"""First-party music renderer: fixed assets, scoped audio and acknowledged RPC."""
import hmac
from http.server import ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import secrets
import sqlite3
import threading
from urllib.parse import urlsplit

from ui.embedded_html import NativeHtmlRenderer
from ui.html_whiteboard import _WhiteboardRequestHandler, inject_audio_bridge
from utils.logger import get_logger

ASSETS=Path(__file__).with_name('music_player').resolve()
logger=get_logger(__name__)


class MusicRequestHandler(_WhiteboardRequestHandler):
    def _valid_host(self):
        return self.headers.get('Host')==f'127.0.0.1:{self.server.server_address[1]}'

    def _active(self):
        try:
            active=self.server.board.get_active() if self.server.board else None
        except (OSError,ValueError,TypeError):
            return False
        return bool(active and active.get('content_type')=='music' and not active.get('hidden')
                    and active.get('content_id')==self.server.content_id)

    def _json(self,value,status=200):
        body=json.dumps(value,ensure_ascii=False).encode('utf-8')
        self._send_headers(status,'application/json; charset=utf-8',len(body))
        self.wfile.write(body)

    def do_HEAD(self):
        if urlsplit(self.path).path.startswith(('/api/','/__ai_governess/')):
            self._send_headers(405,'text/plain; charset=utf-8',0)
            return
        self.do_GET(head=True)

    def do_GET(self,head=False):
        if not self._valid_host():
            self.send_error(403)
            return
        route=urlsplit(self.path).path
        if route in ('/__ai_governess/audio','/__ai_governess/input'):
            return super().do_GET()
        if route.startswith('/api/') and (head or not self._active()):
            self._json({'status':'renderer_unavailable'},409)
            return
        try:
            if route=='/api/state':
                self._json(dict(self.server.manager.manifest(),token=self.server.token,content_id=self.server.content_id))
                return
            if route=='/api/commands':
                self._json({'commands':self.server.manager.commands(self.server.content_id)})
                return
            if route.startswith('/audio/'):
                identifier=route.removeprefix('/audio/')
                path=self.server.manager.audio_path(identifier)
                self._file(path,head=head,ranges=True)
                return
            files={'/':'index.html','/index.html':'index.html','/player.css':'player.css','/player.js':'player.js'}
            if route not in files:
                self.send_error(404)
                return
            path=ASSETS/files[route]
            if path.suffix=='.html':
                body=inject_audio_bridge(path.read_text(encoding='utf-8')).encode('utf-8')
                self._send_headers(200,'text/html; charset=utf-8',len(body))
                if not head:
                    self.wfile.write(body)
            else:
                self._file(path,head=head)
        except (ValueError,OSError):
            self.send_error(404)
        except sqlite3.Error:
            self._json({'status':'unavailable','message_for_user':'曲庫暫時無法讀取，請稍後再試。'},503)

    def _file(self,path,*,head=False,ranges=False):
        size=path.stat().st_size
        begin,end,status=0,size-1,200
        value=self.headers.get('Range') if ranges else None
        if value:
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',value)
            valid=bool(match and (match[1] or match[2]))
            if valid:
                if match[1]:
                    begin=int(match[1]);end=min(size-1,int(match[2])) if match[2] else size-1
                else:
                    suffix=int(match[2]);begin=max(0,size-suffix)
                    valid=suffix>0
                valid=valid and 0<=begin<=end<size
            if not valid:
                self.send_response(416)
                self.send_header('Content-Range',f'bytes */{size}')
                self.send_header('Content-Length','0')
                self.end_headers()
                return
            status=206
        self.send_response(status)
        self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length',str(end-begin+1))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cache-Control','no-store')
        if ranges:
            self.send_header('Accept-Ranges','bytes')
        if status==206:
            self.send_header('Content-Range',f'bytes {begin}-{end}/{size}')
        self.end_headers()
        if not head:
            with path.open('rb') as stream:
                stream.seek(begin)
                remaining=end-begin+1
                while remaining:
                    chunk=stream.read(min(64*1024,remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining-=len(chunk)

    def do_POST(self):
        port=self.server.server_address[1]
        if urlsplit(self.path).path=='/__ai_governess/focus':
            if self._valid_host() and self.headers.get('Origin')==f'http://127.0.0.1:{port}' and self._active():
                return super().do_POST()
            self.send_error(403)
            return
        if (not self._valid_host() or self.headers.get('Origin')!=f'http://127.0.0.1:{port}'
                or not hmac.compare_digest(self.headers.get('X-Music-Token',''),self.server.token)
                or not self._active()):
            self.send_error(403)
            return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 1<=length<=64*1024:
                raise ValueError('請求大小無效。')
            payload=json.loads(self.rfile.read(length).decode('utf-8'))
            if not isinstance(payload,dict):
                raise ValueError('請求必須是 object。')
            route=urlsplit(self.path).path
            if route=='/api/report':
                result=self.server.manager.renderer_report(self.server.content_id,payload)
            elif route=='/api/generate':
                from tools.music_tool import capabilities
                settings=self.server.settings()
                if not capabilities(self.server.manager,settings,self.server.board)['music_available']:
                    raise ValueError('請先在初始設定完成 Google key 與 Gemini API CLI 設定，並確認音樂服務已啟動。')
                result=self.server.manager.enqueue(payload)
            elif route=='/api/cancel':
                result=self.server.manager.cancel(payload.get('job_id',''))
            elif route=='/api/retag':
                track=self.server.manager.retag(payload.get('track_id',''),payload.get('genre_ids',[]),title=payload.get('title'))
                result={'status':'updated','track_id':track['track_id']}
            elif route=='/api/delete':
                result=self.server.manager.delete(payload.get('track_id',''))
            elif route=='/api/restore':
                result=self.server.manager.restore_track(payload.get('track_id',''))
            else:
                self.send_error(404)
                return
            self._json(result)
        except (ValueError,TypeError,KeyError):
            # Fixed user text; provider bodies and credentials cannot reach JS.
            self._json({'status':'error','message_for_user':'操作未完成，請檢查設定、欄位或今日生成上限，再重新嘗試。'},400)
        except (OSError,sqlite3.Error):
            self._json({'status':'unavailable','message_for_user':'曲庫暫時無法寫入，請稍後再試。'},503)


class MusicPlayerRenderer(NativeHtmlRenderer):
    def __init__(self,state_dir,manager,board,settings,**kwargs):
        self.manager,self.board,self.settings=manager,board,settings
        self.content_id=None
        super().__init__(Path(state_dir)/'music',**kwargs)

    def _start_server(self,source_path):
        if Path(source_path).resolve()!=ASSETS/'index.html':
            raise ValueError('音樂播放器只接受 app 內建入口。')
        server=ThreadingHTTPServer(('127.0.0.1',self._preferred_port(source_path)),MusicRequestHandler)
        server.daemon_threads=True
        server.handle_error=lambda *_:None
        server.manager,server.board,server.settings=self.manager,self.board,self.settings
        server.content_id,server.token=self.content_id,secrets.token_urlsafe(32)
        server.source_root=ASSETS
        server.entry_path=ASSETS/'index.html'
        server.volume_getter=self._effective_volume
        server.input_getter=self.input_state
        server.keyboard_capture_notifier=self.set_keyboard_capture
        self._server=server
        self._server_thread=threading.Thread(target=server.serve_forever,daemon=True,name='music-http')
        self._server_thread.start()

    def show_music(self,parent_hwnd,content_id,width,height):
        if self.content_id!=content_id:
            self.stop()
        self.content_id=content_id
        self.manager.player_open(content_id)
        super().show(parent_hwnd,ASSETS/'index.html',width,height)

    def stop(self):
        try:
            if self.content_id:
                self.manager.suspend_player(self.content_id)
        except (OSError,ValueError,sqlite3.Error):
            logger.warning('Music player state could not be saved during shutdown.')
        finally:
            super().stop()

    def reload(self):
        try:
            if self.content_id:
                self.manager.suspend_player(self.content_id)
        except (OSError,ValueError,sqlite3.Error):
            logger.warning('Music player state could not be saved during reload.')
        super().reload()
