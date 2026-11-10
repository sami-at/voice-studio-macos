"""Narration styles.

Every value here was chosen from measurements on this machine, not from guesswork.
What the Qwen3-TTS base model exposes in reference-cloning (ICL) mode was tested one
knob at a time, three seeds per setting, on identical text:

* temperature, top_p, top_k and repetition_penalty change *which take* you get. They
  do not steer pace, pitch range or loudness: across 0.3-1.1 temperature the measured
  differences were smaller than the seed-to-seed spread at a fixed setting.
* the model's own ``speed`` argument and ``instruct`` prompt are not forwarded at all
  on the cloning path, so they do nothing here.
* the **tempo of the reference recording** does steer delivery, but only upwards.
  Conditioning on a reference stretched to 1.15x raised the generated rate from 3.05 to
  3.37 words per second, with every fast-reference take faster than every other take.
  Slowing the reference to 0.88x changed nothing (3.04), so slower styles are paced by
  the post-generation stretch, which is exact.

So a style is built from the three things that genuinely work: how the reference is
conditioned, a pitch-preserving stretch of the result, and the silence between parts.
See ``docs/TEST_RESULTS.md`` for the measurements.
"""

NATURAL = 'Natural'
ENERGETIC = 'Energetic Explainer'
DOCUMENTARY = 'Documentary'
STORYTELLING = 'Storytelling'
CUSTOM = 'Custom'
ORDER = [NATURAL, ENERGETIC, DOCUMENTARY, STORYTELLING, CUSTOM]

# Bounds are the range each control is usable over; the UI and worker both clamp here.
LIMITS = {
    'reference_tempo': (0.85, 1.25),
    'speed': (0.75, 1.25),
    'pause': (0.05, 1.50),
    'sentence_pause': (0.00, 0.80),
}

# Style gaps are targets after near-digital padding removal. Quiet speech and natural
# decay take priority over gap precision. Explicit VDL pauses are inserted PCM silence.
PRESETS = {
    NATURAL: {
        'reference_tempo': 1.00, 'speed': 1.00, 'pause': 0.50, 'sentence_pause': 0.28,
        'summary': 'The reference recording’s own pacing, with even pauses.',
    },
    ENERGETIC: {
        'reference_tempo': 1.15, 'speed': 1.04, 'pause': 0.34, 'sentence_pause': 0.18,
        'summary': 'Quick and clear for short explainers: the model is conditioned to speak '
                   'faster, then nudged a little further, with tight pauses between ideas.',
    },
    # Conditioning on a *slowed* reference was measured to do nothing (3.04 vs 3.05 words a
    # second), so the slower styles get their pace from the exact post-generation stretch.
    DOCUMENTARY: {
        'reference_tempo': 1.00, 'speed': 0.94, 'pause': 0.70, 'sentence_pause': 0.38,
        'summary': 'Measured and deliberate, with room to let a statement land.',
    },
    STORYTELLING: {
        'reference_tempo': 1.00, 'speed': 0.96, 'pause': 0.75, 'sentence_pause': 0.40,
        'summary': 'Unhurried, with long breaths between paragraphs.',
    },
    CUSTOM: {
        'reference_tempo': 1.00, 'speed': 1.00, 'pause': 0.50, 'sentence_pause': 0.28,
        'summary': 'Your own combination of the controls below.',
    },
}

# A section cut mid-sentence must flow on, while a full stop deserves room. These scale the
# sentence pause rather than adding controls that would not earn their place in the window.
BREAK_SCALE = {'paragraph': None, 'sentence': 1.0, 'clause': 0.45, 'mid': 0.18}
# Room left before the first word and after the last, so a narration ends instead of stopping.
LEAD_IN = 0.08
TAIL_ROOM = 0.32


# Engine-specific adjustments to a style, chosen by listening (docs/CHATTERBOX-PACING.md, 25 Oct 2026).
# Chatterbox speaks about 9 % slower than Qwen3 and ends every take with 0.3-0.5 s of near-silence (~-90 dB)
# after its audible decay. For Energetic Explainer it now gets 1.10x on top of the style's speed, and that
# dead air is trimmed at assembly, keeping the decay plus `dead_air_guard_s`. Only NEW takes are affected:
# the values are stored on each take, so existing takes keep their timing. Empty this dict to revert.
ENGINE_TUNING = {
    ('chatterbox', ENERGETIC): {'speed_factor': 1.10, 'dead_air_guard_s': 0.12},
}


def engine_tuning(engine, style):
    """The adjustment for this engine in this named style, or none. Custom settings are never adjusted."""
    return ENGINE_TUNING.get((engine, style), {})


def gap_after(kind, values):
    """Seconds of silence to place after a section that ends with this kind of break."""
    if kind == 'paragraph':
        return max(0.0, values['pause'])
    return max(0.0, values['sentence_pause'] * BREAK_SCALE.get(kind, 1.0))

# Fixed for every style: measured to have no reliable effect on delivery, so they are
# not offered as style controls. They stay at the values the engine was validated with.
SAMPLING = {'temperature': 0.7, 'top_p': 0.9, 'top_k': 50, 'repetition_penalty': 1.05}

CONTROLS = ('reference_tempo', 'speed', 'pause', 'sentence_pause')


def clamp(name, value):
    low, high = LIMITS[name]
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = PRESETS[NATURAL][name]
    return round(min(high, max(low, value)), 3)


def settings(style, overrides=None):
    """Resolve a style name plus optional overrides into concrete, clamped values."""
    base = PRESETS.get(style, PRESETS[NATURAL])
    resolved = {name: clamp(name, base[name]) for name in CONTROLS}
    for name, value in (overrides or {}).items():
        if name in CONTROLS:
            resolved[name] = clamp(name, value)
    return resolved


def summary(style):
    return PRESETS.get(style, PRESETS[NATURAL])['summary']


def matches(style, values):
    """True when values are still exactly the preset, so the UI knows to stay on it."""
    if style not in PRESETS or style == CUSTOM:
        return False
    preset = settings(style)
    return all(abs(preset[name] - clamp(name, values.get(name, preset[name]))) < 1e-6
               for name in CONTROLS)
