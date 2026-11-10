"""Voice Direction Language: a few marks you can type into a script.

The script you write and the text the model is given are not the same thing. This module
is the translation between them, and it is deliberately small: it only carries marks that
were measured to do something.

    [pause:0.5]          exactly half a second of silence, inserted by the assembler
    [say:gigahertz]      the previous word is spoken as written here, display unchanged
    {written|spoken}     the same idea inline: show the left, speak the right

Parsing is pure text work with no model involved, so it is exact and fully testable. What
each mark does to the *audio* is a separate question, answered by measurement in
``docs/VOICE-DIRECTION.md``. Marks that were measured not to work are not accepted here —
a marker that silently does nothing would be worse than no marker at all.
"""
from dataclasses import dataclass, field
import re

# A pause of 0 is pointless and a very long one is almost certainly a typo.
PAUSE_LIMITS = (0.05, 5.0)
MAX_SPOKEN_WORDS = 12          # a pronunciation override replaces one word, not a sentence

# Accepts a negative number so it can be rejected with a message rather than ignored.
PAUSE = re.compile(r'\[pause:\s*(-?[0-9]*\.?[0-9]+)\s*\]', re.I)
SAY = re.compile(r'\[say:\s*([^\]\[]{1,120}?)\s*\]', re.I)
# Empty sides are allowed through so the mistake can be reported rather than ignored.
INLINE = re.compile(r'\{([^{}|]{0,120})\|([^{}|]{0,120})\}')
# Anything in square brackets that is not a mark we support.
UNKNOWN = re.compile(r'\[([a-z][a-z0-9_]*)\s*:?[^\]\[]*\]', re.I)
KNOWN = {'pause', 'say', 'pace'}
# [pace:...] re-times one section with the app's pitch-preserving stretch. Measured at 0.93-1.07x:
# duration exact, pitch within ~0.4 semitone, periodicity and brightness unchanged. Kept modest
# on purpose; larger stretches sound processed.
PACE = re.compile(r'\[pace:\s*(slow|normal|fast)\s*\]', re.I)
PACE_FACTORS = {'slow': 0.93, 'normal': 1.0, 'fast': 1.07}
# Marks people expect that no installed engine can honour while cloning a voice. Naming them,
# with the reason, is kinder than a generic "unknown direction" and cannot be mistaken for success.
UNSUPPORTED = {
    'delivery': 'Voice Studio cannot direct delivery or emotion: on both engines the reference recording '
                'overrides instructions (tested, see the Handbook). Record the section again and pick the take you prefer.',
    'emotion': 'Voice Studio cannot direct emotion (tested, see the Handbook). Record again and pick the best take.',
    'emphasis': 'Word emphasis cannot be controlled on a cloned voice, and raising volume would not be real emphasis. '
                'Rephrase the sentence or record another take.',
    'tone': 'Tone cannot be directed on a cloned voice (tested, see the Handbook).',
    'whisper': 'Whispering cannot be directed on a cloned voice.',
    'breath': 'Breaths cannot be placed. Any breath in a recording is the engine\u2019s own and is left untouched.',
}


@dataclass
class Direction:
    """One script's worth of directions, split into what is shown and what is spoken."""
    display: str                        # exactly what the user typed
    spoken: str                         # what the engine is given
    pauses: list = field(default_factory=list)   # (character offset in spoken, seconds)
    overrides: list = field(default_factory=list)  # (written, spoken) pairs applied
    problems: list = field(default_factory=list)   # human-readable, shown in the UI
    pace: str = None                                # 'slow' | 'normal' | 'fast' | None

    @property
    def pace_factor(self):
        return PACE_FACTORS.get(self.pace, 1.0)

    @property
    def ok(self):
        return not self.problems

    @property
    def total_pause(self):
        return round(sum(seconds for _, seconds in self.pauses), 3)


def _clean_spaces(text):
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return re.sub(r' +([,.;:!?])', r'\1', text).strip()


