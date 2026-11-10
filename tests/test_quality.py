"""Review flags: each one must fire on a case built to trigger it and stay quiet on a normal take."""
import numpy as np
import pytest
import soundfile as sf
from voice_studio import audio, quality

RATE = audio.RATE


def speech(seconds=2.0, level=.2, f0=180, decay=.15, attack=.04):
    t = np.arange(int(seconds * RATE)) / RATE
    x = level * np.sin(2 * np.pi * f0 * t) * (1 + .3 * np.sin(2 * np.pi * 3 * t))
    x *= np.minimum(1, t / attack) * (np.exp(-np.maximum(0, t - (seconds - decay)) / (decay / 6)) if decay else 1)
    return x.astype('float32')


def codes(flags):
    return {f['code'] for f in flags}


def test_a_normal_take_raises_no_warnings():
    take = np.r_[np.zeros(2400), speech(3.0), np.zeros(4800)].astype('float32')
    flags = quality.analyze_take(take, words=9)
    assert not [f for f in flags if f['severity'] == 'warn'], flags


def test_clipping_is_counted():
    take = np.r_[np.zeros(2400), np.clip(speech(2.0, level=1.4), -1, 1), np.zeros(4800)].astype('float32')
    flag = next(f for f in quality.analyze_take(take, words=6) if f['code'] == 'clipping')
    assert flag['samples'] > 100


def test_a_long_silence_inside_speech_is_reported_but_a_comma_is_not():
    comma = np.r_[speech(1.0), np.zeros(int(.35 * RATE)), speech(1.0)].astype('float32')
    long = np.r_[speech(1.0), np.zeros(int(.9 * RATE)), speech(1.0)].astype('float32')
    assert 'long_internal_gap' not in codes(quality.analyze_take(comma, words=8))
    flag = next(f for f in quality.analyze_take(long, words=8) if f['code'] == 'long_internal_gap')
    assert .8 < flag['seconds'] < 1.0


@pytest.mark.parametrize('words,expected', [(2, True), (40, True), (8, False)])
def test_pace_outside_the_measured_range_is_flagged(words, expected):
    take = np.r_[np.zeros(2400), speech(3.0), np.zeros(4800)].astype('float32')
    assert ('unusual_pace' in codes(quality.analyze_take(take, words=words))) is expected


def test_repeated_words_are_found_only_when_the_script_does_not_repeat_them():
    take = np.r_[np.zeros(2400), speech(3.0), np.zeros(4800)].astype('float32')
    heard = 'Flies taste taste with their feet'
    flags = quality.analyze_take(take, words=6, heard=heard, spoken='Flies taste with their feet')
    assert next(f for f in flags if f['code'] == 'repeated_word')['words'] == ['taste']
    ok = quality.analyze_take(take, words=6, heard='Very very small', spoken='Very, very small')
    assert 'repeated_word' not in codes(ok)       # the script itself repeats it


def test_uneven_loudness_inside_a_take_is_flagged():
    loud, quiet = speech(1.0, level=.8), speech(1.0, level=.012)   # ~32 dB apart, both audible
    take = np.r_[np.zeros(2400), loud, quiet, loud, np.zeros(4800)].astype('float32')
    assert 'loudness_spread' in codes(quality.analyze_take(take, words=9))


def test_join_review_flags_a_loudness_step_but_not_a_matching_join():
    steady = {'level_db': -19.0, 'f0_median_hz': 180.0, 'centroid_hz': 750.0}
    assert not quality.review_boundary(steady, dict(steady), .4)
    louder = quality.review_boundary(steady, {**steady, 'level_db': -12.0}, .4)
    assert next(f for f in louder if f['code'] == 'loudness_jump')['jump_db'] == 7.0


def test_join_review_reports_pitch_timbre_and_gap_without_calling_them_errors():
    before = {'level_db': -19.0, 'f0_median_hz': 150.0, 'centroid_hz': 700.0}
    after = {'level_db': -19.0, 'f0_median_hz': 240.0, 'centroid_hz': 1400.0}
    found = {f['code']: f for f in quality.review_boundary(before, after, 2.4)}
    assert found['pitch_jump']['severity'] == 'note' and found['gap']['severity'] == 'note'
    assert found['timbre_change']['ratio'] == 2.0


def test_section_profile_measures_pitch_and_level_of_a_known_tone():
    profile = quality.section_profile(np.r_[np.zeros(2400), speech(2.0, f0=200), np.zeros(2400)].astype('float32'))
    assert abs(profile['f0_median_hz'] - 200) < 8
    assert -30 < profile['level_db'] < -10


def test_validate_export_passes_a_clean_export_and_catches_a_length_mismatch(tmp_path):
    narration = np.r_[np.zeros(2400), speech(3.0, level=.25), np.zeros(4800)].astype('float32')
    sf.write(tmp_path / 'narration.wav', narration, RATE, subtype='PCM_24')
    audio.export_audio(tmp_path / 'narration.wav', tmp_path / 'out.wav')
    audio.export_audio(tmp_path / 'narration.wav', tmp_path / 'out.mp3')
    for name in ('out.wav', 'out.mp3'):
        check = quality.validate_export(tmp_path / name, tmp_path / 'narration.wav', target_lufs=-18)
        assert check['measured']['clipped_samples'] == 0 and check['measured']['true_peak_db'] <= -1.0
        assert not [w for w in check['warnings'] if w['code'] in ('length', 'clipping')], check['warnings']
    sf.write(tmp_path / 'shorter.wav', narration[:RATE], RATE, subtype='PCM_24')
    mismatch = quality.validate_export(tmp_path / 'out.wav', tmp_path / 'shorter.wav')
    assert 'length' in codes(mismatch['warnings']) and not mismatch['ok']


