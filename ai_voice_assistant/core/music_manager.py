"""Durable local music library, generation queue and acknowledged player control.

Each operation owns a short SQLite transaction; tool and UI processes share the
same contract. Credentials and audio blobs are never stored in the database.
"""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

from core.music_catalog import catalog, genre_ids, filter_tracks

TERMINAL={'completed','failed','cancelled','unknown_remote_result'}
PLAYER_ACTIONS={'select','play','pause','next','previous','seek','set-volume','set-repeat','set-filter'}
PLAYER_SEMANTIC_FIELDS={'track_id','playback_state','volume','repeat','genre_ids','genre_match','query','unclassified','renderer_ready'}


class MusicJobCancelled(ValueError):
    """Cancellation won the publication lock; do not publish or regenerate."""


def library_root(app_dir,directory):
    if not isinstance(directory,str) or not directory.strip():
        raise ValueError('請選擇專用的曲庫資料夾，不可留白。')
    app_dir=Path(app_dir).resolve()
    configured=Path(directory.strip()).expanduser()
    root=(configured if configured.is_absolute() else app_dir/configured).resolve()
    if root in (app_dir,app_dir.parent,Path(root.anchor)):
        raise ValueError('曲庫須使用專用資料夾，不能直接使用程式、專案或磁碟根目錄。')
    return root


def _text(value, limit, name, *, required=False):
    if not isinstance(value,str) or len(value)>limit or '\x00' in value or (required and not value.strip()):
        raise ValueError(f'{name} 請填有效文字（最多 {limit} 字）。')
    return value.strip()


def _number(value, low, high, name):
    if type(value) not in (float,int) or not math.isfinite(value) or not low<=value<=high:
        raise ValueError(f'{name} 必須介於 {low}–{high}。')
    return value


