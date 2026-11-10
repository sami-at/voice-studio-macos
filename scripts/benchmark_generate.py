"""ElevenLabs benchmark: controlled Qwen3 generations on the Whydo flies script.

Writes ONLY to samples/elevenlabs-benchmark/experiments/. It never touches
local_data/, the voice library, or any existing take. Resumable: finished files are kept.

Experiments (Hal, Qwen3-TTS, fixed seeds, one take per input, no retry selection):

  baseline-sections    the app's own split (8 paragraph sections) and current reference
  one-pass             the whole script as a single generation
  per-sentence         every sentence generated on its own (9 takes)
  ref-opening          reference = first 10.9 s of Hal's original (the question + walk-in)
  ref-full             reference = all 24 s of Hal's original
  seed-sweep-open      opening question, Energetic settings, 8 seeds

Usage: benchmark_generate.py <experiment> [<experiment> ...]
"""
import json, os, sys, time, resource
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from voice_studio.config import offline_environment
os.environ.update(offline_environment())
from voice_studio import engines, styles
from voice_studio.audio import RATE, conditioned_reference, prepare_reference
from voice_studio.storage import atomic_json
import soundfile as sf
import mlx.core as mx

OUT = ROOT / 'samples/elevenlabs-benchmark/experiments'
HAL = ROOT / 'local_data/voices/a482b4beff9049f995f2d959e89d922d'
ORIGINAL = HAL / '117ff54cf5fa449d9721133610d7ec7e/original.mp3'
CURRENT_REF = HAL / '117ff54cf5fa449d9721133610d7ec7e/reference.wav'
CURRENT_TEXT = json.loads((HAL / 'profile.json').read_text())['transcript']

SENTENCES = [
    "Have you ever wondered why do flies rub their hands together like they're planning something?",
    "You might have noticed that whenever a fly lands, it starts rubbing its front legs together.",
    "It looks a little suspicious, but there's actually an interesting reason behind it.",
    "Flies spend a surprising amount of time cleaning themselves.",
    "And that's because they have tiny taste receptors on their feet, allowing them to taste whatever they land on.",
    "So when a fly walks across your food, it can actually taste it without even using its mouth.",
    "But dirt and dust can interfere with those receptors, which is why flies regularly rub their legs together to keep them clean.",
    "So no, flies aren't secretly planning anything.",
    "They're just keeping their taste receptors clean.",
]
# The app's own paragraph split of the script (scripts/final_quality_generate.py used the same).
SECTIONS = [SENTENCES[0], SENTENCES[1], SENTENCES[2], SENTENCES[3], SENTENCES[4], SENTENCES[5],
            SENTENCES[6], SENTENCES[7] + ' ' + SENTENCES[8]]
OPENING_TEXT = ("Have you ever wondered why do we suddenly forget what we were about to say? "
                "You walk into a room, stop for a second, and realize you have absolutely no idea "
                "why you're there.")
FULL_TEXT = OPENING_TEXT + (" Surprisingly, this happens because your brain sometimes treats walking "
                            "through a doorway as the beginning of a new event. That change can "
                            "interrupt your short-term memory, making you forget what you were "
                            "thinking about just seconds earlier.")


def reference(kind, tempo):
    folder = OUT / 'references' / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'reference.wav'
    if kind == 'current':
        text = CURRENT_TEXT
        if not path.exists():
            import shutil
            shutil.copy2(CURRENT_REF, path)
    elif kind == 'opening':
        text = OPENING_TEXT
        if not path.exists():
            prepare_reference(ORIGINAL, path, start=0.0, duration=10.9)
    elif kind == 'full':
        text = FULL_TEXT
        if not path.exists():
            prepare_reference(ORIGINAL, path, start=0.0, duration=24.3)
    else:
        raise ValueError(kind)
    return conditioned_reference(path, tempo, folder), text


def run(host, name, jobs, ref_kind='current', style=styles.NATURAL, seeds=None):
    values = styles.settings(style)
    ref, ref_text = reference(ref_kind, values['reference_tempo'])
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    for i, text in enumerate(jobs):
        seed = (seeds[i] if seeds else 42 + i)
        raw = folder / f'{i + 1:02d}-raw.wav'
        meta = raw.with_suffix('.json')
        if raw.exists() and meta.exists():
            continue
        started = time.monotonic()
        audio = host.synthesize(engines.QWEN, text, ref, ref_text, seed, {}, RATE)
        sf.write(raw, audio, RATE, subtype='FLOAT')
        atomic_json(meta, {
            'experiment': name, 'text': text, 'seed': seed, 'engine': engines.QWEN,
            'style': style, 'settings': values, 'reference': ref_kind,
            'seconds': round(len(audio) / RATE, 3),
            'generation_seconds': round(time.monotonic() - started, 2),
            'peak_mlx_gb': round(mx.get_peak_memory() / 1e9, 3),
            'peak_rss_gb': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9, 3)})
        print(name, raw.name, round(len(audio) / RATE, 2), 's audio,',
              round(time.monotonic() - started, 1), 's', flush=True)
        del audio
        mx.clear_cache()


EXPERIMENTS = {
    'baseline-sections': lambda h: run(h, 'baseline-sections', SECTIONS),
    'one-pass': lambda h: run(h, 'one-pass', [' '.join(SENTENCES)], seeds=[42]),
    'per-sentence': lambda h: run(h, 'per-sentence', SENTENCES),
    'ref-opening': lambda h: run(h, 'ref-opening', SECTIONS, ref_kind='opening'),
    'ref-full': lambda h: run(h, 'ref-full', SECTIONS, ref_kind='full'),
    'seed-sweep-open': lambda h: run(h, 'seed-sweep-open', [SENTENCES[0]] * 8,
                                     style=styles.ENERGETIC,
                                     seeds=[1996 + 11 * n for n in range(8)]),
}

if __name__ == '__main__':
    wanted = sys.argv[1:] or list(EXPERIMENTS)
    host = engines.EngineHost(emit=lambda kind, **v: print(kind, v, flush=True))
    for name in wanted:
        EXPERIMENTS[name](host)
    host.release()
    print('done', flush=True)
