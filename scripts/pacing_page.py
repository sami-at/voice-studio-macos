"""Offline listening page for the Chatterbox pacing variants -> samples/pacing/index.html (level-matched)."""
import glob, json, sys
from pathlib import Path
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
from benchmark_audio import active_span, load, matched  # noqa: E402
from voice_studio import storage  # noqa: E402

OUT = ROOT / 'samples/pacing'
CHECKS = json.loads((OUT / 'checks.json').read_text())
LABELS = {
    'qwen3-original': 'Qwen3 · Energetic (current)',
    'chatterbox-original': 'Chatterbox · Energetic (current)',
    'chatterbox-speed-105': 'Chatterbox · speech ×1.05',
    'chatterbox-speed-110': 'Chatterbox · speech ×1.10',
    'chatterbox-speed-115': 'Chatterbox · speech ×1.15',
    'chatterbox-pauses': 'Chatterbox · pauses tightened',
    'chatterbox-pauses-speed-105': 'Chatterbox · pauses tightened + ×1.05',
    'chatterbox-pauses-speed-110': 'Chatterbox · pauses tightened + ×1.10',
}
QWEN = 'a617e891c6c645bb993e041938177b41'


def leveled(src, name, trim=False):
    x, r = load(src)
    if trim:
        s0, s1 = active_span(x, r)
        x = x[max(0, int((s0 - .15) * r)):int((s1 + .35) * r)]
    y, _, _ = matched(x, r)
    path = OUT / 'audio' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, y, r, subtype='PCM_16')
    return f'audio/{name}'


def build():
    full = []
    for key, label in LABELS.items():
        c = CHECKS[key]
        full.append({'id': key, 'label': label, 'file': leveled(OUT / 'work' / f'{key}.wav', f'full-{key}.wav'),
                     'meta': f"{c['total']:.1f} s total · {c['voiced']:.1f} s speech · {c['pause_total']:.1f} s pauses · "
                             f"{c['wps']:.2f} words/s · typical gap {c['gaps_between']:.2f} s"})
    session = storage.read_json(storage.DATA / 'sessions' / QWEN / 'project.json')
    sections = []
    for i, g in enumerate(session['segments']):
        items = []
        for key, label in LABELS.items():
            if key == 'qwen3-original':
                src = storage.DATA / storage.selected_take(g)['file']
            else:
                src = OUT / 'work' / key / f'{i + 1:02d}.wav'
            items.append({'id': key, 'label': label, 'file': leveled(src, f's{i + 1:02d}-{key}.wav', trim=True)})
        sections.append({'title': f'Section {i + 1}', 'text': g['text'], 'items': items})
    return full, sections


TEMPLATE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chatterbox pacing</title><style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1c1c1a;--mute:#66665f;--line:#dcdcd4}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--panel:#1f1f1d;--ink:#ecece6;--mute:#a2a299;--line:#34342f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 -apple-system,system-ui,sans-serif}
main{max-width:1050px;margin:0 auto;padding:24px 16px 80px}h1{font-size:1.5rem;margin:0}h2{font-size:1.1rem;margin:30px 0 4px}.mute{color:var(--mute)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px;margin:8px 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:6px}
.card.liked{border-color:#c2185b}.meta{font-size:.8rem;color:var(--mute)}audio{width:100%}
button{font:inherit;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:4px 12px;cursor:pointer}
button[aria-pressed=true]{background:#c2185b;border-color:#c2185b;color:#fff}.tabs button{margin:2px}.tabs button.on{background:#1f5fbf;color:#fff;border-color:#1f5fbf}
</style></head><body><main>
<h1>Chatterbox Energetic Explainer: pacing options</h1>
<p class="mute">The same saved Chatterbox takes, re-timed by Voice Studio's own processing. No new generation. Level-matched to -24 LUFS. Shorter is not the goal; pick the one that sounds most natural at an engaging pace.</p>
<label><input type="checkbox" id="blind"> Blind mode (shuffle, hide names and numbers)</label>
<h2>Whole narrations</h2><div class="grid" id="full"></div>
<h2>Section by section</h2><div class="tabs" id="tabs"></div><p class="mute" id="stext"></p><div class="grid" id="sec"></div>
<h2>Your picks</h2><pre id="picks" class="mute"></pre>
</main><script>
const F=__FULL__, S=__SECTIONS__;let likes={};try{likes=JSON.parse(localStorage.getItem('pacing-likes')||'{}')||{}}catch(e){}
let cur=0;const shuffle=(a,s)=>{a=a.slice();for(let i=a.length-1;i>0;i--){s=(s*1664525+1013904223)>>>0;const j=s%(i+1);[a[i],a[j]]=[a[j],a[i]]}return a};
function card(it,key,i,blind){const c=document.createElement('div');c.className='card'+(likes[key]?' liked':'');
c.innerHTML=`<strong>${blind?'Version '+'ABCDEFGH'[i]:it.label}</strong><audio controls preload="none" src="${it.file}"></audio>`+(it.meta&&!blind?`<div class="meta">${it.meta}</div>`:'')+`<div><button aria-pressed="${!!likes[key]}">${likes[key]?'♥ Preferred':'♡ Prefer'}</button></div>`;
c.querySelector('button').onclick=()=>{likes[key]?delete likes[key]:likes[key]=it.label;try{localStorage.setItem('pacing-likes',JSON.stringify(likes))}catch(e){};render()};
c.querySelector('audio').addEventListener('play',e=>document.querySelectorAll('audio').forEach(a=>{if(a!==e.target)a.pause()}));return c}
function render(){const blind=document.getElementById('blind').checked;
const f=document.getElementById('full');f.innerHTML='';(blind?shuffle(F,11):F).forEach((it,i)=>f.appendChild(card(it,'full|'+it.id,i,blind)));
const t=document.getElementById('tabs');t.innerHTML='';S.forEach((s,i)=>{const b=document.createElement('button');b.textContent=i+1;b.className=i===cur?'on':'';b.onclick=()=>{cur=i;render()};t.appendChild(b)});
document.getElementById('stext').textContent='“'+S[cur].text+'”';const g=document.getElementById('sec');g.innerHTML='';
(blind?shuffle(S[cur].items,cur*7+3):S[cur].items).forEach((it,i)=>g.appendChild(card(it,'s'+cur+'|'+it.id,i,blind)));
document.getElementById('picks').textContent=Object.entries(likes).map(([k,v])=>(k.startsWith('full')?'Whole narration':'Section '+(+k.split('|')[0].slice(1)+1))+': '+v).join('\n')||'Nothing picked yet.'}
document.getElementById('blind').onchange=render;render();
</script></body></html>'''

if __name__ == '__main__':
    full, sections = build()
    (OUT / 'index.html').write_text(TEMPLATE.replace('__FULL__', json.dumps(full)).replace('__SECTIONS__', json.dumps(sections)))
    print('wrote', OUT / 'index.html', len(full), 'narrations,', sum(len(s['items']) for s in sections), 'section clips')
