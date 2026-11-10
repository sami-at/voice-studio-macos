"""Run one TTS process at a time, with the network denied by macOS."""
import subprocess,sys,time,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'samples/final-quality'
report=[]
for engine in ('qwen3','chatterbox'):
 for voice in ('Hal','Mike'):
  for style in ('natural','energetic'):
   tag=f'{voice.lower()}-{engine}-{style}'
   print('START',tag,flush=True); start=time.monotonic()
   with (OUT/(tag+'.log')).open('w') as log:
    p=subprocess.run(['/usr/bin/sandbox-exec','-f',str(ROOT/'docs/deny-network.sb'),sys.executable,'-u',str(ROOT/'scripts/final_quality_generate.py'),voice,engine,style],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
   report.append({'case':tag,'returncode':p.returncode,'wall_seconds':round(time.monotonic()-start,2)})
   (OUT/'generation-matrix.json').write_text(json.dumps(report,indent=2))
   print('END',report[-1],flush=True)
   if p.returncode: raise SystemExit(p.returncode)
