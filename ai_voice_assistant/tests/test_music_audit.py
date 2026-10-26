"""Pre-submit regressions for publication races and acknowledged UI control."""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock,patch
import wave

import pytest

from core.music_manager import MusicJobCancelled,audio_metadata,atomic_json
from core.music_manager import MusicManager,library_root
from core.music_worker import MusicWorker
from ui.music_player_renderer import MusicPlayerRenderer
from test_music import manager,sound,payload,ready,command,wait_for,server,http


def test_completed_publication_does_not_overwrite_immediate_user_retag(manager,sound):
    original=manager.publish;edited=threading.Event()
    def publish(*args,**kwargs):
        data=original(*args,**kwargs)
        manager.retag(data['track_id'],['jazz'],title='使用者的新名稱')
        edited.set()
        return data
    worker=MusicWorker(manager,lambda:{},provider=lambda *a:(sound,{}))
    with patch.object(manager,'publish',side_effect=publish):
        worker.start()
        try:
            wait_for(manager.worker_ready)
            job=manager.enqueue(payload())
            assert edited.wait(5)
            wait_for(lambda:worker.current_job is None)
            track=manager.track(manager.job(job['job_id'])['track_id'])
            assert track['title']=='使用者的新名稱' and track['genre_ids']==['jazz']
            assert track['generation_elapsed_ms']>=0
        finally:worker.stop()


def test_staging_cleanup_failure_does_not_stop_following_jobs(manager,sound):
    def provider(settings,request,folder,cancel):
        folder.mkdir(parents=True)
        return sound,{}
    worker=MusicWorker(manager,lambda:{},provider=provider)
    with patch('core.music_worker.shutil.rmtree',side_effect=PermissionError('busy')):
        worker.start()
        try:
            wait_for(manager.worker_ready)
            jobs=[manager.enqueue(payload()) for _ in range(2)]
            wait_for(lambda:all(manager.job(j['job_id'])['status']=='completed' for j in jobs))
            assert worker.thread.is_alive() and len(manager.tracks())==2
        finally:worker.stop()


def test_cancellation_during_validation_does_not_publish_a_recoverable_song(manager,sound):
    worker=MusicWorker(manager,lambda:{})
    assert worker.lease()
    job=manager.enqueue(payload())
    with manager.connect() as db:db.execute("UPDATE jobs SET state='validating' WHERE id=?",(job['job_id'],))
    original=audio_metadata
    def validate(*args,**kwargs):
        info=original(*args,**kwargs)
        manager.cancel(job['job_id'])
        return info
    with patch('core.music_manager.audio_metadata',side_effect=validate):
        with pytest.raises(MusicJobCancelled):manager.publish(sound,payload(),job_id=job['job_id'])
    manager.recover()
    assert manager.tracks()==[] and not list((manager.root/'metadata').glob('*.json'))


def test_worker_renews_lease_during_slow_validation(manager,sound):
    validating=threading.Event();release=threading.Event();original=manager.publish
    def slow_publish(*args,**kwargs):
        validating.set()
        assert release.wait(5)
        return original(*args,**kwargs)
    worker=MusicWorker(manager,lambda:{},provider=lambda *a:(sound,{}))
    with patch.object(manager,'publish',side_effect=slow_publish):
        worker.start()
        try:
            wait_for(manager.worker_ready);job=manager.enqueue(payload())
            assert validating.wait(3)
            with manager.connect() as db:db.execute('UPDATE runtime SET heartbeat=0')
            wait_for(manager.worker_ready,timeout=2.5)
            assert not MusicWorker(manager,lambda:{}).lease()
            release.set()
            wait_for(lambda:manager.job(job['job_id'])['status']=='completed')
        finally:release.set();worker.stop()


def test_worker_cannot_claim_queue_after_another_owner_takes_lease(manager):
    worker=MusicWorker(manager,lambda:{})
    assert worker.lease();job=manager.enqueue(payload())
    with manager.connect() as db:db.execute('UPDATE runtime SET owner=?',('other-worker',))
    assert worker._claim() is None and manager.job(job['job_id'])['status']=='queued'


def test_ui_change_expires_queued_command_without_reverting_user_state(manager,sound):
    first=manager.publish(sound,payload());second=manager.publish(sound,payload())
    state=ready(manager)
    queued=manager.control(command(state,'play',track_id=first['track_id']))
    changed=manager.renderer_report(state['content_id'],{'track_id':second['track_id'],'playback_state':'paused','volume':.25})
    assert changed['revision']!=state['revision']
    result=manager.renderer_report(state['content_id'],{'track_id':first['track_id'],'playback_state':'playing',
        'command_id':queued['command_id'],'command_status':'applied'})
    assert result['status']=='stale_revision'
    assert manager.player_status()['track_id']==second['track_id']
    assert manager.player_status()['volume']==.25
    assert manager.commands(state['content_id'])==[]


