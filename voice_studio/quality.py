"""Measurable review flags for a take, and for the join between two sections.

These are observations, not verdicts. There is deliberately no single quality score: a number
would invite being read as "this sounds natural", which none of these measurements can show.
Every flag says what was measured so the user can listen and decide. Nothing here edits,
rejects or deletes audio.
"""
from math import gcd

import numpy as np
from scipy import signal

from .audio import CUT_STOP_REL_DB, RATE, SHORT_STOP_REL_DB, edge_decay, ending_stop

# Thresholds come from measurements on 133 raw takes and the ElevenLabs reference
# (docs/ELEVENLABS-QUALITY-BENCHMARK.md). They are deliberately loose: a flag should be worth a listen.
PACE_WORDS_PER_SECOND = (1.8, 5.2)       # references and takes measured 2.2-4.3
LOUDNESS_SPREAD_DB = 28.0                # p90-p10 of 25 ms levels; measured 15-21
LONG_INTERNAL_GAP_S = 0.60               # a comma is 0.2-0.45 s
CLIP_LEVEL = 0.999
LOUDNESS_JUMP_DB = 4.0
PITCH_JUMP_SEMITONES = 4.0
BRIGHTNESS_RATIO = 1.35
GAP_RANGE_S = (0.05, 1.8)


def flag(code, message, severity='warn', **measured):
    return {'code': code, 'severity': severity, 'message': message, **measured}


def _levels(audio, rate, ms):
    step = max(1, int(rate * ms / 1000))
    count = len(audio) // step
    if not count:
        return np.empty(0), step
    block = audio[:count * step].astype(np.float64).reshape(count, step)
    return 10 * np.log10(np.mean(block ** 2, axis=1) + 1e-20), step


