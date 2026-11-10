"""Alternative original-style takes for the two user-reported endings."""
import os,sys,json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from voice_studio.config import DATA,offline_environment
os.environ.update(offline_environment())
from voice_studio import engines,audio,direction
from voice_studio.storage import atomic_json
import soundfile as sf
import mlx.core as mx
OUT=ROOT/'samples/edge-followup';s=json.loads((DATA/'sessions/2ba2d3fa509d4c37849199af710cc2e3/project.json').read_text())
host=engines.EngineHost();records=[]
for index in (1,3):
 seg=s['segments'][index]
 for seed in (1043+index,2043+index):
  start=time.monotonic();raw=host.synthesize(engines.QWEN,direction.parse(seg['text']).spoken,OUT/'reference-t115.wav',s['transcript'],seed,{},audio.RATE)
  stem=f'{index+1:02d}-energetic-{seed}'
  sf.write(OUT/(stem+'.raw.wav'),raw,audio.RATE,subtype='FLOAT');audio.write_segment(raw,OUT/(stem+'.wav'),s['speed'])
  record={'section':index+1,'text':seg['text'],'seed':seed,'raw_file':stem+'.raw.wav','file':stem+'.wav','reference_tempo':1.15,'speed':s['speed'],'boundary':audio.boundary_check(raw),'elapsed':round(time.monotonic()-start,3)}
  records.append(record);atomic_json(OUT/'energetic-candidates.json',records);print(record,flush=True);del raw;mx.clear_cache()
host.release()
from voice_studio.worker import transcribe
from voice_studio import verify
for r in records:
 heard=transcribe(OUT/r['file'],details=True);r['recognition']=heard;r['check']=verify.compare(direction.parse(r['text']).spoken,heard['text']);print(r['file'],r['check'],heard['text'],flush=True)
atomic_json(OUT/'energetic-candidates.json',records)
