"""Resource checks for everyday generation on an 8 GB Apple Silicon Mac.

Voice Studio never closes, suspends or reprioritises other applications, and never changes system
settings. It does three things only:

* **Admission**: before a model is loaded, decide from live readings whether it can be loaded safely
  now, must wait, or must not run at all.
* **Monitoring**: while a worker runs, watch the worker and the system, and ask the worker to stop
  after its current section (or terminate it) when conditions become dangerous.
* **Isolation**: every generation runs in its own process, so when it ends macOS reclaims all of it.

The experiment guard (scripts/eval_guard.py) stays separate and stricter: it is for unproven models.
This policy is calibrated for the two installed engines, whose peaks were measured on this Mac.
A polling monitor cannot prevent every sudden spike; admission is deliberately conservative instead.
"""
import json, re, shutil, subprocess, time
from pathlib import Path

GB = 1e9
TOTAL_GB = None  # filled lazily from hw.memsize

# Measured peaks on this Mac (MLX peak + process overhead), with headroom. Not guaranteed bounds.
ENGINE_PEAK_GB = {'qwen3': 3.9, 'chatterbox': 4.8}
# Kill the worker if its footprint passes these; ~1 GB above the highest peak ever measured.
ENGINE_HARD_GB = {'qwen3': 5.0, 'chatterbox': 6.0}

POLICY = {
    # kern.memorystatus_level (% of memory macOS reports as available). Earlier Qwen3 and Chatterbox
    # runs completed at 30-37 % with Chrome open; the crash came from an 8.6 GB process, not from this.
    'admit_free_percent': {'qwen3': 22, 'chatterbox': 28},
    'wait_floor_percent': 12,         # below this nothing is admitted, whatever the engine
    'max_swap_growth_gb_per_min': 1.0,  # before admission: the system is already thrashing
    'min_disk_free_gb': 12.0,         # swap files grow on this disk
    'refuse_disk_free_gb': 6.0,
    'panic_window_hours': 72,
    # during a run. Swap growth alone is NOT a danger signal: loading a 2-4 GB model on a busy Mac
    # normally makes macOS compress and swap other apps' idle memory for a few seconds (24-25 Oct:
    # three runs were stopped by a one-off 1.4 GB displacement read as "2.8 GB a minute").
    'pause_free_percent': 10,          # pause (finish the section, release the model) if available
    'pause_sustained_s': 15,           #   memory stays below this for this long
    'pause_free_with_swap': 15,        # ... or is below this while swap grows fast over a full window
    'pause_swap_gb_per_min': 3.0,
    'stop_free_percent': 5,            # emergency stop: two readings in a row below this
    'stop_free_with_swap': 8,          # ... or very low memory with very fast swap growth
    'stop_swap_gb_per_min': 6.0,
    'hard_disk_free_gb': 4.0,
    'swap_window_min_s': 45,           # never extrapolate swap growth from a short window
}

ACK_FILE = Path.home() / '.voice_studio_eval_guard' / 'panic-ack.json'   # shared with eval_guard
PANIC_DIRS = (Path('/Library/Logs/DiagnosticReports'), Path('/Library/Logs/DiagnosticReports/Retired'))


# ------------------------------------------------------------------ readings (all user-level, read-only)

