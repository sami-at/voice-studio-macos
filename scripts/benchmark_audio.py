"""Measurement helpers for the ElevenLabs benchmark. numpy/scipy/soundfile and FFmpeg only.

Everything here is descriptive. A pitch range, a speech rate or a decay time does not show
that a voice sounds natural or human; it only locates where two recordings differ so the
difference can be listened to.
"""
import re
import subprocess
import sys
import tempfile
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from voice_studio.audio import ffmpeg  # noqa: E402
from voice_studio.verify import normalize  # noqa: E402

SENTENCES = [
    "Have you ever wondered why do flies rub their hands together like they're planning something?",
    "You might have noticed that whenever a fly lands, it starts rubbing its front legs together.",
    "It looks a little suspicious, but there's actually an interesting reason behind it.",
    "Flies spend a surprising amount of time cleaning themselves.",
    "And that's because they have tiny taste receptors on their feet, allowing them to taste whatever they land on.",
    "So when a fly walks across your food, it can actually taste it without even using its mouth.",
    "But dirt and dust can interfere with those receptors, which is why flies regularly rub their legs together to keep them clean.",
    "So no, flies aren't secretly planning anything.",
    "They're just keeping their taste receptors clean.",
]
KINDS = ['question', 'statement', 'statement', 'surprising statement', 'explanation',
         'explanation', 'explanation', 'conclusion', 'conclusion']


def load(path):
    audio, rate = sf.read(str(path), dtype='float32')
    return (audio.mean(axis=1) if audio.ndim > 1 else audio), rate


