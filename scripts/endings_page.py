"""Offline listening page for phrase endings -> samples/endings/index.html (level-matched, last 2 s of each phrase)."""
import glob, json, sys
from pathlib import Path
import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_audio import ROOT, load, matched  # noqa: E402
sys.path.insert(0, str(ROOT))
from voice_studio import audio as A, storage  # noqa: E402

OUT = ROOT / 'samples/endings'
CLIPS = OUT / 'clips'
ORIGINAL = 'f516b218580e40819dbf3db4d2b6fc15'
REPAIRED = '9016595ce3e74c9da42e9ee508b626df'
EL = ROOT / 'samples/elevenlabs-benchmark/audio/phrases'


def ending(x, rate, seconds=2.0):
    """The last `seconds` before the sound ends, plus 0.4 s after, so the stop (or fade) is audible."""
    live = np.flatnonzero(np.abs(x) > 1e-4)
    end = (live[-1] + 1) if len(live) else len(x)
    return x[max(0, end - int(seconds * rate)):min(len(x), end + int(.4 * rate))]


def clip(name, x, rate):
    y, _, _ = matched(ending(x, rate), rate)
    CLIPS.mkdir(parents=True, exist_ok=True)
    sf.write(CLIPS / name, y, rate, subtype='PCM_16')
    return f'clips/{name}'


def state(raw):
    stop, _ = A.ending_stop(raw)
    return ('cut' if stop > A.CUT_STOP_REL_DB else 'short ending' if stop > A.SHORT_STOP_REL_DB else 'fades out'), round(stop)


def take_item(raw_path, file_path, name, label):
    raw = sf.read(raw_path, dtype='float32')[0]
    x, r = load(file_path)
    kind, stop = state(raw)
    return {'label': label, 'file': clip(name, x, r), 'state': kind, 'stop': stop}


def build():
    D = storage.DATA
    groups = []
    a = storage.read_json(D / 'sessions' / ORIGINAL / 'project.json')
    b = storage.read_json(D / 'sessions' / REPAIRED / 'project.json')
    for i, (sa, sb) in enumerate(zip(a['segments'], b['segments'])):
        ta, tb = storage.selected_take(sa), storage.selected_take(sb)
        items = [take_item(D / ta['raw_file'], D / ta['file'], f'n{i + 1:02d}-before.wav', f"Before · {ta['engine']} seed {ta['seed']}")]
        if tb['id'] != ta['id']:
            items.append(take_item(D / tb['raw_file'], D / tb['file'], f'n{i + 1:02d}-after.wav',
                                   f"After · {tb['engine']} seed {tb['seed']}"))
        groups.append({'title': f'Section {i + 1}' + (' · regenerated' if tb['id'] != ta['id'] else ' · unchanged'),
                       'text': sa['text'], 'items': items})
    # ElevenLabs endings of the same words (the benchmark script)
    el_items = []
    for p, word in (('p1', 'something?'), ('p7', 'clean.'), ('p9', 'clean.')):
        x, r = load(EL / f'{p}-elevenlabs.wav')
        el_items.append({'label': f'ElevenLabs · "…{word}"', 'file': clip(f'el-{p}.wav', x, r), 'state': 'reference', 'stop': None})
    groups.append({'title': 'ElevenLabs reference endings', 'text': 'How the same voice ends "something" and "clean" in your ElevenLabs recording.', 'items': el_items})
    # word list: one cut and one complete Qwen3 take each, plus Chatterbox where Qwen3 kept cutting
    words = json.loads((ROOT / 'samples/endings/experiments/sweep.json').read_text())
    texts = sorted({w['text'] for w in words}, key=lambda t: [x['text'] for x in words].index(t))
    for w, text in enumerate(texts[:6] + texts[7:9]):
        index = texts.index(text)
        files = sorted(glob.glob(str(ROOT / f'samples/endings/experiments/sweep/natural-{index:02d}-*.wav')))
        info = [(f, state(sf.read(f, dtype='float32')[0])) for f in files]
        items = []
        cut = next((f for f, s in info if s[0] == 'cut'), None)
        good = next((f for f, s in info if s[0] == 'fades out'), None)
        for f, label in ((cut, 'Qwen3 · cut take'), (good, 'Qwen3 · complete take')):
            if f:
                x, r = load(f)
                items.append({'label': f"{label} · seed {f.split('-')[-1][:-4]}", 'file': clip(Path(f).name, x, r),
                              'state': state(x)[0], 'stop': state(x)[1]})
        for f in sorted(glob.glob(str(ROOT / f'samples/endings/experiments/chatterbox/chatterbox-{index:02d}-*.wav')))[:2]:
            x, r = load(f)
            items.append({'label': f"Chatterbox · seed {f.split('-')[-1][:-4]}", 'file': clip(Path(f).name, x, r),
                          'state': state(x)[0], 'stop': state(x)[1]})
        cuts = sum(1 for _, s in info if s[0] == 'cut')
        groups.append({'title': f'Test word · "{text.split()[-1].strip(".")}" ({cuts} of {len(info)} Natural takes cut)', 'text': text, 'items': items})
    return groups


