"""Phase 5: does the Voice Direction Language do what the handbook says, on real audio?

Measures the pause actually produced against the pause asked for, checks a pronunciation
override reaches the engine, and confirms completeness is judged against the spoken text
rather than the raw markers. Runs on both engines.
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
from voice_studio import direction, engines, styles, verify
from voice_studio.config import DATA, initialize, offline_environment
from voice_studio.storage import (atomic_json, profiles, read_json, save_session,
                                  segment_needs_audio, session_path, takes_of)
from voice_studio.text import new_session

PLAIN = 'But wait there is actually a scientific reason.'
PAUSED = 'But wait[pause:0.8] there is actually a scientific reason.'
SPOKEN_CHECK = 'Have you ever wondered why flies rub their hands together?'


def worker(job, name, timeout=5400):
    request = DATA / 'jobs' / (name + '.json')
    atomic_json(request, job)
    result = subprocess.run([sys.executable, '-u', '-m', 'voice_studio.worker', str(request)],
                            cwd=ROOT, env={**os.environ, **offline_environment()},
                            capture_output=True, text=True, timeout=timeout)
    (ROOT / 'docs' / (name + '.log')).write_text(result.stdout + '\nSTDERR:\n' + result.stderr)
    if result.returncode:
        print(result.stderr[-2500:], flush=True)
        raise RuntimeError(f'{name} failed ({result.returncode})')
    return [json.loads(l[9:]) for l in result.stdout.splitlines() if l.startswith('VS_EVENT ')]


def heard(path):
    events = worker({'action': 'transcribe', 'source': str(path)}, 'direction-transcribe', 900)
    return next(e['text'] for e in events if e['kind'] == 'transcript')


def longest_gap(path, threshold=0.012, shortest=0.04):
    audio, rate = sf.read(path, dtype='float32')
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    loud = np.flatnonzero(np.abs(audio) > threshold)
    if not len(loud):
        return 0.0
    runs, count = [], 0
    for quiet in np.abs(audio[loud[0]:loud[-1] + 1]) <= threshold:
        if quiet:
            count += 1
        elif count:
            if count / rate >= shortest:
                runs.append(count / rate)
            count = 0
    return round(max(runs), 3) if runs else 0.0


def build(voice, engine, script, title):
    session = new_session(script, title, voice, styles.ENERGETIC, None, 'English', engine)
    save_session(session)
    worker({'action': 'generate', 'session': str(session_path(session)), 'engine': engine},
           'test-direction-' + title.lower().replace(' ', '-').replace('·', ''))
    return read_json(session_path(session))


def main():
    initialize()
    failures, report = [], {}
    hal = next(p for p in profiles() if p['name'] == 'Hal')

    for engine in (engines.QWEN, engines.CHATTERBOX):
        name = engines.label(engine)
        print(f'\n=== {name} ===', flush=True)
        case = {}

        # --- the marker must not be spoken, and must add the silence asked for ---------
        plain = build(hal, engine, PLAIN, f'VDL plain {engine}')
        paused = build(hal, engine, PAUSED, f'VDL paused {engine}')
        plain_out, paused_out = DATA / plain['output'], DATA / paused['output']
        plain_gap, paused_gap = longest_gap(plain_out), longest_gap(paused_out)
        spoken = direction.parse(PAUSED).spoken
        text = heard(paused_out)
        check = verify.compare(spoken, text)
        case['pause'] = {
            'requested': 0.8, 'gap_plain': plain_gap, 'gap_paused': paused_gap,
            'added': round(paused_gap - plain_gap, 3),
            'seconds_plain': round(sf.info(plain_out).duration, 2),
            'seconds_paused': round(sf.info(paused_out).duration, 2),
            'heard': text, 'complete': check['ok'], 'coverage': check['coverage']}
        print(f"  pause: plain gap {plain_gap:.3f}s -> with [pause:0.8] {paused_gap:.3f}s "
              f"(+{paused_gap - plain_gap:.3f}s)  complete={check['ok']}", flush=True)
        if paused_gap < 0.70:
            failures.append(f'{name}: [pause:0.8] produced only {paused_gap:.3f}s of silence')
        if 'pause' in text.lower() or '[' in text:
            failures.append(f'{name}: the pause marker was spoken aloud: {text!r}')
        if not check['ok']:
            failures.append(f'{name}: paused narration incomplete — {verify.describe(check, 0)}')

        # --- a pronunciation override must reach the engine ---------------------------
        script = 'Flies taste with their {tarsi|tar sigh}, which is how they find food.'
        over = build(hal, engine, script, f'VDL say {engine}')
        said = heard(DATA / over['output'])
        plan = direction.parse(script)
        take = takes_of(over['segments'][0])[-1]
        case['override'] = {'script': script, 'spoken': plan.spoken, 'heard': said,
                            'stored_spoken': take.get('spoken'),
                            'reached_engine': 'tar' in said.lower(),
                            'display_preserved': over['segments'][0]['text'] == script}
        print(f"  override: script keeps “tarsi”, engine got “tar sigh” -> heard: {said[:68]}",
              flush=True)
        if take.get('spoken') != plan.spoken:
            failures.append(f'{name}: the take did not store the spoken text')
        if over['segments'][0]['text'] != script:
            failures.append(f'{name}: the written script was rewritten')

        # --- editing timing must reuse the take without deleting it ----------
        before = len(takes_of(paused['segments'][0]))
        paused['segments'][0]['text'] = paused['segments'][0]['text'].replace('0.8', '0.45')
        stale = segment_needs_audio(paused['segments'][0], DATA)
        kept = len(takes_of(paused['segments'][0]))
        case['stale'] = {'went_stale': stale, 'takes_before': before, 'takes_after': kept}
        print(f'  changing [pause:0.8] to [pause:0.45]: stale={stale}, takes kept {kept}',
              flush=True)
        if stale:
            failures.append(f'{name}: changing only a pause invalidated reusable audio')
        if kept != before:
            failures.append(f'{name}: changing a pause deleted a take')

        report[engine] = case

    # --- the reported bug: a pause marker alone between paragraphs -------------------
    REPORTED = ("Have you ever wondered why flies do that?\n\n"
                "[pause:0.4]\n\n"
                "Here's the explanation.")
    for engine in (engines.QWEN, engines.CHATTERBOX):
        name = engines.label(engine)
        built = build(hal, engine, REPORTED, f'VDL standalone {engine}')
        if len(built['segments']) != 2:
            failures.append(f'{name}: the timing paragraph became a section')
        out = DATA / built['output']
        gap = longest_gap(out)
        spoken = ' '.join(direction.parse(p).spoken for p in REPORTED.split('\n\n')
                          if direction.parse(p).spoken.strip())
        result = verify.compare(spoken, heard(out))
        report.setdefault('standalone', {})[engine] = {
            'sections': len(built['segments']), 'gap': gap,
            'lead_pause': built['segments'][1].get('lead_pause'),
            'complete': result['ok'], 'coverage': result['coverage'],
            'seconds': round(sf.info(out).duration, 2)}
        print(f"  {name}: sections={len(built['segments'])} "
              f"lead_pause={built['segments'][1].get('lead_pause')} "
              f"measured gap={gap:.3f}s complete={result['ok']}", flush=True)
        if not 0.33 <= gap <= 0.52:
            failures.append(f'{name}: [pause:0.4] between paragraphs measured {gap:.3f}s')
        if not result['ok']:
            failures.append(f'{name}: standalone-pause narration incomplete')

    # --- exports carry the directions through --------------------------------------
    hal_session = build(hal, engines.QWEN,
                        f'{SPOKEN_CHECK}[pause:0.6] The mystery is over.', 'VDL export')
    source = DATA / hal_session['output']
    report['exports'] = {}
    for extension in ('wav', 'mp3'):
        destination = ROOT / 'samples' / f'direction-demo.{extension}'
        worker({'action': 'export', 'source': str(source), 'destination': str(destination)},
               f'test-direction-export-{extension}', 900)
        spoken = direction.parse(f'{SPOKEN_CHECK} The mystery is over.').spoken
        result = verify.compare(spoken, heard(destination))
        report['exports'][extension] = {'complete': result['ok'], 'coverage': result['coverage'],
                                        'gap': longest_gap(destination)}
        print(f"  export {extension}: complete={result['ok']} cov={result['coverage']} "
              f"gap={longest_gap(destination):.3f}s", flush=True)
        if not result['ok']:
            failures.append(f'{extension} export incomplete')

    report['failures'] = failures
    atomic_json(ROOT / 'docs' / 'direction-results.json', report)
    print(f'\n  FAILURES: {len(failures)}', flush=True)
    for line in failures:
        print('   -', line, flush=True)
    raise SystemExit(1 if failures else 0)


if __name__ == '__main__':
    main()
