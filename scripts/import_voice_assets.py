"""Import a supplied recording as a voice profile, choosing its best reference window.

The window is picked from the local Whisper model's own word timings rather than from
raw energy, so a reference always starts and ends on a complete word and, where possible,
on a sentence boundary. Nothing is written to the source file; the worker copies it.

    .venv/bin/python scripts/import_voice_assets.py --list
    .venv/bin/python scripts/import_voice_assets.py --name Mike --source ~/Downloads/x.mp3
    .venv/bin/python scripts/import_voice_assets.py --name Michael --source ~/Downloads/x.mp4 --start 156.45 --end 163.25

--start/--end use a window chosen by hand (e.g. the one stretch without background music); the
transcript still comes from the words Whisper heard inside it. Video files work: only the audio is read.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from voice_studio import styles
from voice_studio.config import DATA, STT_MODEL, initialize, offline_environment
from voice_studio.storage import atomic_json, has_reference, profiles, read_json, save_profile

TARGET = 12.0           # seconds of reference we aim for
SPAN = (8.0, 15.0)      # acceptable window length
LONG_GAP = 0.8          # a silence this long inside a window is a defect


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def words_of(text):
    return re.findall(r"[a-z0-9']+", text.lower())


def similarity(a, b):
    """Fraction of the expected words that survive, order-insensitive."""
    from collections import Counter
    first, second = Counter(words_of(a)), Counter(words_of(b))
    if not first:
        return 0.0
    return round(sum((first & second).values()) / sum(first.values()), 3)


def transcribe_detailed(path):
    """Full-file transcription with word timings, via the project's offline model."""
    import numpy as np
    import soundfile as sf
    import mlx_whisper
    from voice_studio.audio import ffmpeg
    with tempfile.TemporaryDirectory() as temp:
        wav = Path(temp) / 'probe.wav'
        subprocess.run([ffmpeg(), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                        '-i', str(path), '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(wav)],
                       check=True)
        audio, _ = sf.read(wav, dtype='float32')
    return mlx_whisper.transcribe(np.asarray(audio), path_or_hf_repo=str(STT_MODEL), verbose=None,
                                  condition_on_previous_text=False, temperature=0.0,
                                  word_timestamps=True)


def fixed_window(result, start, end):
    """A hand-picked window, described like choose_window's so the profile records the same fields."""
    words = [w for s in result['segments'] for w in (s.get('words') or []) if start <= w['start'] and w['end'] <= end]
    if not words:
        raise SystemExit(f'No words were recognised between {start} and {end} s.')
    gaps = [b['start'] - a['end'] for a, b in zip(words, words[1:])]
    length = end - start
    return {'start': round(start, 2), 'end': round(end, 2), 'seconds': round(length, 2),
            'text': ''.join(w['word'] for w in words).strip(),
            'confidence': round(sum(w.get('probability', 1.0) for w in words) / len(words), 3),
            'speech_fraction': round(sum(w['end'] - w['start'] for w in words) / length, 3),
            'longest_gap': round(max(gaps), 2) if gaps else 0.0}


def choose_window(result):
    """Best contiguous run of spoken segments, scored for cleanliness and completeness."""
    segments = [s for s in result['segments'] if s.get('text', '').strip()]
    if not segments:
        raise SystemExit('No speech was recognised in this recording.')
    best = None
    for i in range(len(segments)):
        for j in range(i, len(segments)):
            chosen = segments[i:j + 1]
            words = [w for s in chosen for w in (s.get('words') or [])]
            if not words:
                continue
            start, end = words[0]['start'], words[-1]['end']
            length = end - start
            if not SPAN[0] <= length <= SPAN[1]:
                continue
            # Silence inside the window: the gaps between consecutive words.
            gaps = [b['start'] - a['end'] for a, b in zip(words, words[1:])]
            speech = sum(w['end'] - w['start'] for w in words)
            confidence = sum(w.get('probability', 1.0) for w in words) / len(words)
            text = ' '.join(s['text'].strip() for s in chosen)
            score = (
                confidence * 3.0                                   # clean, confidently heard audio
                + (speech / length) * 2.0                          # dense speech, little dead air
                - abs(length - TARGET) * 0.25                      # near the target length
                - sum(g for g in gaps if g > LONG_GAP) * 1.5       # no long internal pauses
                + (0.6 if text.rstrip().endswith(('.', '!', '?')) else 0)   # ends a sentence
                + (0.3 if text[:1].isupper() else 0)               # starts a sentence
            )
            if best is None or score > best['score']:
                best = {'score': round(score, 4), 'start': round(start, 2), 'end': round(end, 2),
                        'seconds': round(length, 2), 'text': text,
                        'confidence': round(confidence, 3),
                        'speech_fraction': round(speech / length, 3),
                        'longest_gap': round(max(gaps), 2) if gaps else 0.0}
    if best is None:
        raise SystemExit(f'No clean {SPAN[0]:.0f}-{SPAN[1]:.0f} s passage was found in this recording.')
    return best


def worker(job, name):
    request = DATA / 'jobs' / (name + '.json')
    atomic_json(request, job)
    result = subprocess.run([sys.executable, '-u', '-m', 'voice_studio.worker', str(request)],
                            cwd=ROOT, env={**os.environ, **offline_environment()},
                            capture_output=True, text=True, timeout=900)
    if result.returncode:
        print(result.stderr[-4000:], flush=True)
        raise RuntimeError(f'{name} failed ({result.returncode})')
    return [json.loads(l[9:]) for l in result.stdout.splitlines() if l.startswith('VS_EVENT ')]


def import_voice(name, source, style, note, start=None, end=None):
    source = Path(source).expanduser()
    if not source.is_file():
        raise SystemExit(f'No such recording: {source}')
    before = digest(source)
    existing = next((p for p in profiles() if p['name'] == name), None)

    print(f'\n=== {name} ===', flush=True)
    print(f'  source   {source.name}', flush=True)
    detail = transcribe_detailed(source)
    window = fixed_window(detail, start, end) if start is not None else choose_window(detail)
    print(f"  window   {window['start']:.2f}-{window['end']:.2f} s ({window['seconds']:.2f} s) "
          f"confidence={window['confidence']} speech={window['speech_fraction']} "
          f"longest_gap={window['longest_gap']}", flush=True)
    print(f"  text     {window['text']}", flush=True)

    events = worker({'action': 'prepare', 'source': str(source), 'name': name,
                     'profile_id': existing['id'] if existing else None,
                     'start': window['start'], 'duration': window['seconds'],
                     'transcript': window['text'], 'transcribe': False,
                     'style': style}, 'import-' + name.lower())
    profile = next(e['profile'] for e in events if e['kind'] == 'profile')

    # Confirm the saved transcript matches the audio that was actually prepared, which the
    # edge trim may have shortened slightly at either end.
    reference = DATA / profile['reference']
    check = transcribe_detailed(reference)['text'].strip()
    agreement = similarity(window['text'], check)
    print(f"  prepared {profile['seconds']:.2f} s @ {profile['sample_rate']} Hz", flush=True)
    print(f"  re-heard {check}", flush=True)
    print(f"  match    {agreement:.3f}", flush=True)
    if agreement < 0.95:
        # Trust the clip we will actually condition on, not the full-file reading.
        profile['transcript'] = check
        print('  note     saved the re-heard transcript; it matches the prepared clip', flush=True)

    profile.update({
        'style': style,
        'description': f'Imported from {source.name}. Reference taken from '
                       f"{window['start']:.2f}-{window['end']:.2f} s of the original recording.",
        'source_file': source.name,
        'source_path': str(source),
        'source_sha256': before,
        'authorization': note,
        'transcript_agreement': agreement,
        'window': {k: window[k] for k in ('start', 'end', 'seconds', 'confidence',
                                          'speech_fraction', 'longest_gap')},
    })
    save_profile(profile)
    assert digest(source) == before, 'the source recording was modified'
    print('  original unchanged (sha256 verified)', flush=True)
    return profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name')
    parser.add_argument('--source')
    parser.add_argument('--style', default=styles.ENERGETIC, choices=styles.ORDER)
    parser.add_argument('--note', default='Supplied by the user. Licence not verified.')
    parser.add_argument('--start', type=float, help='use this window instead of choosing one (seconds)')
    parser.add_argument('--end', type=float)
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()
    initialize()
    if args.list or not (args.name and args.source):
        for item in profiles():
            print(f"  {item['name']:<34} {item.get('style', styles.NATURAL):<20} "
                  f"{'ready' if has_reference(item) else 'awaiting recording'}")
        return
    if (args.start is None) != (args.end is None):
        parser.error('--start and --end go together')
    import_voice(args.name, args.source, args.style, args.note, args.start, args.end)


if __name__ == '__main__':
    main()