TEMPLATE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Phrase endings</title><style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1c1c1a;--mute:#66665f;--line:#dcdcd4;--cut:#b3261e;--short:#8a5a00;--ok:#1d6b3a}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--panel:#1f1f1d;--ink:#ecece6;--mute:#a2a299;--line:#34342f;--cut:#ff8a80;--short:#ffcf8a;--ok:#7bd69a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 -apple-system,system-ui,sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px 80px}h1{font-size:1.5rem;margin:0}h2{font-size:1.05rem;margin:28px 0 2px}.mute{color:var(--mute)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:10px;margin:8px 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:6px}
.card.liked{border-color:#c2185b}.tag{font-size:.78rem;font-weight:600}.cut{color:var(--cut)}.short{color:var(--short)}.ok{color:var(--ok)}audio{width:100%}
button{font:inherit;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:4px 12px;cursor:pointer}
button[aria-pressed=true]{background:#c2185b;border-color:#c2185b;color:#fff}label{display:inline-flex;gap:6px}
</style></head><body><main>
<h1>Phrase endings: before and after</h1>
<p class="mute">The last 2 seconds of each phrase plus 0.4 s after, level-matched to -24 LUFS. Labels come from a measurement of how the sound stops; whether a word sounds complete is your call.</p>
<label><input type="checkbox" id="blind"> Hide labels and measurements</label>
<div id="g"></div></main><script>
const G=__GROUPS__;let likes={};try{likes=JSON.parse(localStorage.getItem('endings-likes')||'{}')||{}}catch(e){}
function render(){const blind=document.getElementById('blind').checked;const h=document.getElementById('g');h.innerHTML='';
G.forEach((g,gi)=>{const d=document.createElement('div');d.innerHTML=`<h2>${g.title}</h2><p class="mute">“${g.text}”</p>`;const grid=document.createElement('div');grid.className='grid';
const items=blind?g.items.slice().sort((a,b)=>(a.file>b.file?1:-1)*(gi%2?1:-1)):g.items;
items.forEach((it,i)=>{const k=gi+'|'+it.label;const c=document.createElement('div');c.className='card'+(likes[k]?' liked':'');
const cls=it.state==='cut'?'cut':it.state==='short ending'?'short':'ok';
c.innerHTML=`<strong>${blind?'Clip '+'ABCDEF'[i]:it.label}</strong><audio controls preload="none" src="${it.file}"></audio>`+(blind?'':`<span class="tag ${cls}">${it.state}${it.stop!==null&&it.stop>-99?' · stops '+it.stop+' dB below speech':''}</span>`)+`<div><button aria-pressed="${!!likes[k]}">${likes[k]?'♥ Sounds complete':'♡ Sounds complete'}</button></div>`;
c.querySelector('button').onclick=()=>{likes[k]?delete likes[k]:likes[k]=1;try{localStorage.setItem('endings-likes',JSON.stringify(likes))}catch(e){};render()};
c.querySelector('audio').addEventListener('play',e=>document.querySelectorAll('audio').forEach(a=>{if(a!==e.target)a.pause()}));grid.appendChild(c)});d.appendChild(grid);h.appendChild(d)})}
document.getElementById('blind').onchange=render;render();
</script></body></html>'''

if __name__ == '__main__':
    groups = build()
    (OUT / 'index.html').write_text(TEMPLATE.replace('__GROUPS__', json.dumps(groups)))
    print('wrote', OUT / 'index.html', sum(len(g['items']) for g in groups), 'clips in', len(groups), 'groups')
