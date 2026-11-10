"""Same-raw before/after processing, offline ASR, assembly and codec comparisons."""
import os, sys, json, time, importlib.util, copy, html, resource
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'samples/final-quality'
os.environ['VOICE_STUDIO_DATA']=str(OUT/'test-data')
sys.path.insert(0,str(ROOT))
from voice_studio.config import offline_environment
os.environ.update(offline_environment())
from voice_studio import audio, direction, verify, styles
from voice_studio.worker import transcribe
from voice_studio.storage import atomic_json
import soundfile as sf
import numpy as np
from scipy.signal import correlate, correlation_lags, resample_poly

spec=importlib.util.spec_from_file_location('voice_studio.audio_before', ROOT/'backups/final-quality-before/voice_studio/audio.py')
before=importlib.util.module_from_spec(spec); spec.loader.exec_module(before)


def recognize(path):
    cache=path.with_name(path.stem+'-asr.json')
    if cache.exists(): return json.loads(cache.read_text())
    start=time.monotonic()
    result=transcribe(path,details=True)
    result['verification_seconds']=round(time.monotonic()-start,3)
    atomic_json(cache,result)
    return result


def export_pair(path):
    outputs={}
    for ext in ('wav','mp3'):
        target=path.with_name(path.stem+'-export.'+ext)
        audio.export_audio(path,target)
        outputs[ext]=str(target.relative_to(OUT))
    decoded=path.with_name(path.stem+'-mp3-decoded.wav')
    audio.convert(['-i',OUT/outputs['mp3'],'-ar',24000,'-ac',1,'-c:a','pcm_s24le',decoded])
    wav,_=sf.read(OUT/outputs['wav'],dtype='float32'); mp3,_=sf.read(decoded,dtype='float32')
    # Codec delay estimate after normalizing to the same rate. Do not count padding
    # as missing speech; decoded endpoints and correlation are retained for review.
    x,y=wav[::6],mp3[::6]
    corr=correlate(y,x,method='fft'); lags=correlation_lags(len(y),len(x))
    lag=int(lags[np.argmax(corr)])
    xa=x[max(0,-lag):]; ya=y[max(0,lag):]; n=min(len(xa),len(ya))
    outputs['codec']={'wav_frames':len(wav),'mp3_decoded_frames':len(mp3),
        'delay_estimate_ms':round(lag/4,3),'aligned_correlation':round(float(np.corrcoef(xa[:n],ya[:n])[0,1]),6),
        'wav_peak':round(float(np.max(np.abs(wav))),6),'mp3_peak':round(float(np.max(np.abs(mp3))),6)}
    return outputs


def compare_case(folder):
    records=json.loads((folder/'manifest.json').read_text()); report=[]
    for record in records:
        raw_path=OUT/record['raw']; raw,_=sf.read(raw_path,dtype='float32')
        stem=raw_path.stem.replace('-raw','')
        old=folder/(stem+'-before-section.wav'); new=folder/(stem+'-after-section.wav')
        before.write_segment(raw,old,record['settings']['speed'])
        audio.write_segment(raw,new,record['settings']['speed'])
        recognized={name:recognize(path) for name,path in [('raw',raw_path),('before',old),('after',new)]}
        spoken=direction.parse(record['text']).spoken
        checks={name:verify.compare(spoken,r['text']) for name,r in recognized.items()}
        checks['raw_boundary']=audio.boundary_check(raw)
        original,_=sf.read(old,dtype='float32')
        old_start,old_end=before.speech_bounds(old)
        old_begin=max(0,old_start-round(audio.RATE*before.KEEP_HEAD))
        old_finish=min(len(original),old_end+round(audio.RATE*before.KEEP_TAIL['paragraph']))
        discarded=np.r_[original[:old_begin],original[old_finish:]]
        r={**record,'before_section':str(old.relative_to(OUT)),'after_section':str(new.relative_to(OUT)),
           'checks':checks,'heard':{k:v['text'] for k,v in recognized.items()},
           'word_timing':recognized['after']['words'],
           'old_assembly_discarded_ms':round((old_begin+len(original)-old_finish)/24,3),
           'old_assembly_discarded_peak':float(np.max(np.abs(discarded))) if len(discarded) else 0,
           'verification_seconds':sum(v['verification_seconds'] for v in recognized.values())}
        report.append(r)
        print(folder.name,stem,'checks',{k:v['ok'] for k,v in checks.items() if 'ok' in v},flush=True)
    atomic_json(folder/'comparison.json',report)
    # Full Whydo script retains its original standalone pause markers.
    result={'name':folder.name,'voice':records[0]['voice'],'engine':records[0]['engine'],
            'style':records[0]['style'],'records':report,'outputs':{}}
    for variant,module in [('before',before),('after',audio)]:
        segs=[{**r,'file':r[variant+'_section']} for r in report if r['group']=='flies']
        session={'segments':segs,**records[0]['settings']}
        path=folder/(variant+'-narration.wav')
        module.join_segments(session,OUT,path)
        exports=export_pair(path)
        asr=recognize(path)
        expected=' '.join(direction.parse(s['text']).spoken for s in segs)
        result['outputs'][variant]={'assembly':str(path.relative_to(OUT)),**exports,
            'check':verify.compare(expected,asr['text']),'heard':asr['text']}
    # Inline markers are tested separately so an unsafe marker cannot hide full narration.
    result['inline']=[]
    for r in report:
        if direction.parse(r['text']).pauses:
            entry={'text':r['text']}
            for variant,module in [('before',before),('after',audio)]:
                path=folder/(Path(r['raw']).stem.replace('-raw','')+f'-{variant}-paused.wav')
                try:
                    module.join_segments({'segments':[{**r,'file':r[variant+'_section']}]},OUT,path)
                    entry[variant]=str(path.relative_to(OUT))
                except ValueError as exc:
                    entry[variant+'_error']=str(exc)
            result['inline'].append(entry)
    return result


