"""Serialize GPU validation after raw capture to keep memory bounded."""
import json,subprocess,sys,time,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'samples/final-quality'
started=time.monotonic()
while True:
 state=json.loads((OUT/'generation-matrix.json').read_text()) if (OUT/'generation-matrix.json').exists() else []
 if any(r['returncode'] for r in state): raise SystemExit('Raw matrix failed; inspect generation logs.')
 if len(state)==8:break
 if time.monotonic()-started>7200:raise SystemExit('Raw matrix did not complete in two hours.')
 time.sleep(15)
jobs=[('chunk-qwen',['scripts/final_quality_benchmark.py','qwen3']),
      ('chunk-chatterbox',['scripts/final_quality_benchmark.py','chatterbox']),
      ('comparisons',['scripts/final_quality_compare.py']),
      ('integration',['scripts/final_quality_integration.py'])]
status=[]
for label,args in jobs:
 print('START',label,flush=True);begin=time.monotonic()
 with (OUT/(label+'.log')).open('w') as log:
  process=subprocess.run(['/usr/bin/sandbox-exec','-f',str(ROOT/'docs/deny-network.sb'),sys.executable,'-u',*args],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
 status.append({'job':label,'returncode':process.returncode,'wall_seconds':round(time.monotonic()-begin,3)})
 (OUT/'validation-jobs.json').write_text(json.dumps(status,indent=2));print('END',status[-1],flush=True)
 if process.returncode:raise SystemExit(process.returncode)
