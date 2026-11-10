"""Build the ElevenLabs benchmark comparison set.

Reads only. Every input recording, voice profile, session and take stays exactly as it is;
all output goes to samples/elevenlabs-benchmark/. Run the steps in order:

  assemble   build each comparison narration with the app's own pipeline
  repair     choose a complete-ending take for the opening question by a fixed rule
  asr        offline Whisper word timings for every narration (loads no TTS engine)
  analyze    cut matching phrases, measure them, write level-matched clips and data/benchmark.json
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_audio import (ROOT, SENTENCES, KINDS, OCTAVES, active_span, cut_points, decode, load,  # noqa: E402
                             matched, octave_levels, phrase_metrics, rms_db, summarize)
from voice_studio.config import offline_environment  # noqa: E402

os.environ.update(offline_environment())
from voice_studio import audio as A, styles, verify  # noqa: E402

OUT = ROOT / 'samples/elevenlabs-benchmark'
WORK, FULL, PHRASES, DATA_OUT = OUT / 'work', OUT / 'audio/full', OUT / 'audio/phrases', OUT / 'data'
DOWNLOADS = Path.home() / 'Downloads'
EL_FILE = next(DOWNLOADS.glob('ElevenLabs_2026-10-23T19_00_04_Hal*_v4.mp3'))
VS_FILE = DOWNLOADS / 'Hal Voice over app.mp3'
SESSION = ROOT / 'local_data/sessions/b3daa1e66e474c45a1bcf501ec03c4e3'
MATRIX = ROOT / 'samples/final-quality'
EXPERIMENTS = OUT / 'experiments'
RATE = A.RATE

# Script structure the app produced for this narration: every paragraph is its own section,
# with the author's [pause:n] marks as lead pauses.
PARAGRAPHS = [  # (text, paragraph_end, lead_pause)
    (SENTENCES[0], True, None), (SENTENCES[1], True, .4), (SENTENCES[2], True, None),
    (SENTENCES[3], True, .5), (SENTENCES[4], True, None), (SENTENCES[5], True, None),
    (SENTENCES[6], True, .4), (SENTENCES[7], False, .3), (SENTENCES[8], True, None)]
SECTIONS8 = [PARAGRAPHS[i] for i in range(7)] + [(SENTENCES[7] + ' ' + SENTENCES[8], True, .3)]

SOURCES = [
    # id, group, label, description
    ('elevenlabs', 'Reference', 'ElevenLabs Hal',
     'Your ElevenLabs recording, used as the quality reference. 44.1 kHz, 128 kbps MP3.'),
    ('vs-original', 'Your Voice Studio file', 'Voice Studio: original',
     'Your "Hal Voice over app.mp3" exactly as exported (Qwen3, Energetic Explainer, takes you selected).'),
    ('vs-raw', 'Same takes, other stages', 'Voice Studio: raw engine output',
     'The same seven selected takes straight from the engine: no gain, no 1.04x tempo, no loudness step, no assembly.'),
    ('vs-repaired', 'Same takes, other stages', 'Voice Studio: repaired',
     'Same takes and the same pipeline, except the opening question is a take whose ending is complete (chosen by a fixed rule, see report).'),
    ('vs-experimental', 'Same takes, other stages', 'Voice Studio: repaired + room-tone floor (experiment)',
     'Repaired, plus a very quiet (-82 dBFS) noise floor inside the exact-silence gaps, as ElevenLabs has. Tests whether digital silence between phrases is part of what you hear (for example on Bluetooth). Not part of the app.'),
    ('vs-presence', 'Same takes, other stages', 'Voice Studio: repaired + presence lift (experiment)',
     'Repaired, plus a +4.5 dB high shelf above 3 kHz, the measured gap to ElevenLabs. Tests whether the duller 4-10 kHz range is part of the clarity difference. Not part of the app.'),
    ('qwen-natural', 'Engine and style alternatives', 'Qwen3 · Natural',
     'Same script, one fixed-seed take per section, Natural settings. No take selection.'),
    ('qwen-energetic', 'Engine and style alternatives', 'Qwen3 · Energetic Explainer',
     'Same, Energetic Explainer (reference at 1.15x, output at 1.04x).'),
    ('chatterbox-natural', 'Engine and style alternatives', 'Chatterbox · Natural',
     'Same script and seeds with Chatterbox. Slower engine.'),
    ('chatterbox-energetic', 'Engine and style alternatives', 'Chatterbox · Energetic Explainer',
     'Same, Energetic Explainer.'),
    ('qwen-one-pass', 'Qwen3 text-splitting and reference tests', 'Qwen3 · whole script in one pass',
     'Natural settings, the entire script generated as a single piece (no section joins).'),
    ('qwen-per-sentence', 'Qwen3 text-splitting and reference tests', 'Qwen3 · one sentence per take',
     'Natural settings, nine separate takes, joined with the script\'s own pauses.'),
    ('qwen-ref-opening', 'Qwen3 text-splitting and reference tests', 'Qwen3 · reference = Hal\'s opening question',
     'Natural settings, cloned from the first 10.9 s of Hal\'s original instead of the 11-24 s window the app uses. One seed per section: later 5-seed testing showed this does not reliably change delivery.'),
    ('qwen-ref-full', 'Qwen3 text-splitting and reference tests', 'Qwen3 · reference = all 24 s of Hal',
     'Natural settings, cloned from the whole 24 s original.'),
]


def raw_audio(path):
    audio, rate = sf.read(str(path), dtype='float32')
    assert rate == RATE and audio.ndim == 1
    return audio


def pipeline(name, sections, values, folder=WORK):
    """Raw takes -> the app's write_segment (gain, tempo) -> the app's join_segments."""
    folder = folder / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    segments = []
    for i, (audio, (text, end, lead)) in enumerate(sections):
        path = folder / f'{i + 1:02d}.wav'
        A.write_segment(audio, path, values['speed'])
        seg = {'file': str(path), 'text': text, 'paragraph_end': end}
        if lead:
            seg['lead_pause'] = lead
        segments.append(seg)
    session = {'segments': segments, 'pause': values['pause'], 'sentence_pause': values['sentence_pause']}
    destination = WORK / f'{name}.wav'
    A.join_segments(session, folder, destination)
    return destination


def experimental_finish(path, destination):
    """Hypothesis test only. (1) A 4 ms half-cosine ramp where audible sound meets exact
    digital silence; (2) a -82 dBFS noise floor inside exact-silence gaps >= 40 ms."""
    x, rate = load(path)
    x = x.astype(np.float64).copy()
    silent = np.abs(x) < 1e-5
    edges = np.diff(np.r_[False, silent, False].astype(int))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    ramp = int(rate * .004)
    rng = np.random.default_rng(7)
    ramped = filled = 0
    for a, b in zip(starts, ends):
        if b - a < int(rate * .04):
            continue
        if a >= ramp and np.sqrt(np.mean(x[a - ramp // 2:a] ** 2)) > 1e-3:   # sound ends at audible level
            x[a - ramp:a] *= np.cos(np.linspace(0, np.pi / 2, ramp)) ** 2
            ramped += 1
        if b + ramp <= len(x) and np.sqrt(np.mean(x[b:b + ramp // 2] ** 2)) > 1e-3:  # sound starts at audible level
            x[b:b + ramp] *= np.sin(np.linspace(0, np.pi / 2, ramp)) ** 2
            ramped += 1
        noise = (rng.random(b - a) - rng.random(b - a)) * 10 ** (-82 / 20) * np.sqrt(6)
        fade = int(rate * .005)
        shape = np.ones(b - a)
        shape[:fade] = np.linspace(0, 1, fade)
        shape[-fade:] = np.linspace(1, 0, fade)
        x[a:b] += noise * shape
        filled += 1
    sf.write(destination, x.astype(np.float32), rate, subtype='FLOAT')
    return {'edges_ramped': ramped, 'gaps_filled': filled}


# ------------------------------------------------------------------ steps

def session_takes():
    project = json.loads((SESSION / 'project.json').read_text())
    out = []
    for seg in project['segments']:
        take = next(t for t in seg['takes'] if t['id'] == seg['selected_take'])
        out.append((seg, take))
    return out


def step_assemble():
    WORK.mkdir(parents=True, exist_ok=True)
    nat, ene = styles.settings(styles.NATURAL), styles.settings(styles.ENERGETIC)
    for key, folder, values in (('qwen-natural', 'hal-qwen3-natural', nat),
                                ('qwen-energetic', 'hal-qwen3-energetic', ene),
                                ('chatterbox-natural', 'hal-chatterbox-natural', nat),
                                ('chatterbox-energetic', 'hal-chatterbox-energetic', ene)):
        sections = [(raw_audio(MATRIX / folder / f'{i + 1:02d}-raw.wav'), SECTIONS8[i]) for i in range(8)]
        print(key, pipeline(key, sections, values))
    for key, folder in (('qwen-ref-opening', 'ref-opening'), ('qwen-ref-full', 'ref-full')):
        sections = [(raw_audio(EXPERIMENTS / folder / f'{i + 1:02d}-raw.wav'), SECTIONS8[i]) for i in range(8)]
        print(key, pipeline(key, sections, nat))
    sections = [(raw_audio(EXPERIMENTS / 'per-sentence' / f'{i + 1:02d}-raw.wav'), PARAGRAPHS[i]) for i in range(9)]
    print('qwen-per-sentence', pipeline('qwen-per-sentence', sections, nat))
    one = raw_audio(EXPERIMENTS / 'one-pass/01-raw.wav')
    print('qwen-one-pass', pipeline('qwen-one-pass', [(one, (' '.join(SENTENCES), True, None))], nat))
    # the user's selected takes, raw: no gain, tempo or loudness step; 0.5 s of silence between
    pieces = []
    for seg, take in session_takes():
        pieces += [raw_audio(ROOT / 'local_data' / take['raw_file']), np.zeros(int(RATE * .5), dtype=np.float32)]
    sf.write(WORK / 'vs-raw.wav', np.concatenate(pieces[:-1]), RATE, subtype='FLOAT')


def step_repair():
    """Pick the opening take by a rule fixed in advance: the lowest seed whose recognised words
    match the script exactly AND whose ending and start are not abrupt. Nothing is chosen by ear."""
    from voice_studio.worker import transcribe
    values = styles.settings(styles.ENERGETIC)
    rows, chosen = [], None
    for i in range(8):
        raw_path = EXPERIMENTS / 'seed-sweep-open' / f'{i + 1:02d}-raw.wav'
        meta = json.loads(raw_path.with_suffix('.json').read_text())
        audio = raw_audio(raw_path)
        check = A.boundary_check(audio)
        processed = WORK / 'sweep' / f'{i + 1:02d}.wav'
        processed.parent.mkdir(parents=True, exist_ok=True)
        A.write_segment(audio, processed, values['speed'])
        heard = transcribe(processed, details=True)
        words = verify.compare(SENTENCES[0], heard['text'])
        ok = bool(words['ok'])
        row = {'index': i + 1, 'seed': meta['seed'], 'seconds': meta['seconds'], 'asr_ok': ok,
               'heard': heard['text'], 'tail_decay_db': round(check['tail_decay_db'], 1),
               'head_rise_db': round(check['head_rise_db'], 1), 'tail_abrupt': check['tail_abrupt'],
               'head_abrupt': check['head_abrupt']}
        row['accepted'] = ok and not check['tail_abrupt'] and not check['head_abrupt']
        if row['accepted'] and chosen is None:
            chosen = row
        rows.append(row)
        print(row)
    DATA_OUT.mkdir(parents=True, exist_ok=True)
    (DATA_OUT / 'repair-choice.json').write_text(json.dumps(
        {'rule': 'lowest seed with exact ASR match and neither tail_abrupt nor head_abrupt',
         'chosen': chosen, 'candidates': rows}, indent=1))
    if not chosen:
        raise SystemExit('No candidate passed the rule; nothing was repaired.')
    # the same seven takes except the first, through the app's own pipeline
    sections = [(raw_audio(EXPERIMENTS / 'seed-sweep-open' / f"{chosen['index']:02d}-raw.wav"),
                 (SENTENCES[0], True, None))]
    for seg, take in session_takes()[1:]:
        text = seg['text']
        end = bool(seg.get('paragraph_end'))
        sections.append((raw_audio(ROOT / 'local_data' / take['raw_file']), (text, end, seg.get('lead_pause'))))
    path = pipeline('vs-repaired', sections, values)
    info = experimental_finish(path, WORK / 'vs-experimental.wav')
    subprocess.run([A.ffmpeg(), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(path),
                    '-af', 'highshelf=f=3000:g=4.5:t=q:w=0.7', '-c:a', 'pcm_f32le', str(WORK / 'vs-presence.wav')], check=True)
    print('repaired', path, 'experimental', info)
    # the app's own export (loudness normalisation + MP3/WAV) for the two repaired narrations
    exports = OUT / 'audio/exports'
    exports.mkdir(parents=True, exist_ok=True)
    for key in ('vs-repaired', 'vs-experimental', 'vs-presence'):
        for suffix in ('mp3', 'wav'):
            A.export_audio(WORK / f'{key}.wav', exports / f'{key}.{suffix}')


def narrations():
    """id -> (waveform path, native rate note). The two originals are decoded, never altered."""
    WORK.mkdir(parents=True, exist_ok=True)
    decode(EL_FILE, WORK / 'elevenlabs.wav')
    decode(VS_FILE, WORK / 'vs-original.wav')
    return {sid: WORK / f'{sid}.wav' for sid, *_ in SOURCES}


def step_asr():
    from voice_studio.worker import transcribe
    (DATA_OUT / 'asr').mkdir(parents=True, exist_ok=True)
    for sid, path in narrations().items():
        result = transcribe(path, details=True)
        (DATA_OUT / 'asr' / f'{sid}.json').write_text(json.dumps(result, default=float, indent=1))
        print(sid, round(sf.info(path).duration, 1), 's:', result['text'][:90])


def step_analyze():
    paths = narrations()
    for folder in (FULL, PHRASES):
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
    report = {'octaves_hz': OCTAVES, 'script': SENTENCES, 'kinds': KINDS, 'sources': [], 'level_target_lufs': -24.0}
    for sid, group, label, description in SOURCES:
        x, rate = load(paths[sid])
        words = json.loads((DATA_OUT / 'asr' / f'{sid}.json').read_text())['words']
        cuts, spans = cut_points(x, rate, words)
        metrics = phrase_metrics(x, rate, cuts)
        whole, gain, limited = matched(x, rate)
        sf.write(FULL / f'{sid}.wav', whole, rate, subtype='PCM_16')
        entry = {'id': sid, 'group': group, 'label': label, 'description': description,
                 'rate': rate, 'seconds': round(len(x) / rate, 2), 'full': f'audio/full/{sid}.wav',
                 'full_gain_db': round(gain, 2), 'phrases': []}
        for i, m in enumerate(metrics):
            if m.get('missing'):
                entry['phrases'].append(m)
                continue
            clip = x[int(cuts[i] * rate):int(cuts[i + 1] * rate)]
            s0, s1 = active_span(clip, rate)
            clip = clip[max(0, int((s0 - .15) * rate)):int((s1 + .30) * rate)]
            leveled, g, lim = matched(clip, rate)
            name = f'p{i + 1}-{sid}.wav'
            sf.write(PHRASES / name, leveled, rate, subtype='PCM_16')
            entry['phrases'].append({**m, 'file': f'audio/phrases/{name}', 'gain_db': round(g, 2),
                                     'peak_limited': lim})
        entry['summary'] = summarize(entry['phrases'])
        entry['octave_db'] = octave_levels(x, rate)
        report['sources'].append(entry)
        print(sid, 'phrases', sum(1 for p in entry['phrases'] if 'file' in p))
    (DATA_OUT / 'benchmark.json').write_text(json.dumps(report, indent=1, default=float))


def step_originals():
    """Bit-identical copies of the two recordings, beside a hash list. The sources are only read."""
    import hashlib
    folder = OUT / 'audio/originals'
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for source, name in ((EL_FILE, 'elevenlabs-hal.mp3'), (VS_FILE, 'voice-studio-original.mp3')):
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        shutil.copyfile(source, folder / name)
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
        rows.append(f'{digest}  {name}  (copy of ~/Downloads/{source.name})')
    (folder / 'SHA256.txt').write_text('\n'.join(rows) + '\n')
    print('\n'.join(rows))


if __name__ == '__main__':
    steps = {'originals': step_originals, 'assemble': step_assemble, 'repair': step_repair, 'asr': step_asr, 'analyze': step_analyze}
    for name in sys.argv[1:] or ['assemble', 'repair', 'asr', 'analyze', 'originals']:
        steps[name]()
