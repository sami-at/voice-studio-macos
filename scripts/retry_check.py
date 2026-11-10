"""Exercise the retry path by making verification fail on purpose.

Real generations pass, so the retry loop would otherwise never run in testing. This drives
the actual worker with a stubbed verifier and checks the three promises: attempts are
bounded, the best take is the one kept, and a section that never passes is reported rather
than quietly accepted.
"""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from voice_studio.config import DATA, initialize, offline_environment
os.environ.update(offline_environment())
from voice_studio import styles, verify
import voice_studio.worker as worker
from voice_studio.storage import profiles, read_json, save_session, session_path
from voice_studio.text import new_session

TEXT = 'Yes. It worked.'


def run(label, verdicts, expect_attempts, expect_verified, expect_kept=None):
    """verdicts: coverage per attempt; ok when coverage is 1.0."""
    profile = next(p for p in profiles() if p['name'] == 'Mike')
    session = new_session(TEXT, f'Retry {label}', profile, styles.ENERGETIC)
    save_session(session)
    calls = {'n': 0}
    real = verify.compare

    def stub(expected, heard):
        result = dict(real(expected, heard))
        coverage = verdicts[min(calls['n'], len(verdicts) - 1)]
        calls['n'] += 1
        result.update(ok=coverage >= 1.0, coverage=coverage, similarity=coverage,
                      head_ok=coverage >= 1.0, tail_ok=True,
                      missing_at_start=0 if coverage >= 1.0 else 2, missing_at_end=0,
                      missing=[] if coverage >= 1.0 else ['yes'])
        return result

    events = []
    worker.verify.compare = stub
    original_emit = worker.emit
    worker.emit = lambda kind, **payload: events.append({'kind': kind, **payload})
    try:
        worker.generate({'action': 'generate', 'session': str(session_path(session))})
    finally:
        worker.verify.compare = real
        worker.emit = original_emit

    session = read_json(session_path(session))
    segment = session['segments'][0]
    folder = DATA / 'sessions' / session['id']
    leftovers = sorted(p.name for p in folder.glob('0001-*.wav'))
    incomplete = [e for e in events if e['kind'] == 'incomplete']
    kept = segment['check']['coverage']

    print(f'\n--- {label}', flush=True)
    print(f"  verifier calls      {calls['n']} (expected {expect_attempts})", flush=True)
    print(f"  takes made          {segment.get('attempts')} (expected {expect_attempts})", flush=True)
    print(f"  take kept           {segment.get('kept_take')} (expected {expect_kept})", flush=True)
    print(f"  verified flag       {segment.get('verified')} (expected {expect_verified})", flush=True)
    print(f"  kept take coverage  {kept} (best offered: {max(verdicts[:expect_attempts])})", flush=True)
    print(f"  section files left  {leftovers}", flush=True)
    print(f"  incomplete events   {len(incomplete)}", flush=True)
    if incomplete:
        print(f"    -> {incomplete[0]['detail']}", flush=True)

    problems = []
    if calls['n'] != expect_attempts:
        problems.append(f'ran {calls["n"]} attempts, expected {expect_attempts}')
    if segment.get('attempts') != expect_attempts:
        problems.append(f'recorded {segment.get("attempts")} takes, expected {expect_attempts}')
    if expect_kept is not None and segment.get('kept_take') != expect_kept:
        problems.append(f'kept take {segment.get("kept_take")}, expected {expect_kept}')
    if segment.get('verified') is not expect_verified:
        problems.append(f'verified={segment.get("verified")}, expected {expect_verified}')
    if kept != max(verdicts[:expect_attempts]):
        problems.append('did not keep the best take')
    if len(leftovers) != 1:
        problems.append(f'left {len(leftovers)} audio files behind, expected 1')
    if expect_verified is False and not incomplete:
        problems.append('a failing section was not reported as incomplete')
    if expect_verified is True and incomplete:
        problems.append('a passing section was reported as incomplete')
    if not (folder / segment['file'].split('/')[-1]).is_file():
        problems.append('the kept file is missing from disk')
    return problems


def main():
    initialize()
    problems = []
    # Fails once, then passes: must stop at two attempts and be marked verified.
    problems += [f'[recovers] {p}' for p in run('recovers on the second take',
                                                [0.40, 1.00], 2, True, expect_kept=2)]
    # Never passes: must stop at the bound, keep the best take, and say so.
    # Best take is the middle one, so the bound must still run three and keep take two.
    problems += [f'[never passes] {p}' for p in run('never passes',
                                                    [0.40, 0.70, 0.55], 3, False, expect_kept=2)]
    print(f'\nPROBLEMS: {len(problems)}', flush=True)
    for line in problems:
        print('  -', line, flush=True)
    raise SystemExit(1 if problems else 0)


if __name__ == '__main__':
    main()
