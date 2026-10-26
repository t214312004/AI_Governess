"""Startup-only settings editor. Edits a copy; never calls runtime setters."""
from copy import deepcopy
import json
import queue
import re
import threading
import time
from pathlib import Path
import customtkinter as ctk

from core.session_settings import SessionConfig, EFFORT_KEYS, assign, parse_field, validate_settings, session_snapshot
from llm.model_catalog import CliCatalog, ModelInfo
from ui.components import BG, PANEL, GREEN, SOFT, INK, MUTED, LINE, NAV, FONT, label, button, card, pill, divider, OwnedComboBox, icon_image
from ui.session_theme import identity_image
from ui.audio_settings import AudioSettingsEditor, OWNED_PATHS
from ui.audio_preview import AudioPreviewController
from ui.gemini_api_settings import GeminiApiSettings, OWNED_PATHS as GEMINI_CLI_PATHS
from ui.theme import CHROME, CHROME_SOFT, WARM_SOFT, BLUE_LINE, PRIMARY_HOVER, SCROLLBAR, SCROLLBAR_HOVER
from ui.settings_fields import SettingsField
from core.settings_schema import SettingsError, public_defaults
from utils.startup_diagnostics import app_path, local_readiness, safe_error, validate_local_selection

BACKENDS = ('codex_cli', 'claude_code', 'opencode_cli', 'grok_cli', 'antigravity_cli')
STEPS = ('AI 服務', '聲音與裝置', '互動與使用限制', '進階選項', '確認與啟動')
BACKEND_NAMES={'codex_cli':'Codex CLI','claude_code':'Claude Code','opencode_cli':'OpenCode CLI','grok_cli':'Grok CLI','antigravity_cli':'Antigravity ACP'}
COMMON_PATHS={('hot_listen','enabled'),('hot_listen','timeout_seconds'),('user_activity_prompt','enabled'),
    ('user_activity_prompt','text'),('heartbeat','enabled'),('heartbeat','interval_minutes'),
    ('whisper_audio_archive','enabled'),('whisper_audio_archive','write_transcript_sidecar'),('speaker_recognition','enabled')}
LABELS = json.loads(Path(__file__).with_name('field_labels.json').read_text(encoding='utf-8'))


def preferred_selection(backend, model, effort):
    """Preserve legacy Gemini variants when catalog separates model and effort."""
    if backend == 'antigravity_cli':
        variant = re.fullmatch(r'(gemini-.+)-(low|medium|high)', model)
        if variant:
            if effort and effort != variant[2]:
                return model, effort  # Require an explicit choice for conflicting settings.
            return variant[1], variant[2]
    return model, effort


class StartupStatus(ctk.CTkLabel):
    """Keep lengthy provider errors out of the fixed navigation row."""
    full_text=''

    def configure(self,require_redraw=False,**kwargs):
        if 'text' in kwargs:
            self.full_text=str(kwargs['text'])
            kwargs['text']=self.full_text[:165]+('…' if len(self.full_text)>165 else '')
        return super().configure(require_redraw=require_redraw,**kwargs)

def leaves(obj, path=()):
    if not isinstance(obj, dict):
        yield path, obj
        return
    for key, value in obj.items():
        if isinstance(value, dict):
            yield from leaves(value, (*path, key))
        else:
            yield (*path, key), value