def mixed(cases):
    out=[]
    for voice in ('Hal','Mike'):
      for style in (styles.NATURAL,styles.ENERGETIC):
        q=next(c for c in cases if c['voice']==voice and c['engine']=='qwen3' and c['style']==style)
        c=next(c for c in cases if c['voice']==voice and c['engine']=='chatterbox' and c['style']==style)
        segs=[copy.deepcopy((q if i%2==0 else c)['records'][i]) for i in range(8)]
        case={'name':voice.lower()+'-mixed-'+('natural' if style==styles.NATURAL else 'energetic'),'outputs':{}}
        folder=OUT/case['name']; folder.mkdir(exist_ok=True)
        for variant,module in [('before',before),('after',audio)]:
            for s in segs:s['file']=s[variant+'_section']
            path=folder/(variant+'-narration.wav'); module.join_segments({'segments':segs,**styles.settings(style)},OUT,path)
            case['outputs'][variant]={'assembly':str(path.relative_to(OUT)),**export_pair(path)}
        out.append(case)
    return out


def existing():
    cases=[]
    source=ROOT/'backups/final-quality-before/local_data'
    for p in (source/'sessions').glob('*/project.json'):
        s=json.loads(p.read_text())
        if 'why do flies' not in s.get('script',''): continue
        if not all(seg.get('file') and (source/seg['file']).exists() for seg in s['segments']): continue
        folder=OUT/('existing-'+s['id'][:8]);folder.mkdir(exist_ok=True)
        entry={'name':s.get('voice_name', 'Voice')+' — existing '+s['id'][:8], 'voice':s.get('voice_name'),'style':s.get('style'),'outputs':{},'source_project':str(p),'script':s['script']}
        for variant,module in [('before',before),('after',audio)]:
            path=folder/(variant+'-narration.wav');module.join_segments(s,source,path)
            entry['outputs'][variant]={'assembly':str(path.relative_to(OUT)),**export_pair(path)}
        cases.append(entry)
    return cases


def benchmarks():
    cases=[]
    for manifest in sorted(OUT.glob('chunk-benchmark-*/benchmark.json')):
        records=json.loads(manifest.read_text())
        for case in records:
            checks=[]
            for segment in case['sections']:
                recognized=recognize(OUT/segment['raw'])
                checks.append({'raw':segment['raw'],'heard':recognized['text'],
                               'check':verify.compare(direction.parse(segment['text']).spoken,recognized['text'])})
            cases.append({'engine':manifest.parent.name.replace('chunk-benchmark-',''),
                          'limit':case['limit'],'section_count':len(case['sections']),
                          'audio_seconds':sum(s['seconds'] for s in case['sections']),
                          'generation_seconds':sum(s['generation_seconds'] for s in case['sections']),
                          'peak_mlx_gb':max(s['peak_mlx_gb'] for s in case['sections']),
                          'checks':checks})
    return cases


def player(path):
    return '<audio controls preload="none" src="'+html.escape(path,quote=True)+'"></audio>'


