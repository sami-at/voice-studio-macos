"""Build samples/natural-upgrade/: level-matched before/after clips and an offline listening page.

Reads recordings that already exist (benchmark clips, experiments, matrix takes). Writes only under
samples/natural-upgrade/. Nothing in local_data/ is touched.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_audio import ROOT, active_span, load, matched  # noqa: E402
from voice_studio import audio as A, styles  # noqa: E402

OUT = ROOT / 'samples/natural-upgrade'
EXP = OUT / 'experiments'
MATRIX = ROOT / 'samples/final-quality'
BENCH = ROOT / 'samples/elevenlabs-benchmark'
CHAIN = [
    "Have you ever wondered why do flies rub their hands together like they're planning something?",
    "You might have noticed that whenever a fly lands, it starts rubbing its front legs together.",
    "It looks a little suspicious, but there's actually an interesting reason behind it.",
    "Flies spend a surprising amount of time cleaning themselves.",
]


def leveled(audio, rate, name, folder='audio'):
    """Trim to the speech (keeping 150 ms before, 300 ms after), match loudness, write 16-bit WAV."""
    s0, s1 = active_span(audio, rate)
    clip = audio[max(0, int((s0 - .15) * rate)):int((s1 + .30) * rate)]
    out, gain, _ = matched(clip, rate)
    path = OUT / folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, out, rate, subtype='PCM_16')
    return f'{folder}/{name}'


def narration(sections, folder, name, style=styles.NATURAL):
    """The app's own pipeline: write_segment then join_segments."""
    values = styles.settings(style)
    with tempfile.TemporaryDirectory() as temp:
        segments = []
        for i, (raw, text, end) in enumerate(sections):
            path = Path(temp) / f'{i}.wav'
            A.write_segment(raw, path, values['speed'])
            segments.append({'file': str(path), 'text': text, 'paragraph_end': end})
        target = Path(temp) / 'out.wav'
        A.join_segments({'segments': segments, 'pause': values['pause'],
                         'sentence_pause': values['sentence_pause']}, temp, target)
        audio, rate = load(target)
    return leveled(audio, rate, name, folder)


def read(path):
    audio, rate = sf.read(str(path), dtype='float32')
    return audio, rate


def build():
    groups = []

    # 1. Abrupt ending: your take vs the take chosen by the fixed rule (existing benchmark clips)
    for source in ('elevenlabs', 'vs-original', 'vs-repaired'):
        pass
    groups.append({
        'title': '1. The opening question: cut-off ending vs a complete one',
        'note': 'Phrase 1 of your narration. Listen to the very end ("…something?") with the "last second" button. '
                'The first take stops at near full level; the second fades the way ElevenLabs does. The new '
                'check flags the first and retries automatically; nothing is faded to hide it.',
        'items': [
            {'label': 'ElevenLabs (reference)', 'file': '../elevenlabs-benchmark/audio/phrases/p1-elevenlabs.wav'},
            {'label': 'Your original take (seed 1996) · flagged: ending may be cut off',
             'file': '../elevenlabs-benchmark/audio/phrases/p1-vs-original.wav'},
            {'label': 'Retried take (seed 2007) · passes the new check',
             'file': '../elevenlabs-benchmark/audio/phrases/p1-vs-repaired.wav'}]})

    # 2. [pace:] on one identical raw recording
    raw, rate = read(MATRIX / 'hal-qwen3-natural/03-raw.wav')
    items = []
    for label, mark, speed in (('[pace:slow]  (x0.93 speed, 1.075x as long)', 'slow', .93),
                               ('[pace:normal]', 'normal', 1.0), ('[pace:fast]  (x1.07 speed, 0.93x as long)', 'fast', 1.07)):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'x.wav'
            A.write_segment(raw, path, speed)
            audio, r = load(path)
        items.append({'label': label, 'file': leveled(audio, r, f'pace-{mark}.wav')})
    groups.append({
        'title': '2. [pace:] on the same recording',
        'note': 'One raw recording of "It looks a little suspicious, but there\'s actually an interesting reason behind it." '
                'processed three ways. Same words, voice and take; only the speed differs. This is a speed control, '
                'not an expressiveness control, and it is for you to say whether slower or faster sounds better here.',
        'items': items})

    # 3. chained context vs fixed reference
    items = []
    for seed in (42, 43):
        for mode, label in (('fixed', 'Normal (fixed reference)'), ('chained', 'Chained (each sentence conditioned on the previous one)')):
            sections = [(read(EXP / 'chain' / f'{mode}-{seed}-{i + 1}.wav')[0], CHAIN[i], i == 3) for i in range(4)]
            items.append({'label': f'{label} · seed {seed}', 'file': narration(sections, 'audio', f'chain-{mode}-{seed}.wav')})
    groups.append({
        'title': '3. Chaining context: smoother pitch, duller voice',
        'note': 'Four sentences, generated either on the fixed Hal reference or each on the previous sentence\'s own recording. '
                'Measured: chaining halves the sentence-to-sentence pitch spread but brightness falls 10-25% per step. '
                'It is NOT enabled in the app. Listen for whether the later sentences sound muffled.',
        'items': items})

    # 4. reference-clip as delivery control
    items = []
    for ref, label in (('calm', 'Calm reference (the app\'s window)'), ('question', 'Question-style reference')):
        for seed in (42, 43, 44):
            audio, r = read(EXP / 'delivery-ref' / f'{ref}-question-{seed}.wav')
            items.append({'label': f'{label} · seed {seed}', 'file': leveled(audio, r, f'delivery-{ref}-{seed}.wav')})
    groups.append({
        'title': '4. Does the reference clip direct delivery?',
        'note': 'The opening question, three seeds on each reference. Measured over five seeds: no reliable change in pitch '
                'or pitch range, so "[delivery:curious]" is refused. If you can hear a consistent difference between the '
                'two rows, tell me; the numbers say you should hear take-to-take variety instead.',
        'items': items})

    # 5. section joins: what the review tab flags
    groups.append({
        'title': '5. A join the review tab flags (your narration, section 6 → 7)',
        'note': 'The review tab reports +7.5 semitones of typical pitch and 1.9x brightness across this join. Listen to '
                'whether the last two sentences sound like a different session.',
        'items': [{'label': 'Phrases 7, 8 and 9 of your original', 'file': None, 'multi': [
            '../elevenlabs-benchmark/audio/phrases/p7-vs-original.wav',
            '../elevenlabs-benchmark/audio/phrases/p8-vs-original.wav',
            '../elevenlabs-benchmark/audio/phrases/p9-vs-original.wav']}]})

    (OUT / 'data').mkdir(parents=True, exist_ok=True)
    (OUT / 'data/groups.json').write_text(json.dumps(groups, indent=1))
    return groups


TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Narration upgrade listening</title>
<style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1c1c1a;--mute:#66665f;--line:#dcdcd4;--accent:#1f5fbf;--warn:#8a4b00;--warnbg:#fff4e0}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--panel:#1f1f1d;--ink:#ecece6;--mute:#a2a299;--line:#34342f;--accent:#6aa3ff;--warn:#ffcf8a;--warnbg:#2e2412}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 -apple-system,BlinkMacSystemFont,system-ui,sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px 80px}h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.1rem;margin:32px 0 4px}
.mute{color:var(--mute)}.note{background:var(--warnbg);color:var(--warn);border-radius:8px;padding:10px 14px;margin:14px 0;font-size:.92rem}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px;margin:10px 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:6px}
.card.liked{border-color:#c2185b}.name{font-weight:600;font-size:.95rem}audio{width:100%;height:36px}
button{font:inherit;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:5px 12px;cursor:pointer}
button[aria-pressed=true]{background:#c2185b;border-color:#c2185b;color:#fff}.row{display:flex;gap:8px;flex-wrap:wrap}
pre{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px;white-space:pre-wrap}
</style></head><body><main>
<h1>Narration upgrade: before and after</h1>
<p class="mute">Level-matched (-24 LUFS). Nobody has listened to these yet; the numbers in the notes are measurements, not opinions.</p>
<div class="note">Press ♡ on the ones that sound good to you. Likes are saved in this browser.</div>
<div id="groups"></div>
<h2>Your likes</h2><pre id="likes"></pre><div class="row"><button id="copy">Copy</button><button id="clear">Clear</button></div>
</main><script>
const G=__GROUPS__;let likes={};try{likes=JSON.parse(localStorage.getItem('natural-upgrade-likes')||'{}')||{}}catch(e){}
const save=()=>{try{localStorage.setItem('natural-upgrade-likes',JSON.stringify(likes))}catch(e){}};
function render(){const host=document.getElementById('groups');host.innerHTML='';
G.forEach((g,gi)=>{const h=document.createElement('div');h.innerHTML=`<h2>${g.title}</h2><p class="mute">${g.note}</p>`;const grid=document.createElement('div');grid.className='grid';
g.items.forEach((it,ii)=>{const key=gi+'|'+it.label;const c=document.createElement('div');c.className='card'+(likes[key]?' liked':'');
const files=it.multi||[it.file];
c.innerHTML=`<div class="name">${it.label}</div>`+files.map(f=>`<audio controls preload="auto" src="${f}"></audio>`).join('')+`<div class="row"><button aria-pressed="${!!likes[key]}">${likes[key]?'♥ Liked':'♡ Like'}</button><button data-end>last second</button></div>`;
c.querySelector('button').onclick=()=>{likes[key]?delete likes[key]:likes[key]=1;save();render()};
c.querySelector('[data-end]').onclick=()=>{const a=c.querySelector('audio');document.querySelectorAll('audio').forEach(x=>x.pause());const go=()=>{a.currentTime=Math.max(0,a.duration-1);a.play()};a.readyState>=1?go():a.addEventListener('loadedmetadata',go,{once:true})};
c.querySelectorAll('audio').forEach(a=>a.addEventListener('play',()=>document.querySelectorAll('audio').forEach(x=>{if(x!==a)x.pause()})));
grid.appendChild(c)});h.appendChild(grid);host.appendChild(h)});
document.getElementById('likes').textContent=Object.keys(likes).map(k=>G[+k.split('|')[0]].title.split(':')[0]+' '+k.split('|').slice(1).join('|')).join('\n')||'Nothing liked yet.'}
document.getElementById('copy').onclick=()=>navigator.clipboard.writeText(document.getElementById('likes').textContent);
document.getElementById('clear').onclick=()=>{if(confirm('Remove all likes?')){likes={};save();render()}};render();
</script></body></html>
'''

if __name__ == '__main__':
    groups = build()
    (OUT / 'index.html').write_text(TEMPLATE.replace('__GROUPS__', json.dumps(groups)))
    print('wrote', OUT / 'index.html', sum(len(g['items']) for g in groups), 'items')
