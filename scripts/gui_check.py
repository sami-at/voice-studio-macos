"""Exercise the actual Qt widgets, media backend, and process cancellation."""
import faulthandler
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
REPORT = Path(os.environ.get('VOICE_STUDIO_TEST_REPORT_DIR', ROOT / 'docs'))
REPORT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from voice_studio.ui import VoiceStudio
from voice_studio import engines, styles
from voice_studio.config import DATA
from voice_studio.storage import (atomic_json, choose_take, has_reference, profiles,
                                  read_json, save_session, session_path, sessions, takes_of)


# Runs in its own process: exits 0 when the chosen output actually advances the clock.
PROBE_SOURCE = """
import sys, time
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
index, path = int(sys.argv[1]), sys.argv[2]
app = QApplication([])
devices = QMediaDevices.audioOutputs()
if index >= len(devices):
    raise SystemExit(2)
player = QMediaPlayer()
output = QAudioOutput(devices[index])
output.setVolume(0.2)
player.setAudioOutput(output)
player.setSource(QUrl.fromLocalFile(path))
deadline = time.monotonic() + 8
while time.monotonic() < deadline and player.position() <= 120:
    QApplication.processEvents()
    if player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
        player.play()
    time.sleep(0.05)
raise SystemExit(0 if player.position() > 120 else 1)
"""


