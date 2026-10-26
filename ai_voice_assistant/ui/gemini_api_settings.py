"""Startup-only Gemini API CLI maintenance and shared music model selection."""
from copy import deepcopy
import time

import customtkinter as ctk

from ui.components import FONT, MUTED, label, button
from ui.google_credentials import GoogleCredentialsEditor
from ui.settings_fields import SettingsField
from utils.gemini_api_cli import MUSIC_MODEL, install_cli, query_models, resolve_executable
from utils.startup_diagnostics import safe_error

OWNED_PATHS = {('gemini_api_cli', 'executable'), ('music', 'model')}


class GeminiApiSettings(ctk.CTkFrame):
    def __init__(self, parent, settings, controller, snapshot, state, save_key, key_changed):
        super().__init__(parent, fg_color='transparent')
        self.settings, self.controller, self.snapshot, self.state = settings, controller, snapshot, state
        self.dead, self.job, self.token = False, None, None
        self._updating_path = False
        if state.get('configured_executable') != settings['gemini_api_cli']['executable']:
            state.clear()
        label(self, '音樂模型套用到所有風格、純音樂與歌曲；目前統一使用 Lyria 3.5。',
              13, color=MUTED, anchor='w', wraplength=300).pack(fill='x', pady=(0, 8))
        self.model_field = SettingsField(self, ('music', 'model'), settings['music']['model'],
                                       title='所有音樂使用的模型', options=[MUSIC_MODEL], readonly=True)
        self.model_field.pack(fill='x', pady=5)
        self.path_field = SettingsField(self, ('gemini_api_cli', 'executable'),
            settings['gemini_api_cli']['executable'], title='Gemini API CLI 路徑（留白自動尋找）')
        self.path_field.pack(fill='x', pady=5)
        label(self, 'Google API key（與 Gemini 語音共用）', 13, anchor='w').pack(fill='x', pady=(10, 0))
        GoogleCredentialsEditor(self, settings, save_key, key_changed).pack(fill='x')
        self.update_button = button(self, '安裝／更新 CLI', lambda: self.start(update=True), height=36)
        self.update_button.pack(fill='x', pady=(12, 6))
        self.query_button = button(self, '查詢可用模型', self.start, height=36)
        self.query_button.pack(fill='x', pady=6)
        self.cancel_button = button(self, '取消 Gemini API 操作', self.cancel, height=32)
        self.cancel_button.pack(fill='x', pady=6)
        self.cancel_button.configure(state='disabled')
        try:
            path = resolve_executable(settings['gemini_api_cli']['executable'])
            initial = '已找到 gemini-api.exe；按「查詢可用模型」檢查連線。'
        except ValueError as exc:
            initial = str(exc)
        self.status = label(self, state.get('message', initial), 12, color=MUTED, anchor='w', wraplength=300)
        self.status.pack(fill='x', pady=8)
        self.models = ctk.CTkTextbox(self, height=150, font=(FONT, 12), wrap='word')
        self.models.pack(fill='x', pady=6)
        self.show_models(state.get('models', ()))
        label(self, '模型查詢只讀取清單。進入主畫面後按音樂圖示，即可開啟曲庫與創作；不計入 HTML 時間。',
              12, color=MUTED, anchor='w', wraplength=300).pack(fill='x', pady=6)
        self.path_field.variable.trace_add('write', lambda *_: self.invalidate_path())

    def apply_to(self, draft):
        draft['gemini_api_cli']['executable'] = self.path_field.parse().strip()
        draft['music']['model'] = self.model_field.parse()

    def show_models(self, models):
        self.models.configure(state='normal')
        self.models.delete('1.0', 'end')
        ordered = sorted(models, key=lambda name: (not name.startswith('lyria'), name))
        self.models.insert('1.0', '\n'.join(ordered) or '尚未查詢 Gemini API 模型。')
        self.models.configure(state='disabled')

    def start(self, *, update=False):
        if self.controller.busy:
            self.status.configure(text='上一筆 Gemini API 操作尚在結束，請稍候。')
            return
        draft = self.snapshot()
        if draft is None:
            return
        draft = deepcopy(draft)
        self.started_executable = draft['gemini_api_cli']['executable']
        def work(cancel, owner):
            try:
                deadline = time.monotonic() + (180 if update else 60)
                if update:
                    result = install_cli(cancel=cancel, deadline=deadline, progress=owner.progress)
                    return dict(result, operation='update')
                return dict(query_models(draft, cancel=cancel, deadline=deadline,
                                         progress=owner.progress), operation='models')
            except Exception as exc:
                raise ValueError(safe_error(exc, draft)) from None
        self.token = self.controller.start(work)
        self.update_button.configure(state='disabled')
        self.query_button.configure(state='disabled')
        self.cancel_button.configure(state='normal')
        self.status.configure(text='正在安裝／更新 CLI…' if update else '正在查詢 Gemini API 模型…')
        self.job = self.after(100, self.poll)

    def poll(self):
        self.job = None
        if self.dead:
            return
        while not self.controller.events.empty():
            token, status, result = self.controller.events.get()
            if token != self.token:
                continue
            if status == 'progress':
                self.status.configure(text=result['message'])
                continue
            if status == 'ok':
                if result['operation'] == 'update':
                    self._updating_path = True
                    try:
                        self.path_field.variable.set('')  # Prefer the verified managed release on future updates.
                    finally:
                        self._updating_path = False
                    self.settings['gemini_api_cli']['executable'] = ''
                    self.state.clear()
                    self.state['configured_executable'] = ''
                    message = f"Gemini API CLI {result['version']} 已就緒；可查詢模型。路徑與模型按「儲存設定」保存。"
                    self.show_models(())
                else:
                    names = result['models']
                    message = f"Gemini API CLI {result['version']}：取得 {len(names)} 個模型。"
                    message += ('已列出 lyria-3.5，所有音樂維持此設定。' if MUSIC_MODEL in names else
                                '清單未列出 lyria-3.5；保留指定模型，可用性需生成時確認。')
                    self.state['models'] = names
                    self.state['configured_executable'] = self.started_executable
                    self.show_models(names)
                self.state['message'] = message
                self.status.configure(text=message)
            else:
                self.status.configure(text='Gemini API 操作已取消。' if status == 'cancelled' else
                                      'Gemini API 操作失敗：'+str(result))
        if self.controller.busy:
            self.job = self.after(100, self.poll)
        else:
            self.update_button.configure(state='normal')
            self.query_button.configure(state='normal')
            self.cancel_button.configure(state='disabled')

    def invalidate_credentials(self):
        self.cancel()
        self.token = None  # Ignore results obtained with the previous credential.
        self.state.clear()
        self.show_models(())
        self.status.configure(text='Google key 已更新，請重新查詢 Gemini API 模型。')

    def invalidate_path(self):
        if self._updating_path:
            return
        self.cancel()
        self.token = None
        self.state.clear()
        self.show_models(())
        self.status.configure(text='CLI 路徑已變更，請重新查詢 Gemini API 模型。')

    def cancel(self):
        self.controller.cancel()

    def destroy(self):
        self.dead = True
        self.controller.cancel()
        if self.job is not None:
            self.after_cancel(self.job)
            self.job = None
        super().destroy()
