"""The redesigned window keeps its widgets and behaviour; the Handbook can be copied whole."""
import os
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from voice_studio import handbook
from voice_studio.handbook import CHAPTERS, QUICK_START, Handbook, WrappedLabel, handbook_text


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_handbook_text_starts_with_the_writing_guide_and_covers_every_entry():
    text = handbook_text()
    assert text.startswith('# How to write a script for Voice Studio')
    for _, steps_body in [(h, b) for h, b in QUICK_START[2]]:
        assert steps_body in text
    for title, _, items in CHAPTERS:
        assert f'## {title}' in text
        for item in items:
            assert item['example'] in text
            assert handbook.BADGE[item['support']][0] in text
    assert '[pause:0.5]' in text and '{GIF|jiff}' in text


def test_handbook_text_for_one_chapter_is_just_that_chapter():
    chapter = CHAPTERS[3]
    text = handbook_text([chapter], quick_start=False)
    assert f'## {chapter[0]}' in text and 'How to write a script' not in text
    assert CHAPTERS[0][0] not in text


def test_quick_start_claims_match_the_parser():
    from voice_studio import direction
    from voice_studio.text import split_script
    assert direction.PAUSE_LIMITS == (0.05, 5.0) and direction.MAX_SPOKEN_WORDS == 12
    assert split_script.__defaults__ == (260,)
    spoken = direction.parse('The {GIF|jiff} and tarsi[say:tar sigh] [pause:0.5] end.')
    assert not spoken.problems and 'jiff' in spoken.spoken and 'tar sigh' in spoken.spoken


def test_copy_buttons_fill_the_clipboard_and_ignore_the_search_filter(app):
    box = Handbook()
    box.show()
    box.search.setText('pause')
    app.processEvents()
    box.copy_handbook()
    whole = app.clipboard().text()
    assert whole == handbook_text()
    box.chapters.setCurrentRow(0)
    box.copy_current_chapter()
    chapter = app.clipboard().text()
    assert chapter.startswith('## ') and len(chapter) < len(whole)
    box.close()


def test_every_wrapped_label_is_tall_enough_for_its_text(app):
    box = Handbook()
    box.resize(940, 680)
    box.show()
    for row in range(box.chapters.count()):
        box.chapters.setCurrentRow(row)
        app.processEvents()
        box.fit_labels()
        for label in box.page.findChildren(WrappedLabel):
            assert label.height() >= label.heightForWidth(label.width()) - 1, label.text()[:40]
    box.close()


def test_window_keeps_its_named_controls_and_collapses_fine_tuning(app, tmp_path, monkeypatch):
    monkeypatch.setenv('VOICE_STUDIO_DATA', str(tmp_path))
    import importlib
    from voice_studio import config, storage, ui
    importlib.reload(config); importlib.reload(storage); importlib.reload(ui)
    window = ui.VoiceStudio()
    window.show()
    for name in ('script', 'table', 'tabs', 'title', 'language', 'style', 'main_engine', 'regenerate',
                 'alternative', 'engine_choice', 'generate_button', 'export_button', 'play_button',
                 'handbook_button', 'controls', 'new_button', 'add_voice', 'history', 'voice_list'):
        assert hasattr(window, name), name
    assert [window.tabs.tabText(i) for i in range(4)] == ['Script', 'Sections', 'Review', 'Voice reference']
    assert not window.fine_panel.isVisible()
    window.style.setCurrentText('Custom')
    app.processEvents()
    assert window.fine_panel.isVisible() and window.fine_toggle.isChecked()
    window.close()