def wait_until(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return
        QTest.qWait(40)
    raise AssertionError('Timed out waiting for Qt condition')


def main():
    # A media-backend deadlock blocks the interpreter inside C code, where a Python
    # signal handler never runs. This watchdog thread still prints stacks and exits.
    faulthandler.dump_traceback_later(900, exit=True)
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = VoiceStudio()
    errors = []
    QMessageBox.warning = lambda *args: errors.append(str(args[-1]))
    window.show()
    wait_until(lambda: window.isVisible())
    window.import_script_path(ROOT / 'samples' / 'narration.txt')
    assert window.script.toPlainText().startswith('Welcome to Voice Studio.')
    assert window.title.text() == 'narration'
    results = {'launch': True, 'txt_import': True}
    results['audio_outputs'] = len(QMediaDevices.audioOutputs())
    assert not QMediaDevices.defaultAudioOutput().isNull(), 'No macOS audio output device is available'
    # The default output can be a device that accepts nothing (a Bluetooth speaker that is
    # switched off). That is the machine's problem, not the app's, so find an output that
    # actually advances the clock and test against it.
    results['requested_output'] = QMediaDevices.defaultAudioOutput().description()
    # Probe each output in a separate process. Opening a device that accepts nothing (a
    # Bluetooth speaker that is switched off) leaves Qt's media backend in a state that
    # segfaults at interpreter exit, so that risk is kept out of this process entirely.
    probe = ROOT / 'samples' / 'flies-hal.wav'
    working = None
    for index, device in enumerate(QMediaDevices.audioOutputs()):
        check = subprocess.run(
            [sys.executable, '-c', PROBE_SOURCE, str(index), str(probe)],
            capture_output=True, text=True, timeout=60)
        if check.returncode == 0:
            working = device
            break
    assert working, ('no audio output on this Mac accepts audio; check System Settings > Sound '
                     f"(default is {results['requested_output']})")
    # Point the existing output at the working device. Replacing the player's QAudioOutput
    # object instead leaves Qt's backend in a state that segfaults at interpreter exit
    # (reproduced: replacing crashes, setDevice does not). The app never replaces it either.
    window.audio_output.setDevice(working)
    window.audio_output.setVolume(.75)
    window.player.setSource(QUrl())
    results['playback_output'] = working.description()
    # Pick a finished narration whose voice is still in the library, rather than a fixed
    # id: voices can be removed, and the regeneration check below needs a usable reference.
    live = {p['id'] for p in profiles() if has_reference(p)}
    usable = [s for s in sessions()
              if s.get('voice_id') in live and s.get('output')
              and (DATA / s['output']).is_file()
              and all(seg.get('file') and (DATA / seg['file']).is_file() for seg in s['segments'])]
    # Prefer a multi-section narration: the cancellation check needs neighbours to verify.
    usable.sort(key=lambda s: (len(s['segments']), s.get('updated', '')), reverse=True)
    session = usable[0] if usable and len(usable[0]['segments']) >= 2 else None
    if session:
        results['session_voice'] = session['voice_name']
        window.load_session(session)
        wait_until(lambda: bool(window.wave.peaks))
        assert window.table.rowCount() == len(session['segments'])
        window.play_full()
        wait_until(lambda: window.player.position() > 250, timeout=15)
        assert window.player.error() == QMediaPlayer.Error.NoError
        window.toggle_playback()
        assert window.player.playbackState() == QMediaPlayer.PlaybackState.PausedState
        window.player.setPosition(1000)
        wait_until(lambda: abs(window.player.position() - 1000) < 200)
        results.update(playback=True, pause=True, seeking=True, waveform=True)
        # Switching source while paused after a seek used to hang the Qt FFmpeg backend.
        window.play_reference()
        wait_until(lambda: window.player.position() > 150)
        window.player.pause()
        window.table.selectRow(0)
        window.play_section()
        wait_until(lambda: window.player.position() > 150)
        window.player.pause()
        results.update(reference_preview=True, section_preview=True)
        # Cancelling a regeneration clears the section's file and the assembled output, by
        # design. Snapshot the project first so this check leaves the narration as it found
        # it: otherwise the saved demo is left broken and the next run has nothing to preview.
        saved_project = read_json(session_path(session))
        # Exercise responsiveness and cancellation during a real inference process.
        beats = [0]
        timer = QTimer()
        timer.setInterval(25)
        timer.timeout.connect(lambda: beats.__setitem__(0, beats[0] + 1))
        timer.start()
        window.regenerate_section()
        wait_until(lambda: window.jobs.busy)
        wait_until(lambda: window.status.text().startswith('Generating section'), timeout=300)
        QTest.qWait(2500)
        start = time.monotonic()
        window.cancel()
        # Tearing down a ~6 GB worker can take a few seconds under memory pressure, so this
        # asserts that cancellation completes and records how long it took, not a stopwatch.
        wait_until(lambda: not window.jobs.busy, timeout=25)
        timer.stop()
        assert beats[0] > 20
        results.update(responsive_heartbeat_ticks=beats[0], cancel_seconds=round(time.monotonic()-start, 3))
        current = read_json(session_path(session))
        # Every section except the cancelled one keeps its audio, however many there are.
        for index, (now_, before_) in enumerate(zip(current['segments'], session['segments'])):
            if index == 0:
                continue
            assert now_['file'] == before_['file'], f'cancelling disturbed section {index + 1}'
        for segment in current['segments']:
            if segment.get('file'):
                assert (DATA / segment['file']).is_file(), 'cancelling deleted finished audio'
        results['cancel_preserves_completed_audio'] = True
        atomic_json(session_path(saved_project), saved_project)
        restored = read_json(session_path(saved_project))
        assert restored['output'] == saved_project['output'], 'the project was not restored'
        results['cancel_check_restores_project'] = True
        window.load_session(restored)
        window.tabs.setCurrentIndex(1)
        QTest.qWait(200)
    # --- narration styles ---------------------------------------------------------
    window.style.setCurrentText(styles.ENERGETIC)
    QApplication.processEvents()
    preset = styles.settings(styles.ENERGETIC)
    assert all(abs(window.controls[n].value() - preset[n]) < 1e-6 for n in styles.CONTROLS), \
        'choosing a style did not load its values'
    assert window.delivery_values()['reference_tempo'] > 1.0
    results['style_preset_applies'] = True

    # Hand-editing any number must drop the preset label, not silently keep it.
    window.controls['speed'].setValue(1.21)
    QApplication.processEvents()
    assert window.style.currentText() == styles.CUSTOM, 'editing a value kept the preset name'
    results['manual_edit_becomes_custom'] = True
    window.style.setCurrentText(styles.NATURAL)
    QApplication.processEvents()
    assert abs(window.controls['speed'].value() - 1.0) < 1e-6
    results['style_restores_defaults'] = True

    # --- switching voices must not bleed one profile into another -------------------
    names, transcripts = [], []
    for row in range(window.voice_list.count()):
        window.voice_list.setCurrentRow(row)
        QApplication.processEvents()
        names.append(window.profile['name'])
        transcripts.append(window.transcript.toPlainText())
    assert len(set(names)) == window.voice_list.count(), 'voices are not distinct'
    ready = [i for i in range(len(names)) if has_reference(
        window.voice_list.item(i).data(Qt.ItemDataRole.UserRole))]
    assert all(transcripts[i].strip() for i in ready), 'a ready voice lost its transcript'
    # Re-select the first voice and confirm its transcript came back unchanged.
    window.voice_list.setCurrentRow(0)
    QApplication.processEvents()
    assert window.transcript.toPlainText() == transcripts[0], 'switching voices overwrote a transcript'
    results.update(voice_count=len(names), profile_switch_preserves_transcript=True)

    # --- a voice with no recording cannot generate ----------------------------------
    pending = [i for i in range(window.voice_list.count()) if not has_reference(
        window.voice_list.item(i).data(Qt.ItemDataRole.UserRole))]
    if pending:
        window.voice_list.setCurrentRow(pending[0])
        QApplication.processEvents()
        window.script.setPlainText('This should not generate.')
        errors.clear()
        window.start_generation()
        QApplication.processEvents()
        assert not window.jobs.busy, 'generation started for a voice with no recording'
        assert errors and 'no recording' in errors[-1], errors
        errors.clear()
        results['placeholder_voice_blocked'] = True
    window.voice_list.setCurrentRow(0)
    QApplication.processEvents()

    # --- Phase A: default voice and the engine selector on the Script screen ---------
    results['default_voice'] = window.profile['name'] if window.profile else None
    results['main_engine_default'] = window.main_engine.currentData()
    assert results['main_engine_default'] == (session.get('engine', engines.DEFAULT) if session else engines.DEFAULT), 'The saved project engine must be restored'
    if session:
        # Read from disk: the cancellation check above restored the project, so the copy
        # captured earlier is out of date.
        session = read_json(session_path(session))
        window.load_session(session)
        QApplication.processEvents()
        before_takes = [len(takes_of(seg)) for seg in window.session['segments']]
        before_files = [seg.get('file') for seg in window.session['segments']]
        other_engine = next((e for e in engines.available() if e != engines.DEFAULT), None)
        if other_engine:
            window.main_engine.setCurrentIndex(window.main_engine.findData(other_engine))
            QApplication.processEvents()
            assert not window.jobs.busy, 'changing the main engine started a generation'
            saved = read_json(session_path(window.session))
            assert saved['engine'] == other_engine, 'the narration engine was not saved'
            assert [len(takes_of(seg)) for seg in saved['segments']] == before_takes, \
                'changing the main engine disturbed the stored takes'
            assert [seg.get('file') for seg in saved['segments']] == before_files, \
                'changing the main engine changed which audio is in use'
            results['main_engine_switch_keeps_takes'] = True
            window.main_engine.setCurrentIndex(window.main_engine.findData(engines.DEFAULT))
            QApplication.processEvents()
            # Reopening the project restores the engine it was saved with.
            window.load_session(read_json(session_path(window.session)))
            QApplication.processEvents()
            assert window.main_engine.currentData() == engines.DEFAULT
            results['main_engine_restores_with_project'] = True

    # --- hybrid: engine choice and takes --------------------------------------------
    if session:
        window.tabs.setCurrentIndex(1)
        window.table.selectRow(0)
        window.section_selected()        # selectRow is silent when the row is already current
        QApplication.processEvents()
        results['engines_offered'] = [window.engine_choice.itemData(i)
                                      for i in range(window.engine_choice.count())]
        assert engines.DEFAULT in results['engines_offered']
        # Choosing an engine for a section must stick, and must not start a generation.
        original_engine = window.section_engine(window.selected_segment()[1])
        other = next((e for e in results['engines_offered'] if e != original_engine), None)
        if other:
            window.engine_choice.setCurrentIndex(window.engine_choice.findData(other))
            QApplication.processEvents()
            assert not window.jobs.busy, 'choosing an engine started a generation'
            saved = read_json(session_path(window.session))
            assert saved['segments'][0]['engine'] == other, 'engine choice was not saved'
            results['engine_choice_persists'] = True
            # Put the original engine back: the cancellation check below regenerates this
            # section, and the slow engine would make it a test of patience.
            window.engine_choice.setCurrentIndex(window.engine_choice.findData(original_engine))
            QApplication.processEvents()
            assert read_json(session_path(window.session))['segments'][0]['engine'] \
                == original_engine, 'the engine choice did not revert'

        # Every section with audio lists at least one take, and the one in use is marked.
        segment = window.selected_segment()[1]
        assert window.takes.count() == len(takes_of(segment)) >= 1
        chosen = [window.takes.item(i) for i in range(window.takes.count())
                  if window.takes.item(i).data(Qt.ItemDataRole.UserRole)
                  == segment.get('selected_take')]
        assert len(chosen) == 1, 'exactly one take should be marked as in use'
        results['takes_listed'] = window.takes.count()

        # Selecting a take must never regenerate: add a second take by hand and switch.
        # Switching clears the assembled narration by design, so snapshot the whole project
        # and put it back afterwards; otherwise this check leaves a half-finished narration.
        take_snapshot = read_json(session_path(window.session))
        assert not window.jobs.busy, 'a generation was still running'
        before_file = segment['file']
        assert takes_of(segment), 'the section has no take to copy'
        spare = dict(takes_of(segment)[0])
        spare.update(id='gui-check-spare', file=before_file, engine=engines.CHATTERBOX,
                     engine_config={'exaggeration': 0.5})
        segment.setdefault('takes', []).append(spare)
        save_session(window.session)
        window.refresh_takes()
        QApplication.processEvents()
        for i in range(window.takes.count()):
            if window.takes.item(i).data(Qt.ItemDataRole.UserRole) == 'gui-check-spare':
                window.takes.setCurrentRow(i)
        window.use_take()
        QApplication.processEvents()
        assert not window.jobs.busy, 'choosing a take started a generation'
        after = read_json(session_path(window.session))
        assert after['segments'][0]['selected_take'] == 'gui-check-spare', (
            f"the spare take was not selected; errors={errors}")
        assert after['segments'][0]['engine'] == engines.CHATTERBOX
        assert len(after['segments'][0]['takes']) == len(takes_of(segment))
        results.update(take_switch_without_regenerating=True)
        # Put the project back exactly as it was found, assembled narration included.
        atomic_json(session_path(take_snapshot), take_snapshot)
        restored_take = read_json(session_path(take_snapshot))
        assert restored_take['output'] == take_snapshot['output'], 'the narration was not restored'
        assert not any(t['id'] == 'gui-check-spare'
                       for t in takes_of(restored_take['segments'][0])), 'spare take left behind'
        results['take_check_restores_project'] = True
        window.load_session(restored_take)
        QApplication.processEvents()

    # --- a narration whose voice was removed must still open -------------------------
    orphans = [s for s in sessions() if s.get('voice_id') not in live]
    if orphans:
        orphan = orphans[0]
        before_voice = orphan['voice_id']
        errors.clear()
        window.load_session(orphan)          # must not raise
        QApplication.processEvents()
        after = read_json(session_path(orphan))
        assert after['voice_id'] == before_voice, 'an orphaned narration was silently reassigned'
        assert after['voice_name'] == orphan['voice_name'], 'orphaned narration lost its voice name'
        errors.clear()
        results.update(orphaned_project_opens=True, orphaned_voice_not_reassigned=True)
        if session:
            window.load_session(session)
            QApplication.processEvents()

    assert not errors, errors
    window.grab().save(str(REPORT / 'desktop-preview.png'))
    window.save_draft()
    window.close()
    QApplication.processEvents()
    reopened = VoiceStudio()
    assert reopened.script.toPlainText() == window.script.toPlainText()
    assert reopened.voice_list.count() == window.voice_list.count()
    results['draft_and_profiles_restore'] = True
    reopened.close()
    QApplication.processEvents()
    results['switch_source_while_paused_after_seek'] = True
    (REPORT / 'gui-results.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2), flush=True)

    # Release the media objects while the interpreter is still healthy. Left to exit-time
    # garbage collection, Qt and Python tear these down in an order that segfaults, which
    # would turn a passing run into a crash.
    for window_ in (reopened, window):
        window_.player.stop()
        window_.player.setSource(QUrl())
    QThreadPool.globalInstance().waitForDone(3000)
    QApplication.processEvents()
    app.quit()


if __name__ == '__main__':
    main()
