"""Mood references: one recording per delivery, chosen per section.

Reference cloning copies the delivery of its sample (docs/EXPRESSIVE-RESEARCH.md): a sad
sample gives sad narration far more reliably than any instruction. So a voice may carry
several short clips of the same speaker in different moods, and each section is generated
from the one that suits its words. Nothing here changes the engine or the words it speaks.

A section's mood is either a name from the voice's clips or AUTO, which reads the section's
text with plain word cues below. Those cues are a guess the user can override per section;
they never block generation, and an unrecognised mood falls back to the main reference.
"""
import re

AUTO = 'auto'
NEUTRAL = 'neutral'

# Display order and labels. A voice need not have every mood.
LABELS = {
    'neutral': 'Neutral',
    'excited': 'Excited',
    'sad': 'Sad',
    'angry': 'Angry',
    'scared': 'Scared / whisper',
    'playful': 'Playful / sarcastic',
    'warm': 'Warm / grateful',
    'calm': 'Calm / reflective',
}
ORDER = tuple(LABELS)

# Whole-word or whole-phrase cues. Each match scores one point for its mood.
CUES = {
    'angry': ('absolutely not', 'how dare', 'ridiculous', 'furious', 'unacceptable', 'hate',
              'enough', 'shut up', 'liar', 'outrageous', 'owes me', 'sick of', 'fed up',
              'angry', 'unbelievable', 'you promised', 'get out', 'damn'),
    'sad': ('sorry', 'miss you', 'gone', 'lost', 'alone', 'tears', 'cry', 'cried', 'goodbye',
            'regret', 'never again', 'broken', 'grief', 'died', 'death', 'lonely', 'sad',
            'empty', 'hurt', 'heartbroken', 'cancelled', 'canceled', 'why does this always'),
    'scared': ('shh', 'shhh', 'scared', 'afraid', 'fear', 'terrified', 'shaking', 'something moved',
               'hide', 'whisper', 'whispered', 'creaked', 'did you hear that', 'help me',
               'nervous', 'trembling', 'run'),
    'excited': ('amazing', 'incredible', 'awesome', 'no way', 'we did it', 'i did it', 'got in',
                "can't believe", 'cannot believe', 'celebrate', 'we won', 'yes', 'woohoo', 'yay'),
    'playful': ('brilliant plan', 'genius', 'yeah right', 'oh great', 'oh sure', 'what could possibly go wrong',
                'obviously', 'totally', 'nice job', 'real smooth'),
    'warm': ('thank you', 'thanks', 'grateful', 'love', 'beautiful', 'dear', 'proud',
             'means a lot', 'bless', 'goodness', 'kind'),
    'calm': ('i guess', 'after all', 'peace', 'gently', 'softly', 'breathe', 'calm',
             'quietly', 'in the end', 'looking back'),
}
_PATTERNS = {mood: [re.compile(r"(?<![\w'])" + re.escape(cue) + r"(?![\w'])") for cue in cues]
             for mood, cues in CUES.items()}


def label(mood):
    return 'Auto (from text)' if mood in (None, AUTO) else LABELS.get(mood, mood.title())


def detect(text, available=None):
    """The mood a section's words suggest, limited to the moods a voice has.

    Returns NEUTRAL when nothing stands out. Exclamation marks lean a line towards excitement
    unless its words are angry; a question alone stays neutral."""
    from .direction import spoken_text
    words = ' '.join(spoken_text(text).lower().replace('’', "'").split())
    scores = {mood: sum(len(p.findall(words)) for p in patterns) for mood, patterns in _PATTERNS.items()}
    shouts = words.count('!')
    if shouts:
        scores['angry' if scores['angry'] else 'excited'] += min(shouts, 2) * 0.5
    if available is not None:
        scores = {m: s for m, s in scores.items() if m in available}
    best = max(scores.items(), key=lambda item: (item[1], -ORDER.index(item[0])), default=(NEUTRAL, 0))
    return best[0] if best[1] > 0 else NEUTRAL


def names(holder):
    """Mood names a profile or session carries, in display order."""
    have = {m['mood'] for m in (holder or {}).get('moods') or []}
    return [m for m in ORDER if m in have] + sorted(have - set(ORDER))


def resolve(session, segment):
    """(mood, reference, transcript) a section is generated from.

    The reference is relative to DATA. With no mood clips, or none matching, the voice's
    main reference is used and the mood is reported as None."""
    clips = {m['mood']: m for m in session.get('moods') or []}
    wanted = segment.get('mood') or AUTO
    if wanted == AUTO and clips:
        wanted = detect(segment.get('text', ''), clips)
    clip = clips.get(wanted)
    if clip is None:
        return None, session['reference'], session['transcript']
    return wanted, clip['reference'], clip['transcript']