def listening(report):
    rows=['<!doctype html><meta charset="utf-8"><title>Voice Studio — final quality listening</title><style>body{font:16px system-ui;background:#14181d;color:#e8edf2;max-width:1100px;margin:40px auto;padding:0 20px}article{padding:20px;background:#20262e;margin:20px 0;border-radius:12px}audio{width:100%}td{padding:12px;vertical-align:top;width:50%}table{width:100%}a{color:#a2d8b9}small{color:#c4cbd1}</style><h1>Final quality listening review</h1><p>Same raw generation, original versus revised processing. No voice matching or emotion correction. ASR scores do not certify phonemes, identity, naturalness or absence of clicks. Please check first/last sounds, transitions, pace and identity against the references. Approval is pending.</p><p>Explicit pauses mean inserted digital silence; the total acoustic gap includes retained natural quiet. “Before” uses the backed-up audio pipeline; no random regeneration is used for each A/B pair.</p>']
    review=[]
    for case in report['cases']:
        for number, record in enumerate(case['records'],1):
            checks=record['checks']; reasons=[]
            if not checks['after']['ok']:
                reasons.append('Recognition uncertain: '+', '.join(checks['after']['missing']))
            boundary=checks['raw_boundary']
            if boundary['head_at_boundary'] or boundary['tail_at_boundary']:
                reasons.append('Raw signal reaches '+('/'.join(k for k in ('head','tail') if boundary[k+'_at_boundary']))+' boundary')
            if reasons:
                anchor=case['name']+'-'+str(number)
                review.append('<li><a href="#'+anchor+'">'+case['name']+' / section '+str(number)+'</a>: '+html.escape('; '.join(reasons))+'</li>')
    rows.append('<h2>Listening review queue</h2><p>'+str(len(review))+' of 92 source takes have recognition or raw-boundary uncertainty. These are fixed-seed diagnostic recordings, without automatic retries; the application retries uncertain new takes up to three times. A flag is not proof of a missing phoneme, and an unflagged take is not listening approval.</p><details><summary>Show flagged sections</summary><ul>'+''.join(review)+'</ul></details>')
    rows.append('<p>Start with Hal Chatterbox Energetic sections 2 and 8, and Hal Chatterbox Natural section 10: their recognition changes from passing before processing to uncertain afterward. Compare raw and both versions by ear. Hal inline pause placement was refused in both engines; Mike placements succeeded. This remains a limitation.</p>')
    for voice in ('Hal','Mike'):
        rows.append('<h2>'+voice+' original reference (copy)</h2>'+player('references/'+voice+'/reference.wav'))
    for group in ('existing','cases','mixed'):
      for case in report[group]:
        rows.append('<article><h2>'+html.escape(case['name'])+'</h2>'+('<p>Existing stored sections only. The original raw model audio was not retained; this comparison isolates assembly.</p>' if group=='existing' else '')+'<table><tr>')
        for variant in ('before','after'):
            item=case['outputs'][variant]
            rows.append('<td><b>'+variant.title()+'</b>'+player(item['assembly'])+'<p><a href="'+item['wav']+'">WAV export</a> · <a href="'+item['mp3']+'">MP3 export</a></p></td>')
        rows.append('</tr></table>')
        if case.get('records'):
          rows.append('<details><summary>Raw, processed sections and ASR flags</summary>')
          for number,r in enumerate(case['records'],1):
            rows.append('<div id="'+case['name']+'-'+str(number)+'"><p><b>Section '+str(number)+'</b> — '+html.escape(r['text'])+'</p><small>Raw engine output</small>'+player(r['raw'])+'<table><tr><td>Before'+player(r['before_section'])+'</td><td>After'+player(r['after_section'])+'</td></tr></table><small>Checks: '+html.escape(json.dumps(r['checks']))+'</small></div>')
          rows.append('</details>')
          for item in case['inline']:
            rows.append('<p>Inline test: '+html.escape(item['text'])+'</p>')
            for variant in ('before','after'):
              rows.append('<p>'+variant+': '+(player(item[variant]) if variant in item else html.escape(item.get(variant+'_error','unavailable')))+'</p>')
        rows.append('</article>')
    for bench in report.get('benchmarks',[]):
        rows.append('<article><h2>Chunk benchmark: '+bench['engine']+' / '+str(bench['limit'])+' characters</h2><p>'+str(bench['section_count'])+' sections. This is one seeded run, not a universal quality ranking.</p>')
        for item in bench['checks']:
            rows.append(player(item['raw'])+'<small>'+html.escape(item['heard'])+'</small>')
        rows.append('</article>')
    rows.append('<p><a href="results.json">Full machine-readable measurements</a> · <a href="whydo-flies.txt">Full original script</a></p><script>function reveal(){const e=document.getElementById(location.hash.slice(1));if(e){const d=e.closest("details");if(d)d.open=true;e.scrollIntoView();}}addEventListener("hashchange",reveal);reveal();</script>')
    (OUT/'index.html').write_text('\n'.join(rows))


def main():
    report={'cases':[],'mixed':[],'existing':[]}
    for folder in sorted(OUT.iterdir()):
        if not (folder/'manifest.json').exists():continue
        saved=folder/'case-results.json'
        if saved.exists():case=json.loads(saved.read_text())
        else:
            case=compare_case(folder);atomic_json(saved,case)
        report['cases'].append(case)
        atomic_json(OUT/'results-partial.json',report)
    report['mixed']=mixed(report['cases']);report['existing']=existing();report['benchmarks']=benchmarks()
    report['asr_peak_rss_gb']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e9
    atomic_json(OUT/'results.json',report);listening(report)
if __name__=='__main__':main()
