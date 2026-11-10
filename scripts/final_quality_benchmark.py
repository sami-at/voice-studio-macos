"""Bounded chunk-size comparison using the existing offline engines and same reference."""
import os,sys,json,time,resource
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'samples/final-quality';sys.path.insert(0,str(ROOT))
from voice_studio.config import offline_environment
os.environ.update(offline_environment())
from voice_studio import engines,direction
from voice_studio.text import split_script
from voice_studio.storage import atomic_json
import mlx.core as mx
import soundfile as sf
engine=sys.argv[1];folder=OUT/('chunk-benchmark-'+engine);folder.mkdir(exist_ok=True)
profile=json.loads((OUT/'references/Hal/profile.json').read_text())
reference=OUT/'references/Hal/reference.wav'
full=(OUT/'whydo-flies.txt').read_text()
# Three connected sentences with a long thought, rather than swallowing the entire script.
script=' '.join(direction.parse(full).spoken.split())
script=script[:script.index('So when a fly')].strip()
results=[];host=engines.EngineHost()
for limit in (160,260,380):
 chunks=split_script(script,limit=limit)
 case={'limit':limit,'text':script,'sections':[]}
 for i,chunk in enumerate(chunks):
  target=folder/f'{limit}-{i+1}.wav';meta=target.with_suffix('.json')
  if meta.exists():record=json.loads(meta.read_text())
  else:
   start=time.monotonic();raw=host.synthesize(engine,direction.parse(chunk['text']).spoken,reference,profile['transcript'],42+i)
   sf.write(target,raw,24000,subtype='FLOAT')
   record={**chunk,'raw':str(target.relative_to(OUT)),'seconds':len(raw)/24000,'generation_seconds':round(time.monotonic()-start,3),'peak_mlx_gb':mx.get_peak_memory()/1e9,'peak_rss_gb':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e9}
   atomic_json(meta,record);del raw;mx.clear_cache()
  case['sections'].append(record);print(engine,limit,i+1,record['generation_seconds'],flush=True)
 results.append(case)
 atomic_json(folder/'benchmark.json',results)
host.release()
