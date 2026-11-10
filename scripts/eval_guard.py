"""Memory guard for model evaluations on an 8 GB Apple Silicon Mac.

Wraps ONE evaluation command. Standard library and built-in macOS tools only; it loads no model.

    python scripts/eval_guard.py --weights-gb 2.0 --kind mlx-quantized -- <command ...>
    python scripts/eval_guard.py --check --weights-gb 5.4 --kind fp32-cpu     # pre-flight only
    python scripts/eval_guard.py --clear-interrupted                          # after reading why it stopped
    python scripts/eval_guard.py --acknowledge-panic                          # after investigating a panic

What it does
  1. Pre-flight refuses to start when: a kernel panic report is newer than the last acknowledgement; a
     previous guarded run was interrupted; memory free < 40 %; swap used > 10 GB; disk free < 25 GB;
     Chrome (or another listed heavy app) is running; another TTS/model process is running; or the
     model's estimated peak footprint exceeds 4.5 GB.
  2. Starts the command in its own process group and samples once a second, from before the model
     loads: the whole process tree's memory, system memory free %, swap growth and disk space.
  3. On an unsafe reading it sends SIGTERM to the whole group, then SIGKILL after 3 s, records why,
     and leaves an "interrupted" marker. It never restarts anything; a human must clear the marker.

What it cannot do
  It lowers the risk of a repeat of 24 October; it does NOT guarantee protection from a kernel panic.
  Memory can be allocated faster than one sample per second, the kernel or other apps can exhaust
  memory on their own, and a watchdog panic can follow from paging pressure the guard never sees.
"""
import argparse, json, os, re, signal, shutil, subprocess, sys, time
from datetime import datetime
from pathlib import Path

STATE = Path.home() / '.voice_studio_eval_guard'
PANIC_DIRS = [Path('/Library/Logs/DiagnosticReports'), Path('/Library/Logs/DiagnosticReports/Retired')]

# Conservative limits for an 8 GB M1 whose swap lives on the system disk (see docs/INCIDENT-2026-10-24-RESTART.md).
LIMITS = {
    'max_estimated_peak_gb': 4.5,     # Qwen3 measured 3.6-3.8 GB, Chatterbox 4.4 GB
    'min_free_percent': 40,           # kern.memorystatus_level before starting
    'max_swap_used_gb': 10.0,
    'min_disk_free_gb': 25.0,
    'kill_footprint_gb': 5.0,         # whole process tree; the crashing process reached 7.5 GB
    'kill_free_percent': 12,
    'kill_swap_growth_gb_per_min': 1.5,
    'kill_disk_free_gb': 10.0,
}
# Peak footprint as a multiple of the weights on disk, from this machine's measurements.
PEAK_FACTOR = {'mlx-quantized': 1.9,  # Qwen3 0.6B 8-bit: 2.0 GB on disk -> 3.8 GB peak
               'mlx-fp16': 1.8,       # Chatterbox v3: 2.5 GB -> 4.4 GB
               'fp32-cpu': 1.7}       # CosyVoice 3: 5.1 GB -> 8.6 GB footprint
HEAVY_APPS = {'Google Chrome': 'refuse', 'Safari': 'warn', 'Code Helper (Plugin)': 'warn'}
MODEL_PROCESS = re.compile(r'voice_studio\.worker|mlx_audio|cosyvoice|cv3_generate|indextts|voxcpm|natural_generate|'
                           r'benchmark_generate|final_quality_generate', re.I)


# ------------------------------------------------------------------ probes (replaceable in tests)

