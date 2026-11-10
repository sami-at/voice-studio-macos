"""Create the starting voice profiles. Safe to re-run; it never touches an existing voice."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from voice_studio import styles
from voice_studio.config import DATA, initialize, offline_environment
from voice_studio.storage import atomic_json, identifier, now, profiles, save_profile

MY_VOICE = 'My Voice'
EXPLAINER = 'Explainer Narrator'


def worker(job, name):
    request = DATA / 'jobs' / (name + '.json')
    atomic_json(request, job)
    result = subprocess.run([sys.executable, '-u', '-m', 'voice_studio.worker', str(request)],
                            cwd=ROOT, env={**os.environ, **offline_environment()},
                            capture_output=True, text=True, timeout=900)
    if result.returncode:
        print(result.stderr[-4000:], flush=True)
        raise RuntimeError(f'{name} failed ({result.returncode})')
    return [json.loads(line[9:]) for line in result.stdout.splitlines()
            if line.startswith('VS_EVENT ')]


def main():
    initialize()
    existing = {p['name'] for p in profiles()}
    created = []

    if MY_VOICE not in existing:
        # An empty slot, so the voice and its style exist before the recording does.
        save_profile({
            'id': identifier(), 'name': MY_VOICE, 'created': now(), 'placeholder': True,
            'reference': '', 'transcript': '', 'seconds': 0, 'style': styles.NATURAL,
            'description': 'Your own voice. Add a clean 5-15 second recording of yourself with '
                           'Replace sample..., correct the transcript, then generate.',
            'authorization': 'Owner of the recording.',
        })
        created.append(MY_VOICE)

    if EXPLAINER not in existing:
        # A delivery style, not an impersonation: it narrates in whatever authorised voice is
        # attached to it. It ships pointing at the public-domain sample so it works immediately.
        sample = ROOT / 'samples' / 'lj-speech-public-domain.wav'
        transcript = (ROOT / 'samples' / 'reference.txt').read_text().strip()
        events = worker({'action': 'prepare', 'source': str(sample), 'name': EXPLAINER,
                         'profile_id': None, 'duration': 15, 'start': 0,
                         'transcript': transcript, 'transcribe': False,
                         'style': styles.ENERGETIC}, 'bootstrap-explainer')
        profile = next(e['profile'] for e in events if e['kind'] == 'profile')
        profile['description'] = (
            'A fast, clear narration style for short educational and curiosity videos. This is a '
            'delivery style, not a copy of any particular person. It currently uses the '
            'public-domain LJ Speech sample; replace that with your own or another authorised '
            'recording to give it a different voice.')
        profile['authorization'] = 'Public-domain LJ Speech sample. Replace with a voice you own '\
                                   'or have written permission to use.'
        profile['style'] = styles.ENERGETIC
        save_profile(profile)
        created.append(EXPLAINER)

    for item in profiles():
        state = 'ready' if item.get('reference') else 'awaiting recording'
        print(f"  {item['name']:<34} {item.get('style', styles.NATURAL):<20} {state}")
    print('created:', ', '.join(created) if created else 'nothing new')


if __name__ == '__main__':
    main()
