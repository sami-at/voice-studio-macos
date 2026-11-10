"""Smart resource management: admission, live monitoring, waiting, cleanup. No model is ever loaded.

Readings are mocked; the "worker" is tests/fake_worker.py, which only sleeps and prints events.
"""
import json, os, subprocess, sys, threading, time, types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from voice_studio import engines, jobs, resources, storage, worker, text

ROOT = Path(__file__).resolve().parents[1]
FAKE = [str(ROOT / 'tests' / 'fake_worker.py')]


def reading(**over):
    base = {'t': 100.0, 'free_percent': 45, 'swap_gb': 6.0, 'disk_gb': 50.0, 'other_workers': [], 'panic': None}
    return {**base, **over}


# ------------------------------------------------------------------ 1-6 admission

def test_1_normal_resources_are_admitted():
    assert resources.admission(['qwen3'], reading())[0] == resources.ADMIT
    assert resources.admission(['chatterbox'], reading(free_percent=30))[0] == resources.ADMIT


def test_2_low_memory_waits_rather_than_loading():
    decision, reason = resources.admission(['chatterbox'], reading(free_percent=25))
    assert decision == resources.WAIT and '25 %' in reason
    assert resources.admission(['qwen3'], reading(free_percent=25))[0] == resources.ADMIT   # lighter engine fits
    assert resources.admission(['qwen3'], reading(free_percent=10))[0] == resources.WAIT     # below the floor


def test_3_rapidly_growing_swap_waits_only_when_memory_is_also_low():
    history = [reading(t=40, swap_gb=6.0)]
    assert resources.admission(['qwen3'], reading(t=100, free_percent=25, swap_gb=8.5), history)[0] == resources.WAIT
    assert resources.admission(['qwen3'], reading(t=100, free_percent=45, swap_gb=8.5), history)[0] == resources.ADMIT
    assert resources.admission(['qwen3'], reading(t=100, swap_gb=18.0), [reading(t=40, swap_gb=18.0)])[0] == resources.ADMIT


def test_4_disk_space_waits_then_refuses():
    assert resources.admission(['qwen3'], reading(disk_gb=10))[0] == resources.WAIT
    assert resources.admission(['qwen3'], reading(disk_gb=4))[0] == resources.REFUSE


def test_5_another_generation_worker_refuses():
    decision, reason = resources.admission(['qwen3'], reading(other_workers=[4242]))
    assert decision == resources.REFUSE and 'one model' in reason


def test_5b_recent_unacknowledged_panic_needs_the_users_decision(tmp_path, monkeypatch):
    panic = tmp_path / 'panic-full-2026-10-24-233813.0002.panic'
    panic.write_text('{}')
    monkeypatch.setattr(resources, 'PANIC_DIRS', (tmp_path,))
    monkeypatch.setattr(resources, 'ACK_FILE', tmp_path / 'ack.json')
    name = resources.recent_unacknowledged_panic()
    assert name == panic.name
    assert resources.admission(['qwen3'], reading(panic=name))[0] == resources.REFUSE
    resources.acknowledge_panic()                                   # only called from the user's button
    assert resources.recent_unacknowledged_panic() is None
    assert resources.recent_unacknowledged_panic(now=time.time() + 4 * 86400) is None   # old panics expire


class FakeMx:
    """Stands in for mlx.core; counts what was loaded and released."""
    def __init__(self):
        self.cleared, self.random = 0, SimpleNamespace(seed=lambda _: None)
        self.metal = SimpleNamespace(is_available=lambda: True)
        self.gpu, self.float32 = 'gpu', np.float32

    def clear_cache(self): self.cleared += 1
    def set_default_device(self, _): pass
    def set_cache_limit(self, _): pass
    def get_active_memory(self): return 2_000_000_000
    def get_cache_memory(self): return 100_000_000
    def get_peak_memory(self): return 0


@pytest.fixture
def fake_mlx(monkeypatch, tmp_path):
    mx = FakeMx()
    loaded = []
    mlx = types.ModuleType('mlx'); mlx.core = mx
    utils = types.ModuleType('mlx_audio.tts.utils')
    utils.load_model = lambda path: loaded.append(path) or SimpleNamespace(tokenizer=1, speech_tokenizer=1, path=path)
    monkeypatch.setitem(sys.modules, 'mlx', mlx); monkeypatch.setitem(sys.modules, 'mlx.core', mx)
    monkeypatch.setitem(sys.modules, 'mlx_audio', types.ModuleType('mlx_audio'))
    monkeypatch.setitem(sys.modules, 'mlx_audio.tts', types.ModuleType('mlx_audio.tts'))
    monkeypatch.setitem(sys.modules, 'mlx_audio.tts.utils', utils)
    for name in engines.ORDER:
        folder = tmp_path / name; folder.mkdir(); (folder / '.complete').write_text('')
    monkeypatch.setattr(engines, 'model_path', lambda e: tmp_path / engines.normalize(e))
    return mx, loaded