def _sh(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ''


def total_gb():
    global TOTAL_GB
    if TOTAL_GB is None:
        TOTAL_GB = int(_sh('sysctl', '-n', 'hw.memsize').strip() or 8 * 1024 ** 3) / GB
    return TOTAL_GB


def free_percent():
    value = _sh('sysctl', '-n', 'kern.memorystatus_level').strip()
    return int(value) if value.isdigit() else None


def swap_used_gb():
    m = re.search(r'used = ([\d.]+)M', _sh('sysctl', '-n', 'vm.swapusage'))
    return float(m.group(1)) * 1024 ** 2 / GB if m else 0.0


def disk_free_gb(path):
    return shutil.disk_usage(path).free / GB


def footprint_gb(pid):
    """Physical footprint of one process, including GPU (MLX/Metal) and compressed memory.
    Plain RSS does not include MLX allocations, so it cannot be used to watch a model."""
    m = re.search(r'Footprint:\s*([\d.]+)\s*([KMG])B', _sh('footprint', str(pid)))
    return float(m.group(1)) * {'K': 1e-6, 'M': 1e-3, 'G': 1.0}[m.group(2)] if m else None


def other_workers(exclude=()):
    """Generation workers from any Voice Studio window (or a script) other than ours."""
    out = []
    for line in _sh('ps', '-axo', 'pid=,command=').splitlines():
        pid, _, command = line.strip().partition(' ')
        if pid.isdigit() and int(pid) not in exclude and 'voice_studio.worker' in command:
            out.append(int(pid))
    return out


def recent_unacknowledged_panic(now=None, window_hours=None):
    window = (window_hours or POLICY['panic_window_hours']) * 3600
    now = now or time.time()
    found = []
    for folder in PANIC_DIRS:
        if folder.is_dir():
            found += [p for p in folder.glob('panic-full-*.panic')]
    if not found:
        return None
    newest = max(found, key=lambda p: p.stat().st_mtime)
    try:
        acknowledged = json.loads(ACK_FILE.read_text()).get('mtime', 0)
    except (OSError, ValueError):
        acknowledged = 0
    mtime = newest.stat().st_mtime
    return newest.name if mtime > acknowledged and now - mtime < window else None


def acknowledge_panic():
    """The user's explicit decision, from the waiting panel. Same record the experiment guard reads."""
    found = [p for d in PANIC_DIRS if d.is_dir() for p in d.glob('panic-full-*.panic')]
    newest = max(found, key=lambda p: p.stat().st_mtime) if found else None
    ACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACK_FILE.write_text(json.dumps({'file': newest.name if newest else None,
                                    'mtime': newest.stat().st_mtime if newest else 0,
                                    'acknowledged': time.strftime('%Y-%m-%dT%H:%M:%S'), 'by': 'Voice Studio'}))


def snapshot(data_dir, exclude_pids=()):
    return {'t': time.monotonic(), 'free_percent': free_percent(), 'swap_gb': swap_used_gb(),
            'disk_gb': disk_free_gb(data_dir), 'other_workers': other_workers(exclude_pids),
            'panic': recent_unacknowledged_panic()}


# ------------------------------------------------------------------ decisions (pure; unit-tested)

ADMIT, WAIT, REFUSE = 'admit', 'wait', 'refuse'


def swap_growth(history, now_sample, seconds=60, min_span=None):
    """Swap growth in GB per minute over the last `seconds`, or None if fewer than `min_span` seconds
    of readings exist. A short window would turn a brief, normal displacement into an alarming rate."""
    min_span = POLICY['swap_window_min_s'] if min_span is None else min_span
    window = [h for h in history if 0 <= now_sample['t'] - h['t'] <= seconds]
    if not window:
        return None
    span = now_sample['t'] - min(h['t'] for h in window)
    if span < min_span:
        return None
    return (now_sample['swap_gb'] - min(h['swap_gb'] for h in window)) * 60 / span


def admission(engines_needed, reading, history=(), policy=POLICY):
    """Decide before any model is loaded. Returns (decision, reason)."""
    if reading.get('panic'):
        return REFUSE, (f"macOS restarted after a kernel panic recently ({reading['panic']}). Generation is "
                        'paused until you confirm you have reviewed it.')
    if reading.get('other_workers'):
        return REFUSE, 'Another voice generation is already running. Only one model is loaded at a time.'
    if reading['disk_gb'] < policy['refuse_disk_free_gb']:
        return REFUSE, f"Only {reading['disk_gb']:.1f} GB of disk is free. Free some space before generating."
    if reading['disk_gb'] < policy['min_disk_free_gb']:
        return WAIT, f"Only {reading['disk_gb']:.1f} GB of disk is free; macOS needs room for memory swap."
    free = reading.get('free_percent')
    if free is None:
        return REFUSE, 'Could not read memory status from macOS.'
    need = max(policy['admit_free_percent'].get(e, 28) for e in engines_needed)
    if free < policy['wait_floor_percent'] or free < need:
        return WAIT, f'Waiting for enough available memory ({free} % available, {need} % needed for this engine).'
    growth = swap_growth(list(history), reading)
    if growth is not None and growth > policy['max_swap_growth_gb_per_min'] and free < 30:
        return WAIT, f'Waiting while macOS settles (swap growing {growth:.1f} GB a minute).'
    return ADMIT, 'Resources are sufficient.'


CONTINUE, PAUSE, TERMINATE = 'continue', 'pause', 'terminate'
STOP_AFTER_SECTION = PAUSE      # older name


def assess(engine, sample, history=(), policy=POLICY):
    """Decide during a run, from the current sample and earlier ones. Returns (action, reason).

    PAUSE: finish the current section, release the model, and continue automatically once memory recovers.
    TERMINATE: stop now; completed sections are kept; nothing restarts on its own.
    """
    history = list(history)
    free = sample.get('free_percent')
    worker = sample.get('worker_gb')
    if worker is not None and engine in ENGINE_HARD_GB and worker > ENGINE_HARD_GB[engine]:
        return TERMINATE, f'the generation worker reached {worker:.1f} GB, above the safe {ENGINE_HARD_GB[engine]:.0f} GB'
    if sample.get('disk_gb', 99) < policy['hard_disk_free_gb']:
        return TERMINATE, f"disk space fell to {sample['disk_gb']:.1f} GB"
    previous = history[-1].get('free_percent') if history else None
    if free is not None and free < policy['stop_free_percent'] and previous is not None \
            and previous < policy['stop_free_percent']:
        return TERMINATE, f'available memory stayed at {free} %'
    growth = swap_growth(history, sample)
    if growth is not None and free is not None and free < policy['stop_free_with_swap'] \
            and growth > policy['stop_swap_gb_per_min']:
        return TERMINATE, f'available memory {free} % with swap growing {growth:.1f} GB a minute'
    if free is not None and free < policy['pause_free_percent']:
        recent = [h for h in history if sample['t'] - h['t'] <= policy['pause_sustained_s']]
        covered = recent and sample['t'] - min(h['t'] for h in recent) >= policy['pause_sustained_s'] * .8
        if covered and all((h.get('free_percent') or 100) < policy['pause_free_percent'] for h in recent):
            return PAUSE, f"available memory stayed below {policy['pause_free_percent']} %"
    if growth is not None and free is not None and free < policy['pause_free_with_swap'] \
            and growth > policy['pause_swap_gb_per_min']:
        return PAUSE, f'available memory {free} % with swap growing {growth:.1f} GB a minute'
    return CONTINUE, ''
