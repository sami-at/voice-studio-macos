import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .config import DATA

def now():
    return datetime.now(timezone.utc).isoformat()

def identifier():
    return uuid.uuid4().hex

def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))

def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.saving-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)

def text_fingerprint(text):
    """Identify the exact words a section's audio was generated from.

    Without this, a section's text and its audio are linked only by a file path, so any
    path that restores or re-attaches a project can pair edited words with the previous
    recording, and the result assembles and plays as if it were correct.

    This legacy fingerprint includes timing for backwards compatibility. New recordings
    also store spoken_fingerprint; compatibility checks use spoken content so timing
    edits do not force regeneration. Never rewrite an old fingerprint in place.
    """
    import hashlib
    from . import direction
    result = direction.parse(text)
    pauses = ';'.join(f'{offset}:{seconds}' for offset, seconds in result.pauses)
    normalized = ' '.join(result.spoken.split()) + '\x1f' + pauses
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]

# --- takes -------------------------------------------------------------------------
# A section keeps every recording ever made for it. The fields a section has always
# carried (file, seconds, text_hash, verified, check) mirror whichever take is selected,
# so assembly, staleness and verification keep working untouched.
MIRRORED = ('file', 'seconds', 'text_hash', 'verified', 'check', 'seed', 'engine',
            'engine_config', 'attempts', 'kept_take', 'spoken_hash', 'word_timing',
            'raw_file', 'boundary_check', 'verification_version', 'quality', 'dead_air_guard_s')


def spoken_fingerprint(text):
    """Timing is assembled later; only spoken content identifies reusable audio."""
    import hashlib
    from .direction import spoken_text
    return hashlib.sha256(' '.join(spoken_text(text).split()).encode('utf-8')).hexdigest()[:16]


def ensure_takes(segment):
    """Give an older section a takes list built from the recording it already had."""
    if segment.get('takes') is None:
        segment['takes'] = []
        if segment.get('file'):
            segment['takes'].append({
                'id': identifier(), 'engine': segment.get('engine', 'qwen3'),
                'engine_config': segment.get('engine_config') or {},
                'file': segment['file'], 'seconds': segment.get('seconds'),
                'text': segment.get('text', ''),
                'text_hash': segment.get('text_hash'),
                'created': segment.get('created') or now(),
                'seed': segment.get('seed'), 'attempts': segment.get('attempts'),
                'kept_take': segment.get('kept_take'),
                'verified': segment.get('verified'), 'check': segment.get('check'),
                'voice_id': segment.get('voice_id'), 'voice_name': segment.get('voice_name'),
            })
            segment['selected_take'] = segment['takes'][0]['id']
    return segment


def takes_of(segment):
    return ensure_takes(segment).get('takes') or []


def selected_take(segment):
    chosen = segment.get('selected_take')
    return next((t for t in takes_of(segment) if t['id'] == chosen), None)


def sync_selected(segment, data=None):
    """Copy the selected take's details onto the section itself."""
    take = selected_take(segment)
    if take is None:
        for field in MIRRORED:
            segment[field] = None if field != 'engine_config' else {}
        segment['file'] = None
        return segment
    for field in MIRRORED:
        segment[field] = take.get(field)
    return segment


def add_take(segment, take):
    """Store a new recording and make it the selected one."""
    ensure_takes(segment)
    take.setdefault('id', identifier())
    take.setdefault('created', now())
    segment['takes'].append(take)
    segment['selected_take'] = take['id']
    return sync_selected(segment)


def choose_take(segment, take_id):
    """Switch to an existing recording. Never regenerates anything."""
    if not any(t['id'] == take_id for t in takes_of(segment)):
        raise ValueError('That take no longer exists for this section.')
    segment['selected_take'] = take_id
    return sync_selected(segment)