def test_6_admission_runs_before_any_model_is_loaded(fake_mlx):
    mx, loaded = fake_mlx
    host = engines.EngineHost()
    host.before_load = lambda engine: False
    with pytest.raises(engines.ResourceWait):
        host.load('qwen3')
    assert loaded == [] and host.model is None


# ------------------------------------------------------------------ 11-12 switching and cleanup (in-process)

def test_11_switching_releases_the_first_engine_and_rechecks_before_loading_the_next(fake_mlx):
    mx, loaded = fake_mlx
    events, checks = [], []
    host = engines.EngineHost(emit=lambda kind, **k: events.append(k.get('message', kind)))
    host.before_load = lambda engine: checks.append((engine, host.model)) or True
    host.load('qwen3'); host.load('qwen3')                  # consecutive sections reuse the model
    assert len(loaded) == 1
    host.load('chatterbox')
    assert len(loaded) == 2 and host.engine == 'chatterbox'
    assert checks == [('qwen3', None), ('chatterbox', None)]    # the old model was gone when the check ran
    assert any('Switching to' in e for e in events)


def test_12_release_drops_the_model_and_clears_mlx_cache(fake_mlx):
    mx, loaded = fake_mlx
    host = engines.EngineHost()
    host.load('qwen3')
    before = mx.cleared
    host.release()
    assert host.model is None and host.engine is None and mx.cleared == before + 1
    host.release()                                           # idempotent
    assert mx.cleared == before + 1


# ------------------------------------------------------------------ 14 worker preserves the project when it must wait

def test_14_worker_that_may_not_load_a_model_leaves_the_project_untouched(monkeypatch, tmp_path, fake_mlx):
    monkeypatch.setattr(worker, 'DATA', tmp_path); monkeypatch.setattr(storage, 'DATA', tmp_path)
    monkeypatch.setattr(worker.engines, 'available', lambda: ['qwen3'])
    monkeypatch.setattr(resources, 'snapshot', lambda data, exclude_pids=(): reading(free_percent=8))
    events = []
    monkeypatch.setattr(worker, 'emit', lambda kind, **kw: events.append((kind, kw)))
    import soundfile as sf
    sf.write(tmp_path / 'reference.wav', np.zeros(24000, dtype='float32'), 24000)
    profile = {'id': 'hal', 'name': 'Hal', 'reference': 'reference.wav', 'transcript': 'Words.'}
    session = text.new_session('One sentence.\n\nTwo sentence.', 'Keep', profile)
    storage.save_session(session)
    before = (tmp_path / 'sessions' / session['id'] / 'project.json').read_bytes()
    worker.generate({'session': str(storage.session_path(session))})
    kinds = [k for k, _ in events]
    assert 'resource_wait' in kinds and 'loaded' not in kinds and 'segment' not in kinds
    assert (tmp_path / 'sessions' / session['id'] / 'project.json').read_bytes() == before


