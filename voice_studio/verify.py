"""Check that generated speech actually contains the words it was asked to say.

Speech recognition is imperfect, so a plain string comparison would reject good audio:
measured on this machine, the model says "there's" where the script reads "there is", and
the transcriber writes "blink's" for "blinks". Both are correct speech. Everything here is
built to ignore that class of difference and still catch a genuinely missing phrase.

No new dependencies: normalisation and sequence matching only.
"""
from difflib import SequenceMatcher
import re

# Judged against 84 measured generations; see docs/TEST_RESULTS.md.
SIMILARITY_FLOOR = 0.82      # whole-section word-sequence agreement
COVERAGE_FLOOR = 0.90        # fraction of expected words that turn up
EDGE_SLACK = 0               # edge disagreement needs review, even for one word

CONTRACTIONS = {
    "aren't": 'are not', "can't": 'can not', "cannot": 'can not', "couldn't": 'could not',
    "didn't": 'did not', "doesn't": 'does not', "don't": 'do not', "hadn't": 'had not',
    "hasn't": 'has not', "haven't": 'have not', "he'd": 'he would', "he'll": 'he will',
    "he's": 'he is', "here's": 'here is', "i'd": 'i would', "i'll": 'i will', "i'm": 'i am',
    "i've": 'i have', "isn't": 'is not', "it'll": 'it will', "it's": 'it is',
    "let's": 'let us', "she'd": 'she would', "she'll": 'she will', "she's": 'she is',
    "shouldn't": 'should not', "that's": 'that is', "there's": 'there is',
    "they'd": 'they would', "they'll": 'they will', "they're": 'they are',
    "they've": 'they have', "wasn't": 'was not', "we'd": 'we would', "we'll": 'we will',
    "we're": 'we are', "we've": 'we have', "weren't": 'were not', "what's": 'what is',
    "won't": 'will not', "wouldn't": 'would not', "you'd": 'you would', "you'll": 'you will',
    "you're": 'you are', "you've": 'you have',
}

NUMBERS = {
    '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four', '5': 'five', '6': 'six',
    '7': 'seven', '8': 'eight', '9': 'nine', '10': 'ten', '11': 'eleven', '12': 'twelve',
    '13': 'thirteen', '14': 'fourteen', '15': 'fifteen', '16': 'sixteen', '17': 'seventeen',
    '18': 'eighteen', '19': 'nineteen', '20': 'twenty', '30': 'thirty', '40': 'forty',
    '50': 'fifty', '60': 'sixty', '70': 'seventy', '80': 'eighty', '90': 'ninety',
    '100': 'hundred', '1000': 'thousand',
}


def normalize(text):
    """Lowercase words, contractions expanded and digits spelled, punctuation dropped."""
    text = (text or '').lower()
    text = text.replace('’', "'").replace('‘', "'")
    text = re.sub(r'[–—-]', ' ', text)
    words = []
    for token in re.findall(r"[^\W_]+(?:'[^\W_]+)?", text, flags=re.UNICODE):
        expanded = CONTRACTIONS.get(token)
        if expanded:
            words.extend(expanded.split())
            continue
        # "blink's" for "blinks" is a transcriber habit, not a different word.
        token = token.replace("'", '')
        words.append(NUMBERS.get(token, token))
    return words


def _unmatched_edges(expected, opcodes):
    """How many expected words go unmatched at the very start and the very end.

    Alignment position, not membership: a dropped "the day" would otherwise look present
    because some other "the" survives elsewhere in the sentence.
    """
    leading = 0
    for tag, i1, i2, _, _ in opcodes:
        if tag == 'equal':
            break
        leading += i2 - i1
    trailing = 0
    for tag, i1, i2, _, _ in reversed(opcodes):
        if tag == 'equal':
            break
        trailing += i2 - i1
    # A section matched nowhere must not report its gap twice.
    if leading >= len(expected) or trailing >= len(expected):
        return len(expected), len(expected)
    return leading, trailing


def compare(expected_text, heard_text):
    """Measure how completely heard_text covers expected_text."""
    expected, heard = normalize(expected_text), normalize(heard_text)
    if not expected:
        return {'ok': True, 'similarity': 1.0, 'coverage': 1.0, 'head_ok': True,
                'tail_ok': True, 'expected_words': 0, 'heard_words': len(heard), 'missing': []}
    matcher = SequenceMatcher(None, expected, heard, autojunk=False)
    similarity = matcher.ratio()
    matched = sum(block.size for block in matcher.get_matching_blocks())
    coverage = matched / len(expected)
    opcodes = matcher.get_opcodes()
    leading, trailing = _unmatched_edges(expected, opcodes)
    head_ok, tail_ok = leading <= EDGE_SLACK, trailing <= EDGE_SLACK
    missing = []
    for tag, i1, i2, _, _ in opcodes:
        if tag in ('delete', 'replace'):
            missing.extend(expected[i1:i2])
    return {
        'ok': bool(similarity >= SIMILARITY_FLOOR and coverage >= COVERAGE_FLOOR
                   and head_ok and tail_ok),
        'similarity': round(similarity, 4), 'coverage': round(coverage, 4),
        'head_ok': head_ok, 'tail_ok': tail_ok,
        'missing_at_start': leading, 'missing_at_end': trailing,
        'expected_words': len(expected), 'heard_words': len(heard),
        'missing': missing[:12],
    }


def candidate_rank(check):
    """A passing check wins over higher coverage with a failed edge or repetition."""
    if check is None:
        return (-1, 0, 0, 0)
    # Among takes that all failed, a word check that passed with a less abrupt ending is preferred.
    return (int(bool(check.get('ok'))), check.get('coverage', 0), check.get('similarity', 0),
            -float(check.get('cliff_db') or 0))


def describe(result, index):
    """A short, human explanation of why a section was rejected.

    Tolerates a trimmed-down result, since a stored check keeps only some of the fields.
    """
    if not result or result.get('ok', True):
        return ''
    reasons = []
    if 'cut_ending' in (result.get('abrupt') or []):
        reasons.append('the last word stops dead, so its final sound is probably incomplete')
    if [c for c in (result.get('abrupt') or []) if c != 'cut_ending']:
        reasons.append('the engine\u2019s sound ' + ' and '.join(
            'stops' if c == 'abrupt_end' else 'starts' for c in result['abrupt'] if c != 'cut_ending')
            + ' at near full level, so the ' + ('ending' if 'abrupt_end' in result['abrupt'] else 'opening')
            + ' may be cut off')
    if not result.get('abrupt') and result.get('boundary_uncertain'):
        reasons.append('the raw audio reaches a file boundary; listen for a cut attack or release')
    if not result.get('head_ok', True):
        reasons.append('the opening words were not confirmed by recognition')
    if not result.get('tail_ok', True):
        reasons.append('the closing words were not confirmed by recognition')
    coverage, similarity = result.get('coverage'), result.get('similarity')
    if coverage is not None and coverage < COVERAGE_FLOOR:
        reasons.append(f'only {coverage * 100:.0f}% of the words were heard')
    elif similarity is not None and similarity < SIMILARITY_FLOOR:
        reasons.append(f'the wording drifted ({similarity * 100:.0f}% match)')
    detail = ' and '.join(reasons) or 'it did not match the script'
    missing = ', '.join(result.get('missing') or [])
    return f"Section {index + 1}: {detail}." + (f' Unconfirmed: {missing}.' if missing else '')
