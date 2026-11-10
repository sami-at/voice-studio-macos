"""Generate one script in several voices and check each one cloned the right reference.

Distinguishable is not enough on its own: a voice could sound different because generation
wandered. So each result is also matched back against every reference, and the right one
has to win.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import numpy as np
import soundfile as sf
from style_check import f0_track
from voice_studio import styles
from voice_studio.config import DATA, initialize, offline_environment
from voice_studio.storage import atomic_json, has_reference, profiles, read_json, save_session, session_path
from voice_studio.text import new_session

SCRIPT = ('Here is something most people get wrong. The brain does not store a memory in one '
          'place. It rebuilds it every single time you remember it.')
VOICES = ['Mike', 'Hal']


def fingerprint(path):
    """Long-term average spectrum over voiced frames: a crude but stable voice timbre print."""
    x, sr = sf.read(path, dtype='float32')
    if x.ndim > 1:
        x = x.mean(axis=1)
    n, h = 1024, 256
    window = np.hanning(n)
    frames = [x[i:i + n] * window for i in range(0, max(0, len(x) - n), h)]
    frames = [f for f in frames if np.sqrt(np.mean(f ** 2)) > 0.02]
    if len(frames) < 10:
        raise ValueError(f'not enough voiced audio in {path}')
    spectrum = np.mean([np.abs(np.fft.rfft(f)) for f in frames], axis=0)
    # Restrict to the band that carries voice identity, then work in dB and normalise.
    freqs = np.fft.rfftfreq(n, 1 / sr)
    band = (freqs >= 80) & (freqs <= 8000)
    db = 20 * np.log10(spectrum[band] + 1e-9)
    db -= db.mean()
    return db / (np.linalg.norm(db) + 1e-9)


def voice_stats(path):
    f0 = f0_track(*sf_mono(path))
    out = {}
    if len(f0) > 10:
        out['f0_median_hz'] = round(float(np.median(f0)), 1)
        out['f0_spread_semitones'] = round(float(np.std(12 * np.log2(f0 / np.median(f0)))), 2)
    return out


def sf_mono(path):
    x, sr = sf.read(path, dtype='float32')
    if x.ndim > 1:
        x = x.mean(axis=1)
    return x, sr


def worker(job, name):
    request = DATA / 'jobs' / (name + '.json')
    atomic_json(request, job)
    result = subprocess.run([sys.executable, '-u', '-m', 'voice_studio.worker', str(request)],
                            cwd=ROOT, env={**os.environ, **offline_environment()},
                            capture_output=True, text=True, timeout=2400)
    (ROOT / 'docs' / (name + '.log')).write_text(result.stdout + '\nSTDERR:\n' + result.stderr)
    if result.returncode:
        print(result.stderr[-4000:], flush=True)
        raise RuntimeError(f'{name} failed ({result.returncode})')
    return [json.loads(l[9:]) for l in result.stdout.splitlines() if l.startswith('VS_EVENT ')]


def main():
    initialize()
    available = {p['name']: p for p in profiles() if has_reference(p)}
    missing = [v for v in VOICES if v not in available]
    assert not missing, f'missing voices: {missing}'
    report = {'script': SCRIPT, 'voices': {}}

    for name in VOICES:
        profile = available[name]
        before = read_json(DATA / 'voices' / profile['id'] / 'profile.json')
        session = new_session(SCRIPT, f'Voice check · {name}', profile,
                              profile.get('style', styles.ENERGETIC))
        save_session(session)
        start = time.monotonic()
        events = worker({'action': 'generate', 'session': str(session_path(session))},
                        'test-voice-' + name.lower())
        session = read_json(session_path(session))
        assert session['output'], f'{name} produced no narration'
        output = DATA / session['output']

        transcript_events = worker({'action': 'transcribe', 'source': str(output)},
                                   'test-voice-transcript')
        heard = next(e['text'] for e in transcript_events if e['kind'] == 'transcript')

        after = read_json(DATA / 'voices' / profile['id'] / 'profile.json')
        report['voices'][name] = {
            'style': session['style'],
            'reference': profile['reference'],
            'reference_seconds': round(profile['seconds'], 2),
            'transcript': profile['transcript'],
            'session_id': session['id'],
            'output': str(output.relative_to(ROOT)),
            'seconds': round(sf.info(output).duration, 2),
            'generation_seconds': round(sum(s['generation_seconds'] for s in session['segments']), 1),
            'peak_memory_gb': next(e['peak_memory_gb'] for e in events if e['kind'] == 'metrics'),
            'wall_seconds': round(time.monotonic() - start, 1),
            'transcription': heard,
            'profile_unchanged_by_generation': before == after,
            **voice_stats(output),
        }
        print(name, json.dumps({k: report['voices'][name][k] for k in
              ('seconds', 'f0_median_hz', 'generation_seconds', 'peak_memory_gb',
               'profile_unchanged_by_generation')}), flush=True)

    # Does each result sound like its own reference rather than the other one?
    prints = {}
    for name in VOICES:
        prints[f'ref:{name}'] = fingerprint(DATA / available[name]['reference'])
        prints[f'gen:{name}'] = fingerprint(ROOT / report['voices'][name]['output'])
    matches = {}
    for name in VOICES:
        scores = {other: round(float(np.dot(prints[f'gen:{name}'], prints[f'ref:{other}'])), 4)
                  for other in VOICES}
        best = max(scores, key=scores.get)
        matches[name] = {'similarity_to_each_reference': scores, 'closest_reference': best,
                         'matched_own_reference': best == name}
        print(f'  {name} generated -> closest reference: {best}  {scores}', flush=True)
    report['reference_matching'] = matches

    a, b = VOICES[0], VOICES[1]
    report['distinguishable'] = {
        'generated_similarity': round(float(np.dot(prints[f'gen:{a}'], prints[f'gen:{b}'])), 4),
        'reference_similarity': round(float(np.dot(prints[f'ref:{a}'], prints[f'ref:{b}'])), 4),
        'f0_median_difference_hz': round(abs(report['voices'][a].get('f0_median_hz', 0)
                                             - report['voices'][b].get('f0_median_hz', 0)), 1),
        'all_matched_own_reference': all(m['matched_own_reference'] for m in matches.values()),
    }
    atomic_json(ROOT / 'docs' / 'voice-results.json', report)
    print(json.dumps(report['distinguishable'], indent=2), flush=True)


if __name__ == '__main__':
    main()
