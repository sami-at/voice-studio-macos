"""A harmless stand-in for voice_studio.worker used by resource tests. Loads nothing; only sleeps and prints."""
import json, os, subprocess, sys, time

job = json.load(open(sys.argv[1]))
emit = lambda kind, **k: print('VS_EVENT ' + json.dumps({'kind': kind, **k}), flush=True)
mode = job.get('fake', 'sleep')
emit('status', message='fake worker started', pid=os.getpid(), nice=os.getpriority(os.PRIO_PROCESS, 0))
if mode == 'crash':
    sys.exit(3)
if mode == 'spawn':
    subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
emit('loaded', engine=job.get('engine', 'qwen3'))
stop = job.get('stop_file')
for section in range(job.get('sections', 40)):
    if stop and os.path.exists(stop):
        emit('safely_stopped', completed=section, total=job.get('sections', 40), message=open(stop).read())
        break
    emit('memory', mlx_gb=job.get('mlx_gb', 1.0))
    time.sleep(job.get('section_seconds', .2))
emit('done')
