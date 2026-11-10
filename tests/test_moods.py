from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import import_voice_moods as mood_importer
from voice_studio import moods
from voice_studio.text import new_session

CLIPS = [{'mood': m, 'reference': f'voices/v/moods/{m}/reference.wav', 'transcript': f'{m} words'}
         for m in ('neutral', 'excited', 'sad', 'angry', 'scared', 'playful', 'warm', 'calm')]


@pytest.mark.parametrize('text, expected', [
    ('It was the third of June when everything changed.', 'neutral'),
    ('No way! I got in! I actually got in!', 'excited'),
    ('The joy was gone, and the tears nobody ever saw.', 'sad'),
    ("That's ridiculous. No, absolutely not!", 'angry'),
    ('Shh... did you hear that? Something moved behind the door.', 'scared'),
    ("Sure, brilliant plan. What could possibly go wrong?", 'playful'),
    ('Oh my goodness, thank you so much.', 'warm'),
    ('I guess grandpa was right after all.', 'calm'),
    ('Have you ever wondered why the sky is blue?', 'neutral'),
    ('This is wonderful!', 'excited'),
    ('{Dr.|Doctor} Shh[say:shush] spoke [pause:0.4] gently.', 'calm'),
])
def test_detect_reads_the_words(text, expected):
    assert moods.detect(text) == expected


def test_detect_is_limited_to_available_moods():
    assert moods.detect('The joy was gone, tears everywhere.', {'neutral', 'excited'}) == 'neutral'
    assert moods.detect('No way! We did it!', {'neutral'}) == 'neutral'


def test_resolve_auto_manual_and_fallback():
    session = {'reference': 'main.wav', 'transcript': 'main words', 'moods': CLIPS}
    assert moods.resolve(session, {'text': 'Thank you, thank you!'})[0] == 'warm'
    mood, reference, transcript = moods.resolve(session, {'text': 'Thank you!', 'mood': 'sad'})
    assert (mood, reference, transcript) == ('sad', 'voices/v/moods/sad/reference.wav', 'sad words')
    # A mood the voice does not have, or a voice with no clips, uses the main reference.
    assert moods.resolve(session, {'text': 'x', 'mood': 'robot'}) == (None, 'main.wav', 'main words')
    plain = {'reference': 'main.wav', 'transcript': 'main words'}
    assert moods.resolve(plain, {'text': 'No way! We did it!'}) == (None, 'main.wav', 'main words')


def test_new_session_copies_mood_clips_without_sharing_them():
    profile = {'id': 'v', 'name': 'V', 'reference': 'main.wav', 'transcript': 't', 'moods': CLIPS}
    session = new_session('Hello there.', 'Title', profile)
    assert session['moods'] == CLIPS and session['moods'][0] is not CLIPS[0]
    assert 'mood' not in session['segments'][0]          # Auto until the user picks one
    assert new_session('Hi.', 'T', {**profile, 'moods': None})['moods'] == []


def test_names_follow_display_order():
    assert moods.names({'moods': list(reversed(CLIPS))}) == list(moods.ORDER)
    assert moods.names({}) == []


def test_padding_never_reaches_a_neighbouring_word():
    words = [{'start': 0.0, 'end': 1.0}, {'start': 1.1, 'end': 2.0}, {'start': 2.06, 'end': 3.0}]
    start, end = mood_importer.padded(words, 1.1, 2.0)
    assert 1.0 < start < 1.1 and 2.0 < end < 2.06
    assert mood_importer.padded(words, 0.0, 3.0) == (0.0, 3.0 + mood_importer.TAIL)


def test_auto_windows_take_one_clean_run_per_mood():
    def segment(text, start, end):
        step = (end - start) / len(text.split())
        return {'text': text, 'words': [{'start': start + i * step, 'end': start + (i + 1) * step,
                                         'probability': 0.95} for i, _ in enumerate(text.split())]}
    result = {'segments': [segment('It was a normal day at the office with nothing going on at all.', 0, 9),
                           segment('No way! We did it! I cannot believe we actually won it all!', 9.5, 16),
                           segment('The joy was gone. Tears, nobody saw the tears.', 17, 19)]}
    windows = mood_importer.auto_windows(result)
    assert set(windows) == {'neutral', 'excited'}          # the sad run is too short to clone from
    assert windows['excited'] == (9.5, 16)
