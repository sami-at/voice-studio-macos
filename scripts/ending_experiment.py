"""Where are final words lost? Reproduce takes, capture the codec codes, decode them two ways.

Qwen3 only, one model, the app's admission check before loading, self-monitored memory.
Writes only to samples/endings/experiments/. Never touches local_data/.

  python scripts/ending_experiment.py reproduce   # selected takes of the latest narration, same seeds
"""
import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from voice_studio.config import DATA, offline_environment
os.environ.update(offline_environment())
from voice_studio import engines, resources, styles, storage
from voice_studio.audio import RATE, conditioned_reference
import numpy as np
import soundfile as sf
import mlx.core as mx

OUT = ROOT / 'samples/endings/experiments'
LIMIT_GB = 6.0   # Chatterbox's hard limit in the app policy; Qwen3 stays far below


def guard():
    used = (mx.get_active_memory() + mx.get_cache_memory()) / 1e9
    free = resources.free_percent()
    if used > LIMIT_GB or (free is not None and free < 8):
        sys.exit(f'STOPPED: MLX {used:.2f} GB, available {free} %')


def generate_with_codes(model, text, ref, ref_text, seed):
    """Same call as EngineHost.synthesize, plus a copy of every code chunk the streaming decoder receives."""
    from mlx_audio.tts.models.qwen3_tts.speech_tokenizer import Qwen3TTSSpeechTokenizerDecoder as Decoder
    captured, original = [], Decoder.streaming_step     # the loaded decoder is mx.compile-wrapped; patch its class

    def recording(self, codes):
        captured.append(np.array(codes))
        guard()
        return original(self, codes)
    Decoder.streaming_step = recording
    try:
        mx.random.seed(seed)
        chunks = [np.asarray(r.audio.astype(mx.float32)).reshape(-1) for r in model.generate(
            text=text, ref_audio=str(ref), ref_text=ref_text, lang_code='english', max_tokens=900, verbose=False,
            stream=True, streaming_interval=2.0, **styles.SAMPLING)]
    finally:
        Decoder.streaming_step = original
    codes = np.concatenate(captured, axis=-1)            # [1, groups, frames]
    return np.concatenate(chunks), codes


def full_decode(model, codes):
    """The non-streaming decoder on exactly the same codes."""
    decoder = model.speech_tokenizer.decoder
    decoder.reset_streaming_state()
    wav = decoder(mx.array(codes))
    mx.eval(wav)
    return np.asarray(wav.astype(mx.float32)).reshape(-1)


def reproduce():
    session = storage.read_json(DATA / 'sessions/f516b218580e40819dbf3db4d2b6fc15/project.json')
    values = styles.settings(session['style'], session.get('settings'))
    reference = conditioned_reference(DATA / session['reference'], values['reference_tempo'], (DATA / session['reference']).parent)
    host = engines.EngineHost(emit=lambda kind, **k: print(kind, k, flush=True))
    host.before_load = lambda engine: resources.admission([engine], resources.snapshot(DATA))[0] == resources.ADMIT
    model = host.load(engines.QWEN)
    OUT.mkdir(parents=True, exist_ok=True)
    report = []
    for index in (1, 4, 5, 7, 2, 9):                     # sections 2, 5, 6, 8, 3, 10 (mix of cut and natural endings)
        seg = session['segments'][index]
        take = storage.selected_take(seg)
        stored = sf.read(DATA / take['raw_file'], dtype='float32')[0]
        start = time.monotonic()
        streamed, codes = generate_with_codes(model, seg['text'], reference, session['transcript'], take['seed'])
        full = full_decode(model, codes)
        name = f'sec{index + 1:02d}'
        sf.write(OUT / f'{name}-streamed.wav', streamed, RATE, subtype='FLOAT')
        sf.write(OUT / f'{name}-fulldecode.wav', full, RATE, subtype='FLOAT')
        np.save(OUT / f'{name}-codes.npy', codes)
        n = min(len(stored), len(streamed))
        row = {'section': index + 1, 'text': seg['text'], 'seed': take['seed'], 'frames': int(codes.shape[-1]),
               'reproduced_exactly': bool(len(stored) == len(streamed) and np.array_equal(stored, streamed)),
               'max_diff_vs_stored': float(np.max(np.abs(stored[:n] - streamed[:n]))),
               'streamed_s': round(len(streamed) / RATE, 3), 'full_s': round(len(full) / RATE, 3),
               'seconds': round(time.monotonic() - start, 1),
               'mlx_peak_gb': round(mx.get_peak_memory() / 1e9, 2), 'free_percent': resources.free_percent()}
        report.append(row)
        print(row, flush=True)
        mx.clear_cache()
    host.release()
    (OUT / 'reproduce.json').write_text(json.dumps(report, indent=1))


