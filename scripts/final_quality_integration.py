"""Real worker generation, hybrid take switching, retiming and resume on copied data."""
import os,sys,json,subprocess,time,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'samples/final-quality'
os.environ['VOICE_STUDIO_DATA']=str(OUT/'integration-data')
sys.path.insert(0,str(ROOT))
from voice_studio.config import DATA,initialize,offline_environment
os.environ.update(offline_environment())
from voice_studio import storage,engines,styles
from voice_studio.text import new_session
from voice_studio.audio import export_audio
initialize()
# Chatterbox's installed loader resolves its separate tokenizer from HF_HOME.
# Clone the existing offline cache into this isolated library; never download it.
cache=DATA/'cache'/'huggingface'
if not cache.exists():
 subprocess.run(['/bin/cp','-cR',str(ROOT/'local_data/cache/huggingface'),str(cache)],check=True)
for refdir in (OUT/'references').iterdir():
 p=json.loads((refdir/'profile.json').read_text());target=DATA/p['reference'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(refdir/'reference.wav',target)
 storage.atomic_json(DATA/'voices'/p['id']/'profile.json',p)
hal=next(p for p in storage.profiles() if p['name']=='Hal')
report={}
def run(job,name):
 path=DATA/'jobs'/(name+'.json');storage.atomic_json(path,job);start=time.monotonic()
 result=subprocess.run([sys.executable,'-u','-m','voice_studio.worker',str(path)],cwd=ROOT,env={**os.environ,**offline_environment()},capture_output=True,text=True,timeout=1800)
 (OUT/(name+'.log')).write_text(result.stdout+'\nSTDERR:\n'+result.stderr)
 events=[json.loads(l[9:]) for l in result.stdout.splitlines() if l.startswith('VS_EVENT ')]
 report[name]={'wall_seconds':round(time.monotonic()-start,3),'returncode':result.returncode,'events':events}
 storage.atomic_json(OUT/'integration-results.json',report)
 if result.returncode:raise RuntimeError(result.stderr[-1500:])
 return events
s=new_session('Have you ever wondered why flies do that?\n\n[pause:0.4]\n\nThe mystery is over.', 'Final quality integration',hal,styles.NATURAL)
storage.save_session(s);job={'action':'generate','session':str(storage.session_path(s))}
run(job,'integration-qwen')
s=storage.read_json(storage.session_path(s));initial=[g['file'] for g in s['segments']];ids=[g['selected_take'] for g in s['segments']]
run({**job,'indices':[1],'engine':engines.CHATTERBOX,'regenerate':True},'integration-chatterbox')
s=storage.read_json(storage.session_path(s));assert s['segments'][0]['file']==initial[0];assert len(storage.takes_of(s['segments'][1]))==2
assert (DATA/initial[1]).exists()
# Select original take, reassemble without a model load; change timing only.
storage.choose_take(s['segments'][1],ids[1]);s['segments'][1]['lead_pause']=.7;s['output']=None;storage.save_session(s)
events=run(job,'integration-retime')
assert not any(e['kind'] in ('loaded','segment') for e in events)
s=storage.read_json(storage.session_path(s));assert [g['file'] for g in s['segments']]==initial
# A completed project resumes by assembling, without regenerating any sections.
events=run(job,'integration-resume');assert not any(e['kind'] in ('loaded','segment') for e in events)
s=storage.read_json(storage.session_path(s))
for extension in ('wav','mp3'):export_audio(DATA/s['output'],OUT/('integration-export.'+extension))
report['assertions']={'other_section_preserved':True,'previous_take_file_preserved':True,'hybrid_take_stored':True,'switch_and_retime_without_generation':True,'resume_without_generation':True,'reopened':True,'exports':True}
storage.atomic_json(OUT/'integration-results.json',report);print(json.dumps(report['assertions'],indent=2))
