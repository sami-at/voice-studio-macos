import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from PySide6.QtCore import QThread, Signal, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit, QLineEdit, QFileDialog, QMessageBox, QProgressBar)

class Worker(QThread):
    finished_file = Signal(str)
    failed = Signal(str)
    def __init__(self, reference, transcript, script, output):
        super().__init__()
        self.reference, self.transcript, self.script, self.output = reference, transcript, script, output
    def run(self):
        try:
            if not shutil.which('ffmpeg'):
                raise RuntimeError('FFmpeg is missing. Install it with: brew install ffmpeg')
            if not shutil.which('f5-tts_infer-cli'):
                raise RuntimeError('F5-TTS CLI is missing. Install dependencies from requirements.txt.')
            with tempfile.TemporaryDirectory() as temp:
                ref = os.path.join(temp, 'reference.wav')
                subprocess.run(['ffmpeg','-y','-i',self.reference,'-ac','1','-ar','24000',ref],check=True,capture_output=True,text=True)
                # The CLI writes a generated.wav file in the specified directory.
                command = ['f5-tts_infer-cli','--model','F5TTS_v1_Base','--ref_audio',ref,'--ref_text',self.transcript,'--gen_text',self.script,'--output_dir',temp,'--output_file','generated.wav']
                result = subprocess.run(command,capture_output=True,text=True)
                if result.returncode:
                    raise RuntimeError(result.stderr[-2500:] or result.stdout[-2500:])
                generated = os.path.join(temp,'generated.wav')
                if not os.path.isfile(generated):
                    raise RuntimeError('The model did not create generated.wav.\n'+result.stdout[-1500:])
                if self.output.lower().endswith('.mp3'):
                    subprocess.run(['ffmpeg','-y','-i',generated,'-codec:a','libmp3lame','-qscale:a','2',self.output],check=True,capture_output=True,text=True)
                else:
                    shutil.copyfile(generated,self.output)
            self.finished_file.emit(self.output)
        except Exception as exc:
            self.failed.emit(str(exc))

class VoiceStudio(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Voice Studio — Local AI Voiceovers')
        self.resize(760, 680)
        self.reference = None
        self.output = None
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.audio.setVolume(0.8)
        root = QVBoxLayout(self)
        title = QLabel('Voice Studio')
        title.setStyleSheet('font-size: 27px; font-weight: bold;')
        root.addWidget(title)
        root.addWidget(QLabel('1. Script — paste text or import a .txt file'))
        self.script = QTextEdit()
        self.script.setPlaceholderText('Paste your narration script here...')
        root.addWidget(self.script)
        import_btn = QPushButton('Import TXT')
        import_btn.clicked.connect(self.import_txt)
        root.addWidget(import_btn)
        root.addWidget(QLabel('2. Reference recording — use a clean speech sample, ideally 5–15 seconds'))
        self.ref_label = QLabel('No audio selected')
        ref_row = QHBoxLayout()
        select_ref = QPushButton('Choose MP3 / WAV')
        select_ref.clicked.connect(self.choose_ref)
        ref_row.addWidget(select_ref)
        ref_row.addWidget(self.ref_label)
        root.addLayout(ref_row)
        root.addWidget(QLabel('3. Exact transcript of the words spoken in the reference recording'))
        self.transcript = QLineEdit()
        self.transcript.setPlaceholderText('Type exactly what you said in the recording...')
        root.addWidget(self.transcript)
        self.generate = QPushButton('Generate Voiceover')
        self.generate.clicked.connect(self.start_generation)
        root.addWidget(self.generate)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        root.addWidget(self.progress)
        self.status = QLabel('Ready — first generation may download the model.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.preview = QPushButton('Play / Pause Last Output')
        self.preview.setEnabled(False)
        self.preview.clicked.connect(self.toggle_playback)
        root.addWidget(self.preview)
        root.addWidget(QLabel('Your files stay on this Mac. The model may need an initial download.'))
        self.setStyleSheet('QWidget { background: #171a20; color: #eef0f6; font-size: 14px; } QTextEdit, QLineEdit { background: #252a34; border: 1px solid #404757; border-radius: 7px; padding: 8px; } QPushButton { background: #343d54; border-radius: 7px; padding: 10px; } QPushButton:hover { background: #465476; } QPushButton:disabled { color: #7c8290; }')
    def import_txt(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open script', '', 'Text Files (*.txt)')
        if path:
            self.script.setPlainText(Path(path).read_text(encoding='utf-8-sig'))
    def choose_ref(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose reference', '', 'Audio (*.mp3 *.wav *.m4a *.flac)')
        if path:
            self.reference = path
            self.ref_label.setText(Path(path).name)
    def start_generation(self):
        script = self.script.toPlainText().strip()
        transcript = self.transcript.text().strip()
        if not (self.reference and script and transcript):
            QMessageBox.warning(self,'Missing input','Select a reference recording, provide its exact transcript, and enter your script.')
            return
        output, _ = QFileDialog.getSaveFileName(self,'Save voiceover',str(Path.home()/'Desktop'/'voiceover.mp3'),'MP3 (*.mp3);;WAV (*.wav)')
        if not output:
            return
        self.generate.setEnabled(False)
        self.progress.setRange(0,0)
        self.status.setText('Generating... this can take several minutes on the first run.')
        self.worker = Worker(self.reference,transcript,script,output)
        self.worker.finished_file.connect(self.on_done)
        self.worker.failed.connect(self.on_error)
        self.worker.start()
    def on_done(self,path):
        self.generate.setEnabled(True)
        self.progress.setRange(0,1)
        self.progress.setValue(1)
        self.output = path
        self.preview.setEnabled(True)
        self.player.setSource(QUrl.fromLocalFile(path))
        self.status.setText('Saved: '+path)
    def on_error(self,error):
        self.generate.setEnabled(True)
        self.progress.setRange(0,1)
        self.progress.setValue(0)
        self.status.setText('Generation failed — see error dialog.')
        QMessageBox.critical(self,'Voice generation failed',error)
    def toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = VoiceStudio()
    window.show()
    sys.exit(app.exec())
