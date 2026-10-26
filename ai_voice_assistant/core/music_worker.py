"""App-owned single music worker with a renewable SQLite lease and cancellation."""
import json
import shutil
import sqlite3
import threading
import time
from uuid import uuid4

from utils.gemini_music import generate, MusicGenerationError
from core.music_manager import MusicJobCancelled
from utils.logger import get_logger

logger=get_logger(__name__)


class MusicWorker:
    def __init__(self,manager,settings,*,provider=generate):
        self.manager,self.settings,self.provider=manager,settings,provider
        self.owner=uuid4().hex
        self.stop_event=threading.Event()
        self.thread=None
        self.current_job=None
        self._owns_lease=threading.Event()
        self._lease_lost=threading.Event()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread=threading.Thread(target=self.run,name='music-generation-worker',daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)

    def lease(self):
        now=time.time()
        with self.manager.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM runtime WHERE id=1').fetchone()
            if row and row['owner']!=self.owner and now-row['heartbeat']<8:
                self._owns_lease.clear()
                return False
            db.execute('INSERT OR REPLACE INTO runtime VALUES(1,?,?)',(self.owner,now))
        self._owns_lease.set()
        self._lease_lost.clear()
        return True

    def _heartbeat(self,finished):
        while not finished.wait(1):
            if not self._owns_lease.is_set():
                continue
            try:
                with self.manager.connect() as db:
                    result=db.execute('UPDATE runtime SET heartbeat=? WHERE id=1 AND owner=?',(time.time(),self.owner))
                    if result.rowcount!=1:
                        self._owns_lease.clear()
                        self._lease_lost.set()
            except (OSError,sqlite3.Error):
                self._lease_lost.set()
                logger.warning('Music worker heartbeat unavailable; no paid request will be retried.')

    def _claim(self):
        with self.manager.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            runtime=db.execute('SELECT owner,heartbeat FROM runtime WHERE id=1').fetchone()
            if not runtime or runtime['owner']!=self.owner or time.time()-runtime['heartbeat']>=8:
                return None
            row=db.execute("SELECT * FROM jobs WHERE state='queued' AND cancel=0 ORDER BY created LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET state='running',updated=?,session_id=? WHERE id=?",(time.time(),self.owner,row['id']))
            return dict(row)

    def _finish(self,identifier,state,reason):
        with self.manager.connect() as db:
            db.execute("UPDATE jobs SET state=?,reason=?,updated=? WHERE id=? AND state!='completed'",(state,reason,time.time(),identifier))

    def run(self):
        acquired=False
        heartbeat_done=threading.Event()
        heartbeat=threading.Thread(target=self._heartbeat,args=(heartbeat_done,),daemon=True,name='music-worker-heartbeat')
        heartbeat.start()
        try:
            while not self.stop_event.is_set():
                if not self.lease():
                    acquired=False
                    self.stop_event.wait(1)
                    continue
                if not acquired:
                    self.manager.recover()
                    with self.manager.connect() as db:
                        db.execute("UPDATE jobs SET state='unknown_remote_result',reason='interrupted_previous_session',updated=? WHERE state IN ('running','validating')",(time.time(),))
                        db.execute('UPDATE jobs SET session_id=? WHERE notified=0',(self.owner,))
                    acquired=True
                row=self._claim()
                if not row:
                    self.stop_event.wait(.5)
                    continue
                identifier=row['id']
                self.current_job=identifier
                manager=self.manager
                worker=self
                class Signal:
                    last=0.
                    def wait(self,seconds):
                        deadline=time.monotonic()+seconds
                        while time.monotonic()<deadline:
                            if self.is_set():
                                return True
                            worker.stop_event.wait(min(.1,max(0,deadline-time.monotonic())))
                        return self.is_set()
                    def is_set(self):
                        if worker.stop_event.is_set() or worker._lease_lost.is_set():
                            return True
                        now=time.monotonic()
                        if now-self.last>.75:
                            self.last=now
                            if not worker.lease():
                                return True
                        with manager.connect() as db:
                            record=db.execute('SELECT cancel FROM jobs WHERE id=?',(identifier,)).fetchone()
                        return worker.stop_event.is_set() or not record or bool(record[0])
                signal=Signal()
                started=time.monotonic()
                try:
                    if signal.is_set():
                        self._finish(identifier,'cancelled','cancelled_before_request')
                        continue
                    settings=self.settings()
                    if not settings.get('music',{}).get('enabled',True):
                        raise MusicGenerationError('music_disabled')
                    path,metadata=self.provider(settings,json.loads(row['payload']),manager.root/'staging'/identifier,signal)
                    if signal.is_set():
                        self._finish(identifier,'cancelled','remote_charge_may_apply')
                        continue
                    with manager.connect() as db:
                        db.execute("UPDATE jobs SET state='validating',updated=? WHERE id=?",(time.time(),identifier))
                    manager.publish(path,json.loads(row['payload']),job_id=identifier,generation_started=started,**metadata)
                except MusicJobCancelled:
                    self._finish(identifier,'cancelled','remote_charge_may_apply')
                except MusicGenerationError as exc:
                    if self._lease_lost.is_set():
                        self._finish(identifier,'unknown_remote_result','worker_lease_lost')
                    elif signal.is_set():
                        self._finish(identifier,'cancelled','remote_charge_may_apply')
                    else:
                        self._finish(identifier,'unknown_remote_result' if exc.uncertain else 'failed',exc.reason)
                except Exception:
                    self._finish(identifier,'unknown_remote_result','validation_or_storage_failed')
                finally:
                    self.current_job=None
                    # Preserve uncertain artifacts for recovery. Published audio is
                    # already durable; remove only this worker's scoped staging.
                    if manager.job(identifier)['status'] in ('completed','cancelled','failed'):
                        staging=(manager.root/'staging'/identifier).resolve()
                        if staging.parent==(manager.root/'staging').resolve() and staging.name==identifier and staging.is_dir():
                            try:
                                shutil.rmtree(staging)
                            except OSError:
                                logger.warning('Music staging cleanup deferred; published tracks are preserved.')
        finally:
            heartbeat_done.set()
            heartbeat.join(timeout=2)
            self._owns_lease.clear()
            if acquired:
                with self.manager.connect() as db:
                    db.execute('DELETE FROM runtime WHERE owner=?',(self.owner,))

    def notifications(self):
        """Pending UI messages; acknowledge only after the UI inserts the message."""
        with self.manager.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute("SELECT id FROM jobs WHERE session_id=? AND notified=0 AND state IN ('completed','failed','cancelled','unknown_remote_result') ORDER BY created",(self.owner,)).fetchall()
        return [self.manager.job(r[0]) for r in rows]

    def acknowledge_notification(self,identifier):
        with self.manager.connect() as db:
            db.execute('UPDATE jobs SET notified=1 WHERE id=? AND session_id=?',(identifier,self.owner))
