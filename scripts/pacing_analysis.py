"""Where does narration time go? Speech vs pauses, per section and for the whole narration. Read-only.

  python scripts/pacing_analysis.py <session-id-prefix> [...]
"""
import json, sys
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from voice_studio import storage  # noqa: E402

BLOCK = 0.01          # 10 ms
QUIET_DB = -50.0      # below this is a pause (digital silence sits near -100)
MIN_PAUSE = 0.08      # shorter dips are consonant closures, not pauses


def levels(x, rate):
    n = int(rate * BLOCK)
    k = len(x) // n
    return 10 * np.log10(np.mean(np.square(x[:k * n].astype(np.float64)).reshape(k, n), axis=1) + 1e-20)


def runs(mask):
    out, i = [], 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j < len(mask) and mask[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def take_timing(path):
    """Speech span, pauses inside the speech, and quiet at the edges of one processed section."""
    x, rate = sf.read(path, dtype='float32')
    e = levels(x, rate)
    live = np.flatnonzero(e > QUIET_DB)
    first, last = live[0], live[-1] + 1
    inner = [(a, b) for a, b in runs(e[first:last] <= QUIET_DB) if (b - a) * BLOCK >= MIN_PAUSE]
    pauses = [(b - a) * BLOCK for a, b in inner]
    span = (last - first) * BLOCK
    return {'span_s': span, 'inner_pause_s': sum(pauses), 'inner_pauses': [round(p, 2) for p in pauses],
            'voiced_s': span - sum(pauses), 'lead_quiet_s': first * BLOCK, 'tail_quiet_s': len(e) * BLOCK - last * BLOCK}


def analyse(prefix):
    folder = next(p for p in (storage.DATA / 'sessions').iterdir() if p.name.startswith(prefix))
    s = storage.read_json(folder / 'project.json')
    total = s.get('seconds') or sf.info(storage.DATA / s['output']).duration
    rows = []
    for g in s['segments']:
        t = storage.selected_take(g)
        timing = take_timing(storage.DATA / t['file'])
        timing['words'] = len(g['text'].split())
        timing['engine'] = t['engine']
        timing['text'] = g['text']
        timing['wps_speech'] = round(timing['words'] / timing['span_s'], 2)
        timing['wps_voiced'] = round(timing['words'] / timing['voiced_s'], 2)
        rows.append(timing)
    span = sum(r['span_s'] for r in rows)
    inner = sum(r['inner_pause_s'] for r in rows)
    between = total - span                       # silence between sections, incl. edge quiet and opening/closing
    x, rate = sf.read(storage.DATA / s['output'], dtype='float32')
    e = levels(x, rate)
    live = np.flatnonzero(e > QUIET_DB)
    summary = {'session': folder.name, 'engine': sorted({r['engine'] for r in rows}), 'style': s.get('style'),
               'settings': s.get('settings'), 'total_s': round(total, 2), 'voiced_s': round(span - inner, 2),
               'pauses_inside_sections_s': round(inner, 2), 'between_sections_s': round(between - live[0] * BLOCK
                                                                                       - (len(e) - live[-1] - 1) * BLOCK, 2),
               'opening_s': round(live[0] * BLOCK, 2), 'closing_s': round((len(e) - live[-1] - 1) * BLOCK, 2),
               'words': sum(r['words'] for r in rows), 'sections': rows}
    summary['wps_overall'] = round(summary['words'] / total, 2)
    summary['wps_voiced'] = round(summary['words'] / summary['voiced_s'], 2)
    return summary


if __name__ == '__main__':
    results = [analyse(p) for p in sys.argv[1:]]
    for r in results:
        print(f"\n== {r['session'][:8]} {r['engine']} {r['style']}  total {r['total_s']} s, {r['words']} words")
        print(f"   voiced speech {r['voiced_s']} s ({r['wps_voiced']} words/s while speaking) · pauses inside sections "
              f"{r['pauses_inside_sections_s']} s · between sections {r['between_sections_s']} s · opening {r['opening_s']} s · closing {r['closing_s']} s")
        for i, sec in enumerate(r['sections']):
            print(f"   {i + 1:2d} voiced {sec['voiced_s']:5.2f}s  inner pauses {sec['inner_pauses']}  edge quiet {sec['lead_quiet_s']:.2f}/{sec['tail_quiet_s']:.2f}s  {sec['wps_voiced']} w/s  …{sec['text'][-30:]}")
    out = ROOT / 'samples/pacing'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'timing.json').write_text(json.dumps(results, indent=1))
