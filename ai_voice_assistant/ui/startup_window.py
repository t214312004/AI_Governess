"""Nonfullscreen preparation window; all Tk work stays on the main thread."""
import queue
import threading
import customtkinter as ctk

from config import config
from ui.components import BG
from ui.startup import StartupView
from ui.fullscreen_host import FullscreenHost
from utils.logger import get_logger

logger = get_logger(__name__)


class StartupWindow(ctk.CTk):
    def __init__(self, assistant_factory):
        ctk.set_appearance_mode('light')
        super().__init__()
        self.title('愛管家')
        self.configure(fg_color=BG)
        width, height = min(1160, self.winfo_screenwidth()-64), min(800, self.winfo_screenheight()-120)
        self.geometry(f'{max(640,width)}x{max(480,height)}')
        self.minsize(640, 480)
        self.factory = assistant_factory
        self.events = queue.SimpleQueue()
        self.result = None
        self.preparing = False
        self.cancelled = False
        self.view = StartupView(self, config.snapshot(), self._prepare)
        self.view.pack(fill='both', expand=True)
        self.protocol('WM_DELETE_WINDOW', self._close_request)
        self.after(200, self._position)
        self.after(100, self._poll)

    def _position(self):
        self.update_idletasks()
        host = FullscreenHost(self.winfo_id())
        area, current = host.monitor_bounds(work_area=True), host.window_bounds()
        width, height = min(current.width, area.width-48), min(current.height, area.height-48)
        host._checked(host.api.SetWindowPos(host.hwnd, None,
            area.left+(area.width-width)//2, area.top+(area.height-height)//2,
            width, height, 0x0004 | 0x0010))

    def _prepare(self, session, draft):
        if self.preparing:
            return
        self.preparing = True
        self.view.set_preparing(True)
        self.view.status.configure(text='準備啟動…')
        previous = config.snapshot()
        def worker():
            assistant = None
            try:
                config.apply_snapshot(draft)
                assistant = self.factory()
                assistant.prepare_for_gui(status_callback=lambda text: self.events.put(('status', text)))
                self.events.put(('ready', (assistant, session)))
            except Exception:
                logger.exception('Startup preparation failed.')
                if assistant is not None:
                    try:
                        assistant.shutdown_prepared_resources()
                    except Exception:
                        logger.exception('Failed to release startup resources.')
                try:
                    config.apply_snapshot(previous)
                except Exception:
                    logger.exception('Failed to restore configuration after startup failure.')
                self.events.put(('error', '啟動失敗，請檢查設定與 backend 登入狀態；詳細原因見 logs。'))
        threading.Thread(target=worker, name='assistant-startup', daemon=True).start()

    def _poll(self):
        if self.cancelled and not self.preparing and not (
                self.view.query_thread and self.view.query_thread.is_alive()):
            self._destroy_owned()
            return
        while not self.events.empty():
            kind, value = self.events.get()
            if kind == 'status':
                self.view.status.configure(text=value)
            elif kind == 'ready':
                if self.cancelled:
                    # Cleanup may wait on backend processes; keep the Tk loop responsive.
                    threading.Thread(target=self._cancel_prepared, args=(value[0],), daemon=True).start()
                    continue
                self.result = value
                self._destroy_owned()
                return
            elif kind == 'closed' or (kind == 'error' and self.cancelled):
                self._destroy_owned()
                return
            elif kind == 'error':
                self.preparing = False
                self.view.status.configure(text=value)
                self.view.set_preparing(False)
        self.after(100, self._poll)

    def _cancel_prepared(self, assistant):
        try:
            assistant.shutdown_prepared_resources()
        finally:
            self.events.put(('closed', None))

    def _close_request(self):
        if self.preparing or (self.view.query_thread and self.view.query_thread.is_alive()):
            self.cancelled = True
            self.view.query_cancel.set()
            self.view.status.configure(text='正在結束啟動程序…')
        else:
            self._destroy_owned()

    def _destroy_owned(self):
        self.view.destroy()
        for job in self.tk.call('after', 'info'):
            self.tk.call('after', 'cancel', job)
        self.destroy()

    def prepare(self):
        self.mainloop()
        return self.result
