"""Chatterbox Energetic Explainer pacing (25 Oct): 1.10x speed and dead-air trimming for NEW takes only."""
import sys, types
from types import SimpleNamespace
import numpy as np
import pytest
import soundfile as sf
from voice_studio import audio, storage, styles, text, worker
from tests_helpers import natural_take

RATE = audio.RATE


def test_only_chatterbox_in_energetic_explainer_is_tuned():
    assert styles.engine_tuning('chatterbox', styles.ENERGETIC) == {'speed_factor': 1.10, 'dead_air_guard_s': 0.12}
    for engine, style in (('qwen3', styles.ENERGETIC), ('chatterbox', styles.NATURAL), ('chatterbox', styles.CUSTOM),
                          ('chatterbox', styles.DOCUMENTARY), ('qwen3', styles.NATURAL)):
        assert styles.engine_tuning(engine, style) == {}


def run_worker(monkeypatch, tmp_path, engine, style, text_script='One sentence here.', existing=None):
    monkeypatch.setattr(worker, 'DATA', tmp_path); monkeypatch.setattr(storage, 'DATA', tmp_path)
    monkeypatch.setattr(worker.engines, 'available', lambda: ['qwen3', 'chatterbox'])
    mx = SimpleNamespace(clear_cache=lambda: None, get_peak_memory=lambda: 0)
    mlx = types.ModuleType('mlx'); mlx.core = mx
    monkeypatch.setitem(sys.modules, 'mlx', mlx); monkeypatch.setitem(sys.modules, 'mlx.core', mx)
    calls = []

    class Host:
        def __init__(self, **kw): self.before_load = self.on_chunk = None
        def load(self, *a): pass
        def release(self): pass
        def synthesize(self, *a, **kw): calls.append(1); return natural_take()
    monkeypatch.setattr(worker.engines, 'EngineHost', Host)
    monkeypatch.setattr(worker, 'emit', lambda *a, **k: None)
    monkeypatch.setattr(worker, 'transcribe', lambda *a, **k: {'text': text_script, 'words': []})
    sf.write(tmp_path / 'reference.wav', np.tile(natural_take(), 4), RATE)     # long enough for the 1.15x reference
    profile = {'id': 'hal', 'name': 'Hal', 'reference': 'reference.wav', 'transcript': 'Words.'}
    session = existing or text.new_session(text_script, 'Pacing', profile, style=style, engine=engine)
    storage.save_session(session)
    worker.generate({'session': str(storage.session_path(session))})
    return storage.read_json(storage.session_path(session)), calls


def test_a_new_chatterbox_energetic_take_records_its_speed_and_dead_air_guard(monkeypatch, tmp_path):
    saved, _ = run_worker(monkeypatch, tmp_path, 'chatterbox', styles.ENERGETIC)
    take = storage.selected_take(saved['segments'][0])
    assert take['speed_used'] == round(1.04 * 1.10, 4) and take['engine_speed_factor'] == 1.10
    assert take['dead_air_guard_s'] == .12 and saved['segments'][0]['dead_air_guard_s'] == .12


@pytest.mark.parametrize('engine,style,speed', [('qwen3', styles.ENERGETIC, 1.04), ('chatterbox', styles.NATURAL, 1.0)])
def test_qwen3_and_natural_style_are_unchanged(monkeypatch, tmp_path, engine, style, speed):
    saved, _ = run_worker(monkeypatch, tmp_path, engine, style)
    take = storage.selected_take(saved['segments'][0])
    assert take['speed_used'] == speed and take['dead_air_guard_s'] is None and take['engine_speed_factor'] == 1.0


def test_emptying_the_table_reverts_to_the_previous_behaviour(monkeypatch, tmp_path):
    monkeypatch.setattr(styles, 'ENGINE_TUNING', {})
    saved, _ = run_worker(monkeypatch, tmp_path, 'chatterbox', styles.ENERGETIC)
    take = storage.selected_take(saved['segments'][0])
    assert take['speed_used'] == 1.04 and take['dead_air_guard_s'] is None


