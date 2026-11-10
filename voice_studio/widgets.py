import math
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget)
from .config import STT_MODEL

# One design system for the whole app. Surfaces step up in lightness (window -> sidebar/inputs
# -> cards -> hover), one accent colour marks the main action and the current selection, and
# every control shares the same 8 px radius so nothing looks bolted on.
ASSETS = Path(__file__).resolve().parent.parent / 'assets' / 'ui'
STYLE = '''
QWidget { color: #e9ecf1; font-family: ".AppleSystemUIFont", "Helvetica Neue"; font-size: 13px; }
QMainWindow, QDialog { background: #121418; }
QFrame#sidebar { background: #171a1f; border-right: 1px solid #262b33; }
QFrame#card, QWidget#card { background: #1b1f26; border: 1px solid #2a2f38; border-radius: 12px; }
QFrame#plain { background: transparent; border: none; }
QLabel { background: transparent; }
QLabel#brand { font-size: 19px; font-weight: 700; letter-spacing: -0.4px; }
QLabel#heading { font-size: 22px; font-weight: 650; letter-spacing: -0.3px; }
QLabel#subheading { font-size: 14px; font-weight: 600; }
QLabel#eyebrow { font-size: 10px; font-weight: 650; color: #7f8a99; letter-spacing: 1.3px; }
QLabel#field { font-size: 11px; font-weight: 600; color: #8f9aa8; }
QLabel#muted { color: #98a2b0; font-size: 12px; }
QLabel#status { color: #b9c3d0; }
QLabel#badge { color: #8fdcbe; background: #1d3129; border: 1px solid #2c4b3e; border-radius: 10px; padding: 4px 10px; font-size: 11px; font-weight: 600; }
QLabel#badgeOff { color: #e3c487; background: #342c1b; border: 1px solid #54462a; border-radius: 10px; padding: 4px 10px; font-size: 11px; font-weight: 600; }
QPushButton { background: #252a33; border: 1px solid #343b47; border-radius: 8px; padding: 7px 13px; font-weight: 550; }
QPushButton:hover { background: #2e3541; border-color: #4a5463; }
QPushButton:pressed { background: #1f242c; }
QPushButton:disabled { color: #5f6875; background: #1c2026; border-color: #272c34; }
QPushButton:focus { border-color: #7bd3b8; }
QPushButton#primary { background: #7bd3b8; color: #0f221b; border: 1px solid #7bd3b8; padding: 10px 22px; font-weight: 700; font-size: 14px; }
QPushButton#primary:hover { background: #95e0c8; border-color: #95e0c8; }
QPushButton#primary:disabled { background: #2a4239; color: #78948a; border-color: #2a4239; }
QPushButton#accent { background: #1f3a31; color: #a9ecd2; border: 1px solid #2f5646; }
QPushButton#accent:hover { background: #26483c; border-color: #3d7060; }
QPushButton#accent:disabled { background: #1c2026; color: #5f6875; border-color: #272c34; }
QPushButton#quiet { background: transparent; border: 1px solid #2f3540; color: #c3cbd6; }
QPushButton#quiet:hover { background: #222730; border-color: #465060; }
QPushButton#flat { background: transparent; border: none; color: #98a2b0; padding: 4px 6px; text-align: left; font-weight: 600; }
QPushButton#flat:hover { color: #e9ecf1; }
QPushButton#play { background: #7bd3b8; color: #0f221b; border: none; border-radius: 18px; min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; padding: 0; font-size: 14px; font-weight: 700; }
QPushButton#play:hover { background: #95e0c8; }
QPushButton#play:disabled { background: #2a4239; color: #78948a; }
QLineEdit, QTextEdit, QPlainTextEdit, QDoubleSpinBox, QComboBox { background: #14171c; border: 1px solid #2e343e; border-radius: 8px; padding: 7px 10px; selection-background-color: #3b6a5c; }
QLineEdit:hover, QDoubleSpinBox:hover, QComboBox:hover { border-color: #434c5a; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #7bd3b8; }
QLineEdit#titleEdit { background: transparent; border: 1px solid transparent; font-size: 24px; font-weight: 650; letter-spacing: -0.4px; padding: 4px 2px; }
QLineEdit#titleEdit:hover { border-color: #2e343e; }
QLineEdit#titleEdit:focus { background: #14171c; border-color: #7bd3b8; }
QTextEdit#script { font-size: 16px; padding: 18px 20px; border-radius: 12px; background: #161a1f; }
QComboBox { padding-right: 26px; min-height: 18px; }
QComboBox::drop-down { border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: center right; }
QComboBox::down-arrow { image: url(@ASSETS@/chevron-down.svg); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: #1e232b; border: 1px solid #3a4250; selection-background-color: #2a4a3f; outline: none; padding: 4px; }
QDoubleSpinBox { padding-right: 22px; }
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 18px; border: none; background: transparent; }
QDoubleSpinBox::up-arrow { image: url(@ASSETS@/chevron-up.svg); width: 10px; height: 10px; }
QDoubleSpinBox::down-arrow { image: url(@ASSETS@/chevron-down.svg); width: 10px; height: 10px; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { border-radius: 8px; padding: 9px 10px; margin: 0 0 3px 0; color: #c7ced9; }
QListWidget::item:selected { background: #22372f; color: #e6faf1; }
QListWidget::item:hover:!selected { background: #1f242b; }
QListWidget#bordered { background: #14171c; border: 1px solid #2e343e; border-radius: 8px; padding: 4px; }
QTabWidget::pane { border: none; top: 0; }
QTabBar { background: transparent; }
QTabBar::tab { background: transparent; padding: 8px 16px; margin-right: 4px; color: #98a2b0; border: none; border-radius: 8px; font-weight: 600; }
QTabBar::tab:hover { color: #e9ecf1; background: #1c2027; }
QTabBar::tab:selected { color: #e6faf1; background: #22372f; }
QTableWidget { background: #14171c; alternate-background-color: #181c22; border: 1px solid #2a2f38; border-radius: 10px; gridline-color: transparent; selection-background-color: #22372f; selection-color: #e6faf1; outline: none; }
QTableWidget::item { padding: 6px 8px; border: none; }
QHeaderView { background: transparent; }
QHeaderView::section { background: #1b1f26; padding: 8px 9px; border: none; border-bottom: 1px solid #2a2f38; color: #8f9aa8; font-size: 11px; font-weight: 650; }
QProgressBar { background: #232830; border: none; border-radius: 2px; max-height: 4px; min-height: 4px; }
QProgressBar::chunk { background: #7bd3b8; border-radius: 2px; }
QSlider::groove:horizontal { height: 4px; background: #303743; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #7bd3b8; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; height: 14px; margin: -5px 0; background: #e6faf1; border-radius: 7px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #3a424f; min-height: 28px; border-radius: 3px; }
QScrollBar::handle:vertical:hover { background: #4d586a; }
QScrollBar:horizontal { height: 0; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QMenu { background: #1e232b; border: 1px solid #3a4250; padding: 5px; border-radius: 8px; }
QMenu::item { padding: 7px 20px; border-radius: 5px; }
QMenu::item:selected { background: #2a4a3f; }
QToolTip { background: #262d37; color: #eff5f2; border: 1px solid #4a5666; padding: 7px; }
QSplitter::handle { background: transparent; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #434c5a; border-radius: 4px; background: #14171c; }
QCheckBox::indicator:checked { background: #7bd3b8; border-color: #7bd3b8; }
'''.replace('@ASSETS@', str(ASSETS))

