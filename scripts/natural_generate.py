"""Natural-narration upgrade: controlled Qwen3 generations that test genuine control levers.

Writes only to samples/natural-upgrade/experiments/. Never touches local_data/.

  delivery-ref   three reference windows of Hal's original x three sentence types x five seeds
  chain          each sentence conditioned on the previous generated sentence vs the fixed
                 reference, over a four-sentence run, two seeds
"""
import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from voice_studio.config import offline_environment
os.environ.update(offline_environment())
from voice_studio import engines
from voice_studio.audio import RATE, prepare_reference
from voice_studio.storage import atomic_json
import soundfile as sf
import mlx.core as mx

OUT = ROOT / 'samples/natural-upgrade/experiments'
HAL = ROOT / 'local_data/voices/a482b4beff9049f995f2d959e89d922d'
ORIGINAL = HAL / '117ff54cf5fa449d9721133610d7ec7e/original.mp3'
CALM = HAL / '117ff54cf5fa449d9721133610d7ec7e/reference.wav'
CALM_TEXT = json.loads((HAL / 'profile.json').read_text())['transcript']
QUESTION_TEXT = 'Have you ever wondered why do we suddenly forget what we were about to say?'
OPENING_TEXT = (QUESTION_TEXT + " You walk into a room, stop for a second, and realize you have "
                "absolutely no idea why you're there.")

SENTENCES = {
    'question': "Have you ever wondered why do flies rub their hands together like they're planning something?",
    'explain': "But dirt and dust can interfere with those receptors, which is why flies regularly rub their legs together to keep them clean.",
    'conclude': "So no, flies aren't secretly planning anything. They're just keeping their taste receptors clean.",
}
CHAIN = [
    "Have you ever wondered why do flies rub their hands together like they're planning something?",
    "You might have noticed that whenever a fly lands, it starts rubbing its front legs together.",
    "It looks a little suspicious, but there's actually an interesting reason behind it.",
    "Flies spend a surprising amount of time cleaning themselves.",
]


def references():
    folder = OUT / 'references'
    folder.mkdir(parents=True, exist_ok=True)
    out = {'calm': (CALM, CALM_TEXT)}
    for name, seconds, text in (('question', 4.1, QUESTION_TEXT), ('opening', 10.9, OPENING_TEXT)):
        path = folder / f'{name}.wav'
        if not path.exists():
            prepare_reference(ORIGINAL, path, start=0.0, duration=seconds)
        out[name] = (path, text)
    return out


def take(host, text, ref, ref_text, seed, path, extra):
    if path.exists() and path.with_suffix('.json').exists():
        return
    start = time.monotonic()
    audio = host.synthesize(engines.QWEN, text, ref, ref_text, seed, {}, RATE)
    sf.write(path, audio, RATE, subtype='FLOAT')
    atomic_json(path.with_suffix('.json'), {**extra, 'text': text, 'seed': seed,
                                            'seconds': round(len(audio) / RATE, 3),
                                            'generation_seconds': round(time.monotonic() - start, 2)})
    print(path.name, round(len(audio) / RATE, 2), 's', flush=True)
    mx.clear_cache()


def delivery_ref(host):
    refs = references()
    folder = OUT / 'delivery-ref'
    folder.mkdir(parents=True, exist_ok=True)
    for ref_name, (ref, ref_text) in refs.items():
        for kind, text in SENTENCES.items():
            for seed in range(42, 47):
                take(host, text, ref, ref_text, seed, folder / f'{ref_name}-{kind}-{seed}.wav',
                     {'experiment': 'delivery-ref', 'reference': ref_name, 'kind': kind})


def chain(host):
    """Condition sentence n on sentence n-1's own audio and words; compare with the fixed reference."""
    folder = OUT / 'chain'
    folder.mkdir(parents=True, exist_ok=True)
    refs = references()
    ref, ref_text = refs['calm']
    for seed in (42, 43):
        for i, text in enumerate(CHAIN):
            take(host, text, ref, ref_text, seed, folder / f'fixed-{seed}-{i + 1}.wav',
                 {'experiment': 'chain', 'mode': 'fixed', 'index': i + 1})
        for i, text in enumerate(CHAIN):
            if i == 0:                                    # nothing before it: same as fixed
                prev_ref, prev_text = ref, ref_text
            else:
                previous = folder / f'chained-{seed}-{i}.wav'
                audio, _ = sf.read(previous, dtype='float32')
                prev_ref = folder / f'chained-{seed}-{i}-asref.wav'
                sf.write(prev_ref, audio, RATE, subtype='PCM_16')
                prev_text = CHAIN[i - 1]
            take(host, text, prev_ref, prev_text, seed, folder / f'chained-{seed}-{i + 1}.wav',
                 {'experiment': 'chain', 'mode': 'chained', 'index': i + 1})


if __name__ == '__main__':
    host = engines.EngineHost(emit=lambda kind, **v: print(kind, v, flush=True))
    for name in sys.argv[1:] or ['delivery-ref', 'chain']:
        {'delivery-ref': delivery_ref, 'chain': chain}[name](host)
    host.release()
    print('done', flush=True)