def test_an_existing_take_is_neither_regenerated_nor_retimed(monkeypatch, tmp_path):
    saved, calls = run_worker(monkeypatch, tmp_path, 'chatterbox', styles.ENERGETIC)
    take = storage.selected_take(saved['segments'][0])
    old = take.copy()
    for k in ('engine_speed_factor', 'dead_air_guard_s', 'speed_used'):   # make it look like a pre-change take
        take.pop(k, None)
    storage.sync_selected(saved['segments'][0]) if hasattr(storage, 'sync_selected') else None
    storage.save_session(saved)
    again, calls2 = run_worker(monkeypatch, tmp_path, 'chatterbox', styles.ENERGETIC, existing=saved)
    assert len(calls2) == 0 and len(again['segments'][0]['takes']) == 1      # nothing new was recorded
    assert storage.selected_take(again['segments'][0])['file'] == old['file']


def section_with_dead_air(seconds=.45, click=False):
    """Speech that decays naturally, then ~-90 dB near-silence like Chatterbox's ending."""
    rng = np.random.default_rng(5)
    dead = (10 ** (-90 / 20) * rng.standard_normal(int(seconds * RATE))).astype('float32')
    if click:
        dead[-500] = .002                                    # one faint sample, far below -60 dB as 10 ms RMS
    return np.r_[natural_take()[:-2400], dead].astype('float32')


def assemble(tmp_path, guard, lead=None, name='out.wav', click=False):
    x = section_with_dead_air(click=click)
    sf.write(tmp_path / 'a.wav', x, RATE, subtype='PCM_24'); sf.write(tmp_path / 'b.wav', x, RATE, subtype='PCM_24')
    segs = [{'file': 'a.wav', 'text': 'One.', 'paragraph_end': True, 'dead_air_guard_s': guard},
            {'file': 'b.wav', 'text': 'Two.', 'paragraph_end': True, 'dead_air_guard_s': guard,
             **({'lead_pause': lead} if lead is not None else {})}]
    audio.join_segments({'segments': segs, 'pause': .34, 'sentence_pause': .18}, tmp_path, tmp_path / name)
    return sf.read(tmp_path / name, dtype='float32')[0], x


def test_dead_air_is_trimmed_but_the_decay_is_kept_exactly(tmp_path):
    out, x = assemble(tmp_path, .12)
    old, _ = assemble(tmp_path, None, name='old.wav')
    assert len(out) < len(old) - int(.25 * RATE)                              # dead air gone from the gap
    end = audio.decay_end(tmp_path / 'a.wav')
    first = np.flatnonzero(np.abs(out) > audio.SILENCE)[0]
    start, _ = audio.speech_bounds(tmp_path / 'a.wav')
    decoded = sf.read(tmp_path / 'a.wav', dtype='float32')[0]
    np.testing.assert_array_equal(out[first:first + end - start], decoded[start:end])   # every audible sample kept
    gap = np.diff(np.flatnonzero(np.abs(out) > 1e-3)).max() / RATE
    assert .30 <= gap <= .50                                                  # roughly the style's 0.34 s


def test_untagged_takes_assemble_exactly_as_before(tmp_path):
    a, _ = assemble(tmp_path, None, name='one.wav')
    b, _ = assemble(tmp_path, None, name='two.wav')
    np.testing.assert_array_equal(a, b)
    x = section_with_dead_air()
    assert len(a) > 2 * len(x)                                               # the whole tail is still there


def test_an_explicit_pause_is_still_inserted_exactly(tmp_path):
    long, _ = assemble(tmp_path, .12, lead=.8, name='long.wav')
    short, _ = assemble(tmp_path, .12, lead=.4, name='short.wav')
    # [pause:n] inserts exactly n seconds (in addition to kept natural quiet), trimming or not
    assert len(long) - len(short) == int(.4 * RATE)


def test_faint_dead_air_beyond_the_trim_does_not_lengthen_the_gap(tmp_path):
    clean, _ = assemble(tmp_path, .12, name='clean.wav')
    clicked, _ = assemble(tmp_path, .12, name='click.wav', click=True)
    # quiet that is trimmed away must not count as "no retained quiet" and add the full style gap again
    assert len(clicked) == len(clean)
