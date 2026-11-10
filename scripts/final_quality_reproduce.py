"""Reproduce destructive old edge cuts using known audio, without a TTS/ASR model."""
import sys,importlib.util,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
import soundfile as sf
from voice_studio import audio,verify,direction
OUT=ROOT/'samples/final-quality/reproductions';OUT.mkdir(parents=True,exist_ok=True)
def old(name):
 spec=importlib.util.spec_from_file_location('voice_studio.old_'+name,ROOT/'backups/final-quality-before/voice_studio'/f'{name}.py')
 module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);return module
before=old('audio');old_verify=old('verify');old_direction=old('direction')
rng=np.random.default_rng(7);quiet=rng.uniform(-.0005,.0005,4800).astype('float32');vowel=(.2*np.sin(np.arange(12000)*.1)).astype('float32')
raw=np.r_[np.zeros(2400),quiet,vowel,quiet,np.zeros(2400)].astype('float32')
sf.write(OUT/'synthetic-quiet-edges-raw.wav',raw,24000,subtype='FLOAT')
report={}
for label,mod in [('before',before),('after',audio)]:
 path=OUT/(label+'-section.wav');mod.write_segment(raw,path)
 mod.join_segments({'segments':[{'file':path.name,'text':'Synthetic quiet attack and decay.'}]},OUT,OUT/(label+'-assembly.wav'))
 signal,_=sf.read(path);active=np.flatnonzero(np.abs(signal)>.00001)
 assembled,_=sf.read(OUT/(label+'-assembly.wav'));bounds=np.flatnonzero(np.abs(assembled)>.00001)
 report[label]={'processed_active_span_ms':round((active[-1]-active[0]+1)/24,3),'assembled_active_span_ms':round((bounds[-1]-bounds[0]+1)/24,3)}
expected='Have you ever wondered why flies rub their hands together and why this matters?'
report['missing_first_word']={'before':old_verify.compare(expected,expected[5:]),'after':verify.compare(expected,expected[5:])}
report['missing_last_word']={'before':old_verify.compare(expected,expected.rsplit(' ',1)[0]),'after':verify.compare(expected,expected.rsplit(' ',1)[0])}
script='  One   [pause:0.4]two  [pause:0.6]three.'
report['pause_offsets']={'before':old_direction.parse(script).pauses,'after':direction.parse(script).pauses}
raw=np.full(2400,.04,dtype='float32')
report['boundary_fade']={'old_first':float(before.polish_segment(raw)[0]),'old_last':float(before.polish_segment(raw)[-1]),'new_first_speech':float(audio.polish_segment(raw)[1920]),'new_last_speech':float(audio.polish_segment(raw)[4319])}
(OUT/'confirmed-bugs.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
