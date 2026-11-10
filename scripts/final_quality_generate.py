"""Offline acceptance raw capture. Never writes to the user's library; resumable."""
import json, os, sys, time, resource, shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from voice_studio.config import offline_environment
os.environ.update(offline_environment())
from voice_studio import engines, styles, direction
from voice_studio.audio import conditioned_reference, RATE
from voice_studio.text import split_script
from voice_studio.storage import atomic_json
import soundfile as sf
import mlx.core as mx
OUT = ROOT / 'samples/final-quality'

def main():
    voice, engine, style_key = sys.argv[1:4]
    style = styles.NATURAL if style_key == 'natural' else styles.ENERGETIC
    profile = next(json.loads(p.read_text()) for p in (ROOT/'local_data/voices').glob('*/profile.json') if json.loads(p.read_text())['name'] == voice)
    original = ROOT/'local_data'/profile['reference']
    refdir = OUT/'references'/voice
    refdir.mkdir(parents=True, exist_ok=True)
    reference = refdir/'reference.wav'
    if not reference.exists(): shutil.copy2(original, reference)
    atomic_json(refdir/'profile.json', profile)
    values = styles.settings(style)
    reference = conditioned_reference(reference, values['reference_tempo'], refdir)
    script = json.loads((ROOT/'backups/final-quality-before/local_data/draft.json').read_text())['script']
    (OUT/'whydo-flies.txt').write_text(script)
    cases = [('flies', c) for c in split_script(script)]
    # Full matrix also exercises short endings, quiet attacks, repeated words, overrides.
    challenge = ["Have you ever wondered? The mystery is over.",
                 "Surprisingly, that's how it works.",
                 "But here's the interesting part. And now you understand.",
                 "Flies have tiny receptors. Everything is different.",
                 "The reason is simple. They're keeping themselves clean.",
                 "Very, very small. The {tarsi|tar sigh} and nuclei[say:new clee eye] matter.",
                 "But wait[pause:0.4] there is actually a scientific reason."]
    if style_key == 'natural': cases += [('edges', {'text':t,'paragraph_end':True}) for t in challenge]
    folder=OUT/f'{voice.lower()}-{engine}-{style_key}'
    folder.mkdir(exist_ok=True)
    host=engines.EngineHost(emit=lambda k,**v: print(k,v,flush=True))
    records=[]
    for i,(group, chunk) in enumerate(cases):
        raw=folder/f'{i+1:02d}-raw.wav'; meta=raw.with_suffix('.json')
        if raw.exists() and meta.exists(): records.append(json.loads(meta.read_text())); continue
        started=time.monotonic(); seed=42+i
        audio=host.synthesize(engine,direction.parse(chunk['text']).spoken,reference,profile['transcript'],seed,{},RATE)
        sf.write(raw,audio,RATE,subtype='FLOAT')
        record={**chunk,'group':group,'raw':str(raw.relative_to(OUT)),'seed':seed,'voice':voice,'engine':engine,'style':style,'settings':values,
                'seconds':len(audio)/RATE,'generation_seconds':round(time.monotonic()-started,3),
                'peak_mlx_gb':round(mx.get_peak_memory()/1e9,3),'peak_rss_gb':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e9,3)}
        atomic_json(meta,record); records.append(record)
        print(raw.name,record['seconds'],record['generation_seconds'],flush=True)
        del audio; mx.clear_cache()
    host.release(); atomic_json(folder/'manifest.json',records)
if __name__=='__main__': main()
