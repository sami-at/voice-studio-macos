"""Audit saved narrations and stamp their sections with the words they actually say.

Narrations made before sections carried a text fingerprint cannot be trusted on faith, so
each one is listened back to. A section whose audio matches its text is stamped and left
alone; a section that does not match has its audio detached so the app regenerates it.
Audio files are never deleted — only the link from a section to a recording is cleared.

    .venv/bin/python scripts/repair_sessions.py            # report only
    .venv/bin/python scripts/repair_sessions.py --apply    # stamp and detach
"""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from voice_studio.config import DATA, initialize, offline_environment
os.environ.update(offline_environment())
from voice_studio import verify
from voice_studio.storage import save_session, sessions, text_fingerprint
from voice_studio.worker import transcribe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='write the repairs')
    args = parser.parse_args()
    initialize()

    stamped = detached = checked = 0
    for session in sessions():
        changes, notes = False, []
        for index, segment in enumerate(session['segments']):
            path = DATA / segment['file'] if segment.get('file') else None
            if not path or not path.is_file():
                continue
            if segment.get('text_hash'):
                continue                                    # already trustworthy
            checked += 1
            result = verify.compare(segment['text'], transcribe(path))
            if result['ok']:
                segment['text_hash'] = text_fingerprint(segment['text'])
                stamped += 1
                changes = True
            else:
                notes.append(f'    section {index + 1}: {verify.describe(result, index)}')
                notes.append(f'      detaching {Path(segment["file"]).name} (file kept on disk)')
                segment['file'] = None
                segment.pop('text_hash', None)
                session['output'] = None
                detached += 1
                changes = True
        if notes:
            print(f"  {session['title']}")
            print('\n'.join(notes))
        if changes and args.apply:
            save_session(session)

    print(f'\n  sections checked : {checked}')
    print(f'  stamped as good  : {stamped}')
    print(f'  detached as wrong: {detached}')
    if detached and not args.apply:
        print('\n  Re-run with --apply to write these repairs.')
    elif detached:
        print('\n  Open those narrations and press Generate to record the current wording.')


if __name__ == '__main__':
    main()
