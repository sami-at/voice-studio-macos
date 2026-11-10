"""Build the local listening comparison: level-matched copies plus an offline HTML page.

Loudness is matched with a single measured gain per file. Nothing else is touched — no
compression, no pitch or timing change — so what you compare is delivery, not volume.
Originals are never modified; the matched copies are written alongside them.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from voice_studio.audio import ffmpeg

ENGINES = ROOT / 'samples' / 'engines'
MATCHED = ENGINES / 'level-matched'
TARGET_LUFS = -20.0          # quiet enough that no file needs limiting to reach it

SCRIPTS = [
    ('1-question', 'A curious question',
     'Have you ever wondered why flies rub their hands together?'),
    ('2-surprise', 'A surprising fact',
     'Surprisingly, they are not plotting anything. They are cleaning themselves.'),
    ('3-explain', 'A conversational explanation',
     'Flies taste with their feet, so keeping them clean is how they find food.'),
    ('4-emphasis', 'A line needing natural emphasis',
     'You walk into a room and realise you have absolutely no idea why you are there.'),
    ('5-conclusion', 'A calm conclusion',
     'So the next time you see it, you will know exactly what is going on. The mystery is over.'),
]
EXAGGERATION = [
    ('chatterbox_exag25_s11', 'Exaggeration 0.25'),
    ('chatterbox_exag60_s11', 'Exaggeration 0.60'),
    ('chatterbox_exag100_s11', 'Exaggeration 1.00'),
]
SEEDS = [(f'chatterbox_exag{level}_s{seed}', f'Exaggeration {int(level)/100:.2f} · seed {seed}')
         for level in (25, 60, 100) for seed in (11, 22, 33)]


def loudness(path):
    """Integrated loudness in LUFS, measured by ffmpeg's EBU R128 meter."""
    result = subprocess.run(
        [ffmpeg(), '-nostdin', '-hide_banner', '-i', str(path),
         '-af', 'ebur128=framelog=quiet', '-f', 'null', '-'],
        capture_output=True, text=True, timeout=300)
    found = re.findall(r'I:\s*(-?\d+\.\d+)\s*LUFS', result.stderr)
    return float(found[-1]) if found else None


def level_match(source, destination):
    """Copy with one constant gain so every clip plays back at the same loudness."""
    measured = loudness(source)
    gain = 0.0 if measured is None else round(TARGET_LUFS - measured, 2)
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg(), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                    '-i', str(source), '-af', f'volume={gain}dB',
                    '-c:a', 'libmp3lame', '-b:a', '320k', str(destination)],
                   check=True, timeout=300)
    return {'measured_lufs': measured, 'gain_db': gain}


def main():
    MATCHED.mkdir(parents=True, exist_ok=True)
    wanted = {}
    for key, _, _ in SCRIPTS:
        for engine in ('current', 'chatterbox'):
            wanted[f'{engine}_{key}'] = f'{engine}_{key}'
    for name, _ in SEEDS:
        wanted[name] = name

    levels = {}
    for name in sorted(wanted):
        source = ENGINES / f'{name}.wav'
        if not source.is_file():
            print(f'  missing {source.name}, skipped', flush=True)
            continue
        info = level_match(source, MATCHED / f'{name}.mp3')
        levels[name] = info
        print(f"  {name:34s} {info['measured_lufs']:>7} LUFS  gain {info['gain_db']:+.2f} dB",
              flush=True)

    spread = [v['measured_lufs'] for v in levels.values() if v['measured_lufs'] is not None]
    print(f'\n  original loudness spread: {min(spread):.1f} to {max(spread):.1f} LUFS '
          f'({max(spread)-min(spread):.1f} dB) — all matched to {TARGET_LUFS:.0f} LUFS', flush=True)

    page = ROOT / 'docs' / 'engine-comparison.html'
    page.write_text(render(levels))
    (ROOT / 'docs' / 'comparison-levels.json').write_text(json.dumps(levels, indent=2))
    print(f'  page: {page}', flush=True)
    return page


