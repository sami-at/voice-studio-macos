"""Write samples/elevenlabs-benchmark/index.html from data/benchmark.json.

One self-contained page: no network, no external scripts or fonts. Open it by double-clicking.
Clips are already level-matched (integrated loudness, -24 LUFS) by benchmark_build.py.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'samples/elevenlabs-benchmark'


def main():
    data = json.loads((OUT / 'data/benchmark.json').read_text())
    repair = json.loads((OUT / 'data/repair-choice.json').read_text())
    payload = json.dumps({'data': data, 'repair': repair}, separators=(',', ':'))
    (OUT / 'index.html').write_text(TEMPLATE.replace('__PAYLOAD__', payload))
    print('wrote', OUT / 'index.html')


TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hal listening comparison</title>
<style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1c1c1a;--mute:#66665f;--line:#dcdcd4;--accent:#1f5fbf;--accent-ink:#fff;--warn:#8a4b00;--warn-bg:#fff4e0;--ok:#1d6b3a;--play:#e8f0fc}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#161615;--panel:#1f1f1d;--ink:#ececE6;--mute:#a2a299;--line:#34342f;--accent:#6aa3ff;--accent-ink:#0b0b0a;--warn:#ffcf8a;--warn-bg:#2e2412;--ok:#7bd69a;--play:#1b2638}}
:root[data-theme="dark"]{--bg:#161615;--panel:#1f1f1d;--ink:#ececE6;--mute:#a2a299;--line:#34342f;--accent:#6aa3ff;--accent-ink:#0b0b0a;--warn:#ffcf8a;--warn-bg:#2e2412;--ok:#7bd69a;--play:#1b2638}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 80px}
h1{font-size:1.6rem;margin:0 0 4px}h2{font-size:1.2rem;margin:36px 0 8px}h3{font-size:1rem;margin:20px 0 6px}
p{margin:6px 0}.mute{color:var(--mute)}.small{font-size:.86rem}
.note{background:var(--warn-bg);color:var(--warn);border-radius:8px;padding:10px 14px;margin:14px 0;font-size:.92rem}
.bar{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:14px 0;position:sticky;top:0;z-index:5}
label{display:inline-flex;gap:6px;align-items:center;cursor:pointer}
button{font:inherit;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:6px 12px;cursor:pointer}
button:hover{border-color:var(--accent)}button.primary{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.tabs button[aria-selected="true"]{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.phrase{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:8px 0}
.phrase .kind{font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;color:var(--mute)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px;margin:10px 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:6px}
.card.playing{background:var(--play);border-color:var(--accent)}
.card .name{font-weight:600}.card .meta{font-size:.8rem;color:var(--mute);font-variant-numeric:tabular-nums}
.card .row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
audio{width:100%;height:36px}
.key{display:inline-block;min-width:1.4em;text-align:center;border:1px solid var(--line);border-radius:4px;font-size:.78rem;color:var(--mute);padding:0 4px}
table{border-collapse:collapse;width:100%;font-size:.86rem;font-variant-numeric:tabular-nums}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:right}th:first-child,td:first-child{text-align:left}
th{color:var(--mute);font-weight:600;position:sticky;top:0;background:var(--bg)}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--panel)}
.grp{font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;color:var(--mute);margin:18px 0 4px}
a{color:var(--accent)}code{font-size:.88em}
.flag{color:var(--warn)}
button.like{display:inline-flex;gap:5px;align-items:center}
button.like[aria-pressed="true"]{background:#c2185b;border-color:#c2185b;color:#fff}
.card.liked{border-color:#c2185b}
.tabs button .n{font-size:.75rem;margin-left:4px;opacity:.9}
.likes li{margin:2px 0}
</style>
</head>
<body>
<main>
<h1>Hal: ElevenLabs vs Voice Studio</h1>
<p class="mute">Same "Why do flies rub their hands together" script. Everything on this page is offline and level-matched to the same integrated loudness (-24 LUFS), so louder does not read as better.</p>
<div class="note"><strong>These files are for your ears.</strong> Nobody has listened to them yet. The numbers beside each clip show where recordings differ; they do not show which one sounds natural or human. The Alternatives are single fixed-seed takes with no take selection, so they show what each engine does by default, not its best.</div>

<div class="bar" id="bar">
  <label><input type="checkbox" id="blind"> Blind mode (shuffle and hide names)</label>
  <label><input type="checkbox" id="loop"> Loop clip</label>
  <label><input type="checkbox" id="metrics" checked> Show measurements</label>
  <button id="reveal" hidden>Reveal names</button>
  <span class="small mute">Keys: <span class="key">1</span>-<span class="key">9</span> play that card (phrase view), <span class="key">Space</span> pause, <span class="key">←</span><span class="key">→</span> previous/next phrase</span>
</div>

<h2>1. Whole narrations</h2>
<p class="mute small">Level-matched copies. The bit-identical originals are in <code>audio/originals/</code>.</p>
<div id="full"></div>

<h2>2. Phrase by phrase</h2>
<p class="mute small">Matching phrases from every source, cut at the quietest point between sentences. Use "Play all" to hear them back to back; "last second" replays only the ending.</p>
<div class="tabs" id="tabs" role="tablist"></div>
<div class="phrase" id="phrase"></div>
<div class="row"><button class="primary" id="playall">Play all in order</button> <button id="stop">Stop</button></div>
<div id="grid"></div>

<h2>3. Your likes</h2>
<p class="mute small">Saved in this browser on this Mac. Names are hidden while blind mode is on; reveal to see them.</p>
<div id="likes" class="phrase"></div>
<div class="row" style="margin-top:8px"><button id="copylikes">Copy as text</button> <button id="dllikes">Download JSON</button> <button id="clearlikes">Clear all likes</button></div>

<h2>4. What the measurements say</h2>
<p class="mute small">Averages over the nine phrases. Pace is words per second of speech time; pitch range is the 5th-95th percentile of tracked F0 in semitones; sentence gap is the silence before each phrase. Octave levels are relative to the 1 kHz octave. Alignment uses offline Whisper word times (approximate), so differences of a few percent are noise.</p>
<div class="scroll"><table id="summary"></table></div>
<p class="small mute" style="margin-top:10px">Opening-question repair rule and candidates (same text, same Energetic settings, only the seed changes):</p>
<div class="scroll"><table id="repair"></table></div>
<p class="small mute">Full explanation: <code>docs/ELEVENLABS-QUALITY-BENCHMARK.md</code>.</p>
</main>
<script>
const P = __PAYLOAD__;
const D = P.data, S = D.sources, N = D.script.length;
const $ = (s, r = document) => r.querySelector(s);
let likes = {};
try { likes = JSON.parse(localStorage.getItem('hal-benchmark-likes') || '{}') || {}; } catch (e) { likes = {}; }
function saveLikes() { try { localStorage.setItem('hal-benchmark-likes', JSON.stringify(likes)); } catch (e) { /* private window: likes last until the page closes */ } }
let phrase = 0, blind = false, order = {}, playing = null, seqAbort = false;
const letters = 'ABCDEFGHIJKLMNOP';
function shuffle(a, seed) { a = a.slice(); let s = seed; for (let i = a.length - 1; i > 0; i--) { s = (s * 1664525 + 1013904223) >>> 0; const j = s % (i + 1); [a[i], a[j]] = [a[j], a[i]]; } return a; }
function ordered(key) { const ids = S.map(s => s.id); if (!blind) return ids; if (!order[key]) order[key] = shuffle(ids, 7 + key.length * 31 + (key.charCodeAt(0) || 0)); return order[key]; }
const byId = id => S.find(s => s.id === id);
function fmt(x, d = 1) { return x === null || x === undefined ? '–' : Number(x).toFixed(d); }

function card(src, file, idx, extra, key) {
  const c = document.createElement('div'); c.className = 'card'; c.dataset.id = src.id;
  const shownName = blind ? 'Clip ' + letters[idx] : src.label;
  const meta = (!blind || !$('#blind').checked) ? '' : '';
  c.innerHTML = `<div class="name"><span class="key">${idx < 9 ? idx + 1 : ''}</span> ${shownName}</div>
    <audio controls preload="auto" src="${file}"></audio>
    <div class="row"><button class="like" data-act="like" aria-pressed="false" title="Like this one">♡ Like</button><button data-act="end">last second</button></div>
    <div class="meta">${blind ? '' : (extra.meta || '')}</div>
    <div class="small mute">${blind ? '' : src.description}</div>`;
  const a = $('audio', c);
  a.addEventListener('play', () => { if (playing && playing !== a) playing.pause(); playing = a; document.querySelectorAll('.card').forEach(x => x.classList.remove('playing')); c.classList.add('playing'); });
  a.addEventListener('pause', () => c.classList.remove('playing'));
  a.addEventListener('ended', () => { c.classList.remove('playing'); if ($('#loop').checked) { a.currentTime = 0; a.play(); } });
  $('[data-act=end]', c).onclick = () => { stopAll(); const go = () => { a.currentTime = Math.max(0, a.duration - 1.0); a.play(); }; a.readyState >= 1 ? go() : a.addEventListener('loadedmetadata', go, { once: true }); };
  const lb = $('[data-act=like]', c), lk = key + '|' + src.id;
  const sync = () => { const on = !!likes[lk]; lb.setAttribute('aria-pressed', on); lb.textContent = on ? '♥ Liked' : '♡ Like'; c.classList.toggle('liked', on); };
  lb.onclick = () => { if (likes[lk]) delete likes[lk]; else likes[lk] = Date.now(); saveLikes(); sync(); renderLikes(); renderTabCounts(); };
  sync();
  return c;
}
function stopAll() { seqAbort = true; document.querySelectorAll('audio').forEach(a => a.pause()); }

function renderFull() {
  const host = $('#full'); host.innerHTML = '';
  let lastGroup = null; const ids = ordered('full');
  const g = document.createElement('div'); g.className = 'grid'; host.appendChild(g);
  ids.forEach((id, i) => {
    const s = byId(id);
    if (!blind && s.group !== lastGroup) { const h = document.createElement('div'); h.className = 'grp'; h.style.gridColumn = '1/-1'; h.textContent = s.group; g.appendChild(h); lastGroup = s.group; }
    const meta = `${fmt(s.seconds)} s · ${s.rate / 1000} kHz source · gain ${fmt(s.full_gain_db)} dB to match`;
    g.appendChild(card(s, s.full, i, { meta }, 'full'));
  });
}
function renderPhrase() {
  $('#phrase').innerHTML = `<div class="kind">Phrase ${phrase + 1} of ${N} · ${D.kinds[phrase]}</div><div>${D.script[phrase]}</div>`;
  document.querySelectorAll('#tabs button').forEach((b, i) => b.setAttribute('aria-selected', i === phrase));
  const host = $('#grid'); host.innerHTML = ''; let lastGroup = null;
  const g = document.createElement('div'); g.className = 'grid'; host.appendChild(g);
  ordered('p' + phrase).forEach((id, i) => {
    const s = byId(id), p = s.phrases[phrase];
    if (!p.file) return;
    if (!blind && s.group !== lastGroup) { const h = document.createElement('div'); h.className = 'grp'; h.style.gridColumn = '1/-1'; h.textContent = s.group; g.appendChild(h); lastGroup = s.group; }
    const flag = p.end_decay_db > -15 ? '<span class="flag"> · abrupt ending</span>' : '';
    const meta = $('#metrics').checked ? `${fmt(p.speech_s)} s · ${fmt(p.wps, 2)} words/s · pitch range ${fmt(p.f0_range_st)} st · ending decay ${fmt(p.end_decay_db)} dB${flag}` : '';
    g.appendChild(card(s, p.file, i, { meta }, 'p' + (phrase + 1)));
  });
}
async function playAll() {
  seqAbort = false; stopAll(); seqAbort = false;
  for (const a of document.querySelectorAll('#grid audio')) {
    if (seqAbort) return;
    a.currentTime = 0;
    await new Promise(res => { const done = () => { a.removeEventListener('ended', done); a.removeEventListener('pause', pausedEarly); res(); };
      const pausedEarly = () => { if (a.currentTime < a.duration - .05) { done(); } };
      a.addEventListener('ended', done); a.addEventListener('pause', pausedEarly); a.play().catch(done); });
    await new Promise(r => setTimeout(r, 450));
  }
}
function likeRows() {
  const rows = [];
  S.forEach(s => {
    const parts = [];
    if (likes['full|' + s.id]) parts.push('whole narration');
    for (let i = 1; i <= N; i++) if (likes['p' + i + '|' + s.id]) parts.push('P' + i);
    if (parts.length) rows.push({ id: s.id, label: s.label, parts, count: parts.length });
  });
  return rows.sort((a, b) => b.count - a.count);
}
function renderLikes() {
  const rows = likeRows(), host = $('#likes');
  if (!rows.length) { host.innerHTML = '<span class="mute">Nothing liked yet. Press ♡ Like on any clip.</span>'; return; }
  if (blind) { host.innerHTML = `<span class="mute">${rows.reduce((n, r) => n + r.count, 0)} like(s) saved. Reveal names to see them.</span>`; return; }
  host.innerHTML = '<ol class="likes">' + rows.map(r => `<li><strong>${r.label}</strong> — ${r.count} like${r.count > 1 ? 's' : ''}: ${r.parts.join(', ')}</li>`).join('') + '</ol>';
}
function renderTabCounts() {
  document.querySelectorAll('#tabs button').forEach((b, i) => {
    const n = S.filter(s => likes['p' + (i + 1) + '|' + s.id]).length;
    b.innerHTML = 'P' + (i + 1) + (n ? `<span class="n">♥${n}</span>` : '');
  });
}
function likesText() { return likeRows().map(r => `${r.label}: ${r.parts.join(', ')}`).join('\n') || 'No likes yet.'; }
function renderTables() {
  const bands = D.octaves_hz;
  let h = `<tr><th>Source</th><th>Length s</th><th>Words/s</th><th>Pitch range st</th><th>Sentence gap s (SD)</th><th>Abrupt endings</th>${bands.slice(5).map(b => `<th>${b >= 1000 ? b / 1000 + 'k' : b} dB</th>`).join('')}</tr>`;
  S.forEach(s => { const m = s.summary; h += `<tr><td>${s.label}</td><td>${fmt(s.seconds)}</td><td>${fmt(m.wps, 2)}</td><td>${fmt(m.f0_range_st)}</td><td>${fmt(m.gap_mean_s, 2)} (${fmt(m.gap_sd_s, 2)})</td><td>${m.abrupt_endings}/${m.phrases}</td>${s.octave_db.slice(5).map(v => `<td>${fmt(v)}</td>`).join('')}</tr>`; });
  $('#summary').innerHTML = h;
  let r = '<tr><th>Take</th><th>Seed</th><th>Length s</th><th>Words match script</th><th>Ending decay dB</th><th>Start abrupt</th><th>Verdict</th></tr>';
  P.repair.candidates.forEach(c => { const chosen = P.repair.chosen && c.seed === P.repair.chosen.seed; r += `<tr><td>${c.index}${c.index === 1 ? ' (your take)' : ''}</td><td>${c.seed}</td><td>${fmt(c.seconds, 2)}</td><td>${c.asr_ok ? 'yes' : 'no'}</td><td>${fmt(c.tail_decay_db)}${c.tail_abrupt ? ' <span class="flag">abrupt</span>' : ''}</td><td>${c.head_abrupt ? '<span class="flag">yes</span>' : 'no'}</td><td>${chosen ? '<strong>chosen</strong>' : c.accepted ? 'accepted' : 'rejected'}</td></tr>`; });
  $('#repair').innerHTML = r;
}
function build() {
  $('#tabs').innerHTML = ''; for (let i = 0; i < N; i++) { const b = document.createElement('button'); b.textContent = 'P' + (i + 1); b.setAttribute('role', 'tab'); b.onclick = () => { stopAll(); phrase = i; renderPhrase(); renderTabCounts(); }; $('#tabs').appendChild(b); }
  renderFull(); renderPhrase(); renderTables(); renderLikes(); renderTabCounts();
}
$('#blind').onchange = e => { blind = e.target.checked; order = {}; $('#reveal').hidden = !blind; stopAll(); renderFull(); renderPhrase(); renderLikes(); };
$('#reveal').onclick = () => { $('#blind').checked = false; blind = false; $('#reveal').hidden = true; renderFull(); renderPhrase(); renderLikes(); };
$('#copylikes').onclick = async () => { try { await navigator.clipboard.writeText(likesText()); $('#copylikes').textContent = 'Copied'; } catch (e) { prompt('Copy your likes:', likesText()); } setTimeout(() => $('#copylikes').textContent = 'Copy as text', 1500); };
$('#dllikes').onclick = () => { const blob = new Blob([JSON.stringify({ liked: Object.keys(likes).sort(), summary: likeRows() }, null, 2)], { type: 'application/json' }); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'hal-likes.json'; a.click(); };
$('#clearlikes').onclick = () => { if (confirm('Remove all likes?')) { likes = {}; saveLikes(); renderFull(); renderPhrase(); renderLikes(); renderTabCounts(); } };
$('#metrics').onchange = renderPhrase; $('#playall').onclick = playAll; $('#stop').onclick = stopAll;
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.metaKey || e.ctrlKey) return;
  if (e.key === ' ') { e.preventDefault(); if (playing && !playing.paused) playing.pause(); else if (playing) playing.play(); }
  else if (e.key === 'ArrowRight') { stopAll(); phrase = Math.min(N - 1, phrase + 1); renderPhrase(); }
  else if (e.key === 'ArrowLeft') { stopAll(); phrase = Math.max(0, phrase - 1); renderPhrase(); }
  else if (/^[1-9]$/.test(e.key)) { const a = document.querySelectorAll('#grid audio')[+e.key - 1]; if (a) { stopAll(); a.currentTime = 0; a.play(); } }
});
build();
</script>
</body>
</html>
'''

if __name__ == '__main__':
    main()