def test_validate_export_rejects_missing_and_undecodable_files(tmp_path):
    assert not quality.validate_export(tmp_path / 'absent.wav')['ok']
    (tmp_path / 'junk.mp3').write_bytes(b'not audio' * 400)
    assert not quality.validate_export(tmp_path / 'junk.mp3')['ok']


def test_review_session_compares_neighbours_from_real_files(tmp_path):
    for name, level in (('a.wav', .2), ('b.wav', .02)):
        sf.write(tmp_path / name, np.r_[np.zeros(2400), speech(2.5, level=level), np.zeros(4800)], RATE, subtype='PCM_24')
    session = {'pause': .5, 'sentence_pause': .28, 'segments': [
        {'file': 'a.wav', 'text': 'One.', 'paragraph_end': True},
        {'file': 'b.wav', 'text': 'Two.', 'paragraph_end': True},
        {'file': None, 'text': 'Three.'}]}
    result = quality.review_session(session, tmp_path)
    assert len(result['sections']) == 3 and len(result['joins']) == 2
    assert 'loudness_jump' in codes(result['joins'][0]['flags'])
    assert 'no_audio' in codes(result['sections'][2]['flags'])
    assert result['joins'][0]['designed_gap_s'] == .5


# ---------------------------------------------------------------- cut endings (25 Oct)

def fricative(seconds, level=.05, seed=3):
    rng = np.random.default_rng(seed)
    return (level * rng.standard_normal(int(seconds * RATE))).astype('float32')


def test_a_final_sound_that_stops_dead_is_a_cut_ending():
    # a vowel, then an "s" that is cut off at full strength, then the decoder's digital silence
    take = np.r_[np.zeros(2400), speech(1.0, decay=.02), fricative(.12), np.zeros(1600)].astype('float32')
    stop, fall = audio.ending_stop(take)
    assert stop > audio.CUT_STOP_REL_DB and fall >= audio.CUT_FALL_DB
    flag = next(f for f in quality.analyze_take(take, words=4) if f['code'] == 'cut_ending')
    assert flag['severity'] == 'warn'
    assert audio.boundary_check(take)['tail_cut']


def test_a_naturally_fading_final_sound_is_not_a_cut():
    fade = np.r_[fricative(.12) * np.linspace(1, 0, int(.12 * RATE)) ** 3, np.zeros(1600)]
    take = np.r_[np.zeros(2400), speech(1.0, decay=.02), fade].astype('float32')
    assert audio.ending_stop(take)[0] <= audio.SHORT_STOP_REL_DB
    assert not {'cut_ending', 'short_ending'} & codes(quality.analyze_take(take, words=4))
    natural = np.r_[np.zeros(2400), speech(2.0), np.zeros(4800)].astype('float32')
    assert audio.ending_stop(natural)[0] <= audio.SHORT_STOP_REL_DB


def test_sound_running_to_the_last_sample_counts_as_cut():
    assert audio.ending_stop(np.r_[np.zeros(2400), speech(1.0, decay=0)].astype('float32'))[0] > audio.CUT_STOP_REL_DB


def test_a_shortened_decay_is_noted_not_retried():
    tail = fricative(.12, level=.004)                        # stops ~33 dB below the vowel
    take = np.r_[np.zeros(2400), speech(1.0, decay=.02), tail, np.zeros(1600)].astype('float32')
    found = {f['code']: f for f in quality.analyze_take(take, words=4)}
    assert 'short_ending' in found and found['short_ending']['severity'] == 'note' and 'cut_ending' not in found


def test_ranking_prefers_the_least_abrupt_of_failed_takes():
    from voice_studio import verify
    a = {'ok': False, 'coverage': 1.0, 'similarity': 1.0, 'cliff_db': 48.0}
    b = {'ok': False, 'coverage': 1.0, 'similarity': 1.0, 'cliff_db': 31.0}
    passing = {'ok': True, 'coverage': .95, 'similarity': .9}
    assert verify.candidate_rank(b) > verify.candidate_rank(a)
    assert verify.candidate_rank(passing) > verify.candidate_rank(b)
    assert 'last word stops dead' in verify.describe({**a, 'abrupt': ['cut_ending']}, 0)


@pytest.mark.parametrize('name,cut', [('sec02', True), ('sec05', True), ('sec06', True), ('sec03', False), ('sec10', False), ('sec08', False)])
def test_real_qwen3_endings_from_the_25_october_narration(name, cut):
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / f'samples/endings/experiments/{name}-streamed.wav'
    if not path.exists():
        pytest.skip('evaluation audio not present')
    x, _ = sf.read(path, dtype='float32')
    assert (audio.ending_stop(x)[0] > audio.CUT_STOP_REL_DB) is cut
