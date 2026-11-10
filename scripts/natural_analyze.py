"""Analyse samples/natural-upgrade/experiments: does a lever move delivery by more than seed noise?"""
import json, os, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_audio import ROOT, active_span, load, yin_track
from voice_studio.config import offline_environment
os.environ.update(offline_environment())
from voice_studio.verify import compare

EXP = ROOT / 'samples/natural-upgrade/experiments'


def measure(path):
    x, r = load(path)
    s0, s1 = active_span(x, r)
    clip = x[int(s0 * r):int(s1 * r)]
    t, f0, per, level = yin_track(clip, r)
    v = ~np.isnan(f0)
    st = 12 * np.log2(f0[v] / np.median(f0[v]))
    meta = json.loads(path.with_suffix('.json').read_text())
    words = len(meta['text'].split())
    act = level[level > -45]
    return {'f0_mean': float(np.mean(f0[v])), 'f0_range_st': float(np.percentile(st, 95) - np.percentile(st, 5)),
            'wps': words / (s1 - s0), 'dyn_db': float(np.percentile(act, 90) - np.percentile(act, 10)),
            'seconds': s1 - s0}


def summarize(rows, key):
    a = np.array([r[key] for r in rows])
    return a.mean(), a.std(ddof=1)


def delivery():
    from voice_studio.worker import transcribe
    refs = ['calm', 'question', 'opening']
    kinds = ['question', 'explain', 'conclude']
    data, words = {}, {}
    for ref in refs:
        for kind in kinds:
            files = sorted((EXP / 'delivery-ref').glob(f'{ref}-{kind}-*.wav'))
            data[ref, kind] = [measure(f) for f in files]
            ok = 0
            for f in files:
                heard = transcribe(f)
                text = json.loads(f.with_suffix('.json').read_text())['text']
                ok += bool(compare(text, heard)['ok'])
            words[ref, kind] = (ok, len(files))
    out = {'cells': {}, 'effects': []}
    print(f"{'reference':9s} {'sentence':9s}  F0 mean Hz       F0 range st      words/s        word-check")
    for kind in kinds:
        for ref in refs:
            rows = data[ref, kind]
            m = {k: summarize(rows, k) for k in ('f0_mean', 'f0_range_st', 'wps')}
            out['cells'][f'{ref}|{kind}'] = {k: [round(v[0], 2), round(v[1], 2)] for k, v in m.items()} | {'n': len(rows), 'words_ok': words[ref, kind][0]}
            print(f"{ref:9s} {kind:9s}  {m['f0_mean'][0]:6.1f} ±{m['f0_mean'][1]:5.1f}   {m['f0_range_st'][0]:5.1f} ±{m['f0_range_st'][1]:4.1f}    {m['wps'][0]:4.2f} ±{m['wps'][1]:4.2f}    {words[ref, kind][0]}/{words[ref, kind][1]}")
    print('\nseparation vs calm = difference of means / pooled seed SD (|d| > 1 means the reference moved delivery by more than seed noise; all five takes of each ref ranking apart is stronger)')
    for kind in kinds:
        for ref in ('question', 'opening'):
            for key in ('f0_mean', 'f0_range_st', 'wps'):
                a = np.array([r[key] for r in data['calm', kind]]); b = np.array([r[key] for r in data[ref, kind]])
                pooled = np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
                d = (b.mean() - a.mean()) / pooled if pooled else float('nan')
                separated = bool(b.min() > a.max() or b.max() < a.min())
                out['effects'].append({'kind': kind, 'ref': ref, 'metric': key, 'd': round(float(d), 2), 'no_overlap': separated,
                                       'delta': round(float(b.mean() - a.mean()), 2)})
                print(f'  {kind:9s} {ref:9s} vs calm  {key:12s} delta {b.mean() - a.mean():+6.2f}  d={d:+5.2f}  no-overlap={separated}')
    (EXP / 'delivery-results.json').write_text(json.dumps(out, indent=1))


def chain():
    from voice_studio.worker import transcribe
    from voice_studio.quality import section_profile
    res = {}
    for seed in (42, 43):
        for mode in ('fixed', 'chained'):
            rows, ok = [], 0
            for i in range(1, 5):
                f = EXP / 'chain' / f'{mode}-{seed}-{i}.wav'
                x, r = load(f)
                p = section_profile(x, r)
                rows.append(p)
                text = json.loads(f.with_suffix('.json').read_text())['text']
                ok += bool(compare(text, transcribe(f))['ok'])
            res[mode, seed] = (rows, ok)
    print(f"{'mode':8s} seed  level dB (sd)   F0 median Hz [per sentence]        centroid Hz [per sentence]            words ok")
    out = {}
    for (mode, seed), (rows, ok) in res.items():
        lv = [r['level_db'] for r in rows]; f0 = [r['f0_median_hz'] for r in rows]; cc = [r['centroid_hz'] for r in rows]
        print(f'{mode:8s} {seed}   {np.mean(lv):6.1f} ({np.std(lv):.2f})   {[round(v) for v in f0]}   {[round(v) for v in cc]}   {ok}/4')
        out[f'{mode}|{seed}'] = {'level_sd': float(np.std(lv)), 'f0': f0, 'centroid': cc, 'words_ok': ok}
    (EXP / 'chain-results.json').write_text(json.dumps(out, indent=1))


if __name__ == '__main__':
    for name in sys.argv[1:] or ['delivery', 'chain']:
        {'delivery': delivery, 'chain': chain}[name]()