WORDS = ["The mystery is finally over.", "Flies live all over the world.", "Every fly is a little bit different.",
         "Now you finally understand.", "They look like they're planning something.", "They're just keeping their feet clean.",
         "Well, it turns out they're actually cleaning themselves.",
         "So when a fly walks across your food, it's already tasting it without even opening its mouth.",
         "But there's a catch.",
         "That's why they constantly rub their legs together, brushing away tiny particles to keep their taste receptors working properly."]


def cliff_db(x):
    n = 120; k = len(x) // n
    e = 10 * np.log10(np.mean(x[:k * n].astype(np.float64).reshape(k, n) ** 2, axis=1) + 1e-20)
    live = np.flatnonzero(e > -60)
    j = live[-1]
    if j + 1 >= len(e):
        return 99.0
    return float(max([e[i] - e[i + 1] for i in range(max(1, j - 60), min(len(e) - 1, j + 2))
                      if e[i] > -60 and e[i + 1] < -80] or [0.0]))


def sweep():
    session = storage.read_json(DATA / 'sessions/f516b218580e40819dbf3db4d2b6fc15/project.json')
    base_ref = DATA / session['reference']
    host = engines.EngineHost(emit=lambda kind, **k: print(kind, k, flush=True))
    host.before_load = lambda engine: resources.admission([engine], resources.snapshot(DATA))[0] == resources.ADMIT
    host.load(engines.QWEN)
    folder = OUT / 'sweep'
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for cond, style, suffix in (('natural', styles.NATURAL, ''), ('natural-newline', styles.NATURAL, '\n'),
                                ('energetic', styles.ENERGETIC, '')):
        ref = conditioned_reference(base_ref, styles.settings(style)['reference_tempo'], base_ref.parent)
        for w, text in enumerate(WORDS):
            for seed in range(42, 47):
                path = folder / f'{cond}-{w:02d}-{seed}.wav'
                if path.exists():
                    x = sf.read(path, dtype='float32')[0]
                else:
                    guard()
                    x = host.synthesize(engines.QWEN, text + suffix, ref, session['transcript'], seed, {}, RATE)
                    sf.write(path, x, RATE, subtype='FLOAT')
                    mx.clear_cache()
                rows.append({'cond': cond, 'text': text, 'seed': seed, 'cliff_db': round(cliff_db(x), 1)})
        cut = [r for r in rows if r['cond'] == cond and r['cliff_db'] >= 30]
        print(cond, f'{len(cut)} of {len(WORDS) * 5} takes end with a cut', 'peak', round(mx.get_peak_memory() / 1e9, 2),
              'GB, available', resources.free_percent(), '%', flush=True)
    host.release()
    (OUT / 'sweep.json').write_text(json.dumps(rows, indent=1))


def chatterbox():
    """The sentences Qwen3 kept cutting, with Chatterbox (justified by the sweep), three seeds each."""
    from voice_studio.audio import ending_stop
    session = storage.read_json(DATA / 'sessions/f516b218580e40819dbf3db4d2b6fc15/project.json')
    values = styles.settings(session['style'], session.get('settings'))
    ref = conditioned_reference(DATA / session['reference'], values['reference_tempo'], (DATA / session['reference']).parent)
    host = engines.EngineHost(emit=lambda kind, **k: print(kind, k, flush=True))
    host.before_load = lambda engine: resources.admission([engine], resources.snapshot(DATA))[0] == resources.ADMIT
    folder = OUT / 'chatterbox'
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for w in (7, 8, 5):
        for seed in (42, 43, 44):
            path = folder / f'chatterbox-{w:02d}-{seed}.wav'
            if not path.exists():
                guard()
                x = host.synthesize(engines.CHATTERBOX, WORDS[w], ref, session['transcript'], seed, {}, RATE)
                sf.write(path, x, RATE, subtype='FLOAT')
                mx.clear_cache()
            x = sf.read(path, dtype='float32')[0]
            stop, fall = ending_stop(x)
            rows.append({'text': WORDS[w], 'seed': seed, 'stop_rel_db': round(stop, 1), 'cut': stop > -27})
            print(rows[-1], 'peak', round(mx.get_peak_memory() / 1e9, 2), 'GB available', resources.free_percent(), flush=True)
    host.release()
    (OUT / 'chatterbox.json').write_text(json.dumps(rows, indent=1))


if __name__ == '__main__':
    {'reproduce': reproduce, 'sweep': sweep, 'chatterbox': chatterbox}[sys.argv[1]]()
