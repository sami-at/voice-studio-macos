"""Controlled diagnosis of the user's two reported word endings; no library writes."""
import os,sys,json,time,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from voice_studio.config import offline_environment,DATA
os.environ.update(offline_environment())
from voice_studio import audio,engines,styles,direction
from voice_studio.storage import atomic_json
import numpy as np
import soundfile as sf
import mlx.core as mx
OUT=ROOT/'samples/edge-followup';OUT.mkdir(exist_ok=True)
session=json.loads((DATA/'sessions/2ba2d3fa509d4c37849199af710cc2e3/project.json').read_text())
profile=json.loads((DATA/'voices'/session['voice_id']/'profile.json').read_text())
reference=OUT/'reference.wav'
shutil.copy2(DATA/session['reference'],reference)
fast=audio.conditioned_reference(reference,session['settings']['reference_tempo'],OUT)
host=engines.EngineHost();model=host.load(engines.QWEN);decoder=model.speech_tokenizer.decoder
report=[]
for index in (1,3):
 seg=session['segments'][index];prefix=f'{index+1:02d}';raw,_=sf.read(DATA/seg['raw_file'],dtype='float32')
 shutil.copy2(DATA/seg['file'],OUT/(prefix+'-saved.wav'))
 shutil.copy2(DATA/seg['raw_file'],OUT/(prefix+'-saved-raw.wav'))
 audio.write_segment(raw,OUT/(prefix+'-same-raw-speed100.wav'),1.0)
 codes=[]
 class CaptureDecoder:
  def __getattr__(self,name):return getattr(decoder,name)
  def __call__(self,*args,**kwargs):return decoder(*args,**kwargs)
  def streaming_step(self,c):
   codes.append(np.asarray(c));return decoder.streaming_step(c)
 model.speech_tokenizer.decoder=CaptureDecoder()
 start=time.monotonic()
 repeated=host.synthesize(engines.QWEN,direction.parse(seg['text']).spoken,fast,session['transcript'],seg['seed'],{},audio.RATE)
 model.speech_tokenizer.decoder=decoder
 sf.write(OUT/(prefix+'-repeated-stream.wav'),repeated,audio.RATE,subtype='FLOAT')
 equal=len(raw)==len(repeated) and np.array_equal(raw,repeated)
 ref_codes=next(iter(model._icl_cache.values()))[0]
 target=mx.concatenate([mx.array(c) for c in codes],axis=2)
 np.save(OUT/(prefix+'-codes.npy'),np.asarray(target))
 # Decode the EXACT same generated acoustic codes with the reference context,
 # matching the installed nonstreaming ICL path. No resampling/regeneration here.
 full=mx.concatenate([mx.transpose(ref_codes,(0,2,1)),mx.transpose(target,(0,2,1))],axis=1)
 decoded,length=model.speech_tokenizer.decode(full);decoded=decoded[0][:int(length[0])]
 cut=int(ref_codes.shape[2]/full.shape[1]*len(decoded));decoded=np.asarray(decoded[cut:])
 sf.write(OUT/(prefix+'-context-decoded-raw.wav'),decoded,audio.RATE,subtype='FLOAT')
 audio.write_segment(decoded,OUT/(prefix+'-context-decoded.wav'),session['speed'])
 del decoded,full,target;mx.clear_cache()
 # Isolate accelerated reference conditioning while keeping final speed unchanged.
 unpaced=host.synthesize(engines.QWEN,direction.parse(seg['text']).spoken,reference,session['transcript'],seg['seed'],{},audio.RATE)
 sf.write(OUT/(prefix+'-natural-reference-raw.wav'),unpaced,audio.RATE,subtype='FLOAT')
 audio.write_segment(unpaced,OUT/(prefix+'-natural-reference.wav'),session['speed'])
 row={'section':index+1,'text':seg['text'],'seed':seg['seed'],'repeated_stream_identical_to_saved':equal,'seconds':round(time.monotonic()-start,2),'peak_mlx_gb':mx.get_peak_memory()/1e9}
 report.append(row);atomic_json(OUT/'diagnosis.json',report);print(row,flush=True)
host.release()
