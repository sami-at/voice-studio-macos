"""Does a delivery instruction actually change delivery, repeatably, without losing the voice?

The test that matters. For each instruction the same sentence is generated with several
seeds, so a real effect can be told apart from seed variation — the trap that made earlier
candidates look controllable when they were not. Voice identity is measured against Hal's
own reference, and every clip is transcribed so a dramatic take that drops words is caught.

Nothing here touches the application or its engines.
"""
import json
import os
from pathlib import Path
import statistics as st
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import numpy as np
import soundfile as sf
from voice_studio import verify
from voice_studio.config import DATA, STT_MODEL
from voice_studio.storage import profiles

OUT = ROOT / 'samples' / 'expressive'
MODEL = ROOT / 'models' / 'evaluation' / 'VoxCPM2-8bit'
GB = 1e9
SEEDS = (11, 22, 33)
SENTENCE = 'Have you ever wondered why flies rub their hands together?'
# Plain words, the kind a narrator would actually be told. Neutral is the baseline.
INSTRUCTIONS = [
    ('neutral', None),
    ('curious', 'curious and engaged, asking a genuine question'),
    ('surprised', 'pleasantly surprised, as if revealing something unexpected'),
    ('confident', 'calm and confident, explaining something you know well'),
    ('playful', 'light and playful, with a hint of humour'),
]


