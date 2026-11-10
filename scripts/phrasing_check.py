"""Before-and-after phrasing comparison, from identical speech.

Sections are generated once, then assembled twice: with the previous rules and with the
current ones. The speech is byte-identical between the two, so every difference you hear
is the phrasing change and nothing else. Both versions are written to samples/comparison
for listening, and both are transcribed back to prove no words were lost.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np
import soundfile as sf
from voice_studio import styles, verify
from voice_studio.audio import RATE, export_audio, join_segments
from voice_studio.config import DATA, initialize, offline_environment
from voice_studio.storage import atomic_json, profiles, read_json, save_session, session_path
from voice_studio.text import new_session

OUT = ROOT / 'samples' / 'comparison'
# Questions, a surprising fact, an explanation, long and short sentences, and endings on
# a range of consonants and vowels.
SCRIPT = (
    "Why do we forget what we were about to say? You walk into a room, stop for a second, "
    "and realise you have absolutely no idea why you are there.\n\n"
    "Surprisingly, this happens because your brain treats a doorway as the start of a new "
    "event. The old room is filed away, and the thought you were holding goes with it. "
    "That is why it feels like the idea simply vanished.\n\n"
    "There is a fix, and it is almost too simple. Say the thing out loud before you move. "
    "The words survive the doorway, and so does the thought. The experiment is over."
)
# The pause values that shipped before this change, for an honest comparison.
OLD = {'Natural': {'pause': 0.30, 'sentence_pause': 0.10},
       'Energetic Explainer': {'pause': 0.18, 'sentence_pause': 0.06}}


def worker(job, name, timeout=3600):
    request = DATA / 'jobs' / (name + '.json')
    atomic_json(request, job)
    result = subprocess.run([sys.executable, '-u', '-m', 'voice_studio.worker', str(request)],
                            cwd=ROOT, env={**os.environ, **offline_environment()},
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        print(result.stderr[-3000:], flush=True)
        raise RuntimeError(f'{name} failed ({result.returncode})')
    return [json.loads(l[9:]) for l in result.stdout.splitlines() if l.startswith('VS_EVENT ')]


def heard(path):
    events = worker({'action': 'transcribe', 'source': str(path)}, 'phrasing-transcribe', 900)
    return next(e['text'] for e in events if e['kind'] == 'transcript')


def join_the_old_way(session, data, destination):
    """The previous assembly: whole segment files, a flat pause, nothing at either end."""
    with sf.SoundFile(destination, 'w', samplerate=RATE, channels=1, subtype='PCM_24') as out:
        for i, segment in enumerate(session['segments']):
            with sf.SoundFile(Path(data) / segment['file']) as source:
                for block in source.blocks(blocksize=65536, dtype='float32'):
                    out.write(block)
            if i < len(session['segments']) - 1:
                pause = (session['pause'] if segment.get('paragraph_end')
                         else session.get('sentence_pause', .10))
                out.write(np.zeros(int(RATE * max(0, pause)), dtype=np.float32))
    return sf.info(destination).duration


def silence_profile(path, threshold=0.012, shortest=0.02):
    audio, rate = sf.read(path, dtype='float32')
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    loud = np.flatnonzero(np.abs(audio) > threshold)
    leading = loud[0] / rate
    trailing = (len(audio) - loud[-1] - 1) / rate
    gaps, count = [], 0
    for quiet in np.abs(audio[loud[0]:loud[-1] + 1]) <= threshold:
        if quiet:
            count += 1
        elif count:
            if count / rate >= shortest:
                gaps.append(round(count / rate, 3))
            count = 0
    return leading, gaps, trailing


def main():
    initialize()
    OUT.mkdir(parents=True, exist_ok=True)
    voices = {p['name']: p for p in profiles() if p['name'] in ('Mike', 'Hal')}
    report = {'script': SCRIPT, 'cases': {}}

    for name, profile in voices.items():
        for style in (styles.NATURAL, styles.ENERGETIC):
            label = f'{name}-{style.split()[0]}'
            session = new_session(SCRIPT, f'Phrasing {label}', profile, style)
            save_session(session)
            worker({'action': 'generate', 'session': str(session_path(session))},
                   f'test-phrasing-{label.lower()}')
            session = read_json(session_path(session))
            assert session['output'], f'{label} produced no narration'

            after = OUT / f'{label}-after.wav'
            join_segments(session, DATA, after)
            # Same sections, previous assembly rules and previous pause values.
            old_session = dict(session, **OLD[style])
            before = OUT / f'{label}-before.wav'
            join_the_old_way(old_session, DATA, before)

            row = {'style': style, 'voice': name, 'sections': len(session['segments'])}
            for tag, path in (('before', before), ('after', after)):
                lead, gaps, trail = silence_profile(path)
                check = verify.compare(SCRIPT, heard(path))
                row[tag] = {'seconds': round(sf.info(path).duration, 2),
                            'lead_silence_ms': round(lead * 1000, 1),
                            'tail_room_ms': round(trail * 1000, 1),
                            'gaps_ms': [round(g * 1000) for g in gaps],
                            'complete': check['ok'], 'coverage': check['coverage']}
                export_audio(path, OUT / f'{label}-{tag}.mp3')
            report['cases'][label] = row
            print(f'  {label}', flush=True)
            for tag in ('before', 'after'):
                r = row[tag]
                print(f"    {tag:6s} {r['seconds']:6.2f}s  lead={r['lead_silence_ms']:5.1f}ms  "
                      f"tail_room={r['tail_room_ms']:6.1f}ms  gaps={r['gaps_ms']}  "
                      f"complete={r['complete']} cov={r['coverage']}", flush=True)

    atomic_json(ROOT / 'docs' / 'phrasing-results.json', report)
    broken = [k for k, v in report['cases'].items() if not v['after']['complete']]
    print(f'\n  files for listening: {OUT.relative_to(ROOT)}', flush=True)
    print(f'  incomplete after the change: {len(broken)} {broken}', flush=True)
    raise SystemExit(1 if broken else 0)


if __name__ == '__main__':
    main()