def atomic_json(path, data):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name('.'+path.name+'.'+uuid4().hex+'.tmp')
    try:
        with temporary.open('w',encoding='utf-8',newline='\n') as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def audio_metadata(path, *, max_seconds=300, max_bytes=30*1024*1024):
    import av
    import numpy as np
    path=Path(path)
    if not path.is_file() or not 1<=path.stat().st_size<=max_bytes:
        raise ValueError('音檔不存在、是空檔或超過大小上限。')
    samples=rate=channels=0
    peak=0.
    with av.open(str(path)) as container:
        if not container.streams.audio:
            raise ValueError('檔案沒有音軌。')
        for frame in container.decode(audio=0):
            if rate and (rate!=frame.sample_rate or channels!=len(frame.layout.channels)):
                raise ValueError('音檔格式不一致。')
            rate,channels=frame.sample_rate,len(frame.layout.channels)
            samples+=frame.samples
            if not rate or samples/rate>max_seconds or channels>2:
                raise ValueError('音檔長度或聲道超出上限。')
            peak=max(peak,float(np.max(np.abs(frame.to_ndarray().astype(np.float64)))))
    if not samples or not peak:
        raise ValueError('音檔沒有可播放的聲音。')
    return {'duration_seconds':samples/rate,'sample_rate':rate,'channels':channels,
            'byte_size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


class MusicManager:
    def __init__(self, app_dir, settings=None):
        self.app_dir=Path(app_dir).resolve()
        self.settings=dict((settings or {}).get('music',{}))
        self.root=library_root(self.app_dir,self.settings.get('directory','music_library'))
        for name in ('tracks','metadata','staging','trash'):
            (self.root/name).mkdir(parents=True,exist_ok=True)
        self.database=self.root/'catalog.sqlite3'
        with self.connect() as db:
            if db.execute('PRAGMA user_version').fetchone()[0] not in (0,1,2):
                raise ValueError('曲庫版本不受此程式支援；請使用對應版本或還原備份。')
            db.executescript('''
            CREATE TABLE IF NOT EXISTS tracks(id TEXT PRIMARY KEY, data TEXT NOT NULL, created REAL NOT NULL, sha TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS track_genres(track_id TEXT REFERENCES tracks(id) ON DELETE CASCADE, genre_id TEXT NOT NULL, PRIMARY KEY(track_id,genre_id));
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, track_id TEXT, reason TEXT, cancel INTEGER NOT NULL DEFAULT 0, notified INTEGER NOT NULL DEFAULT 0, session_id TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS runtime(id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT NOT NULL, heartbeat REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS player(id INTEGER PRIMARY KEY CHECK(id=1), content_id TEXT NOT NULL, revision TEXT NOT NULL, data TEXT NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, content_id TEXT NOT NULL, revision TEXT NOT NULL, data TEXT NOT NULL, state TEXT NOT NULL, reason TEXT, created REAL NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS deleted_tracks(id TEXT PRIMARY KEY, data TEXT NOT NULL, deleted REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS job_state ON jobs(state,created);
            CREATE INDEX IF NOT EXISTS command_state ON commands(content_id,state,created);
            PRAGMA user_version=2;
            ''')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.database,timeout=10)
        db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                yield db
        finally:
            db.close()

    def worker_ready(self):
        with self.connect() as db:
            row=db.execute('SELECT * FROM runtime WHERE id=1').fetchone()
        return bool(row and time.time()-row['heartbeat']<8)

    def normalize_request(self, payload):
        if not isinstance(payload,dict):
            raise ValueError('音樂 payload 必須是 JSON object。')
        allowed={'request_id','title','genre_ids','style_notes','tags','instrumental','requested_duration_seconds','prompt','lyrics','language','vocal_description'}
        if set(payload)-allowed:
            raise ValueError('音樂 payload 含不支援欄位；model 由 app 設定決定。')
        tags=payload.get('tags',[])
        if not isinstance(tags,list) or len(tags)>12:
            raise ValueError('tags 最多 12 項。')
        instrumental=payload.get('instrumental',True)
        if type(instrumental) is not bool:
            raise ValueError('instrumental 必須是 boolean。')
        result={'request_id':_text(payload.get('request_id',''),120,'request_id',required=True),
                'title':_text(payload.get('title','新旋律'),80,'title',required=True),
                'genre_ids':genre_ids(payload.get('genre_ids',[])),
                'tags':list(dict.fromkeys(_text(t,40,'tag',required=True) for t in tags)),
                'instrumental':instrumental,
                'requested_duration_seconds':_number(payload.get('requested_duration_seconds',60),10,180,'期望長度')}
        for field,maximum in (('prompt',4000),('style_notes',500),('lyrics',3000),('language',30),('vocal_description',200)):
            result[field]=_text(payload.get(field,''),maximum,field)
        if instrumental and result['lyrics']:
            raise ValueError('純音樂不能同時指定歌詞。')
        return result

    def enqueue(self,payload):
        request=self.normalize_request(payload)
        if not self.settings.get('enabled',True) or self.settings.get('model','lyria-3.5')!='lyria-3.5':
            raise ValueError('音樂創作未啟用或 model 不是 lyria-3.5。')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT * FROM jobs WHERE request_id=?',(request['request_id'],)).fetchone()
            if previous:
                if json.loads(previous['payload'])!=request:
                    raise ValueError('同一 request_id 的內容不同，未重複生成。')
                return self._job(previous)
            runtime=db.execute('SELECT * FROM runtime WHERE id=1').fetchone()
            if not runtime or time.time()-runtime['heartbeat']>=8:
                raise ValueError('愛管家音樂服務尚未就緒；請先啟動主畫面。')
            start=datetime.now(ZoneInfo('Asia/Taipei')).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
            used=db.execute('SELECT COUNT(*) FROM jobs WHERE created>=?',(start,)).fetchone()[0]
            limit=int(self.settings.get('daily_generation_limit',10))
            budget=float(self.settings.get('daily_budget_usd',.8))
            if used>=limit or (used+1)*.08>budget+1e-9:
                raise ValueError('今日音樂生成次數或預估費用已達設定上限；既有歌曲仍可播放。')
            if self.storage_bytes()>=int(self.settings.get('max_storage_mb',2048))*1024*1024:
                raise ValueError('曲庫容量已滿；既有歌曲保留，未新增工作。')
            identifier=uuid4().hex
            now=time.time()
            db.execute('INSERT INTO jobs(id,request_id,payload,state,created,updated,session_id) VALUES(?,?,?,?,?,?,?)',
                       (identifier,request['request_id'],json.dumps(request,ensure_ascii=False),'queued',now,now,runtime['owner']))
            return self._job(db.execute('SELECT * FROM jobs WHERE id=?',(identifier,)).fetchone())

    @staticmethod
    def _job(row):
        if row is None:
            raise ValueError('找不到音樂工作。')
        payload=json.loads(row['payload'])
        return {'job_id':row['id'],'request_id':row['request_id'],'status':row['state'],
                'title':payload['title'],'track_id':row['track_id'],'reason':row['reason'],
                'created_at':row['created'],'updated_at':row['updated'],'cancel_requested':bool(row['cancel'])}

    def job(self,identifier):
        with self.connect() as db:
            return self._job(db.execute('SELECT * FROM jobs WHERE id=?',(identifier,)).fetchone())

    def jobs(self):
        with self.connect() as db:
            return [self._job(r) for r in db.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 100')]

    def cancel(self,identifier):
        from core.whiteboard_manager import _StateFileLock
        with _StateFileLock(self.root/'.library.lock'):
            return self._cancel(identifier)

    def _cancel(self,identifier):
        with self.connect() as db:
            row=db.execute('SELECT * FROM jobs WHERE id=?',(identifier,)).fetchone()
            job=self._job(row)
            if job['status'] not in TERMINAL:
                state='cancelled' if job['status']=='queued' else job['status']
                db.execute('UPDATE jobs SET cancel=1,state=?,updated=? WHERE id=?',(state,time.time(),identifier))
        return self.job(identifier)

    def storage_bytes(self):
        total=0
        for path in self.root.rglob('*'):
            try:
                if path.is_file():
                    total+=path.stat().st_size
            except FileNotFoundError:
                pass  # worker may atomically publish/remove its own staging
        return total

    def tracks(self,selected=(),match='any',query='',unclassified=False):
        with self.connect() as db:
            rows=db.execute('SELECT data FROM tracks ORDER BY created DESC,id DESC').fetchall()
        tracks=[]
        for row in rows:
            data=json.loads(row['data'])
            data['available']=self.audio_path(data['track_id'],required=False) is not None
            tracks.append(data)
        return filter_tracks(tracks,selected,match,query,unclassified)

    def track(self,identifier):
        with self.connect() as db:
            row=db.execute('SELECT data FROM tracks WHERE id=?',(identifier,)).fetchone()
        if not row:
            raise ValueError('找不到這首歌曲。')
        return json.loads(row['data'])

    def audio_path(self,identifier,*,required=True):
        if not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{32}',identifier):
            raise ValueError('track_id 格式無效。')
        with self.connect() as db:
            row=db.execute('SELECT data FROM tracks WHERE id=?',(identifier,)).fetchone()
        path=None
        if row:
            name=json.loads(row['data']).get('audio_file','')
            candidate=(self.root/'tracks'/name).resolve()
            if (candidate.parent== (self.root/'tracks').resolve() and candidate.is_file()
                    and candidate.name in (identifier+'.mp3',identifier+'.wav')):
                path=candidate
        if path is None and required:
            raise ValueError('音檔遺失或不可讀取；未自動重生成。')
        return path

    def publish(self,source,request,*,job_id=None,provider_version='',response_id='',generation_started=None):
        source=Path(source).resolve()
        if source.suffix.lower() not in ('.mp3','.wav'):
            raise ValueError('只接受 MP3 或 WAV 音檔。')
        info=audio_metadata(source,max_seconds=self.settings.get('max_audio_seconds',300))
        from core.whiteboard_manager import _StateFileLock
        with _StateFileLock(self.root/'.library.lock'):
            return self._publish(source,request,info,job_id,provider_version,response_id,generation_started)

    def _publish(self,source,request,info,job_id,provider_version,response_id,generation_started):
        if job_id:
            with self.connect() as db:
                job=db.execute('SELECT cancel,state FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not job:
                raise ValueError('找不到音樂工作。')
            if job['cancel'] or job['state']=='cancelled':
                raise MusicJobCancelled('音樂工作已取消。')
        if self.storage_bytes()+info['byte_size']>int(self.settings.get('max_storage_mb',2048))*1024*1024:
            raise ValueError('曲庫容量已滿，未發布新歌曲。')
        identifier=uuid4().hex
        name=identifier+source.suffix.lower()
        title=_text(request.get('title','新旋律'),80,'title',required=True)
        notes=_text(request.get('style_notes',''),500,'style_notes')
        prompt=_text(request.get('prompt',''),4000,'prompt')
        lyrics=_text(request.get('lyrics',''),3000,'lyrics')
        tags=request.get('tags',[])
        if not isinstance(tags,list) or len(tags)>12:
            raise ValueError('tags 最多 12 項。')
        tags=list(dict.fromkeys(_text(t,40,'tag',required=True) for t in tags))
        data=dict(info,track_id=identifier,title=title,
                  genre_ids=genre_ids(request.get('genre_ids',[])),requested_genre_ids=genre_ids(request.get('genre_ids',[])),
                  tags=tags,style_notes=notes,
                  instrumental_requested=request.get('instrumental',True),prompt=prompt,
                  lyrics_requested=lyrics,lyrics_verified=False,review_status='未確認',
                  requested_duration_seconds=request.get('requested_duration_seconds'),
                  model='lyria-3.5' if job_id else 'imported',provider_version=provider_version,
                  response_id=response_id,job_id=job_id,audio_file=name,created_at=time.time(),
                  estimated_cost_usd=.08 if job_id else 0)
        temporary=self.root/'tracks'/('.'+name+'.part')
        try:
            shutil.copyfile(source,temporary)
            if generation_started is not None:
                data['generation_elapsed_ms']=(time.monotonic()-generation_started)*1000
            atomic_json(self.root/'metadata'/(identifier+'.json'),data)
            os.replace(temporary,self.root/'tracks'/name)
            self._index_track(data)
        finally:
            temporary.unlink(missing_ok=True)
        return data

    def _index_track(self,data,*,restore=False):
        # Replayable after a crash between file publication and database commit.
        with self.connect() as db:
            if restore:
                db.execute('DELETE FROM deleted_tracks WHERE id=?',(data['track_id'],))
            elif db.execute('SELECT 1 FROM deleted_tracks WHERE id=?',(data['track_id'],)).fetchone():
                return  # a late worker/retag must not resurrect deleted music
            db.execute('INSERT OR REPLACE INTO tracks VALUES(?,?,?,?)',
                       (data['track_id'],json.dumps(data,ensure_ascii=False),data['created_at'],data['sha256']))
            db.execute('DELETE FROM track_genres WHERE track_id=?',(data['track_id'],))
            db.executemany('INSERT INTO track_genres VALUES(?,?)',[(data['track_id'],g) for g in data['genre_ids']])
            if data.get('job_id'):
                db.execute("UPDATE jobs SET state='completed',track_id=?,updated=?,reason=NULL WHERE id=?",
                           (data['track_id'],time.time(),data['job_id']))

    def recover(self):
        from core.whiteboard_manager import _StateFileLock
        with _StateFileLock(self.root/'.library.lock'):
            self._recover()

    def _recover(self):
        # The journal is authoritative even after an interrupted deletion or a
        # rebuilt SQLite index. Audio stays private and can be restored as-is.
        journal_ids=set()
        for path in (self.root/'trash').glob('*.json'):
            if not re.fullmatch('[a-f0-9]{32}',path.stem):
                continue
            journal_ids.add(path.stem)
            try:
                record=json.loads(path.read_text(encoding='utf-8'))
                if not self._valid_recovery_data(record['track'],path.stem):
                    continue
                if record['state']=='deleted':
                    _number(record.get('deleted_at'),0,1e12,'deleted_at')
                    self._apply_delete(record)
                elif record['state']=='restored':
                    metadata=self.root/'metadata'/(path.stem+'.json')
                    data=json.loads(metadata.read_text(encoding='utf-8')) if metadata.is_file() else record['track']
                    if not self._valid_recovery_data(data,path.stem):
                        continue
                    self._index_track(data,restore=True)
                    path.unlink()
            except (OSError,ValueError,KeyError,TypeError):
                continue
        with self.connect() as db:
            known={r[0] for r in db.execute('SELECT id FROM tracks')}
            known.update(r[0] for r in db.execute('SELECT id FROM deleted_tracks'))
            known.update(journal_ids)  # malformed deletion journals fail closed
        for path in (self.root/'metadata').glob('*.json'):
            if path.stem in known:
                continue
            try:
                data=json.loads(path.read_text(encoding='utf-8'))
                if not self._valid_recovery_data(data,path.stem):
                    continue
                audio=(self.root/'tracks'/data['audio_file']).resolve()
                if (audio.parent!=(self.root/'tracks').resolve() or not audio.is_file()
                        or audio.name not in (path.stem+'.mp3',path.stem+'.wav')):
                    continue
                if hashlib.sha256(audio.read_bytes()).hexdigest()!=data['sha256']:
                    continue
                genre_ids(data['genre_ids'])
                self._index_track(data)
            except (OSError,ValueError,KeyError,TypeError):
                continue

    @staticmethod
    def _valid_recovery_data(data,identifier):
        if (not isinstance(data,dict) or not re.fullmatch('[a-f0-9]{32}',identifier)
                or data.get('track_id')!=identifier
                or data.get('audio_file') not in (identifier+'.mp3',identifier+'.wav')
                or not isinstance(data.get('sha256'),str) or not re.fullmatch('[a-f0-9]{64}',data['sha256'])):
            return False
        _text(data.get('title'),80,'title',required=True)
        _number(data.get('created_at'),0,1e12,'created_at')
        genre_ids(data.get('genre_ids'))
        return True

    def retag(self,identifier,genres,*,title=None,tags=None):
        from core.whiteboard_manager import _StateFileLock
        with _StateFileLock(self.root/'.library.lock'):
            return self._retag(identifier,genres,title=title,tags=tags)

    def _retag(self,identifier,genres,*,title=None,tags=None):
        data=self.track(identifier)
        data['genre_ids']=genre_ids(genres)
        if title is not None:
            data['title']=_text(title,80,'title',required=True)
        if tags is not None:
            if not isinstance(tags,list) or len(tags)>12:
                raise ValueError('tags 最多 12 項。')
            data['tags']=[_text(t,40,'tag',required=True) for t in tags]
        atomic_json(self.root/'metadata'/(identifier+'.json'),data)
        self._index_track(data)
        return data

    def deleted_tracks(self):
        with self.connect() as db:
            return [dict(json.loads(r['data']),deleted_at=r['deleted']) for r in
                    db.execute('SELECT * FROM deleted_tracks ORDER BY deleted DESC,id')]

    def delete(self,identifier):
        if not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{32}',identifier):
            raise ValueError('track_id 格式無效。')
        from core.whiteboard_manager import _StateFileLock
        with _StateFileLock(self.root/'.library.lock'):
            with self.connect() as db:
                prior=db.execute('SELECT deleted FROM deleted_tracks WHERE id=?',(identifier,)).fetchone()
            if prior:
                return {'status':'deleted','track_id':identifier,'undoable':True}
            data=self.track(identifier)
            record={'state':'deleted','track':data,'deleted_at':time.time()}
            atomic_json(self.root/'trash'/(identifier+'.json'),record)
            self._apply_delete(record)
            return {'status':'deleted','track_id':identifier,'undoable':True}

    def _apply_delete(self,record):
        data=record['track'];identifier=data['track_id']
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO deleted_tracks VALUES(?,?,?)',
                       (identifier,json.dumps(data,ensure_ascii=False),record['deleted_at']))
            db.execute('DELETE FROM tracks WHERE id=?',(identifier,))
            db.execute('UPDATE jobs SET notified=1 WHERE track_id=?',(identifier,))
            row=db.execute('SELECT * FROM player WHERE id=1').fetchone()
            state=json.loads(row['data']) if row else {}
            selected=state.get('track_id')==identifier
            if selected:
                state.update(track_id=None,position_seconds=0,duration_seconds=0,
                             playback_state='unknown',renderer_ready=False,heartbeat=0)
                db.execute('UPDATE player SET revision=?,data=?,updated=? WHERE id=1',
                           (uuid4().hex,json.dumps(state),time.time()))
            for command in db.execute("SELECT id,data FROM commands WHERE state='accepted'").fetchall():
                if selected or json.loads(command['data']).get('track_id')==identifier:
                    db.execute("UPDATE commands SET state='expired',reason='track_deleted' WHERE id=?",(command['id'],))

    def restore_track(self,identifier):
        if not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{32}',identifier):
            raise ValueError('track_id 格式無效。')
        from core.whiteboard_manager import _StateFileLock
        with _StateFileLock(self.root/'.library.lock'):
            with self.connect() as db:
                row=db.execute('SELECT * FROM deleted_tracks WHERE id=?',(identifier,)).fetchone()
            if not row:
                self.track(identifier)
                return {'status':'restored','track_id':identifier}
            data=json.loads(row['data'])
            atomic_json(self.root/'trash'/(identifier+'.json'),
                        {'state':'restored','track':data,'deleted_at':row['deleted']})
            self._index_track(data,restore=True)
            (self.root/'trash'/(identifier+'.json')).unlink(missing_ok=True)
            return {'status':'restored','track_id':identifier}

    def player_open(self,content_id,track_id=None):
        if track_id:
            self.audio_path(track_id)
        with self.connect() as db:
            row=db.execute('SELECT * FROM player WHERE id=1').fetchone()
            if not row or row['content_id']!=content_id:
                state={'track_id':track_id,'playback_state':'paused','position_seconds':0,'volume':.6,
                       'repeat':'none','genre_ids':[],'genre_match':'any','query':'','renderer_ready':False,
                       'heartbeat':0,'last_command_id':None,'message':''}
                revision=uuid4().hex
                db.execute("UPDATE commands SET state='expired',reason='stale_content' WHERE state='accepted'")
                db.execute('INSERT OR REPLACE INTO player VALUES(1,?,?,?,?)',
                           (content_id,revision,json.dumps(state),time.time()))
            elif track_id:
                state=json.loads(row['data'])
                if not state.get('renderer_ready') or time.time()-state.get('heartbeat',0)>6:
                    state.update(track_id=track_id,position_seconds=0,playback_state='paused')
                    db.execute('UPDATE player SET data=?,updated=? WHERE id=1',(json.dumps(state),time.time()))
        return self.player_status()

    def player_status(self):
        with self.connect() as db:
            row=db.execute('SELECT * FROM player WHERE id=1').fetchone()
        if not row:
            return {'status':'renderer_unavailable','renderer_ready':False}
        state=json.loads(row['data'])
        state.update(content_id=row['content_id'],revision=row['revision'],status='applied')
        if not state.get('renderer_ready') or time.time()-state.get('heartbeat',0)>6:
            state.update(status='renderer_unavailable',renderer_ready=False,playback_state='unknown')
        return state

    def suspend_player(self,content_id):
        with self.connect() as db:
            row=db.execute('SELECT * FROM player WHERE id=1 AND content_id=?',(content_id,)).fetchone()
            if row:
                state=json.loads(row['data'])
                state.update(playback_state='paused',renderer_ready=False,heartbeat=0)
                db.execute('UPDATE player SET data=?,updated=? WHERE id=1',(json.dumps(state),time.time()))
            db.execute("UPDATE commands SET state='expired',reason='renderer_unavailable' WHERE content_id=? AND state='accepted'",(content_id,))

    def control(self,payload,*,allow_select=False):
        if not isinstance(payload,dict) or set(payload)-{'request_id','content_id','expected_revision','action','track_id','position_seconds','volume','repeat','genre_ids','genre_match','query','unclassified'}:
            raise ValueError('播放器指令含不支援欄位。')
        action=payload.get('action')
        if action not in PLAYER_ACTIONS or (action=='select' and not allow_select):
            raise ValueError('不支援的播放器動作。')
        request_id=_text(payload.get('request_id',''),120,'request_id',required=True)
        if payload.get('track_id'):
            self.audio_path(payload['track_id'])
        if 'volume' in payload:
            _number(payload['volume'],0,1,'volume')
        if 'position_seconds' in payload:
            _number(payload['position_seconds'],0,300,'position_seconds')
        if action=='seek' and 'position_seconds' not in payload or action=='set-volume' and 'volume' not in payload:
            raise ValueError('缺少播放器動作需要的參數。')
        if action=='set-repeat' and 'repeat' not in payload or action=='select' and not payload.get('track_id'):
            raise ValueError('缺少播放器動作需要的參數。')
        if 'unclassified' in payload and type(payload['unclassified']) is not bool:
            raise ValueError('unclassified 必須是 boolean。')
        if 'genre_ids' in payload:
            genre_ids(payload['genre_ids'])
        if payload.get('genre_match','any') not in ('any','all') or payload.get('repeat','none') not in ('none','one','all'):
            raise ValueError('播放器篩選或循環設定無效。')
        if 'query' in payload:
            _text(payload['query'],200,'query')
        now=time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT * FROM commands WHERE request_id=?',(request_id,)).fetchone()
            if previous:
                if json.loads(previous['data'])!=payload:
                    raise ValueError('同一 request_id 的播放器指令不同。')
                return self._command(previous)
            row=db.execute('SELECT * FROM player WHERE id=1').fetchone()
            if not row or row['content_id']!=payload.get('content_id'):
                return {'status':'stale_content'}
            state=json.loads(row['data'])
            if row['revision']!=payload.get('expected_revision'):
                return {'status':'stale_revision'}
            if not state.get('renderer_ready') or now-state.get('heartbeat',0)>6:
                return {'status':'renderer_unavailable'}
            db.execute("UPDATE commands SET state='expired',reason='timeout' WHERE state='accepted' AND expires<?",(now,))
            db.execute("UPDATE commands SET state='expired',reason='stale_revision' WHERE state='accepted' AND content_id=? AND revision!=?",
                       (row['content_id'],row['revision']))
            if db.execute("SELECT 1 FROM commands WHERE content_id=? AND state='accepted'",(row['content_id'],)).fetchone():
                return {'status':'busy','reason':'command_pending'}
            identifier=uuid4().hex
            db.execute('INSERT INTO commands VALUES(?,?,?,?,?,?,?,?,?)',
                (identifier,request_id,row['content_id'],row['revision'],json.dumps(payload),'accepted',None,now,now+12))
            return {'status':'accepted','command_id':identifier,'content_id':row['content_id']}

    @staticmethod
    def _command(row):
        return {'command_id':row['id'],'status':row['state'],'reason':row['reason'],'action':json.loads(row['data'])['action']}

    def commands(self,content_id):
        with self.connect() as db:
            db.execute("UPDATE commands SET state='expired',reason='timeout' WHERE state='accepted' AND expires<?",(time.time(),))
            db.execute("""UPDATE commands SET state='expired',reason='stale_revision' WHERE state='accepted'
                AND content_id=? AND revision!=(SELECT revision FROM player WHERE id=1)""",(content_id,))
            rows=db.execute("SELECT * FROM commands WHERE content_id=? AND state='accepted' ORDER BY created,id",(content_id,)).fetchall()
        return [dict(self._command(r),payload=json.loads(r['data']),expires_at=r['expires']) for r in rows]

    def renderer_report(self,content_id,payload):
        allowed={'track_id','playback_state','position_seconds','duration_seconds','volume','repeat','genre_ids','genre_match','query','unclassified','renderer_ready','command_id','command_status','message'}
        if not isinstance(payload,dict) or set(payload)-allowed:
            raise ValueError('播放器狀態格式無效。')
        if payload.get('track_id'):
            self.track(payload['track_id'])
        for key,low,high in (('position_seconds',0,300),('duration_seconds',0,300),('volume',0,1)):
            if key in payload:
                _number(payload[key],low,high,key)
        if payload.get('playback_state') not in ('playing','paused','buffering','ended','needs_user_gesture','error'):
            raise ValueError('playback_state 無效。')
        if payload.get('repeat','none') not in ('none','one','all') or payload.get('genre_match','any') not in ('any','all'):
            raise ValueError('播放器狀態設定無效。')
        genre_ids(payload.get('genre_ids',[]))
        for field in ('renderer_ready','unclassified'):
            if field in payload and type(payload[field]) is not bool:
                raise ValueError(field+' 必須是 boolean。')
        for field in ('query','message'):
            _text(payload.get(field,''),200,field)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM player WHERE id=1 AND content_id=?',(content_id,)).fetchone()
            if not row:
                return {'status':'stale_content'}
            state=json.loads(row['data'])
            command_id=payload.get('command_id')
            revision=row['revision']
            if command_id:
                command=db.execute("SELECT * FROM commands WHERE id=? AND content_id=? AND state='accepted'",(command_id,content_id)).fetchone()
                if not command or command['expires']<time.time():
                    return {'status':'expired'}
                if command['revision']!=row['revision']:
                    db.execute("UPDATE commands SET state='expired',reason='stale_revision' WHERE id=?",(command_id,))
                    return {'status':'stale_revision'}
                status=payload.get('command_status','applied')
                if status not in ('applied','needs_user_gesture','error'):
                    raise ValueError('command_status 無效。')
                db.execute('UPDATE commands SET state=?,reason=? WHERE id=?',(status,payload.get('message',''),command_id))
                state['last_command_id']=command_id
                revision=uuid4().hex
            if any(key in payload and state.get(key)!=payload[key] for key in PLAYER_SEMANTIC_FIELDS):
                revision=uuid4().hex
            state.update({k:v for k,v in payload.items() if k not in ('command_id','command_status')})
            state['heartbeat']=time.time()
            db.execute('UPDATE player SET revision=?,data=?,updated=? WHERE id=1',(revision,json.dumps(state),time.time()))
        return self.player_status()

    def manifest(self):
        tracks=self.tracks()
        public=[]
        for t in tracks:
            public.append({k:t.get(k) for k in ('track_id','title','genre_ids','tags','style_notes','duration_seconds','created_at','review_status','available')})
        styles=[]
        for style in catalog()['styles']:
            styles.append(dict(style,count=sum(style['id'] in t['genre_ids'] for t in tracks)))
        return {'tracks':public,'styles':styles,'catalog_version':catalog()['version'],
                'trash':[{k:t.get(k) for k in ('track_id','title','genre_ids','duration_seconds','deleted_at')}
                         for t in self.deleted_tracks()],
                'jobs':self.jobs(),'player':self.player_status(),'total':len(tracks),'model':'lyria-3.5'}