def render(levels):
    def rel(name):
        return f'../samples/engines/level-matched/{name}.mp3'

    pairs = '\n'.join(f"""
      <section class="pair" data-pair="{key}">
        <header>
          <h3>{label}</h3>
          <p class="line">&ldquo;{text}&rdquo;</p>
        </header>
        <div class="ab">
          <article class="side">
            <div class="tag tag-a">A &middot; Current engine</div>
            <p class="meta">Qwen3-TTS 0.6B 8-bit &middot; voice: Mike</p>
            <audio preload="none" controls src="{rel(f'current_{key}')}"></audio>
          </article>
          <article class="side">
            <div class="tag tag-b">B &middot; Chatterbox</div>
            <p class="meta">multilingual v3 &middot; exaggeration 0.60 &middot; voice: Mike</p>
            <audio preload="none" controls src="{rel(f'chatterbox_{key}')}"></audio>
          </article>
        </div>
        <div class="controls">
          <button data-play="A">Play A</button>
          <button data-play="B">Play B</button>
          <button data-play="AB">A then B</button>
          <button data-play="stop">Stop</button>
          <span class="verdict">
            <label><input type="radio" name="v-{key}" value="A"> A sounds better</label>
            <label><input type="radio" name="v-{key}" value="B"> B sounds better</label>
            <label><input type="radio" name="v-{key}" value="="> No real difference</label>
          </span>
        </div>
      </section>""" for key, label, text in SCRIPTS)

    exaggeration = '\n'.join(f"""
          <article class="side">
            <div class="tag tag-b">{label}</div>
            <audio preload="none" controls src="{rel(name)}"></audio>
          </article>""" for name, label in EXAGGERATION)

    seeds = '\n'.join(f"""
          <article class="seed">
            <div class="tag tag-muted">{label}</div>
            <audio preload="none" controls src="{rel(name)}"></audio>
          </article>""" for name, label in SEEDS if (MATCHED / f'{name}.mp3').is_file())

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Engine Listening Test</title>
<style>
  :root {{
    --bg:#15171b; --panel:#1c2026; --line:#303640; --text:#e5e8ed; --muted:#99a4b4;
    --accent:#b6d8cf; --a:#8fb6d8; --b:#d8bb8f; --radius:12px;
  }}
  @media (prefers-color-scheme: light) {{
    :root:not([data-theme="dark"]) {{
      --bg:#f6f7f9; --panel:#ffffff; --line:#dfe3e9; --text:#1a1d22; --muted:#5c6673;
      --accent:#2f6f60; --a:#2d5f85; --b:#8a5f1c;
    }}
  }}
  :root[data-theme="dark"] {{
    --bg:#15171b; --panel:#1c2026; --line:#303640; --text:#e5e8ed; --muted:#99a4b4;
    --accent:#b6d8cf; --a:#8fb6d8; --b:#d8bb8f;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; background:var(--bg); color:var(--text);
    font:15px/1.6 -apple-system, "SF Pro Text", "Helvetica Neue", sans-serif;
  }}
  .wrap {{ max-width:1080px; margin:0 auto; padding:40px 16px 80px; }}
  h1 {{ font-size:27px; letter-spacing:-.6px; margin:0 0 6px; }}
  h2 {{ font-size:19px; margin:44px 0 14px; padding-bottom:9px; border-bottom:1px solid var(--line); }}
  h3 {{ font-size:15px; margin:0 0 4px; color:var(--accent); }}
  p.sub {{ color:var(--muted); margin:0 0 4px; }}
  .note {{
    background:var(--panel); border:1px solid var(--line); border-radius:var(--radius);
    padding:16px 18px; margin:22px 0;
  }}
  .note p {{ margin:0 0 8px; }}
  .note p:last-child {{ margin:0; }}
  ul.listen {{ margin:10px 0 0; padding-left:20px; color:var(--muted); }}
  ul.listen li {{ margin-bottom:5px; }}
  ul.listen b {{ color:var(--text); font-weight:600; }}
  .pair {{
    background:var(--panel); border:1px solid var(--line); border-radius:var(--radius);
    padding:18px; margin-bottom:16px;
  }}
  .line {{ color:var(--muted); font-style:italic; margin:0 0 14px; }}
  .ab {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
  @media (max-width:720px) {{ .ab {{ grid-template-columns:1fr; }} }}
  .side {{ border:1px solid var(--line); border-radius:9px; padding:12px; }}
  .tag {{ font-size:11px; font-weight:700; letter-spacing:.8px; text-transform:uppercase; }}
  .tag-a {{ color:var(--a); }} .tag-b {{ color:var(--b); }} .tag-muted {{ color:var(--muted); }}
  .meta {{ color:var(--muted); font-size:12px; margin:3px 0 10px; }}
  audio {{ width:100%; }}
  .controls {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:14px; }}
  button {{
    background:transparent; color:var(--text); border:1px solid var(--line);
    border-radius:7px; padding:7px 13px; font:inherit; font-size:13px; cursor:pointer;
  }}
  button:hover {{ border-color:var(--accent); color:var(--accent); }}
  button.on {{ background:var(--accent); color:var(--bg); border-color:var(--accent); }}
  .verdict {{ display:flex; flex-wrap:wrap; gap:12px; margin-left:auto; font-size:13px; color:var(--muted); }}
  .verdict label {{ cursor:pointer; }}
  .grid3 {{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; }}
  @media (max-width:720px) {{ .grid3 {{ grid-template-columns:1fr; }} }}
  .seeds {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }}
  @media (max-width:720px) {{ .seeds {{ grid-template-columns:1fr; }} }}
  .seed {{ border:1px solid var(--line); border-radius:9px; padding:10px; }}
  footer {{ color:var(--muted); font-size:13px; margin-top:46px;
            border-top:1px solid var(--line); padding-top:16px; }}
  code {{ background:rgba(127,127,127,.14); padding:1px 5px; border-radius:4px; font-size:12.5px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Which engine narrates better?</h1>
  <p class="sub">Same script, same voice (Mike), level-matched. Your ears decide this one.</p>

  <div class="note">
    <p><b>Every clip is matched to the same loudness</b> ({TARGET_LUFS:.0f} LUFS) with a single
    constant gain. Nothing else was altered — no compression, no pitch or timing change. The
    original recordings are untouched in <code>samples/engines/</code>.</p>
    <p>The measurements said Chatterbox is <b>6.5&times; slower</b> (a 45-second narration takes
    about 7 minutes instead of 31 seconds) and that its expressiveness control did not behave
    consistently. Measurements cannot judge naturalness, so ignore all of that until you have
    listened.</p>
  </div>

  <h2>What to listen for</h2>
  <div class="note">
    <ul class="listen">
      <li><b>Naturalness</b> — does it sound like a person explaining, or a machine reading?</li>
      <li><b>Emotional expression</b> — is there genuine interest, or flat recitation?</li>
      <li><b>Intonation</b> — does pitch move with the meaning? Does the question rise?</li>
      <li><b>Emphasis</b> — in sample 4, does &ldquo;absolutely no idea&rdquo; stand out?</li>
      <li><b>Sentence endings</b> — does &ldquo;The mystery is over&rdquo; feel finished, or cut off?</li>
      <li><b>Pacing</b> — are the pauses where a person would put them?</li>
      <li><b>Voice consistency</b> — does it stay recognisably Mike throughout?</li>
      <li><b>Clarity</b> — any slurred, dropped or mispronounced words?</li>
    </ul>
  </div>

  <h2>A / B comparison &mdash; same script, both engines</h2>
  {pairs}

  <h2>Does the expressiveness dial do anything?</h2>
  <div class="note">
    <p>Chatterbox alone, same sentence and seed, only <code>exaggeration</code> changes. If the
    dial works, these should differ in a consistent direction. Measured pitch variation moved
    the <i>wrong</i> way (4.85 &rarr; 4.16 semitones as the dial went up), so this is the claim
    to test by ear.</p>
  </div>
  <div class="grid3">{exaggeration}</div>

  <h2>Is it the dial, or just the seed?</h2>
  <div class="note">
    <p>The same three settings across three random seeds. If seeds at one setting differ as much
    as the settings differ from each other, the dial is not really controlling anything.</p>
  </div>
  <div class="seeds">{seeds}</div>

  <footer>
    Generated locally by <code>scripts/build_comparison.py</code>. Works offline; no network,
    fonts or scripts are loaded from anywhere. Current engine: Qwen3-TTS 12&#8239;Hz 0.6B Base,
    8-bit MLX. Candidate: Chatterbox multilingual v3, MLX.
  </footer>
</div>
<script>
  // One clip at a time, so a comparison is never muddled by two playing at once.
  const all = Array.from(document.querySelectorAll('audio'));
  all.forEach(a => a.addEventListener('play', () => {{
    all.forEach(o => {{ if (o !== a) {{ o.pause(); }} }});
  }}));

  let chain = null;
  function stopChain() {{
    if (chain) {{ clearTimeout(chain.timer); chain.audio.removeEventListener('ended', chain.next); }}
    chain = null;
    document.querySelectorAll('button.on').forEach(b => b.classList.remove('on'));
  }}

  document.querySelectorAll('.pair').forEach(pair => {{
    const [a, b] = pair.querySelectorAll('audio');
    pair.querySelectorAll('button[data-play]').forEach(button => {{
      button.addEventListener('click', () => {{
        const mode = button.dataset.play;
        all.forEach(o => {{ o.pause(); }});
        stopChain();
        if (mode === 'stop') return;
        button.classList.add('on');
        if (mode === 'A' || mode === 'B') {{
          const clip = mode === 'A' ? a : b;
          clip.currentTime = 0;
          clip.play();
          return;
        }}
        a.currentTime = 0; b.currentTime = 0;
        const next = () => {{ b.currentTime = 0; b.play(); }};
        chain = {{ audio: a, next, timer: null }};
        a.addEventListener('ended', next, {{ once: true }});
        a.play();
      }});
    }});
  }});

  // Remember verdicts between visits, so a second listening session can continue.
  document.querySelectorAll('.verdict input').forEach(input => {{
    try {{
      if (localStorage.getItem(input.name) === input.value) input.checked = true;
    }} catch (e) {{}}
    input.addEventListener('change', () => {{
      try {{ localStorage.setItem(input.name, input.value); }} catch (e) {{}}
    }});
  }});
</script>
</body>
</html>
"""


if __name__ == '__main__':
    main()