def decode(source, destination, rate=None):
    """Decode any audio file to float WAV (read-only on the source)."""
    args = ['-i', str(source), '-ac', '1'] + (['-ar', str(rate)] if rate else []) + \
           ['-c:a', 'pcm_f32le', str(destination)]
    subprocess.run([ffmpeg(), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', *args], check=True)


def db(value):
    return 20 * np.log10(np.maximum(value, 1e-12))


def rms_db(x):
    return float(10 * np.log10(np.mean(np.square(x.astype(np.float64))) + 1e-20))


def integrated_lufs(audio, rate):
    """ITU-R BS.1770 integrated loudness via FFmpeg's ebur128."""
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'x.wav'
        sf.write(path, audio, rate, subtype='FLOAT')
        out = subprocess.run([ffmpeg(), '-nostdin', '-hide_banner', '-i', str(path), '-af',
                              'ebur128=peak=true', '-f', 'null', '-'],
                             capture_output=True, text=True).stderr
    summary = out[out.rfind('Integrated loudness'):]
    match = re.search(r'I:\s*(-?[\d.]+)\s*LUFS', summary)
    return float(match.group(1)) if match else None


def matched(audio, rate, target=-24.0, ceiling_db=-1.0):
    """Linear gain to a common integrated loudness. Returns (audio, gain_db, limited)."""
    level = integrated_lufs(audio, rate)
    gain = target - level
    peak = float(np.max(np.abs(audio))) + 1e-12
    limited = db(peak) + gain > ceiling_db
    if limited:
        gain = ceiling_db - db(peak)
    return (audio * 10 ** (gain / 20)).astype(np.float32), float(gain), bool(limited)


# ---------------------------------------------------------------- pitch / voicing

def to_rate(x, rate, target=16000):
    g = gcd(int(rate), target)
    return signal.resample_poly(x, target // g, int(rate) // g).astype(np.float64), target


def yin_track(x, rate, fmin=65, fmax=400, hop_ms=10, win_ms=40, thr=0.25):
    """YIN pitch tracker. Returns frame times, F0 (nan = unvoiced), periodicity dB, level dB.

    The periodicity figure is a coarse, conservative proxy; compare it between files, never
    read it as an absolute harmonics-to-noise ratio.
    """
    x16, r16 = to_rate(x, rate)
    n = int(r16 * win_ms / 1000)
    hop = int(r16 * hop_ms / 1000)
    tmax, tmin = int(r16 / fmin), int(r16 / fmax)
    count = max(0, (len(x16) - n - tmax) // hop)
    f0 = np.full(count, np.nan)
    per = np.full(count, np.nan)
    level = np.zeros(count)
    for i in range(count):
        frame = x16[i * hop:i * hop + n + tmax]
        window = frame[:n]
        level[i] = 10 * np.log10(np.mean(window ** 2) + 1e-20)
        if level[i] < -60:
            continue
        energy = np.cumsum(np.r_[0, frame ** 2])
        ac = signal.fftconvolve(frame, window[::-1], mode='valid')[:tmax + 1]
        tau = np.arange(tmax + 1)
        d = (energy[n] - energy[0]) + (energy[tau + n] - energy[tau]) - 2 * ac
        cum = np.cumsum(d[1:])
        dn = np.r_[1, d[1:] * np.arange(1, tmax + 1) / np.maximum(cum, 1e-12)]
        cand = np.flatnonzero(dn[tmin:tmax] < thr)
        if not len(cand):
            continue
        t0 = tmin + cand[0]
        while t0 + 1 < tmax and dn[t0 + 1] < dn[t0]:
            t0 += 1
        if 0 < t0 < tmax:
            a, b, c = dn[t0 - 1], dn[t0], dn[t0 + 1]
            den = a - 2 * b + c
            t_ = t0 + (0.5 * (a - c) / den if abs(den) > 1e-12 else 0)
        else:
            t_ = t0
        f0[i] = r16 / t_
        p = min(max(1 - dn[t0], 1e-3), 1 - 1e-3)
        per[i] = 10 * np.log10(p / (1 - p))
    return np.arange(count) * hop / r16 + n / 2 / r16, f0, per, level


# ---------------------------------------------------------------- phrase alignment

def sentence_spans(words, sentences=SENTENCES):
    """Map each script sentence to (first, last) word indexes by sequence alignment."""
    from difflib import SequenceMatcher
    expected, owner = [], []
    for index, sentence in enumerate(sentences):
        tokens = normalize(sentence)
        expected += tokens
        owner += [index] * len(tokens)
    heard, home = [], []
    for index, word in enumerate(words):
        tokens = normalize(word['word'])
        heard += tokens
        home += [index] * len(tokens)
    mapping = {}
    for block in SequenceMatcher(None, expected, heard, autojunk=False).get_matching_blocks():
        for n in range(block.size):
            mapping[block.a + n] = block.b + n
    spans = []
    for index in range(len(sentences)):
        hit = [home[mapping[e]] for e in range(len(expected)) if owner[e] == index and e in mapping]
        spans.append((min(hit), max(hit)) if hit else None)
    return spans


def quiet_centre(x, rate, around, window=0.45, floor_db=-50.0):
    """Centre of the longest quiet run (>= 40 ms) within +/-window of a time; else the quietest block."""
    step = int(rate * 0.005)
    lo = max(0, int((around - window) * rate) // step)
    hi = min(len(x) // step - 1, int((around + window) * rate) // step)
    levels = np.array([rms_db(x[k * step:(k + 1) * step]) for k in range(lo, hi + 1)])
    quiet = levels < floor_db
    best, i = None, 0
    while i < len(quiet):
        if quiet[i]:
            j = i
            while j < len(quiet) and quiet[j]:
                j += 1
            if j - i >= 8 and (best is None or j - i > best[1] - best[0]):
                best = (i, j)
            i = j
        else:
            i += 1
    centre = (best[0] + best[1]) / 2 if best else int(np.argmin(levels)) + 0.5
    return (lo + centre) * step / rate


def cut_points(x, rate, words, sentences=SENTENCES):
    spans = sentence_spans(words, sentences)
    cuts = [0.0]
    for i in range(len(sentences) - 1):
        if spans[i] is None or spans[i + 1] is None:
            cuts.append(None)
            continue
        mid = (words[spans[i][1]]['end'] + words[spans[i + 1][0]]['start']) / 2
        cuts.append(quiet_centre(x, rate, mid))
    cuts.append(len(x) / rate)
    return cuts, spans


# ---------------------------------------------------------------- phrase measurements

def _levels(x, rate, ms=5):
    n = int(rate * ms / 1000)
    count = len(x) // n
    return np.array([rms_db(x[i * n:(i + 1) * n]) for i in range(count)]), n


def active_span(x, rate, floor_db=-45):
    levels, n = _levels(x, rate)
    live = np.flatnonzero(levels > floor_db)
    return ((live[0] * n / rate, (live[-1] + 1) * n / rate) if len(live) else (0.0, len(x) / rate))


def phrase_metrics(x, rate, cuts, sentences=SENTENCES):
    out, previous_end = [], None
    for i, sentence in enumerate(sentences):
        a, b = cuts[i], cuts[i + 1]
        if a is None or b is None:
            out.append({'i': i + 1, 'missing': True})
            continue
        clip = x[int(a * rate):int(b * rate)]
        s0, s1 = active_span(clip, rate)
        words = len(sentence.split())
        m = {'i': i + 1, 'kind': KINDS[i], 'words': words, 'speech_s': round(s1 - s0, 2),
             'wps': round(words / (s1 - s0), 2),
             'gap_before': None if previous_end is None else round(a + s0 - previous_end, 2)}
        previous_end = a + s1
        t, f0, per, level = yin_track(clip[int(s0 * rate):int(s1 * rate)], rate)
        voiced = ~np.isnan(f0)
        if voiced.sum() > 8:
            st = 12 * np.log2(f0[voiced] / np.median(f0[voiced]))
            m.update(f0_mean=round(float(np.mean(f0[voiced])), 1),
                     f0_range_st=round(float(np.percentile(st, 95) - np.percentile(st, 5)), 1))
        active = level[level > -45]
        if len(active) > 10:
            m['dyn_db'] = round(float(np.percentile(active, 90) - np.percentile(active, 10)), 1)
        levels, n = _levels(clip, rate)
        live = np.flatnonzero(levels > -62)
        if len(live) > 30:
            j = live[-1]
            ref = 10 * np.log10(np.mean(10 ** (levels[max(0, j - 40):max(1, j - 10)] / 10)))
            m['end_decay_db'] = round(float(levels[j] - ref), 1)
        out.append(m)
    return out


OCTAVES = [250, 400, 630, 1000, 1600, 2500, 4000, 6300, 9000]


def octave_levels(x, rate):
    """Octave-band level of the louder 40% of frames, relative to the 1 kHz octave (dB)."""
    f, _, spec = signal.stft(x, rate, nperseg=2048, noverlap=1536, window='hann')
    power = np.abs(spec) ** 2
    energy = power.sum(0)
    mean = power[:, energy > np.percentile(energy, 60)].mean(1)
    levels = np.array([10 * np.log10(mean[(f >= c / 2 ** .5) & (f < c * 2 ** .5)].sum() + 1e-20)
                       for c in OCTAVES])
    return [round(float(v), 1) for v in levels - levels[OCTAVES.index(1000)]]


def summarize(phrases):
    """Source-level averages of the per-phrase measurements."""
    rows = [p for p in phrases if 'file' in p]
    pick = lambda key: [p[key] for p in rows if p.get(key) is not None]
    gaps = pick('gap_before')
    ends = pick('end_decay_db')
    return {'wps': round(float(np.mean(pick('wps'))), 2),
            'f0_range_st': round(float(np.mean(pick('f0_range_st'))), 1),
            'f0_mean_hz': round(float(np.mean(pick('f0_mean'))), 0),
            'gap_mean_s': round(float(np.mean(gaps)), 2), 'gap_sd_s': round(float(np.std(gaps)), 2),
            'abrupt_endings': int(sum(1 for e in ends if e > -15)), 'phrases': len(rows)}