def pitch_track(audio, rate=RATE, fmin=65, fmax=400, hop_ms=10, win_ms=40, threshold=0.25):
    """YIN F0 per 10 ms frame (nan = unvoiced). Coarse by design; used for jumps and medians."""
    g = gcd(int(rate), 16000)
    x = signal.resample_poly(audio.astype(np.float64), 16000 // g, int(rate) // g)
    n, hop = int(16 * win_ms), int(16 * hop_ms)
    tmax, tmin = int(16000 / fmin), int(16000 / fmax)
    count = max(0, (len(x) - n - tmax) // hop)
    f0 = np.full(count, np.nan)
    for i in range(count):
        frame = x[i * hop:i * hop + n + tmax]
        window = frame[:n]
        if 10 * np.log10(np.mean(window ** 2) + 1e-20) < -55:
            continue
        energy = np.cumsum(np.r_[0, frame ** 2])
        ac = signal.fftconvolve(frame, window[::-1], mode='valid')[:tmax + 1]
        tau = np.arange(tmax + 1)
        d = (energy[n] - energy[0]) + (energy[tau + n] - energy[tau]) - 2 * ac
        norm = np.r_[1, d[1:] * np.arange(1, tmax + 1) / np.maximum(np.cumsum(d[1:]), 1e-12)]
        under = np.flatnonzero(norm[tmin:tmax] < threshold)
        if not len(under):
            continue
        t0 = tmin + under[0]
        while t0 + 1 < tmax and norm[t0 + 1] < norm[t0]:
            t0 += 1
        f0[i] = 16000 / t0
    return f0


def section_profile(audio, rate=RATE, words=None):
    """What a section sounds like in four numbers, for comparing neighbours."""
    levels, _ = _levels(audio, rate, 25)
    live = levels > -45
    f0 = pitch_track(audio, rate)
    voiced = f0[~np.isnan(f0)]
    freqs, _, spec = signal.stft(audio, rate, nperseg=1024, noverlap=768)
    power = np.abs(spec) ** 2
    frames = power.sum(0) > np.percentile(power.sum(0), 60)
    band = (freqs >= 100) & (freqs <= 8000)
    centroid = float((power[band][:, frames] * freqs[band][:, None]).sum()
                     / max(power[band][:, frames].sum(), 1e-20)) if frames.any() else None
    profile = {'level_db': float(10 * np.log10(np.mean(10 ** (levels[live] / 10)))) if live.any() else None,
               'f0_median_hz': float(np.median(voiced)) if len(voiced) > 8 else None,
               'centroid_hz': centroid,
               'speech_s': float(live.sum() * .025)}
    if words:
        profile['words_per_second'] = round(words / max(profile['speech_s'], 1e-6), 2)
    return profile


def analyze_take(audio, rate=RATE, words=0, heard=None, spoken=None):
    """Flags for one raw take. ``heard`` is the offline transcript, used only for repeated words."""
    audio = np.asarray(audio, dtype=np.float32)
    out = []
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    clipped = int(np.sum(np.abs(audio) >= CLIP_LEVEL))
    if clipped:
        out.append(flag('clipping', f'{clipped} samples reach full scale. The model output itself is clipped.',
                        samples=clipped, peak=peak))
    tail, head = edge_decay(audio, rate)
    if tail is not None and tail > -15.0:
        out.append(flag('abrupt_end', 'The sound is still near full level at its last audible moment, '
                        'so the ending was probably cut off. A fade would hide this, not fix it; '
                        'record the section again.', tail_decay_db=round(tail, 1)))
    stop, fall = ending_stop(audio, rate)
    if stop > CUT_STOP_REL_DB:
        out.append(flag('cut_ending', f'The last word stops dead while still loud ({stop:.0f} dB below speech, then '
                        f'{min(fall, 99):.0f} dB to silence in 10 ms), so its final sound is probably incomplete. A word '
                        'check cannot hear this. Record the section again.', stop_rel_db=round(stop, 1),
                        cliff_db=round(stop + 99, 1)))
    elif stop > SHORT_STOP_REL_DB:
        out.append(flag('short_ending', f'The last sound ends without its usual fade ({stop:.0f} dB below speech, then '
                        'silence). Listen to the last word.', severity='note', stop_rel_db=round(stop, 1)))
    if head is not None and head > -6.0:
        out.append(flag('abrupt_start', 'The sound starts at near full level, so the first sound may be '
                        'missing. Record the section again.', head_rise_db=round(head, 1)))
    levels, step = _levels(audio, rate, 10)
    live = np.flatnonzero(levels > -50)
    if len(live) > 20:
        inner = levels[live[0]:live[-1] + 1] < -60
        longest = run = 0
        for quiet in inner:
            run = run + 1 if quiet else 0
            longest = max(longest, run)
        seconds = longest * step / rate
        if seconds > LONG_INTERNAL_GAP_S:
            out.append(flag('long_internal_gap', f'{seconds:.2f} s of near-silence inside the speech.',
                            seconds=round(seconds, 2)))
        speech_s = len(live) * step / rate
        if words:
            pace = words / max(speech_s, 1e-6)
            low, high = PACE_WORDS_PER_SECOND
            if not low <= pace <= high:
                out.append(flag('unusual_pace', f'{pace:.1f} words per second of speech '
                                f'(references measured 2.2 to 4.3).', words_per_second=round(pace, 2)))
        short, _ = _levels(audio, rate, 25)
        active = short[short > -45]
        if len(active) > 10:
            spread = float(np.percentile(active, 90) - np.percentile(active, 10))
            if spread > LOUDNESS_SPREAD_DB:
                out.append(flag('loudness_spread', f'Loudness varies by {spread:.0f} dB inside the take '
                                f'(references measured 15 to 21).', spread_db=round(spread, 1)))
    if heard and spoken:
        from .verify import normalize
        want, got = normalize(spoken), normalize(heard)
        repeats = [got[i] for i in range(1, len(got)) if got[i] == got[i - 1]
                   and not any(want[j] == want[j - 1] == got[i] for j in range(1, len(want)))]
        if repeats:
            out.append(flag('repeated_word', 'The recording seems to repeat: ' + ', '.join(sorted(set(repeats))),
                            words=sorted(set(repeats))))
    f0 = pitch_track(audio, rate)
    run = f0[~np.isnan(f0)]
    pairs = [(a, b) for a, b in zip(f0[:-1], f0[1:]) if not (np.isnan(a) or np.isnan(b))]
    if len(pairs) > 40:
        jumps = np.mean([abs(12 * np.log2(b / a)) > 5 for a, b in pairs])
        if jumps > 0.06:
            out.append(flag('pitch_jumps', f'{jumps:.0%} of voiced frames jump more than 5 semitones. '
                            'The tracker is coarse, so listen before acting on this.',
                            severity='note', fraction=round(float(jumps), 3)))
    return out


def review_boundary(before, after, gap_seconds, rate=RATE):
    """Compare the end of one section with the start of the next. Inputs are section profiles
    of the *tail* and *head* audio (about two seconds each), so a long section is not averaged away."""
    out = []
    if before.get('level_db') is not None and after.get('level_db') is not None:
        jump = after['level_db'] - before['level_db']
        if abs(jump) > LOUDNESS_JUMP_DB:
            out.append(flag('loudness_jump', f'Loudness changes by {jump:+.1f} dB across this join.',
                            jump_db=round(jump, 1)))
    if before.get('f0_median_hz') and after.get('f0_median_hz'):
        jump = 12 * np.log2(after['f0_median_hz'] / before['f0_median_hz'])
        if abs(jump) > PITCH_JUMP_SEMITONES:
            out.append(flag('pitch_jump', f'Typical pitch changes by {jump:+.1f} semitones across this join.',
                            severity='note', jump_semitones=round(float(jump), 1)))
    if before.get('centroid_hz') and after.get('centroid_hz'):
        ratio = after['centroid_hz'] / before['centroid_hz']
        if ratio > BRIGHTNESS_RATIO or ratio < 1 / BRIGHTNESS_RATIO:
            out.append(flag('timbre_change', f'Brightness differs by {ratio:.2f}x; the takes may sound like '
                            'different recording sessions.', ratio=round(float(ratio), 2)))
    low, high = GAP_RANGE_S
    if not low <= gap_seconds <= high:
        out.append(flag('gap', f'The designed gap is {gap_seconds:.2f} s.', severity='note',
                        seconds=round(gap_seconds, 2)))
    return out


def edge_profile(audio, rate=RATE, seconds=2.0, tail=False):
    """Profile of the first or last couple of seconds of audible speech."""
    levels, step = _levels(audio, rate, 10)
    live = np.flatnonzero(levels > -50)
    if len(live) < 20:
        return {}
    a, b = live[0] * step, (live[-1] + 1) * step
    window = int(seconds * rate)
    chunk = audio[max(a, b - window):b] if tail else audio[a:a + window]
    return section_profile(chunk, rate)


# ---------------------------------------------------------------- exports and whole narrations

def validate_export(path, source=None, target_lufs=-18.0):
    """Decode an exported WAV/MP3 and check what a listener or a platform would measure.

    Returns {'ok', 'measured', 'warnings'}. ``source`` is the assembled narration the export was
    made from; the lengths must agree. MP3 adds a few frames of encoder padding, so 50 ms is allowed.
    """
    import re
    import subprocess
    import tempfile
    from pathlib import Path
    import soundfile as sf
    from .audio import ffmpeg
    path = Path(path)
    warnings, measured = [], {}
    if not path.is_file() or path.stat().st_size < 1000:
        return {'ok': False, 'measured': {}, 'warnings': [flag('missing', 'The exported file is missing or empty.')]}
    with tempfile.TemporaryDirectory() as temp:
        decoded = Path(temp) / 'decoded.wav'
        run = subprocess.run([ffmpeg(), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(path),
                              '-ac', '1', '-c:a', 'pcm_f32le', str(decoded)], capture_output=True, text=True)
        if run.returncode:
            return {'ok': False, 'measured': {}, 'warnings': [flag('undecodable', 'The export cannot be decoded: ' + run.stderr[-200:])]}
        audio, rate = sf.read(decoded, dtype='float32')
        loud = subprocess.run([ffmpeg(), '-nostdin', '-hide_banner', '-i', str(decoded), '-af', 'ebur128=peak=true',
                               '-f', 'null', '-'], capture_output=True, text=True).stderr
    tail = loud[loud.rfind('Integrated loudness'):]
    lufs = re.search(r'I:\s*(-?[\d.]+)\s*LUFS', tail)
    true_peak = re.search(r'Peak:\s*(-?[\d.]+)\s*dBFS', tail)
    measured = {'seconds': round(len(audio) / rate, 3), 'sample_rate': rate,
                'lufs': float(lufs.group(1)) if lufs else None,
                'true_peak_db': float(true_peak.group(1)) if true_peak else None,
                'clipped_samples': int(np.sum(np.abs(audio) >= CLIP_LEVEL))}
    if not np.isfinite(audio).all():
        warnings.append(flag('invalid_samples', 'The export contains invalid samples.'))
    if measured['clipped_samples']:
        warnings.append(flag('clipping', f"{measured['clipped_samples']} samples reach full scale."))
    if measured['true_peak_db'] is not None and measured['true_peak_db'] > -1.0:
        warnings.append(flag('true_peak', f"True peak {measured['true_peak_db']:.1f} dBFS is above -1 dBFS; "
                             'lossy platforms may clip.', severity='note'))
    if measured['lufs'] is not None and abs(measured['lufs'] - target_lufs) > 2.0:
        warnings.append(flag('loudness', f"Integrated loudness is {measured['lufs']:.1f} LUFS; the target is "
                             f'{target_lufs:.0f}.', severity='note'))
    if source is not None:
        expected = sf.info(source).duration
        if abs(expected - measured['seconds']) > 0.05:
            warnings.append(flag('length', f"The export is {measured['seconds']:.2f} s but the narration is "
                                 f'{expected:.2f} s.', expected=round(expected, 3)))
    return {'ok': not any(w['severity'] == 'warn' for w in warnings), 'measured': measured, 'warnings': warnings}


def review_session(session, data):
    """Per-section flags and per-join comparison for a finished narration. Read-only.

    The designed gap is the style or explicit pause, not a measurement of the assembled file.
    """
    from pathlib import Path
    import soundfile as sf
    from . import styles
    from .text import break_after
    values = {'pause': session.get('pause', .30), 'sentence_pause': session.get('sentence_pause', .10)}
    sections, joins = [], []
    heads, tails = [], []
    for i, segment in enumerate(session['segments']):
        path = Path(data) / (segment.get('file') or '')
        entry = {'index': i + 1, 'flags': list((segment.get('quality') or [])), 'file': segment.get('file')}
        if segment.get('file') and path.is_file():
            audio, rate = sf.read(path, dtype='float32')
            heads.append(edge_profile(audio, rate))
            tails.append(edge_profile(audio, rate, tail=True))
            entry['profile'] = section_profile(audio, rate)
        else:
            heads.append({}), tails.append({})
            entry['flags'].append(flag('no_audio', 'This section has no recording yet.'))
        sections.append(entry)
    for i in range(len(session['segments']) - 1):
        nxt = session['segments'][i + 1]
        asked = nxt.get('lead_pause')
        gap = float(asked) if asked is not None else styles.gap_after(break_after(session['segments'][i]), values)
        joins.append({'after': i + 1, 'designed_gap_s': round(gap, 2),
                      'flags': review_boundary(tails[i], heads[i + 1], gap)})
    return {'sections': sections, 'joins': joins}
