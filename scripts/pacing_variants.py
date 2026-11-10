"""Chatterbox Energetic Explainer pacing variants, built from SAVED raw takes (no model runs). Stage A only.

Every variant uses the app's own write_segment (pitch-preserving tempo) and join_segments (assembly).
Writes only to samples/pacing/. The projects and takes are not modified.
"""
import json, shutil, sys, tempfile
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
from voice_studio import audio as A, storage, styles  # noqa: E402
from benchmark_audio import active_span, load, matched  # noqa: E402

OUT = ROOT / 'samples/pacing'
CHATTERBOX = 'c40802daa3454d178af2bb2c1fc3e48e'
QWEN = 'a617e891c6c645bb993e041938177b41'
DECAY_FLOOR = 10 ** (-60 / 20)      # below -60 dBFS the decay is over; what follows at ~-90 dB is dead air
TAIL_GUARD_S = 0.12                 # kept after the decay ends, so nothing audible is touched


def trim_dead_air(x, rate=A.RATE):
    """Keep everything up to the end of the audible decay plus a guard; drop only the near-silent remainder."""
    n = int(rate * .01)
    k = len(x) // n
    rms = np.sqrt(np.mean(np.square(x[:k * n].astype(np.float64)).reshape(k, n), axis=1))
    loud = np.flatnonzero(rms > DECAY_FLOOR)
    if not len(loud):
        return x, 0.0
    end = min(len(x), (loud[-1] + 1) * n + int(TAIL_GUARD_S * rate))
    return x[:end], (len(x) - end) / rate


VARIANTS = {   # name: (extra speed on top of the style, trim dead air)
    'chatterbox-original': (1.00, False),
    'chatterbox-speed-105': (1.05, False),
    'chatterbox-speed-110': (1.10, False),
    'chatterbox-speed-115': (1.15, False),
    'chatterbox-pauses': (1.00, True),
    'chatterbox-pauses-speed-105': (1.05, True),
    'chatterbox-pauses-speed-110': (1.10, True),
}


def build():
    D = storage.DATA
    session = storage.read_json(D / 'sessions' / CHATTERBOX / 'project.json')
    values = styles.settings(session['style'], session.get('settings'))
    report = {}
    for name, (extra, trim) in VARIANTS.items():
        folder = OUT / 'work' / name
        shutil.rmtree(folder, ignore_errors=True); folder.mkdir(parents=True)
        segments, removed = [], 0.0
        for i, g in enumerate(session['segments']):
            take = storage.selected_take(g)
            raw = sf.read(D / take['raw_file'], dtype='float32')[0]
            if trim:
                raw, cut = trim_dead_air(raw)
                removed += cut
            path = folder / f'{i + 1:02d}.wav'
            A.write_segment(raw, path, round(values['speed'] * extra, 4))
            segments.append({'file': str(path), 'text': g['text'], 'paragraph_end': g.get('paragraph_end', True),
                             **({'lead_pause': g['lead_pause']} if g.get('lead_pause') is not None else {})})
        target = OUT / 'work' / f'{name}.wav'
        A.join_segments({'segments': segments, 'pause': values['pause'], 'sentence_pause': values['sentence_pause']},
                        folder, target)
        report[name] = {'extra_speed': extra, 'final_speed': round(values['speed'] * extra, 3), 'trim_dead_air': trim,
                        'dead_air_removed_s': round(removed, 2), 'seconds': round(sf.info(target).duration, 2)}
        print(name, report[name], flush=True)
    for name, sid in (('qwen3-original', QWEN), ('chatterbox-app-original', CHATTERBOX)):
        s = storage.read_json(D / 'sessions' / sid / 'project.json')
        shutil.copyfile(D / s['output'], OUT / 'work' / f'{name}.wav')
    (OUT / 'variants.json').write_text(json.dumps(report, indent=1))


if __name__ == '__main__':
    build()