def take_is_stale(segment, take):
    """True when a take was recorded from different words than the section now holds."""
    if take.get('spoken_hash'):
        return take['spoken_hash'] != spoken_fingerprint(segment.get('text', ''))
    if take.get('spoken') and take.get('text_hash'):
        # Recorded offsets used the old parser's whitespace rules. Validate the saved
        # evidence directly rather than recomputing those offsets with a newer parser.
        import hashlib
        from .direction import spoken_text
        words = ' '.join(take['spoken'].split())
        pauses = ';'.join(f'{offset}:{seconds}' for offset, seconds in take.get('pauses', []))
        stamp = hashlib.sha256((words + '\x1f' + pauses).encode('utf-8')).hexdigest()[:16]
        if stamp == take['text_hash']:
            return words != ' '.join(spoken_text(segment.get('text', '')).split())
    # Legacy takes retain their original display text. Trust it only when its original
    # fingerprint agrees; never bless an already stale legacy recording by migration.
    if take.get('text_hash') and take.get('text') is not None:
        if take['text_hash'] == text_fingerprint(take['text']):
            return spoken_fingerprint(take['text']) != spoken_fingerprint(segment.get('text', ''))
    stamp = take.get('text_hash')
    return bool(stamp) and stamp != text_fingerprint(segment.get('text', ''))


def fresh_takes(segment):
    return [t for t in takes_of(segment) if not take_is_stale(segment, t)]


def segment_is_stale(segment):
    """True when a section's audio was made from different words than it now holds."""
    if segment.get('takes'):
        take = selected_take(segment)
        if take:
            return take_is_stale(segment, take)
    if segment.get('spoken_hash'):
        return segment['spoken_hash'] != spoken_fingerprint(segment.get('text', ''))
    stamp = segment.get('text_hash')
    return bool(stamp) and stamp != text_fingerprint(segment.get('text', ''))

def segment_needs_audio(segment, data=None):
    """A section needs generating when it has no usable, current audio."""
    data = DATA if data is None else data
    if not segment.get('file') or not (data / segment['file']).is_file():
        return True
    return segment_is_stale(segment)

def slug(text):
    return re.sub(r'[^\w-]+', '-', text, flags=re.UNICODE).strip('-_')[:64] or 'voiceover'

def read_script(path):
    raw = Path(path).read_bytes()
    if len(raw) > 5_000_000:
        raise ValueError('This script is larger than 5 MB. Import a smaller chapter.')
    encoding = 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError as exc:
        raise ValueError('Save your TXT file as UTF-8 or UTF-16, then import it again.') from exc

def has_reference(profile):
    """A profile can exist before its recording does; only then can it generate."""
    try:
        return bool(profile.get('reference')) and (DATA / profile['reference']).is_file()
    except (TypeError, OSError):
        return False

def profiles():
    """Every voice, including ones still waiting for a recording."""
    result = []
    for path in (DATA / 'voices').glob('*/profile.json'):
        try:
            item = read_json(path)
            if item and (has_reference(item) or item.get('placeholder')):
                result.append(item)
        except (ValueError, KeyError, OSError):
            continue
    # Ready voices first, then by name, so a placeholder never hides a usable one.
    return sorted(result, key=lambda p: (not has_reference(p), p.get('name', '').casefold()))

def set_default_profile(profile):
    """Mark the voice the library opens on. Only one carries the flag."""
    for item in profiles():
        wanted = item['id'] == profile['id']
        if bool(item.get('default')) != wanted:
            item['default'] = wanted
            save_profile(item)
    profile['default'] = True
    return profile


def default_profile_id():
    return next((p['id'] for p in profiles() if p.get('default')), None)


def rename_profile(profile, name):
    name = name.strip()
    if not name:
        raise ValueError('Give this voice a name.')
    if len(name) > 80:
        raise ValueError('Keep the voice name under 80 characters.')
    profile['name'] = name
    save_profile(profile)
    return profile

def delete_profile(profile):
    """Remove one voice and its recordings. Narrations already generated keep their audio."""
    import shutil
    folder = DATA / 'voices' / profile['id']
    if folder.is_dir():
        shutil.rmtree(folder)

def save_profile(profile):
    profile['updated'] = now()
    atomic_json(DATA / 'voices' / profile['id'] / 'profile.json', profile)

def session_path(session):
    return DATA / 'sessions' / session['id'] / 'project.json'

def save_session(session):
    session['updated'] = now()
    atomic_json(session_path(session), session)

def sessions():
    result = []
    for path in (DATA / 'sessions').glob('*/project.json'):
        try:
            item = read_json(path)
            if item:
                result.append(item)
        except (ValueError, OSError):
            continue
    return sorted(result, key=lambda s: s.get('updated', ''), reverse=True)
