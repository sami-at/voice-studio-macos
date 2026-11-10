"""Exercise timing edits and review states in actual Qt widgets, on an isolated copy."""
import os,sys,json,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'samples/final-quality'
os.environ['VOICE_STUDIO_DATA']=str(OUT/'gui-data')
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication,QMessageBox
from PySide6.QtCore import Qt,QUrl,QThreadPool
from voice_studio.ui import VoiceStudio
from voice_studio import storage, direction
from voice_studio.text import new_session
from voice_studio.config import DATA
app=QApplication([])
window=VoiceStudio();window.show();app.processEvents()
errors=[];QMessageBox.warning=lambda *a:errors.append(str(a[-1]))
results={}
assert window.profile['name']=='Hal'
results['default_hal']=True
hal=window.profile
session=new_session('Wait[pause:0.4] now.\n\n[pause:0.5]\n\nThe mystery is over.', 'Timing regression',hal)
existing=next(s for s in storage.sessions() if all(x.get('file') for x in s['segments']))
for index,seg in enumerate(session['segments']):
 src=existing['segments'][min(index,len(existing['segments'])-1)]
 storage.add_take(seg,{'file':src['file'],'seconds':src.get('seconds',1),
                      'text':seg['text'],'text_hash':storage.text_fingerprint(seg['text']),
                      'verified':True,'verification_version':2,'engine':'qwen3'})
storage.save_session(session);window.load_session(session);app.processEvents()
original=[s['file'] for s in window.session['segments']]
window.script.setPlainText(session['script'].replace('0.4','0.9'));app.processEvents()
started=[];window.start_job=lambda job:started.append(job)
window.start_generation();app.processEvents()
assert [s['file'] for s in window.session['segments']]==original
assert not any(storage.segment_needs_audio(s,DATA) for s in window.session['segments'])
assert '0.9' in window.session['segments'][0]['text']
results['inline_timing_reuses_selected_takes']=True
window.tabs.setCurrentIndex(1);window.table.selectRow(1);window.section_selected();app.processEvents()
window.section_text.setPlainText('Everything is different.')
window.save_section_edit();app.processEvents()
assert '[pause:0.5]' in window.session['script']
assert storage.segment_is_stale(window.session['segments'][1])
results['section_edit_preserves_standalone_pause_and_flags_stale']=True
window.script.setPlainText('Bad [pause: marker');app.processEvents()
window.start_generation();assert errors and 'direction' in errors[-1].lower();errors.clear()
results['malformed_direction_blocks_generation_without_widget_exception']=True
window.load_session(storage.read_json(storage.session_path(session)));app.processEvents()
seg=window.session['segments'][0];seg['verified']=None
window.refresh_table();assert window.table.item(0,3).text()=='Unchecked'
seg['verified']=True;seg['verification_version']=1
window.refresh_table();assert window.table.item(0,3).text()=='Legacy check'
results['unchecked_and_legacy_checks_visible']=True
seg['verification_version']=None
for take in storage.takes_of(seg):take['verification_version']=None
window.refresh_table();assert window.table.item(0,3).text()=='Legacy check'
results['legacy_null_version_safe_after_take_switch']=True
window.open_handbook();app.processEvents();h=window._handbook
h.search.setText('inserted');app.processEvents();assert h.chapters.count()>0
h.close();results['handbook_search']=True
window.on_event({'kind':'unverified','indices':[0],'detail':'unconfirmed'})
assert window._incomplete
results['unverified_reassembly_is_reported']=True
window.grab().save(str(OUT/'gui-quality.png'))
for width,height in ((1240,850),(980,740)):
 window.resize(width,height);app.processEvents()
 for button in (window.regenerate,window.alternative,window.engine_choice):
  assert button.width() >= button.minimumSizeHint().width()
  point=button.mapTo(window,button.rect().bottomRight())
  assert point.x()<window.width() and point.y()<window.height()
results['section_actions_fit_default_and_small_window']=True
window.player.setSource(QUrl());window.close();QThreadPool.globalInstance().waitForDone(3000);app.processEvents()
(OUT/'gui-quality-results.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
app.quit()
