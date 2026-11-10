"""End-to-end proof that generated narrations contain the whole script.

Everything here is checked against the actual audio: every section, the assembled
narration, and both exported files are transcribed back and compared with the script,
with particular attention to the first and last words of each section.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import soundfile as sf
from voice_studio import styles, verify
from voice_studio.config import DATA, initialize, offline_environment
from voice_studio.storage import atomic_json, profiles, read_json, save_session, session_path
from voice_studio.text import new_session

LONG = ("It was a cold night in late autumn and the dog ran off into the dark. We waited by "
        "the gate for almost an hour, saying nothing at all, watching the empty road.\n\n"
        "A day later he showed up at the door. He was muddy, tired and very pleased with "
        "himself, so we fed him, dried him off, and let him sleep by the fire.\n\n"
        "Most people never notice this, but a dog remembers a route by smell rather than by "
        "sight. That is why he found his way back to a house he had only seen once.")
TINY = 'Yes. It worked.'
EDGES = ('A bird sat on the wire. It did not move for an hour, and then it was gone.\n\n'
         'So we went in. The room was empty and the light was off.')


def worker(job, name, timeout=3600):
    request = DATA / 'jobs' / (name + '.json')
    atomic_json(request, job)
    result = subprocess.run([sys.executable, '-u', '-m', 'voice_studio.worker', str(request)],
                            cwd=ROOT, env={**os.environ, **offline_environment()},
                            capture_output=True, text=True, timeout=timeout)
    (ROOT / 'docs' / (name + '.log')).write_text(result.stdout + '\nSTDERR:\n' + result.stderr)
    if result.returncode:
        print(result.stderr[-4000:], flush=True)
        raise RuntimeError(f'{name} failed ({result.returncode})')
    return [json.loads(l[9:]) for l in result.stdout.splitlines() if l.startswith('VS_EVENT ')]


def heard(path, tag='verify-transcribe'):
    events = worker({'action': 'transcribe', 'source': str(path)}, tag, timeout=900)
    return next(e['text'] for e in events if e['kind'] == 'transcript')


def audit(label, script, session, failures):
    """Re-check the audio ourselves rather than trusting the worker's own verdict."""
    rows = []
    for i, seg in enumerate(session['segments']):
        result = verify.compare(seg['text'], heard(DATA / seg['file']))
        rows.append({'index': i, 'ok': result['ok'], 'similarity': result['similarity'],
                     'coverage': result['coverage'], 'head_ok': result['head_ok'],
                     'tail_ok': result['tail_ok'], 'attempts': seg.get('attempts'),
                     'worker_verified': seg.get('verified')})
        if not result['ok']:
            failures.append(f'{label} section {i + 1}: {verify.describe(result, i)}')
        if not result['head_ok'] or not result['tail_ok']:
            failures.append(f'{label} section {i + 1}: edge words missing from the audio')
    whole = verify.compare(script, heard(DATA / session['output']))
    if not whole['ok']:
        failures.append(f'{label} full narration: {verify.describe(whole, 0)}')
    return {'sections': rows, 'full': whole}


