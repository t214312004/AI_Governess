"""Music contract, durable files, worker and localhost renderer regressions."""
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import struct
import threading
import time
from unittest.mock import patch
from uuid import uuid4
import wave

import pytest

from core.music_catalog import catalog, filter_tracks, genre_ids
from core.music_manager import MusicManager, audio_metadata
from core.music_worker import MusicWorker
from core.whiteboard_manager import WhiteboardManager
from ui.music_player_renderer import MusicRequestHandler, ASSETS
from utils.gemini_music import MusicGenerationError


@pytest.fixture
def manager(tmp_path):
    return MusicManager(tmp_path, {'music': {'daily_generation_limit': 20, 'daily_budget_usd': 2}})


@pytest.fixture
def sound(tmp_path):
    import math
    path=tmp_path/'source.wav'
    with wave.open(str(path),'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(8000)
        stream.writeframes(b''.join(struct.pack('<h',int(2000*math.sin(i*.1))) for i in range(4000)))
    return path


def payload(**extra):
    return dict({'request_id':uuid4().hex,'title':'午後的小小冒險','genre_ids':['folk','pop'],
                 'prompt':'溫暖的木吉他，輕快而溫柔','instrumental':True},**extra)


def wait_for(predicate, timeout=5):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        result=predicate()
        if result:return result
        time.sleep(.02)
    pytest.fail('worker did not reach expected state')


def ready(manager, content='test-board'):
    manager.player_open(content)
    return manager.renderer_report(content,{'playback_state':'paused','renderer_ready':True})


def command(state, action='pause', **extra):
    return dict(request_id=uuid4().hex,content_id=state['content_id'],expected_revision=state['revision'],action=action,**extra)


def test_catalog_and_multigenre_semantics():
    styles=catalog()['styles']
    assert len(styles)==12 and len({s['id'] for s in styles})==12
    assert all(s['zh'] and s['en'] and s['description'] for s in styles)
    tracks=[{'track_id':'a','title':'晴天','genre_ids':['pop','folk']},
            {'track_id':'b','title':'星空','genre_ids':['pop']},{'track_id':'c','title':'無類別','genre_ids':[]}]
    assert [t['track_id'] for t in filter_tracks(tracks,['folk','pop'])]==['a','b']
    assert [t['track_id'] for t in filter_tracks(tracks,['folk','pop'],'all')]==['a']
    assert [t['track_id'] for t in filter_tracks(tracks,unclassified=True)]==['c']
    assert len(filter_tracks(tracks,query='FOLK'))==1
    assert len(filter_tracks(tracks,query='民謠'))==1
    assert genre_ids(['pop','pop','folk'])==['pop','folk']
    with pytest.raises(ValueError):genre_ids(['made-up'])
    with pytest.raises(ValueError):filter_tracks(tracks,match='invalid')


@pytest.mark.parametrize('change',[
    {'model':'lyria-3'}, {'instrumental':'true'}, {'requested_duration_seconds':False},
    {'requested_duration_seconds':float('nan')}, {'requested_duration_seconds':181},
    {'genre_ids':['ambient']}, {'lyrics':'唱歌'}, {'title':''}, {'tags':['x'*41]},
])
def test_invalid_generation_payload_rejected(manager,change):
    with pytest.raises(ValueError):manager.normalize_request(payload(**change))


def test_durable_publish_retag_recover_and_missing_audio(manager,sound):
    track=manager.publish(sound,payload())
    identifier=track['track_id']
    assert track['duration_seconds']==pytest.approx(.5)
    assert audio_metadata(manager.audio_path(identifier))['sha256']==track['sha256']
    reopened=MusicManager(manager.app_dir)
    assert reopened.tracks(['pop','folk'],'all')[0]['track_id']==identifier
    reopened.retag(identifier,['jazz','blues'],title='新的名字')
    assert len(reopened.tracks(['jazz','blues']))==1
    assert reopened.track(identifier)['requested_genre_ids']==['folk','pop']
    with reopened.connect() as db:db.execute('DELETE FROM tracks')
    reopened.recover()
    assert reopened.track(identifier)['title']=='新的名字'
    reopened.audio_path(identifier).unlink()
    assert reopened.tracks()[0]['available'] is False
    with pytest.raises(ValueError):reopened.audio_path(identifier)
    assert not reopened.jobs()  # missing audio never triggers paid regeneration


def test_delete_active_track_is_undoable_and_invalidates_commands(manager,sound):
    first=manager.publish(sound,payload());second=manager.publish(sound,payload())
    identifier=first['track_id'];path=manager.audio_path(identifier)
    manager.player_open('board',identifier);state=ready(manager,'board')
    cmd=manager.control(command(state,'play',track_id=identifier))
    assert manager.delete(identifier)=={'status':'deleted','track_id':identifier,'undoable':True}
    assert path.is_file()  # recoverable deletion keeps the original audio
    assert manager.player_status()['status']=='renderer_unavailable'
    assert manager.player_status()['track_id'] is None
    assert manager.commands('board')==[]
    with manager.connect() as db:
        assert db.execute('SELECT reason FROM commands WHERE id=?',(cmd['command_id'],)).fetchone()[0]=='track_deleted'
    assert [t['track_id'] for t in manager.tracks()]==[second['track_id']]
    assert len(manager.deleted_tracks())==1
    with pytest.raises(ValueError):manager.audio_path(identifier)
    assert manager.delete(identifier)['status']=='deleted'
    assert manager.restore_track(identifier)['status']=='restored'
    assert manager.restore_track(identifier)['status']=='restored'
    assert len(manager.tracks())==2 and not manager.deleted_tracks()
    assert audio_metadata(manager.audio_path(identifier))['sha256']==first['sha256']
    assert manager.track(identifier)['genre_ids']==['folk','pop']


def test_delete_journal_survives_index_rebuild_and_restore_retag(manager,sound):
    track=manager.publish(sound,payload());identifier=track['track_id']
    manager.delete(identifier)
    with manager.connect() as db:db.execute('DELETE FROM deleted_tracks')
    manager.recover()
    assert manager.tracks()==[] and len(manager.deleted_tracks())==1
    manager._index_track(track)  # delayed writer cannot resurrect a deleted song
    assert manager.tracks()==[]
    manager.restore_track(identifier)
    manager.retag(identifier,['jazz'],title='恢復後的新名字')
    manager.recover()
    assert manager.track(identifier)['title']=='恢復後的新名字'
    assert manager.track(identifier)['genre_ids']==['jazz']


def test_interrupted_delete_and_restore_recover_intended_state(manager,sound):
    track=manager.publish(sound,payload());identifier=track['track_id']
    with patch.object(manager,'_apply_delete',side_effect=OSError('interrupted')):
        with pytest.raises(OSError):manager.delete(identifier)
    manager.recover()
    assert not manager.tracks()
    with patch.object(manager,'_index_track',side_effect=OSError('interrupted')):
        with pytest.raises(OSError):manager.restore_track(identifier)
    manager.recover()
    assert manager.track(identifier)['sha256']==track['sha256']
    assert not manager.deleted_tracks()


@pytest.mark.parametrize('identifier',['../config.local.json','0'*31,None])
def test_invalid_delete_restore_identifiers_rejected(manager,identifier):
    for action in (manager.delete,manager.restore_track):
        with pytest.raises(ValueError):action(identifier)


def test_publication_crash_replays_files(manager,sound):
    with patch.object(manager,'_index_track',side_effect=OSError('disk')):
        with pytest.raises(OSError):manager.publish(sound,payload())
    assert manager.tracks()==[]
    manager.recover()
    assert len(manager.tracks())==1
    assert not list((manager.root/'tracks').glob('*.part'))


def test_silent_invalid_and_storage_limits(manager,tmp_path,sound):
    invalid=tmp_path/'bad.mp3';invalid.write_bytes(b'not music')
    with pytest.raises(Exception):manager.publish(invalid,payload())
    manager.settings['max_storage_mb']=.00001
    with pytest.raises(ValueError,match='容量'):manager.publish(sound,payload())
    assert not manager.tracks()
    for value in ('../config.local.json','A'*32,'0'*32):
        with pytest.raises(ValueError):manager.audio_path(value)


def test_queue_requires_worker_and_idempotency_is_atomic(manager):
    request=payload()
    with pytest.raises(ValueError,match='尚未就緒'):manager.enqueue(request)
    worker=MusicWorker(manager,lambda:{})
    assert worker.lease()
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs=list(pool.map(lambda _:manager.enqueue(request),range(8)))
    assert len({j['job_id'] for j in jobs})==1 and len(manager.jobs())==1
    with pytest.raises(ValueError,match='內容不同'):manager.enqueue(dict(request,title='changed'))
    manager.settings['daily_generation_limit']=1
    with pytest.raises(ValueError,match='上限'):manager.enqueue(payload())
    assert manager.cancel(jobs[0]['job_id'])['status']=='cancelled'
    assert manager.enqueue(request)['status']=='cancelled'


def test_worker_single_owner_success_and_notification_ack(manager,sound):
    calls=[]
    def provider(settings,request,folder,cancel):
        assert cancel.wait(.001) is False
        calls.append(request);folder.mkdir(parents=True);(folder/'prompt.txt').write_text('private prompt')
        return sound,{'provider_version':'test'}
    worker=MusicWorker(manager,lambda:{},provider=provider)
    worker.start()
    try:
        wait_for(manager.worker_ready)
        other=MusicWorker(manager,lambda:{})
        assert not other.lease()
        job=manager.enqueue(payload())
        wait_for(lambda:manager.job(job['job_id'])['status']=='completed')
        assert len(calls)==1 and len(manager.tracks())==1
        assert worker.notifications()[0]['job_id']==job['job_id']
        assert len(worker.notifications())==1
        worker.acknowledge_notification(job['job_id'])
        assert worker.notifications()==[]
        wait_for(lambda:not (manager.root/'staging'/job['job_id']).exists())
    finally:worker.stop()
    assert not manager.worker_ready()


@pytest.mark.parametrize('uncertain,status',[(False,'failed'),(True,'unknown_remote_result')])
def test_worker_never_retries_paid_failure(manager,uncertain,status):
    calls=[]
    def provider(*args):
        calls.append(1)
        raise MusicGenerationError('safe_reason',uncertain=uncertain)
    worker=MusicWorker(manager,lambda:{},provider=provider);worker.start()
    try:
        wait_for(manager.worker_ready)
        job=manager.enqueue(payload())
        wait_for(lambda:manager.job(job['job_id'])['status']==status)
        assert len(calls)==1
    finally:worker.stop()


def test_running_cancellation_and_restart_do_not_resubmit(manager):
    started=threading.Event()
    def provider(settings,request,folder,cancel):
        started.set()
        while not cancel.is_set():time.sleep(.01)
        raise MusicGenerationError('cancelled',uncertain=True)
    worker=MusicWorker(manager,lambda:{},provider=provider);worker.start()
    try:
        wait_for(manager.worker_ready)
        job=manager.enqueue(payload())
        assert started.wait(3)
        manager.cancel(job['job_id'])
        wait_for(lambda:manager.job(job['job_id'])['status']=='cancelled')
    finally:worker.stop()
    worker=MusicWorker(manager,lambda:{},provider=lambda *a:pytest.fail('must not resubmit'))
    assert worker.lease()
    second=manager.enqueue(payload())
    with manager.connect() as db:db.execute("UPDATE jobs SET state='running' WHERE id=?",(second['job_id'],))
    worker.start()
    try:wait_for(lambda:manager.job(second['job_id'])['status']=='unknown_remote_result')
    finally:worker.stop()


def test_player_ack_revision_stale_and_user_gesture(manager,sound):
    track=manager.publish(sound,payload())
    stale=manager.player_open('board')
    assert stale['status']=='renderer_unavailable'
    assert manager.control(command(stale))['status']=='renderer_unavailable'
    state=ready(manager,'board')
    request=command(state,'play',track_id=track['track_id'])
    result=manager.control(request)
    assert result['status']=='accepted'
    assert manager.player_status()['playback_state']=='paused'
    assert manager.control(request)['command_id']==result['command_id']
    queued=manager.commands('board')
    assert len(queued)==1 and queued[0]['expires_at']>time.time()
    after=manager.renderer_report('board',{'track_id':track['track_id'],'playback_state':'needs_user_gesture',
        'command_id':result['command_id'],'command_status':'needs_user_gesture','renderer_ready':True})
    assert after['revision']!=state['revision']
    assert manager.control(command(state))['status']=='stale_revision'
    assert manager.commands('board')==[]
    assert manager.control(dict(command(after),content_id='old'))['status']=='stale_content'
    manager.suspend_player('board')
    assert manager.player_status()['status']=='renderer_unavailable'
    assert manager.renderer_report('old',{'playback_state':'paused'})['status']=='stale_content'


@pytest.mark.parametrize('action,fields',[
    ('seek',{}),('set-volume',{}),('set-repeat',{}),('seek',{'position_seconds':float('inf')}),
    ('set-volume',{'volume':2}),('set-repeat',{'repeat':'forever'}),('set-filter',{'unclassified':'yes'}),
    ('set-filter',{'genre_ids':['unknown']}),('play',{'bypass':True}),
])
def test_invalid_control_rejected(manager,action,fields):
    with pytest.raises(ValueError):manager.control(command(ready(manager),action,**fields))


def test_expired_commands_never_report_success(manager):
    state=ready(manager)
    result=manager.control(command(state))
    with manager.connect() as db:db.execute('UPDATE commands SET expires=0')
    assert manager.commands(state['content_id'])==[]
    assert manager.renderer_report(state['content_id'],{'playback_state':'paused',
        'command_id':result['command_id'],'command_status':'applied'})['status']=='expired'


def test_show_player_with_requested_track_after_hide_preserves_selection(manager,sound):
    first=manager.publish(sound,payload())
    second=manager.publish(sound,payload())
    manager.player_open('board',first['track_id'])
    ready(manager,'board')
    manager.suspend_player('board')
    state=manager.player_open('board',second['track_id'])
    assert state['track_id']==second['track_id'] and state['position_seconds']==0
    assert state['status']=='renderer_unavailable'


@pytest.mark.parametrize('broken_quota',[False,True])
def test_music_quota_exemption_cannot_be_used_for_arbitrary_html(tmp_path,broken_quota):
    board=WhiteboardManager(tmp_path,state_dir=tmp_path/'board',html_daily_minutes=0)
    with patch.object(board,'_html_quota_status',side_effect=OSError('quota')) if broken_quota else patch.object(board,'_html_quota_status',wraps=board._html_quota_status):
        result=board.show_music()
        assert result['status']=='shown' and result['html_time_metered'] is False
        identifier=result['content_id']
        assert board.hide(identifier)['status']=='hidden'
        assert board.restore(identifier)['status']=='restored'
        assert board.reload(identifier)['status']=='reloaded'
        assert board.get_active()['reload_token']
    assert board.show_html({'html_path':str(ASSETS/'index.html'),'html_time_metered':False})['status']=='blocked'
    assert board.status()['content_type']=='music'


@pytest.fixture
def server(manager,tmp_path):
    board=WhiteboardManager(tmp_path,state_dir=tmp_path/'board',html_daily_minutes=0)
    shown=board.show_music();manager.player_open(shown['content_id'])
    server=ThreadingHTTPServer(('127.0.0.1',0),MusicRequestHandler)
    server.daemon_threads=True
    server.manager,server.board,server.content_id=manager,board,shown['content_id']
    server.token='test-nonce';server.settings=lambda:{}
    server.source_root=ASSETS;server.entry_path=ASSETS/'index.html'
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield server
    server.shutdown();server.server_close();thread.join(3)


def http(server,path,method='GET',data=None,**headers):
    connection=HTTPConnection(*server.server_address,timeout=3)
    body=json.dumps(data).encode() if data is not None else None
    connection.request(method,path,body,headers)
    response=connection.getresponse();result=response.status,dict(response.getheaders()),response.read()
    connection.close();return result


def test_http_manifest_ranges_and_path_scope(manager,sound,server):
    track=manager.publish(sound,payload())
    status,headers,body=http(server,'/api/state')
    manifest=json.loads(body)
    assert status==200 and len(manifest['styles'])==12
    assert sum(s['count'] for s in manifest['styles'])==2
    assert 'prompt' not in manifest['tracks'][0] and 'audio_file' not in manifest['tracks'][0]
    route='/audio/'+track['track_id'];original=sound.read_bytes()
    assert http(server,route,'HEAD')[2]==b''
    status,headers,body=http(server,route,Range='bytes=7-18')
    assert status==206 and body==original[7:19]
    assert headers['Content-Range']==f'bytes 7-18/{len(original)}'
    assert http(server,route,Range='bytes=-17')[2]==original[-17:]
    for value in ('bytes=999999-','bytes=-0','bytes=9-1','bytes=1-2,4-5'):
        assert http(server,route,Range=value)[0]==416
    for path in ('/audio/../../config.local.json','/config.local.json','/../player.js'):
        assert http(server,path)[0]==404
    assert http(server,'/',Host='evil.example')[0]==403


def test_http_mutation_requires_exact_origin_nonce_and_active_board(server):
    origin=f'http://127.0.0.1:{server.server_address[1]}'
    route='/api/report';body={'playback_state':'paused','renderer_ready':True}
    assert http(server,route,'POST',body)[0]==403
    assert http(server,route,'POST',body,Origin=origin,**{'X-Music-Token':'wrong'})[0]==403
    headers={'Origin':origin,'X-Music-Token':server.token}
    assert http(server,route,'POST',body,**headers)[0]==200
    assert http(server,route,'POST',{'playback_state':'invalid'},**headers)[0]==400
    assert http(server,route,'POST',[],**headers)[0]==400
    server.board.hide(server.content_id)
    assert http(server,route,'POST',body,**headers)[0]==403
    assert http(server,'/api/state')[0]==409


def test_http_delete_restore_and_public_trash_manifest(manager,sound,server):
    track=manager.publish(sound,payload());identifier=track['track_id']
    headers={'Origin':f'http://127.0.0.1:{server.server_address[1]}','X-Music-Token':server.token}
    assert http(server,'/api/delete','POST',{'track_id':identifier})[0]==403
    status,_,body=http(server,'/api/delete','POST',{'track_id':identifier},**headers)
    assert status==200 and json.loads(body)['status']=='deleted'
    data=json.loads(http(server,'/api/state')[2])
    assert data['total']==0 and len(data['styles'])==12
    assert data['trash'][0]['track_id']==identifier
    assert not {'prompt','audio_file','response_id'}&set(data['trash'][0])
    assert http(server,'/audio/'+identifier)[0]==404
    assert http(server,'/api/restore','POST',{'track_id':identifier},**headers)[0]==200
    assert http(server,'/audio/'+identifier,Range='bytes=0-9')[0]==206


def test_agent_tool_delete_and_restore_contract(manager,sound):
    from tools.music_tool import parser,execute
    identifier=manager.publish(sound,payload())['track_id']
    p=parser()
    assert execute(p.parse_args(['delete','--track-id',identifier]),{},manager,None)['status']=='deleted'
    assert execute(p.parse_args(['trash']),{},manager,None)['tracks'][0]['track_id']==identifier
    assert execute(p.parse_args(['restore','--track-id',identifier]),{},manager,None)['status']=='restored'


def test_common_agent_hint_uses_canonical_contract_without_key(manager):
    from llm.music_context import music_context
    settings={'gemini':{'api_key':'SECRET_SENTINEL'},'llm':{'active_backend':'custom','custom':{'project_dir':str(manager.app_dir/'custom')}}}
    hint=music_context(manager,settings,None)
    assert 'SECRET_SENTINEL' not in hint and 'lyria-3.5' in hint and 'expected_revision' in hint
    assert 'music_tool.py' in hint and 'USAGE.md' in hint and 'needs_user_gesture' in hint
    assert all(s['id'] in hint for s in catalog()['styles'])
    assert (manager.app_dir/'custom/tool_payloads/music').is_dir()


@pytest.mark.parametrize('backend',['codex_cli','claude_code','opencode_cli','grok_cli','antigravity_cli'])
def test_common_prompt_discloses_music_to_every_backend_without_rewriting_private_guides(manager,backend):
    from core.assistant import VoiceAssistant
    assistant=VoiceAssistant.__new__(VoiceAssistant)
    assistant.voice_input_enabled=False;assistant.voice_output_enabled=False
    assistant.output_muted=True;assistant.whiteboard_manager=None;assistant.music_manager=manager
    workspace=manager.app_dir/backend;workspace.mkdir()
    guide=workspace/'AGENTS.md';guide.write_text('private instructions stay intact',encoding='utf-8')
    settings={'llm':{'active_backend':backend,backend:{'project_dir':str(workspace)}}}
    with patch('core.assistant.config.snapshot',return_value=settings):
        prompt=assistant._build_llm_prompt('想聽一首民謠',current_time='2026-10-26')
    assert 'music_tool.py' in prompt and 'lyria-3.5' in prompt and '想聽一首民謠' in prompt
    assert guide.read_text(encoding='utf-8')=='private instructions stay intact'
    with patch('llm.music_context.music_context',side_effect=OSError('storage unavailable')):
        assert '一般對話可繼續' in assistant._build_llm_prompt('你好',current_time='2026-10-26')