def measure(x, sr):
    """Pace, pitch movement and loudness range — the things an instruction should move."""
    n, h = int(0.04 * sr), int(0.01 * sr)
    lo, hi = int(sr / 350), int(sr / 70)
    pitches, rms = [], []
    for i in range(0, max(0, len(x) - n), h):
        frame = x[i:i + n].astype(np.float64)
        level = np.sqrt(np.mean(frame ** 2))
        rms.append(level)
        if level < 0.03:
            continue
        frame = frame - frame.mean()
        ac = np.correlate(frame, frame, 'full')[n - 1:]
        if ac[0] <= 0 or hi >= len(ac):
            continue
        k = int(np.argmax(ac[lo:hi])) + lo
        if ac[k] / ac[0] < 0.45:
            continue
        pitches.append(sr / k)
    rms = np.array(rms)
    voiced = rms > 0.03
    out = {'seconds': round(len(x) / sr, 2),
           'words_per_sec': round(len(SENTENCE.split()) / (len(x) / sr), 2)}
    if len(pitches) > 10:
        pitches = np.array(pitches)
        out['f0_median'] = round(float(np.median(pitches)), 1)
        out['f0_spread'] = round(float(np.std(12 * np.log2(pitches / np.median(pitches)))), 2)
    if voiced.sum() > 10:
        db = 20 * np.log10(rms[voiced] + 1e-9)
        out['dynamics_db'] = round(float(np.percentile(db, 90) - np.percentile(db, 10)), 2)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    assert MODEL.is_dir(), f'{MODEL} is missing; download it first'
    import mlx.core as mx
    sys.path.insert(0, str(ROOT))
    from voice_check import fingerprint
    import mlx_whisper
    from scipy.signal import resample_poly
    import math

    from scipy.signal import resample_poly as _resample

    def voice_print(path, work=OUT / '_fingerprint.wav'):
        """Fingerprint at a common 24 kHz: this model returns 48 kHz, the references 24."""
        audio, sr = sf.read(path, dtype='float32')
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != 24000:
            g = math.gcd(sr, 24000)
            audio = _resample(audio, 24000 // g, sr // g).astype(np.float32)
        sf.write(work, audio, 24000, subtype='PCM_16')
        return fingerprint(work)

    hal = next(p for p in profiles() if p['name'] == 'Hal')
    reference = DATA / hal['reference']
    hal_print = voice_print(reference)
    mike = next((p for p in profiles() if p['name'] == 'Mike'), None)
    mike_print = voice_print(DATA / mike['reference']) if mike else None

    def heard(path):
        audio, sr = sf.read(path, dtype='float32')
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        g = math.gcd(sr, 16000)
        audio = resample_poly(audio, 16000 // g, sr // g).astype(np.float32)
        return mlx_whisper.transcribe(audio, path_or_hf_repo=str(STT_MODEL), verbose=None,
                                      condition_on_previous_text=False,
                                      temperature=0.0)['text'].strip()

    mx.set_default_device(mx.gpu)
    mx.set_cache_limit(256 * 1024 * 1024)
    from mlx_audio.tts.utils import load_model
    import time
    t = time.monotonic()
    model = load_model(str(MODEL))
    report = {'model': 'mlx-community/VoxCPM2-8bit', 'sentence': SENTENCE,
              'load_seconds': round(time.monotonic() - t, 1),
              'model_memory_gb': round(mx.get_active_memory() / GB, 2), 'instructions': {}}
    print(f"  loaded {type(model).__name__} in {report['load_seconds']}s "
          f"({report['model_memory_gb']} GB resident)", flush=True)

    peak = 0.0
    for label, instruct in INSTRUCTIONS:
        rows = []
        for seed in SEEDS:
            mx.random.seed(seed)
            mx.reset_peak_memory()
            started = time.monotonic()
            kwargs = dict(text=SENTENCE, ref_audio=str(reference),
                          ref_text=hal['transcript'], verbose=False)
            if instruct:
                kwargs['instruct'] = instruct
            chunks, sr = [], 24000
            for result in model.generate(**kwargs):
                chunks.append(np.asarray(result.audio.astype(mx.float32)).reshape(-1))
                sr = result.sample_rate
            audio = np.concatenate(chunks)
            peak = max(peak, mx.get_peak_memory() / GB)
            path = OUT / f'voxcpm_{label}_s{seed}.wav'
            sf.write(path, audio, sr, subtype='PCM_16')
            row = measure(audio, sr)
            row['sample_rate'] = sr
            row['seed'] = seed
            row['generation_seconds'] = round(time.monotonic() - started, 1)
            row['realtime_factor'] = round(row['generation_seconds'] / row['seconds'], 1)
            row['identity_hal'] = round(float(np.dot(voice_print(path), hal_print)), 4)
            if mike_print is not None:
                row['identity_mike'] = round(float(np.dot(voice_print(path), mike_print)), 4)
            check = verify.compare(SENTENCE, heard(path))
            row['complete'] = check['ok']
            row['coverage'] = check['coverage']
            rows.append(row)
            mx.clear_cache()
            print(f"  {label:10s} seed={seed} {row['seconds']:5.2f}s "
                  f"f0_spread={row.get('f0_spread')} dyn={row.get('dynamics_db')} "
                  f"w/s={row['words_per_sec']} hal={row['identity_hal']} "
                  f"complete={row['complete']} ({row['realtime_factor']}x RT)", flush=True)

        def mean(field):
            values = [r[field] for r in rows if r.get(field) is not None]
            return round(st.mean(values), 2) if values else None

        report['instructions'][label] = {
            'instruct': instruct, 'takes': rows,
            'f0_spread_mean': mean('f0_spread'), 'dynamics_mean': mean('dynamics_db'),
            'words_per_sec_mean': mean('words_per_sec'), 'f0_median_mean': mean('f0_median'),
            'identity_hal_mean': mean('identity_hal'),
            'all_complete': all(r['complete'] for r in rows)}

    report['peak_memory_gb'] = round(peak, 3)

    # Does any instruction separate cleanly from neutral, or do the takes overlap?
    base = report['instructions']['neutral']
    print('\n  instruction      f0_spread   dynamics   words/s   identity(Hal)  separates?', flush=True)
    verdicts = {}
    for label, data in report['instructions'].items():
        spread_values = [r.get('f0_spread') for r in data['takes'] if r.get('f0_spread')]
        base_values = [r.get('f0_spread') for r in base['takes'] if r.get('f0_spread')]
        clean = bool(spread_values and base_values and
                     (min(spread_values) > max(base_values) or
                      max(spread_values) < min(base_values)))
        verdicts[label] = clean
        print(f"  {label:14s} {str(data['f0_spread_mean']):>9} {str(data['dynamics_mean']):>10} "
              f"{str(data['words_per_sec_mean']):>9} {str(data['identity_hal_mean']):>14}"
              f"   {'yes' if clean and label != 'neutral' else '-'}", flush=True)
    report['separates_from_neutral'] = {k: v for k, v in verdicts.items() if k != 'neutral'}
    report['any_instruction_separates'] = any(report['separates_from_neutral'].values())

    identity = [r['identity_hal'] for d in report['instructions'].values() for r in d['takes']]
    report['identity_hal_range'] = [round(min(identity), 4), round(max(identity), 4)]
    print(f"\n  peak memory {report['peak_memory_gb']} GB", flush=True)
    print(f"  Hal identity across every take: {report['identity_hal_range']}", flush=True)
    print(f"  any instruction separating from neutral on pitch movement: "
          f"{report['any_instruction_separates']}", flush=True)
    (ROOT / 'docs' / 'expressive-voxcpm.json').write_text(json.dumps(report, indent=2))
    print(f"  audio: {OUT.relative_to(ROOT)}", flush=True)


if __name__ == '__main__':
    main()
