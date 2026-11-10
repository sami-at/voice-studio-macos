"""Regression cases for confirmed processing, verification and direction failures."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
import soundfile as sf
from voice_studio import audio, direction, storage, text, verify, worker


def soft_edges():
    # Quiet /h/, /f/, /s/-like energy around a louder vowel, with known full bounds.
    rng = np.random.default_rng(7)
    quiet = rng.uniform(-.0005, .0005, 4800).astype('float32')
    vowel = (.2 * np.sin(np.arange(12000) * .1)).astype('float32')
    return np.r_[np.zeros(2400), quiet, vowel, quiet, np.zeros(2400)].astype('float32')


def natural_edges():
    # The same quiet consonants around a vowel that rises and falls like a spoken one.
    rng = np.random.default_rng(7)
    quiet = rng.uniform(-.0005, .0005, 4800).astype('float32')
    vowel = (.2 * np.hanning(12000) * np.sin(np.arange(12000) * .1)).astype('float32')
    return np.r_[np.zeros(2400), quiet, vowel, quiet, np.zeros(2400)].astype('float32')


def test_polish_keeps_quiet_attack_decay_and_sample_order():
    raw = soft_edges()
    result = audio.polish_segment(raw)
    core = result[1920:1920+len(raw)]
    gain = np.dot(core, raw) / np.dot(raw, raw)
    np.testing.assert_allclose(core, raw * gain, atol=1e-7)
    assert np.count_nonzero(core) == np.count_nonzero(raw)


def test_assembly_preserves_quiet_consonants_below_old_threshold(tmp_path):
    raw = soft_edges()
    sf.write(tmp_path/'section.wav', raw, audio.RATE, subtype='PCM_24')
    decoded, _ = sf.read(tmp_path/'section.wav', dtype='float32')
    session = {'segments':[{'file':'section.wav','text':'Have you finished?'}]}
    audio.join_segments(session,tmp_path,tmp_path/'out.wav')
    out, _ = sf.read(tmp_path/'out.wav',dtype='float32')
    start,end = audio.speech_bounds(tmp_path/'section.wav')
    first = np.flatnonzero(np.abs(out) > audio.SILENCE)[0]
    np.testing.assert_array_equal(out[first:first+end-start], decoded[start:end])
    assert end-start >= 21590  # includes both 200 ms quiet consonants


def test_raw_edge_activity_is_flagged_and_never_faded():
    raw = np.full(2400, .04, dtype='float32')
    check = audio.boundary_check(raw)
    assert check['head_at_boundary'] and check['tail_at_boundary']
    result = audio.polish_segment(raw)
    assert result[1920] == result[1920+2399] != 0


@pytest.mark.parametrize('speed',[.75,1.04,1.25])
def test_tempo_filter_preserves_final_event(tmp_path,speed):
    # A final event followed by guard silence must survive FFmpeg's filter drain.
    t=np.arange(2400)/audio.RATE
    pulse=(.1*np.sin(2*np.pi*300*t)*np.hanning(2400)).astype('float32')
    raw=np.r_[pulse,np.zeros(12000),pulse]
    path=tmp_path/'tempo.wav'
    audio.write_segment(raw,path,speed)
    x,_=sf.read(path)
    active=np.flatnonzero(np.abs(x)>.01)
    assert active[-1]/audio.RATE > .60/speed
    assert np.max(np.abs(x[round(.60/speed*audio.RATE):]))>.02


@pytest.mark.parametrize('script',['Hi [pause:','Hi {bad|}', 'Hi [unknown]', 'Hi [pause:no]'])
def test_malformed_directions_block_splitting(script):
    with pytest.raises(ValueError): text.split_script(script)


def test_pause_offsets_follow_cleaned_text_and_do_not_merge_words():
    plan=direction.parse('  One   [pause:0.4]two  [pause:0.6]three.')
    assert plan.spoken == 'One two three.'
    assert plan.pauses == [(3,.4),(7,.6)]


def test_single_line_pause_is_a_boundary():
    pieces=text.split_script('First sentence.\n[pause:0.4]\nSecond sentence.')
    assert len(pieces)==2 and pieces[1]['lead_pause']==.4


def test_long_pronunciation_cannot_be_split_inside_markup():
    script=('Some words before a {representation|very long spoken representation} '
            'and nuclei[say:new clee eye] with a conclusion.')
    pieces=text.split_script(script,limit=45)
    assert all(direction.parse(p['text']).ok for p in pieces)
    assert ' '.join(direction.parse(p['text']).spoken for p in pieces)==direction.parse(script).spoken


def test_pause_edit_reuses_legacy_take_but_word_edit_invalidates():
    original='Wait[pause:0.4] now.'
    seg={'text':original}
    storage.add_take(seg,{'text':original,'file':'old.wav','text_hash':storage.text_fingerprint(original)})
    seg['text']='Wait[pause:0.9] now.'
    assert not storage.segment_is_stale(seg)
    seg['text']='Wait[pause:0.9] later.'
    assert storage.segment_is_stale(seg)
    assert len(seg['takes'])==1


def test_section_edit_serialization_preserves_boundary_pauses():
    script='First.\n\n[pause:0.4]\n\nSecond.\n\n[pause:0.7]'
    chunks=text.split_script(script)
    chunks[1]['text']='Different words.'
    restored=text.split_script(text.session_script(chunks))
    assert restored==chunks


def test_alignment_never_guesses_from_character_position(tmp_path):
    sf.write(tmp_path/'x.wav',soft_edges(),audio.RATE)
    with pytest.raises(ValueError,match='locate'):
        audio.split_at_pauses(tmp_path/'x.wav','Wait now.',[(4,.4)],0,0)


def test_aligned_pause_inserts_exact_samples_and_keeps_original_audio(tmp_path):
    tone=np.full(2400,.1,dtype='float32')
    x=np.r_[tone,np.zeros(4800),tone]
    sf.write(tmp_path/'x.wav',x,audio.RATE,subtype='PCM_24')
    timing=[{'word':'Wait','start':0,'end':.1},{'word':'now','start':.3,'end':.4}]
    seg={'file':'x.wav','text':'Wait[pause:0.4] now.','word_timing':timing}
    pause=audio.split_at_pauses(tmp_path/'x.wav','Wait now.',[(4,.4)],0,0,word_timing=timing)
    assert len(pause)==1 and .1*audio.RATE<pause[0][0]<.3*audio.RATE
    audio.join_segments({'segments':[seg]},tmp_path,tmp_path/'paused.wav')
    seg['text']='Wait now.'
    audio.join_segments({'segments':[seg]},tmp_path,tmp_path/'plain.wav')
    assert sf.info(tmp_path/'paused.wav').frames-sf.info(tmp_path/'plain.wav').frames==9600
    y,_=sf.read(tmp_path/'paused.wav'); original,_=sf.read(tmp_path/'plain.wav')
    np.testing.assert_array_equal(y[y!=0],original[original!=0])


def test_inline_pause_refuses_continuous_speech(tmp_path):
    sf.write(tmp_path/'x.wav',np.full(24000,.05),audio.RATE)
    with pytest.raises(ValueError,match='quiet'):
        audio.split_at_pauses(tmp_path/'x.wav','Wait now.',[(4,.4)],0,0,
            word_timing=[{'word':'Wait','start':0,'end':.5},{'word':'now','start':.5,'end':1}])


def test_valid_candidate_wins_over_higher_coverage_failed_edge():
    assert verify.candidate_rank({'ok':True,'coverage':.95,'similarity':.95}) > verify.candidate_rank({'ok':False,'coverage':.99,'similarity':.99})


def test_asr_edge_substitution_is_uncertain_not_claimed_missing():
    result=verify.compare('Most people can hear this ending.', 'Must people can hear this ending.')
    assert not result['ok']
    assert 'not confirmed' in verify.describe(result,0)
    assert 'are missing' not in verify.describe(result,0)


def setup_worker(monkeypatch,tmp_path,heard):
    import types
    mx=SimpleNamespace(clear_cache=lambda:None,get_peak_memory=lambda:0)
    mlx=types.ModuleType('mlx'); mlx.core=mx
    monkeypatch.setitem(sys.modules,'mlx',mlx); monkeypatch.setitem(sys.modules,'mlx.core',mx)
    monkeypatch.setattr(worker,'DATA',tmp_path); monkeypatch.setattr(storage,'DATA',tmp_path)
    monkeypatch.setattr(worker.engines,'available',lambda:['qwen3'])
    class Host:
        def __init__(self,**kw): pass
        def load(self,*a): pass
        def release(self): pass
        def synthesize(self,*a,**kw): return natural_edges()
    monkeypatch.setattr(worker.engines,'EngineHost',Host)
    events=[]; monkeypatch.setattr(worker,'emit',lambda kind,**kw:events.append((kind,kw)))
    responses=iter(heard)
    monkeypatch.setattr(worker,'transcribe',lambda *a,**kw:{'text':next(responses),'words':[]})
    sf.write(tmp_path/'reference.wav',soft_edges(),audio.RATE)
    profile={'id':'hal','name':'Hal','reference':'reference.wav','transcript':'Original words.'}
    session=text.new_session('Have you ever wondered why flies rub their hands together?', 'Regression',profile)
    storage.save_session(session)
    return session,events


def test_failed_regeneration_keeps_previously_valid_selection_and_bounds_retries(monkeypatch,tmp_path):
    s,events=setup_worker(monkeypatch,tmp_path,['different words']*3)
    seg=s['segments'][0]
    audio.write_segment(soft_edges(),tmp_path/'valid.wav')
    storage.add_take(seg,{'file':'valid.wav','seconds':1.,'text':seg['text'],
                         'text_hash':storage.text_fingerprint(seg['text']),'verified':True,'seed':4})
    old=seg['selected_take']; storage.save_session(s)
    worker.generate({'session':str(storage.session_path(s)),'indices':[0],'attempts':100})
    saved=storage.read_json(storage.session_path(s))['segments'][0]
    assert saved['selected_take']==old and saved['file']=='valid.wav'
    assert len(saved['takes'])==2 and saved['takes'][-1]['attempts']==3
    assert (tmp_path/'valid.wav').exists()
    assert any(k=='incomplete' for k,_ in events)


def test_unknown_verification_does_not_claim_pass(monkeypatch,tmp_path):
    s,events=setup_worker(monkeypatch,tmp_path,[])
    worker.generate({'session':str(storage.session_path(s))})
    saved=storage.read_json(storage.session_path(s))['segments'][0]
    assert saved['verified'] is None
    assert any(k=='warning' and 'could not be checked' in v['message'] for k,v in events)


def test_regenerate_legacy_take_with_no_seed_preserves_old_audio(monkeypatch,tmp_path):
    s,events=setup_worker(monkeypatch,tmp_path,['Have you ever wondered why flies rub their hands together?'])
    seg=s['segments'][0]
    audio.write_segment(soft_edges(),tmp_path/'legacy.wav')
    storage.add_take(seg,{'file':'legacy.wav','seconds':1.,'text':seg['text'],
                         'text_hash':storage.text_fingerprint(seg['text']),'verified':True})
    assert seg['seed'] is None
    storage.save_session(s)
    worker.generate({'session':str(storage.session_path(s)),'indices':[0],'regenerate':True})
    saved=storage.read_json(storage.session_path(s))['segments'][0]
    assert len(saved['takes'])==2 and (tmp_path/'legacy.wav').is_file()
    assert saved['seed']==43 and saved['verified'] is True


def test_legacy_pause_offsets_do_not_invalidate_identical_spoken_words():
    import hashlib
    words='One two three.'
    pauses=[(8,.4),(13,.6)]
    stamp=hashlib.sha256((words+'\x1f'+';'.join(f'{o}:{s}' for o,s in pauses)).encode()).hexdigest()[:16]
    seg={'text':'One[pause:0.8] two[pause:0.6] three.'}
    take={'spoken':words,'text_hash':stamp,'pauses':pauses}
    assert not storage.take_is_stale(seg,take)
    seg['text']='One[pause:0.8] two[pause:0.6] four.'
    assert storage.take_is_stale(seg,take)


def test_direct_assembly_rejects_stale_audio_before_replacing_output(tmp_path):
    sf.write(tmp_path/'old.wav',soft_edges(),audio.RATE)
    target=tmp_path/'out.wav';target.write_bytes(b'prior narration')
    seg={'text':'New words.','file':'old.wav','text_hash':storage.text_fingerprint('Old words.')}
    with pytest.raises(ValueError,match='stale'):
        audio.join_segments({'segments':[seg]},tmp_path,target)
    assert target.read_bytes()==b'prior narration'


def test_engine_release_collects_cycles_before_clearing_cache(monkeypatch):
    import types, weakref
    from voice_studio.engines import EngineHost
    class Model: pass
    model=Model();model.cycle=model;ref=weakref.ref(model)
    host=EngineHost();host.model=model;host.engine='qwen3';del model
    observed=[];mx=SimpleNamespace(clear_cache=lambda:observed.append(ref() is None))
    mlx=types.ModuleType('mlx');mlx.core=mx
    monkeypatch.setitem(sys.modules,'mlx',mlx);monkeypatch.setitem(sys.modules,'mlx.core',mx)
    host.release()
    assert host.model is None and host.engine is None and observed==[True]


def test_new_reference_trim_retains_quiet_attack_and_decay():
    raw=soft_edges()
    np.testing.assert_array_equal(audio.edge_trim(raw),raw)


def test_style_gap_uses_actual_retained_padding(tmp_path, monkeypatch):
    monkeypatch.setattr(audio, 'RAMP_SECONDS', 0)   # gap arithmetic only; the ramp has its own tests
    x=np.full(2400,.05,dtype='float32')
    sf.write(tmp_path/'x.wav',x,audio.RATE,subtype='PCM_24')
    segs=[{'file':'x.wav','text':'First.'},{'file':'x.wav','text':'Second.'}]
    audio.join_segments({'segments':segs,'sentence_pause':.3},tmp_path,tmp_path/'out.wav')
    y,_=sf.read(tmp_path/'out.wav');active=np.flatnonzero(np.abs(y)>.01)
    gap=np.max(np.diff(active))-1
    assert gap==7200


def test_trailing_inline_marker_replaces_style_gap_even_before_punctuation(tmp_path):
    x=np.r_[np.zeros(2400),np.full(2400,.05),np.zeros(2400)]
    sf.write(tmp_path/'x.wav',x,audio.RATE,subtype='PCM_24')
    segs=[{'file':'x.wav','text':'First[pause:0.4].'},{'file':'x.wav','text':'Second.'}]
    audio.join_segments({'segments':segs,'sentence_pause':.3},tmp_path,tmp_path/'out.wav')
    y,_=sf.read(tmp_path/'out.wav');active=np.flatnonzero(np.abs(y)>.01)
    # .4 inserted plus .01 retained on both sides, with no additional style gap.
    assert (np.max(np.diff(active))-1)==10080


def test_hard_split_does_not_strand_an_article_or_preposition():
    script='We carefully explain this important idea to the curious listener in plain language.'
    limit=len('We carefully explain this important idea to the')
    chunks=text.split_script(script,limit=limit)
    assert not chunks[0]['text'].endswith((' the',' to'))
    assert ' '.join(c['text'] for c in chunks)==script


def test_natural_quiet_counts_towards_style_without_deleting_it(tmp_path, monkeypatch):
    monkeypatch.setattr(audio, 'RAMP_SECONDS', 0)   # gap arithmetic only; the ramp has its own tests
    # Low room tone must survive, but need not gain another full style pause on top.
    x=np.r_[np.full(2400,.05),np.full(7200,.0002)]
    sf.write(tmp_path/'x.wav',x,audio.RATE,subtype='PCM_24')
    audio.join_segments({'segments':[{'file':'x.wav','text':'One.'},{'file':'x.wav','text':'Two.'}],
                         'sentence_pause':.3},tmp_path,tmp_path/'out.wav')
    y,_=sf.read(tmp_path/'out.wav');active=np.flatnonzero(np.abs(y)>.01)
    assert np.max(np.diff(active))-1==7200
    assert np.count_nonzero((y>0)&(y<.001))==14400


def test_non_latin_expected_words_cannot_pass_as_empty():
    assert verify.normalize('你好世界。') == ['你好世界']
    assert not verify.compare('你好世界。','')['ok']
    assert verify.normalize('Ça va très bien.')==['ça','va','très','bien']


@pytest.mark.parametrize('engine,expected',[('qwen3','french'),('chatterbox','fr')])
def test_narration_language_is_forwarded_to_each_engine(monkeypatch,engine,expected):
    import types
    from voice_studio.engines import EngineHost
    calls=[]
    class Model:
        def generate(self,**kw):
            calls.append(kw)
            yield SimpleNamespace(sample_rate=24000,audio=np.zeros(100,dtype='float32'))
    host=EngineHost();monkeypatch.setattr(host,'load',lambda _:Model())
    mx=SimpleNamespace(float32=np.float32,random=SimpleNamespace(seed=lambda _:None))
    mlx=types.ModuleType('mlx');mlx.core=mx
    monkeypatch.setitem(sys.modules,'mlx',mlx);monkeypatch.setitem(sys.modules,'mlx.core',mx)
    host.synthesize(engine,'Bonjour.','reference.wav','Bonjour.',42,language='French')
    assert calls[0]['lang_code']==expected


def voiced(seconds, level=.2, decay=None, attack=None):
    t = np.arange(int(seconds * audio.RATE)) / audio.RATE
    x = level * np.sin(2 * np.pi * 180 * t)
    if decay:
        x *= np.exp(-np.maximum(0, t - (seconds - decay)) / (decay / 6))
    if attack:
        x *= np.minimum(1, t / attack)
    return x.astype('float32')


def test_abrupt_stop_is_flagged_even_when_the_final_sample_is_silent():
    # The decoders pad with near-silence, so the last sample says nothing about a dead stop.
    stopped = np.r_[voiced(1.0), np.zeros(4800)].astype('float32')
    check = audio.boundary_check(stopped)
    assert not check['tail_at_boundary']          # the old single-sample test is blind to it
    assert check['tail_abrupt'] and check['tail_decay_db'] > audio.ABRUPT_TAIL_DB


def test_natural_decay_and_gradual_attack_are_not_flagged():
    natural = np.r_[voiced(1.0, decay=.2, attack=.05), np.zeros(4800)].astype('float32')
    check = audio.boundary_check(natural)
    assert not check['tail_abrupt'] and check['tail_decay_db'] < -25
    assert not check['head_abrupt']


def test_abrupt_start_is_flagged():
    check = audio.boundary_check(np.r_[np.zeros(4800), voiced(1.0, decay=.2)].astype('float32'))
    assert check['head_abrupt'] and not check['tail_abrupt']


def test_edge_diagnostics_never_alter_or_reject_audio():
    raw = np.r_[voiced(1.0), np.zeros(4800)].astype('float32')
    before = raw.copy()
    audio.boundary_check(raw)
    np.testing.assert_array_equal(raw, before)
    # Too little audible signal: no verdict, and no crash.
    quiet = audio.boundary_check(np.full(2400, 1e-6, dtype='float32'))
    assert quiet['tail_decay_db'] is None and not quiet['tail_abrupt'] and not quiet['head_abrupt']
    for key in ('head_at_boundary', 'tail_at_boundary', 'peak', 'dc_mean'):
        assert key in quiet                       # existing keys keep their meaning


def test_a_take_that_stops_abruptly_is_flagged_kept_and_retried(monkeypatch, tmp_path):
    s, events = setup_worker(monkeypatch, tmp_path, ['Have you ever wondered why flies rub their hands together?'] * 3)
    calls = []

    def synthesize(self, *a, **kw):
        calls.append(1)
        return soft_edges() if len(calls) == 1 else natural_edges()    # first stops dead, second finishes
    monkeypatch.setattr(worker.engines.EngineHost, 'synthesize', synthesize, raising=False)
    monkeypatch.setattr(worker, 'transcribe', lambda *a, **kw: {
        'text': 'Have you ever wondered why flies rub their hands together?', 'words': []})
    worker.generate({'session': str(storage.session_path(s)), 'indices': [0]})
    saved = storage.read_json(storage.session_path(s))['segments'][0]
    assert len(calls) == 2                                   # retried with another seed
    take = storage.selected_take(saved)
    assert take['verified'] is True and take['attempts'] == 2
    assert not [f for f in take['quality'] if f['code'] == 'abrupt_end']
    first = take['attempt_files'][0]
    assert 'abrupt_end' in first['check']['abrupt'] and first['check']['ok'] is False
    assert (tmp_path / first['raw_file']).is_file()          # the cut-off recording is kept, not deleted


def test_edge_ramp_touches_only_an_audible_outer_3ms_and_never_the_stored_take(tmp_path):
    take = np.r_[np.full(2400, .05), np.zeros(4800)].astype('float32')    # starts at audible level
    sf.write(tmp_path / 'take.wav', take, audio.RATE, subtype='PCM_24')
    stored = (tmp_path / 'take.wav').read_bytes()
    audio.join_segments({'segments': [{'file': 'take.wav', 'text': 'One.'}]}, tmp_path, tmp_path / 'out.wav')
    out, _ = sf.read(tmp_path / 'out.wav', dtype='float32')
    first = np.flatnonzero(np.abs(out) > 1e-7)[0]
    ramp = int(audio.RATE * audio.RAMP_SECONDS)
    assert out[first] < .001 and abs(out[first + ramp + 10] - .05) < 1e-6          # ramped in, then untouched
    assert (tmp_path / 'take.wav').read_bytes() == stored                           # the take is never rewritten
    assert audio.join_segments.last_edges_ramped == 1


def test_edge_ramp_leaves_a_naturally_decaying_take_untouched(tmp_path):
    take = natural_edges()
    sf.write(tmp_path / 'take.wav', take, audio.RATE, subtype='PCM_24')
    decoded, _ = sf.read(tmp_path / 'take.wav', dtype='float32')
    audio.join_segments({'segments': [{'file': 'take.wav', 'text': 'One.'}]}, tmp_path, tmp_path / 'out.wav')
    out, _ = sf.read(tmp_path / 'out.wav', dtype='float32')
    start, end = audio.speech_bounds(tmp_path / 'take.wav')
    first = np.flatnonzero(np.abs(out) > audio.SILENCE)[0]
    np.testing.assert_array_equal(out[first:first + end - start], decoded[start:end])
    assert audio.join_segments.last_edges_ramped == 0


def test_a_ramp_does_not_hide_a_cut_off_take_from_the_quality_flags():
    stopped = np.r_[voiced(1.0), np.zeros(4800)].astype('float32')
    ramped, did = audio.edge_ramp(stopped[:24000], False)
    assert did
    from voice_studio import quality
    codes = [f['code'] for f in quality.analyze_take(stopped)]
    assert 'abrupt_end' in codes            # flags read the stored take, which the ramp never edits


# ---------------------------------------------------------------- [pace:] and unsupported marks

@pytest.mark.parametrize('mark,factor', [('slow', .93), ('normal', 1.0), ('fast', 1.07)])
def test_pace_mark_is_parsed_removed_from_speech_and_scaled(mark, factor):
    plan = direction.parse(f'It looks suspicious. [pace:{mark}]')
    assert plan.spoken == 'It looks suspicious.' and plan.pace == mark and plan.pace_factor == factor
    assert not plan.problems


def test_conflicting_or_malformed_pace_is_reported_not_ignored():
    assert 'only one' in ' '.join(direction.parse('[pace:slow] A. [pace:fast] B.').problems)
    assert direction.parse('[pace:medium] A.').problems
    assert direction.parse('Plain words.').pace is None


@pytest.mark.parametrize('mark', ['[delivery:curious]', '[emphasis:taste]', '[emotion:happy]', '[whisper:on]', '[breath:soft]'])
def test_marks_no_engine_can_honour_are_refused_with_a_reason(mark):
    plan = direction.parse(f'{mark} Why do flies rub their hands?')
    assert plan.problems and 'not supported' in plan.problems[0]
    assert mark in plan.spoken            # left visible, never silently dropped


def test_changing_pace_never_makes_a_recording_stale():
    plain = storage.spoken_fingerprint('Flies taste with their feet.')
    paced = storage.spoken_fingerprint('Flies taste with their feet. [pace:slow]')
    assert plain == paced
    seg = {'text': 'Flies taste with their feet. [pace:slow]', 'takes': []}
    take = {'id': 't', 'spoken_hash': plain}
    assert not storage.take_is_stale(seg, take)


def test_pace_change_retimes_from_the_saved_raw_take_as_a_new_take(monkeypatch, tmp_path):
    s, events = setup_worker(monkeypatch, tmp_path, ['Have you ever wondered why flies rub their hands together?'])
    worker.generate({'session': str(storage.session_path(s)), 'indices': [0]})
    saved = storage.read_json(storage.session_path(s))
    first = storage.selected_take(saved['segments'][0])
    assert first['pace_factor'] == 1.0
    saved['segments'][0]['text'] += ' [pace:slow]'
    storage.save_session(saved)
    calls = []
    monkeypatch.setattr(worker.engines.EngineHost, 'synthesize', lambda *a, **k: calls.append(1), raising=False)
    worker.generate({'session': str(storage.session_path(s))})
    after = storage.read_json(storage.session_path(s))['segments'][0]
    assert not calls                                            # no model was involved
    assert len(after['takes']) == 2                             # the first take is kept
    new, old = storage.selected_take(after), storage.takes_of(after)[0]
    assert old['id'] == first['id'] and (tmp_path / old['file']).is_file()
    assert new['pace'] == 'slow' and new['retimed_from'] == first['id']
    longer = sf.info(tmp_path / new['file']).duration / sf.info(tmp_path / old['file']).duration
    assert abs(longer - 1 / .93) < .03                          # the stretch asked for (short fixture: filter windowing ~2%)
    raw_before = sf.read(tmp_path / old['raw_file'])[0]
    np.testing.assert_array_equal(raw_before, sf.read(tmp_path / new['raw_file'])[0])   # same raw recording
    # Asking for the same pace again changes nothing.
    worker.generate({'session': str(storage.session_path(s))})
    assert len(storage.read_json(storage.session_path(s))['segments'][0]['takes']) == 2


def test_a_take_whose_last_word_is_cut_is_retried_and_kept(monkeypatch, tmp_path):
    s, events = setup_worker(monkeypatch, tmp_path, ['Have you ever wondered why flies rub their hands together?'] * 3)
    rng = np.random.default_rng(1)
    cut = np.r_[np.zeros(2400), natural_edges()[2400:-2400 - 4800][:-1200],
                (.05 * rng.standard_normal(2400)).astype('float32'), np.zeros(1600)].astype('float32')
    calls = []

    def synthesize(self, *a, **kw):
        calls.append(1)
        return cut if len(calls) == 1 else natural_edges()
    monkeypatch.setattr(worker.engines.EngineHost, 'synthesize', synthesize, raising=False)
    monkeypatch.setattr(worker, 'transcribe', lambda *a, **kw: {
        'text': 'Have you ever wondered why flies rub their hands together?', 'words': []})
    worker.generate({'session': str(storage.session_path(s)), 'indices': [0]})
    saved = storage.read_json(storage.session_path(s))['segments'][0]
    take = storage.selected_take(saved)
    assert len(calls) == 2 and take['verified'] is True
    first = take['attempt_files'][0]
    assert 'cut_ending' in first['check']['abrupt'] and (tmp_path / first['raw_file']).is_file()


def test_a_cut_older_take_does_not_beat_a_regeneration(monkeypatch, tmp_path):
    s, events = setup_worker(monkeypatch, tmp_path, ['Have you ever wondered why flies rub their hands together?'] * 3)
    seg = s['segments'][0]
    rng = np.random.default_rng(2)
    cut = np.r_[np.zeros(2400), natural_edges()[2400:-7200], (.05 * rng.standard_normal(2400)).astype('float32'),
                np.zeros(1600)].astype('float32')
    sf.write(tmp_path / 'old.raw.wav', cut, audio.RATE, subtype='FLOAT')
    audio.write_segment(cut, tmp_path / 'old.wav')
    storage.add_take(seg, {'file': 'old.wav', 'raw_file': 'old.raw.wav', 'seconds': 1., 'text': seg['text'],
                           'text_hash': storage.text_fingerprint(seg['text']), 'verified': True, 'seed': 4})
    old_id = seg['selected_take']
    storage.save_session(s)
    monkeypatch.setattr(worker.engines.EngineHost, 'synthesize', lambda *a, **k: cut, raising=False)   # every retry cut too
    worker.generate({'session': str(storage.session_path(s)), 'indices': [0], 'regenerate': True})
    saved = storage.read_json(storage.session_path(s))['segments'][0]
    assert saved['selected_take'] != old_id and len(saved['takes']) == 2     # old take kept, not preferred
    assert (tmp_path / 'old.wav').is_file()