def parse(script):
    """Turn a written script into the text to speak, plus the pauses to insert.

    Never raises: a malformed mark is reported in ``problems`` and left visible in the
    spoken text, so a typo is obvious rather than silently swallowed.
    """
    script = script or ''
    problems, overrides, pauses = [], [], []

    for match in UNKNOWN.finditer(script):
        word = match.group(1).lower()
        if word in UNSUPPORTED:
            problems.append(f'“{match.group(0)}” is not supported. ' + UNSUPPORTED[word])
        elif word not in KNOWN:
            problems.append(f'“{match.group(0)}” is not a direction Voice Studio knows. '
                            f'Supported: [pause:seconds], [pace:slow|normal|fast] and [say:word].')

    # {written|spoken} first: it is self-contained and cannot span other marks.
    def inline(match):
        written, spoken = match.group(1).strip(), match.group(2).strip()
        if not written or not spoken:
            problems.append(f'“{match.group(0)}” needs text on both sides of the bar.')
            return match.group(0)
        if len(spoken.split()) > MAX_SPOKEN_WORDS:
            problems.append(f'“{written}” is replaced by too many words to be a pronunciation.')
            return written
        overrides.append((written, spoken))
        return spoken

    working = INLINE.sub(inline, script)

    # [pace:...] describes the whole section, so it is removed wherever it stands.
    paces = [m.group(1).lower() for m in PACE.finditer(working)]
    if len(set(paces)) > 1:
        problems.append('A section can have only one [pace:] mark; found ' + ', '.join(sorted(set(paces))) + '.')
    pace = paces[0] if paces else None
    working = PACE.sub(' ', working)

    # [say:...] replaces the word immediately before it.
    def say(match):
        spoken = match.group(1).strip()
        if not spoken:
            problems.append('“[say:]” needs the pronunciation to use.')
            return match.group(0)
        if len(spoken.split()) > MAX_SPOKEN_WORDS:
            problems.append(f'“{match.group(0)}” replaces a word with too many words.')
            return ''
        return '\x00' + spoken + '\x00'

    working = SAY.sub(say, working)
    # Attach each marker to the word in front of it, which is the word being respelled.
    def attach(match):
        before, spoken = match.group(1), match.group(2)
        word = before.rstrip()
        if not word:
            problems.append(f'“[say:{spoken}]” has no word before it to respell.')
            return spoken
        lead = before[:len(before) - len(word)]
        overrides.append((word, spoken))
        return lead + spoken
    working = re.sub(r'(\S*[ \t]*)\x00([^\x00]*)\x00', attach, working)
    working = working.replace('\x00', '')

    # [pause:n] last, so its offset refers to the final spoken text.
    out, cursor = [], 0
    for match in PAUSE.finditer(working):
        seconds = float(match.group(1))
        low, high = PAUSE_LIMITS
        if not low <= seconds <= high:
            problems.append(f'“{match.group(0)}” must be between {low} and {high} seconds.')
            out.append(working[cursor:match.end()])
            cursor = match.end()
            continue
        out.append(working[cursor:match.start()])
        # Offsets refer to the cleaned spoken form, including earlier marks. A pause
        # separates words even when typed without spaces: one[pause:0.5]two.
        pauses.append((len(_clean_spaces(''.join(out))), round(seconds, 3)))
        out.append(' ')
        cursor = match.end()
    out.append(working[cursor:])
    spoken = _clean_spaces(''.join(out))

    if any(c in spoken for c in '[]{}') and not problems:
        problems.append('Unclosed or malformed direction. Use [pause:0.5], [pace:slow], '
                        'word[say:spoken], or {written|spoken}.')

    # A known word inside a marker that still did not parse is a typo, not plain text.
    for leftover in re.finditer(r'\[(pause|say|pace)\b[^\]\[]*\]', spoken, re.I):
        message = (f'“{leftover.group(0)}” could not be read. Use [pause:0.5] with a number, '
                   '[pace:slow], [pace:normal] or [pace:fast], or [say:word] after the word.')
        if message not in problems and not any(leftover.group(0) in p for p in problems):
            problems.append(message)

    if not spoken and (script.strip()):
        problems.append('This section has directions but no words to speak.')
    return Direction(display=script, spoken=spoken, pauses=pauses,
                     overrides=overrides, problems=problems, pace=pace)


def spoken_text(script):
    """Just the words the engine should say."""
    return parse(script).spoken


def has_directions(script):
    return bool(PAUSE.search(script or '') or SAY.search(script or '')
                or INLINE.search(script or '') or PACE.search(script or ''))


def describe(result):
    """A short summary for the status line."""
    bits = []
    if result.pauses:
        bits.append(f'{len(result.pauses)} pause(s), {result.total_pause:g}s total')
    if result.overrides:
        bits.append(f'{len(result.overrides)} pronunciation(s)')
    if result.pace:
        bits.append(f'pace {result.pace}')
    return ' · '.join(bits)
