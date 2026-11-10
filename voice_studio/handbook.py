"""The Voice Direction Handbook, built into the app.

Every claim here comes from a measurement on this Mac, recorded in
``docs/VOICE-DIRECTION.md``. Where a mark does nothing useful it is listed under
*Not supported* rather than left out, because the likeliest reason to look it up is
having just tried it.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)


class WrappedLabel(QLabel):
    """A word-wrapped label whose height is set by its owner from the width it will really get.

    A scroll area lays its page out from minimum sizes and ignores height-for-width, so a plain
    wrapped QLabel is given one line and the next card is drawn over the rest. The Handbook
    calls ``Handbook.fit_labels`` on render and on every resize to give each one its true height.
    """

    def __init__(self, text=''):
        super().__init__(text)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


def wrapped(text, style=None):
    item = WrappedLabel(text)
    if style:
        item.setObjectName(style)
    item.setFixedHeight(item.fontMetrics().height())
    return item

from .widgets import STYLE, label

RELIABLE, PARTIAL, UNSUPPORTED = 'reliable', 'partial', 'unsupported'
BADGE = {RELIABLE: ('Reliable', '#8fdcbe', '#1d3129'),
         PARTIAL: ('Varies by engine', '#d8c79a', '#3a3324'),
         UNSUPPORTED: ('Not supported', '#d8a2a2', '#3a2626')}


def entry(sign, purpose, example, effect, support, engines, limits=''):
    return {'sign': sign, 'purpose': purpose, 'example': example, 'effect': effect,
            'support': support, 'engines': engines, 'limits': limits}


CHAPTERS = [
 ('Basic punctuation',
  'Write normally. Punctuation is passed to the engine untouched, and both engines do '
  'lengthen the gap at a mark — but by how much is only loosely under your control. '
  'Measured over three takes per mark on one sentence:',
  [entry(',', 'Separates parts of a sentence.', 'They are not plotting, they are cleaning.',
         'Longest gap averaged 0.35 s on Qwen3 and 0.39 s on Chatterbox.',
         PARTIAL, 'Both',
         'On Qwen3 a comma reliably produced a longer gap than a full stop (0.29–0.44 s '
         'against 0.22–0.23 s), which is the opposite of what most people expect.'),
   entry('.', 'Ends a sentence.', 'The mystery is over.',
         'The steadiest mark on Qwen3: 0.215–0.232 s across three takes.',
         PARTIAL, 'Both', 'On Chatterbox the same mark ranged 0.15–0.40 s.'),
   entry(';  :', 'Joins closely related statements.', 'It is simple; nobody expected it.',
         'Qwen3 treats them much like a full stop (0.22 s and 0.23 s).',
         PARTIAL, 'Both',
         'Chatterbox produced byte-identical audio for “;” and “…”, and for “:” and “,”, '
         'so it appears to fold them together before speaking.'),
   entry('—', 'A sharp aside or interruption.', 'The answer — nobody expected it — was simple.',
         'Slightly longer gaps and a slightly longer line on both engines.',
         PARTIAL, 'Both', 'Overlaps with the other marks take to take.')]),

 ('Questions and exclamations',
  'These change where the pause falls, but not the tune of the sentence.',
  [entry('?', 'Marks a question.', 'Have you ever wondered why flies rub their hands?',
         'Gap averaged 0.31 s on Qwen3, 0.35 s on Chatterbox.',
         PARTIAL, 'Both',
         'It does NOT produce a rising, curious inflection. Measured across five seeds and '
         'two voices, the final pitch moved in opposite directions for different voices, '
         'and the take-to-take spread was larger than any difference between “?” and “.”.'),
   entry('!', 'Marks emphasis or surprise.', 'And it worked!',
         'Shortest gap of all the marks on Qwen3 (0.13–0.21 s).',
         PARTIAL, 'Both',
         'No measurable excitement. On Chatterbox one take of three dropped a word, so check '
         'the result when you use it.'),
   entry('?!', 'Surprise and question together.', 'You did what?!',
         'Longest gap on Chatterbox (0.42 s).', PARTIAL, 'Both',
         'Still no change in intonation.')]),

 ('Suspense and dramatic pauses',
  'For a deliberate beat, do not rely on punctuation. Ask for the silence you want.',
  [entry('...', 'Suggests trailing off.', 'But wait... there is a reason.',
         'On Qwen3 it gave no more pause than a full stop (0.22 s).',
         PARTIAL, 'Both',
         'If you want an audible beat, write [pause:0.6] instead. The ellipsis is kept in the '
         'text, so the engine still sees it.'),
   entry('[pause:0.6]', 'A real, measured beat before a reveal.',
         'But wait[pause:0.6] there is a reason.',
         'Exactly 0.6 s of digital silence is inserted; the audible gap also includes natural quiet.',
         RELIABLE, 'Both', 'Inline placement needs offline word alignment and a quiet interval. If uncertain, put the marker between paragraphs.'),
   entry('[pause:0.4] on its own line', 'A beat between two paragraphs.',
         'Have you ever wondered why flies do that?\n\n[pause:0.4]\n\n'
         'Here is the explanation.',
         'The marker is a boundary, not a section — nothing is recorded for it. The pause '
         'replaces the style’s paragraph gap. Retained natural quiet may make the audible gap longer.',
         RELIABLE, 'Both',
         'Markers on consecutive lines add up. One before the first words lengthens the '
         'opening; one after the last lengthens the ending. Changing only the timing keeps '
         'your existing takes.')]),

 ('Exact pause controls',
  'The inserted digital silence is exact to the nearest sample. The acoustic gap is not: it also includes natural quiet. Voice Studio inserts silence when it '
  'assembles the narration, so it does not depend on the engine.',
  [entry('[pause:0.5]', 'Insert exactly half a second of silence.',
         'The mystery is over[pause:0.5] or is it?',
         'Offline word alignment locates the boundary, then a quiet interval is required. Natural silence '
         'is preserved in addition to the requested inserted silence. No words are overlapped or removed.',
         RELIABLE, 'Both',
         'Between 0.05 and 5 seconds. Outside that range the marker is refused and reported '
         'rather than guessed at. Explicit boundary pauses replace the style gap. If alignment is uncertain, assembly reports it instead of guessing.')]),

 ('Speaking pace',
  'One mark re-times a single section. It uses the same pitch-preserving stretch as the Final speed '
  'control, limited to a modest range because larger stretches sound processed. Measured at 0.93x '
  'and 1.07x on three takes: duration changes by exactly the amount asked, pitch stays within about '
  'half a semitone, and brightness within about 6 %. Whether a slower or faster section sounds '
  'better is for your ears; use Play take to compare it with the earlier one.',
  [entry('[pace:slow]', 'Slow one section about 7 %, for a reveal or an important explanation.',
         'The answer is hidden on their feet. [pace:slow]',
         'The section is re-timed from its saved raw recording to 1.075x as long. The voice, '
         'words and pronunciation are the same recording, stretched.',
         RELIABLE, 'Both',
         'Applies to the whole section the mark is in. A paragraph under 260 characters is one section. '
         'It re-times; it does not make the delivery more expressive. The earlier take stays in the list.'),
   entry('[pace:fast]', 'Speed one section up about 7 %, for an aside.',
         'But that is a story for another day. [pace:fast]',
         'The section is re-timed to about 0.93x as long.',
         RELIABLE, 'Both',
         'Stacks with the style\u2019s Final speed, so Energetic Explainer plus fast is about 1.11x.'),
   entry('[pace:normal]', 'Return one section to the style\u2019s own speed.',
         'Back to the main point. [pace:normal]',
         'No extra stretch. Useful to undo slow or fast without deleting the mark\u2019s place.',
         RELIABLE, 'Both'),
   entry('Changing a pace mark', 'Edit, add or remove a [pace:] mark on a recorded section.',
         'Add [pace:slow] to a finished section, then press Generate.',
         'No model runs. The section is re-processed from its saved raw recording as a NEW take; '
         'the earlier take is kept and can be selected again.',
         RELIABLE, 'Both',
         'Takes recorded before this feature may not have a saved raw recording; you are told to '
         'record those again.'),
  ]),
 ('Pronunciation overrides',
  'When a word is read wrongly, give the engine a spelling it can say. Your script keeps '
  'the real word; only the engine sees the replacement.',
  [entry('{written|spoken}', 'Show one thing, say another.',
         'The {gigahertz|giga hertz} chip is fast.',
         'The script still reads “gigahertz”; the engine is given “giga hertz”.',
         RELIABLE, 'Both', 'Only this occurrence changes — the same word elsewhere is left alone.'),
   entry('[say:new clee eye]', 'Respell the word just before the marker.',
         'He studied the nuclei[say:new clee eye] closely.',
         'The engine is given “new clee eye” in place of “nuclei”.',
         RELIABLE, 'Both',
         'Replaces one word with up to twelve. Put it straight after the word, no space.')]),

 ('Experimental emphasis and delivery',
  'Tested, and not working. These are listed so you know what happened if you try them.',
  [entry('*important*', 'Intended to stress a word.',
         'You have *absolutely no idea* why you are there.',
         'The asterisks are not spoken aloud, but they do not create emphasis either. They '
         'change the take the way a different seed does.',
         UNSUPPORTED, 'Neither',
         'Not implemented as a feature. Voice Studio will not add loudness or pitch to fake '
         'it, because that sounds artificial rather than emphatic.'),
   entry('CAPITALS', 'Intended to stress a word.', 'You have ABSOLUTELY no idea.',
         'Same as asterisks: the audio changes, the emphasis does not.',
         UNSUPPORTED, 'Neither',
         'On Chatterbox both capitals and asterisks produced a word substitution in testing '
         '(“are” heard as “were”), so they carry a small risk.'),
   entry('[curious] [excited]', 'Intended to direct the delivery.',
         '[curious] Have you ever wondered why?',
         'Not accepted. Unknown markers are reported and left visible so the mistake is plain.',
         UNSUPPORTED, 'Neither',
         'No local engine tested takes delivery direction while cloning a voice. The character '
         'of the narration comes from the reference recording.'),
   entry('[delivery:curious]  [emotion:happy]', 'Intended to direct how a section is performed.',
         '[delivery:curious] Have you ever wondered why?',
         'Refused with an explanation, and left visible in the text. Nothing is silently ignored.',
         UNSUPPORTED, 'Neither',
         'Measured on this Mac. Instructions such as curious, surprised, confident and playful moved pitch '
         'range by less than the take-to-take spread, and the cloned voice\u2019s own reference '
         'overrides them. Choosing a different reference clip did not steer delivery either: with five '
         'seeds per setting, a question-style clip did not raise pitch or widen pitch range on a question '
         '(+1.4 Hz, well inside seed noise). The practical control is to record a section again and pick the '
         'take you prefer.'),
   entry('[emphasis:taste]', 'Intended to stress one word.', 'They can [emphasis:taste] your food.',
         'Refused with an explanation. No word-level control exists in either engine.',
         UNSUPPORTED, 'Neither',
         'Raising the volume of a word is not emphasis and Voice Studio will not fake it. Rephrase so the '
         'important word falls where a speaker would stress it, or record another take.'),
   entry('Context between sections', 'Making a section sound as if it follows the one before.', '(no mark)',
         'Neither engine accepts previous text. The only way to carry context is to use the previous '
         'recording as the reference.',
         UNSUPPORTED, 'Neither',
         'Tested: chaining each sentence on the one before did smooth pitch between sentences (spread of '
         'per-sentence pitch roughly halved), but every step made the voice duller (brightness fell 10 to '
         '25 % per step), drifting away from the cloned voice. Not offered.')]),

 ('Common mistakes',
  'The parser reports these rather than quietly doing nothing.',
  [entry('[pause:2 seconds]', 'A pause with words in it.', 'Wait[pause:2 seconds] now.',
         'Refused: “could not be read”. Write [pause:2].', UNSUPPORTED, '—'),
   entry('[pause:0]  [pause:99]', 'Out of range.', 'Wait[pause:99] now.',
         'Refused with the allowed range. Use 0.05 to 5 seconds.', UNSUPPORTED, '—'),
   entry('[say:word] at the start', 'Nothing to respell.', '[say:hello] there.',
         'Reported: there is no word before it.', UNSUPPORTED, '—'),
   entry('{written|}', 'An empty side.', 'The {gigahertz|} chip.',
         'Reported: it needs text on both sides of the bar.', UNSUPPORTED, '—'),
   entry('Editing after recording', 'Changing words or pauses.', 'Wait[pause:0.9] now.',
         'Changing only a pause reuses compatible takes. Changing spoken words marks them stale. All takes are '
         'kept, and go back to normal if you restore the wording.', RELIABLE, 'Both')]),

 ('Full narration examples',
  'Paste one of these into the script to see how it reads.',
  [entry('A curiosity opener',
         'A beat before the reveal, and a respelled word.',
         'Have you ever wondered why flies rub their hands together?[pause:0.6] '
         'They are not plotting anything.\n\n'
         'They taste with their feet, so a clean pair of {tarsi|tar sigh} is how they find food.',
         'Two sentences, 0.6 s of inserted silence, and one pronunciation override to review by ear.',
         RELIABLE, 'Both'),
   entry('A conclusion that lands',
         'A short beat before the last line.',
         'So the next time you see it, you will know exactly what is going on.'
         '[pause:0.45] The mystery is over.',
         'The inserted silence is exact; placement must pass alignment checks. The narration closes '
         'with room rather than stopping dead.',
         RELIABLE, 'Both')]),
]


QUICK_START = (
    'How to write a script for Voice Studio',
    'Voice Studio turns written text into a narration in a cloned voice, entirely on your Mac. '
    'The engines read your text very literally and do not take acting directions, so the way '
    'you write is the main control you have.',
    [
        ('Write it the way it should be said.',
         'Short sentences, everyday words, contractions (it\u2019s, they\u2019re). Read your script '
         'aloud once: wherever you run out of breath, add a full stop.'),
        ('One idea per paragraph.',
         'A blank line starts a new paragraph and gives a clear pause. Long paragraphs are cut '
         'automatically into sections of about 260 characters, at sentence ends first, then at '
         'commas. Each section is recorded separately and can be edited or re-recorded in the '
         'Sections tab, so shorter paragraphs give you more control.'),
        ('Use punctuation for rhythm, not for emotion.',
         'Commas, full stops, question marks and exclamation marks are passed to the engine and '
         'move the pauses a little, but they do not change the tune of a sentence. A comma is not '
         'a reliable pause (on Qwen3 it often gave a longer gap than a full stop). For a pause you '
         'can count on, use a pause mark.'),
        ('Exact pauses: [pause:0.5]',
         'Put it on its own line between paragraphs. It inserts exactly that much silence, from '
         '0.05 to 5 seconds, and replaces the normal gap between paragraphs. Written inside a '
         'sentence, right after a word, it only works where the recording has a quiet moment; if '
         'not, Voice Studio says so rather than cutting a word. Move it to a paragraph break then.'),
        ('Pronunciation: word[say:spelling] or {Written|spoken}',
         'If a word is read wrongly, respell it the way it should sound: tarsi[say:tar sigh], or '
         '{GIF|jiff}. The page still shows what you wrote; only the engine hears the respelling. '
         'A respelling can be up to 12 words.'),
        ('Write numbers, symbols and abbreviations the way they are said.',
         'General advice rather than something measured here: \u201ctwenty twenty-six\u201d, '
         '\u201cdoctor\u201d, \u201cpercent\u201d read more predictably than 2026, Dr. or %.'),
        ('Speed one section up or down: [pace:slow] or [pace:fast]',
         'Re-times the section it is written in by about 7 %, keeping the voice and pitch. Use it '
         'sparingly, for a reveal or an aside. It changes speed only; it does not add expression. '
         'Adding or changing it never needs a new recording.'),
        ('Do not rely on these. No engine can do them.',
         'Capital letters and *asterisks* for emphasis (they only change the take, like a different '
         'random seed), and directions like [delivery:curious], [emotion:happy] or [emphasis:word]. '
         'Voice Studio refuses those marks and tells you why instead of pretending. Expression comes '
         'from the voice recording and from choosing the best take.'),
        ('Listen, then re-record only what is wrong.',
         'Every recording of a section is kept as a take. If one sentence is not right, record '
         'that section again (or with the other engine) and choose the take you prefer. Changing '
         'only a pause never needs a new recording; changing spoken words does.'),
    ])


def _plain(text):
    return ' '.join(str(text).split())


def handbook_text(chapters=None, quick_start=True, preface=None):
    """The handbook as Markdown that reads fine pasted into a chat, email or document.

    Pure text, no Qt: ``chapters`` defaults to every chapter; pass a list to copy just some.
    """
    chapters = CHAPTERS if chapters is None else chapters
    preface = quick_start if preface is None else preface
    lines = []
    if quick_start:
        title, intro, steps = QUICK_START
        lines += [f'# {title}', '', intro, '']
        for number, (head, body) in enumerate(steps, 1):
            lines += [f'{number}. **{head}** {body}']
        lines += ['']
    if preface:
        lines += ['# Reference: every mark, and what it really does', '',
                  'Supported directions and their limits, measured on this Mac. Anything that does '
                  'not work says so.', '']
    for title, blurb, items in chapters:
        lines += [f'## {title}', '', _plain(blurb), '']
        for item in items:
            label_text, _, _ = BADGE[item['support']]
            lines += [f"### `{item['sign'].strip()}` ({label_text}, {item['engines']})", '',
                      _plain(item['purpose']), '',
                      f"Example: `{item['example']}`", '',
                      'What it changes: ' + _plain(item['effect'])]
            if item['limits']:
                lines += ['', 'Limitations: ' + _plain(item['limits'])]
            lines += ['']
    return '\n'.join(lines).rstrip() + '\n'


class Handbook(QDialog):
    """A searchable reference, with every example insertable into the script."""

    insert = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Voice Direction Handbook')
        self.resize(940, 680)
        self.setStyleSheet(STYLE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(8)
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(label('Voice Direction Handbook', 'heading'))
        head.addWidget(label('How to write a script, and every mark you can type into it. Tested on '
                             'this Mac; what does not work says so.', 'muted'))
        top.addLayout(head, 1)
        self.copy_all = QPushButton('Copy handbook')
        self.copy_all.setObjectName('primary')
        self.copy_all.setToolTip('Copy the whole guide as plain text to send to someone: how to '
                                 'write a script, then every mark.')
        self.copy_all.clicked.connect(self.copy_handbook)
        self.copy_chapter = QPushButton('Copy this chapter')
        self.copy_chapter.clicked.connect(self.copy_current_chapter)
        self.save_file = QPushButton('Save as file…')
        self.save_file.clicked.connect(self.save_handbook)
        for button in (self.copy_chapter, self.save_file, self.copy_all):
            top.addWidget(button)
        outer.addLayout(top)

        self.search = QLineEdit()
        self.search.setPlaceholderText('Search the handbook — try “pause”, “pronunciation”, '
                                       '“emphasis”…')
        self.search.textChanged.connect(self.apply_search)
        outer.addWidget(self.search)

        body = QHBoxLayout()
        body.setSpacing(14)
        self.chapters = QListWidget()
        self.chapters.setFixedWidth(248)
        self.chapters.currentRowChanged.connect(self.show_chapter)
        body.addWidget(self.chapters)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setStyleSheet('QScrollArea { background: transparent; border: none; }')
        self.scroll.viewport().setAutoFillBackground(False)
        self.page = QWidget()
        self.page.setObjectName('page')
        self.page.setStyleSheet('QWidget#page { background: transparent; }')
        self.page_layout = QVBoxLayout(self.page)
        self.page_layout.setContentsMargins(4, 0, 14, 0)
        self.page_layout.setSpacing(12)
        self.scroll.setWidget(self.page)
        body.addWidget(self.scroll, 1)
        outer.addLayout(body, 1)

        footer = QHBoxLayout()
        self.summary = label('', 'muted')
        footer.addWidget(self.summary, 1)
        close = QPushButton('Close')
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        outer.addLayout(footer)

        for title, _, _ in CHAPTERS:
            self.chapters.addItem(QListWidgetItem(title))
        self.chapters.setCurrentRow(0)

    # --- content -----------------------------------------------------------------
    def matching(self, query):
        query = (query or '').strip().lower()
        if not query:
            return [(title, blurb, items) for title, blurb, items in CHAPTERS]
        found = []
        for title, blurb, items in CHAPTERS:
            hits = [i for i in items
                    if query in ' '.join(str(v) for v in i.values()).lower()]
            if query in title.lower() or query in blurb.lower() or hits:
                found.append((title, blurb, hits or items))
        return found

    def apply_search(self, text):
        chapters = self.matching(text)
        titles = [c[0] for c in chapters]
        self.chapters.blockSignals(True)
        self.chapters.clear()
        for title in titles:
            self.chapters.addItem(QListWidgetItem(title))
        self.chapters.blockSignals(False)
        if titles:
            self.chapters.setCurrentRow(0)
            self.show_chapter(0)
        else:
            self.render(None)
            self.summary.setText('Nothing matches that.')

    def fit_labels(self):
        """Give every wrapped label the exact height its text needs at the current width."""
        width = self.scroll.viewport().width() - 18          # the page's own side margins
        for item in self.page.findChildren(WrappedLabel):
            inner = width - (0 if item.parent() is self.page else 32)   # card padding + border
            needed = item.heightForWidth(max(120, inner))
            if needed > 0:
                item.setFixedHeight(needed + 2)
        self.page.adjustSize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_labels()

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_labels()

    def show_chapter(self, row):
        chapters = self.matching(self.search.text())
        if 0 <= row < len(chapters):
            self.render(chapters[row])

    def render(self, chapter):
        while self.page_layout.count():
            item = self.page_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Unparent at once: deleteLater alone leaves the old chapter on screen
                # until the event loop runs, and the next one draws on top of it.
                widget.setParent(None)
                widget.deleteLater()
        if chapter is None:
            self.page_layout.addStretch()
            return
        title, blurb, items = chapter
        heading = label(title, 'heading')
        self.page_layout.addWidget(heading)
        self.page_layout.addWidget(wrapped(blurb, 'muted'))
        for item in items:
            self.page_layout.addWidget(self.card(item))
        self.page_layout.addStretch()
        reliable = sum(1 for i in items if i['support'] == RELIABLE)
        self.summary.setText(f'{len(items)} entries · {reliable} reliable')
        self.fit_labels()

    def card(self, item):
        frame = QWidget()
        frame.setObjectName('card')
        frame.setStyleSheet('QWidget#card { background:#1b1f26; border:1px solid #2a2f38;'
                            ' border-radius:12px; }')
        box = QVBoxLayout(frame)
        box.setContentsMargins(15, 13, 15, 13)
        box.setSpacing(7)

        top = QHBoxLayout()
        sign = QLabel(item['sign'])
        sign.setStyleSheet('font-family:"SF Mono",Menlo,monospace; font-size:15px;'
                           ' font-weight:700; color:#b6d8cf;')
        sign.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(sign)
        top.addStretch()
        text, fg, bg = BADGE[item['support']]
        tag = QLabel(f"{text} · {item['engines']}")
        tag.setStyleSheet(f'color:{fg}; background:{bg}; border-radius:9px;'
                          ' padding:3px 9px; font-size:11px; font-weight:600;')
        top.addWidget(tag)
        box.addLayout(top)

        box.addWidget(wrapped(item['purpose'], 'muted'))

        example = wrapped(item['example'])
        example.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        example.setStyleSheet('font-family:"SF Mono",Menlo,monospace; font-size:12.5px;'
                              ' color:#e9ecf1; background:#14171c; border:1px solid #2e343e;'
                              ' border-radius:8px;')
        example.setContentsMargins(10, 8, 10, 8)
        box.addWidget(example)

        box.addWidget(wrapped('What it changes: ' + item['effect'], 'muted'))
        if item['limits']:
            limits = wrapped('Limitations: ' + item['limits'], 'muted')
            limits.setStyleSheet('color:#c9a98f;')
            box.addWidget(limits)

        if item['support'] != UNSUPPORTED:
            row = QHBoxLayout()
            row.addStretch()
            add = QPushButton('Insert into script')
            add.clicked.connect(lambda _=False, text=item['example']: self.insert.emit(text))
            row.addWidget(add)
            copy = QPushButton('Copy')
            copy.clicked.connect(lambda _=False, text=item['example']:
                                 self.copy_to_clipboard(text))
            row.addWidget(copy)
            box.addLayout(row)
        return frame

    def copy_to_clipboard(self, text, message='Copied to the clipboard.'):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        self.summary.setText(message)

    def copy_handbook(self):
        """The whole guide, ignoring any search filter, ready to paste to someone else."""
        text = handbook_text()
        self.copy_to_clipboard(text, f'Copied the whole handbook ({len(text.split()):,} words) as plain text.')
        self._flash(self.copy_all, 'Copied ✓', 'Copy handbook')

    def copy_current_chapter(self):
        chapters = self.matching(self.search.text())
        row = self.chapters.currentRow()
        if not 0 <= row < len(chapters):
            self.summary.setText('Nothing to copy: pick a chapter first.')
            return
        self.copy_to_clipboard(handbook_text([chapters[row]], quick_start=False),
                               f'Copied “{chapters[row][0]}”.')
        self._flash(self.copy_chapter, 'Copied ✓', 'Copy this chapter')

    def save_handbook(self):
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, 'Save the handbook', str(Path.home() / 'Voice Studio Handbook.md'),
                                              'Markdown (*.md);;Text (*.txt)')
        if path:
            Path(path).write_text(handbook_text(), encoding='utf-8')
            self.summary.setText(f'Saved to {path}')

    def _flash(self, button, shown, normal):
        from PySide6.QtCore import QTimer
        button.setText(shown)
        QTimer.singleShot(1600, lambda: button.setText(normal))
