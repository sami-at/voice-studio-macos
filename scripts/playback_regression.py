"""Exercise the user's saved audio through Qt on an isolated library copy."""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'samples/playback-system'
os.environ['VOICE_STUDIO_DATA'] = str(OUT / 'test-data')
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QThreadPool, QUrl
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication, QMessageBox
from voice_studio.ui import VoiceStudio
from voice_studio.storage import read_json
from voice_studio.config import DATA


app = QApplication([])
window = VoiceStudio()
window.show()
warnings = []
QMessageBox.warning = lambda *args: warnings.append(str(args[-1]))
session = read_json(DATA / 'sessions/2ba2d3fa509d4c37849199af710cc2e3/project.json')
window.load_session(session)
app.processEvents()
window.job_action = 'generate'
window.on_event({'kind': 'unverified', 'indices': [3]})
window.on_finished(True, '')
assert not warnings
assert 'takes to review' in window.status.text()
assert not hasattr(window, 'output_choice')
assert window.play_button.isEnabled() and window.full_preview.isEnabled()
# Exercise the notification without touching the system's actual routing.
window.media_devices.audioOutputsChanged.emit()
window.play_full()
deadline = time.monotonic() + 15
while window.player.position() < 5000 and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(.03)
assert window.player.position() >= 5000
assert window.player.error() == QMediaPlayer.Error.NoError
window.player.pause()
window.player.setPosition(2000)
window.play_section()
deadline = time.monotonic() + 15
while window.player.position() < 400 and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(.03)
assert window.player.position() >= 400
window.player.pause()
window.tabs.setCurrentIndex(1)
for width, height in ((1240,850), (980,740)):
    window.resize(width,height)
    app.processEvents()
    for control in (window.play_button, window.regenerate):
        point = control.mapTo(window,control.rect().bottomRight())
        assert point.x() < width and point.y() < height, (control.objectName(), point.x(), point.y(), width, height)
window.resize(1240,850)
app.processEvents()
window.grab().save(str(OUT / 'playback-ui.png'))
result = {'review_notice_is_nonmodal': True, 'output_selector_removed': True,
          'backend': os.environ.get('QT_MEDIA_BACKEND'), 'device_change_signal_handled': True,
          'system_output': window.output_device_name(), 'full_narration_advances': True,
          'section_after_seek_advances': True, 'controls_fit_both_sizes': True,
          'source_project': session['id']}
(OUT / 'playback-results.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
window.player.setSource(QUrl())
window.close()
QThreadPool.globalInstance().waitForDone(3000)
app.processEvents()