def test_14b_stop_file_stops_before_the_next_section_and_keeps_finished_ones(monkeypatch, tmp_path):
    from tests_helpers import natural_take
    monkeypatch.setattr(worker, 'DATA', tmp_path); monkeypatch.setattr(storage, 'DATA', tmp_path)
    monkeypatch.setattr(worker.engines, 'available', lambda: ['qwen3'])
    mx = SimpleNamespace(clear_cache=lambda: None, get_peak_memory=lambda: 0)
    mlx = types.ModuleType('mlx'); mlx.core = mx
    monkeypatch.setitem(sys.modules, 'mlx', mlx); monkeypatch.setitem(sys.modules, 'mlx.core', mx)
    stop = tmp_path / 'job.stop'
    calls = []

    class Host:
        def __init__(self, **kw): self.before_load = self.on_chunk = None
        def load(self, *a): pass
        def release(self): pass
        def synthesize(self, *a, **kw):
            calls.append(1); stop.write_text('available memory fell to 9 %')   # pressure rises mid-run
            return natural_take()
    monkeypatch.setattr(worker.engines, 'EngineHost', Host)
    events = []
    monkeypatch.setattr(worker, 'emit', lambda kind, **kw: events.append((kind, kw)))
    monkeypatch.setattr(worker, 'transcribe', lambda *a, **k: {'text': 'One sentence.', 'words': []})
    import soundfile as sf
    sf.write(tmp_path / 'reference.wav', natural_take(), 24000)
    profile = {'id': 'hal', 'name': 'Hal', 'reference': 'reference.wav', 'transcript': 'Words.'}
    session = text.new_session('One sentence.\n\nTwo sentence.\n\nThree sentence.', 'Stop', profile)
    storage.save_session(session)
    worker.generate({'session': str(storage.session_path(session)), 'stop_file': str(stop), 'verify': False})
    saved = storage.read_json(storage.session_path(session))
    assert len(calls) == 1                                   # nothing further was scheduled
    assert saved['segments'][0]['file'] and not saved['segments'][1].get('file')
    stopped = [kw for k, kw in events if k == 'safely_stopped']
    assert stopped and stopped[0]['completed'] == 1 and '9 %' in stopped[0]['message']


# ------------------------------------------------------------------ 7-10, 13, 15-16 with a real (fake) worker process

