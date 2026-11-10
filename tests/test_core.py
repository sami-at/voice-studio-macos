from pathlib import Path
import json
import re
import numpy as np
import pytest
import soundfile as sf
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import import_voice_assets as importer
from voice_studio import direction, engines, styles, verify
from voice_studio.text import break_after, new_session, split_script
from voice_studio.storage import (add_take, atomic_json, choose_take, ensure_takes,
                                  fresh_takes, has_reference, read_script, segment_is_stale,
                                  segment_needs_audio, selected_take, slug, take_is_stale,
                                  takes_of, text_fingerprint)
from voice_studio.audio import (RATE, conditioned_reference, convert, prepare_reference,
                                join_segments, write_segment, export_audio, waveform)

@pytest.mark.parametrize('script', [
    '', 'Hello world.', 'Dr. Green paid $3.14. “Really?” Yes!',
    ('A calm sentence, with punctuation; then another sentence!\n\n' * 2000),
    'a' * 1500, '你好。世界！' * 300, 'One\nline\n\nSecond paragraph.',
])
def test_segments_preserve_all_nonwhitespace(script):
    pieces = split_script(script)
    assert all(0 < len(piece['text']) <= 260 for piece in pieces)
    assert re.sub(r'\s+', '', ''.join(p['text'] for p in pieces)) == re.sub(r'\s+', '', script)
    if pieces:
        assert pieces[-1]['paragraph_end']

def test_paragraphs():
    assert [p['paragraph_end'] for p in split_script('One.\n\nTwo.')] == [True, True]

def test_clause_on_limit_boundary():
    text = 'x' * 40 + ',' + 'x' * 39 + ',tail'
    assert all(len(p['text']) <= 80 for p in split_script(text, limit=80))

def test_txt_bom_and_unicode(tmp_path):
    for encoding in ['utf-8-sig', 'utf-16']:
        path = tmp_path / (encoding + '.txt')
        path.write_text('Narration — café 你好', encoding=encoding)
        assert read_script(path) == 'Narration — café 你好'
    (tmp_path / 'invalid.txt').write_bytes(b'\xffhello')
    with pytest.raises(ValueError, match='UTF'):
        read_script(tmp_path / 'invalid.txt')

def test_atomic_storage_and_safe_names(tmp_path):
    target = tmp_path / 'new' / 'data.json'
    atomic_json(target, {'text': 'é'})
    atomic_json(target, {'text': '你好'})
    assert json.loads(target.read_text())['text'] == '你好'
    assert not list(target.parent.glob('.saving-*'))
    assert '/' not in slug('../../my narrations')

