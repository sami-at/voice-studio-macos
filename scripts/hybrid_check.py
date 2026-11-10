"""The hybrid workflow end to end, on real audio.

Builds a narration where different sections are recorded by different engines, proves that
every take is kept and selectable, that editing words makes takes stale, and that the
exported file is the one made from the selected takes.
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
from voice_studio import engines, styles, verify
from voice_studio.config import DATA, initialize, offline_environment
from voice_studio.storage import (atomic_json, choose_take, profiles, read_json, save_session,
                                  segment_needs_audio, selected_take, session_path, takes_of,
                                  take_is_stale, text_fingerprint)
from voice_studio.text import new_session

SCRIPT = ("Have you ever wondered why flies rub their hands together?\n\n"
          "Surprisingly, they are not plotting anything. They are cleaning themselves.\n\n"
          "Flies taste with their feet, so a clean pair of feet is how they find food.")


def worker(job, name, timeout=5400):
    request = DATA / 'jobs' / (name + '.json')
    atomic_json(request, job)
    result = subprocess.run([sys.executable, '-u', '-m', 'voice_studio.worker', str(request)],
                            cwd=ROOT, env={**os.environ, **offline_environment()},
                            capture_output=True, text=True, timeout=timeout)
    (ROOT / 'docs' / (name + '.log')).write_text(result.stdout + '\nSTDERR:\n' + result.stderr)
    if result.returncode:
        print(result.stderr[-3000:], flush=True)
        raise RuntimeError(f'{name} failed ({result.returncode})')
    return [json.loads(l[9:]) for l in result.stdout.splitlines() if l.startswith('VS_EVENT ')]


def heard(path):
    events = worker({'action': 'transcribe', 'source': str(path)}, 'hybrid-transcribe', 900)
    return next(e['text'] for e in events if e['kind'] == 'transcript')


def main():
    initialize()
    failures, report = [], {}
    mike = next(p for p in profiles() if p['name'] == 'Mike')
    session = new_session(SCRIPT, 'Hybrid demo', mike, styles.ENERGETIC)
    save_session(session)
    path = session_path(session)
    peak = 0.0

    # --- 1. every section with Qwen, then section 2 again with Chatterbox --------------
    events = worker({'action': 'generate', 'session': str(path), 'engine': engines.QWEN},
                    'test-hybrid-qwen')
    peak = max(peak, next(e['peak_memory_gb'] for e in events if e['kind'] == 'metrics'))
    session = read_json(path)
    assert session['output'], 'the Qwen pass produced no narration'
    qwen_files = [s['file'] for s in session['segments']]
    print(f"  Qwen pass: {len(session['segments'])} sections, "
          f"{session['seconds']:.2f}s", flush=True)

    start = time.monotonic()
    events = worker({'action': 'generate', 'session': str(path), 'indices': [1],
                     'engine': engines.CHATTERBOX, 'engine_config': {'exaggeration': 0.5}},
                    'test-hybrid-chatterbox')
    peak = max(peak, next(e['peak_memory_gb'] for e in events if e['kind'] == 'metrics'))
    session = read_json(path)
    middle = session['segments'][1]
    print(f"  Chatterbox alternative for section 2 in {time.monotonic()-start:.0f}s, "
          f"takes now {len(takes_of(middle))}", flush=True)

    # --- 2. both takes kept, each with its own engine and settings ---------------------
    if len(takes_of(middle)) != 2:
        failures.append('the Qwen take for section 2 was not preserved')
    kinds = {t['engine'] for t in takes_of(middle)}
    if kinds != {engines.QWEN, engines.CHATTERBOX}:
        failures.append(f'expected one take per engine, found {kinds}')
    for take in takes_of(middle):
        if not (DATA / take['file']).is_file():
            failures.append(f"take file missing for {take['engine']}")
        if take['engine'] == engines.CHATTERBOX and not take.get('engine_config'):
            failures.append('the Chatterbox take did not keep its settings')
        if take.get('verified') is False:
            print(f"  note: the {take['engine']} take did not pass completeness", flush=True)
    if session['segments'][0]['file'] != qwen_files[0] or \
            session['segments'][2]['file'] != qwen_files[2]:
        failures.append('generating one section disturbed its neighbours')

    # --- 3. the narration is assembled from the selected takes ------------------------
    worker({'action': 'generate', 'session': str(path)}, 'test-hybrid-assemble')
    session = read_json(path)
    mixed = [selected_take(s)['engine'] for s in session['segments']]
    print(f'  assembled with engines: {mixed}', flush=True)
    if mixed[1] != engines.CHATTERBOX:
        failures.append('the newest take was not the one in use')
    output = DATA / session['output']
    check = verify.compare(SCRIPT, heard(output))
    print(f"  mixed narration {sf.info(output).duration:.2f}s complete={check['ok']} "
          f"cov={check['coverage']}", flush=True)
    if not check['ok']:
        failures.append(f'mixed-engine narration incomplete: {verify.describe(check, 0)}')
    report['mixed'] = {'engines': mixed, 'seconds': round(sf.info(output).duration, 2),
                       'coverage': check['coverage'], 'complete': check['ok']}

    # --- 4. switching back to the Qwen take changes the audio, without regenerating ----
    qwen_take = next(t for t in takes_of(middle) if t['engine'] == engines.QWEN)
    before = {t['id']: t['file'] for t in takes_of(middle)}
    session['segments'][1] = choose_take(session['segments'][1], qwen_take['id'])
    save_session(session)
    session = read_json(path)
    if session['segments'][1]['file'] != qwen_take['file']:
        failures.append('selecting a take did not change the section audio')
    if {t['id']: t['file'] for t in takes_of(session['segments'][1])} != before:
        failures.append('selecting a take altered the stored takes')
    worker({'action': 'generate', 'session': str(path)}, 'test-hybrid-reassemble')
    session = read_json(path)
    all_qwen = DATA / session['output']
    print(f"  reassembled all-Qwen {sf.info(all_qwen).duration:.2f}s "
          f"(engines {[selected_take(s)['engine'] for s in session['segments']]})", flush=True)

    # --- 5. exports follow the selection ----------------------------------------------
    session['segments'][1] = choose_take(session['segments'][1],
                                         next(t['id'] for t in takes_of(session['segments'][1])
                                              if t['engine'] == engines.CHATTERBOX))
    save_session(session)
    worker({'action': 'generate', 'session': str(path)}, 'test-hybrid-final')
    session = read_json(path)
    source = DATA / session['output']
    report['exports'] = {}
    for extension in ('wav', 'mp3'):
        destination = ROOT / 'samples' / f'hybrid-demo.{extension}'
        worker({'action': 'export', 'source': str(source), 'destination': str(destination)},
               f'test-hybrid-export-{extension}', 900)
        exported = verify.compare(SCRIPT, heard(destination))
        report['exports'][extension] = {'complete': exported['ok'],
                                        'coverage': exported['coverage']}
        print(f"  export {extension}: complete={exported['ok']} cov={exported['coverage']}",
              flush=True)
        if not exported['ok']:
            failures.append(f'{extension} export of the mixed narration is incomplete')

    # --- 6. editing the words makes the takes stale, and keeps them ---------------------
    session['segments'][1]['text'] = 'They are simply cleaning themselves, nothing more.'
    stale = [take_is_stale(session['segments'][1], t) for t in takes_of(session['segments'][1])]
    if not all(stale):
        failures.append('editing a section did not make its takes stale')
    if len(takes_of(session['segments'][1])) != 2:
        failures.append('editing a section discarded its takes')
    if not segment_needs_audio(session['segments'][1], DATA):
        failures.append('an edited section is not queued for regeneration')
    print(f'  after editing section 2: takes kept={len(takes_of(session["segments"][1]))} '
          f'all stale={all(stale)}', flush=True)

    report.update(peak_memory_gb=peak, failures=failures, session_id=session['id'])
    atomic_json(ROOT / 'docs' / 'hybrid-results.json', report)
    print(f'\n  peak memory {peak} GB', flush=True)
    print(f'  FAILURES: {len(failures)}', flush=True)
    for line in failures:
        print('   -', line, flush=True)
    raise SystemExit(1 if failures else 0)


if __name__ == '__main__':
    main()
