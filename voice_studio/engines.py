"""The speech engines, behind one interface.

Two engines are available and the choice is always yours, per section. Nothing here
decides which one sounds better; they simply produce audio from the same inputs.

* **Qwen3-TTS** — the original path. Fast (about 1.4x real time), 3.84 GB peak, and it
  conditions on the reference recording *and* its transcript.
* **Chatterbox** — slower (about 9x real time) and 4.51 GB peak. It takes the reference
  recording but no transcript, and has its own ``exaggeration`` setting.

Only one is ever held in memory. ``EngineHost`` keeps the current one loaded while
consecutive sections use it, and releases it before loading the other.
"""
from pathlib import Path

from .config import CHATTERBOX_MODEL, TTS_MODEL

QWEN = 'qwen3'
CHATTERBOX = 'chatterbox'
DEFAULT = QWEN
ORDER = (QWEN, CHATTERBOX)
LANGUAGE_CODES = {'English': 'en', 'French': 'fr', 'Spanish': 'es', 'German': 'de',
                  'Italian': 'it', 'Portuguese': 'pt', 'Chinese': 'zh',
                  'Japanese': 'ja', 'Korean': 'ko', 'Russian': 'ru'}

LABELS = {QWEN: 'Qwen3-TTS', CHATTERBOX: 'Chatterbox v3'}
SUMMARIES = {
    QWEN: 'Fast and well tested. About 1.4x real time.',
    CHATTERBOX: 'A second opinion for a phrase that does not sit right. '
                'Slower than Qwen3. Timbre and accent can differ; compare with the reference.',
}

# Chatterbox's own default is 0.1; 0.5 is its documented middle setting. Measured here it
# did not move pitch range or loudness in a consistent direction, so it is offered as a
# per-take variation to try by ear, not as an expressiveness control.
EXAGGERATION_DEFAULT = 0.5
EXAGGERATION_LIMITS = (0.0, 1.0)

# Classifier-free guidance costs a second forward pass per step. Preserve the existing
# 0.0 setting. The installed Chatterbox implementation ignores streaming arguments;
# do not describe these flags as a measured streaming optimization.
CHATTERBOX_CFG_WEIGHT = 0.0


def label(engine):
    return LABELS.get(engine, LABELS[DEFAULT])


def normalize(engine):
    return engine if engine in ORDER else DEFAULT


def model_path(engine):
    return CHATTERBOX_MODEL if engine == CHATTERBOX else TTS_MODEL


def is_installed(engine):
    return (model_path(engine) / '.complete').exists()


def available():
    """Engines whose weights are actually present, in display order."""
    return [e for e in ORDER if is_installed(e)]


def config_for(engine, requested=None):
    """The stored, validated settings for one engine. Kept with every take."""
    requested = requested or {}
    if engine != CHATTERBOX:
        return {}
    low, high = EXAGGERATION_LIMITS
    try:
        value = float(requested.get('exaggeration', EXAGGERATION_DEFAULT))
    except (TypeError, ValueError):
        value = EXAGGERATION_DEFAULT
    return {'exaggeration': round(min(high, max(low, value)), 3)}


class ResourceWait(Exception):
    """Raised when a model must not be loaded now; nothing has been loaded."""


class EngineHost:
    """Holds at most one model. Switching engines frees the previous one first."""

    def __init__(self, emit=None):
        self.engine = None
        self.model = None
        self._emit = emit or (lambda *a, **k: None)
        self.on_chunk = None
        self.before_load = None             # admission check, called after any release and before loading

    def release(self):
        if self.model is None:
            return
        import mlx.core as mx
        import gc
        self.model = None
        self.engine = None
        gc.collect()  # release reference cycles before another engine is loaded
        mx.clear_cache()

    def load(self, engine):
        engine = normalize(engine)
        if self.engine == engine and self.model is not None:
            return self.model                      # consecutive sections reuse the model
        if self.model is not None:
            self._emit('status', message=f'Switching to {label(engine)}…')
        self.release()
        if self.before_load and not self.before_load(engine):
            raise ResourceWait(engine)
        path = model_path(engine)
        if not (path / '.complete').exists():
            raise RuntimeError(
                f'{label(engine)} is not installed. Run Install Voice Studio.command once, '
                'or choose the other engine for this section.')
        self._emit('status', message=f'Loading {label(engine)} on the Apple GPU…')
        import mlx.core as mx
        from mlx_audio.tts.utils import load_model
        if not mx.metal.is_available():
            raise RuntimeError('Apple Metal is unavailable. Launch Voice Studio in your '
                               'normal macOS desktop session.')
        mx.set_default_device(mx.gpu)
        mx.set_cache_limit(256 * 1024 * 1024)
        model = load_model(str(path))
        if engine == QWEN and (model.tokenizer is None or model.speech_tokenizer is None):
            raise RuntimeError('The model tokenizer could not load. See the diagnostic log '
                               'and rerun the installer to repair model assets.')
        self.model, self.engine = model, engine
        self._emit('loaded', device='Apple Metal (MLX)', engine=engine, model=label(engine))
        return model

    def synthesize(self, engine, text, reference, ref_text, seed, config=None, rate=24000,
                   language='English'):
        """One take. Returns a mono float32 array at `rate`."""
        import numpy as np
        import mlx.core as mx
        from . import styles
        if language not in LANGUAGE_CODES:
            raise ValueError('Choose one of the supported narration languages.')
        model = self.load(engine)
        mx.random.seed(seed)
        if engine == CHATTERBOX:
            # No transcript: Chatterbox conditions on the recording alone. In the
            # installed implementation stream/streaming_interval are accepted but
            # ignored; no memory or speed improvement is claimed for these flags.
            stream = model.generate(
                text=text, ref_audio=str(reference), temperature=0.8,
                cfg_weight=CHATTERBOX_CFG_WEIGHT,
                lang_code=LANGUAGE_CODES[language],
                exaggeration=config_for(CHATTERBOX, config)['exaggeration'],
                stream=True, streaming_interval=2.0, verbose=False)
        else:
            # Streaming keeps the codec's peak memory down; measured 5.38 GB -> 3.84 GB.
            stream = model.generate(
                text=text, ref_audio=str(reference), ref_text=ref_text,
                lang_code=language.lower(), max_tokens=900, verbose=False,
                stream=True, streaming_interval=2.0, **styles.SAMPLING)
        arrays = []
        for result in stream:
            if self.on_chunk:                   # lets the worker report real MLX memory while it runs
                self.on_chunk(mx.get_active_memory() + mx.get_cache_memory())
            if result.sample_rate != rate:
                raise RuntimeError(f'Unexpected model sample rate: {result.sample_rate}')
            arrays.append(np.asarray(result.audio.astype(mx.float32)).reshape(-1))
        if not arrays:
            raise RuntimeError('The model returned no speech. Try a different reference window.')
        audio = np.concatenate(arrays)
        if len(audio) > rate * 70:
            raise RuntimeError('This section exceeded the generation limit. Shorten it and '
                               'regenerate to avoid truncated speech.')
        return audio
