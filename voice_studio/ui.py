import os
import sys
from datetime import datetime
from pathlib import Path
# Use the installed macOS media backend for previews. The FFmpeg preview path
# advanced its clock without audible output on this Mac; native playback worked.
# FFmpeg remains the offline conversion/export tool and does not change the files.
if sys.platform == 'darwin':
    os.environ.setdefault('QT_MEDIA_BACKEND', 'darwin')
from PySide6.QtCore import (QObject, QRunnable, QSize, QThreadPool, QTimer, Qt, QUrl, Signal, QLockFile)
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPalette
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QDoubleSpinBox,
    QFileDialog, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QSlider, QSplitter,
    QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
    QScrollArea, QLayout)
from .config import DATA, ROOT, TTS_MODEL, LANGUAGES, initialize, offline_environment
from .jobs import Jobs
from . import direction, engines, moods, styles
from .storage import (atomic_json, delete_profile, has_reference, identifier, now, profiles,
                      choose_take, default_profile_id, read_json, read_script, rename_profile,
                      save_profile, save_session, segment_needs_audio, selected_take,
                      session_path, sessions, slug, spoken_fingerprint, sync_selected,
                      take_is_stale, takes_of)
from .text import new_session, split_script, session_script
from .handbook import Handbook
from . import quality, resources
from .widgets import ImportVoiceDialog, STYLE, Waveform, label

QUALITY_LABELS = {'cut_ending': 'last word cut off', 'short_ending': 'short ending', 'abrupt_end': 'ending may be cut off', 'abrupt_start': 'start may be cut off',
                  'clipping': 'clipped', 'long_internal_gap': 'long gap', 'unusual_pace': 'unusual pace',
                  'loudness_spread': 'uneven loudness', 'repeated_word': 'repeats a word',
                  'pitch_jumps': 'pitch jumps'}

class WaveSignals(QObject):
    ready = Signal(str, list)

class WaveTask(QRunnable):
    def __init__(self, path):
        super().__init__()
        self.path = str(path)
        self.signals = WaveSignals()

    def run(self):
        from .audio import waveform
        try:
            peaks = waveform(self.path)
        except Exception:
            peaks = []
        self.signals.ready.emit(self.path, peaks)

class ReviewSignals(QObject):
    ready = Signal(dict)

class ReviewTask(QRunnable):
    """Measure every section and join off the UI thread. Read-only."""
    def __init__(self, session, data):
        super().__init__()
        self.session, self.data = session, data
        self.signals = ReviewSignals()

    def run(self):
        try:
            result = quality.review_session(self.session, self.data)
        except Exception as exc:
            result = {'error': str(exc), 'sections': [], 'joins': []}
        self.signals.ready.emit(result)

