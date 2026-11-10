"""Bounded-memory audio preparation, mastering, and atomic export."""
import os
import subprocess
import tempfile
from pathlib import Path
import numpy as np
import soundfile as sf

RATE = 24000

def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

def convert(arguments):
    result = subprocess.run([ffmpeg(), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', *map(str, arguments)],
                            capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise RuntimeError('Audio conversion failed: ' + result.stderr[-1800:])

def edge_trim(audio, rate=RATE, padding=0.10):
    """Trim near-digital silence in a newly prepared reference, not quiet speech."""
    if not len(audio):
        raise ValueError('The recording contains no audio.')
    frame = max(1, int(rate * .01))
    padded = np.pad(audio, (0, (-len(audio)) % frame))
    energy = np.sqrt(np.mean(padded.reshape(-1, frame) ** 2, axis=1))
    threshold = 0.00001
    active = np.flatnonzero(energy > threshold)
    if not len(active):
        raise ValueError('This recording is silent or too quiet. Choose a clear speech sample.')
    first = max(0, int(active[0] * frame - rate * padding))
    last = min(len(audio), int((active[-1] + 1) * frame + rate * padding))
    return audio[first:last].copy()

def prepare_reference(source, destination, start=0.0, duration=12.0):
    if start < 0 or not 3 <= duration <= 30:
        raise ValueError('Choose a start at or after zero and a 3–30 second reference window.')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        wav = Path(temp) / 'decoded.wav'
        convert(['-ss', start, '-i', source, '-t', duration, '-vn', '-ac', 1, '-ar', RATE, '-c:a', 'pcm_s16le', wav])
        audio, rate = sf.read(wav, dtype='float32')
        clipped = float(np.mean(np.abs(audio) >= .999)) if len(audio) else 0
        audio = edge_trim(audio, rate)
        if len(audio) / rate < 2.0:
            raise ValueError('The selected window contains under two seconds of speech. Choose a longer sample.')
        peak = float(np.max(np.abs(audio)))
        rms = float(np.sqrt(np.mean(audio ** 2)))
        gain = min(0.10 / max(rms, 1e-6), 0.89 / max(peak, 1e-6), 8)
        audio *= gain
        sf.write(wav, audio, rate, subtype='PCM_16')
        os.replace(wav, destination)
    return {'seconds': len(audio) / rate, 'sample_rate': rate, 'source_clipped_fraction': clipped,
            'warning': 'The source may be clipped; a cleaner recording will improve similarity.' if clipped > .005 else ''}

def conditioned_reference(reference, tempo, folder):
    """Reference cloning copies the sample's delivery, so pacing is set by stretching it.

    Returns the reference unchanged at 1.0x. Otherwise writes a tempo-shifted copy
    beside the sample and reuses it next time; the words are untouched, so the saved
    transcript stays correct.
    """
    reference = Path(reference)
    if abs(tempo - 1.0) <= .001:
        return reference
    destination = Path(folder) / f'reference-t{int(round(tempo * 100)):03d}.wav'
    if destination.is_file():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        shifted = Path(temp) / 'shifted.wav'
        convert(['-i', reference, '-af', f'atempo={tempo}', '-ac', 1, '-ar', RATE,
                 '-c:a', 'pcm_s16le', shifted])
        if sf.info(shifted).duration < 1.5:
            raise ValueError('The reference becomes too short at this pace. '
                             'Choose a longer sample window or a slower style.')
        os.replace(shifted, destination)
    return destination

# Measured on 133 raw takes and on ElevenLabs' own phrase endings: its worst ending had
# fallen 16.5 dB by its last audible moment, its median 26 dB. A take that is still within
# 15 dB of its speech level there stopped; it did not finish. See docs/ELEVENLABS-QUALITY-BENCHMARK.md.
ABRUPT_TAIL_DB = -15.0
ABRUPT_HEAD_DB = -6.0


def edge_decay(audio, rate=RATE, floor_db=-60.0, block=0.005):
    """How far the sound has fallen at its last audible moment, and how steeply it began.

    The final *sample* of a take is a poor witness: the decoders pad with near-silence, so a
    voiced burst that stops dead still ends in ~-80 dB. This looks at the last block above
    ``floor_db`` instead and compares it with the speech 50-200 ms before (tail), or after
    (head). Returns (tail_db, head_db), each None when too little signal is audible.
    """
    step = max(1, int(rate * block))
    count = len(audio) // step
    if not count:
        return None, None
    levels = 10 * np.log10(np.mean(np.square(audio[:count * step].astype(np.float64))
                                   .reshape(count, step), axis=1) + 1e-20)
    live = np.flatnonzero(levels > floor_db)
    if len(live) < 30:
        return None, None
    power = lambda a, b: float(10 * np.log10(np.mean(10 ** (levels[a:b] / 10))))
    last, first = int(live[-1]), int(live[0])
    tail = float(levels[last]) - power(max(0, last - 40), max(1, last - 10))
    head = float(levels[first]) - power(first + 10, first + 40)
    return tail, head


# Measured 25 Oct on 150 fresh Qwen3 takes and the ElevenLabs reference: ElevenLabs' phrase endings never fall
# more than 11 dB in one 5 ms step, while about half of Qwen3's takes fall 30+ dB straight to digital silence
# from an audible level, in the middle of a codec frame: the last sound ("s", "th", "ch", a vowel) is cut short.
# This is the model's output (streaming and full decoding give identical samples), so it cannot be repaired by
# processing; it can only be detected and re-recorded.
CUT_FALL_DB = 30.0       # the fall to near-silence (< -80 dBFS) within 10 ms
CUT_STOP_REL_DB = -27.0  # ... from a level within 27 dB of the take's speech: the sound was still loud -> cut
SHORT_STOP_REL_DB = -35.0  # ... within 27-35 dB: a shortened decay, worth a listen but not a retry


def ending_stop(audio, rate=RATE, block=0.005):
    """How a take's sound ends. Returns (stop_rel_db, fall_db).

    stop_rel_db: the level at which the sound stops dead, relative to the take's speech level (-99 if it fades
    out naturally). fall_db: how far it then drops within 10 ms. ElevenLabs' phrase endings never drop more
    than 13 dB in 10 ms; Qwen3's often drop 30-60 dB straight to digital silence. Sound that runs to the last
    sample counts as stopping where it is.
    """
    step = max(1, int(rate * block))
    count = len(audio) // step
    if count < 3:
        return -99.0, 0.0
    levels = 10 * np.log10(np.mean(np.square(audio[:count * step].astype(np.float64)).reshape(count, step), axis=1) + 1e-20)
    speech = levels[levels > -45]
    live = np.flatnonzero(levels > -60)
    if len(live) < 20 or not len(speech):
        return -99.0, 0.0
    reference = 10 * np.log10(np.mean(10 ** (speech / 10)))
    last = int(live[-1])
    if last + 1 >= count:
        return float(levels[last] - reference), 99.0
    best = (-99.0, 0.0)
    for i in range(max(0, last - 60), min(count - 1, last + 2)):
        after = float(np.min(levels[i + 1:i + 3]))
        fall = float(levels[i]) - after
        if levels[i] > -60 and after < -80 and fall >= CUT_FALL_DB and levels[i] - reference > best[0]:
            best = (float(levels[i] - reference), fall)
    return best


def boundary_check(audio, rate=RATE):
    """Flag nonquiet raw endpoints and abrupt starts/stops, not phonetic completeness.

    ``tail_abrupt``/``head_abrupt`` mean the engine's sound was still near full level at its
    last/first audible moment. They are diagnostics: they do not prove a phoneme is missing,
    and nothing is trimmed, faded or repaired because of them.
    """
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all():
        raise ValueError('The model produced empty, non-mono, or invalid audio.')
    tail, head = edge_decay(audio, rate)
    stop, fall = ending_stop(audio, rate)
    return {'head_at_boundary': bool(abs(float(audio[0])) > .003),
            'tail_at_boundary': bool(abs(float(audio[-1])) > .003),
            'peak': float(np.max(np.abs(audio))),
            'dc_mean': float(np.mean(audio)),
            'tail_decay_db': tail, 'head_rise_db': head,
            'tail_abrupt': bool(tail is not None and tail > ABRUPT_TAIL_DB),
            'tail_stop_rel_db': round(stop, 1), 'tail_fall_db': round(fall, 1),
            'tail_cut': bool(stop > CUT_STOP_REL_DB),
            'head_abrupt': bool(head is not None and head > ABRUPT_HEAD_DB)}


def polish_segment(audio):
    """Preserve the entire generated signal; gain and guard silence only.

    A quiet consonant is not silence. No energy-based trim or fade is allowed to
    remove it. Guards also give FFmpeg's tempo filter room to drain its final window.
    They cannot repair speech omitted by the model.
    """
    audio = np.asarray(audio, dtype=np.float32)
    boundary_check(audio)
    audio = audio.copy()
    peak = max(float(np.max(np.abs(audio))), 1e-6)
    if peak < 1e-5:
        raise ValueError('The model produced silent audio. Regenerate this section.')
    # Measure level over active samples so engine-specific padding does not change gain.
    active = audio[np.abs(audio) > peak * .01]
    rms = max(float(np.sqrt(np.mean(active ** 2))), 1e-6)
    audio *= min(.12 / rms, .89 / peak, 3.0)
    return np.pad(audio, (int(RATE * .08), int(RATE * .16)))


def write_segment(audio, destination, speed=1.0):
    if not .75 <= speed <= 1.25:
        raise ValueError('Speaking speed must be between 0.75× and 1.25×.')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        raw = Path(temp) / 'raw.wav'
        sf.write(raw, polish_segment(audio), RATE, subtype='PCM_24')
        if abs(speed - 1.0) > .001:
            adjusted = Path(temp) / 'adjusted.wav'
            convert(['-i', raw, '-af', f'atempo={speed}', '-c:a', 'pcm_s24le', adjusted])
            raw = adjusted
        os.replace(raw, destination)
    return sf.info(destination).duration

# A trim floor near PCM quantization noise, not a speech-onset threshold.
# Preserve even very quiet attacks and releases. These are NOT phoneme bounds.
SILENCE = 0.00001
KEEP_HEAD = 0.01
KEEP_TAIL = {'paragraph': 0.01, 'sentence': 0.01, 'clause': 0.01, 'mid': 0.01}


def speech_bounds(path, threshold=SILENCE, limit=None):
    """Bounds of non-negligible samples, scanned in bounded memory.

    Used only to remove near-digital silence. Noise/breaths remain, deliberately.
    The optional limit is retained for older callers; it cannot justify a speech cut.
    """
    with sf.SoundFile(path) as source:
        if source.channels != 1:
            raise ValueError('A section must be mono.')
        total = len(source)
        start, end, position = None, 0, 0
        for block in source.blocks(blocksize=65536, dtype='float32'):
            active = np.flatnonzero(np.abs(block) > threshold)
            if len(active):
                if start is None:
                    start = position + int(active[0])
                end = position + int(active[-1]) + 1
            position += len(block)
    return (start, end) if start is not None else (0, total)


DECAY_FLOOR = 10 ** (-60 / 20)     # below -60 dBFS (10 ms RMS) a take's audible decay is over


def decay_end(path, rate=RATE):
    """Sample index where a section's audible sound, including its decay, ends."""
    audio, _ = sf.read(path, dtype='float32')
    n = int(rate * .01)
    count = len(audio) // n
    if not count:
        return len(audio)
    rms = np.sqrt(np.mean(np.square(audio[:count * n].astype(np.float64)).reshape(count, n), axis=1))
    loud = np.flatnonzero(rms > DECAY_FLOOR)
    return int((loud[-1] + 1) * n) if len(loud) else len(audio)


def split_at_pauses(path, spoken, pauses, keep_head, keep_tail, rate=RATE, word_timing=None):
    """Insert silence only at an aligned word boundary with a quiet interval.

    Never guess word locations from character fractions. Never remove existing
    speech or natural silence. A requested pause is the inserted PCM duration.
    Missing/ambiguous alignment is an actionable error, not a cut through a word.
    """
    from .verify import normalize
    from difflib import SequenceMatcher
    if not pauses or not spoken.strip():
        return []
    expected = normalize(spoken)
    heard, times = [], []
    for word in word_timing or []:
        tokens = normalize(word.get('word', ''))
        heard.extend(tokens)
        times.extend([(float(word['start']), float(word['end']))] * len(tokens))
    mapping = {}
    for block in SequenceMatcher(None, expected, heard, autojunk=False).get_matching_blocks():
        for n in range(block.size):
            mapping[block.a + n] = block.b + n
    with sf.SoundFile(path) as source:
        total = len(source)
        cuts = []
        for offset, seconds in pauses:
            left = len(normalize(spoken[:offset])) - 1
            if left < 0:
                cuts.append((0, seconds, 0.0))
                continue
            if left >= len(expected) - 1:
                cuts.append((total, seconds, 0.0))
                continue
            l, r = mapping.get(left), mapping.get(left + 1)
            if l is None or r is None or r != l + 1:
                raise ValueError('Cannot locate an inline pause reliably. Regenerate this '
                                 'section or put the pause between paragraphs.')
            end, start = times[l][1], times[r][0]
            if start < end - .02 or start - end > 1.5:
                raise ValueError('Inline pause word alignment is uncertain. Use a pause '
                                 'between paragraphs or regenerate this section.')
            low = max(0, round((end - .04) * rate))
            high = min(total, round((start + .04) * rate))
            source.seek(low)
            audio = source.read(max(0, high - low), dtype='float32')
            # Require a quiet 12 ms run; an isolated zero crossing is not a pause.
            quiet = np.abs(audio) < .0003
            edges = np.diff(np.r_[False, quiet, False].astype(int))
            runs = [(a, b) for a, b in zip(np.flatnonzero(edges == 1),
                                          np.flatnonzero(edges == -1))
                    if b - a >= round(.012 * rate)]
            if not runs:
                raise ValueError('No safe quiet interval at the inline pause. Put it '
                                 'between paragraphs or regenerate this section.')
            a, b = max(runs, key=lambda run: run[1] - run[0])
            middle = (a + b) // 2
            cuts.append((low + middle, seconds, 0.0))
    return sorted(cuts)


RAMP_SECONDS = 0.003
RAMP_FLOOR = 10 ** (-50 / 20)       # an edge quieter than -50 dBFS cannot click


def edge_ramp(block, head):
    """Protect a join, not a phoneme: ramp only the outer 3 ms, and only if that edge is audible.

    An edge is where a section's own sound meets the digital silence assembly places around it.
    A ramp stops a step into silence from clicking; it cannot restore a sound the engine never
    finished, so cut-off endings are flagged and re-recorded instead (see quality.py).
    Returns (block, ramped). The stored take is never modified.
    """
    count = min(len(block), int(RATE * RAMP_SECONDS))
    if count < 8:
        return block, False
    edge = block[:count] if head else block[-count:]
    if np.max(np.abs(edge)) <= RAMP_FLOOR:
        return block, False
    shape = np.sin(np.linspace(0, np.pi / 2, count)) ** 2
    block = block.copy()
    if head:
        block[:count] *= shape
    else:
        block[-count:] *= shape[::-1]
    return block, True


def join_segments(session, data, destination):
    """Stream PCM blocks to disk so book-length scripts don't accumulate in RAM."""
    from . import direction, styles
    from .text import break_after
    from .storage import segment_is_stale
    from .verify import normalize
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    values = {'pause': session.get('pause', .30),
              'sentence_pause': session.get('sentence_pause', .10)}
    segments = session['segments']
    edges_ramped = 0
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        combined = Path(temp) / 'combined.wav'
        with sf.SoundFile(combined, 'w', samplerate=RATE, channels=1, subtype='PCM_24') as output:
            lead = styles.LEAD_IN + max(0.0, segments[0].get('lead_pause', 0) or 0) \
                if segments else styles.LEAD_IN
            output.write(np.zeros(int(RATE * lead), dtype=np.float32))
            for i, segment in enumerate(segments):
                if segment_is_stale(segment):
                    raise ValueError(f'Section {i + 1} has stale audio. Generate the edited words first.')
                if not segment.get('file'):
                    raise ValueError('Generate every section before assembling the narration.')
                path = Path(data) / segment['file']
                kind = break_after(segment)
                keep_tail = KEEP_TAIL.get(kind, 0.06)
                with sf.SoundFile(path) as source:
                    if source.samplerate != RATE or source.channels != 1:
                        raise ValueError('A section has an incompatible audio format.')
                    total = len(source)
                    start, end = speech_bounds(path)
                    # Keep the natural decay after the last sound; drop the dead padding.
                    begin = max(0, start - int(RATE * KEEP_HEAD))
                    finish = min(total, end + int(RATE * keep_tail))
                    guard = segment.get('dead_air_guard_s')
                    if guard is not None:
                        # Only for takes made under an engine tuning that asks for it (Chatterbox Energetic):
                        # keep the audible decay plus the guard, drop the near-silence the model adds after it.
                        finish = min(finish, max(begin, decay_end(path) + int(RATE * guard)))
                    plan = direction.parse(segment.get('text', ''))
                    if plan.problems:
                        raise ValueError(' '.join(plan.problems))
                    cuts = split_at_pauses(path, plan.spoken, plan.pauses,
                                           int(RATE * KEEP_HEAD), int(RATE * keep_tail),
                                           word_timing=segment.get('word_timing'))
                    # Leading/trailing inline markers are kept at the section edges.
                    marks = [(max(begin, min(c, finish)), seconds, already)
                             for c, seconds, already in cuts]
                    source.seek(begin)
                    position = begin
                    head_done = False
                    for cut, seconds, already in marks:
                        remaining = cut - position
                        while remaining > 0:
                            block = source.read(min(65536, remaining), dtype='float32')
                            if not len(block):
                                break
                            if not head_done:
                                block, ramped = edge_ramp(block, True)
                                head_done = True
                                edges_ramped += ramped
                            output.write(block)
                            remaining -= len(block)
                        position = cut
                        # Exact inserted silence; existing quiet audio is untouched.
                        extra = max(0.0, seconds - already)
                        if extra > 0:
                            output.write(np.zeros(round(RATE * extra), dtype=np.float32))
                    remaining = finish - position
                    while remaining > 0:
                        block = source.read(min(65536, remaining), dtype='float32')
                        if not len(block):
                            break
                        if not head_done:
                            block, ramped = edge_ramp(block, True)
                            head_done = True
                            edges_ramped += ramped
                        if remaining <= len(block):
                            block, ramped = edge_ramp(block, False)
                            edges_ramped += ramped
                        output.write(block)
                        remaining -= len(block)
                if i < len(segments) - 1:
                    asked = segments[i + 1].get('lead_pause')
                    # Explicit means exactly N inserted silent samples in addition to
                    # retained natural quiet. It replaces, rather than adds to, style.
                    next_plan = direction.parse(segments[i + 1].get('text', ''))
                    inline_boundary = any(not normalize(plan.spoken[o:]) for o, _ in plan.pauses) or any(
                        not normalize(next_plan.spoken[:o]) for o, _ in next_plan.pauses)
                    gap = float(asked) if asked is not None else styles.gap_after(kind, values)
                    next_file = segments[i + 1].get('file')
                    if not next_file:
                        raise ValueError('Generate every section before assembling the narration.')
                    next_start, _ = speech_bounds(Path(data) / next_file)
                    # Estimate quiet room ONLY to avoid adding unnecessary style silence.
                    # This higher threshold never determines which samples survive.
                    _, room_end = speech_bounds(path, threshold=.001)
                    if guard is not None:
                        # Count only quiet that survives the trim; faint dead air beyond it isn't kept.
                        kept = np.flatnonzero(np.abs(sf.read(path, frames=finish, dtype='float32')[0]) > .001)
                        room_end = int(kept[-1]) + 1 if len(kept) else 0
                    room_start, _ = speech_bounds(Path(data) / next_file, threshold=.001)
                    next_begin = max(0, next_start - round(RATE * KEEP_HEAD))
                    retained = (max(0, finish - room_end) + max(0, room_start - next_begin)) / RATE
                    inserted = (gap if asked is not None else 0.0 if inline_boundary
                                else max(0.0, gap - retained))
                    if inserted > 0:
                        output.write(np.zeros(round(RATE * inserted), dtype=np.float32))
            # Let the narration finish rather than stop dead on the last sample.
            trailing = styles.TAIL_ROOM + max(0.0, (segments[-1].get('trail_pause', 0) or 0)
                                              if segments else 0)
            output.write(np.zeros(int(RATE * trailing), dtype=np.float32))
        os.replace(combined, destination)
    join_segments.last_edges_ramped = edges_ramped
    return sf.info(destination).duration

def export_audio(source, destination):
    destination = Path(destination)
    if destination.suffix.lower() not in ('.wav', '.mp3'):
        raise ValueError('Choose a WAV or MP3 filename.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        target = Path(temp) / ('export' + destination.suffix.lower())
        codec = ['-c:a', 'libmp3lame', '-b:a', '320k', '-ar', '48000'] if target.suffix == '.mp3' else ['-c:a', 'pcm_s24le', '-ar', RATE]
        convert(['-i', source, '-vn', '-af', 'loudnorm=I=-18:TP=-1.5:LRA=11', *codec, target])
        os.replace(target, destination)

def waveform(path, bins=420):
    with sf.SoundFile(path) as source:
        step = max(1, (len(source) + bins - 1) // bins)
        peaks = [float(np.max(np.abs(block))) for block in source.blocks(blocksize=step, dtype='float32')]
    return peaks
