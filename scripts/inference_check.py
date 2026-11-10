"""Reproducible real-model check using the public-domain LJ Speech reference."""
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


def worker(job, log_name):
    request = DATA / 'jobs' / (log_name + '.json')
    atomic_json(request, job)
    result = subprocess.run([sys.executable, '-u', '-m', 'voice_studio.worker', str(request)],
                            cwd=ROOT, env={**os.environ, **offline_environment()},
                            capture_output=True, text=True, timeout=1800)
    (ROOT / 'docs' / (log_name + '.log')).write_text(result.stdout + '\nSTDERR:\n' + result.stderr)
    print(result.stdout, flush=True)
    if result.returncode:
        print(result.stderr[-7000:], flush=True)
        raise RuntimeError(f'{log_name} failed ({result.returncode})')
    return [json.loads(line[9:]) for line in result.stdout.splitlines() if line.startswith('VS_EVENT ')]


def main():
    initialize()
    start = time.monotonic()
    reference = ROOT / 'samples' / 'lj-speech-public-domain.wav'
    transcript = (ROOT / 'samples' / 'reference.txt').read_text().strip()
    existing = next((p['id'] for p in profiles() if p['name'] == 'Demo · LJ Speech (public domain)'), None)
    events = worker({'action': 'prepare', 'source': str(reference), 'name': 'Demo · LJ Speech (public domain)',
                    'profile_id': existing, 'duration': 15, 'start': 0, 'transcript': transcript, 'transcribe': False}, 'test-reference')
    profile = next(e['profile'] for e in events if e['kind'] == 'profile')
    script = (ROOT / 'samples' / 'long-narration.txt').read_text().strip()
    session = new_session(script, 'Local inference check', profile)
    save_session(session)
    events = worker({'action': 'generate', 'session': str(session_path(session))}, 'test-inference')
    session = read_json(session_path(session))
    assert session['output'] and len(session['segments']) == 3
    original_files = [s['file'] for s in session['segments']]
    initial_generation_seconds = sum(s['generation_seconds'] for s in session['segments'])
    worker({'action': 'generate', 'session': str(session_path(session)), 'indices': [1], 'regenerate': True}, 'test-regeneration')
    session = read_json(session_path(session))
    assert session['segments'][0]['file'] == original_files[0]
    assert session['segments'][1]['file'] != original_files[1]
    assert session['segments'][2]['file'] == original_files[2]
    for extension in ['wav', 'mp3']:
        worker({'action': 'export', 'source': str(DATA / session['output']),
                'destination': str(ROOT / 'samples' / ('generated-demo.' + extension))}, 'test-export-' + extension)
    transcript_events = worker({'action': 'transcribe', 'source': str(reference)}, 'test-transcription')
    generated_events = worker({'action': 'transcribe', 'source': str(DATA / session['output'])}, 'test-generated-transcription')
    report = {'session_id': session['id'], 'profile_id': profile['id'], 'script': script,
              'seconds': session['seconds'], 'segments': session['segments'],
              'individual_regeneration': True, 'initial_generation_seconds': initial_generation_seconds,
              'peak_memory_gb': next(e['peak_memory_gb'] for e in events if e['kind'] == 'metrics'),
              'reference_transcription': next(e['text'] for e in transcript_events if e['kind'] == 'transcript'),
              'generated_transcription': next(e['text'] for e in generated_events if e['kind'] == 'transcript'),
              'wall_seconds': round(time.monotonic() - start, 2)}
    atomic_json(ROOT / 'docs' / 'inference-results.json', report)
    print(json.dumps(report, indent=2), flush=True)

if __name__ == '__main__':
    main()
