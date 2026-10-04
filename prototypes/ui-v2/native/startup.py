"""Startup-only settings editor. Edits a copy; never calls runtime setters."""
from copy import deepcopy
import json
import queue
import threading
import time
from pathlib import Path
import customtkinter as ctk

from domain import SessionConfig
from services import DemoCatalog, ModelInfo
from validation import assign, parse_field, validate_settings, session_snapshot
from widgets import BG, PANEL, GREEN, SOFT, INK, MUTED, LINE, NAV, FONT, label, button, card, pill, divider, OwnedComboBox, icon_image

BACKENDS = ('codex_cli', 'claude_code', 'opencode_cli', 'grok_cli', 'antigravity_cli')
STEPS = ('AI 與更新', '輸入與輸出', '白板與時間', '進階設定', '啟動確認')
LABELS = json.loads(Path(__file__).with_name('field_labels.json').read_text(encoding='utf-8'))

def leaves(obj, path=()):
    for key, value in obj.items():
        if isinstance(value, dict):
            yield from leaves(value, (*path, key))
        else:
            yield (*path, key), value

class StartupView(ctk.CTkFrame):
    def __init__(self, root, defaults, on_start, catalog=None):
        super().__init__(root, fg_color=BG, corner_radius=0)
        self.root, self.on_start = root, on_start
        self.settings = deepcopy(defaults)
        self.defaults = deepcopy(defaults)
        self.catalog = catalog or DemoCatalog()
        self.query_thread = None
        self.query_cancel = threading.Event()
        self.query_results = queue.SimpleQueue()
        self.query_token = 0
        self.query_key = None
        self.query_deadline = 0
        self.querying = False
        self.query_next_step = None
        self.destroyed = False
        self.poll_job = None
        self.step = 0
        self.ready = False
        self.models = ()
        self.backend = ctk.StringVar(value='codex_cli')
        self.model = ctk.StringVar(value='')
        self.effort = ctk.StringVar(value='')
        self.update_cli = ctk.BooleanVar(value=True)
        self.voice_in = ctk.StringVar(value='語音 + 文字')
        self.voice_out = ctk.StringVar(value='語音 + 文字')
        self.minutes = ctk.StringVar(value='30')
        self.font_size = ctk.StringVar(value='21')
        self.editors = []
        self.grid_columnconfigure(1,weight=1)
        self.grid_rowconfigure(1,weight=1)
        self.grid_columnconfigure(2,weight=0,minsize=225)
        nav = ctk.CTkFrame(self,width=196,fg_color=NAV,corner_radius=0)
        nav.grid(row=0,column=0,rowspan=3,sticky='nsew')
        nav.grid_propagate(False)
        identity=ctk.CTkFrame(nav,fg_color='transparent')
        identity.pack(fill='x',padx=22,pady=(32,34))
        mark=ctk.CTkFrame(identity,width=36,height=36,corner_radius=12,fg_color=GREEN)
        mark.pack(side='left',padx=(0,10));mark.pack_propagate(False)
        ctk.CTkLabel(mark,text='',image=icon_image('chat',color='white',size=21)).place(relx=.5,rely=.5,anchor='center')
        label(identity,'愛管家',20,weight='bold').pack(side='left')
        self.nav_buttons=[]
        for i,text in enumerate(STEPS):
            b=button(nav,text,lambda i=i:self.navigate(i),anchor='w',width=164,height=46,
                image=icon_image(('backend','mic','board','settings','check')[i],size=20),
                compound='left',border_width=0,font=(FONT,14))
            b.pack(pady=5,padx=16)
            self.nav_buttons.append(b)
        top=ctk.CTkFrame(self,fg_color='transparent')
        top.grid(row=0,column=1,sticky='ew',padx=30,pady=(32,24))
        self.breadcrumb=label(top,'1 / 5',13,color=MUTED)
        self.breadcrumb.pack(side='right')
        self.heading=label(top,'',27,weight='bold',anchor='w')
        self.heading.pack(side='left')
        self.content=ctk.CTkScrollableFrame(self,fg_color=BG,corner_radius=0,
            scrollbar_fg_color=BG,scrollbar_button_color='#CFD8E3',scrollbar_button_hover_color='#BAC8D8')
        self.content.grid(row=1,column=1,sticky='nsew',padx=(22,15),pady=(0,8))
        footer=ctk.CTkFrame(self,fg_color=PANEL,corner_radius=0,height=80)
        footer.grid(row=2,column=1,columnspan=2,sticky='ew')
        self.status=label(footer,'CLI・語音：模擬',12,color=MUTED)
        self.status.pack(side='left',padx=25,pady=23)
        self.next=button(footer,'下一步  →',self.advance,primary=True,width=125,height=44)
        self.next.pack(side='right',padx=(10,26),pady=18)
        self.previous=button(footer,'上一步',lambda:self.navigate(self.step-1),width=84,height=44)
        self.previous.pack(side='right')
        self.summary=ctk.CTkFrame(self,fg_color=NAV,corner_radius=0,width=225)
        self.summary.grid(row=0,column=2,rowspan=2,sticky='nsew',padx=(0,0))
        self.summary.grid_propagate(False)
        self._compact=False
        self.bind('<Configure>',self._resize_layout,add='+')
        self.render()

    def _resize_layout(self,event=None):
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
                border_color='#AEC5DF' if variable.get()==value else LINE,border_width=1,corner_radius=13)
            frame.grid(row=0,column=i,sticky='nsew',padx=(0,6) if i==0 else (6,0),pady=8)
            ctk.CTkRadioButton(frame,text=value,variable=variable,value=value,
                font=(FONT,15),text_color=INK,fg_color=GREEN,border_color='#B7C4D4',
                hover_color='#274E7A',radiobutton_width=19,radiobutton_height=19,
                border_width_unchecked=2,border_width_checked=5,
                command=self.render).pack(anchor='w',padx=19,pady=23)

    def render_summary(self):
        for child in self.summary.winfo_children(): child.destroy()
        label(self.summary,'本次設定',14,weight='bold',anchor='w').pack(fill='x',padx=24,pady=(38,21))
        values=[('Backend',self.backend.get().replace('_cli','').replace('_',' ').title()),
                ('Model',self.model.get() or '尚未選擇'),('輸入',self.voice_in.get()),
                ('輸出',self.voice_out.get()),('HTML 額度',self.minutes.get()+' 分鐘 / 日')]
        for key,value in values:
            label(self.summary,key,11,color=MUTED,anchor='w').pack(fill='x',padx=24,pady=(7,2))
            label(self.summary,value,14,anchor='w',wraplength=180).pack(fill='x',padx=24,pady=(0,13))
        divider(self.summary).pack(fill='x',padx=24,pady=10)
        pill(self.summary,'Alt+F4 退出',color=MUTED,bg='#EEF2F7').pack(anchor='w',padx=24,pady=10)

    def navigate(self,index):
        if self.querying:
            self.status.configure(text='正在檢查，請稍候')
            return
        if not self.collect():
            return
        self.step=max(0,min(4,index))
        self.render()

    def collect(self):
        try:
            minutes=int(self.minutes.get())
            if not 0<=minutes<=1440:
                raise ValueError('每日時間：0–1440 分鐘')
            candidate=deepcopy(self.settings)
            for path,variable,original in self.editors:
                assign(candidate,path,parse_field(variable.get(),original))
            candidate=validate_settings(candidate,self.defaults)
        except (ValueError,TypeError) as exc:
            self.status.configure(text=f'請檢查欄位：{exc}')
            return False
        self.settings=candidate
        return True

    def render(self):
        self.editors=[]
        for child in self.content.winfo_children(): child.destroy()
        self.heading.configure(text=STEPS[self.step])
        self.breadcrumb.configure(text=f'{self.step+1} / 5')
        for i,b in enumerate(self.nav_buttons):
            b.configure(fg_color=SOFT if i==self.step else NAV,
                text_color=GREEN if i==self.step else MUTED,
                hover_color='#E5EDF7',font=(FONT,14,'bold' if i==self.step else 'normal'))
        self.previous.configure(state='normal' if self.step else 'disabled')
        self.next.configure(text='啟動  ↗' if self.step==4 else '下一步  →',
                            state='disabled' if self.querying else 'normal')
        self.render_summary()
        if self.step==0:
            body=self.section('AI 服務')
            self.field(body,'Backend',self.backend,list(BACKENDS),self.invalidate)
            update_row=ctk.CTkFrame(body,fg_color=NAV,corner_radius=10)
            update_row.pack(fill='x',pady=(18,0))
            label(update_row,'啟動前更新 CLI',13).pack(side='left',padx=14,pady=14)
            ctk.CTkSwitch(update_row,text='',width=40,variable=self.update_cli,
                command=self.invalidate,progress_color=GREEN,fg_color='#D7DFEA',
                button_color=PANEL,button_hover_color='#F1F5FA').pack(side='right',padx=14)
            body=self.section('模型與推理')
            fields=ctk.CTkFrame(body,fg_color='transparent')
            fields.pack(fill='x')
            fields.grid_columnconfigure(0,weight=3);fields.grid_columnconfigure(1,weight=2)
            left=ctk.CTkFrame(fields,fg_color='transparent');left.grid(row=0,column=0,sticky='ew',padx=(0,12))
            right=ctk.CTkFrame(fields,fg_color='transparent');right.grid(row=0,column=1,sticky='ew')
            self.model_menu=self.field(left,'Model',self.model,[m.id for m in self.models] or ['尚未查詢'],self.select_model)
            self.effort_menu=self.field(right,'Effort',self.effort,['尚未查詢'])
            if not self.ready:
                self.model.set('尚未查詢');self.effort.set('—')
                self.model_menu.configure(state='disabled');self.effort_menu.configure(state='disabled')
            else: self.select_model(self.model.get())
            self.query_button=button(body,'更新並查詢模型' if self.update_cli.get() else '查詢模型',self.query,primary=True,height=40)
            self.query_button.pack(anchor='w',pady=(22,0))
            self.query_button.configure(state='disabled' if self.querying else 'normal')
        elif self.step==1:
            self.choice(self.content,'輸入',self.voice_in)
            self.choice(self.content,'輸出',self.voice_out)
            body=self.section('閱讀')
            self.field(body,'對話字級',self.font_size,['19','21','24'],lambda _:self.render_summary())
        elif self.step==2:
            body=self.section('HTML 每日額度')
            row=ctk.CTkFrame(body,fg_color='transparent');row.pack(fill='x',pady=(12,18))
            ctk.CTkEntry(row,textvariable=self.minutes,width=130,height=62,font=(FONT,30),
                fg_color=NAV,text_color=INK,border_color=LINE,border_width=1,
                corner_radius=12,justify='center').pack(side='left')
            label(row,'分鐘 / 日',15,color=MUTED).pack(side='left',padx=16)
            divider(body).pack(fill='x',pady=4)
            for text in ['隱藏、關閉時暫停','每日 00:00 重置','Markdown、圖片不限時']:
                label(body,'✓  '+text,14,anchor='w').pack(fill='x',pady=(12,0))
        elif self.step==3:
            groups=list(self.settings)
            body=self.section('設定分類')
            self.group=ctk.StringVar(value=LABELS.get(groups[0],groups[0]))
            self.current_group=groups[0]
            self.field(body,'分類',self.group,[LABELS.get(g,g) for g in groups],
                lambda name:self.render_group(groups[[LABELS.get(g,g) for g in groups].index(name)]))
            self.editor_frame=ctk.CTkFrame(body,fg_color='transparent')
            self.editor_frame.pack(fill='both',expand=True,pady=(15,0))
            self.render_group(groups[0])
        else:
            body=self.section('啟動確認')
            rows=[('Backend',self.backend.get()),('Model',self.model.get() if self.ready else '尚未查詢'),
                  ('Effort',self.effort.get() if self.ready else '—'),('輸入',self.voice_in.get()),
                  ('輸出',self.voice_out.get()),('HTML',f'{self.minutes.get()} 分鐘 / 日'),
                  ('對話字級',self.font_size.get()+' px')]
            for i,(key,value) in enumerate(rows):
                line=ctk.CTkFrame(body,fg_color='transparent')
                line.pack(fill='x',pady=7)
                label(line,key,13,color=MUTED).pack(side='left',pady=4)
                label(line,value,14,weight='bold').pack(side='right')
                if i<len(rows)-1: divider(body).pack(fill='x')
            pill(body,'已完成檢查' if self.ready else '請先查詢模型').pack(anchor='w',pady=(20,0))

    def render_group(self,group):
        if not self.collect():
            self.group.set(LABELS.get(self.current_group,self.current_group))
            return
        self.current_group=group
        self.editors=[]
        for child in self.editor_frame.winfo_children(): child.destroy()
        for path,value in leaves(self.settings[group],(group,)):
            if path[-1] in ('fullscreen_exit_shortcuts','fullscreen_enter_shortcuts'):
                label(self.editor_frame,'全螢幕退出固定為 Alt+F4',13).pack(anchor='w',pady=8)
                continue
            if path[0]=='llm' and path[-1] in ('active_backend','model','reasoning_effort'):
                continue
            name=' / '.join(LABELS.get(p,p) for p in path[1:])
            label(self.editor_frame,name,14,anchor='w',wraplength=560).pack(fill='x',pady=(12,4))
            if isinstance(value,bool):
                var=ctk.BooleanVar(value=value)
                widget=ctk.CTkSwitch(self.editor_frame,text='',variable=var,progress_color=GREEN,
                    fg_color='#D7DFEA',button_color=PANEL,button_hover_color='#F1F5FA')
            else:
                var=ctk.StringVar(value='; '.join(map(str,value)) if isinstance(value,list) else '' if value is None else str(value))
                widget=ctk.CTkEntry(self.editor_frame,textvariable=var,height=44,font=(FONT,14),
                    fg_color=NAV,text_color=INK,border_color=LINE,border_width=1,corner_radius=10,
                    show='•' if path[-1]=='api_key' else '')
            widget.pack(fill='x',pady=(0,5))
            self.editors.append((path,var,value))

    def invalidate(self,*args):
        self.query_token+=1
        self.query_cancel.set()
        self.querying=False
        self.query_next_step=None
        self.ready=False
        self.models=()
        self.model.set('')
        self.effort.set('')
        self.render()

    def query(self,*,advance_after=False):
        if self.querying:
            self.status.configure(text='正在檢查，請稍候')
            return
        if self.query_thread and self.query_thread.is_alive():
            self.status.configure(text='上一筆查詢尚未結束，請稍候')
            return
        self.ready=False
        self.models=()
        self.querying=True
        self.query_next_step=1 if advance_after else None
        # Keep the clicked button alive until its CTk click animation finishes.
        # Rebuilding the page here would destroy that pending Tcl command.
        self.model.set('尚未查詢');self.effort.set('—')
        self.model_menu.configure(state='disabled')
        self.effort_menu.configure(state='disabled')
        self.query_button.configure(state='disabled')
        self.next.configure(state='disabled')
        self.render_summary()
        self.status.configure(text='查詢中（模擬）')
        self.query_token+=1
        token=self.query_token
        key=(self.backend.get(),self.update_cli.get())
        self.query_key=key
        self.query_cancel=threading.Event()
        cancel=self.query_cancel
        self.query_deadline=time.monotonic()+30
        def work():
            try:
                models=self.catalog.query(*key,cancel=cancel,timeout=30)
                result=(models,None)
            except Exception as exc:
                result=(None,type(exc).__name__)
            self.query_results.put((token,key,result))
        # A stalled adapter cannot keep the demo process alive after close.
        self.query_thread=threading.Thread(target=work,daemon=True,name='demo-catalog')
        self.query_thread.start()
        if not self.poll_job:
            self.poll_job=self.after(100,self.poll_query)

    def poll_query(self):
        self.poll_job=None
        if self.destroyed: return
        while not self.query_results.empty():
            token,key,(models,error)=self.query_results.get()
            if token!=self.query_token or key!=(self.backend.get(),self.update_cli.get()): continue
            self.querying=False
            try:
                if error: raise ValueError(error)
                if not isinstance(models,tuple) or not models or len(models)>500 or any(not isinstance(m,ModelInfo) for m in models):
                    raise ValueError('模型清單格式無效')
                if len({m.id for m in models})!=len(models): raise ValueError('模型識別字重複')
                self.models=models
                self.model.set(models[0].id)
                self.effort.set(models[0].efforts[0] if models[0].efforts else '')
                self.ready=True
                self.status.configure(text='模型清單已更新 · 模擬資料')
            except ValueError as exc:
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
        if self.querying:
            self.status.configure(text='正在檢查，請稍候')
            return
        if self.step==0 and (not self.ready or self.query_key!=(self.backend.get(),self.update_cli.get())):
            if self.collect(): self.query(advance_after=True)
            return
        if self.step!=4:
            self.navigate(self.step+1)
            return
        if not self.collect(): return
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
            self.on_start(cfg,session_snapshot(self.settings,cfg))
        except ValueError as exc:
            self.status.configure(text=str(exc))

    def destroy(self):
        self.destroyed=True
        self.query_token+=1
        self.query_cancel.set()
        if self.poll_job:
            self.after_cancel(self.poll_job)
            self.poll_job=None
        super().destroy()