def sh(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout


def free_percent():
    return int(sh('sysctl', '-n', 'kern.memorystatus_level').strip() or 0)


def swap_used_gb():
    m = re.search(r'used = ([\d.]+)M', sh('sysctl', '-n', 'vm.swapusage'))
    return float(m.group(1)) / 1024 if m else 0.0


def disk_free_gb(path='.'):
    return shutil.disk_usage(path).free / 1e9


def processes():
    """[(pid, ppid, rss_kb, command)] for every process."""
    rows = []
    for line in sh('ps', '-axo', 'pid=,ppid=,rss=,command=').splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[0].isdigit():
            rows.append((int(parts[0]), int(parts[1]), int(parts[2]), parts[3]))
    return rows


def tree_rss_gb(root, rows):
    children, rss = {}, {}
    for pid, ppid, kb, _ in rows:
        children.setdefault(ppid, []).append(pid)
        rss[pid] = kb
    total, stack = 0, [root]
    while stack:
        pid = stack.pop()
        total += rss.get(pid, 0)
        stack.extend(children.get(pid, []))
    return total / 1e6


def footprint_gb(pid):
    """Physical footprint (includes compressed memory), slower; used every few seconds."""
    m = re.search(r'Footprint:\s*([\d.]+)\s*([KMG])B', sh('footprint', '-p', str(pid)))
    if not m:
        return None
    return float(m.group(1)) * {'K': 1e-6, 'M': 1e-3, 'G': 1.0}[m.group(2)]


def newest_panic():
    found = []
    for folder in PANIC_DIRS:
        if folder.is_dir():
            found += [p for p in folder.glob('panic-full-*.panic')]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


# ------------------------------------------------------------------ decisions (pure, unit-tested)

def estimate_peak_gb(weights_gb, kind):
    if kind not in PEAK_FACTOR:
        raise ValueError(f'kind must be one of {sorted(PEAK_FACTOR)}')
    return round(weights_gb * PEAK_FACTOR[kind], 2)


def preflight_problems(readings, limits=LIMITS):
    """readings: dict of measured values. Returns (refusals, warnings)."""
    refuse, warn = [], []
    if readings.get('unacknowledged_panic'):
        refuse.append(f"a kernel panic report ({readings['unacknowledged_panic']}) is newer than the last "
                      'acknowledgement; investigate it, then run --acknowledge-panic')
    if readings.get('interrupted'):
        refuse.append('a previous guarded run was interrupted (' + readings['interrupted'] + '); read why, then run '
                      '--clear-interrupted. Nothing is restarted automatically')
    if readings['estimated_peak_gb'] > limits['max_estimated_peak_gb']:
        refuse.append(f"estimated peak {readings['estimated_peak_gb']} GB exceeds the {limits['max_estimated_peak_gb']} GB limit")
    if readings['free_percent'] < limits['min_free_percent']:
        refuse.append(f"memory free {readings['free_percent']} % is below {limits['min_free_percent']} %")
    if readings['swap_used_gb'] > limits['max_swap_used_gb']:
        refuse.append(f"swap in use {readings['swap_used_gb']:.1f} GB exceeds {limits['max_swap_used_gb']} GB; restart the Mac first")
    if readings['disk_free_gb'] < limits['min_disk_free_gb']:
        refuse.append(f"disk free {readings['disk_free_gb']:.1f} GB is below {limits['min_disk_free_gb']} GB (swap lives on this disk)")
    for app, level in readings.get('heavy_apps', []):
        (refuse if level == 'refuse' else warn).append(f'{app} is running; quit it first' if level == 'refuse'
                                                        else f'{app} is running and uses memory')
    for pid, command in readings.get('model_processes', []):
        refuse.append(f'another model process is running (pid {pid}: {command[:80]}); only one model at a time')
    return refuse, warn


def kill_reason(sample, history, limits=LIMITS):
    """sample: {'t', 'tree_gb', 'footprint_gb', 'free_percent', 'swap_gb', 'disk_gb'}; history: earlier samples."""
    peak = max(v for v in (sample.get('tree_gb'), sample.get('footprint_gb')) if v is not None)
    if peak > limits['kill_footprint_gb']:
        return f"evaluation memory {peak:.2f} GB > {limits['kill_footprint_gb']} GB"
    if sample['free_percent'] < limits['kill_free_percent']:
        return f"system memory free {sample['free_percent']} % < {limits['kill_free_percent']} %"
    if sample['disk_gb'] < limits['kill_disk_free_gb']:
        return f"disk free {sample['disk_gb']:.1f} GB < {limits['kill_disk_free_gb']} GB"
    window = [h for h in history if sample['t'] - h['t'] <= 60]
    if window:
        growth = sample['swap_gb'] - min(h['swap_gb'] for h in window)
        if growth > limits['kill_swap_growth_gb_per_min']:
            return f"swap grew {growth:.2f} GB within a minute"
    return None


# ------------------------------------------------------------------ state

def read_state(name):
    try:
        return json.loads((STATE / name).read_text())
    except (OSError, ValueError):
        return None


def write_state(name, value):
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / name).write_text(json.dumps(value, indent=1))


