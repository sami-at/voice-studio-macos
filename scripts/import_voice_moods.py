"""Add mood clips to an existing voice, cut from one recording of that speaker.

Each clip is a short reference of the same voice in one delivery (voice_studio/moods.py).
Windows are given by hand, or found by reading Whisper's transcript with the same word cues
the app uses to pick a section's mood. Every window starts and ends on a whole word. The
source is never written to; existing takes and narrations are untouched.

    .venv/bin/python scripts/import_voice_moods.py --name "Mr. Stick" \\
        --mood neutral=12.08-24.54 --mood sad=51.38-63.46
    .venv/bin/python scripts/import_voice_moods.py --name "Mr. Stick" --auto

--source defaults to the voice's own stored original. --replace drops clips not listed.
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from import_voice_assets import digest, fixed_window, similarity, transcribe_detailed
from voice_studio import moods
from voice_studio.audio import prepare_reference
from voice_studio.config import DATA, initialize
from voice_studio.storage import identifier, profiles, save_profile

SPAN = (4.0, 15.0)      # a mood clip shorter than this gives the model too little to copy
TARGET = 10.0
LEAD, TAIL = 0.15, 0.30  # breathing room around the first and last word, never into a neighbour


def parse_window(text):
    name, _, span = text.partition('=')
    start, _, end = span.partition('-')
    try:
        return name.strip().lower(), float(start), float(end)
    except ValueError:
        raise SystemExit(f'Write a mood window as name=start-end, e.g. sad=51.4-63.5 (got {text!r}).')


def all_words(result):
    return [w for s in result['segments'] for w in (s.get('words') or [])]


def padded(words, start, end):
    """Widen a word-aligned window into the silence on either side, stopping short of other words."""
    before = max((w['end'] for w in words if w['end'] <= start + 1e-3), default=0.0)
    after = min((w['start'] for w in words if w['start'] >= end - 1e-3), default=end + TAIL * 2)
    return max(0.0, start - min(LEAD, (start - before) / 2)), end + min(TAIL, (after - end) / 2)


def auto_windows(result):
    """Best clean run of segments for each mood the transcript clearly shows."""
    segments = [s for s in result['segments'] if s.get('text', '').strip() and s.get('words')]
    tagged = [moods.detect(s['text']) for s in segments]
    best = {}
    for i in range(len(segments)):
        for j in range(i, len(segments)):
            mood = tagged[i]
            if any(t != mood for t in tagged[i:j + 1]):
                break
            words = [w for s in segments[i:j + 1] for w in s['words']]
            start, end = words[0]['start'], words[-1]['end']
            length = end - start
            if length > SPAN[1]:
                break
            if length < SPAN[0]:
                continue
            speech = sum(w['end'] - w['start'] for w in words)
            confidence = sum(w.get('probability', 1.0) for w in words) / len(words)
            score = confidence * 3 + speech / length * 2 - abs(length - TARGET) * 0.25
            if mood not in best or score > best[mood][0]:
                best[mood] = (score, start, end)
    return {mood: (start, end) for mood, (_, start, end) in best.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--name', required=True)
    parser.add_argument('--source')
    parser.add_argument('--mood', action='append', default=[], metavar='NAME=START-END')
    parser.add_argument('--auto', action='store_true', help='find windows from the transcript')
    parser.add_argument('--replace', action='store_true', help='drop existing clips not given here')
    args = parser.parse_args()
    if not args.mood and not args.auto:
        parser.error('give --mood windows, --auto, or both (hand-picked windows win)')
    initialize()
    profile = next((p for p in profiles() if p['name'] == args.name), None)
    if profile is None:
        raise SystemExit(f'No voice named {args.name!r}. Import it first with import_voice_assets.py.')
    source = Path(args.source).expanduser() if args.source else DATA / profile['original']
    if not source.is_file():
        raise SystemExit(f'No such recording: {source}')
    before = digest(source)

    print(f'\n=== {profile["name"]} · mood clips ===', flush=True)
    print(f'  source   {source.name}', flush=True)
    detail = transcribe_detailed(source)
    words = all_words(detail)
    windows = auto_windows(detail) if args.auto else {}
    for text in args.mood:
        name, start, end = parse_window(text)
        windows[name] = (start, end)

    folder = DATA / 'voices' / profile['id'] / ('moods-' + identifier()[:12])
    clips = {m['mood']: m for m in ([] if args.replace else profile.get('moods') or [])}
    for name in sorted(windows, key=lambda m: moods.ORDER.index(m) if m in moods.ORDER else 99):
        start, end = windows[name]
        window = fixed_window(detail, start, end)
        inside = [w for w in words if start <= w['start'] and w['end'] <= end]
        cut_start, cut_end = padded(words, inside[0]['start'], inside[-1]['end'])
        reference = folder / name / 'reference.wav'
        details = prepare_reference(source, reference, round(cut_start, 3), round(cut_end - cut_start, 3))
        heard = transcribe_detailed(reference)['text'].strip()
        agreement = similarity(window['text'], heard)
        # Condition on the words in the clip we actually saved, as import_voice_assets does.
        transcript = window['text'] if agreement >= 0.95 else heard
        clips[name] = {'mood': name, 'reference': str(reference.relative_to(DATA)),
                       'transcript': transcript, 'seconds': round(details['seconds'], 2),
                       'start': round(cut_start, 2), 'end': round(cut_end, 2),
                       'transcript_agreement': agreement}
        print(f"  {name:<8} {cut_start:7.2f}-{cut_end:7.2f} s ({details['seconds']:5.2f} s) "
              f"match={agreement:.3f}  {transcript}", flush=True)
        if details.get('warning'):
            print(f"           {details['warning']}", flush=True)

    profile['moods'] = [clips[m] for m in moods.ORDER if m in clips] + \
                       [clips[m] for m in sorted(set(clips) - set(moods.ORDER))]
    save_profile(profile)
    assert digest(source) == before, 'the source recording was modified'
    print(f"  saved    {len(profile['moods'])} mood clip(s); original unchanged (sha256 verified)", flush=True)


if __name__ == '__main__':
    main()
