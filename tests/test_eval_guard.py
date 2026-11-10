"""The evaluation memory guard: decisions with fake readings, and supervision of a harmless child process."""
import importlib.util
import sys
import time
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('eval_guard', Path(__file__).resolve().parents[1] / 'scripts/eval_guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

SAFE = {'estimated_peak_gb': 3.8, 'free_percent': 55, 'swap_used_gb': 2.0, 'disk_free_gb': 40.0,
        'heavy_apps': [], 'model_processes': [], 'unacknowledged_panic': None, 'interrupted': None}


def test_estimates_match_what_was_measured_on_this_mac():
    assert guard.estimate_peak_gb(2.0, 'mlx-quantized') == 3.8           # Qwen3 0.6B 8-bit
    assert guard.estimate_peak_gb(5.1, 'fp32-cpu') > guard.LIMITS['max_estimated_peak_gb']   # CosyVoice 3
    with pytest.raises(ValueError):
        guard.estimate_peak_gb(1, 'unknown')


def test_a_safe_machine_passes():
    assert guard.preflight_problems(SAFE) == ([], [])


@pytest.mark.parametrize('change,expect', [
    ({'estimated_peak_gb': 8.7}, 'estimated peak'),
    ({'free_percent': 30}, 'memory free'),
    ({'swap_used_gb': 20.0}, 'swap in use'),
    ({'disk_free_gb': 14.0}, 'disk free'),
    ({'heavy_apps': [('Google Chrome', 'refuse')]}, 'Google Chrome'),
    ({'model_processes': [(123, 'python -m voice_studio.worker job.json')]}, 'one model at a time'),
    ({'unacknowledged_panic': 'panic-full-2026-10-24-233813.0002.panic'}, 'kernel panic'),
    ({'interrupted': 'terminated by guard: evaluation memory 6.1 GB > 5.0 GB'}, 'interrupted'),
])
def test_each_unsafe_condition_refuses_to_start(change, expect):
    refuse, _ = guard.preflight_problems({**SAFE, **change})
    assert refuse and expect in ' '.join(refuse)


def test_visual_studio_code_only_warns():
    refuse, warn = guard.preflight_problems({**SAFE, 'heavy_apps': [('Code Helper (Plugin)', 'warn')]})
    assert not refuse and warn


def sample(t=10, tree=1.0, fp=None, free=50, swap=2.0, disk=40.0):
    return {'t': t, 'tree_gb': tree, 'footprint_gb': fp, 'free_percent': free, 'swap_gb': swap, 'disk_gb': disk}


@pytest.mark.parametrize('s,expect', [
    (sample(tree=5.5), 'evaluation memory'),
    (sample(tree=1.0, fp=7.5), 'evaluation memory'),        # compressed memory counts too
    (sample(free=8), 'system memory free'),
    (sample(disk=6.0), 'disk free'),
])
def test_each_kill_trigger(s, expect):
    assert expect in guard.kill_reason(s, [])


def test_swap_growth_is_judged_over_one_minute_only():
    history = [sample(t=0, swap=2.0), sample(t=30, swap=2.5)]
    assert 'swap grew' in guard.kill_reason(sample(t=50, swap=4.0), history)
    assert guard.kill_reason(sample(t=200, swap=4.0), history) is None    # old samples fall out of the window
    assert guard.kill_reason(sample(), []) is None


def test_unsafe_reading_terminates_the_whole_process_group_and_leaves_a_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, 'STATE', tmp_path)
    child = [sys.executable, '-c', 'import subprocess, time; subprocess.Popen(["sleep", "60"]); time.sleep(60)']
    calls = []

    def fake(pid, t):
        calls.append(pid)
        return sample(t=t, tree=6.0 if len(calls) >= 3 else 0.5)
    start = time.monotonic()
    code, reason = guard.supervise(child, interval=.1, sampler=fake, log=tmp_path / 'log.jsonl')
    assert reason and 'evaluation memory' in reason and time.monotonic() - start < 10
    marker = guard.read_state('running.json')
    assert 'terminated by guard' in marker['reason']                     # a human must clear it
    group = calls[0]
    import os
    with pytest.raises(ProcessLookupError):                               # the grandchild is gone too
        os.killpg(group, 0)
    assert guard.preflight_problems({**SAFE, 'interrupted': marker['reason']})[0]


def test_a_clean_run_clears_its_marker_and_is_never_restarted(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, 'STATE', tmp_path)
    runs = []
    code, reason = guard.supervise([sys.executable, '-c', 'pass'], interval=.05,
                                   sampler=lambda pid, t: (runs.append(pid), sample(t=t))[1], log=tmp_path / 'l')
    assert code == 0 and reason is None and guard.read_state('running.json') is None
    assert len(set(runs)) <= 1                                            # one process, never relaunched


def test_cli_check_refuses_an_oversized_model_without_running_anything(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(guard, 'STATE', tmp_path)
    monkeypatch.setattr(guard, 'gather', lambda w, k: {**SAFE, 'estimated_peak_gb': guard.estimate_peak_gb(w, k)})
    monkeypatch.setattr(guard, 'supervise', lambda *a, **k: pytest.fail('must not run'))
    assert guard.main(['--weights-gb', '5.1', '--kind', 'fp32-cpu', '--', 'echo', 'hi']) == 3
    assert 'REFUSED' in capsys.readouterr().out