def main():
    initialize()
    voices = {p['name']: p for p in profiles() if p['name'] in ('Mike', 'Hal')}
    assert len(voices) == 2, 'Mike and Hal are required'
    report, failures = {'cases': {}}, []
    started = time.monotonic()

    # --- the main matrix: both voices, both styles, a three-paragraph script -------------
    for name, profile in voices.items():
        for style in (styles.NATURAL, styles.ENERGETIC):
            label = f'{name}/{style.split()[0]}'
            session = new_session(LONG, f'Completeness {label}', profile, style)
            save_session(session)
            start = time.monotonic()
            events = worker({'action': 'generate', 'session': str(session_path(session))},
                            f'test-complete-{name.lower()}-{style.split()[0].lower()}')
            session = read_json(session_path(session))
            assert session['output'], f'{label} produced no narration'
            case = audit(label, LONG, session, failures)
            case.update(style=style, voice=name, sections_count=len(session['segments']),
                        seconds=round(sf.info(DATA / session['output']).duration, 2),
                        peak_memory_gb=next(e['peak_memory_gb'] for e in events
                                            if e['kind'] == 'metrics'),
                        retried=[s.get('attempts', 1) for s in session['segments']],
                        wall_seconds=round(time.monotonic() - start, 1),
                        session_id=session['id'])
            report['cases'][label] = case
            print(f"  {label:16s} {case['sections_count']} sections  {case['seconds']:6.2f}s  "
                  f"full_ok={case['full']['ok']} cov={case['full']['coverage']:.3f}  "
                  f"takes={case['retried']}  peak={case['peak_memory_gb']}GB", flush=True)

    # --- a very short script, where an edge word is most of the section -------------------
    for name, profile in voices.items():
        session = new_session(TINY, f'Tiny {name}', profile, styles.ENERGETIC)
        save_session(session)
        worker({'action': 'generate', 'session': str(session_path(session))},
               f'test-complete-tiny-{name.lower()}')
        session = read_json(session_path(session))
        case = audit(f'{name}/tiny', TINY, session, failures)
        report['cases'][f'{name}/tiny'] = case
        print(f"  {name}/tiny          full_ok={case['full']['ok']} "
              f"cov={case['full']['coverage']:.3f}", flush=True)

    # --- short words at section edges ------------------------------------------------------
    profile = voices['Mike']
    session = new_session(EDGES, 'Edge words', profile, styles.ENERGETIC)
    save_session(session)
    worker({'action': 'generate', 'session': str(session_path(session))}, 'test-complete-edges')
    session = read_json(session_path(session))
    report['cases']['Mike/edges'] = audit('Mike/edges', EDGES, session, failures)
    print(f"  Mike/edges        full_ok={report['cases']['Mike/edges']['full']['ok']}", flush=True)

    # --- resume after a partial run, then regenerate one section ---------------------------
    session = new_session(LONG, 'Resume check', profile, styles.ENERGETIC)
    save_session(session)
    worker({'action': 'generate', 'session': str(session_path(session)), 'indices': [0]},
           'test-complete-partial')
    partial = read_json(session_path(session))
    assert partial['segments'][0]['file'] and not partial['output'], 'partial run looks wrong'
    first_file = partial['segments'][0]['file']
    worker({'action': 'generate', 'session': str(session_path(session))}, 'test-complete-resume')
    session = read_json(session_path(session))
    assert session['output'], 'resuming did not assemble a narration'
    assert session['segments'][0]['file'] == first_file, 'resuming re-did a finished section'
    resumed = audit('resume', LONG, session, failures)
    report['cases']['resume'] = resumed
    print(f"  resume            full_ok={resumed['full']['ok']} "
          f"cov={resumed['full']['coverage']:.3f}", flush=True)

    keep = [s['file'] for s in session['segments']]
    worker({'action': 'generate', 'session': str(session_path(session)), 'indices': [1],
            'regenerate': True}, 'test-complete-regen')
    session = read_json(session_path(session))
    assert session['segments'][0]['file'] == keep[0], 'regeneration disturbed section 1'
    assert session['segments'][2]['file'] == keep[2], 'regeneration disturbed section 3'
    assert session['segments'][1]['file'] != keep[1], 'regeneration did not replace section 2'
    regen = audit('regenerated', LONG, session, failures)
    report['cases']['regenerated'] = regen
    print(f"  regenerated       full_ok={regen['full']['ok']} "
          f"cov={regen['full']['coverage']:.3f}", flush=True)

    # --- exports must contain exactly what playback does ------------------------------------
    source = DATA / session['output']
    report['exports'] = {}
    for extension in ('wav', 'mp3'):
        destination = ROOT / 'samples' / f'completeness-demo.{extension}'
        worker({'action': 'export', 'source': str(source), 'destination': str(destination)},
               'test-complete-export-' + extension)
        result = verify.compare(LONG, heard(destination))
        report['exports'][extension] = {'file': str(destination.relative_to(ROOT)),
                                        'ok': result['ok'], 'coverage': result['coverage'],
                                        'head_ok': result['head_ok'], 'tail_ok': result['tail_ok']}
        if not result['ok']:
            failures.append(f'{extension} export: {verify.describe(result, 0)}')
        print(f"  export {extension:3s}        ok={result['ok']} "
              f"cov={result['coverage']:.3f}", flush=True)

    report['failures'] = failures
    report['wall_seconds'] = round(time.monotonic() - started, 1)
    report['peak_memory_gb'] = max(c['peak_memory_gb'] for c in report['cases'].values()
                                   if 'peak_memory_gb' in c)
    atomic_json(ROOT / 'docs' / 'completeness-results.json', report)
    print(f"\n  peak memory {report['peak_memory_gb']} GB over {report['wall_seconds']} s", flush=True)
    print(f'  FAILURES: {len(failures)}', flush=True)
    for line in failures:
        print('   -', line, flush=True)
    raise SystemExit(1 if failures else 0)


if __name__ == '__main__':
    main()