@pytest.fixture
def qt(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(jobs, 'DATA', tmp_path)
    (tmp_path / 'jobs').mkdir(); (tmp_path / 'logs').mkdir()
    monkeypatch.setattr(jobs, 'WORKER_ARGS', FAKE)
    return app


def run_until(app, predicate, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end and not predicate():
        app.processEvents(); time.sleep(.02)
    return predicate()


def start(qt, job, sampler=None, interval=.1):
    runner = jobs.Jobs()
    runner.MONITOR_INTERVAL = interval
    runner.sampler = sampler
    result, events = {}, []
    runner.event.connect(events.append)
    runner.ended.connect(lambda ok, msg: result.update(ok=ok, msg=msg))
    runner.start({'action': 'generate', **job})
    return runner, result, events


def gone(pid):
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True


def test_8_cancel_during_generation_ends_the_worker_and_its_children(qt):
    runner, result, events = start(qt, {'fake': 'spawn', 'sections': 400})
    assert run_until(qt, lambda: any(e.get('kind') == 'loaded' for e in events))
    pid = runner.process.processId()
    runner.cancel()
    assert run_until(qt, lambda: 'ok' in result)
    assert result['ok'] is False and 'Cancelled' in result['msg']
    assert run_until(qt, lambda: gone(pid), 5)
    out = subprocess.run(['pgrep', '-g', str(pid)], capture_output=True, text=True).stdout
    assert out.strip() == ''                                   # the spawned grandchild is gone too


def test_9_worker_crash_is_reported_and_monitoring_stops(qt):
    runner, result, events = start(qt, {'fake': 'crash'})
    assert run_until(qt, lambda: 'ok' in result)
    assert result['ok'] is False and 'stopped unexpectedly' in result['msg']
    assert runner.monitor is None and not runner.busy


class Clock:
    """Fake readings on a fake clock: each call advances 2 s, so 'sustained' can be tested quickly."""
    def __init__(self, levels, swaps=None):
        self.levels, self.swaps, self.n = list(levels), list(swaps or []), 0

    def __call__(self, pid):
        i = self.n; self.n += 1
        level = self.levels[min(i, len(self.levels) - 1)]
        swap = self.swaps[min(i, len(self.swaps) - 1)] if self.swaps else 6.0
        return {'t': 1000 + 2.0 * i, 'free_percent': level, 'swap_gb': swap, 'disk_gb': 50.0, 'footprint_gb': 1.0}


def series(levels, swaps=None):
    """Feed readings through assess the way the job runner does; return the decisions."""
    clock, history, out = Clock(levels, swaps), [], []
    for _ in range(len(levels)):
        sample = clock(0)
        out.append(resources.assess('qwen3', sample, history)[0])
        history = [h for h in history if sample['t'] - h['t'] <= 120] + [sample]
    return out


def test_10_the_24_october_pattern_no_longer_stops_generation():
    # model load at 36 % available: swap jumps 1.4 GB within 30 s, then settles (read as "2.8 GB a minute" before)
    swaps = [10.0, 10.3, 10.8, 11.2, 11.4] + [11.4] * 40
    assert set(series([36] * 45, swaps)) == {resources.CONTINUE}


def test_10a_a_brief_dip_is_tolerated_but_sustained_low_memory_pauses():
    assert set(series([30, 9, 9, 30, 30, 30])) == {resources.CONTINUE}          # 4 s below 10 %
    decisions = series([30] + [9] * 12)
    assert decisions[-1] == resources.PAUSE and resources.TERMINATE not in decisions


def test_10b_low_memory_with_fast_sustained_swap_growth_pauses():
    swaps = [6.0 + 0.15 * i for i in range(40)]                                 # 4.5 GB a minute for 80 s
    decisions = series([14] * 40, swaps)
    assert resources.PAUSE in decisions and resources.TERMINATE not in decisions


def test_10c_two_critical_readings_in_a_row_stop_immediately():
    assert series([30, 4]) == [resources.CONTINUE, resources.CONTINUE]          # one reading is not enough
    assert series([30, 4, 4])[-1] == resources.TERMINATE


def test_10d_sustained_pressure_pauses_the_worker_cleanly(qt):
    runner, result, events = start(qt, {'fake': 'sleep', 'sections': 400, 'section_seconds': .2},
                                   Clock([30] + [8] * 400))
    stop_file = runner.stop_file
    assert run_until(qt, lambda: 'ok' in result)
    assert result['ok'] is True                                               # a pause is not a failure
    assert any(e.get('kind') == 'safely_stopped' for e in events)
    assert not stop_file.exists()


def test_10e_an_emergency_stops_the_worker_and_says_why(qt):
    runner, result, events = start(qt, {'fake': 'sleep', 'sections': 400}, Clock([30, 4, 4, 4, 4]))
    assert run_until(qt, lambda: 'ok' in result)
    assert result['ok'] is False and 'safely stopped' in result['msg'] and 'untouched' in result['msg']


def test_10f_worker_memory_above_the_engine_limit_terminates(qt):
    sampler = lambda pid: {'t': time.monotonic(), 'free_percent': 40, 'swap_gb': 6.0, 'disk_gb': 50.0,
                           'footprint_gb': None}
    runner, result, events = start(qt, {'fake': 'sleep', 'sections': 400, 'mlx_gb': 5.6, 'engine': 'qwen3'}, sampler)
    assert run_until(qt, lambda: 'ok' in result)
    assert 'safely stopped' in result['msg'] and '5.6 GB' in result['msg']


def test_13_repeated_generation_leaves_nothing_behind(qt):
    pids = []
    threads_before = threading.active_count()
    for _ in range(3):
        runner, result, events = start(qt, {'fake': 'sleep', 'sections': 3})
        assert run_until(qt, lambda: 'ok' in result)
        pids += [e['pid'] for e in events if 'pid' in e]
        assert result['ok'] is True and runner.monitor is None and not runner.busy
    assert all(run_until(qt, lambda p=p: gone(p), 5) for p in pids)
    assert run_until(qt, lambda: threading.active_count() <= threads_before, 5)   # monitor threads ended
    assert not list((jobs.DATA / 'jobs').glob('*.stop'))


def test_15_slow_readings_never_block_the_interface(qt):
    def slow(pid):
        time.sleep(.5)                                             # a slow footprint call
        return {'t': time.monotonic(), 'free_percent': 40, 'swap_gb': 6.0, 'disk_gb': 50.0, 'footprint_gb': 1.0}
    from PySide6.QtCore import QTimer
    ticks = []
    timer = QTimer(); timer.setInterval(20); timer.timeout.connect(lambda: ticks.append(time.monotonic())); timer.start()
    runner, result, events = start(qt, {'fake': 'sleep', 'sections': 10, 'section_seconds': .2}, slow, interval=.05)
    assert run_until(qt, lambda: 'ok' in result)
    timer.stop()
    gaps = np.diff(ticks)
    assert len(ticks) > 20 and gaps.max() < .3                    # the event loop kept running


def test_16_no_scheduling_change_is_made_to_the_worker(qt):
    runner, result, events = start(qt, {'fake': 'sleep', 'sections': 2})
    assert run_until(qt, lambda: 'ok' in result)
    nice = [e['nice'] for e in events if 'nice' in e]
    assert nice == [os.getpriority(os.PRIO_PROCESS, 0)]            # inherited, not raised or lowered


# ------------------------------------------------------------------ 7 waiting state in the window

def test_7_waiting_state_is_visible_bounded_and_cancellable(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import importlib
    monkeypatch.setenv('VOICE_STUDIO_DATA', str(tmp_path))
    from voice_studio import config, ui
    importlib.reload(config); importlib.reload(storage); importlib.reload(ui)
    window = ui.VoiceStudio()
    window.session = text.new_session('One.', 'Wait test', {'id': 'hal', 'name': 'Hal', 'reference': 'r.wav',
                                                            'transcript': 'Words.'}, engine='chatterbox')
    import itertools; levels = itertools.repeat(20)
    monkeypatch.setattr(ui.resources, 'snapshot', lambda data, exclude_pids=(): reading(free_percent=next(levels)))
    started = []
    monkeypatch.setattr(window.jobs, 'start', lambda job: started.append(job))
    window.start_job({'action': 'generate', 'session': 'x'})
    assert not started and window._waiting_job is not None
    assert 'Waiting for enough free memory' in window.status.text() and 'untouched' in window.status.text()
    assert '%' not in window.status.text() and '%' in window.status.toolTip()   # numbers only in the details
    assert window.generate_button.text() == 'Retry now' and window.cancel_button.text() == 'Stop waiting'
    assert window.wait_timer.isActive()
    for _ in range(window.WAIT_RETRY_LIMIT + 3):                  # bounded: no endless retrying
        window.retry_waiting()
    assert not window.wait_timer.isActive() and not started
    assert 'Retry now' in window.status.text()
    window.cancel()                                                # "Stop waiting"
    assert window._waiting_job is None and window.generate_button.text() == 'Generate narration'
    monkeypatch.setattr(ui.resources, 'snapshot', lambda data, exclude_pids=(): reading(free_percent=45))
    window.start_job({'action': 'generate', 'session': 'x'})
    assert len(started) == 1                                       # admitted when memory is back
    window.close()


def test_17_a_pause_resumes_automatically_with_only_the_unfinished_sections(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import importlib
    monkeypatch.setenv('VOICE_STUDIO_DATA', str(tmp_path))
    from voice_studio import config, ui
    importlib.reload(config); importlib.reload(storage); importlib.reload(ui)
    window = ui.VoiceStudio()
    window.session = text.new_session('One.\n\nTwo.\n\nThree.\n\nFour.', 'Resume', {'id': 'hal', 'name': 'Hal',
                                      'reference': 'r.wav', 'transcript': 'Words.'})
    monkeypatch.setattr(ui.resources, 'snapshot', lambda data, exclude_pids=(): reading(free_percent=45))
    started = []
    monkeypatch.setattr(window.jobs, 'start', lambda job: started.append(job))
    monkeypatch.setattr(ui, 'read_json', lambda path: window.session)
    window.start_job({'action': 'generate', 'session': 'x', 'indices': [0, 1, 2, 3]})
    assert started and window._progress_total == 4 and window._progress_offset == 0
    # the worker reports progress across the whole narration, finishes sections 1 and 2, then pauses
    window.on_event({'kind': 'progress', 'completed': 1, 'total': 4, 'index': 1, 'message': 'Generating section 2 of 4…'})
    assert window.progress.maximum() == 4 and window.progress.value() == 1
    for i in (0, 1):
        window.on_event({'kind': 'segment', 'index': i, 'file': 'x', 'seconds': 1, 'elapsed': 1, 'completed': i + 1,
                         'total': 4, 'verified': True, 'attempts': 1, 'kept_take': 1, 'engine': 'qwen3', 'takes': 1})
    window.on_event({'kind': 'safely_stopped', 'completed': 2, 'total': 4, 'message': 'available memory stayed below 10 %'})
    window.on_finished(True, '')
    assert window._waiting_job is not None and 'continue automatically' in window.status.text()
    window.retry_waiting()                                          # memory is back: resumes on its own
    assert len(started) == 2 and started[1]['indices'] == [2, 3]     # finished sections are not re-recorded
    window.close()


def test_18_a_completed_run_says_generation_complete(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import importlib
    monkeypatch.setenv('VOICE_STUDIO_DATA', str(tmp_path))
    from voice_studio import config, ui
    importlib.reload(config); importlib.reload(storage); importlib.reload(ui)
    window = ui.VoiceStudio()
    window.job_action = 'generate'
    window.on_finished(True, '')
    assert window.status.text() == 'Generation complete.'
    window.close()
