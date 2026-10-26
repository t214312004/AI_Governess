"""Agent music tools. Read capabilities/styles first; no credential output."""
import argparse
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

sys.dont_write_bytecode=True
APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))

from config import config
from core.music_catalog import catalog
from core.music_manager import MusicManager
from core.whiteboard_manager import WhiteboardManager
from utils.gemini_api_cli import resolve_executable
from utils.gemini_audio import resolve_api_key


def whiteboard(settings,app_dir=APP):
    options=settings.get('whiteboard',{})
    if not options.get('enabled',True):
        return None
    return WhiteboardManager(app_dir,state_dir=options.get('state_dir','whiteboard_state'),
                             html_daily_minutes=options.get('html_daily_minutes',30))


def capabilities(manager,settings,board):
    ready=False
    try:
        resolve_executable(settings.get('gemini_api_cli',{}).get('executable',''))
        c=settings.get('gemini',{})
        resolve_api_key(c.get('api_key',''),c.get('api_key_env','GEMINI_API_KEY'))
        ready=True
    except Exception:
        pass
    worker=manager.worker_ready()
    return {'contract_version':1,'style_catalog_version':catalog()['version'],
            'music_model':'lyria-3.5','music_available':bool(ready and worker and settings.get('music',{}).get('enabled',True)
                and settings.get('music',{}).get('model','lyria-3.5')=='lyria-3.5'),
            'player_available':board is not None,'worker_ready':worker,'cli_and_key_configured':ready,
            'html_time_metered':False,'guide':str(APP/'tools/music/USAGE.md')}


def load_payload(path,settings):
    candidate=Path(path).resolve()
    backend=settings.get('llm',{}).get('active_backend','')
    project=Path(settings.get('llm',{}).get(backend,{}).get('project_dir','agent_workspace'))
    if not project.is_absolute():
        project=APP/project
    roots=[(APP/'agent_workspace/tool_payloads/music').resolve(),(project/'tool_payloads/music').resolve()]
    if not any(candidate.is_relative_to(root) for root in roots) or candidate.stat().st_size>64*1024:
        raise ValueError('payload 必須是工作區 tool_payloads/music/ 內不超過 64 KiB 的 JSON。')
    return json.loads(candidate.read_text(encoding='utf-8-sig'))


def execute(args,settings,manager,board):
    action=args.action
    if action=='capabilities':
        return capabilities(manager,settings,board)
    if action=='styles':
        return catalog()
    if action=='generate':
        if not capabilities(manager,settings,board)['music_available']:
            return {'status':'unavailable','message_for_user':'請先啟動主畫面，並在初始 UI 完成 Gemini API CLI 與 Google key 設定。'}
        return manager.enqueue(load_payload(args.payload,settings))
    if action=='job-status':
        return manager.job(args.job_id)
    if action=='cancel':
        return manager.cancel(args.job_id)
    if action=='list':
        tracks=manager.tracks(args.genre_id,args.genre_match,args.query,args.unclassified)
        return {'status':'ok','total':len(tracks),'tracks':[{k:t.get(k) for k in
            ('track_id','title','genre_ids','style_notes','duration_seconds','available')} for t in tracks[:args.limit]]}
    if action=='show-player':
        if board is None:
            return {'status':'unavailable','message_for_user':'白板功能未啟用。'}
        if args.track_id:
            manager.audio_path(args.track_id)
        result=board.show_music()
        if result['status']=='shown':
            state=manager.player_open(result['content_id'],args.track_id)
            if args.track_id and state.get('renderer_ready'):
                manager.control({'request_id':uuid4().hex,'content_id':result['content_id'],
                    'expected_revision':state['revision'],'action':'select','track_id':args.track_id},allow_select=True)
        return result
    if action=='player-status':
        result=manager.player_status()
        active=board.get_active() if board else None
        if not active or active.get('content_type')!='music' or active.get('hidden') or active.get('content_id')!=result.get('content_id'):
            result.update(status='renderer_unavailable',renderer_ready=False,playback_state='unknown')
        if args.command_id:
            manager.commands(result.get('content_id',''))  # expire commands even without a live renderer
            with manager.connect() as db:
                row=db.execute('SELECT * FROM commands WHERE id=?',(args.command_id,)).fetchone()
            result['command']=manager._command(row) if row else {'status':'not_found'}
        return result
    if action=='player-control':
        if board is None or not (board.get_active() or {}).get('content_type')=='music' or (board.get_active() or {}).get('hidden'):
            return {'status':'renderer_unavailable'}
        return manager.control(load_payload(args.payload,settings))
    if action=='import':
        request={'title':args.title,'genre_ids':args.genre_id,'tags':[],'style_notes':args.notes}
        return {'status':'imported','track':manager.publish(args.path,request)}
    if action=='retag':
        return {'status':'updated','track':manager.retag(args.track_id,args.genre_id,title=args.title)}
    if action=='delete':
        return manager.delete(args.track_id)
    if action=='restore':
        return manager.restore_track(args.track_id)
    if action=='trash':
        return {'status':'ok','tracks':[{k:t.get(k) for k in ('track_id','title','genre_ids','deleted_at')}
                                      for t in manager.deleted_tracks()]}
    raise ValueError('未知音樂工具動作。')


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='action',required=True)
    for name in ('capabilities','styles'):
        sub.add_parser(name)
    for name in ('generate','player-control'):
        sub.add_parser(name).add_argument('--payload',required=True)
    for name in ('job-status','cancel'):
        sub.add_parser(name).add_argument('--job-id',required=True)
    listing=sub.add_parser('list')
    listing.add_argument('--genre-id',action='append',default=[])
    listing.add_argument('--genre-match',choices=('any','all'),default='any')
    listing.add_argument('--query',default='')
    listing.add_argument('--unclassified',action='store_true')
    listing.add_argument('--limit',type=int,choices=range(1,501),default=50)
    sub.add_parser('show-player').add_argument('--track-id')
    sub.add_parser('player-status').add_argument('--command-id')
    imp=sub.add_parser('import')
    imp.add_argument('--path',required=True)
    imp.add_argument('--title',required=True)
    imp.add_argument('--genre-id',action='append',default=[])
    imp.add_argument('--notes',default='')
    tag=sub.add_parser('retag')
    tag.add_argument('--track-id',required=True)
    tag.add_argument('--genre-id',action='append',default=[])
    tag.add_argument('--title')
    sub.add_parser('trash')
    for action in ('delete','restore'):
        sub.add_parser(action).add_argument('--track-id',required=True)
    return p


def main():
    sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    args=parser().parse_args()
    try:
        settings=config.snapshot()
        result=execute(args,settings,MusicManager(APP,settings),whiteboard(settings))
    except Exception as exc:
        result={'status':'error','message_for_user':str(exc) if isinstance(exc,ValueError) else '音樂工具操作失敗：'+type(exc).__name__}
    print(json.dumps(result,ensure_ascii=False))
    return 1 if result.get('status')=='error' else 0


if __name__=='__main__':
    raise SystemExit(main())