def gather(weights_gb, kind, own_pid=None):
    rows = processes()
    panic = newest_panic()
    ack = read_state('panic-ack.json') or {}
    unack = panic and panic.stat().st_mtime > ack.get('mtime', 0)
    running = read_state('running.json')
    apps = sorted({(app, level) for _, _, _, cmd in rows for app, level in HEAVY_APPS.items() if app in cmd})
    models = [(pid, cmd) for pid, _, _, cmd in rows if MODEL_PROCESS.search(cmd) and pid != (own_pid or os.getpid())
              and 'eval_guard' not in cmd]
    return {'estimated_peak_gb': estimate_peak_gb(weights_gb, kind), 'free_percent': free_percent(),
            'swap_used_gb': swap_used_gb(), 'disk_free_gb': disk_free_gb(),
            'heavy_apps': apps, 'model_processes': models,
            'unacknowledged_panic': panic.name if unack else None,
            'interrupted': (running or {}).get('reason') or ((running or {}).get('command') and 'still marked running')}


def terminate(proc):
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
    except ProcessLookupError:
        pass


def supervise(command, interval=1.0, sampler=None, log=None):
    """Run command under the monitor. Returns (exit_code, reason or None)."""
    log = log or (STATE / 'last-run.jsonl')
    STATE.mkdir(parents=True, exist_ok=True)
    write_state('running.json', {'command': command, 'started': datetime.now().isoformat(timespec='seconds')})
    proc = subprocess.Popen(command, start_new_session=True)       # own group: SIGTERM reaches children
    history, reason, last_footprint, start = [], None, None, time.monotonic()
    with open(log, 'w') as out:
        while proc.poll() is None:
            t = time.monotonic() - start
            if sampler:
                sample = sampler(proc.pid, t)
            else:
                if int(t) % 5 == 0:
                    last_footprint = footprint_gb(proc.pid) or last_footprint
                sample = {'t': t, 'tree_gb': tree_rss_gb(proc.pid, processes()), 'footprint_gb': last_footprint,
                          'free_percent': free_percent(), 'swap_gb': swap_used_gb(), 'disk_gb': disk_free_gb()}
            out.write(json.dumps(sample) + '\n'); out.flush()
            reason = kill_reason(sample, history)
            if reason:
                terminate(proc)
                break
            history.append(sample)
            time.sleep(interval)
    code = proc.wait()
    if reason:
        write_state('running.json', {'command': command, 'reason': 'terminated by guard: ' + reason,
                                     'when': datetime.now().isoformat(timespec='seconds')})
    elif code != 0:
        write_state('running.json', {'command': command, 'reason': f'exited with code {code}',
                                     'when': datetime.now().isoformat(timespec='seconds')})
    else:
        (STATE / 'running.json').unlink(missing_ok=True)
    return code, reason


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--weights-gb', type=float, help='model weights on disk, in GB')
    ap.add_argument('--kind', choices=sorted(PEAK_FACTOR), default='mlx-quantized')
    ap.add_argument('--check', action='store_true', help='pre-flight only')
    ap.add_argument('--clear-interrupted', action='store_true')
    ap.add_argument('--acknowledge-panic', action='store_true')
    ap.add_argument('command', nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    if args.clear_interrupted:
        print('previous state:', read_state('running.json')); (STATE / 'running.json').unlink(missing_ok=True); return 0
    if args.acknowledge_panic:
        panic = newest_panic()
        write_state('panic-ack.json', {'file': panic.name if panic else None, 'mtime': panic.stat().st_mtime if panic else 0,
                                       'acknowledged': datetime.now().isoformat(timespec='seconds')})
        print('acknowledged', panic.name if panic else 'no panic reports'); return 0
    if args.weights_gb is None:
        ap.error('--weights-gb is required')
    readings = gather(args.weights_gb, args.kind)
    refuse, warn = preflight_problems(readings)
    print(json.dumps({k: v for k, v in readings.items()}, indent=1, default=str))
    for w in warn:
        print('WARNING:', w)
    if refuse:
        for r in refuse:
            print('REFUSED:', r)
        return 3
    print('pre-flight passed')
    if args.check:
        return 0
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        ap.error('give the command to run after --')
    code, reason = supervise(command)
    print('STOPPED BY GUARD: ' + reason if reason else f'finished with exit code {code}')
    return 4 if reason else code


if __name__ == '__main__':
    sys.exit(main())