def test_controls_are_serialized_but_position_heartbeats_do_not_invalidate_them(manager):
    state=ready(manager)
    first=manager.control(command(state,'pause'))
    assert manager.control(command(state,'set-volume',volume=.5))['status']=='busy'
    after=manager.renderer_report(state['content_id'],{'playback_state':'paused','position_seconds':1})
    assert after['revision']==state['revision']
    assert manager.commands(state['content_id'])[0]['command_id']==first['command_id']


@pytest.mark.parametrize('bad',[
    {'created_at':{}},{'title':[]},{'audio_file':'../outside.wav'},{'sha256':'bad'},
])
def test_corrupt_sidecar_is_skipped_without_breaking_recovery(manager,sound,bad):
    data=manager.publish(sound,payload());identifier=data['track_id']
    atomic_json(manager.root/'metadata'/(identifier+'.json'),dict(data,**bad))
    with manager.connect() as db:db.execute('DELETE FROM tracks')
    manager.recover()
    assert manager.tracks()==[]


def test_corrupt_delete_journal_does_not_resurrect_song_after_index_rebuild(manager,sound):
    data=manager.publish(sound,payload());identifier=data['track_id'];manager.delete(identifier)
    atomic_json(manager.root/'trash'/(identifier+'.json'),{'broken':True})
    with manager.connect() as db:db.execute('DELETE FROM deleted_tracks')
    manager.recover()
    assert manager.tracks()==[]


def test_simultaneous_imports_respect_storage_limit(manager,sound,tmp_path):
    large=tmp_path/'large.wav'
    with wave.open(str(sound),'rb') as source,wave.open(str(large),'wb') as target:
        target.setparams(source.getparams());target.writeframes(source.readframes(source.getnframes())*80)
    manager.settings['max_storage_mb']=1
    barrier=threading.Barrier(2);original=audio_metadata
    def validate(*args,**kwargs):
        info=original(*args,**kwargs);barrier.wait(timeout=3);return info
    def publish(_):
        try:manager.publish(large,payload());return 'ok'
        except ValueError as exc:
            assert '容量' in str(exc)
            return 'full'
    with patch('core.music_manager.audio_metadata',side_effect=validate),ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(publish,range(2)))==['full','ok']


def test_renderer_stops_owned_browser_even_if_database_is_unavailable(manager,tmp_path):
    renderer=MusicPlayerRenderer(tmp_path,manager,None,lambda:{})
    renderer.content_id='board'
    with patch.object(manager,'suspend_player',side_effect=sqlite3.OperationalError('offline')),patch('ui.music_player_renderer.NativeHtmlRenderer.stop') as stop:
        renderer.stop();stop.assert_called_once()


def test_unwritable_music_profile_does_not_break_conversation_startup(tmp_path):
    from ui.session_window import VoiceAssistantUI
    ui=SimpleNamespace(settings={'music':{'enabled':True},'whiteboard':{'html_audio_duck_volume':.2}},
        assistant=SimpleNamespace(app_dir=tmp_path,whiteboard_manager=None),chat_header_holder=Mock(),
        open_music=Mock(),_post_to_ui=Mock())
    with patch('ui.session_window.IconButton'),patch('ui.music_player_renderer.MusicPlayerRenderer',side_effect=PermissionError('profile')),patch('core.music_worker.MusicWorker') as worker:
        VoiceAssistantUI._setup_music(ui)
        assert ui._music_startup_error and not hasattr(ui,'music_manager')
        worker.assert_not_called()


def test_http_storage_failure_returns_safe_json_and_head_has_no_body(manager,server):
    with patch.object(manager,'manifest',side_effect=sqlite3.OperationalError('private diagnostic')):
        status,_,body=http(server,'/api/state')
        assert status==503 and json.loads(body)['status']=='unavailable'
        assert b'private diagnostic' not in body
    status,_,body=http(server,'/api/state','HEAD')
    assert status==405 and body==b''


@pytest.mark.parametrize('value',['','  ','.','..',None,False])
def test_music_directory_requires_dedicated_private_folder(tmp_path,value):
    from core.settings_schema import validate_field,SettingsError
    with pytest.raises(ValueError):MusicManager(tmp_path,{'music':{'directory':value}})
    with pytest.raises(SettingsError):validate_field(('music','directory'),value)
    assert not (tmp_path/'catalog.sqlite3').exists()
    assert library_root(tmp_path,'private/music')==tmp_path/'private/music'


def test_unknown_schema_version_is_preserved_instead_of_downgraded(manager):
    with manager.connect() as db:db.execute('PRAGMA user_version=99')
    with pytest.raises(ValueError,match='版本'):MusicManager(manager.app_dir)
    with manager.connect() as db:assert db.execute('PRAGMA user_version').fetchone()[0]==99