def label(text, style=None):
    item = QLabel(text)
    if style:
        item.setObjectName(style)
    return item

class Waveform(QWidget):
    seek = Signal(float)

    def __init__(self):
        super().__init__()
        self.peaks = []
        self.progress = 0
        self.setMinimumHeight(66)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('Click the waveform to seek')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        if not self.peaks:
            painter.setPen(QColor('#56616f'))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Your waveform will appear here')
            return
        maximum = max(max(self.peaks), .001)
        for i, peak in enumerate(self.peaks):
            x = (i + .5) / len(self.peaks) * width
            half = max(1.2, peak / maximum * (height * .43))
            painter.setPen(QPen(QColor('#b6d8cf' if i / len(self.peaks) <= self.progress else '#4c6260'), 2))
            painter.drawLine(int(x), int(height / 2 - half), int(x), int(height / 2 + half))
        painter.setPen(QPen(QColor('#e4f2ec'), 1))
        painter.drawLine(int(width * self.progress), 0, int(width * self.progress), height)

    def mousePressEvent(self, event):
        if self.peaks:
            self.seek.emit(min(1, max(0, event.position().x() / max(1, self.width()))))

class ImportVoiceDialog(QDialog):
    def __init__(self, parent=None, profile=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle('Replace voice sample' if profile else 'Add a voice')
        self.resize(540, 490)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 24, 25, 24)
        layout.setSpacing(14)
        layout.addWidget(label('A voice, ready for your next story.', 'heading'))
        hint = label('Choose a clean recording of your voice. A 5–15 second passage\nwith one speaker and no music usually works best.', 'muted')
        layout.addWidget(hint)
        form = QFormLayout()
        self.name = QLineEdit(profile['name'] if profile else '')
        self.name.setPlaceholderText('e.g. My narration voice')
        form.addRow('Voice name', self.name)
        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText('MP3, WAV, M4A or FLAC')
        browse = QPushButton('Browse…')
        browse.clicked.connect(self.browse)
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        form.addRow('Recording', row)
        trim = QHBoxLayout()
        self.start = QDoubleSpinBox()
        self.start.setRange(0, 86400)
        self.start.setSuffix(' s start')
        self.duration = QDoubleSpinBox()
        self.duration.setRange(3, 30)
        self.duration.setValue(12)
        self.duration.setSuffix(' s window')
        trim.addWidget(self.start)
        trim.addWidget(self.duration)
        form.addRow('Sample window', trim)
        layout.addLayout(form)
        self.auto = QCheckBox('Transcribe the selected sample offline')
        self.auto.setChecked((STT_MODEL / '.complete').exists())
        layout.addWidget(self.auto)
        self.transcript = QTextEdit()
        self.transcript.setPlaceholderText('Or enter the exact words spoken in the selected window.\nYou can review and correct the transcript after importing.')
        self.transcript.setMaximumHeight(100)
        layout.addWidget(self.transcript)
        self.error = label('', 'muted')
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Prepare voice')
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose a voice recording', '', 'Audio or video (*.mp3 *.wav *.m4a *.flac *.mp4 *.mov)')
        if path:
            self.path.setText(path)
            if not self.name.text():
                self.name.setText(Path(path).stem)

    def validate(self):
        if not Path(self.path.text()).is_file():
            self.error.setText('Choose an existing audio recording.')
            return
        if not self.name.text().strip():
            self.error.setText('Give this voice a name.')
            return
        self.accept()

    def job(self):
        return {'action': 'prepare', 'source': self.path.text(), 'name': self.name.text(),
                'start': self.start.value(), 'duration': self.duration.value(),
                'transcript': self.transcript.toPlainText(), 'transcribe': self.auto.isChecked(),
                'profile_id': self.profile['id'] if self.profile else None}
