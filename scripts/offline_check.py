"""Prove generation needs no network: run the worker inside a network-denied sandbox."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from voice_studio.config import DATA, initialize, offline_environment
from voice_studio.storage import atomic_json, profiles, read_json, save_session, session_path
from voice_studio.text import new_session

SANDBOX = ['/usr/bin/sandbox-exec', '-f', str(ROOT / 'docs' / 'deny-network.sb')]


def sandboxed(arguments, timeout=1800):
    return subprocess.run([*SANDBOX, *arguments], cwd=ROOT, env={**os.environ, **offline_environment()},
                          capture_output=True, text=True, timeout=timeout)


def main():
    initialize()
    results = {}
    # Confirm the sandbox really blocks sockets, so a pass below means something.
    probe = sandboxed([sys.executable, '-I', '-c',
                       'import socket; socket.create_connection(("1.1.1.1", 443), 5)'], timeout=60)
    results['sandbox_blocks_network'] = probe.returncode != 0
    assert results['sandbox_blocks_network'], 'The deny-network sandbox did not block an outbound socket.'

    profile = next((p for p in profiles() if p['name'].startswith('Demo · LJ Speech')), None)
    assert profile, 'Run scripts/inference_check.py first to create the demonstration profile.'
    script = 'Voice Studio generated this sentence with no network connection available.'
    session = new_session(script, 'Offline generation check', profile)
    save_session(session)
    request = DATA / 'jobs' / 'test-offline.json'
    atomic_json(request, {'action': 'generate', 'session': str(session_path(session))})

    start = time.monotonic()
    result = sandboxed([sys.executable, '-u', '-m', 'voice_studio.worker', str(request)])
    (ROOT / 'docs' / 'test-offline.log').write_text(result.stdout + '\nSTDERR:\n' + result.stderr)
    print(result.stdout, flush=True)
    if result.returncode:
        print(result.stderr[-7000:], flush=True)
        raise RuntimeError(f'Offline generation failed ({result.returncode})')
    events = [json.loads(line[9:]) for line in result.stdout.splitlines() if line.startswith('VS_EVENT ')]

    session = read_json(session_path(session))
    output = DATA / session['output']
    assert output.is_file() and output.stat().st_size > 40_000, 'No usable offline narration was written.'
    import soundfile as sf
    info = sf.info(output)
    results.update(session_id=session['id'], output=str(output.relative_to(ROOT)),
                   seconds=round(info.duration, 2), sample_rate=info.samplerate,
                   device=next(e['device'] for e in events if e['kind'] == 'loaded'),
                   peak_memory_gb=next(e['peak_memory_gb'] for e in events if e['kind'] == 'metrics'),
                   generation_seconds=session['segments'][0]['generation_seconds'],
                   wall_seconds=round(time.monotonic() - start, 2))
    atomic_json(ROOT / 'docs' / 'offline-results.json', results)
    print(json.dumps(results, indent=2), flush=True)


if __name__ == '__main__':
    main()
