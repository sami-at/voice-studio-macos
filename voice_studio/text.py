"""Punctuation-aware bounded segmentation, with explicit paragraph pauses."""
import re
from . import direction, engines, styles
from .storage import identifier, now

def split_script(text, limit=260):
    if limit < 40:
        raise ValueError('The section limit must be at least 40 characters.')
    text = text.replace('\r\n', '\n').strip()
    # A timing line is a boundary even without blank lines around it.
    text = re.sub(r'(?m)^[ \t]*((?:\[pause:[^\]\n]*\][ \t]*)+)$', r'\n\n\1\n\n', text)
    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    # A paragraph holding only direction markers is timing, not speech. It becomes a pause
    # on the boundary between the sections around it rather than an empty section of its
    # own, which the engine cannot speak. Consecutive markers add up.
    pending = 0.0
    for paragraph in paragraphs:
        paragraph = re.sub(r'\s+', ' ', paragraph).strip()
        if not paragraph:
            continue
        timing = direction.parse(paragraph)
        errors = [p for p in timing.problems if p != 'This section has directions but no words to speak.']
        if errors:
            raise ValueError(' '.join(errors))
        if not timing.spoken.strip():
            pending = round(pending + timing.total_pause, 3)
            continue
        before = len(chunks)
        # Mask punctuation and whitespace inside directions while retaining offsets.
        masked = re.sub(r'\[[^\]]*\]|\{[^}]*\}', lambda m: '_' * len(m[0]), paragraph)
        masked = re.sub(r'\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|vs)\.',
                        lambda m: m[0][:-1] + '_', masked, flags=re.I)
        sentences = [paragraph[m.start():m.end()] for m in
                     re.finditer(r'.+?(?:[.!?。！？]+[”’\"\']*(?=\s|$)|$)', masked)]
        current = ''
        for sentence in sentences:
            sentence = sentence.strip()
            while sentence:
                room = limit - len(current) - bool(current)
                if len(sentence) <= room:
                    current += (' ' if current else '') + sentence
                    break
                if current:
                    chunks.append({'text': current, 'paragraph_end': False})
                    current = ''
                    continue
                masked_sentence = re.sub(r'\[[^\]]*\]|\{[^}]*\}',
                                         lambda m: '_' * len(m[0]), sentence)
                candidates = [m.end() for m in re.finditer(r'[,;:，；：]\s*', masked_sentence[:limit + 1])
                              if limit // 2 <= m.end() <= limit]
                boundary = candidates[-1] if candidates else masked_sentence.rfind(' ', 0, limit + 1)
                boundary = boundary if boundary > 0 else limit
                if not candidates:
                    # Avoid leaving an article/preposition/conjunction stranded at a
                    # hard length boundary. The size limit remains bounded.
                    attached = {'a', 'an', 'the', 'to', 'of', 'in', 'on', 'with', 'by',
                                'for', 'from', 'and', 'or', 'but'}
                    while boundary > limit // 2:
                        prefix = sentence[:boundary].rstrip()
                        last = re.search(r'\b(\w+)$', prefix)
                        if not last or last[1].lower() not in attached:
                            break
                        earlier = masked_sentence.rfind(' ', 0, last.start())
                        if earlier <= limit // 2:
                            break
                        boundary = earlier
                # A single long direction is indivisible; never send a broken marker.
                for mark in re.finditer(r'\S*\[[^\]]*\]|\{[^}]*\}', sentence):
                    if mark.start() < boundary < mark.end():
                        boundary = mark.start() if mark.start() > 0 else mark.end()
                chunks.append({'text': sentence[:boundary].strip(), 'paragraph_end': False})
                sentence = sentence[boundary:].strip()
        if current:
            chunks.append({'text': current, 'paragraph_end': True})
        elif chunks:
            chunks[-1]['paragraph_end'] = True
        if pending and len(chunks) > before:
            # The pause belongs before the first section of this paragraph.
            chunks[before]['lead_pause'] = pending
            pending = 0.0
    if pending and chunks:
        # Markers after the last words: the narration waits before it ends.
        chunks[-1]['trail_pause'] = pending
    return chunks

# How a section ends decides how long the narration should wait before the next one.
SENTENCE_END = ('.', '!', '?', '…')
CLAUSE_END = (',', ';', ':', '—')


def break_after(segment):
    """Classify the join after a section: paragraph, sentence, clause or mid-sentence.

    Read from the words themselves rather than a stored field, so narrations saved before
    this existed are phrased correctly too.
    """
    if segment.get('paragraph_end'):
        return 'paragraph'
    text = direction.spoken_text(segment.get('text') or '').rstrip().rstrip('”’"\'')
    if text.endswith(SENTENCE_END):
        return 'sentence'
    if text.endswith(CLAUSE_END):
        return 'clause'
    return 'mid'


def session_script(segments):
    """Rebuild an edited script without losing its standalone timing metadata."""
    out = ''
    for i, seg in enumerate(segments):
        if seg.get('lead_pause'):
            out = out.rstrip() + f"\n\n[pause:{seg['lead_pause']:g}]\n\n"
        out += seg['text']
        if seg.get('trail_pause'):
            out += f"\n\n[pause:{seg['trail_pause']:g}]"
        out += '\n\n' if seg.get('paragraph_end') else ' '
    return out.strip()


def new_session(script, title, profile, style=None, overrides=None, language='English',
                engine=None):
    """A narration is pinned to the voice and the style values it was generated with."""
    style = style or styles.NATURAL
    values = styles.settings(style, overrides)
    return {
        'id': identifier(), 'title': title.strip() or 'Untitled narration', 'created': now(),
        'script': script, 'voice_id': profile['id'], 'voice_name': profile['name'],
        'reference': profile['reference'], 'transcript': profile['transcript'],
        # Mood clips of the same voice; each section picks one (voice_studio/moods.py).
        'moods': [dict(m) for m in profile.get('moods') or []],
        'language': language, 'output': None,
        'style': style, 'settings': values,
        # The engine a section falls back to when it has not chosen its own.
        'engine': engines.normalize(engine),
        # Kept alongside the style so older code paths and saved projects still read.
        'speed': values['speed'], 'pause': values['pause'],
        'sentence_pause': values['sentence_pause'],
        'segments': [{'id': identifier(), 'file': None, 'seed': 42 + i, **chunk}
                     for i, chunk in enumerate(split_script(script))],
    }