@pytest.fixture
def tone(tmp_path):
    path = tmp_path / 'source.wav'
    t = np.arange(RATE * 4) / RATE
    audio = (.12 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    sf.write(path, np.concatenate([np.zeros(RATE), audio, np.zeros(RATE)]), RATE)
    return path

@pytest.mark.parametrize('extension', ['wav', 'mp3', 'm4a'])
def test_audio_import_formats_and_prepare(tmp_path, tone, extension):
    source = tone
    if extension != 'wav':
        source = tmp_path / ('input.' + extension)
        codec = ['-c:a', 'libmp3lame'] if extension == 'mp3' else ['-c:a', 'aac']
        convert(['-i', tone, *codec, source])
    prepared = tmp_path / 'prepared.wav'
    info = prepare_reference(source, prepared, duration=6)
    assert 4 <= info['seconds'] <= 4.3
    audio, rate = sf.read(prepared)
    assert rate == RATE and audio.ndim == 1
    assert 0.01 < np.max(np.abs(audio)) < .95
    assert tone.exists()

def test_silence_rejected(tmp_path):
    path = tmp_path / 'silent.wav'
    sf.write(path, np.zeros(RATE * 4), RATE)
    with pytest.raises(ValueError, match='silent'):
        prepare_reference(path, tmp_path / 'prepared.wav')

def test_failed_preparation_preserves_existing_reference(tmp_path):
    target = tmp_path / 'existing.wav'
    target.write_bytes(b'existing user recording')
    source = tmp_path / 'invalid.mp3'
    source.write_bytes(b'not audio')
    with pytest.raises(RuntimeError, match='conversion failed'):
        prepare_reference(source, target)
    assert target.read_bytes() == b'existing user recording'

def test_failed_export_preserves_destination(tmp_path):
    target = tmp_path / 'existing.mp3'
    target.write_bytes(b'existing export')
    with pytest.raises(RuntimeError):
        export_audio(tmp_path / 'missing.wav', target)
    assert target.read_bytes() == b'existing export'

def test_incomplete_session_cannot_export(tmp_path):
    with pytest.raises(ValueError, match='every section'):
        join_segments({'segments': [{'file': None}], 'pause': .3}, tmp_path, tmp_path / 'out.wav')

def test_segment_join_and_export(tmp_path, tone):
    audio, rate = sf.read(tone, dtype='float32')
    normal, slow = tmp_path / 'one.wav', tmp_path / 'two.wav'
    n = write_segment(audio, normal)
    s = write_segment(audio, slow, .8)
    assert s > n * 1.15
    session = {'segments': [{'file': 'one.wav', 'text': 'One.', 'paragraph_end': True},
                            {'file': 'two.wav', 'text': 'Two.', 'paragraph_end': True}],
               'pause': .4, 'sentence_pause': .3}
    combined = tmp_path / 'combined.wav'
    duration = join_segments(session, tmp_path, combined)
    # Trimming each section's padding shortens the join slightly; the point here is that
    # both sections and the gap survive the round trip to WAV and MP3.
    expected = 4 + 4 / .8 + .4 + styles.LEAD_IN + styles.TAIL_ROOM
    assert expected - .08 < duration <= expected + .08, f'{duration:.3f}s against {expected:.3f}s'
    assert 1 <= len(waveform(combined)) <= 420
    for ext in ['wav', 'mp3']:
        output = tmp_path / ('export.' + ext)
        export_audio(combined, output)
        assert output.stat().st_size > 10000
        decoded = tmp_path / ('decoded-' + ext + '.wav')
        convert(['-i', output, '-c:a', 'pcm_s16le', decoded])
        assert abs(sf.info(decoded).duration - duration) < .2
        result, _ = sf.read(decoded)
        assert np.isfinite(result).all() and np.max(np.abs(result)) < 1


def test_style_presets_are_within_their_limits():
    for name in styles.ORDER:
        values = styles.settings(name)
        assert set(values) == set(styles.CONTROLS)
        for control, value in values.items():
            low, high = styles.LIMITS[control]
            assert low <= value <= high, (name, control, value)


def test_energetic_is_faster_and_tighter_than_natural():
    natural, energetic = styles.settings(styles.NATURAL), styles.settings(styles.ENERGETIC)
    assert energetic['reference_tempo'] > natural['reference_tempo']
    assert energetic['speed'] >= natural['speed']
    assert energetic['pause'] < natural['pause']
    assert energetic['sentence_pause'] < natural['sentence_pause']
    # Slowing the reference was measured to do nothing, so the slower styles must get
    # their pace from the post-generation stretch instead.
    for name in (styles.DOCUMENTARY, styles.STORYTELLING):
        slower = styles.settings(name)
        assert slower['speed'] < natural['speed'], name
        assert slower['pause'] > natural['pause'], name
        assert slower['reference_tempo'] <= natural['reference_tempo'], name


@pytest.mark.parametrize('control,value,expected', [
    ('speed', 99, styles.LIMITS['speed'][1]), ('speed', 0, styles.LIMITS['speed'][0]),
    ('reference_tempo', 'nonsense', 1.0), ('sentence_pause', -5, 0.0),
])
def test_out_of_range_settings_are_clamped(control, value, expected):
    assert styles.clamp(control, value) == pytest.approx(expected)
    assert styles.settings(styles.NATURAL, {control: value})[control] == pytest.approx(expected)


def test_overrides_switch_a_preset_to_custom():
    assert styles.matches(styles.ENERGETIC, styles.settings(styles.ENERGETIC))
    drifted = {**styles.settings(styles.ENERGETIC), 'speed': 1.20}
    assert not styles.matches(styles.ENERGETIC, drifted)
    assert not styles.matches(styles.CUSTOM, styles.settings(styles.CUSTOM))
    assert styles.settings('a style that does not exist') == styles.settings(styles.NATURAL)


def test_session_records_the_style_it_was_made_with():
    profile = {'id': 'v1', 'name': 'Test', 'reference': 'r.wav', 'transcript': 'words'}
    session = new_session('One. Two.', 'Demo', profile, styles.ENERGETIC)
    assert session['style'] == styles.ENERGETIC
    assert session['settings'] == styles.settings(styles.ENERGETIC)
    # Legacy fields must agree with the style, since assembly still reads them.
    assert session['speed'] == session['settings']['speed']
    assert session['pause'] == session['settings']['pause']
    assert session['sentence_pause'] == session['settings']['sentence_pause']
    plain = new_session('One. Two.', 'Demo', profile)
    assert plain['style'] == styles.NATURAL


def silence_profile(path, threshold=0.012, shortest=0.02):
    """Leading silence, the gaps between sounds, and the room left at the end.

    Runs below `shortest` are ignored: a waveform dips under any threshold twice a cycle,
    and those are zero crossings, not pauses.
    """
    audio, rate = sf.read(path, dtype='float32')
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    loud = np.flatnonzero(np.abs(audio) > threshold)
    if not len(loud):
        return 0.0, [], len(audio) / rate
    leading = loud[0] / rate
    trailing = (len(audio) - loud[-1] - 1) / rate
    gaps, count = [], 0
    for value in np.abs(audio[loud[0]:loud[-1] + 1]) <= threshold:
        if value:
            count += 1
        elif count:
            if count / rate >= shortest:
                gaps.append(count / rate)
            count = 0
    return leading, gaps, trailing


def clean_tone(seconds=1.0):
    """Continuous tone with no silence of its own, so padding can be controlled exactly."""
    t = np.arange(int(RATE * seconds)) / RATE
    return (.12 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def padded_segment(path, audio=None, lead=0.1, tail=0.1):
    """A section written the way the worker writes one, silence padding included."""
    audio = clean_tone() if audio is None else audio
    quiet_lead = np.zeros(int(RATE * lead), dtype='float32')
    quiet_tail = np.zeros(int(RATE * tail), dtype='float32')
    sf.write(path, np.concatenate([quiet_lead, audio, quiet_tail]), RATE, subtype='PCM_24')
    return audio


def test_the_gap_between_sections_is_the_pause_that_was_asked_for(tmp_path):
    """The padding inside each section used to be added on top of every pause."""
    for name in ('one.wav', 'two.wav'):
        padded_segment(tmp_path / name)
    session = {'segments': [{'file': 'one.wav', 'text': 'A finished sentence.',
                             'paragraph_end': False},
                            {'file': 'two.wav', 'text': 'Another one.', 'paragraph_end': True}],
               'pause': .5, 'sentence_pause': .30}
    combined = tmp_path / 'joined.wav'
    join_segments(session, tmp_path, combined)
    leading, gaps, trailing = silence_profile(combined)
    assert gaps, 'no gap was found between the sections'
    # 0.30 s asked for; before this fix the same session produced about 0.50 s.
    assert abs(gaps[0] - 0.30) < 0.05, f'gap was {gaps[0]:.3f}s, expected 0.30s'
    assert leading < 0.2 and trailing >= 0.25


def test_a_narration_ends_with_room_rather_than_stopping_dead(tmp_path):
    padded_segment(tmp_path / 'one.wav', tail=0.1)
    session = {'segments': [{'file': 'one.wav', 'text': 'The experiment is over.',
                             'paragraph_end': True}], 'pause': .5, 'sentence_pause': .30}
    combined = tmp_path / 'joined.wav'
    join_segments(session, tmp_path, combined)
    _, _, trailing = silence_profile(combined)
    assert trailing >= 0.25, f'only {trailing:.3f}s of room after the last word'


def test_closely_related_sections_are_joined_more_tightly_than_sentences(tmp_path):
    gaps = {}
    for kind, first in (('sentence', 'A finished sentence.'),
                        ('clause', 'a trailing clause,'),
                        ('mid', 'a hard split with no punctuation')):
        for name in ('one.wav', 'two.wav'):
            padded_segment(tmp_path / name)
        session = {'segments': [{'file': 'one.wav', 'text': first, 'paragraph_end': False},
                                {'file': 'two.wav', 'text': 'and the rest.',
                                 'paragraph_end': True}],
                   'pause': .5, 'sentence_pause': .30}
        combined = tmp_path / f'joined-{kind}.wav'
        join_segments(session, tmp_path, combined)
        _, runs, _ = silence_profile(combined)
        gaps[kind] = max(runs or [0])
    assert gaps['sentence'] > gaps['clause'] > gaps['mid'], gaps
    assert gaps['mid'] < 0.12, f"a mid-sentence split left {gaps['mid']:.3f}s of silence"


def test_assembly_keeps_every_sample_of_speech(tmp_path):
    """Trimming padding must never shorten the speech itself."""
    audio = padded_segment(tmp_path / 'one.wav', lead=0.1, tail=0.1)
    session = {'segments': [{'file': 'one.wav', 'text': 'Hello.', 'paragraph_end': True}],
               'pause': .5, 'sentence_pause': .30}
    combined = tmp_path / 'joined.wav'
    join_segments(session, tmp_path, combined)
    joined, _ = sf.read(combined, dtype='float32')
    loud_in = np.flatnonzero(np.abs(audio) > 0.012)
    loud_out = np.flatnonzero(np.abs(joined) > 0.012)
    speech_in = (loud_in[-1] - loud_in[0]) / RATE
    speech_out = (loud_out[-1] - loud_out[0]) / RATE
    assert abs(speech_out - speech_in) < 0.01, f'{speech_in:.3f}s of speech became {speech_out:.3f}s'


@pytest.mark.parametrize('text,paragraph,expected', [
    ('A finished sentence.', False, 'sentence'), ('Really?', False, 'sentence'),
    ('He said "stop."', False, 'sentence'), ('a trailing clause,', False, 'clause'),
    ('a list item;', False, 'clause'), ('no punctuation here', False, 'mid'),
    ('End of the paragraph.', True, 'paragraph'), ('', False, 'mid'),
])
def test_break_classification(text, paragraph, expected):
    assert break_after({'text': text, 'paragraph_end': paragraph}) == expected


def test_pause_policy_orders_breaks_sensibly():
    for name in (styles.NATURAL, styles.ENERGETIC, styles.DOCUMENTARY, styles.STORYTELLING):
        v = styles.settings(name)
        gaps = {k: styles.gap_after(k, v) for k in ('paragraph', 'sentence', 'clause', 'mid')}
        assert gaps['paragraph'] > gaps['sentence'] > gaps['clause'] > gaps['mid'] >= 0, (name, gaps)


def test_reference_conditioning_changes_length_and_is_reused(tmp_path, tone):
    source = tmp_path / 'reference.wav'
    convert(['-i', tone, '-ac', 1, '-ar', RATE, '-c:a', 'pcm_s16le', source])
    assert conditioned_reference(source, 1.0, tmp_path) == source
    faster = conditioned_reference(source, 1.15, tmp_path)
    assert faster != source and faster.is_file()
    assert sf.info(faster).duration < sf.info(source).duration
    stamp = faster.stat().st_mtime_ns
    assert conditioned_reference(source, 1.15, tmp_path) == faster
    assert faster.stat().st_mtime_ns == stamp, 'an existing conditioned reference was rebuilt'


def test_a_profile_without_a_recording_is_listed_but_not_usable():
    assert not has_reference({'reference': ''})
    assert not has_reference({})
    assert not has_reference({'reference': 'voices/missing/nope.wav'})


def _spoken(start, end, text, confidence=0.99, gap=0.0):
    """A Whisper-shaped segment whose words tile the span evenly."""
    count = max(1, len(text.split()))
    step = (end - start) / count
    words = []
    at = start
    for piece in text.split():
        words.append({'word': piece, 'start': at, 'end': at + step - gap,
                      'probability': confidence})
        at += step
    return {'start': start, 'end': end, 'text': text, 'words': words}


def test_window_choice_prefers_a_complete_sentence():
    result = {'segments': [
        _spoken(0.0, 3.0, 'a half thought that trails off and'),
        _spoken(3.0, 15.0, 'This is a complete sentence that runs for a comfortable length.'),
    ]}
    window = importer.choose_window(result)
    assert window['text'].endswith('.')
    assert window['start'] >= 3.0
    assert importer.SPAN[0] <= window['seconds'] <= importer.SPAN[1]


def test_window_choice_avoids_the_noisier_passage():
    clean = _spoken(0.0, 12.0, 'Clean confident speech all the way through this passage here.',
                    confidence=0.99)
    noisy = _spoken(12.0, 24.0, 'Muffled uncertain speech all the way through this passage here.',
                    confidence=0.35)
    assert importer.choose_window({'segments': [clean, noisy]})['start'] == 0.0
    # Order must not decide it.
    flipped = {'segments': [_spoken(0.0, 12.0, 'Muffled uncertain speech all the way through '
                                               'this passage here.', confidence=0.35),
                            _spoken(12.0, 24.0, 'Clean confident speech all the way through '
                                                'this passage here.', confidence=0.99)]}
    assert importer.choose_window(flipped)['start'] == 12.0


def test_window_choice_refuses_when_nothing_is_long_enough():
    with pytest.raises(SystemExit):
        importer.choose_window({'segments': [_spoken(0.0, 1.2, 'Too short.')]})
    with pytest.raises(SystemExit):
        importer.choose_window({'segments': []})


def test_window_reports_silence_and_confidence():
    window = importer.choose_window({'segments': [
        _spoken(0.0, 12.0, 'A steady passage of speech with very little dead air in it.')]})
    assert 0 < window['speech_fraction'] <= 1
    assert 0 < window['confidence'] <= 1
    assert window['seconds'] == pytest.approx(window['end'] - window['start'], abs=0.01)


@pytest.mark.parametrize('expected,heard,floor', [
    ('the brain rebuilds a memory', 'the brain rebuilds a memory', 1.0),
    ('the brain rebuilds a memory', 'The Brain rebuilds a memory!', 1.0),
    ('the brain rebuilds a memory', 'completely different words entirely', 0.0),
])
def test_transcript_similarity(expected, heard, floor):
    assert importer.similarity(expected, heard) == pytest.approx(floor, abs=0.26)


SENTENCE = ('Most people never notice this, but the human eye blinks far less when you stare '
            'at a screen, and that single habit is the reason your eyes feel dry at the end '
            'of the day.')


@pytest.mark.parametrize('heard', [
    # Real transcriber output measured from generated audio on this machine. None of these
    # are missing speech, and none of them may be reported as such.
    "most people never notice this but the human eye blink's far less when you stare at a "
    "screen and that single habit is the reason your eyes feel dry at the end of the day",
    "Most people never notice this, but the human eye blinks far less when you stare at a "
    "screen, and that single habit is the reason your eyes feel dry at the end of the day.",
])
def test_transcription_quirks_are_not_reported_as_missing_audio(heard):
    assert verify.compare(SENTENCE, heard)['ok']


def test_contractions_and_digits_normalise_together():
    assert verify.normalize("There's 20 of them") == verify.normalize('there is twenty of them')
    assert verify.normalize("blink's") == verify.normalize('blinks')
    assert verify.normalize("It's") == ['it', 'is']
    assert verify.normalize('') == []


@pytest.mark.parametrize('cut,where', [(2, 'start'), (4, 'start'), (2, 'end'), (5, 'end')])
def test_truncated_speech_is_detected(cut, where):
    words = SENTENCE.split()
    heard = ' '.join(words[cut:] if where == 'start' else words[:-cut])
    result = verify.compare(SENTENCE, heard)
    assert not result['ok'], f'{cut} words lost at the {where} slipped through'
    assert (not result['head_ok']) if where == 'start' else (not result['tail_ok'])
    assert verify.describe(result, 0)


def test_even_one_lost_edge_word_needs_review():
    words = SENTENCE.split()
    assert not verify.compare(SENTENCE, ' '.join(words[1:]))['ok']
    assert not verify.compare(SENTENCE, ' '.join(words[:-1]))['ok']
    assert not verify.compare(SENTENCE, ' '.join(words[2:]))['ok']
    assert not verify.compare(SENTENCE, ' '.join(words[:-2]))['ok']


def test_dropped_middle_and_empty_audio_are_detected():
    words = SENTENCE.split()
    gutted = verify.compare(SENTENCE, ' '.join(words[:10] + words[20:]))
    assert not gutted['ok'] and gutted['coverage'] < verify.COVERAGE_FLOOR
    silence = verify.compare(SENTENCE, '')
    assert not silence['ok'] and silence['coverage'] == 0
    assert not silence['head_ok'] and not silence['tail_ok']
    assert 'Section 3' in verify.describe(silence, 2)


def test_empty_expected_text_never_fails():
    assert verify.compare('', 'anything at all')['ok']


def test_describe_is_quiet_when_everything_matched():
    assert verify.describe(verify.compare(SENTENCE, SENTENCE), 0) == ''


def test_describe_handles_a_stored_partial_check():
    """A saved section keeps only part of the check; describing it must not explode."""
    full = verify.compare(SENTENCE, ' '.join(SENTENCE.split()[4:]))
    stored = {k: full[k] for k in ('ok', 'similarity', 'coverage', 'head_ok', 'tail_ok',
                                   'missing_at_start', 'missing_at_end', 'missing')}
    assert 'Section 2' in verify.describe(stored, 1)
    assert verify.describe({}, 0) == ''
    assert verify.describe(None, 0) == ''
    assert verify.describe({'ok': False}, 0).startswith('Section 1')


def test_fingerprint_tracks_wording_not_formatting():
    assert text_fingerprint('Hello there.') == text_fingerprint('  Hello   there.  ')
    assert text_fingerprint('Hello there.') == text_fingerprint('Hello\nthere.')
    assert text_fingerprint('Hello there.') != text_fingerprint('Hello there!')
    assert text_fingerprint('Hello there.') != text_fingerprint('hi how are you')
    assert text_fingerprint('') == text_fingerprint('   ')


def test_edited_text_marks_its_old_audio_stale(tmp_path, tone):
    """The bug: a section's words were edited but it kept the previous recording."""
    audio_file = tmp_path / 'one.wav'
    audio, _ = sf.read(tone, dtype='float32')
    write_segment(audio, audio_file)
    segment = {'text': 'the original wording', 'file': 'one.wav',
               'text_hash': text_fingerprint('the original wording')}
    assert not segment_is_stale(segment)
    assert not segment_needs_audio(segment, tmp_path)

    segment['text'] = 'hi how are you'          # edited in the app, audio untouched
    assert segment_is_stale(segment)
    assert segment_needs_audio(segment, tmp_path), 'edited section was not queued for generating'


def test_missing_audio_still_needs_generating(tmp_path):
    assert segment_needs_audio({'text': 'words', 'file': None}, tmp_path)
    assert segment_needs_audio({'text': 'words', 'file': 'gone.wav'}, tmp_path)
    # A section from before fingerprints existed is left alone rather than force-regenerated.
    (tmp_path / 'legacy.wav').write_bytes(b'x')
    assert not segment_needs_audio({'text': 'words', 'file': 'legacy.wav'}, tmp_path)
    assert not segment_is_stale({'text': 'words', 'file': 'legacy.wav'})


def a_take(text='the words', engine='qwen3', file='take.wav', **extra):
    return {'id': extra.pop('id', 'take-' + file), 'engine': engine, 'file': file,
            'text': text, 'text_hash': text_fingerprint(text), 'seconds': 1.0,
            'created': '2026-10-21T00:00:00+00:00', 'verified': True,
            'engine_config': extra.pop('engine_config', {}), **extra}


def test_an_older_section_gains_a_take_from_the_audio_it_already_had():
    """Existing projects must open without the user migrating anything."""
    legacy = {'text': 'the words', 'file': 'old.wav', 'seconds': 2.0,
              'text_hash': text_fingerprint('the words'), 'verified': True, 'seed': 42}
    ensure_takes(legacy)
    assert len(takes_of(legacy)) == 1
    take = selected_take(legacy)
    assert take['file'] == 'old.wav' and take['engine'] == 'qwen3'
    assert legacy['selected_take'] == take['id']
    # A section that never had audio gets an empty list, not a phantom take.
    empty = {'text': 'nothing yet', 'file': None}
    assert takes_of(empty) == [] and selected_take(empty) is None


def test_a_new_take_never_removes_an_earlier_one():
    segment = {'text': 'the words', 'file': None}
    add_take(segment, a_take(file='qwen.wav', engine='qwen3'))
    add_take(segment, a_take(file='cbx.wav', engine='chatterbox',
                             engine_config={'exaggeration': 0.5}))
    assert [t['file'] for t in takes_of(segment)] == ['qwen.wav', 'cbx.wav']
    assert segment['file'] == 'cbx.wav', 'the newest take should be in use'
    assert segment['engine'] == 'chatterbox'
    assert segment['engine_config'] == {'exaggeration': 0.5}


def test_choosing_a_take_switches_the_section_without_touching_the_others():
    segment = {'text': 'the words', 'file': None}
    add_take(segment, a_take(file='qwen.wav', engine='qwen3'))
    add_take(segment, a_take(file='cbx.wav', engine='chatterbox'))
    first = takes_of(segment)[0]['id']
    choose_take(segment, first)
    assert segment['file'] == 'qwen.wav' and segment['engine'] == 'qwen3'
    assert len(takes_of(segment)) == 2, 'switching must not discard a take'
    with pytest.raises(ValueError):
        choose_take(segment, 'a-take-that-does-not-exist')


def test_editing_the_words_makes_existing_takes_stale():
    segment = {'text': 'the words', 'file': None}
    add_take(segment, a_take(text='the words', file='qwen.wav'))
    assert not take_is_stale(segment, takes_of(segment)[0])
    assert fresh_takes(segment)

    segment['text'] = 'completely different words'
    assert take_is_stale(segment, takes_of(segment)[0])
    assert fresh_takes(segment) == []
    assert segment_is_stale(segment), 'the section itself should read as stale'
    # The recording is kept, not deleted, so going back to the old wording recovers it.
    assert len(takes_of(segment)) == 1
    segment['text'] = 'the words'
    assert not take_is_stale(segment, takes_of(segment)[0])


def test_takes_from_both_engines_keep_their_own_settings():
    segment = {'text': 'the words', 'file': None}
    add_take(segment, a_take(file='a.wav', engine='qwen3'))
    add_take(segment, a_take(file='b.wav', engine='chatterbox',
                             engine_config={'exaggeration': 0.9}))
    by_engine = {t['engine']: t for t in takes_of(segment)}
    assert by_engine['qwen3']['engine_config'] == {}
    assert by_engine['chatterbox']['engine_config'] == {'exaggeration': 0.9}


@pytest.mark.parametrize('value,expected', [
    (None, engines.EXAGGERATION_DEFAULT), (0.5, 0.5), (2.0, 1.0), (-1, 0.0),
    ('not a number', engines.EXAGGERATION_DEFAULT),
])
def test_chatterbox_settings_are_validated(value, expected):
    requested = {} if value is None else {'exaggeration': value}
    assert engines.config_for('chatterbox', requested)['exaggeration'] == pytest.approx(expected)
    assert engines.config_for('qwen3', requested) == {}, 'Qwen has no exaggeration setting'


def test_engine_names_fall_back_safely():
    assert engines.normalize('chatterbox') == 'chatterbox'
    assert engines.normalize('qwen3') == 'qwen3'
    assert engines.normalize('something-else') == engines.DEFAULT
    assert engines.normalize(None) == engines.DEFAULT
    assert engines.DEFAULT == 'qwen3', 'Qwen must stay the default engine'
    assert engines.label('chatterbox') and engines.label('qwen3')


# --- Voice Direction Language -------------------------------------------------------

def test_a_plain_script_passes_through_untouched():
    result = direction.parse('Hello there. How are you?')
    assert result.spoken == 'Hello there. How are you?'
    assert result.pauses == [] and result.overrides == [] and result.ok


@pytest.mark.parametrize('script,spoken,seconds', [
    ('But wait[pause:0.8] there is a reason.', 'But wait there is a reason.', 0.8),
    ('One[pause:0.25] two[pause:0.5] three.', 'One two three.', 0.75),
    ('[pause:1] Then it began.', 'Then it began.', 1.0),
])
def test_pause_markers_are_removed_from_the_spoken_text(script, spoken, seconds):
    result = direction.parse(script)
    assert result.spoken == spoken, 'a marker was spoken aloud'
    assert result.total_pause == pytest.approx(seconds)
    assert result.ok


def test_pause_offsets_point_at_the_right_place_in_the_spoken_text():
    result = direction.parse('But wait[pause:0.8] there is a reason.')
    offset, seconds = result.pauses[0]
    assert result.spoken[:offset] == 'But wait'
    assert seconds == 0.8


@pytest.mark.parametrize('script', ['Bad [pause:0] marker.', 'Bad [pause:99] marker.',
                                    'Bad [pause:-1] marker.'])
def test_out_of_range_pauses_are_rejected_not_guessed(script):
    result = direction.parse(script)
    assert not result.ok and result.pauses == []
    assert 'between' in result.problems[0]


@pytest.mark.parametrize('script,spoken,pair', [
    ('The {gigahertz|giga hertz} chip.', 'The giga hertz chip.', ('gigahertz', 'giga hertz')),
    ('He read nuclei[say:new clee eye] aloud.', 'He read new clee eye aloud.',
     ('nuclei', 'new clee eye')),
])
def test_pronunciation_overrides_replace_only_their_own_word(script, spoken, pair):
    result = direction.parse(script)
    assert result.spoken == spoken
    assert pair in result.overrides
    assert result.ok


def test_an_override_does_not_touch_the_same_word_elsewhere():
    result = direction.parse('A lead pipe made of {lead|led}, not lead.')
    assert result.spoken == 'A lead pipe made of led, not lead.'
    assert result.spoken.count('lead') == 2, 'other occurrences must be left alone'


def test_the_written_script_is_always_preserved():
    script = 'Wait[pause:0.4] for the {gigahertz|giga hertz} chip.'
    result = direction.parse(script)
    assert result.display == script, 'the script the user typed must not be rewritten'
    assert '[pause:' not in result.spoken and '{' not in result.spoken


@pytest.mark.parametrize('script,hint', [
    ('Unknown [emphasis:strong] marker.', 'not supported'),
    ('[say:orphan] leads the line.', 'no word before it'),
    ('{only-left|} is wrong.', 'both sides'),
])
def test_malformed_directions_are_reported_rather_than_ignored(script, hint):
    result = direction.parse(script)
    assert not result.ok
    assert any(hint in problem for problem in result.problems), result.problems


def test_unknown_markers_are_left_visible_so_the_mistake_shows():
    result = direction.parse('Unknown [emphasis:strong] marker.')
    assert '[emphasis:strong]' in result.spoken, 'a silent no-op would hide the mistake'


def test_directions_change_the_fingerprint_so_old_audio_goes_stale():
    base = text_fingerprint('Wait[pause:0.5] now.')
    assert base == text_fingerprint('Wait[pause:0.5] now.')
    assert base != text_fingerprint('Wait[pause:0.9] now.'), 'a new pause must restale audio'
    assert base != text_fingerprint('Wait now.'), 'removing a pause must restale audio'
    assert text_fingerprint('A{x|y}B') == text_fingerprint('AyB'), \
        'the same spoken words should not restale audio'


def test_a_section_of_only_directions_is_reported():
    result = direction.parse('[pause:0.5]')
    assert not result.ok and 'no words to speak' in result.problems[0]


@pytest.mark.parametrize('script,expected', [
    ('plain text', False), ('a[pause:0.5]b', True),
    ('a{x|y}b', True), ('a[say:z]b', True),
])
def test_has_directions_detects_markup(script, expected):
    assert direction.has_directions(script) is expected


# --- standalone pause markers between paragraphs -------------------------------------

REPORTED = ("Have you ever wondered why flies do that?\n\n"
            "[pause:0.4]\n\n"
            "Here's the explanation.")


def test_the_reported_standalone_pause_no_longer_makes_an_empty_section():
    """A paragraph of only [pause:n] used to become a section with nothing to say."""
    chunks = split_script(REPORTED)
    assert len(chunks) == 2, 'the timing-only paragraph should not be a section'
    assert chunks[0]['text'] == 'Have you ever wondered why flies do that?'
    assert chunks[1]['text'] == "Here's the explanation."
    assert chunks[1]['lead_pause'] == 0.4
    for chunk in chunks:
        assert direction.parse(chunk['text']).spoken.strip(), 'a section has no words to speak'


@pytest.mark.parametrize('script,texts,lead,trail', [
    ('[pause:0.5]\n\nFirst words.', ['First words.'], 0.5, None),
    ('Last words.\n\n[pause:0.7]', ['Last words.'], None, 0.7),
    ('One.\n\n[pause:0.3]\n\n[pause:0.2]\n\nTwo.', ['One.', 'Two.'], 0.5, None),
    ('One.\n\n[pause:0.25]\n\nTwo.', ['One.', 'Two.'], 0.25, None),
])
def test_standalone_pauses_at_any_position(script, texts, lead, trail):
    chunks = split_script(script)
    assert [c['text'] for c in chunks] == texts
    if lead is not None:
        target = chunks[1] if len(chunks) > 1 else chunks[0]
        assert target['lead_pause'] == pytest.approx(lead), 'consecutive markers should add up'
    if trail is not None:
        assert chunks[-1]['trail_pause'] == pytest.approx(trail)


def test_a_script_of_only_timing_makes_no_sections():
    assert split_script('[pause:0.5]') == []
    assert split_script('[pause:0.3]\n\n[pause:0.2]') == []


def test_a_standalone_pause_replaces_the_paragraph_gap_rather_than_adding_to_it(tmp_path):
    """The length asked for is the length heard, not that plus the style's own gap."""
    for name in ('one.wav', 'two.wav'):
        padded_segment(tmp_path / name)
    session = {'segments': [{'file': 'one.wav', 'text': 'One.', 'paragraph_end': True},
                            {'file': 'two.wav', 'text': 'Two.', 'paragraph_end': True,
                             'lead_pause': 0.9}],
               'pause': .5, 'sentence_pause': .30}
    combined = tmp_path / 'joined.wav'
    join_segments(session, tmp_path, combined)
    _, internal, _ = silence_profile(combined)
    assert internal, 'no gap between the sections'
    # 0.9 asked for; the style's paragraph pause of 0.5 must not be added on top.
    assert abs(internal[0] - 0.9) < 0.06, f'gap was {internal[0]:.3f}s, expected 0.9s'


def test_a_trailing_standalone_pause_extends_the_ending(tmp_path):
    padded_segment(tmp_path / 'one.wav')
    base = {'segments': [{'file': 'one.wav', 'text': 'One.', 'paragraph_end': True}],
            'pause': .5, 'sentence_pause': .30}
    plain = tmp_path / 'plain.wav'
    join_segments(base, tmp_path, plain)
    _, _, plain_tail = silence_profile(plain)

    base['segments'][0]['trail_pause'] = 0.6
    longer = tmp_path / 'longer.wav'
    join_segments(base, tmp_path, longer)
    _, _, long_tail = silence_profile(longer)
    assert long_tail - plain_tail == pytest.approx(0.6, abs=0.06)


def test_a_leading_standalone_pause_extends_the_opening(tmp_path):
    padded_segment(tmp_path / 'one.wav')
    base = {'segments': [{'file': 'one.wav', 'text': 'One.', 'paragraph_end': True}],
            'pause': .5, 'sentence_pause': .30}
    plain = tmp_path / 'plain.wav'
    join_segments(base, tmp_path, plain)
    plain_lead, _, _ = silence_profile(plain)

    base['segments'][0]['lead_pause'] = 0.5
    longer = tmp_path / 'longer.wav'
    join_segments(base, tmp_path, longer)
    long_lead, _, _ = silence_profile(longer)
    assert long_lead - plain_lead == pytest.approx(0.5, abs=0.06)


def test_changing_only_the_timing_leaves_the_sections_alone():
    """Section text and fingerprints must survive a pause-only edit, so takes are kept."""
    profile = {'id': 'v1', 'name': 'Test', 'reference': 'r.wav', 'transcript': 'words'}
    before = new_session(REPORTED, 'Demo', profile)
    after = new_session(REPORTED.replace('0.4', '0.9'), 'Demo', profile)
    assert [s['text'] for s in before['segments']] == [s['text'] for s in after['segments']]
    assert [text_fingerprint(s['text']) for s in before['segments']] == \
           [text_fingerprint(s['text']) for s in after['segments']], \
        'a timing-only change must not restale the recordings'
    assert before['segments'][1]['lead_pause'] == 0.4
    assert after['segments'][1]['lead_pause'] == 0.9


def test_a_standalone_pause_survives_saving_and_reopening(tmp_path):
    profile = {'id': 'v1', 'name': 'Test', 'reference': 'r.wav', 'transcript': 'words'}
    session = new_session(REPORTED, 'Demo', profile)
    path = tmp_path / 'project.json'
    atomic_json(path, session)
    reopened = json.loads(path.read_text())
    assert reopened['segments'][1]['lead_pause'] == 0.4
    assert len(reopened['segments']) == 2