class VoiceStudio(QMainWindow):
    WAIT_RETRY_MS = 10000      # re-check every 10 s ...
    WAIT_RETRY_LIMIT = 30      # ... for at most 5 minutes, then wait for the user
    AUTO_RESUME_LIMIT = 6      # pauses one Generate press may resume from on its own

    def __init__(self):
        super().__init__()
        initialize()
        self.setWindowTitle('Voice Studio')
        self.setWindowIcon(QIcon(str(ROOT / 'assets' / 'icon.png')))
        self.resize(1240, 850)
        self.setMinimumSize(980, 740)
        self.session = None
        self.profile = None
        self.output_path = None
        self.preview_path = None
        self.job_action = None
        self._closing = False
        self._wave_tasks = []
        self._profile_warning = ''
        self._incomplete = []
        self._applying = False
        self.jobs = Jobs(self)
        self.jobs.event.connect(self.on_event)
        self.jobs.ended.connect(self.on_finished)
        # Waiting for memory: one pending job, re-checked on a timer. Nothing is loaded while waiting.
        self._waiting_job = None
        self._wait_attempts = 0
        self._worker_wait = None
        self._safe_stop = None
        self._resource_history = []
        self.wait_timer = QTimer(self)
        self.wait_timer.setInterval(self.WAIT_RETRY_MS)
        self.wait_timer.timeout.connect(self.retry_waiting)
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(.75)
        self.player.setAudioOutput(self.audio_output)
        self.media_devices = QMediaDevices(self)
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)
        self.player.playbackStateChanged.connect(self.play_state_changed)
        self.player.errorOccurred.connect(lambda code, message: self.status.setText('Playback: ' + message))
        # A dead output device (a Bluetooth speaker that is off, say) leaves the player
        # reporting "playing" while nothing is heard. Notice that and say so.
        self._stall_position = -1
        self._stall_ticks = 0
        self._stall_warned = False
        self.stall_watch = QTimer(self)
        self.stall_watch.setInterval(600)
        self.stall_watch.timeout.connect(self.check_playback_progress)
        self.build_ui()
        self.refresh_output_devices()
        self.media_devices.audioOutputsChanged.connect(self.refresh_output_devices)
        self.build_menu()
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.setInterval(450)
        self.autosave.timeout.connect(self.save_draft)
        self.script.textChanged.connect(self.script_changed)
        self.title.textChanged.connect(lambda: self.autosave.start())
        self.language.currentTextChanged.connect(lambda: self.autosave.start())
        self.load_profiles()
        self.load_history()
        self.restore_draft()
        self.refresh_controls()

    def button(self, text, callback, style=None):
        widget = QPushButton(text)
        if style:
            widget.setObjectName(style)
        widget.clicked.connect(callback)
        return widget

    def build_ui(self):
        container = QWidget()
        self.setCentralWidget(container)
        root = QHBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        side = QFrame()
        side.setObjectName('sidebar')
        side.setFixedWidth(240)
        sidebar = QVBoxLayout(side)
        sidebar.setContentsMargins(18, 26, 18, 18)
        sidebar.setSpacing(8)
        sidebar.addWidget(label('◖  Voice Studio', 'brand'))
        sidebar.addWidget(label('Private narration, on your Mac.', 'muted'))
        sidebar.addSpacing(14)
        self.new_button = self.button('＋  New narration', self.new_narration, 'accent')
        sidebar.addWidget(self.new_button)
        sidebar.addSpacing(16)
        sidebar.addWidget(label('VOICES', 'eyebrow'))
        self.voice_list = QListWidget()
        self.voice_list.setMinimumHeight(96)
        self.voice_list.setMaximumHeight(210)
        self.voice_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.voice_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.voice_list.currentItemChanged.connect(self.select_profile)
        self.voice_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.voice_list.customContextMenuRequested.connect(self.voice_menu)
        sidebar.addWidget(self.voice_list, 1)
        self.add_voice = self.button('+  Add your voice', self.import_voice, 'quiet')
        sidebar.addWidget(self.add_voice)
        sidebar.addSpacing(16)
        sidebar.addWidget(label('RECENT NARRATIONS', 'eyebrow'))
        self.history = QListWidget()
        self.history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.history.setToolTip('Double-click a narration to open it.')
        self.history.itemDoubleClicked.connect(self.open_history)
        sidebar.addWidget(self.history, 2)
        sidebar.addWidget(label('Double-click to open', 'muted'))
        sidebar.addSpacing(8)
        ready = (TTS_MODEL / '.complete').exists()
        self.model_badge = label('●  Local model ready' if ready else '○  Model setup needed',
                                 'badge' if ready else 'badgeOff')
        sidebar.addWidget(self.model_badge)
        footnote = label('Qwen3-TTS · 0.6B · 8-bit\nPrivate: no cloud audio.', 'muted')
        footnote.setWordWrap(True)
        sidebar.addWidget(footnote)
        root.addWidget(side)
        main = QVBoxLayout()
        main.setContentsMargins(26, 22, 26, 18)
        main.setSpacing(12)
        heading = QHBoxLayout()
        heading.setSpacing(8)
        self.title = QLineEdit('Untitled narration')
        self.title.setObjectName('titleEdit')
        self.title.setPlaceholderText('Name your narration')
        self.title.setToolTip('Click to rename this narration.')
        heading.addWidget(self.title, 1)
        self.handbook_button = self.button('Handbook', self.open_handbook, 'quiet')
        self.handbook_button.setToolTip('How to write a script: pauses, pronunciations, '
                                        'and what punctuation really does. Can be copied to share.')
        heading.addWidget(self.handbook_button)
        self.import_button = self.button('Import TXT…', self.import_txt, 'quiet')
        heading.addWidget(self.import_button)
        main.addLayout(heading)

        def field(caption, widget, stretch=0):
            column = QVBoxLayout()
            column.setSpacing(4)
            column.addWidget(label(caption.upper(), 'field'))
            column.addWidget(widget)
            return column

        settings_card = QFrame()
        settings_card.setObjectName('card')
        card_layout = QVBoxLayout(settings_card)
        card_layout.setContentsMargins(16, 13, 16, 12)
        card_layout.setSpacing(10)
        settings = QHBoxLayout()
        settings.setSpacing(14)
        self.language = QComboBox()
        self.language.addItems(LANGUAGES)
        settings.addLayout(field('Language', self.language), 2)
        self.style = QComboBox()
        self.style.addItems(styles.ORDER)
        self.style.currentTextChanged.connect(self.style_chosen)
        settings.addLayout(field('Narration style', self.style), 3)
        self.main_engine = QComboBox()
        for name in engines.available():
            self.main_engine.addItem(engines.label(name), name)
        self.main_engine.setToolTip('The engine new sections use. A section can override it '
                                    'in the Sections tab, and existing takes are kept either way.')
        self.main_engine.currentIndexChanged.connect(self.main_engine_chosen)
        settings.addLayout(field('Engine', self.main_engine), 3)
        card_layout.addLayout(settings)
        notes = QHBoxLayout()
        self.style_note = label(styles.summary(styles.NATURAL), 'muted')
        self.style_note.setWordWrap(True)
        notes.addWidget(self.style_note, 1)
        self.fine_toggle = QPushButton('  Fine-tune delivery')
        self.fine_toggle.setIcon(QIcon(str(ROOT / 'assets' / 'ui' / 'chevron-right.svg')))
        self.fine_toggle.setObjectName('flat')
        self.fine_toggle.setIconSize(QSize(11, 11))
        self.fine_toggle.setCheckable(True)
        self.fine_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fine_toggle.setToolTip('Pace, speed and pauses. Changing one switches the style to Custom.')
        notes.addWidget(self.fine_toggle)
        card_layout.addLayout(notes)
        self.fine_panel = QWidget()
        delivery = QHBoxLayout(self.fine_panel)
        delivery.setContentsMargins(0, 0, 0, 0)
        delivery.setSpacing(14)
        self.controls = {}
        for name, caption, suffix, step, tip in (
            ('reference_tempo', 'Reference pace', ' ×', .05,
             'Stretches the voice sample the model listens to. Higher speaks faster in its own '
             'voice. Measured: a 1.15× reference raised delivery from 3.05 to 3.37 words a second.'),
            ('speed', 'Final speed', ' ×', .05,
             'Pitch-preserving stretch applied after generation. Exact, but large values sound processed.'),
            ('pause', 'Paragraph pause', ' s', .05, 'Silence inserted between paragraphs.'),
            ('sentence_pause', 'Section pause', ' s', .02,
             'Silence between sections inside one paragraph.'),
        ):
            low, high = styles.LIMITS[name]
            box = QDoubleSpinBox()
            box.setRange(low, high)
            box.setSingleStep(step)
            box.setSuffix(suffix)
            box.setDecimals(2)
            box.setValue(styles.PRESETS[styles.NATURAL][name])
            box.setToolTip(tip)
            box.valueChanged.connect(self.delivery_changed)
            self.controls[name] = box
            delivery.addLayout(field(caption, box), 1)
        self.fine_panel.setVisible(False)
        card_layout.addWidget(self.fine_panel)

        def toggle_fine(shown):
            self.fine_panel.setVisible(shown)
            self.fine_toggle.setIcon(QIcon(str(ROOT / 'assets' / 'ui' / ('chevron-down.svg' if shown else 'chevron-right.svg'))))
        self.fine_toggle.toggled.connect(toggle_fine)
        # A hand-tuned value is the point of Custom, so show the controls that make it.
        self.style.currentTextChanged.connect(
            lambda name: self.fine_toggle.setChecked(True) if name == styles.CUSTOM else None)
        main.addWidget(settings_card)
        # Two legacy aliases: plenty of existing code reads these by name.
        self.speed, self.pause = self.controls['speed'], self.controls['pause']
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.tabBar().setExpanding(False)
        self.script = QTextEdit()
        self.script.setObjectName('script')
        self.script.setAcceptRichText(False)
        self.script.setPlaceholderText('Every great narration starts with a few words.\n\nPaste your script here, or import a TXT file.\n\nParagraphs become natural pauses. Long passages are divided into short, editable sections automatically.')
        self.tabs.addTab(self.script, 'Script')
        section_page = QWidget()
        section_page_layout = QVBoxLayout(section_page)
        section_page_layout.setContentsMargins(0, 8, 0, 0)
        section_page_layout.setSpacing(10)
        sections = QWidget()
        sections.setObjectName('sectionContent')
        sections.setStyleSheet('QWidget#sectionContent { background: transparent; }')
        section_layout = QVBoxLayout(sections)
        section_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(10)
        self.table = QTableWidget(0, 5)
        self.table.setMinimumHeight(112)
        self.table.setHorizontalHeaderLabels(['#', 'Section', 'Engine', 'Status', 'Length'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setColumnWidth(0, 42)
        self.table.setColumnWidth(2, 112)
        self.table.setColumnWidth(3, 96)
        self.table.setColumnWidth(4, 70)
        self.table.itemSelectionChanged.connect(self.section_selected)
        section_layout.addWidget(self.table, 1)
        editing = QHBoxLayout()
        editing.setSpacing(14)
        words = QVBoxLayout()
        words.setSpacing(5)
        words.addWidget(label('SECTION WORDS', 'eyebrow'))
        self.section_text = QTextEdit()
        self.section_text.setMinimumHeight(70)
        self.section_text.setMaximumHeight(96)
        self.section_text.setPlaceholderText('Select a section to edit its wording.')
        words.addWidget(self.section_text)
        editing.addLayout(words, 3)
        # Every recording ever made for this section, so nothing is lost by trying again.
        column = QVBoxLayout()
        column.setSpacing(5)
        column.addWidget(label('TAKES FOR THIS SECTION', 'eyebrow'))
        self.takes = QListWidget()
        self.takes.setObjectName('bordered')
        self.takes.setMinimumHeight(70)
        self.takes.setMaximumHeight(96)
        self.takes.setToolTip('Double-click a take to use it in the narration.')
        self.takes.itemDoubleClicked.connect(self.use_take)
        self.takes.itemSelectionChanged.connect(self.refresh_controls)
        column.addWidget(self.takes)
        editing.addLayout(column, 2)
        section_layout.addLayout(editing)
        section_scroll = QScrollArea()
        section_scroll.setWidgetResizable(True)
        section_scroll.setFrameShape(QFrame.Shape.NoFrame)
        section_scroll.setStyleSheet('QScrollArea { background: transparent; border: none; }')
        section_scroll.setWidget(sections)
        section_page_layout.addWidget(section_scroll, 1)
        section_buttons = QHBoxLayout()
        section_buttons.setSpacing(8)
        self.apply_section = self.button('Save section edit', self.save_section_edit)
        self.preview_section = self.button('▶  Play section', self.play_section)
        self.play_take_button = self.button('▶  Play take', self.play_take)
        self.use_take_button = self.button('Use this take', self.use_take)
        for btn in (self.apply_section, self.preview_section,
                    self.play_take_button, self.use_take_button):
            section_buttons.addWidget(btn)
        section_buttons.addStretch()
        self.engine_choice = QComboBox()
        for name in engines.available():
            self.engine_choice.addItem(engines.label(name), name)
        self.engine_choice.setMinimumWidth(140)
        self.engine_choice.currentIndexChanged.connect(self.engine_chosen)
        self.regenerate = self.button('Generate section', self.regenerate_section, 'accent')
        self.alternative = self.button('Generate with other engine', self.generate_alternative)
        self.engine_note = label('', 'muted')
        self.engine_note.setWordWrap(True)
        # Which of the voice's mood clips this section is cloned from (voice_studio/moods.py).
        self.mood_choice = QComboBox()
        self.mood_choice.setMinimumWidth(150)
        self.mood_choice.setToolTip('The recording of this voice the section copies its delivery from.\n'
                                    'Auto reads the words; pick a mood to override, then Generate section.')
        self.mood_choice.currentIndexChanged.connect(self.mood_chosen)
        generation_buttons = QHBoxLayout()
        generation_buttons.setSpacing(8)
        generation_buttons.addWidget(self.engine_note, 1)
        generation_buttons.addWidget(label('Mood', 'muted'))
        generation_buttons.addWidget(self.mood_choice)
        generation_buttons.addWidget(label('Engine', 'muted'))
        generation_buttons.addWidget(self.engine_choice)
        generation_buttons.addWidget(self.regenerate)
        generation_buttons.addWidget(self.alternative)
        actions_card = QFrame()
        actions_card.setObjectName('card')
        actions_layout = QVBoxLayout(actions_card)
        actions_layout.setContentsMargins(12, 10, 12, 10)
        actions_layout.setSpacing(8)
        actions_layout.addLayout(section_buttons)
        actions_layout.addLayout(generation_buttons)
        section_page_layout.addWidget(actions_card)
        self.tabs.addTab(section_page, 'Sections')
        review_tab = QWidget()
        review = QVBoxLayout(review_tab)
        review.setContentsMargins(0, 10, 0, 0)
        review.setSpacing(10)
        self.review_summary = label('Generate a narration to review how its sections fit together.', 'muted')
        self.review_summary.setWordWrap(True)
        review.addWidget(self.review_summary)
        self.review_table = QTableWidget(0, 3)
        self.review_table.setHorizontalHeaderLabels(['Where', 'Type', 'What was measured'])
        self.review_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.review_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.review_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.review_table.setAlternatingRowColors(True)
        self.review_table.setShowGrid(False)
        self.review_table.setWordWrap(True)
        self.review_table.verticalHeader().hide()
        self.review_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.review_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.review_table.setColumnWidth(0, 120)
        self.review_table.setColumnWidth(1, 80)
        self.review_table.itemSelectionChanged.connect(self.refresh_controls)
        review.addWidget(self.review_table, 1)
        review_buttons = QHBoxLayout()
        self.review_refresh = self.button('Refresh review', self.run_review)
        self.review_play = self.button('▶  Play this join', self.play_join)
        review_buttons.addWidget(self.review_refresh)
        review_buttons.addWidget(self.review_play)
        review_buttons.addStretch()
        review_buttons.addWidget(label('Measurements to guide your listening. They never change or remove audio.', 'muted'))
        review.addLayout(review_buttons)
        self.review_joins = []
        self.tabs.addTab(review_tab, 'Review')
        self.tabs.currentChanged.connect(lambda i: self.run_review() if self.tabs.tabText(i) == 'Review' else None)
        reference_tab = QWidget()
        ref = QVBoxLayout(reference_tab)
        ref.setContentsMargins(1, 17, 1, 0)
        self.ref_heading = label('Add a voice to get started', 'heading')
        ref.addWidget(self.ref_heading)
        self.ref_info = label('Import a short, clear recording using the Voice Library.', 'muted')
        self.ref_info.setWordWrap(True)
        ref.addWidget(self.ref_info)
        ref.addWidget(label('REFERENCE TRANSCRIPT', 'eyebrow'))
        self.transcript = QTextEdit()
        self.transcript.setAcceptRichText(False)
        self.transcript.setPlaceholderText('The exact words spoken in the prepared reference sample.\nUse offline transcription, then listen and correct any mistakes.')
        ref.addWidget(self.transcript, 1)
        ref_controls = QHBoxLayout()
        self.play_ref = self.button('Play reference', self.play_reference)
        self.auto_transcribe = self.button('Transcribe offline', self.transcribe_reference)
        self.save_ref = self.button('Save transcript', self.save_reference)
        self.replace_ref = self.button('Replace sample…', lambda: self.import_voice(replace=True))
        for btn in (self.play_ref, self.auto_transcribe, self.save_ref, self.replace_ref):
            ref_controls.addWidget(btn)
        ref.addLayout(ref_controls)
        note = label('This is reference-based voice cloning. No model is trained on your recording.\nUse the same sample across sections for a more consistent voice.', 'muted')
        note.setWordWrap(True)
        ref.addWidget(note)
        self.tabs.addTab(reference_tab, 'Voice reference')
        main.addWidget(self.tabs, 1)
        information = QHBoxLayout()
        self.script_info = label('0 words · 0 sections', 'muted')
        self.voice_info = label('Select or add a voice', 'muted')
        information.addWidget(self.script_info)
        information.addStretch()
        information.addWidget(self.voice_info)
        main.addLayout(information)
        preview = QFrame()
        preview.setObjectName('card')
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(16, 10, 16, 12)
        preview_layout.setSpacing(6)
        self.preview_label = label('AUDIO PREVIEW', 'eyebrow')
        preview_layout.addWidget(self.preview_label)
        self.wave = Waveform()
        self.wave.setMinimumHeight(38)
        self.wave.seek.connect(lambda fraction: self.player.setPosition(int(fraction * self.player.duration())))
        preview_layout.addWidget(self.wave)
        transport = QHBoxLayout()
        transport.setSpacing(10)
        self.play_button = self.button('▶', self.toggle_playback, 'play')
        transport.addWidget(self.play_button)
        self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.timeline.setRange(0, 0)
        self.timeline.sliderMoved.connect(self.player.setPosition)
        transport.addWidget(self.timeline, 1)
        self.time_label = label('0:00 / 0:00', 'muted')
        transport.addWidget(self.time_label)
        self.full_preview = self.button('Full narration', self.play_full, 'quiet')
        transport.addWidget(self.full_preview)
        self.export_button = self.button('Export audio…', self.export, 'quiet')
        transport.addWidget(self.export_button)
        preview_layout.addLayout(transport)
        main.addWidget(preview)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        main.addWidget(self.progress)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.status = label('Ready. Add your voice, then bring your script to life.', 'status')
        self.status.setWordWrap(True)
        actions.addWidget(self.status, 1)
        self.cancel_button = self.button('Cancel', self.cancel)
        self.cancel_button.hide()
        actions.addWidget(self.cancel_button)
        self.generate_button = self.button('Generate narration', self.start_generation, 'primary')
        actions.addWidget(self.generate_button)
        main.addLayout(actions)
        root.addLayout(main, 1)
        self.play_button.setToolTip('Play')
        self.setStyleSheet(STYLE)

    def build_menu(self):
        file_menu = self.menuBar().addMenu('File')
        for name, shortcut, callback in [('New narration', 'Ctrl+N', self.new_narration),
                                          ('Import script…', 'Ctrl+O', self.import_txt),
                                          ('Add voice…', 'Ctrl+Shift+O', self.import_voice),
                                          ('Export audio…', 'Ctrl+Shift+E', self.export)]:
            action = QAction(name, self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            file_menu.addAction(action)
        voices_menu = self.menuBar().addMenu('Voices')
        for name, callback in [('Add voice…', self.import_voice),
                               ('New empty voice…', self.new_voice_slot),
                               ('Replace sample…', lambda: self.import_voice(replace=True)),
                               ('Rename voice…', self.rename_voice),
                               ('Remove voice…', self.remove_voice)]:
            action = QAction(name, self)
            action.triggered.connect(callback)
            voices_menu.addAction(action)
        help_menu = self.menuBar().addMenu('Help')
        for name, path in [('Usage guide', ROOT / 'README.md'), ('Open local files', DATA), ('Open diagnostic logs', DATA / 'logs')]:
            action = QAction(name, self)
            action.triggered.connect(lambda checked=False, p=path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))))
            help_menu.addAction(action)

    def show_error(self, message):
        self.status.setText(message)
        QMessageBox.warning(self, 'Voice Studio', message)

    def load_profiles(self, selected=None):
        # Falls back to the voice marked as default, so the library opens on the same one
        # every time rather than on whichever name happens to sort first.
        selected = (selected or (self.profile['id'] if self.profile else None)
                    or default_profile_id())
        self.voice_list.blockSignals(True)
        self.voice_list.clear()
        for profile in profiles():
            detail = (f"{profile.get('seconds', 0):.1f} s reference" if has_reference(profile)
                      else 'Waiting for a recording')
            item = QListWidgetItem(f"{profile['name']}\n{detail}")
            item.setData(Qt.ItemDataRole.UserRole, profile)
            self.voice_list.addItem(item)
            if profile['id'] == selected:
                self.voice_list.setCurrentItem(item)
        self.voice_list.blockSignals(False)
        if self.voice_list.currentRow() < 0 and self.voice_list.count():
            self.voice_list.setCurrentRow(0)
        else:
            self.select_profile(self.voice_list.currentItem(), None)

    def select_profile(self, current, previous):
        if previous and self.profile and has_reference(self.profile):
            self.save_reference(silent=True)
        self.profile = current.data(Qt.ItemDataRole.UserRole) if current else None
        if self.profile:
            self.transcript.setPlainText(self.profile.get('transcript', ''))
            self.ref_heading.setText(self.profile['name'])
            if has_reference(self.profile):
                self.ref_info.setText(f"{self.profile.get('seconds', 0):.1f} seconds · mono · 24 kHz · stored on this Mac\nReview the prepared sample and ensure the transcript matches exactly.")
                if moods.names(self.profile):
                    self.ref_info.setText(self.ref_info.text() + '\nMood clips: '
                                          + ', '.join(moods.LABELS.get(m, m) for m in moods.names(self.profile))
                                          + '. Each section uses the one that fits its words.')
                if self.profile.get('warning'):
                    self.ref_info.setText(self.ref_info.text() + '\n' + self.profile['warning'])
            else:
                self.ref_info.setText(self.profile.get('description') or
                    'This voice has no recording yet. Use Replace sample… to add one.')
            self.voice_info.setText('Voice: ' + self.profile['name'])
            # Each voice remembers the style it is usually narrated in.
            default = self.profile.get('style')
            if default in styles.ORDER and not self.session:
                self.apply_settings(default, styles.settings(default))
        else:
            self.transcript.clear()
            self.voice_info.setText('Select or add a voice')
        self.refresh_controls()

    def new_voice_slot(self):
        """Create an empty voice the user fills with a recording later."""
        if self.jobs.busy:
            return
        name, ok = QInputDialog.getText(self, 'New voice', 'Name this voice:')
        if not ok or not name.strip():
            return
        profile = {'id': identifier(), 'name': name.strip(), 'created': now(), 'updated': now(),
                   'placeholder': True, 'reference': '', 'transcript': '', 'style': styles.NATURAL,
                   'seconds': 0, 'description': 'This voice has no recording yet. '
                   'Use Replace sample… to add one you own or are authorised to use.'}
        save_profile(profile)
        self.profile = None
        self.load_profiles(profile['id'])
        self.tabs.setCurrentIndex(2)
        self.status.setText('Voice created. Add a recording with Replace sample…')

    def rename_voice(self):
        if self.jobs.busy or not self.profile:
            return
        name, ok = QInputDialog.getText(self, 'Rename voice', 'Voice name:', text=self.profile['name'])
        if not ok:
            return
        try:
            rename_profile(self.profile, name)
        except ValueError as exc:
            self.show_error(str(exc))
            return
        self.load_profiles(self.profile['id'])
        self.load_history()
        self.status.setText('Voice renamed. Existing narrations keep their audio.')

    def remove_voice(self):
        if self.jobs.busy or not self.profile:
            return
        answer = QMessageBox.question(self, 'Remove this voice?',
            f"Remove \u201c{self.profile['name']}\u201d and its recordings?\n\n"
            'Narrations already generated with it keep their audio. This cannot be undone.',
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        delete_profile(self.profile)
        self.profile = None
        self.load_profiles()
        self.status.setText('Voice removed.')

    def voice_menu(self, point):
        if not self.voice_list.count():
            return
        menu = QMenu(self)
        for name, callback in (('Replace sample…', lambda: self.import_voice(replace=True)),
                               ('Rename…', self.rename_voice),
                               ('Remove…', self.remove_voice)):
            action = menu.addAction(name)
            action.setEnabled(bool(self.profile) and not self.jobs.busy)
            action.triggered.connect(callback)
        menu.exec(self.voice_list.mapToGlobal(point))

    def save_reference(self, checked=False, silent=False):
        if self.profile:
            self.profile['transcript'] = self.transcript.toPlainText().strip()
            save_profile(self.profile)
            if not silent:
                self.status.setText('Reference transcript saved locally.')

    def import_voice(self, checked=False, replace=False):
        if self.jobs.busy:
            return
        dialog = ImportVoiceDialog(self, self.profile if replace else None)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.start_job(dialog.job())

    def transcribe_reference(self):
        if self.profile and not self.jobs.busy:
            self.start_job({'action': 'transcribe', 'source': str(DATA / self.profile['reference'])})

    def import_txt(self):
        if self.jobs.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Import narration script', '', 'Text files (*.txt)')
        if path:
            self.import_script_path(path)

    def import_script_path(self, path):
        try:
            script = read_script(path)
            self.script.setPlainText(script)
            self.title.setText(Path(path).stem)
            self.tabs.setCurrentIndex(0)
            self.status.setText('Script imported. Review the text, then generate your narration.')
        except (OSError, ValueError) as exc:
            self.show_error(str(exc))

    def open_handbook(self):
        """The built-in reference, with examples that can be inserted straight away."""
        if getattr(self, '_handbook', None) is None:
            self._handbook = Handbook(self)
            self._handbook.insert.connect(self.insert_direction)
        self._handbook.show()
        self._handbook.raise_()
        self._handbook.activateWindow()

    def insert_direction(self, text):
        """Drop a handbook example where the cursor is, in whichever box is in use."""
        target = self.section_text if self.tabs.currentIndex() == 1 else self.script
        if self.tabs.currentIndex() != 1:
            self.tabs.setCurrentIndex(0)
        target.insertPlainText(text)
        target.setFocus()
        self.status.setText('Example inserted. Generate to hear it.')

    def script_changed(self):
        text = self.script.toPlainText()
        plan = direction.parse(text)
        try:
            section_count = str(len(split_script(text)))
        except ValueError:
            section_count = '—'
        bits = [f'{len(plan.spoken.split()):,} words',
                f'{section_count} sections']
        note = direction.describe(plan)
        if note:
            bits.append(note)
        self.script_info.setText(' · '.join(bits))
        # Say what is wrong while it is still being typed, rather than at generation time.
        if plan.problems:
            self.script_info.setText(self.script_info.text() + '  ·  ' + plan.problems[0])
        self.autosave.start()
        self.refresh_controls()

    def save_draft(self):
        atomic_json(DATA / 'draft.json', {'script': self.script.toPlainText(), 'title': self.title.text(),
                    'session': self.session['id'] if self.session else None,
                    'voice': self.profile['id'] if self.profile else None,
                    'language': self.language.currentText(),
                    'style': self.style.currentText(), 'settings': self.delivery_values()})

    def restore_draft(self):
        try:
            draft = read_json(DATA / 'draft.json', {})
            if draft.get('session'):
                saved = read_json(DATA / 'sessions' / draft['session'] / 'project.json')
                if saved:
                    self.load_session(saved)
            self.script.setPlainText(draft.get('script', ''))
            self.title.setText(draft.get('title', 'Untitled narration'))
            self.language.setCurrentText(draft.get('language', 'English'))
            style = draft.get('style', styles.NATURAL)
            self.apply_settings(style, styles.settings(style, draft.get('settings')))
            if draft.get('voice'):
                self.load_profiles(draft['voice'])
        except (OSError, ValueError, KeyError):
            self.status.setText('The last draft could not be restored. Saved narrations remain in Recent narrations.')

    def load_history(self):
        self.history.clear()
        for session in sessions()[:30]:
            count = sum(bool(s.get('file')) for s in session['segments'])
            item = QListWidgetItem(f"{session['title']}\n{count}/{len(session['segments'])} sections · {session['voice_name']}")
            item.setData(Qt.ItemDataRole.UserRole, session['id'])
            self.history.addItem(item)

    def open_history(self, item):
        if self.jobs.busy:
            return
        self.save_draft()
        try:
            session = read_json(DATA / 'sessions' / item.data(Qt.ItemDataRole.UserRole) / 'project.json')
            self.load_session(session)
            self.save_draft()
        except (OSError, ValueError, KeyError) as exc:
            self.show_error('Could not open this narration: ' + str(exc))

    def load_session(self, session):
        self.session = session
        self.title.setText(session['title'])
        self.script.setPlainText(session['script'])
        self.language.setCurrentText(session['language'])
        self._applying = True
        index = self.main_engine.findData(engines.normalize(session.get('engine')))
        if index >= 0:
            self.main_engine.setCurrentIndex(index)
        self._applying = False
        self.apply_settings(session.get('style', styles.NATURAL),
                            styles.settings(session.get('style', styles.NATURAL), session.get('settings')))
        self.load_profiles(session['voice_id'])
        self.refresh_table()
        self.output_path = DATA / session['output'] if session.get('output') else None
        if self.output_path and self.output_path.exists():
            self.set_preview(self.output_path, 'FULL NARRATION')
        else:
            # Say why there is nothing to play, rather than leaving a silent Play button.
            self.clear_preview()
            pending = sum(1 for seg in session['segments'] if segment_needs_audio(seg, DATA))
            self.status.setText(
                f'{pending} section(s) still need recording. Press Generate narration.'
                if pending else
                'Every section has audio, but the narration has not been assembled yet. '
                'Press Generate narration to put it together.')
        self.refresh_controls()

    def new_narration(self):
        if self.jobs.busy:
            return
        self.save_draft()
        self.session = None
        self.script.clear()
        self.title.setText('Untitled narration')
        self.output_path = None
        self.clear_preview()
        self.refresh_table()
        self.tabs.setCurrentIndex(0)
        self.status.setText('A new narration is ready for your words.')
        self.refresh_controls()

    def delivery_values(self):
        return {name: box.value() for name, box in self.controls.items()}

    def apply_settings(self, style, values, silent=True):
        """Put a style and its numbers into the controls without feeding changes back."""
        self._applying = True
        try:
            for name, box in self.controls.items():
                box.setValue(styles.clamp(name, values.get(name, box.value())))
            self.style.setCurrentText(style if style in styles.ORDER else styles.CUSTOM)
            self.style_note.setText(styles.summary(self.style.currentText()))
        finally:
            self._applying = False
        if not silent:
            self.autosave.start()

    def style_chosen(self, name):
        self.style_note.setText(styles.summary(name))
        if self._applying or name == styles.CUSTOM:
            return
        self.apply_settings(name, styles.settings(name))
        self.autosave.start()

    def delivery_changed(self):
        """Hand-editing a number means the preset no longer describes it."""
        if self._applying:
            return
        current = self.style.currentText()
        if current != styles.CUSTOM and not styles.matches(current, self.delivery_values()):
            self._applying = True
            self.style.setCurrentText(styles.CUSTOM)
            self.style_note.setText(styles.summary(styles.CUSTOM))
            self._applying = False
        self.autosave.start()

    def retimed_only(self, script):
        """True when the edit changed pauses between sections but not a single word."""
        session = self.session
        if not session or session.get('voice_id') != (self.profile or {}).get('id'):
            return False
        if session.get('style') != self.style.currentText():
            return False
        if session.get('language') != self.language.currentText():
            return False
        saved = styles.settings(session.get('style', styles.NATURAL), session.get('settings'))
        values = self.delivery_values()
        if any(abs(saved[n] - styles.clamp(n, values[n])) > 1e-6 for n in styles.CONTROLS):
            return False
        chunks = split_script(script)
        if len(chunks) != len(session['segments']):
            return False
        return all(spoken_fingerprint(chunk['text']) == spoken_fingerprint(segment['text']) and
                   chunk.get('paragraph_end') == segment.get('paragraph_end')
                   for chunk, segment in zip(chunks, session['segments']))

    def session_matches(self):
        s, p = self.session, self.profile
        if not (s and p):
            return False
        values = self.delivery_values()
        saved = styles.settings(s.get('style', styles.NATURAL), s.get('settings'))
        return all((s['script'] == self.script.toPlainText().strip(),
            s['voice_id'] == p['id'], s['reference'] == p['reference'], s['transcript'] == p['transcript'],
            (s.get('moods') or []) == (p.get('moods') or []),
            s['language'] == self.language.currentText(),
            s.get('style', styles.NATURAL) == self.style.currentText(),
            all(abs(saved[n] - styles.clamp(n, values[n])) < 1e-6 for n in styles.CONTROLS)))

    def start_generation(self):
        if self.jobs.busy:
            return
        self.save_reference(silent=True)
        if not self.profile:
            self.show_error('Add or select a voice in the Voice Library first.')
            return
        if not has_reference(self.profile):
            self.tabs.setCurrentIndex(2)
            self.show_error(f"\u201c{self.profile['name']}\u201d has no recording yet. "
                            'Use Replace sample… to add one, then generate.')
            return
        if not self.profile.get('transcript'):
            self.tabs.setCurrentIndex(2)
            self.show_error('Enter the reference transcript or use Transcribe offline, then review it.')
            return
        script = self.script.toPlainText().strip()
        if not script:
            self.show_error('Import a TXT file or type your narration script first.')
            return
        try:
            chunks = split_script(script)
            if not chunks:
                raise ValueError('This script has directions but no words to speak.')
        except ValueError as exc:
            self.show_error(str(exc))
            return
        if not self.session_matches():
            if self.retimed_only(script):
                # Only the timing between sections changed. The recordings are still of the
                # right words, so reassemble rather than record everything again.
                self.session['script'] = script
                for segment, chunk in zip(self.session['segments'], split_script(script)):
                    takes_of(segment)  # preserve the old display text in legacy takes
                    segment['text'] = chunk['text']
                    for field in ('lead_pause', 'trail_pause'):
                        if chunk.get(field):
                            segment[field] = chunk[field]
                        else:
                            segment.pop(field, None)
                self.session['output'] = None
                self.output_path = None
                self.clear_preview()
                self.status.setText('Timing updated. The existing takes are kept.')
            else:
                self.session = new_session(script, self.title.text(), self.profile,
                                           self.style.currentText(), self.delivery_values(),
                                           self.language.currentText(),
                                           self.main_engine.currentData())
                self.output_path = None
                self.clear_preview()
        self.session['title'] = self.title.text().strip() or 'Untitled narration'
        save_session(self.session)
        self.refresh_table()
        self.save_draft()
        indices = [i for i, seg in enumerate(self.session['segments'])
                   if segment_needs_audio(seg, DATA)]
        if not indices and self.session.get('output'):
            self.play_full()
            self.status.setText('All sections are ready. Select a section to regenerate, or export the narration.')
            return
        self.start_job({'action': 'generate', 'session': str(session_path(self.session))})

    def section_engine(self, segment):
        """The engine this section will use next time it is generated."""
        return engines.normalize(segment.get('engine') or
                                 (self.session or {}).get('engine') or engines.DEFAULT)

    def refresh_table(self):
        row = self.table.currentRow()
        segments = self.session['segments'] if self.session else []
        self.table.setRowCount(len(segments))
        for i, seg in enumerate(segments):
            ready = not segment_needs_audio(seg, DATA)
            take = selected_take(seg)
            spare = len(takes_of(seg))
            if not ready and spare:
                status = 'Edited'          # takes exist but none matches the words
            elif not ready:
                status = 'Pending'
            elif seg.get('verified') is False:
                status = 'Check it'
            elif seg.get('verified') is not True:
                status = 'Unchecked'
            elif (seg.get('verification_version') or 1) < 2:
                status = 'Legacy check'
            else:
                status = 'Ready'
            engine = engines.label(take['engine']) if take else engines.label(self.section_engine(seg))
            mood = take.get('mood') if take else self.section_mood(seg)
            if mood:
                engine += ' · ' + moods.LABELS.get(mood, mood).split(' /')[0]
            if spare > 1:
                engine += f'  ({spare} takes)'
            values = [str(i + 1), seg['text'], engine, status,
                      f"{seg.get('seconds', 0):.1f} s" if ready else '—']
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(i, col, item)
        if segments:
            self.table.selectRow(max(0, min(row, len(segments) - 1)))
        else:
            self.section_text.clear()
        # Re-selecting the same row emits no signal, so refresh the takes list directly
        # rather than leaving it showing a previous section's recordings.
        self.refresh_takes()
        self.refresh_controls()

    def selected_segment(self):
        row = self.table.currentRow()
        return (row, self.session['segments'][row]) if self.session and 0 <= row < len(self.session['segments']) else (-1, None)

    def section_selected(self):
        row, segment = self.selected_segment()
        self.section_text.setPlainText(segment['text'] if segment else '')
        self.refresh_takes()
        if segment:
            self._applying = True
            engine = self.section_engine(segment)
            index = self.engine_choice.findData(engine)
            if index >= 0:
                self.engine_choice.setCurrentIndex(index)
            self._applying = False
            self.engine_note.setText(engines.SUMMARIES.get(engine, ''))
        else:
            self.engine_note.setText('')
        self.refresh_moods()
        self.refresh_controls()

    def section_mood(self, segment):
        """The mood clip this section will be generated from next time, or None for the main reference."""
        return moods.resolve(self.session, segment)[0] if self.session else None

    def refresh_moods(self):
        """Offer Auto plus the narration's mood clips, showing what Auto would pick."""
        row, segment = self.selected_segment()
        available = moods.names(self.session)
        self._applying = True
        self.mood_choice.clear()
        if segment is not None and available:
            guess = moods.detect(segment.get('text', ''), available)
            self.mood_choice.addItem(f'Auto · {moods.LABELS.get(guess, guess)}', moods.AUTO)
            for name in available:
                self.mood_choice.addItem(moods.LABELS.get(name, name), name)
            index = self.mood_choice.findData(segment.get('mood') or moods.AUTO)
            self.mood_choice.setCurrentIndex(max(index, 0))
        else:
            self.mood_choice.addItem('One reference' if segment is not None else '', moods.AUTO)
        self._applying = False

    def mood_chosen(self):
        """Remember the mood this section should use next time. Existing takes are untouched."""
        if self._applying:
            return
        row, segment = self.selected_segment()
        mood = self.mood_choice.currentData()
        if segment is None or self.jobs.busy or (segment.get('mood') or moods.AUTO) == mood:
            return
        if mood == moods.AUTO:
            segment.pop('mood', None)
        else:
            segment['mood'] = mood
        save_session(self.session)
        self.refresh_table()
        self.status.setText(f'Section {row + 1} will use the {moods.label(mood)} clip. '
                            'Press Generate section for a new take; existing takes are kept.')

    def refresh_takes(self):
        """List every recording this section has, newest last, marking the one in use."""
        self.takes.clear()
        row, segment = self.selected_segment()
        if not segment:
            return
        chosen = segment.get('selected_take')
        for take in takes_of(segment):
            stale = take_is_stale(segment, take)
            missing = not (DATA / take['file']).is_file() if take.get('file') else True
            bits = [engines.label(take.get('engine', engines.DEFAULT))]
            if take.get('mood'):
                bits.append(moods.LABELS.get(take['mood'], take['mood']))
            if take.get('seconds'):
                bits.append(f"{take['seconds']:.1f} s")
            if take.get('verified') is False:
                bits.append('needs review')
            elif take.get('verified') is not True:
                bits.append('unchecked')
            elif (take.get('verification_version') or 1) < 2:
                bits.append('legacy check — listen to edges')
            warns = [f for f in (take.get('quality') or []) if f.get('severity') == 'warn']
            if warns:
                bits.append('⚠ ' + ', '.join(QUALITY_LABELS.get(f['code'], f['code']) for f in warns))
            if stale:
                bits.append('stale — words changed')
            if missing:
                bits.append('file missing')
            mark = '●  ' if take['id'] == chosen else '○  '
            item = QListWidgetItem(mark + ' · '.join(bits))
            item.setData(Qt.ItemDataRole.UserRole, take['id'])
            if stale or missing:
                item.setForeground(QColor('#8a93a0'))
            notes = ''.join('\n• ' + f['message'] for f in (take.get('quality') or []))
            item.setToolTip(('In use. ' if take['id'] == chosen else '')
                            + notes.lstrip('\n') + ('\n' if notes else '')
                            + f"Recorded {take.get('created', '')[:19].replace('T', ' ')}"
                            + (f"\nexaggeration {take['engine_config']['exaggeration']}"
                               if take.get('engine_config', {}).get('exaggeration') is not None
                               else ''))
            self.takes.addItem(item)
            if take['id'] == chosen:
                self.takes.setCurrentItem(item)

    def current_take(self):
        item = self.takes.currentItem()
        if not item:
            return None, None
        row, segment = self.selected_segment()
        take_id = item.data(Qt.ItemDataRole.UserRole)
        return segment, next((t for t in takes_of(segment or {}) if t['id'] == take_id), None)

    def use_take(self, *args):
        """Switch the narration to an existing recording. Never regenerates."""
        segment, take = self.current_take()
        if self.jobs.busy or not segment or not take:
            return
        if take['id'] == segment.get('selected_take'):
            return
        if take_is_stale(segment, take):
            self.show_error('That take was recorded from different words. '
                            'Generate this section again, or pick a take that matches.')
            return
        if not (DATA / take['file']).is_file():
            self.show_error('That take\u2019s audio file is missing.')
            return
        choose_take(segment, take['id'])
        self.session['output'] = None          # the narration must be reassembled
        self.output_path = None
        self.clear_preview()
        save_session(self.session)
        self.refresh_table()
        self.refresh_takes()
        self.set_preview(DATA / segment['file'], f'SECTION {self.table.currentRow() + 1} TAKE')
        self.status.setText(f"Using the {engines.label(take['engine'])} take. "
                            'Press Generate narration to reassemble.')

    def play_take(self):
        segment, take = self.current_take()
        if not take or not take.get('file'):
            return
        path = DATA / take['file']
        if not path.is_file():
            self.show_error('That take\u2019s audio file is missing.')
            return
        self.set_preview(path, f"TAKE · {engines.label(take.get('engine', engines.DEFAULT))}", True)

    def main_engine_chosen(self):
        """The engine for the narration as a whole. Sections may still override it."""
        if self._applying:
            return
        engine = self.main_engine.currentData()
        if self.session and self.session.get('engine') != engine:
            self.session['engine'] = engine
            save_session(self.session)
            self.refresh_table()       # sections without their own choice follow this one
        self.autosave.start()
        overrides = sum(1 for seg in (self.session or {}).get('segments', [])
                        if seg.get('engine') and seg['engine'] != engine)
        self.status.setText(
            f'New sections will use {engines.label(engine)}.'
            + (f' {overrides} section(s) keep their own engine.' if overrides else '')
            + ' Existing takes are untouched.')

    def engine_chosen(self):
        """Remember the engine this section should use next time."""
        if self._applying:
            return
        row, segment = self.selected_segment()
        engine = self.engine_choice.currentData()
        self.engine_note.setText(engines.SUMMARIES.get(engine, ''))
        if segment is None or self.jobs.busy:
            return
        if segment.get('engine') != engine:
            segment['engine'] = engine
            save_session(self.session)
            self.refresh_table()

    def generate_alternative(self):
        """Record this section with the engine it is not currently using."""
        row, segment = self.selected_segment()
        if self.jobs.busy or segment is None:
            return
        current = self.section_engine(segment)
        other = next((e for e in engines.available() if e != current), None)
        if other is None:
            self.show_error('Only one engine is installed, so there is no alternative to try.')
            return
        self.regenerate_section(engine=other)

    def save_section_edit(self):
        row, segment = self.selected_segment()
        if self.jobs.busy or segment is None:
            return
        if self.script.toPlainText().strip() != self.session['script']:
            self.show_error('The Script tab has newer edits. Generate it first to rebuild the sections, or reopen this saved narration.')
            return
        text = self.section_text.toPlainText().strip()
        if not text or len(text) > 400:
            self.show_error('Keep an individual section between 1 and 400 characters. For larger edits, use the Script tab.')
            return
        if text == segment['text']:
            return
        plan = direction.parse(text)
        if plan.problems:
            self.show_error(' '.join(plan.problems))
            return
        takes_of(segment)
        segment['text'] = text
        requested_engine = segment.get('engine')
        sync_selected(segment)
        if requested_engine:
            segment['engine'] = requested_engine
        self.session['output'] = None
        self.session['script'] = session_script(self.session['segments'])
        self.script.setPlainText(self.session['script'])
        self.output_path = None
        self.clear_preview()
        save_session(self.session)
        self.refresh_table()
        self.status.setText('Section updated. Generate resumes pending sections; other audio is preserved.')

    def regenerate_section(self, checked=False, engine=None):
        row, segment = self.selected_segment()
        if self.jobs.busy or segment is None:
            return
        if self.script.toPlainText().strip() != self.session['script']:
            self.show_error('Generate the edited script first to rebuild its sections.')
            return
        self.save_section_edit()
        row, segment = self.selected_segment()
        if segment is None or self.section_text.toPlainText().strip() != segment['text']:
            return
        engine = engines.normalize(engine or self.section_engine(segment))
        self.start_job({'action': 'generate', 'session': str(session_path(self.session)),
                        'indices': [row], 'regenerate': True, 'engine': engine,
                        'engine_config': segment.get('engine_config') or {}})

    def engines_needed(self, job):
        """Engines a generate job will load: none for a timing-only reassembly."""
        if job.get('action') != 'generate' or not self.session:
            return []
        if job.get('engine'):
            return [engines.normalize(job['engine'])]
        indices = job.get('indices')
        segments = self.session['segments']
        chosen = [segments[i] for i in indices] if indices is not None else \
            [s for s in segments if segment_needs_audio(s, DATA)]
        return sorted({engines.normalize(s.get('engine') or self.session.get('engine') or engines.DEFAULT)
                       for s in chosen})

    def admit(self, job):
        """Check live resources before a model could load. Returns True to start now."""
        needed = self.engines_needed(job)
        if not needed:
            return True
        reading = resources.snapshot(DATA)
        decision, reason = resources.admission(needed, reading, self._resource_history)
        self._resource_history = [h for h in self._resource_history if reading['t'] - h['t'] <= 120] + [reading]
        if decision == resources.ADMIT:
            return True
        if decision == resources.REFUSE and reading.get('panic'):
            box = QMessageBox(self)
            box.setWindowTitle('Voice Studio')
            box.setText(reason)
            box.setInformativeText('The report is described in docs/INCIDENT-2026-10-24-RESTART.md. Continue only if '
                                   'you have reviewed it. Voice Studio will still check memory before every model load.')
            review = box.addButton('I have reviewed it — continue', QMessageBox.ButtonRole.AcceptRole)
            box.addButton('Not now', QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is review:
                resources.acknowledge_panic()
                return self.admit(job)
            self.status.setText('Generation not started. ' + reason)
            return False
        if decision == resources.REFUSE:
            self.show_error(reason)
            return False
        self.enter_waiting(job, reason)
        return False

    def enter_waiting(self, job, reason):
        # The attempt count is reset only by a fresh Generate (start_job), never by a retry.
        self._waiting_job = job
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        auto = self._wait_attempts < self.WAIT_RETRY_LIMIT
        resuming = bool(getattr(self, '_resumes', 0))
        self.status.setText(('Paused while your Mac frees memory. ' if resuming else 'Waiting for enough free memory. ')
                            + ('It will continue automatically. ' if auto else 'Press Retry now when you are ready. ')
                            + 'Your apps and projects are untouched.')
        self.status.setToolTip(reason)
        if self._wait_attempts < self.WAIT_RETRY_LIMIT:
            self.wait_timer.start()
        else:
            self.wait_timer.stop()
        self.refresh_controls()

    def retry_waiting(self):
        if self._waiting_job is None or self.jobs.busy:
            self.wait_timer.stop()
            return
        self._wait_attempts += 1
        job, self._waiting_job = self._waiting_job, None
        self.wait_timer.stop()
        if self.admit(job):
            self.start_job(job, admitted=True)
        elif self._waiting_job is not None and self._wait_attempts >= self.WAIT_RETRY_LIMIT:
            self.enter_waiting(self._waiting_job, 'Still waiting for enough available memory.')

    def stop_waiting(self):
        self.wait_timer.stop()
        self._waiting_job = None
        self.status.setText('Stopped waiting. Nothing was generated; press Generate when you are ready.')
        self.refresh_controls()

    def start_job(self, job, admitted=False):
        if not admitted and job.get('action') == 'generate':
            self._wait_attempts = 0
            self._resumes = 0
            self._done_indices = set()
            if not self.admit(job):
                return
        self._waiting_job = None
        self.wait_timer.stop()
        self._worker_wait = None
        self._safe_stop = None
        self.job_action = job['action']
        self._last_job = job
        if job['action'] == 'generate' and self.session:
            # Progress counts the whole narration, so it does not jump back after a pause.
            segments = self.session['segments']
            pending = len(job['indices']) if job.get('indices') is not None else \
                sum(1 for seg in segments if segment_needs_audio(seg, DATA))
            self._progress_offset, self._progress_total = len(segments) - pending, len(segments)
        else:
            self._progress_offset, self._progress_total = 0, None
        self._profile_warning = ''
        self._incomplete = []
        self.player.pause()
        self.status.setToolTip('')
        self.progress.setRange(0, 0)
        self.status.setText('Starting local task…')
        try:
            self.jobs.start(job)
        except Exception as exc:
            self.show_error(str(exc))
        self.refresh_controls()

    def on_event(self, event):
        kind = event['kind']
        if kind in ('status', 'progress', 'warning'):
            self.status.setText(event['message'])
            if kind == 'warning':
                self._profile_warning = event['message']
        if kind in ('progress', 'segment'):
            total = getattr(self, '_progress_total', None)
            if total and self.job_action == 'generate' and not self._progress_offset + event['total'] > total:
                self.progress.setRange(0, total)
                self.progress.setValue(self._progress_offset + event['completed'])
            else:
                self.progress.setRange(0, max(1, event['total']))
                self.progress.setValue(event['completed'])
        if kind == 'loaded':
            self.model_badge.setText('●  Apple Metal active')
        if kind == 'resource_wait':
            self._worker_wait = event
        if kind == 'safely_stopped':
            self._safe_stop = event
        if kind == 'segment':
            self._done_indices = getattr(self, '_done_indices', set()) | {event['index']}
        if kind == 'incomplete':
            # Keep the audio, but never let an incomplete section pass as finished.
            self._incomplete.append(event)
            self.status.setText(event['detail'] + ' Keeping the closest take.')
        if kind == 'unverified':
            known = {e['index'] for e in self._incomplete}
            for index in event['indices']:
                if index not in known:
                    self._incomplete.append({'index': index, 'detail':
                        f'Section {index + 1}: the selected take needs listening review.'})
        if kind == 'profile':
            self.profile = None
            self.load_profiles(event['profile']['id'])
            self.tabs.setCurrentIndex(2)
            self.set_preview(DATA / event['profile']['reference'], 'VOICE REFERENCE')
        elif kind == 'transcript':
            self.transcript.setPlainText(event['text'])
            self.save_reference(silent=True)
        elif kind == 'segment':
            self.session = read_json(session_path(self.session))
            self.output_path = None
            self.refresh_table()
            self.status.setText(f"Section {event['index'] + 1} saved · {event['seconds']:.1f} s audio · {event['elapsed']:.0f} s generation")
        elif kind == 'output':
            self.output_path = Path(event['file'])
            self.set_preview(self.output_path, 'FULL NARRATION')
        elif kind == 'exported':
            self.last_export = event['file']
            check = event.get('validation')
            if check and check['measured']:
                m = check['measured']
                summary = f"{m['seconds']:.1f} s · {m['lufs']:.1f} LUFS · peak {m['true_peak_db']:.1f} dBFS"
                notes = '; '.join(w['message'] for w in check['warnings'])
                self.status.setText(f"Exported: {event['file']}  ({summary})" + (f'. Check: {notes}' if notes else '. Checked ✓'))
            else:
                self.status.setText('Exported: ' + event['file'])
        elif kind == 'error':
            self.status.setText(event['message'])

    def on_finished(self, success, message):
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if success else 0)
        if self.session and self.job_action == 'generate':
            self.session = read_json(session_path(self.session))
            self.output_path = DATA / self.session['output'] if self.session.get('output') else None
            if not self.output_path and self.preview_label.text() == 'FULL NARRATION':
                self.clear_preview()
            self.refresh_table()
            self.load_history()
        if self._worker_wait and not message:
            # The worker refused to load a model; nothing was loaded and nothing was lost.
            wait, self._worker_wait = self._worker_wait, None
            job = {k: v for k, v in getattr(self, '_last_job', {}).items() if k != 'stop_file'}
            if wait.get('decision') == resources.WAIT and job:
                self.enter_waiting(job, wait['message'])
            else:
                self.status.setText('Generation not started: ' + wait['message'])
        elif self._safe_stop and not message:
            # A pause, not a failure: the model has been released; continue once memory recovers.
            stop, self._safe_stop = self._safe_stop, None
            job = {k: v for k, v in getattr(self, '_last_job', {}).items() if k not in ('stop_file', 'regenerate')}
            if job.get('indices') is not None:       # never re-record a section this run already finished
                job['indices'] = [i for i in job['indices'] if i not in getattr(self, '_done_indices', set())]
            if job and getattr(self, '_resumes', 0) < self.AUTO_RESUME_LIMIT:
                self._resumes = getattr(self, '_resumes', 0) + 1
                self._wait_attempts = 0
                self.enter_waiting(job, stop['message'])
            else:
                self.status.setText('Paused several times to protect your Mac. Completed sections are saved; '
                                    'press Generate to continue.')
                self.status.setToolTip(stop['message'])
        elif message:
            self.status.setText(message)
            if not self.jobs.cancelled and not self._closing and not self.jobs.safety_reason:
                QMessageBox.warning(self, 'Task could not finish', message)
        elif success and self._incomplete and self.job_action == 'generate':
            rows = ', '.join(str(e['index'] + 1) for e in self._incomplete)
            self.status.setText(f'Audio saved. Section {rows} has takes to review. '
                                'Press Play to listen, or compare takes in Sections.')
            self.status.setToolTip('\n'.join(e['detail'] for e in self._incomplete))
        elif success:
            messages = {'generate': 'Generation complete.',
                        'prepare': 'Voice saved. Listen to the sample and check its transcript before generating.',
                        'transcribe': 'Transcript saved. Review it against the reference recording.',
                        'export': 'Exported: ' + getattr(self, 'last_export', '')}
            self.status.setText(self._profile_warning or messages.get(self.job_action, 'Ready.'))
        self.refresh_controls()
        self.save_draft()
        if self._closing:
            self.close()

    def cancel(self):
        if self._waiting_job is not None and not self.jobs.busy:
            self.stop_waiting()
            return
        self.status.setText('Cancelling the task…')
        self.cancel_button.setEnabled(False)
        self.jobs.cancel()

    def refresh_controls(self):
        if not hasattr(self, 'generate_button'):
            return
        busy = self.jobs.busy
        for widget in (self.add_voice, self.new_button, self.import_button, self.voice_list, self.history,
                       self.language, self.speed, self.pause, self.title, self.main_engine):
            widget.setEnabled(not busy)
        self.script.setReadOnly(busy)
        self.transcript.setReadOnly(busy)
        self.section_text.setReadOnly(busy)
        self.generate_button.setEnabled(not busy)
        row = self.review_table.currentRow()
        self.review_play.setEnabled(not busy and 0 <= row < len(self.review_joins)
                                    and self.review_joins[row] is not None)
        waiting = self._waiting_job is not None and not busy
        self.cancel_button.setVisible(busy or waiting)
        self.cancel_button.setEnabled(busy or waiting)
        self.cancel_button.setText('Stop waiting' if waiting else 'Cancel')
        self.generate_button.setText('Retry now' if waiting else 'Generate narration')
        ready_voice = bool(self.profile) and has_reference(self.profile)
        for button in (self.play_ref, self.auto_transcribe, self.save_ref):
            button.setEnabled(ready_voice and not busy)
        self.replace_ref.setEnabled(bool(self.profile) and not busy)
        row, segment = self.selected_segment()
        self.apply_section.setEnabled(segment is not None and not busy)
        self.regenerate.setEnabled(segment is not None and not busy)
        self.alternative.setEnabled(segment is not None and not busy
                                    and len(engines.available()) > 1)
        self.engine_choice.setEnabled(segment is not None and not busy)
        self.mood_choice.setEnabled(segment is not None and not busy and bool(moods.names(self.session)))
        self.preview_section.setEnabled(bool(segment and segment.get('file')))
        _, take = self.current_take()
        self.play_take_button.setEnabled(bool(take and take.get('file')))
        self.use_take_button.setEnabled(bool(take and not busy
                                             and take['id'] != (segment or {}).get('selected_take')))
        current_script = bool(self.session and self.script.toPlainText().strip() == self.session['script'])
        self.export_button.setEnabled(bool(self.output_path and self.output_path.exists()) and current_script and not busy)
        self.full_preview.setEnabled(bool(self.output_path and self.output_path.exists()))
        self.play_button.setEnabled(bool(self.preview_path))

    def set_preview(self, path, title, autoplay=False):
        path = Path(path)
        if not path.exists():
            self.status.setText('This audio file is missing. Regenerate the section.')
            return
        # setSource() already stops and resets playback. An explicit stop() here hangs the
        # Qt FFmpeg backend whenever the player is paused after a seek, so it is left out.
        self.preview_path = str(path)
        self._stall_warned = False
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.preview_label.setText(title)
        self.wave.peaks = []
        self.wave.progress = 0
        self.wave.update()
        task = WaveTask(path)
        self._wave_tasks.append(task)
        task.signals.ready.connect(self.wave_ready)
        task.signals.ready.connect(lambda p, peaks, t=task: self._wave_tasks.remove(t) if t in self._wave_tasks else None)
        QThreadPool.globalInstance().start(task)
        self.refresh_controls()
        if autoplay:
            self.start_playback()

    def wave_ready(self, path, peaks):
        if path == self.preview_path:
            self.wave.peaks = peaks
            self.wave.update()

    def clear_preview(self):
        self.player.setSource(QUrl())
        self.preview_path = None
        self.wave.peaks = []
        self.wave.update()
        self.preview_label.setText('AUDIO PREVIEW')

    def play_reference(self):
        if self.profile:
            self.set_preview(DATA / self.profile['reference'], 'VOICE REFERENCE · ' + self.profile['name'], True)

    def play_section(self):
        row, segment = self.selected_segment()
        if segment and segment.get('file'):
            self.set_preview(DATA / segment['file'], f'SECTION {row + 1}', True)

    def run_review(self):
        if not self.session or not self.session.get('segments') \
                or not all(seg.get('file') for seg in self.session['segments']):
            self.review_table.setRowCount(0)
            self.review_joins = []
            self.review_summary.setText('Generate every section to review how they fit together.')
            return
        self.review_summary.setText('Measuring sections and joins…')
        task = ReviewTask(read_json(session_path(self.session)) or self.session, DATA)
        task.signals.ready.connect(self.show_review)
        self._review_task = task
        QThreadPool.globalInstance().start(task)

    def show_review(self, result):
        rows = []
        if result.get('error'):
            self.review_summary.setText('Review failed: ' + result['error'])
            return
        for section in result['sections']:
            for item in section['flags']:
                rows.append((f"Section {section['index']}", item, None))
        for join in result['joins']:
            for item in join['flags']:
                rows.append((f"Join {join['after']} → {join['after'] + 1}", item, join['after'] - 1))
        self.review_joins = [r[2] for r in rows]
        self.review_table.setRowCount(len(rows))
        for row, (where, item, _) in enumerate(rows):
            kind = 'Check' if item['severity'] == 'warn' else 'Note'
            for column, text in enumerate((where, kind, item['message'])):
                self.review_table.setItem(row, column, QTableWidgetItem(text))
            self.review_table.resizeRowToContents(row)
        checks = sum(1 for r in rows if r[1]['severity'] == 'warn')
        self.review_summary.setText(
            (f'{checks} thing(s) worth a listen and {len(rows) - checks} note(s).' if rows
             else 'Nothing unusual measured at the joins: loudness, pitch, brightness and gaps look consistent.')
            + ' Level, pitch and brightness are compared across each join; a flag is a reason to listen, not proof of a problem.')
        self.refresh_controls()

    def play_join(self):
        row = self.review_table.currentRow()
        if row < 0 or row >= len(self.review_joins) or self.review_joins[row] is None:
            self.status.setText('Select a row about a join to hear it.')
            return
        import copy
        from .audio import join_segments
        index = self.review_joins[row]
        pair = copy.deepcopy(self.session['segments'][index:index + 2])
        pair[0].pop('lead_pause', None)
        target = DATA / 'cache' / 'review' / f'join-{index + 1}.wav'
        try:
            join_segments({**self.session, 'segments': pair}, DATA, target)
        except Exception as exc:
            self.status.setText('Could not build that join: ' + str(exc))
            return
        self.set_preview(target, f'JOIN {index + 1} → {index + 2}', True)

    def play_full(self):
        if self.output_path:
            self.set_preview(self.output_path, 'FULL NARRATION', True)

    def toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            if self.player.position() >= self.player.duration():
                self.player.setPosition(0)
            self.start_playback()

    def start_playback(self):
        # Re-resolve even if a device notification was missed while a dialog was open.
        if self.refresh_output_devices():
            self.player.play()
        else:
            self.status.setText('No audio output is connected. Connect speakers or headphones, then press Play.')

    def refresh_output_devices(self):
        selected = QMediaDevices.defaultAudioOutput()
        current = self.audio_output.device()
        if selected.isNull():
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
            return False
        if current.isNull() or bytes(current.id()) != bytes(selected.id()):
            # Preserve the existing QAudioOutput: replacing it can crash Qt's backend.
            self.audio_output.setDevice(selected)
            self._stall_position, self._stall_ticks, self._stall_warned = -1, 0, False
        return True

    def play_state_changed(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText('❚❚' if playing else '▶')
        self.play_button.setToolTip('Pause' if playing else 'Play')
        if playing:
            self._stall_position, self._stall_ticks = -1, 0
            self.stall_watch.start()
        else:
            self.stall_watch.stop()

    def output_device_name(self):
        device = self.audio_output.device()
        return device.description() if device and not device.isNull() else 'the system output'

    def check_playback_progress(self):
        """Playing, but the clock is not moving: the chosen output is not taking audio."""
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self.stall_watch.stop()
            return
        position = self.player.position()
        if position != self._stall_position:
            self._stall_position, self._stall_ticks = position, 0
            return
        self._stall_ticks += 1
        if self._stall_ticks < 4 or self._stall_warned:
            return
        self._stall_warned = True
        self.stall_watch.stop()
        others = [d.description() for d in QMediaDevices.audioOutputs()
                  if d.description() != self.output_device_name()]
        self.show_error(
            f'Playback is not advancing on \u201c{self.output_device_name()}\u201d. '
            'Check that the device is connected and its volume is audible.\n\n'
            'Voice Studio follows the system output. Check System Settings → Sound'
            + (f', such as {others[0]}.' if others else '.'))

    @staticmethod
    def timecode(ms):
        seconds = int(ms / 1000)
        return f'{seconds // 60}:{seconds % 60:02d}'

    def position_changed(self, position):
        if not self.timeline.isSliderDown():
            self.timeline.setValue(position)
        self.wave.progress = position / max(1, self.player.duration())
        self.wave.update()
        self.time_label.setText(f'{self.timecode(position)} / {self.timecode(self.player.duration())}')

    def duration_changed(self, duration):
        self.timeline.setRange(0, duration)
        self.position_changed(self.player.position())

    def export(self):
        if self.jobs.busy or not self.output_path:
            return
        if not self.session or self.script.toPlainText().strip() != self.session['script']:
            self.show_error('Generate the edited script before exporting, or reopen the saved narration from Recent narrations.')
            return
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        default = str(Path.home() / 'Music' / (slug(self.title.text()) + '-' + stamp + '.mp3'))
        path, selected = QFileDialog.getSaveFileName(self, 'Export narration', default, 'High-quality MP3 (*.mp3);;24-bit WAV (*.wav)')
        if path:
            if Path(path).suffix.lower() not in ('.wav', '.mp3'):
                path += '.wav' if 'WAV' in selected else '.mp3'
            self.start_job({'action': 'export', 'source': str(self.output_path), 'destination': path})

    def closeEvent(self, event):
        self.save_reference(silent=True)
        self.save_draft()
        if self.jobs.busy:
            self._closing = True
            self.jobs.cancel()
            self.status.setText('Stopping the local task before closing…')
            event.ignore()
            return
        self.player.setSource(QUrl())
        QThreadPool.globalInstance().waitForDone(3000)
        event.accept()

def main():
    initialize()
    os.environ.update(offline_environment())
    app = QApplication(sys.argv)
    app.setApplicationName('Voice Studio')
    app.setApplicationDisplayName('Voice Studio')
    app.setOrganizationName('VoiceStudio')
    app.setStyle('Fusion')
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor('#15171b'))
    palette.setColor(QPalette.ColorRole.WindowText, QColor('#e5e8ed'))
    palette.setColor(QPalette.ColorRole.Base, QColor('#111419'))
    palette.setColor(QPalette.ColorRole.Text, QColor('#e5e8ed'))
    palette.setColor(QPalette.ColorRole.Button, QColor('#2a3039'))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor('#e5e8ed'))
    app.setPalette(palette)
    lock = QLockFile(str(DATA / 'desktop.lock'))
    if not lock.tryLock(100):
        QMessageBox.information(None, 'Voice Studio is already open', 'Switch to the existing Voice Studio window.')
        return
    window = VoiceStudio()
    window.show()
    sys.exit(app.exec())
