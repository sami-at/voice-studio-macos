"""One job per child process. JSON events on stdout; model logs on stderr."""
import contextlib
import json
import os
from pathlib import Path
import resource
import shutil
import sys
import time
import traceback

from .config import DATA, ROOT, STT_MODEL, TTS_MODEL, initialize, offline_environment
from .storage import (add_take, atomic_json, choose_take, selected_take, spoken_fingerprint,
                      identifier, now, read_json, save_profile,
                      save_session, segment_is_stale, segment_needs_audio, takes_of,
                      text_fingerprint)
from . import direction, engines, moods, quality, resources, styles, verify

EVENT = 'VS_EVENT '

def emit(kind, **payload):
    sys.__stdout__.write(EVENT + json.dumps({'kind': kind, **payload}, ensure_ascii=False) + '\n')
    sys.__stdout__.flush()

def transcribe(path, details=False):
    if not (STT_MODEL / '.complete').exists():
        raise RuntimeError('Offline transcription model is missing. Run Install Voice Studio.command once.')
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    import mlx_whisper
    audio, rate = sf.read(path, dtype='float32')
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    import math
    gcd = math.gcd(rate, 16000)
    audio = resample_poly(audio, 16000 // gcd, rate // gcd).astype(np.float32)
    result = mlx_whisper.transcribe(audio, path_or_hf_repo=str(STT_MODEL), verbose=None,
                                   condition_on_previous_text=False, temperature=0.0,
                                   word_timestamps=details)
    text = result['text'].strip()
    if not text:
        raise ValueError('No speech was recognized. Enter the reference transcript manually.')
    if details:
        return {'text': text, 'words': [word for seg in result.get('segments', [])
                                      for word in seg.get('words', [])]}
    return text

def prepare(job):
    from .audio import prepare_reference
    profile_id = job.get('profile_id') or identifier()
    version = identifier()
    folder = DATA / 'voices' / profile_id / version
    folder.mkdir(parents=True, exist_ok=True)
    source = Path(job['source'])
    original = folder / ('original' + source.suffix.lower())
    shutil.copy2(source, original)
    emit('status', message='Preparing a clean 24 kHz voice reference…')
    reference = folder / 'reference.wav'
    details = prepare_reference(original, reference, job.get('start', 0), job.get('duration', 12))
    # Replacing a recording keeps everything else about the voice: its name if none was
    # given, its default style, and any notes already saved against it.
    existing = read_json(DATA / 'voices' / profile_id / 'profile.json') or {}
    profile = {**existing,
               'id': profile_id, 'name': job['name'].strip() or existing.get('name') or source.stem,
               'created': existing.get('created') or now(),
               'original': str(original.relative_to(DATA)), 'reference': str(reference.relative_to(DATA)),
               'transcript': job.get('transcript', '').strip(), 'start': job.get('start', 0),
               'style': job.get('style') or existing.get('style') or styles.NATURAL,
               'placeholder': False, **details}
    # Save the usable sample even if recognition fails; the user can type its transcript.
    save_profile(profile)
    if job.get('transcribe', False):
        emit('status', message='Transcribing the selected sample locally…')
        try:
            profile['transcript'] = transcribe(reference)
            save_profile(profile)
        except Exception as exc:
            emit('warning', message=f'Voice saved. Automatic transcription failed: {exc}')
    emit('profile', profile=profile)

def previous_cut(take):
    """An older take was verified before cut endings were detected. Judge its raw audio by today's rule,
    so a regeneration is never discarded in favour of a take whose last word was cut off."""
    if any(f.get('code') == 'cut_ending' for f in take.get('quality') or []):
        return True
    raw = DATA / take['raw_file'] if take.get('raw_file') else None
    if not raw or not raw.is_file():
        return False
    import soundfile as sf
    from .audio import CUT_STOP_REL_DB, ending_stop
    return ending_stop(sf.read(raw, dtype='float32')[0])[0] > CUT_STOP_REL_DB


def generate(job):
    from .audio import RATE, boundary_check, conditioned_reference, join_segments, write_segment
    import numpy as np
    import soundfile as sf
    if not engines.available():
        raise RuntimeError('No speech engine is installed. Run Install Voice Studio.command once.')
    session = read_json(job['session'])
    reference = DATA / session['reference']
    if not reference.is_file() or not session.get('transcript', '').strip():
        raise ValueError('The voice reference or its transcript is missing. Update this voice profile and create a new narration.')
    style = styles.settings(session.get('style', styles.NATURAL), session.get('settings'))
    # Record what was actually used, so assembling and reopening agree with the audio
    # even for a session saved before styles existed.
    session['speed'], session['pause'] = style['speed'], style['pause']
    session['sentence_pause'] = style['sentence_pause']
    # Pace comes from the reference's own delivery; the sample is stretched, not the words.
    # Each mood clip sits in its own folder, so its stretched copy never collides with another's.
    conditioned = {}

    def reference_for(segment):
        mood, path, transcript = moods.resolve(session, segment)
        if not (DATA / path).is_file() or not (transcript or '').strip():
            emit('warning', message=f'The {moods.label(mood)} clip is missing; using the main reference.')
            mood, path, transcript = None, session['reference'], session['transcript']
        if path not in conditioned:
            source = DATA / path
            conditioned[path] = conditioned_reference(source, style['reference_tempo'], source.parent)
        return mood, conditioned[path], transcript
    import mlx.core as mx
    host = engines.EngineHost(emit=emit)
    stop_file = Path(job['stop_file']) if job.get('stop_file') else None
    history = []

    def admit(engine):
        """Re-check live resources before every model load (first load and after any switch)."""
        print('[resources] checking before loading', engine, file=sys.stderr, flush=True)
        reading = resources.snapshot(DATA, exclude_pids=(os.getpid(),))
        decision, reason = resources.admission([engine], reading, history)
        history.append(reading)
        if decision != resources.ADMIT:
            emit('resource_wait', decision=decision, engine=engine, message=reason)
            return False
        print('[resources] admitted', engine, reading, file=sys.stderr, flush=True)
        return True

    last_report = [0.0]

    def report(nbytes):
        now = time.monotonic()
        if now - last_report[0] >= 1.0:
            last_report[0] = now
            emit('memory', mlx_gb=round(nbytes / 1e9, 3))
    host.before_load = admit
    host.on_chunk = report
    selected = job.get('indices')
    if selected is None:
        # Also pick up sections whose words were edited after their audio was made.
        selected = [i for i, s in enumerate(session['segments']) if segment_needs_audio(s, DATA)]
    total = len(selected)
    # Generating consecutive sections with one engine keeps it loaded; the order below
    # groups them so a slow model is not loaded and freed over and over.
    selected = sorted(selected, key=lambda i: engines.normalize(
        job.get('engine') or session['segments'][i].get('engine') or
        session.get('engine') or engines.DEFAULT))

    # A zero-shot model occasionally drops or garbles words. Each take is listened back to
    # and compared with the script; a bad one is retried with a different seed rather than
    # being passed off as finished.
    attempts = min(3, max(1, int(job.get('attempts', 3)))) if job.get('verify', True) else 1
    for done, index in enumerate(selected):
        segment = session['segments'][index]
        engine = engines.normalize(job.get('engine') or segment.get('engine')
                                   or session.get('engine') or engines.DEFAULT)
        config = engines.config_for(engine, job.get('engine_config') or
                                    segment.get('engine_config'))
        # A new take must not repeat an existing one, so start past the seeds already used.
        used = [t.get('seed') or 0 for t in takes_of(segment)]
        saved_seed = segment.get('seed')
        base = (saved_seed if saved_seed is not None else 42 + index) + (1 if job.get('regenerate') else 0)
        if used:
            base = max(base, max(used) + 1)
        plan = direction.parse(segment['text'])
        spoken = plan.spoken
        if plan.problems:
            raise ValueError(f'Section {index + 1}: ' + ' '.join(plan.problems))
        if not spoken.strip():
            raise ValueError(f'Section {index + 1} has no words to speak.')
        if stop_file and stop_file.exists():
            # The app asked to stop safely: everything finished so far is already saved.
            emit('safely_stopped', completed=done, total=total,
                 message=stop_file.read_text().strip() or 'Stopped to protect the system.')
            break
        # Load before announcing, so "Loading…" cannot overwrite "Generating section…".
        # Consecutive sections on the same engine reuse the model and skip this.
        try:
            host.load(engine)
        except engines.ResourceWait:
            break                                   # resource_wait was emitted; nothing was loaded
        emit('progress', completed=done, total=total, index=index, engine=engine,
             message=f'Generating section {index + 1} of {len(session["segments"])} '
                     f'with {engines.label(engine)}…')
        start = time.monotonic()
        best, takes = None, 0
        previous = selected_take(segment)
        previous_valid = (previous and previous.get('verified') is True
                          and not segment_is_stale(segment)
                          and (DATA / previous['file']).is_file()
                          and not previous_cut(previous))
        attempt_files = []
        mood, reference, ref_text = reference_for(segment)
        for attempt in range(attempts):
            takes = attempt + 1
            seed = base + attempt * 977        # a different take, not a nearby one
            if attempt:
                emit('status', message=f'Section {index + 1} was incomplete. '
                                       f'Take {attempt + 1} of {attempts}…')
            # The engine is given the spoken form, never the direction markers.
            audio = host.synthesize(engine, spoken, reference,
                                    ref_text, seed, config, RATE,
                                    language=session.get('language', 'English'))
            candidate = DATA / 'sessions' / session['id'] / f'{index + 1:04d}-{identifier()[:8]}.wav'
            candidate.parent.mkdir(parents=True, exist_ok=True)
            raw_path = candidate.with_suffix('.raw.wav')
            # Keep model output for diagnosing generation versus processing defects.
            sf.write(raw_path, audio, RATE, subtype='FLOAT')
            boundary = boundary_check(audio)
            tuning = styles.engine_tuning(engine, session.get('style'))
            used_speed = round(style['speed'] * plan.pace_factor * tuning.get('speed_factor', 1.0), 4)
            seconds = write_segment(audio, candidate, used_speed)
            del audio
            mx.clear_cache()
            check = None
            word_timing = []
            if attempts > 1 or job.get('verify', True):
                try:
                    recognized = transcribe(candidate, details=True)
                    check = verify.compare(spoken, recognized['text'])
                    word_timing = recognized['words']
                    check['heard'] = recognized['text']
                    if boundary['head_at_boundary'] or boundary['tail_at_boundary']:
                        check.update(ok=False, boundary_uncertain=True)
                except Exception as exc:                      # never fail a good take on this
                    emit('warning', message=f'Section {index + 1} could not be checked: {exc}')
            # Measured flags for the review tab. Observations only: they never delete or fade audio.
            try:
                flags = quality.analyze_take(sf.read(raw_path, dtype='float32')[0], RATE,
                                             words=len(verify.normalize(spoken)),
                                             heard=(check or {}).get('heard'), spoken=spoken)
            except Exception as exc:
                flags = []
                emit('warning', message=f'Section {index + 1} quality flags unavailable: {exc}')
            # A sound that stops at full level was cut off. Treat it like any other unconfirmed
            # edge: keep the take, mark it for review, and try another seed.
            cut = [f['code'] for f in flags if f['code'] in ('abrupt_end', 'abrupt_start', 'cut_ending')]
            if cut and check is not None:
                cliff = next((f.get('cliff_db') for f in flags if f['code'] == 'cut_ending'), 0.0)
                check.update(ok=False, boundary_uncertain=True, abrupt=cut, cliff_db=cliff)
            take = {'file': candidate, 'seconds': seconds, 'seed': seed, 'check': check,
                    'attempt': attempt + 1, 'raw_file': raw_path, 'boundary_check': boundary,
                    'word_timing': word_timing, 'quality': flags, 'speed_used': used_speed,
                    'engine_speed_factor': tuning.get('speed_factor', 1.0),
                    'dead_air_guard_s': tuning.get('dead_air_guard_s')}
            attempt_files.append({'file': str(candidate.relative_to(DATA)),
                                  'raw_file': str(raw_path.relative_to(DATA)), 'check': check})
            if best is None or verify.candidate_rank(check) > verify.candidate_rank(best['check']):
                best = take
            if check is None or check['ok']:
                break
        check = best['check']
        # Every generation adds a take; an earlier one is never overwritten or deleted.
        add_take(segment, {
            'engine': engine, 'engine_config': config,
            'voice_id': session.get('voice_id'), 'voice_name': session.get('voice_name'),
            'mood': mood,
            'file': str(best['file'].relative_to(DATA)), 'seconds': best['seconds'],
            'raw_file': str(best['raw_file'].relative_to(DATA)),
            'boundary_check': best['boundary_check'], 'word_timing': best['word_timing'],
            'quality': best['quality'], 'speed_used': best['speed_used'],
            'engine_speed_factor': best['engine_speed_factor'], 'dead_air_guard_s': best['dead_air_guard_s'],
            'pace': plan.pace, 'pace_factor': plan.pace_factor,
            'verification_version': 2, 'attempt_files': attempt_files,
            'text': segment['text'], 'spoken': spoken,
            'pauses': plan.pauses, 'overrides': plan.overrides,
            'text_hash': text_fingerprint(segment['text']),
            'spoken_hash': spoken_fingerprint(segment['text']),
            'seed': best['seed'], 'attempts': takes, 'kept_take': best['attempt'],
            'verified': (check['ok'] if check else None),
            'check': check,
        })
        if previous_valid and not (check and check['ok']):
            choose_take(segment, previous['id'])
            emit('warning', message=f'Section {index + 1}: the new take needs review; '
                                   'your previously valid take remains selected.')
        segment['generation_seconds'] = round(time.monotonic() - start, 2)
        session['output'] = None
        save_session(session)
        if check and not check['ok']:
            # Keep the best audio we got, but say plainly that it is not complete.
            emit('incomplete', index=index, detail=verify.describe(check, index),
                 attempts=takes, kept_take=best['attempt'], **{k: check[k] for k in
                 ('similarity', 'coverage', 'head_ok', 'tail_ok')})
        emit('segment', index=index, file=str(DATA / segment['file']), seconds=segment['seconds'],
             elapsed=segment['generation_seconds'], completed=done + 1, total=total,
             verified=segment['verified'], attempts=takes, kept_take=best['attempt'],
             engine=engine, mood=mood, takes=len(takes_of(segment)))
        mx.clear_cache()
    print('[resources] releasing the model', file=sys.stderr, flush=True)
    host.release()
    # A [pace:] change needs no new recording: the raw model output is kept with every take, so the
    # section is re-processed from it as a NEW take. The earlier take stays listed and selectable.
    for index, seg in enumerate(session['segments']):
        plan = direction.parse(seg['text'])
        take = selected_take(seg)
        if plan.problems or not take or segment_needs_audio(seg, DATA):
            continue
        factor = take.get('engine_speed_factor', 1.0)          # what this take was made with; never re-decided
        wanted = round(style['speed'] * plan.pace_factor * factor, 4)
        have = take.get('speed_used', style['speed'] * take.get('pace_factor', 1.0))
        # Only a changed [pace:] mark triggers this; a new style speed never re-times old takes.
        if abs(plan.pace_factor - (take.get('pace_factor') or 1.0)) < 1e-6:
            continue
        raw_path = DATA / take['raw_file'] if take.get('raw_file') else None
        if not raw_path or not raw_path.is_file():
            emit('warning', message=f'Section {index + 1}: its pace changed, but this older take has no saved '
                                    'raw recording. Record the section again to apply it.')
            continue
        import soundfile as sf
        stem = DATA / 'sessions' / session['id'] / f'{index + 1:04d}-{identifier()[:8]}'
        new_file = stem.with_suffix('.wav')
        seconds = write_segment(sf.read(raw_path, dtype='float32')[0], new_file, wanted)
        ratio = have / wanted                                   # a faster take shortens every timestamp
        timing = [{**w, 'start': w['start'] * ratio, 'end': w['end'] * ratio} for w in take.get('word_timing') or []]
        clone = {k: v for k, v in take.items() if k not in ('id', 'created')}
        clone.update(file=str(new_file.relative_to(DATA)), seconds=seconds, word_timing=timing,
                     speed_used=wanted, pace=plan.pace, pace_factor=plan.pace_factor,
                     retimed_from=take['id'])
        add_take(seg, clone)
        session['output'] = None
        save_session(session)
        emit('status', message=f'Section {index + 1} re-timed ({plan.pace or "normal"}) from its saved recording.')
    # Old takes can be retimed without TTS. Align the selected audio once, after the
    # speech model has been released; store timestamps with that exact take.
    for index, seg in enumerate(session['segments']):
        plan = direction.parse(seg['text'])
        words = len(verify.normalize(plan.spoken))
        internal = any(0 < len(verify.normalize(plan.spoken[:offset])) < words
                       for offset, _ in plan.pauses)
        if internal and not seg.get('word_timing') and not segment_needs_audio(seg, DATA):
            emit('status', message=f'Locating pause words in section {index + 1} offline…')
            timing = transcribe(DATA / seg['file'], details=True)['words']
            seg['word_timing'] = timing
            take = selected_take(seg)
            if take:
                take['word_timing'] = timing
            save_session(session)
    used_engines = {selected_take(s).get('engine') for s in session['segments'] if selected_take(s)}
    if len(used_engines) > 1:
        emit('warning', message='This narration mixes engines. Compare the selected takes '
                               'against the voice reference; timbre and accent can differ.')
    unverified = [i for i, seg in enumerate(session['segments']) if seg.get('verified') is False]
    if unverified:
        emit('unverified', indices=unverified,
             detail='; '.join(verify.describe(session['segments'][i]['check'], i)
                              for i in unverified if session['segments'][i].get('check')))
    unchecked = [i + 1 for i, seg in enumerate(session['segments'])
                 if seg.get('verified') is None]
    if unchecked:
        emit('warning', message='Recognition was unavailable for section(s) '
                               + ', '.join(map(str, unchecked)) + '. These takes remain unchecked.')
    stale = [i for i, s in enumerate(session['segments']) if segment_is_stale(s)]
    if stale:
        # Refuse to present audio of the wrong words as a finished narration.
        rows = ', '.join(str(i + 1) for i in stale)
        raise RuntimeError(f'Section {rows} was edited after its audio was generated. '
                           'Press Generate to record the new wording.')
    if all(s.get('file') and (DATA / s['file']).exists() for s in session['segments']):
        emit('status', message='Assembling your narration…')
        destination = DATA / 'sessions' / session['id'] / f'narration-{identifier()[:8]}.wav'
        seconds = join_segments(session, DATA, destination)
        session['output'] = str(destination.relative_to(DATA))
        session['seconds'] = seconds
        save_session(session)
        emit('output', file=str(destination), seconds=seconds)
    # MLX counts only its own buffers; resident size is what competes with macOS for 8 GB.
    emit('metrics', peak_memory_gb=round(mx.get_peak_memory() / 1e9, 3),
         peak_rss_gb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9, 3))

