"""Save the user's approved energetic takes in an independent narration copy.

This is a one-off repair, not an automatic phoneme-completeness detector.
"""
import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import soundfile as sf
from voice_studio import audio, direction, storage
from voice_studio.config import DATA
from voice_studio.text import session_script, split_script

OUT = ROOT / 'samples/edge-followup'
SOURCE_ID = '2ba2d3fa509d4c37849199af710cc2e3'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    receipt = OUT / 'saved-repair.json'
    if receipt.exists():
        print(receipt.read_text())
        return
    original_paths = [p for folder in ('sessions', 'voices')
                      for p in (DATA / folder).rglob('*') if p.is_file()]
    before = {str(p.relative_to(DATA)): digest(p) for p in original_paths}
    source_folder = DATA / 'sessions' / SOURCE_ID
    source = storage.read_json(source_folder / 'project.json')
    backup = ROOT / 'backups/approved-endings-before'
    backup.mkdir(exist_ok=True)
    shutil.copytree(source_folder, backup / SOURCE_ID, dirs_exist_ok=True)
    shutil.copy2(DATA / 'draft.json', backup / 'draft.json')
    storage.atomic_json(backup / 'original-hashes.json', before)

    target_id = storage.identifier()
    target_folder = DATA / 'sessions' / target_id
    shutil.copytree(source_folder, target_folder)
    old_prefix, new_prefix = f'sessions/{SOURCE_ID}/', f'sessions/{target_id}/'

    def remap(value):
        if isinstance(value, dict):
            return {k: remap(v) for k, v in value.items()}
        if isinstance(value, list):
            return [remap(v) for v in value]
        if isinstance(value, str) and value.startswith(old_prefix):
            return new_prefix + value[len(old_prefix):]
        return value

    project = remap(source)
    project.update(id=target_id, title='Whydo flies — Energetic repaired', created=storage.now())
    context = storage.read_json(OUT / '02-03-energetic-context.json')
    themselves = next(c for c in storage.read_json(OUT / 'energetic-candidates.json')
                      if c['seed'] == 2046)
    context.update(file='02-03-energetic-context.wav', raw_file='02-03-energetic-context.raw.wav')
    archived = copy.deepcopy(project['segments'][1:3])
    joined = {'id': storage.identifier(), 'text': context['text'],
              'paragraph_end': project['segments'][2]['paragraph_end'],
              'lead_pause': project['segments'][1]['lead_pause'], 'takes': []}
    assert joined['text'] == ' '.join(s['text'] for s in archived)

    def install(segment, candidate, approved_word):
        for field in ('file', 'raw_file'):
            shutil.copy2(OUT / candidate[field], target_folder / candidate[field])
        check = copy.deepcopy(candidate['check'])
        check['heard'] = candidate['recognition']['text']
        if any(candidate['boundary'][edge] for edge in ('head_at_boundary', 'tail_at_boundary')):
            check.update(ok=False, boundary_uncertain=True)
        plan = direction.parse(segment['text'])
        storage.add_take(segment, {
            'engine': project['engine'], 'engine_config': {},
            'voice_id': project['voice_id'], 'voice_name': project['voice_name'],
            'file': new_prefix + candidate['file'],
            'raw_file': new_prefix + candidate['raw_file'],
            'seconds': sf.info(target_folder / candidate['file']).duration,
            'text': segment['text'], 'spoken': plan.spoken,
            'pauses': plan.pauses, 'overrides': plan.overrides,
            'text_hash': storage.text_fingerprint(segment['text']),
            'spoken_hash': storage.spoken_fingerprint(segment['text']),
            'seed': candidate['seed'], 'attempts': 1, 'kept_take': 1,
            'verified': check['ok'], 'check': check,
            'word_timing': candidate['recognition']['words'],
            'boundary_check': candidate['boundary'], 'verification_version': 2,
            'delivery_settings': project['settings'],
            'listening_review': {'word': approved_word, 'ending_approved_by_user': True,
                                 'scope': 'Reported word ending; not blanket approval of every phoneme.'},
        })
        segment['generation_seconds'] = candidate['elapsed']

    install(joined, context, 'together')
    install(project['segments'][3], themselves, 'themselves')
    project['segments'][1:3] = [joined]
    project['script'] = session_script(project['segments'])
    project['repair'] = {
        'source_project': SOURCE_ID, 'archived_sections': archived,
        'reason': 'User approved complete endings with original energetic settings.',
        'context_boundary': 'Original sections 2 and 3 retained as one complete recording; no internal cut.',
        'scope': 'Specific selected takes, not a universal model-generation fix.',
    }
    assert direction.spoken_text(project['script']).split() == direction.spoken_text(source['script']).split()
    planned = split_script(project['script'])
    assert len(planned) == len(project['segments']) == 7
    for expected, segment in zip(planned, project['segments']):
        assert expected['text'] == segment['text']
        assert expected.get('lead_pause') == segment.get('lead_pause')
        assert not storage.segment_needs_audio(segment)
    destination = target_folder / 'narration-repaired.wav'
    project['seconds'] = audio.join_segments(project, DATA, destination)
    project['output'] = str(destination.relative_to(DATA))
    storage.save_session(project)
    # Every retained speech sample must survive assembly; only digital padding may go.
    trim_evidence = []
    for segment in project['segments']:
        signal, rate = sf.read(DATA / segment['file'], dtype='float32')
        start, end = audio.speech_bounds(DATA / segment['file'])
        begin = max(0, start - int(rate * audio.KEEP_HEAD))
        from voice_studio.text import break_after
        finish = min(len(signal), end + int(rate * audio.KEEP_TAIL.get(break_after(segment), .06)))
        dropped = np.concatenate((signal[:begin], signal[finish:]))
        peak = float(np.max(np.abs(dropped))) if len(dropped) else 0.0
        assert peak <= audio.SILENCE
        trim_evidence.append({'section': segment['id'], 'discarded_peak': peak})
    assert all(digest(DATA / path) == value for path, value in before.items())
    shutil.copy2(destination, OUT / 'narration-repaired.wav')
    audio.export_audio(destination, OUT / 'narration-repaired.mp3')
    feedback = storage.read_json(OUT / 'listening-feedback.json')
    feedback['context_generation'] = {
        'file': context['file'], 'user_report': 'Yes: together sounds complete with the next sentence following.',
        'settings': project['settings'], 'selected_in_project': target_id,
    }
    feedback['original_energy_new_takes']['selection'] = 'Approved themselves take selected in repaired copy.'
    storage.atomic_json(OUT / 'listening-feedback.json', feedback)
    result = {'project_id': target_id, 'title': project['title'], 'output': project['output'],
              'seconds': project['seconds'], 'sections': len(project['segments']),
              'all_original_files_unchanged': True, 'checked_original_files': len(before),
              'assembly_trim': trim_evidence,
              'remaining_review': ['Merged section 2 raw onset flag', 'Section 3 recognition spelling of Flies'],
              'speech_text_and_explicit_pauses_preserved': True}
    storage.atomic_json(receipt, result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
