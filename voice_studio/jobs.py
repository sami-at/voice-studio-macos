import json
import os
import signal
import sys
import threading
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from . import resources
from .config import DATA, ROOT, offline_environment
from .storage import atomic_json, identifier

WORKER_ARGS = ['-m', 'voice_studio.worker']   # tests substitute a harmless fake worker


class Monitor:
    """Samples the system and the worker off the GUI thread; results go back through a Qt signal.

    Reads only: sysctl, disk usage, and `footprint` of our own worker (which, unlike RSS, includes
    the MLX/Metal allocations that hold a model). Nothing about any other process is changed.
    """

    def __init__(self, pid, emit, interval=1.5, footprint_every=2, sampler=None):
        self.pid, self.emit, self.interval = pid, emit, interval
        self.footprint_every, self.sampler = footprint_every, sampler
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        last_footprint, n = None, 0
        while not self.stop.is_set():
            if self.sampler:
                sample = self.sampler(self.pid)
            else:
                if n % self.footprint_every == 0:
                    last_footprint = resources.footprint_gb(self.pid) or last_footprint
                sample = {'t': resources.time.monotonic(), 'free_percent': resources.free_percent(),
                          'swap_gb': resources.swap_used_gb(), 'disk_gb': resources.disk_free_gb(DATA),
                          'footprint_gb': last_footprint}
            n += 1
            if self.stop.is_set():          # the job ended while this reading was being taken
                break
            try:
                self.emit(sample)
            except RuntimeError:            # the receiving Jobs object is gone (window closing)
                break
            self.stop.wait(self.interval)

class Jobs(QObject):
    event = Signal(dict)
    ended = Signal(bool, str)
    sampled = Signal(dict)
    MONITOR_INTERVAL = 1.5
    sampler = None                       # tests inject fake readings here

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.cancelled = False
        self.buffer = b''
        self.error = ''
        self.done = False
        self.log = None
        self.monitor = None
        self.safety_reason = ''
        self.stop_requested = ''
        self.engine = None
        self.mlx_gb = None
        self.history = []
        self.sampled.connect(self.on_sample)

    @property
    def busy(self):
        return self.process is not None

    def start(self, job):
        if self.busy:
            raise RuntimeError('A task is already running.')
        job_id = identifier()
        request = DATA / 'jobs' / f'{job_id}.json'
        self.stop_file = None
        if job.get('action') == 'generate':
            # The worker checks this before each section: a polite "finish this one, then stop".
            self.stop_file = DATA / 'jobs' / f'{job_id}.stop'
            job = {**job, 'stop_file': str(self.stop_file)}
        self.safety_reason, self.stop_requested, self.history, self._samples = '', '', [], 0
        self.engine, self.mlx_gb = job.get('engine'), None
        atomic_json(request, job)
        self.log = (DATA / 'logs' / f'{job_id}.log').open('wb')
        self.cancelled, self.buffer, self.error, self.done = False, b'', '', False
        process = QProcess(self)
        self.process = process
        environment = QProcessEnvironment.systemEnvironment()
        for key, value in offline_environment().items():
            environment.insert(key, value)
        process.setProcessEnvironment(environment)
        process.setWorkingDirectory(str(ROOT))
        process.setProgram(sys.executable)
        process.setArguments(['-u', *WORKER_ARGS, str(request)])
        process.readyReadStandardOutput.connect(self.read_output)
        process.readyReadStandardError.connect(self.read_error)
        process.finished.connect(self.finished)
        process.errorOccurred.connect(self.process_error)
        process.start()
        if self.stop_file is not None and process.waitForStarted(5000):
            self.monitor = Monitor(process.processId(), self.sampled.emit, self.MONITOR_INTERVAL,
                                   sampler=self.sampler)
            self.monitor.thread.start()

    def on_sample(self, sample):
        """GUI thread. Decide whether the running generation is still safe. Details go to the job log."""
        if not self.process:
            return
        sample = dict(sample)
        sample['worker_gb'] = max([v for v in (sample.get('footprint_gb'), self.mlx_gb) if v is not None],
                                  default=None)
        action, reason = resources.assess(self.engine or 'qwen3', sample, self.history)
        self.history = [h for h in self.history if sample['t'] - h['t'] <= 120] + [sample]
        self._samples = getattr(self, '_samples', 0) + 1
        if action != resources.CONTINUE or self._samples % 20 == 1:
            self._diagnostic(f"resources {json.dumps({k: sample.get(k) for k in ('free_percent', 'swap_gb', 'disk_gb', 'worker_gb')})} -> {action} {reason}")
        if action == resources.TERMINATE and not self.safety_reason:
            self.safety_reason = reason
            self.cancel()
        elif action == resources.PAUSE and not self.stop_requested and self.stop_file:
            # Finish the current section, release the model, and let the window resume automatically.
            self.stop_requested = reason
            try:
                self.stop_file.write_text(reason)
            except OSError:
                pass

    def _diagnostic(self, line):
        if self.log:
            self.log.write(('[voice studio] ' + line + '\n').encode())
            self.log.flush()

    def read_output(self):
        if not self.process:
            return
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            if line.startswith(b'VS_EVENT '):
                try:
                    event = json.loads(line[9:])
                    if event['kind'] == 'error':
                        self.error = event['message']
                    if event['kind'] == 'done':
                        self.done = True
                    if event['kind'] == 'loaded':
                        self.engine = event.get('engine') or self.engine
                    if event['kind'] == 'memory':
                        self.mlx_gb = event.get('mlx_gb')
                    self.event.emit(event)
                except (ValueError, KeyError):
                    pass
            elif self.log:
                self.log.write(line + b'\n')

    def read_error(self):
        if self.process and self.log:
            self.log.write(bytes(self.process.readAllStandardError()))
            self.log.flush()

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.error = 'The Python worker could not start. Run Install Voice Studio.command to repair the environment.'
            self.finished(-1, QProcess.ExitStatus.CrashExit)

    def cancel(self):
        process = self.process
        if not process:
            return
        self.cancelled = True
        self._signal(process, signal.SIGTERM)
        QTimer.singleShot(1500, lambda: self._signal(process, signal.SIGKILL) if self.process is process else None)

    @staticmethod
    def _signal(process, sig):
        pid = process.processId()
        if not pid:
            return
        try:
            if os.getpgid(pid) == pid:
                os.killpg(pid, sig)
            else:
                os.kill(pid, sig)
        except ProcessLookupError:
            pass

    def finished(self, code, status):
        if not self.process:
            return
        self.read_output()
        self.read_error()
        process, self.process = self.process, None
        process.deleteLater()
        if self.monitor:
            self.monitor.stop.set()
            self.monitor = None
        if self.stop_file is not None:
            self.stop_file.unlink(missing_ok=True)
        if self.log:
            self.log.close()
            self.log = None
        if self.safety_reason:
            message = ('Generation safely stopped to protect your Mac: ' + self.safety_reason + '. Completed sections '
                       'are saved, and your applications and projects are untouched. Press Generate to resume '
                       'when more memory is available.')
        elif self.cancelled:
            message = 'Cancelled. Completed sections are saved; Generate resumes the remaining sections.'
        else:
            message = self.error
        if code and not message:
            message = 'The voice worker stopped unexpectedly. Close memory-heavy apps and retry. Details are in local_data/logs.'
        self.ended.emit(code == 0 and self.done and not self.cancelled and not self.safety_reason, message)
