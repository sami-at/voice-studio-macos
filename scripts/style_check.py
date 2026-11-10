"""Generate the same script in each narration style and measure what actually differs."""
import json
import os
from pathlib import Path
import statistics as st
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np
import soundfile as sf
from voice_studio import styles
from voice_studio.config import DATA, initialize, offline_environment
from voice_studio.storage import atomic_json, profiles, read_json, save_session, session_path
from voice_studio.text import new_session

SCRIPT = ("Most people never notice this, but the human eye blinks far less when you stare at a "
          "screen. That single habit is why your eyes feel dry at the end of a long day.\n\n"
          "There is a simple fix. Every twenty minutes, look at something twenty feet away for "
          "twenty seconds. Your eyes reset, and the strain fades before it builds.")
WORDS = len(SCRIPT.split())
RATE = 24000
COMPARE = [styles.NATURAL, styles.ENERGETIC, styles.DOCUMENTARY]


def f0_track(x, sr=RATE, fmin=70, fmax=350):
    n, h = int(0.04 * sr), int(0.01 * sr)
    lo, hi = int(sr / fmax), int(sr / fmin)
    out = []
    for i in range(0, max(0, len(x) - n), h):
        fr = x[i:i + n].astype(np.float64)
        if np.sqrt(np.mean(fr ** 2)) < 0.02:
            continue
        fr -= fr.mean()
        ac = np.correlate(fr, fr, 'full')[n - 1:]
        if ac[0] <= 0 or hi >= len(ac):
            continue
        k = int(np.argmax(ac[lo:hi])) + lo
        if ac[k] / ac[0] < 0.3:
            continue
        out.append(sr / k)
    return np.array(out)


def measure(path):
    x, sr = sf.read(path, dtype='float32')
    if x.ndim > 1:
        x = x.mean(axis=1)
    n, h = int(0.04 * sr), int(0.01 * sr)
    rms = np.array([np.sqrt(np.mean(x[i:i + n] ** 2)) for i in range(0, max(0, len(x) - n), h)])
    quiet = rms <= 0.02
    gaps, run = [], 0
    for q in quiet:
        if q:
            run += 1
        elif run:
            gaps.append(run * 0.01)
            run = 0
    f0 = f0_track(x, sr)
    seconds = len(x) / sr
    out = {'seconds': round(seconds, 2), 'words_per_sec': round(WORDS / seconds, 2),
           'silences_over_200ms': sum(1 for g in gaps if g >= 0.2),
           'longest_silence': round(max(gaps), 2) if gaps else 0.0}
    if len(f0) > 10:
        semis = 12 * np.log2(f0 / np.median(f0))
        out['f0_median_hz'] = round(float(np.median(f0)), 1)
        out['f0_spread_semitones'] = round(float(np.std(semis)), 2)
    return out


def worker(job, name):
    request = DATA / 'jobs' / (name + '.json')
    atomic_json(request, job)
    result = subprocess.run([sys.executable, '-u', '-m', 'voice_studio.worker', str(request)],
                            cwd=ROOT, env={**os.environ, **offline_environment()},
                            capture_output=True, text=True, timeout=2400)
    (ROOT / 'docs' / (name + '.log')).write_text(result.stdout + '\nSTDERR:\n' + result.stderr)
    if result.returncode:
        print(result.stderr[-5000:], flush=True)
        raise RuntimeError(f'{name} failed ({result.returncode})')
    return [json.loads(l[9:]) for l in result.stdout.splitlines() if l.startswith('VS_EVENT ')]


def main():
    initialize()
    profile = next(p for p in profiles() if p['name'].startswith('Demo'))
    report = {'script_words': WORDS, 'voice': profile['name'], 'styles': {}}

    for style in COMPARE:
        session = new_session(SCRIPT, f'Style check · {style}', profile, style)
        save_session(session)
        start = time.monotonic()
        events = worker({'action': 'generate', 'session': str(session_path(session))},
                        'test-style-' + style.split()[0].lower())
        session = read_json(session_path(session))
        assert session['output'], f'{style} produced no narration'
        output = DATA / session['output']
        row = measure(output)
        row.update(settings=styles.settings(style),
                   sections=len(session['segments']),
                   generation_seconds=round(sum(s['generation_seconds'] for s in session['segments']), 1),
                   wall_seconds=round(time.monotonic() - start, 1),
                   peak_memory_gb=next(e['peak_memory_gb'] for e in events if e['kind'] == 'metrics'),
                   session_id=session['id'], output=str(output.relative_to(ROOT)))
        # Each style must still be fully intelligible, not just different.
        transcript_events = worker({'action': 'transcribe', 'source': str(output)},
                                   'test-style-transcript')
        row['transcription'] = next(e['text'] for e in transcript_events if e['kind'] == 'transcript')
        spoken = set(row['transcription'].lower().replace(',', '').replace('.', '').split())
        wanted = set(SCRIPT.lower().replace(',', '').replace('.', '').replace('\n', ' ').split())
        row['words_recovered'] = round(len(spoken & wanted) / len(wanted), 3)
        report['styles'][style] = row
        print(style, json.dumps({k: row[k] for k in
              ('seconds', 'words_per_sec', 'silences_over_200ms', 'longest_silence',
               'words_recovered', 'generation_seconds', 'peak_memory_gb')}), flush=True)

    natural, energetic = report['styles'][styles.NATURAL], report['styles'][styles.ENERGETIC]
    report['energetic_vs_natural'] = {
        'words_per_sec_gain_pct': round((energetic['words_per_sec'] / natural['words_per_sec'] - 1) * 100, 1),
        'seconds_saved': round(natural['seconds'] - energetic['seconds'], 2),
        'longest_silence_delta': round(energetic['longest_silence'] - natural['longest_silence'], 2),
    }
    # Exporting a styled narration must keep working in both formats.
    source = DATA / read_json(session_path({'id': energetic['session_id']}))['output']
    for extension in ('wav', 'mp3'):
        destination = ROOT / 'samples' / f'style-energetic-demo.{extension}'
        worker({'action': 'export', 'source': str(source), 'destination': str(destination)},
               'test-style-export-' + extension)
        report.setdefault('exports', {})[extension] = {
            'file': str(destination.relative_to(ROOT)),
            'seconds': round(sf.info(destination).duration, 2) if extension == 'wav' else None,
            'bytes': destination.stat().st_size}
    atomic_json(ROOT / 'docs' / 'style-results.json', report)
    print(json.dumps(report['energetic_vs_natural'], indent=2), flush=True)


if __name__ == '__main__':
    main()