def run(job):
    action = job['action']
    if action == 'prepare':
        prepare(job)
    elif action == 'transcribe':
        emit('status', message='Transcribing the reference on your Mac…')
        emit('transcript', text=transcribe(job['source']))
    elif action == 'generate':
        generate(job)
    elif action == 'export':
        from .audio import export_audio
        emit('status', message='Mastering and exporting audio…')
        export_audio(job['source'], job['destination'])
        try:                       # decode what was written and measure it; a failure here never blocks the export
            check = quality.validate_export(job['destination'], job['source'])
        except Exception as exc:
            check = {'ok': False, 'measured': {}, 'warnings': [{'code': 'validation', 'severity': 'note',
                                                                'message': f'Could not validate: {exc}'}]}
        emit('exported', file=job['destination'], validation=check)
    else:
        raise ValueError('Unknown task: ' + action)

def main():
    # Child process owns a group; cancellation also stops any active FFmpeg child.
    if hasattr(os, 'setsid'):
        try:
            os.setsid()
        except OSError:
            pass
    initialize()
    os.environ.update(offline_environment())
    try:
        job = read_json(sys.argv[1])
        with contextlib.redirect_stdout(sys.stderr):
            run(job)
        emit('done')
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        emit('error', message=str(exc))
        sys.exit(1)

if __name__ == '__main__':
    main()