class StartupView(ctk.CTkFrame):
    def __init__(self, root, defaults, on_start, catalog=None, save_google_key=None, on_save=None):
        super().__init__(root, fg_color=BG, corner_radius=0)
        self.root, self.on_start = root, on_start
        self.save_google_key = save_google_key
        self.on_save=on_save
        self.field_controls={}
        self.test_states={}
        self.selections={}
        self.managers=[]
        self.error_path=None
        self.error_step=None
        self.advanced_group='audio'
        self.advanced_search=''
        self.show_all=False
        self.show_inactive_audio=False
        self.audio_preview = AudioPreviewController()
        self.audio_editor = None
        self.gemini_cli_controller = AudioPreviewController()
        self.gemini_cli_state = {}
        self.gemini_cli_editor = None
        self.settings = deepcopy(defaults)
        self.defaults = deepcopy(defaults)
        self.catalog = catalog or CliCatalog(lambda: deepcopy(self.settings))
        self.query_thread = None
        self.query_cancel = threading.Event()
        self.query_results = queue.SimpleQueue()
        self.query_progress=queue.SimpleQueue()
        self.query_token = 0
        self.query_key = None
        self.query_deadline = 0
        self.querying = False
        self.preparing = False
        self._disabled_controls = []
        self.query_next_step = None
        self.destroyed = False
        self.poll_job = None
        self.step = 0
        self.ready = False
        self.models = ()
        backend = defaults['llm']['active_backend']
        if backend not in BACKENDS:
            backend=public_defaults()['llm']['active_backend']
            self.settings['llm']['active_backend']=backend
        self.backend = ctk.StringVar(value=backend)
        self.preferred_model, self.preferred_effort = self._preferred_selection(backend)
        self.model = ctk.StringVar(value=self.preferred_model)
        self.effort = ctk.StringVar(value=self.preferred_effort)
        self.update_cli = ctk.BooleanVar(value=False)
        self.backend_label=ctk.StringVar(value=BACKEND_NAMES.get(backend,backend))
        self.voice_in = ctk.StringVar(value='語音 + 文字' if defaults.get('interaction', {}).get('voice_input', True) else '固定文字')
        self.voice_out = ctk.StringVar(value='語音 + 文字' if defaults.get('interaction', {}).get('voice_output', True) else '固定文字')
        self.minutes = ctk.StringVar(value=str(defaults['whiteboard'].get('html_daily_minutes', 30)))
        self.font_size = ctk.StringVar(value=str(defaults['ui'].get('chat_font_size', 21)))
        self.editors = []
        self.grid_columnconfigure(1,weight=1)
        self.grid_rowconfigure(1,weight=1)
        self.grid_columnconfigure(2,weight=0,minsize=225)
        nav = ctk.CTkFrame(self,width=196,fg_color=CHROME,corner_radius=0)
        nav.grid(row=0,column=0,rowspan=3,sticky='nsew')
        nav.grid_propagate(False)
        identity=ctk.CTkFrame(nav,fg_color='transparent')
        identity.pack(fill='x',padx=22,pady=(32,34))
        mark=ctk.CTkFrame(identity,width=36,height=36,corner_radius=12,fg_color=CHROME_SOFT,
            border_width=1,border_color='#75605E')
        mark.pack(side='left',padx=(0,10));mark.pack_propagate(False)
        ctk.CTkLabel(mark,text='',image=identity_image(size=27)).place(relx=.5,rely=.5,anchor='center')
        label(identity,'愛管家',20,weight='bold',color='#FFF8EF').pack(side='left')
        self.nav_buttons=[]
        for i,text in enumerate(STEPS):
            b=button(nav,text,lambda i=i:self.navigate(i),anchor='w',width=164,height=46,
                image=icon_image(('backend','mic','board','settings','check')[i],size=20),
                compound='left',border_width=0,font=(FONT,14))
            b.pack(pady=5,padx=16)
            self.nav_buttons.append(b)
        top=ctk.CTkFrame(self,fg_color='transparent')
        top.grid(row=0,column=1,sticky='ew',padx=30,pady=(32,24))
        self.breadcrumb=label(top,'1 / 5',13,color='#8B6942',fg_color=WARM_SOFT,
            corner_radius=10,width=60,height=30)
        self.breadcrumb.pack(side='right')
        self.heading=label(top,'',27,weight='bold',anchor='w')
        self.heading.pack(side='left')
        self.content=ctk.CTkScrollableFrame(self,fg_color=BG,corner_radius=0,
            scrollbar_fg_color=BG,scrollbar_button_color=SCROLLBAR,scrollbar_button_hover_color=SCROLLBAR_HOVER)
        self.content.grid(row=1,column=1,sticky='nsew',padx=(22,15),pady=(0,8))
        footer=ctk.CTkFrame(self,fg_color=PANEL,corner_radius=0,height=80)
        footer.grid(row=2,column=1,columnspan=2,sticky='ew')
        divider(footer).place(relx=0,rely=0,relwidth=1)
        footer.grid_columnconfigure(0,weight=1)
        self.status=StartupStatus(footer,text='',font=(FONT,12),text_color=MUTED,anchor='w',wraplength=350,height=42)
        self.status.grid(row=0,column=0,sticky='ew',padx=18,pady=(8,2))
        self.fix_button=button(footer,'錯誤詳情',self.show_diagnostics,width=90,height=32)
        self.fix_button.grid(row=0,column=1,padx=(4,16),pady=6)
        actions=ctk.CTkFrame(footer,fg_color='transparent')
        actions.grid(row=1,column=0,columnspan=2,sticky='ew',padx=16,pady=(2,12))
        self.save_button=button(actions,'儲存設定',self.save_draft,width=100,height=38)
        self.save_button.pack(side='left')
        self.save_button.configure(state='normal' if on_save else 'disabled')
        self.next=button(actions,'下一步  →',self.advance,primary=True,width=110,height=38)
        self.next.pack(side='right',padx=(8,0))
        self.previous=button(actions,'上一步',lambda:self.navigate(self.step-1),width=78,height=38)
        self.previous.pack(side='right')
        self.summary=ctk.CTkFrame(self,fg_color=WARM_SOFT,corner_radius=0,width=225)
        self.summary.grid(row=0,column=2,rowspan=2,sticky='nsew',padx=(0,0))
        self.summary.grid_propagate(False)
        self._compact=False
        self.bind('<Configure>',self._resize_layout,add='+')
        self.render()

    def _resize_layout(self,event=None):
        if hasattr(self,'status'):
            available=max(180,round(self.winfo_width()/self._get_widget_scaling())-330)
            self.status.configure(wraplength=min(560,available))
        compact=self.winfo_width()/self._get_widget_scaling()<1040
        if compact==self._compact: return
        self._compact=compact
        if compact:
            self.summary.grid_remove()
            self.grid_columnconfigure(2,minsize=0)
        else:
            self.summary.grid()
            self.grid_columnconfigure(2,minsize=225)

    def section(self,title):
        panel=card(self.content)
        panel.pack(fill='x',padx=6,pady=(0,16))
        label(panel,title,16,weight='bold',anchor='w').pack(fill='x',padx=24,pady=(22,8))
        body=ctk.CTkFrame(panel,fg_color='transparent')
        body.pack(fill='both',expand=True,padx=24,pady=(0,24))
        return body

    def field(self,parent,title,variable,values,command=None):
        label(parent,title,13,color=MUTED,anchor='w').pack(fill='x',pady=(10,8))
        widget=OwnedComboBox(parent,variable=variable,values=values,command=command,
            state='readonly')
        widget.pack(fill='x')
        return widget

    def choice(self,parent,title,variable):
        body=self.section(title)
        body.grid_columnconfigure((0,1),weight=1)
        for i,value in enumerate(('語音 + 文字','固定文字')):
            frame=ctk.CTkFrame(body,fg_color=SOFT if variable.get()==value else NAV,
                border_color=BLUE_LINE if variable.get()==value else LINE,border_width=1,corner_radius=13)
            frame.grid(row=0,column=i,sticky='nsew',padx=(0,6) if i==0 else (6,0),pady=8)
            ctk.CTkRadioButton(frame,text=value,variable=variable,value=value,
                font=(FONT,15),text_color=INK,fg_color=GREEN,border_color='#B8A99C',
                hover_color=PRIMARY_HOVER,radiobutton_width=19,radiobutton_height=19,
                border_width_unchecked=2,border_width_checked=5,
                command=self._voice_mode_changed).pack(anchor='w',padx=19,pady=23)

    def render_summary(self):
        for child in self.summary.winfo_children(): child.destroy()
        label(self.summary,'本次設定',14,weight='bold',anchor='w').pack(fill='x',padx=24,pady=(38,21))
        values=[('Backend',self.backend.get().replace('_cli','').replace('_',' ').title()),
                ('Model',self.model.get() or '尚未選擇'),('輸入',self.voice_in.get()),
                ('輸出',self.voice_out.get()),('HTML 額度',self.minutes.get()+' 分鐘 / 日')]
        stt,tts,voice=self._audio_selection()
        values.extend([('語音辨識',stt),('語音輸出',tts+(' / '+voice if tts=='gemini' else ''))])
        for key,value in values:
            label(self.summary,key,11,color=MUTED,anchor='w').pack(fill='x',padx=24,pady=(7,2))
            label(self.summary,value,14,anchor='w',wraplength=180).pack(fill='x',padx=24,pady=(0,13))
        divider(self.summary).pack(fill='x',padx=24,pady=10)
        pill(self.summary,'Alt+F4 退出',color=MUTED,bg=PANEL).pack(anchor='w',padx=24,pady=10)

    def navigate(self,index):
        if self.preparing:
            return
        if self.querying:
            self.status.configure(text='正在檢查，請稍候')
            return
        if not self.collect():
            return
        self.audio_preview.cancel()
        self.step=max(0,min(4,index))
        self.render()

    def collect(self):
        try:
            try: minutes=int(self.minutes.get())
            except ValueError: raise SettingsError(('whiteboard','html_daily_minutes'),'請填 0–1440 的整數分鐘') from None
            if not 0<=minutes<=1440:
                raise SettingsError(('whiteboard','html_daily_minutes'),'請填 0–1440 的整數分鐘')
            candidate=deepcopy(self.settings)
            for path,variable,original in self.editors:
                field=self.field_controls.get(path)
                assign(candidate,path,field.parse() if field else parse_field(variable.get(),original,path))
            if self.audio_editor is not None:
                self.audio_editor.apply_to(candidate)
            if self.gemini_cli_editor is not None:
                self.gemini_cli_editor.apply_to(candidate)
            candidate['interaction'].update(voice_input=self.voice_in.get()!='固定文字',voice_output=self.voice_out.get()!='固定文字',update_cli=False)
            candidate['llm']['active_backend']=self.backend.get()
            candidate['whiteboard']['html_daily_minutes']=minutes
            try: candidate['ui']['chat_font_size']=int(self.font_size.get())
            except ValueError: raise SettingsError(('ui','chat_font_size'),'請選擇 16–32 px 的字級') from None
            if candidate['tts']['backend']=='bluemagpie': candidate['tts']['bluemagpie']['enabled']=True
            candidate=validate_settings(candidate,self.defaults)
        except (ValueError,TypeError) as exc:
            self.show_error(exc)
            return False
        self.settings=candidate
        self.error_path=None
        self.error_step=None
        return True

    def render(self):
        self.editors=[]
        self.field_controls={}
        self.audio_editor=None
        self.gemini_cli_editor=None
        for child in self.content.winfo_children(): child.destroy()
        self.heading.configure(text=STEPS[self.step])
        self.breadcrumb.configure(text=f'{self.step+1} / 5')
        for i,b in enumerate(self.nav_buttons):
            active=i==self.step
            b.configure(fg_color=WARM_SOFT if active else 'transparent',
                text_color=INK if active else '#DBC7BC',
                text_color_disabled='#A69C9B',
                image=icon_image(('backend','mic','board','settings','check')[i],
                    color=GREEN if active else '#C8AD8E',size=20),
                hover_color='#EADCCC' if active else CHROME_SOFT,
                font=(FONT,14,'bold' if active else 'normal'))
        self.previous.configure(state='normal' if self.step else 'disabled')
        self.next.configure(text='啟動  ↗' if self.step==4 else '下一步  →',
                            state='disabled' if self.querying else 'normal')
        self.render_summary()
        if self.step==0:
            antigravity = self.backend.get()=='antigravity_cli'
            body=self.section('AI 服務')
            self.field(body,'選擇 AI 服務',self.backend_label,list(BACKEND_NAMES.values()),self.change_backend)
            hint=('使用官方 agy-acp-server 與 Google AI Pro 個人訂閱；僅提供 Gemini 模型。請先安裝，再登入有 Pro 訂閱的 Google 帳號。'
                  if antigravity else '使用已安裝並登入的 CLI。先查詢可用模型；更新 CLI 是另外的選用操作。')
            label(body,hint,12,color=MUTED,wraplength=300,anchor='w').pack(fill='x',pady=10)
            try:
                executable=CliCatalog._executable(self.backend.get(),self.settings)
                installed=f'已找到 {"官方 ACP" if antigravity else "CLI"}：{Path(executable).name}；登入與連線狀態待查詢。'
            except ValueError:
                installed=('官方 ACP 尚未就緒；請按下方安裝／更新按鈕。' if antigravity else
                           '尚未找到 CLI；請先依指南安裝並登入，再回來查詢。')
            label(body,installed,12,color=MUTED,wraplength=300,anchor='w').pack(fill='x',pady=6)
            button(body,'安裝／登入與排除問題',self.open_setup_guide,height=34).pack(fill='x')
            body=self.section('模型與推理')
            fields=ctk.CTkFrame(body,fg_color='transparent')
            fields.pack(fill='x')
            fields.grid_columnconfigure(0,weight=3);fields.grid_columnconfigure(1,weight=2)
            left=ctk.CTkFrame(fields,fg_color='transparent');left.grid(row=0,column=0,sticky='ew',padx=(0,12))
            right=ctk.CTkFrame(fields,fg_color='transparent');right.grid(row=0,column=1,sticky='ew')
            self.model_menu=self.field(left,'模型',self.model,[m.id for m in self.models] or ['尚未查詢'],self.select_model)
            self.effort_menu=self.field(right,'推理強度',self.effort,['尚未查詢'])
            label(body,'推理強度越高通常需要較久；只提供所選模型回報的選項。',12,color=MUTED,wraplength=300,anchor='w').pack(fill='x',pady=8)
            if not self.ready:
                self.model.set(self.preferred_model or '尚未查詢');self.effort.set(self.preferred_effort or '—')
                self.model_menu.configure(state='disabled');self.effort_menu.configure(state='disabled')
            elif any(m.id == self.model.get() for m in self.models):
                self.select_model(self.model.get())
            else:
                self.model.set('請選擇模型');self.effort.set('—')
                self.effort_menu.configure(state='disabled')
            self.query_button=button(body,'查詢模型（不更新）',self.query,primary=True,height=40)
            self.query_button.pack(fill='x',pady=(12,0))
            self.query_button.configure(state='disabled' if self.querying else 'normal')
            self.update_button=button(body,'安裝／更新官方 ACP 並查詢模型' if antigravity else '更新 CLI 並查詢模型',lambda:self.query(update=True),height=36)
            self.update_button.pack(fill='x',pady=(8,0))
            self.update_button.configure(state='disabled' if self.querying else 'normal')
            self.auth_button=None
            if antigravity:
                self.auth_button=button(body,'登入 Google AI Pro 並查詢模型',lambda:self.query(authenticate=True),height=36)
                self.auth_button.pack(fill='x',pady=(8,0))
                self.auth_button.configure(state='disabled' if self.querying else 'normal')
                label(body,'登入會開啟 Google 官方瀏覽器流程；不使用 API key 或 Cloud 計費。首次準備可能需要約半分鐘，登入另需等待你完成操作。',12,color=MUTED,wraplength=300,anchor='w').pack(fill='x',pady=8)
            self.cancel_button=button(body,'取消查詢',self.cancel_query,height=34)
            self.cancel_button.pack(fill='x',pady=(8,0))
            self.cancel_button.configure(state='normal' if self.querying else 'disabled')
            body=self.section('Gemini API CLI 與音樂')
            self.gemini_cli_editor=GeminiApiSettings(body,self.settings,self.gemini_cli_controller,
                self._audio_snapshot,self.gemini_cli_state,self.save_google_key,self._google_key_changed)
            self.gemini_cli_editor.pack(fill='x')
        elif self.step==1:
            self.choice(self.content,'輸入',self.voice_in)
            self.choice(self.content,'輸出',self.voice_out)
            if self.voice_in.get()!='固定文字' or self.voice_out.get()!='固定文字' or self.show_inactive_audio:
                body=self.section('語音服務與測試')
                self.audio_editor=AudioSettingsEditor(body,self.settings,self.audio_preview,
                    self._audio_snapshot,self.render_summary,self.save_google_key,self._google_key_changed,self.test_states,self.show_inactive_audio)
                self.audio_editor.pack(fill='x')
            else:
                body=self.section('本次使用純文字')
                label(body,'不需要麥克風、語音服務或金鑰；仍可保留先前設定。',13,color=MUTED,wraplength=300,anchor='w').pack(fill='x')
                button(body,'查看暫未使用的語音設定',self.show_audio_settings).pack(fill='x',pady=10)
        elif self.step==2:
            body=self.section('HTML 每日額度')
            row=ctk.CTkFrame(body,fg_color='transparent');row.pack(fill='x',pady=(12,18))
            ctk.CTkEntry(row,textvariable=self.minutes,width=130,height=62,font=(FONT,30),
                fg_color=NAV,text_color=INK,border_color=LINE,border_width=1,
                corner_radius=12,justify='center').pack(side='left')
            label(row,'分鐘 / 日',15,color=MUTED).pack(side='left',padx=16)
            divider(body).pack(fill='x',pady=4)
            for text in ['0 表示停用 HTML；可填 0–1440 分鐘','隱藏、關閉時暫停','Asia/Taipei 每日 00:00 重置','Markdown、圖片與音樂播放器不限時']:
                label(body,'✓  '+text,14,anchor='w').pack(fill='x',pady=(12,0))
            body=self.section('閱讀與字級')
            self.field(body,'對話字級（16–32 px）',self.font_size,[str(i) for i in range(16,33)],self.update_font_preview)
            try: preview_size=max(16,min(32,int(self.font_size.get())))
            except ValueError: preview_size=21
            self.font_preview=label(body,'愛管家：這是對話字級預覽。',preview_size,anchor='w',wraplength=300)
            self.font_preview.pack(fill='x',pady=15)
            body=self.section('互動與保存')
            for path in sorted(COMMON_PATHS):
                value=self.settings[path[0]][path[1]]
                self.add_setting(body,path,value)
            body=self.section('喚醒詞、家人聲紋與角色')
            button(body,'編輯喚醒詞',lambda:self.open_manager('keywords')).pack(fill='x',pady=5)
            button(body,'錄音測試喚醒詞',self.test_wake_word).pack(fill='x',pady=5)
            button(body,'新增家人／錄製聲紋',lambda:self.open_manager('profiles')).pack(fill='x',pady=5)
            button(body,'編輯角色指令 AGENTS.md',lambda:self.open_manager('AGENTS.md')).pack(fill='x',pady=5)
            button(body,'編輯私人記憶 MEMORY.md',lambda:self.open_manager('MEMORY.md')).pack(fill='x',pady=5)
        elif self.step==3:
            groups=[g for g in self.settings if self.advanced_paths(g)]
            body=self.section('設定分類')
            selected=self.advanced_group if self.advanced_group in groups else groups[0]
            self.group=ctk.StringVar(value=LABELS.get(selected,selected))
            self.current_group=selected
            self.search=ctk.StringVar(value=self.advanced_search)
            ctk.CTkEntry(body,textvariable=self.search,placeholder_text='搜尋欄位名稱／識別字',height=40).pack(fill='x',pady=6)
            button(body,'搜尋此分類',lambda:self.render_group(self.current_group)).pack(fill='x',pady=4)
            button(body,'搜尋全部分類',lambda:self.render_group('__search__')).pack(fill='x',pady=4)
            self.all_var=ctk.BooleanVar(value=self.show_all)
            ctk.CTkCheckBox(body,text='包含其他服務與基本設定欄位',variable=self.all_var,command=self.toggle_all).pack(anchor='w',pady=10)
            self.field(body,'分類',self.group,[LABELS.get(g,g) for g in groups],
                lambda name:self.render_group(groups[[LABELS.get(g,g) for g in groups].index(name)]))
            self.editor_frame=ctk.CTkFrame(body,fg_color='transparent')
            self.editor_frame.pack(fill='both',expand=True,pady=(15,0))
            button(body,'還原此分類預設值',lambda:self.after(150,self.restore_group)).pack(fill='x',pady=8)
            self.render_group(selected,collect=False)
        else:
            body=self.section('啟動確認')
            rows=[('AI 服務',BACKEND_NAMES[self.backend.get()]),('模型',self.model.get() if self.ready else '尚未查詢'),
                  ('推理強度',self.effort.get() if self.ready else '—'),('輸入',self.voice_in.get()),
                  ('輸出',self.voice_out.get()),('HTML',f'{self.minutes.get()} 分鐘 / 日'),
                  ('音樂模型',self.settings['music']['model']+'（所有風格）'),
                  ('對話字級',self.font_size.get()+' px')]
            stt,tts,voice=self._audio_selection()
            stt_detail=self.settings['whisper']['model_size']+' / '+self.settings['whisper']['device'] if stt=='local' else self.settings['whisper'][stt]['model']
            tts_detail=self.settings['tts']['voice']+' / '+self.settings['tts']['rate'] if tts=='edge' else self.settings['tts']['gemini']['model']+' / '+voice if tts=='gemini' else '選用即啟用 / '+self.settings['tts']['bluemagpie']['device']
            rows.extend([('語音辨識',stt+' / '+stt_detail if self.voice_in.get()!='固定文字' else '本次不使用'),
                ('語音輸出',tts+' / '+tts_detail if self.voice_out.get()!='固定文字' else '本次不使用')])
            for kind,title in (('input','麥克風'),('output','播放裝置')):
                selection=self.settings['audio'].get(kind+'_device')
                rows.append((title,selection['name']+' / '+selection['hostapi'] if selection else 'Windows 預設裝置'))
            for i,(key,value) in enumerate(rows):
                line=ctk.CTkFrame(body,fg_color='transparent')
                line.pack(fill='x',pady=7)
                label(line,key,13,color=MUTED,anchor='w').pack(fill='x',pady=2)
                label(line,value,14,weight='bold',anchor='w',wraplength=300).pack(fill='x')
                if i<len(rows)-1: divider(body).pack(fill='x')
            pill(body,'模型已查詢' if self.ready else '模型尚未查詢').pack(anchor='w',pady=(20,0))
            checks=[('裝置格式',self.test_states.get('devices','未檢查')),('音訊辨識',self.test_states.get('stt','未測試')),
                ('麥克風錄音',self.test_states.get('microphone_stt','未測試')),
                ('語音試聽',self.test_states.get('tts','未測試')),('喚醒詞錄音',self.test_states.get('wake','未測試'))]
            checks.extend(local_readiness(self.settings))
            import os
            for provider,values in (('Google',self.settings['gemini']),('Groq',self.settings['whisper']['groq'])):
                used=(provider=='Google' and (self.settings['interaction']['voice_input'] and stt=='gemini' or self.settings['interaction']['voice_output'] and tts=='gemini') or
                    provider=='Groq' and self.settings['interaction']['voice_input'] and stt=='groq')
                if not used:
                    checks.append((provider,'本次不使用'))
                    continue
                source='本機 key 已設定' if values.get('api_key') else '環境變數已設定' if os.environ.get(values.get('api_key_env','')) else '尚未設定 key'
                checks.append((provider,source+'；連線'+('已驗證' if provider=='Google' and self.test_states.get('catalog')=='通過' else '未驗證')))
            for key,value in checks:
                label(body,key+'：'+value,12,color=MUTED,anchor='w',wraplength=300).pack(fill='x',pady=5)
            label(body,'未測試不代表故障；啟動仍會執行必要的環境與連線檢查。',12,color=MUTED,anchor='w',wraplength=300).pack(fill='x',pady=10)
        self.reset_scroll()
        self.enable_keyboard()

    def advanced_paths(self,group,include_all=False):
        if group=='__search__':
            return [item for name in self.settings for item in self.advanced_paths(name,include_all=True)]
        result=[]
        for path,value in leaves(self.settings[group],(group,)):
            if path in GEMINI_CLI_PATHS and not include_all:
                continue
            if path in (('interaction','voice_input'),('interaction','voice_output'),('interaction','update_cli'),
                ('whiteboard','html_daily_minutes'),('ui','chat_font_size'),('audio','input_device'),('audio','output_device'),
                ('tts','bluemagpie','enabled'),('gemini','api_key')): continue
            if path[-1] in ('fullscreen_exit_shortcuts','fullscreen_enter_shortcuts'): continue
            if path[0]=='llm' and path[-1] in ('active_backend','model','reasoning_effort','effort'): continue
            if not (self.show_all or include_all):
                if path in OWNED_PATHS or path in COMMON_PATHS: continue
                if path[0]=='llm' and len(path)>2 and path[1] in BACKENDS and path[1]!=self.backend.get(): continue
                if path[0]=='whisper':
                    stt=self.settings['whisper']['backend']
                    if len(path)>2 and path[1] in ('groq','gemini') and path[1]!=stt: continue
                if path[0]=='tts' and len(path)>2 and path[1] in ('gemini','bluemagpie') and path[1]!=self.settings['tts']['backend']: continue
            result.append((path,value))
        return result

    def add_setting(self,parent,path,value):
        title=' / '.join(LABELS.get(part,part) for part in path)
        field=SettingsField(parent,path,value,title,changed=self.clear_test_states)
        field.pack(fill='x',pady=(0,5))
        self.field_controls[path]=field
        self.editors.append((path,field.variable,value))
        return field

    def render_group(self,group,*,collect=True):
        if collect and not self.collect():
            self.group.set(LABELS.get(self.current_group,self.current_group))
            return
        self.current_group=group
        self.group.set('全部分類搜尋結果' if group=='__search__' else LABELS.get(group,group))
        self.advanced_group=group
        self.advanced_search=self.search.get() if hasattr(self,'search') else ''
        self.editors=[]
        self.field_controls={}
        for child in self.editor_frame.winfo_children(): child.destroy()
        query=self.advanced_search.strip().casefold()
        for path,value in self.advanced_paths(group):
            terms=' '.join((*path,*(LABELS.get(p,p) for p in path))).casefold()
            if query and query not in terms: continue
            self.add_setting(self.editor_frame,path,value)
        if group=='__search__':
            links=[(('ui','chat_font_size'),'對話字級',2),(('whiteboard','html_daily_minutes'),'HTML 每日額度',2),
                (('interaction','voice_input'),'輸入與輸出方式／麥克風／播放裝置',1),(('llm','model'),'AI 服務／模型／推理強度',0)]
            for path,title,page in links:
                terms=(' '.join(path)+' '+title).casefold()
                if query and query in terms:
                    button(self.editor_frame,'前往：'+title,lambda page=page:self.after(150,lambda:self.navigate(page))).pack(fill='x',pady=6)
        if not self.editors:
            label(self.editor_frame,'沒有符合的欄位；可清除搜尋或勾選「包含其他服務」。',13,color=MUTED,wraplength=300,anchor='w').pack(fill='x',pady=12)
        self.reset_scroll()
        self.enable_keyboard()

    def toggle_all(self):
        if not self.collect():
            self.all_var.set(self.show_all)
            return
        self.show_all=self.all_var.get()
        self.after(150,self.render)

    def restore_group(self):
        if self.current_group=='__search__':
            self.status.configure(text='請先選擇一個分類再還原預設值。')
            return
        defaults=public_defaults().get(self.current_group,{})
        # Restore visible fields only, preserving custom keys and other services.
        for path,_ in self.advanced_paths(self.current_group):
            value=defaults
            for key in path[1:]:
                if not isinstance(value,dict) or key not in value: break
                value=value[key]
            else: assign(self.settings,path,deepcopy(value))
        self.clear_test_states()
        self.render_group(self.current_group,collect=False)
        self.status.configure(text='此分類已還原；按儲存設定或啟動後生效。')

    def reset_scroll(self):
        def reset():
            if not self.destroyed:
                self.update_idletasks()
                self.content._parent_canvas.yview_moveto(0)
        self.after_idle(reset)

    def clear_test_states(self):
        self.test_states.clear()

    def enable_keyboard(self):
        def visit(owner):
            if isinstance(owner,ctk.CTkButton):
                owner._canvas.configure(takefocus=1)
                owner._canvas.bind('<Return>',lambda event,w=owner:w.invoke())
                owner._canvas.bind('<space>',lambda event,w=owner:w.invoke())
            elif isinstance(owner,(ctk.CTkSwitch,ctk.CTkCheckBox,ctk.CTkRadioButton)):
                owner._canvas.configure(takefocus=1)
                action=owner.invoke if isinstance(owner,ctk.CTkRadioButton) else owner.toggle
                owner._canvas.bind('<space>',lambda event,action=action:action())
            focus_widget=getattr(owner,'_entry',None) or getattr(owner,'_textbox',None)
            if focus_widget is not None:
                focus_widget.bind('<FocusIn>',lambda event,w=owner:self.reveal_focused(w),add='+')
            for child in owner.winfo_children(): visit(child)
        visit(self)

    def reveal_focused(self,widget):
        if not widget.winfo_ismapped(): return
        canvas=self.content._parent_canvas
        y=widget.winfo_rooty()-canvas.winfo_rooty()
        if y<0 or y+widget.winfo_height()>canvas.winfo_height():
            top=widget.winfo_rooty()-self.content.winfo_rooty()
            canvas.yview_moveto(max(0,top-12)/max(1,self.content.winfo_height()))

    def show_error(self,exc):
        self.error_path=getattr(exc,'path',None)
        message=safe_error(exc,self.settings)
        self.error_step=1 if any(word in message for word in ('Google','Groq','BlueMagpie','聲音與裝置')) else None
        self.status.configure(text='請檢查設定：'+message[:170])
        self.last_error=message
        if self.error_path:
            field=self.field_controls.get(self.error_path)
            if field is None and self.audio_editor is not None: field=self.audio_editor.field_controls.get(self.error_path)
            if field is not None:
                field.show_error(getattr(exc,'message',message))
                self.focus_setting(field)

    def focus_setting(self,field):
        def focus():
            if not field.winfo_exists(): return
            self.update_idletasks()
            canvas=self.content._parent_canvas
            top=field.winfo_rooty()-self.content.winfo_rooty()
            canvas.yview_moveto(max(0,top-15)/max(1,self.content.winfo_height()))
            field.focus_field()
        self.after_idle(focus)

    def show_diagnostics(self):
        from tkinter import messagebox
        message=self.status.full_text or getattr(self,'last_error',None) or '目前沒有錯誤。'
        if self.error_path and messagebox.askyesno('設定需要修正',message+'\n\n前往對應設定欄位？',parent=self.root):
            # Keep the invalid draft visible; navigation must not discard its raw input.
            field=self.field_controls.get(self.error_path)
            if field is None and self.audio_editor is not None: field=self.audio_editor.field_controls.get(self.error_path)
            if field and field.winfo_exists():
                self.focus_setting(field)
                return
            self.step=3
            if self.error_path in (('ui','chat_font_size'),('whiteboard','html_daily_minutes')):
                self.step=2
            elif self.error_path in (('audio','input_device'),('audio','output_device'),('gemini','api_key')):
                self.step=1
            self.show_all=True
            self.advanced_search=''
            self.advanced_group=self.error_path[0]
            self.render()
            if self.error_path in self.field_controls: self.focus_setting(self.field_controls[self.error_path])
        elif not self.error_path and self.error_step is not None:
            if messagebox.askyesno('啟動診斷',message+'\n\n返回相關設定？',parent=self.root):
                self.step=self.error_step
                self.render()
        elif not self.error_path:
            messagebox.showinfo('啟動診斷',message,parent=self.root)

    def save_draft(self):
        if self.preparing or not self.collect() or self.on_save is None: return
        try:
            draft=self.draft_snapshot()
            self.on_save(draft)
            self.status.configure(text='設定已儲存至本機；可稍後再查詢模型與啟動。')
        except Exception as exc: self.show_error(exc)

    def draft_snapshot(self):
        draft=deepcopy(self.settings)
        for backend,(model,effort) in self.selections.items():
            draft['llm'][backend]['model']=model
            draft['llm'][backend][EFFORT_KEYS.get(backend,'reasoning_effort')]=effort
        if self.ready and any(m.id == self.model.get() for m in self.models):
            draft['llm'][self.backend.get()]['model']=self.model.get()
            draft['llm'][self.backend.get()][EFFORT_KEYS.get(self.backend.get(),'reasoning_effort')]=self.effort.get()
        draft['ui']['fullscreen_exit_shortcuts']=['ALT+F4']
        draft['ui']['fullscreen_enter_shortcuts']=[]
        return draft

    def _preferred_selection(self, backend):
        options = self.settings['llm'][backend]
        model, effort = self.selections.get(backend, (
            options.get('model', ''), options.get(EFFORT_KEYS.get(backend, 'reasoning_effort'), '')))
        return preferred_selection(backend, model, effort)

    def change_backend(self,name):
        if not self.collect():
            self.backend_label.set(BACKEND_NAMES[self.backend.get()])
            return
        if self.ready and any(m.id == self.model.get() for m in self.models):
            self.selections[self.backend.get()]=(self.model.get(),self.effort.get())
        self.backend.set(next(key for key,value in BACKEND_NAMES.items() if value==name))
        selected=self.backend.get()
        self.preferred_model,self.preferred_effort=self._preferred_selection(selected)
        self.invalidate()

    def open_setup_guide(self):
        from ui.setup_managers import show_guide
        urls={'codex_cli':'https://learn.chatgpt.com/docs/codex/cli','claude_code':'https://code.claude.com/docs/en/setup',
            'opencode_cli':'https://opencode.ai/docs/','grok_cli':'https://docs.x.ai/build/overview',
            'antigravity_cli':'https://antigravity.google/docs/install/'}
        self.managers.append(show_guide(self,Path(__file__).resolve().parents[2]/'docs'/'startup_setup_guide.md',
            [('開啟 '+BACKEND_NAMES[self.backend.get()]+' 官方說明',urls[self.backend.get()])]))

    def show_audio_settings(self):
        self.show_inactive_audio=True
        self.after(150,self.render)

    def update_font_preview(self,*args):
        self.font_preview.configure(font=(FONT,int(self.font_size.get())))
        self.render_summary()

    def open_manager(self,kind):
        if not self.collect(): return
        if self.audio_preview.busy:
            self.audio_preview.cancel()
            self.status.configure(text='正在停止語音測試，請稍候再開啟。')
            return
        from ui.setup_managers import LocalTextEditor, VoiceProfilesEditor, validate_keywords
        if kind=='profiles': dialog=VoiceProfilesEditor(self,self.settings)
        elif kind=='keywords':
            tokens=app_path(self.settings['wake_word']['model_dir'])/'tokens.txt'
            dialog=LocalTextEditor(self,'編輯喚醒詞',app_path(self.settings['wake_word']['keywords_file']),validator=lambda text:validate_keywords(text,tokens))
        else:
            folder=app_path(self.settings['llm'][self.backend.get()]['project_dir'])
            dialog=LocalTextEditor(self,'角色與私人記憶',folder/kind)
        self.managers.append(dialog)
        dialog.grab_set()

    @property
    def preview_busy(self):
        return self.audio_preview.busy or self.gemini_cli_controller.busy or any(manager.winfo_exists() and hasattr(manager,'controller') and manager.controller.busy for manager in self.managers)

    def cancel_previews(self):
        self.audio_preview.cancel()
        self.gemini_cli_controller.cancel()
        for manager in self.managers:
            if manager.winfo_exists() and hasattr(manager,'controller'): manager.controller.cancel()

    def test_wake_word(self):
        if not self.collect() or self.audio_preview.busy: return
        from ui.audio_preview import record_audio
        from core.wake_word import WakeWordDetector
        import asyncio
        import numpy as np
        draft=deepcopy(self.settings)
        def work(cancel,owner):
            detector=WakeWordDetector(str(app_path(draft['wake_word']['keywords_file'])),str(app_path(draft['wake_word']['model_dir'])))
            if detector.keyword_spotter is None: raise ValueError('喚醒模型／詞檔未就緒，請在進階設定確認路徑。')
            audio=record_audio(draft,cancel,owner)
            pcm=np.clip(audio*32768,-32768,32767).astype(np.int16)
            detected=[]
            for offset in range(0,len(pcm),512):
                if cancel.is_set(): raise asyncio.CancelledError
                result=detector.detect(pcm[offset:offset+512],draft['audio']['input_sample_rate'])
                if result: detected.append(result)
            return {'message':'偵測到：'+'、'.join(detected) if detected else '未偵測到喚醒詞；請確認發音與模型。','detected':bool(detected)}
        self.wake_token=self.audio_preview.start(work)
        self.after(100,self.poll_wake)

    def poll_wake(self):
        if self.destroyed: return
        while not self.audio_preview.events.empty():
            token,status,result=self.audio_preview.events.get()
            if token!=self.wake_token: continue
            if status in ('ok','progress'):
                self.status.configure(text=result['message'])
                if status=='ok': self.test_states['wake']='通過' if result.get('detected') else '未通過'
            else: self.status.configure(text='已停止。' if status=='cancelled' else str(result))
        if self.audio_preview.busy: self.after(100,self.poll_wake)

    def _google_key_changed(self,value):
        self.audio_preview.cancel()
        self.gemini_cli_controller.cancel()
        self.gemini_cli_state.clear()
        if self.gemini_cli_editor is not None:
            self.gemini_cli_editor.invalidate_credentials()
        self.clear_test_states()
        self.settings.setdefault('gemini',{})['api_key']=value
        self.defaults.setdefault('gemini',{})['api_key']=value

    def _audio_selection(self):
        if self.audio_editor is not None:
            return self.audio_editor.summary_values()
        return (self.settings['whisper']['backend'],self.settings['tts']['backend'],
            self.settings['tts'].get('gemini',{}).get('voice',''))

    def _audio_snapshot(self):
        return deepcopy(self.settings) if self.collect() else None

    def _voice_mode_changed(self):
        if self.collect():
            self.clear_test_states()
            self.after(150,self.render)
        else:
            self.voice_in.set('語音 + 文字' if self.settings['interaction']['voice_input'] else '固定文字')
            self.voice_out.set('語音 + 文字' if self.settings['interaction']['voice_output'] else '固定文字')

    def invalidate(self,*args):
        if self.preparing:
            return
        self.query_token+=1
        self.query_cancel.set()
        self.querying=False
        self.query_next_step=None
        self.ready=False
        self.models=()
        self.model.set('')
        self.effort.set('')
        self.render()

    def query(self,*,advance_after=False,update=False,authenticate=False):
        if self.preparing:
            return
        if self.querying:
            self.status.configure(text='正在檢查，請稍候')
            return
        if self.query_thread and self.query_thread.is_alive():
            self.status.configure(text='上一筆查詢尚未結束，請稍候')
            return
        self.ready=False
        self.update_cli.set(bool(update))
        self.models=()
        backend=self.backend.get()
        self.preferred_model,self.preferred_effort=self._preferred_selection(backend)
        self.querying=True
        self.query_next_step=1 if advance_after else None
        # Keep the clicked button alive until its CTk click animation finishes.
        # Rebuilding the page here would destroy that pending Tcl command.
        self.model.set('尚未查詢');self.effort.set('—')
        self.model_menu.configure(state='disabled')
        self.effort_menu.configure(state='disabled')
        self.query_button.configure(state='disabled')
        self.update_button.configure(state='disabled')
        if getattr(self,'auth_button',None) is not None:
            self.auth_button.configure(state='disabled')
        self.cancel_button.configure(state='normal')
        self.next.configure(state='disabled')
        self.render_summary()
        self.status.configure(text='等待 Google 官方登入；請選擇 Google AI Pro 帳號' if authenticate else
                              '更新與查詢中' if self.update_cli.get() else '查詢中')
        self.query_token+=1
        token=self.query_token
        key=(self.backend.get(),self.update_cli.get())
        self.query_key=key
        self.query_cancel=threading.Event()
        cancel=self.query_cancel
        timeout=480 if authenticate else 300 if update and backend=='antigravity_cli' else 180
        self.query_deadline=time.monotonic()+timeout
        def work():
            try:
                options={'cancel':cancel,'timeout':timeout}
                if isinstance(self.catalog,CliCatalog):
                    options['progress']=lambda text:self.query_progress.put((token,text))
                    options['authenticate']=authenticate
                models=self.catalog.query(*key,**options)
                result=(models,None)
            except Exception as exc:
                result=(None,safe_error(exc,self.settings))
            self.query_results.put((token,key,result))
        self.query_thread=threading.Thread(target=work,daemon=True,name='cli-model-catalog')
        self.query_thread.start()
        if not self.poll_job:
            self.poll_job=self.after(100,self.poll_query)

    def poll_query(self):
        self.poll_job=None
        if self.destroyed: return
        while not self.query_progress.empty():
            token,message=self.query_progress.get()
            if token==self.query_token: self.status.configure(text=message)
        while not self.query_results.empty():
            token,key,(models,error)=self.query_results.get()
            if token!=self.query_token or key!=(self.backend.get(),self.update_cli.get()): continue
            self.querying=False
            try:
                if error: raise ValueError(error)
                if not isinstance(models,tuple) or not models or len(models)>500 or any(not isinstance(m,ModelInfo) for m in models):
                    raise ValueError('模型清單格式無效')
                if len({m.id for m in models})!=len(models): raise ValueError('模型識別字重複')
                if key == ('antigravity_cli', True) and isinstance(self.catalog, CliCatalog):
                    # Successful update/catalog selected the managed release.
                    # Save that selection with the user's normal startup draft.
                    self.settings['llm']['antigravity_cli']['executable']=''
                self.models=models
                selected=next((m for m in models if m.id==self.preferred_model),None)
                choice_required = (self.backend.get() == 'antigravity_cli' and
                    bool(self.preferred_model) and (selected is None or
                    bool(self.preferred_effort) and self.preferred_effort not in selected.efforts))
                if choice_required:
                    self.model.set('請選擇模型');self.effort.set('—')
                    self.query_next_step=None
                else:
                    selected=selected or models[0]
                    self.model.set(selected.id)
                    self.effort.set(self.preferred_effort if self.preferred_effort in selected.efforts else selected.efforts[0] if selected.efforts else '')
                self.ready=True
                self.status.configure(text='原模型或推理強度已不適用於官方 ACP；請從清單重新選擇。' if choice_required else '模型清單已更新')
            except ValueError as exc:
                self.error_step=0
                self.status.configure(text=f'查詢失敗：{exc}')
            if self.ready and self.query_next_step is not None:
                self.step=self.query_next_step
            self.query_next_step=None
            self.render()
        if self.querying and time.monotonic()>=self.query_deadline:
            self.invalidate()
            self.status.configure(text='查詢逾時，已取消')
        if self.querying or (self.query_thread and self.query_thread.is_alive()):
            self.poll_job=self.after(100,self.poll_query)

    def cancel_query(self):
        self.query_cancel.set()
        self.query_token+=1
        self.querying=False
        self.ready=False
        self.query_next_step=None
        self.status.configure(text='已取消查詢；正在清理本次子程序，可稍後重新查詢。')
        self.after(150,self.render)

    def select_model(self,value):
        model=next((m for m in self.models if m.id==value),None)
        if model is None:
            self.invalidate()
            self.status.configure(text='模型選擇無效，請重新查詢')
            return
        self.effort_menu.configure(values=list(model.efforts) or ['不支援'],state='readonly' if model.efforts else 'disabled')
        if self.effort.get() not in model.efforts:
            self.effort.set(model.efforts[0] if model.efforts else '')
        self.render_summary()

    def advance(self):
        if self.preparing:
            return
        if self.querying:
            self.status.configure(text='正在檢查，請稍候')
            return
        if self.step==0 and (not self.ready or self.query_key!=(self.backend.get(),self.update_cli.get())):
            if self.collect(): self.query(advance_after=True)
            return
        if self.step==0 and not any(m.id == self.model.get() for m in self.models):
            self.status.configure(text='請從清單選擇可用模型與推理強度，再繼續。')
            return
        if self.step!=4:
            self.navigate(self.step+1)
            return
        if not self.collect(): return
        if self.preview_busy:
            self.cancel_previews()
            self.status.configure(text='正在停止語音測試，請稍候…')
            self.after(100,self.advance)
            return
        if not self.ready:
            self.step=0;self.render();self.status.configure(text='請先查詢模型');return
        try:
            selected=next((m for m in self.models if m.id==self.model.get()),None)
            if selected is None or self.backend.get() not in BACKENDS or self.query_key!=(self.backend.get(),self.update_cli.get()):
                raise ValueError('請重新查詢模型')
            if self.effort.get() not in (selected.efforts or ('',)):
                raise ValueError('Effort 不屬於所選模型')
            cfg=SessionConfig(self.backend.get(),self.model.get(),self.effort.get(),
                self.voice_in.get()!='固定文字',self.voice_out.get()!='固定文字',
                int(self.minutes.get()),int(self.font_size.get()))
            if (cfg.voice_input and self.settings['whisper']['backend']=='gemini' or
                    cfg.voice_output and self.settings['tts']['backend']=='gemini'):
                from utils.gemini_audio import resolve_api_key, GeminiAPIError
                try:
                    resolve_api_key(self.settings['gemini']['api_key'],self.settings['gemini']['api_key_env'])
                except GeminiAPIError:
                    raise ValueError('請在「聲音與裝置」設定 Google API key') from None
            snapshot=session_snapshot(self.draft_snapshot(),cfg)
            snapshot['interaction']['update_cli']=False
            validate_local_selection(snapshot)
            self.on_start(cfg,snapshot)
        except ValueError as exc:
            self.show_error(exc)

    def set_preparing(self, preparing):
        """Freeze the confirmed draft until preparation succeeds or fails."""
        self.preparing = bool(preparing)
        if preparing:
            def disable(owner):
                if isinstance(owner, (ctk.CTkButton, ctk.CTkEntry, ctk.CTkComboBox,
                                      ctk.CTkSwitch, ctk.CTkRadioButton, ctk.CTkTextbox, ctk.CTkCheckBox,ctk.CTkSlider)):
                    # CTkTextbox 5.2.2 forwards configure(state) but not cget(state).
                    state = owner._textbox.cget('state') if isinstance(owner, ctk.CTkTextbox) else owner.cget('state')
                    self._disabled_controls.append((owner, state))
                    owner.configure(state='disabled')
                for child in owner.winfo_children():
                    disable(child)
            disable(self)
        else:
            controls, self._disabled_controls = self._disabled_controls, []
            for control, state in controls:
                if control.winfo_exists():
                    control.configure(state=state)

    def destroy(self):
        self.audio_preview.cancel()
        self.gemini_cli_controller.cancel()
        for manager in self.managers:
            if manager.winfo_exists():
                if hasattr(manager,'controller'): manager.controller.cancel()
                if getattr(manager,'job',None): manager.after_cancel(manager.job)
                manager.destroy()
        self.destroyed=True
        self.query_token+=1
        self.query_cancel.set()
        if self.poll_job:
            self.after_cancel(self.poll_job)
            self.poll_job=None
        super().destroy()
