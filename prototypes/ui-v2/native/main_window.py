"""Native v2 shell, with existing animation, input monitor and Windows guards.

Legacy VoiceAssistantUI.__init__ is intentionally NOT invoked: it would create
the production UI and assistant. Only its Windows guard/event helpers are reused.
An approved integration should extract those helpers into a shared component.
"""
import ctypes
import json
import math
import queue
import sys
import threading
import time
import tkinter as tk
from copy import deepcopy

import customtkinter as ctk
from PIL import Image
from config import config as isolated_config
from core.state_machine import State
from ui.animation_controller import AnimationController
from ui.global_input_monitor import GlobalInputMonitor
from html_host import NativeHtmlRenderer
from ui.main_window import VoiceAssistantUI as LegacyWindow
from markdown_host import OwnedMarkdownRenderer
from fullscreen_host import FullscreenHost

from bootstrap import APP, NATIVE, RUNTIME
from domain import HtmlBudget, Phase, SessionController
from services import DemoTurnService
from window_environment import desktop_available
from startup import StartupView
from widgets import BG, PANEL, GREEN, INK, SOFT, MUTED, LINE, NAV, GOLD, FONT, label, button, IconButton, card, pill, icon_image

# Main-view accents stay separate from the neutral startup form. Reading and
# animation surfaces remain plain; decorative shapes live in the chrome only.
MAIN_BG = '#EEF2F5'
CHROME = '#243E57'
BLUE_TINT = '#EDF3F8'
SAGE = '#718F87'
SAGE_TINT = '#E9F1EC'
WARM_TINT = '#F7F3EB'


class PreviewInputMonitor(GlobalInputMonitor):
    def _can_use_widget_bindings(self):
        # Embedded Edge has its own event loop, so Tk bindings miss its events.
        return False

    def _is_own_app_foreground(self):
        return self.widget._keyboard_guard_in_scope()

class MainWindow(LegacyWindow):
    def __init__(self, review_tools=False, smoke=False, runtime_path=None):
        ctk.CTk.__init__(self)
        self.title('愛管家 · Native UI Demo')
        screen_width,screen_height=self._get_logical_screen_size()
        width,height=min(1160,max(320,screen_width-48)),min(800,max(240,screen_height-80))
        self.geometry(f'{width}x{height}')
        self.minsize(min(1080,width),min(720,height))
        self.configure(fg_color=BG)
        self.review_tools=review_tools
        self.smoke=smoke
        self.runtime=runtime_path or RUNTIME
        self.controller=None
        self._closing_event=threading.Event()
        self._ui_event_queue=queue.SimpleQueue()
        self._ui_event_after_id=None
        self._whiteboard_current_state={}
        self.html_whiteboard_renderer=None
        self.animator=None
        self.input_monitor=None
        self.board_kind=None
        self.board_visible=False
        self._tick_job=None
        self._capture_job=None
        self._resize_job=None
        self._html_resize_job=None
        self._notice_job=None
        self._scroll_job=None
        self._turn_timeout_job=None
        self._budget_charge=False
        self._budget_failed=False
        self._budget_save_stamp=0
        self._native_root=None
        self.cleanup_errors=[]
        self._message_blocks=[]
        self._composer_focused=False
        self._board_source_image=None
        self._fullscreen_host=None
        self._fullscreen_resize_job=None
        self._startup_position_job=None
        self._fullscreen_exit_shortcuts=self._normalize_fullscreen_shortcuts(['ALT+F4'])
        self._fullscreen_keyboard_block_enabled=False
        self._schedule_ui_event_poll()
        self.protocol('WM_DELETE_WINDOW',self._window_close_request)
        self.bind('<Alt-F4>',lambda e:self.close())
        self.bind('<F11>',lambda e:'break')
        self.bind('<Escape>',lambda e:'break')
        self.bind('<Button-1>',self._release_whiteboard_keyboard_capture,add='+')
        self.bind('<Configure>',self._schedule_fullscreen_fit,add='+')
        defaults=json.loads((APP/'config.default.json').read_text(encoding='utf-8'))
        # The requested activity behavior is enabled in this isolated demo only.
        defaults['user_activity_prompt']['enabled']=True
        self.startup=StartupView(self,defaults,self.start_session)
        self.startup.pack(fill='both',expand=True)
        self._startup_position_job=self.after(200,self._position_startup)

    def _position_startup(self):
        self._startup_position_job=None
        if self._is_closing() or self.controller: return
        self.update_idletasks()
        host=FullscreenHost(self.winfo_id())
        area=host.monitor_bounds(work_area=True)
        current=host.window_bounds()
        width=min(current.width,max(1,area.width-48))
        height=min(current.height,max(1,area.height-48))
        # Native work-area coordinates include titlebar/taskbar and DPI. Avoid
        # a well-sized startup form opening partly below the visible desktop.
        host._checked(host.api.SetWindowPos(host.hwnd,None,
            area.left+(area.width-width)//2,area.top+(area.height-height)//2,
            width,height,0x0004|0x0010))

    def _window_close_request(self):
        if self.controller is None:
            self.close()

    def _handle_fullscreen_exit_shortcut(self,event=None):
        return self.close()

    @staticmethod
    def _should_block_fullscreen_keyboard_shortcut(vk_code,flags=0,ctrl_down=False):
        return vk_code in (0x7A,0x1B) or LegacyWindow._should_block_fullscreen_keyboard_shortcut(vk_code,flags,ctrl_down)

    def _keyboard_guard_in_scope(self):
        if self._is_closing(): return False
        if GlobalInputMonitor._is_own_app_foreground():
            return True
        api=ctypes.windll.user32
        api.GetForegroundWindow.restype=ctypes.c_void_p
        api.GetAncestor.argtypes=[ctypes.c_void_p,ctypes.c_uint]
        api.GetAncestor.restype=ctypes.c_void_p
        foreground=api.GetForegroundWindow()
        if foreground and self._native_root and api.GetAncestor(foreground,2)==self._native_root:
            return True
        renderer=self.html_whiteboard_renderer
        if renderer: renderer.set_keyboard_capture(False)
        return False

    def _remove_fullscreen_screen_guard(self):
        hwnd=self.__dict__.get('_screen_guard_hwnd')
        previous=self.__dict__.get('_screen_guard_prev_wndproc')
        proc=self.__dict__.get('_screen_guard_proc')
        if hwnd and previous and proc:
            _,setter=self._get_window_long_accessors()
            if not setter(hwnd,-4,previous):
                # Retain the callback while the HWND still refers to it. The
                # close() cleanup owner will destroy the window with it alive.
                raise RuntimeError('無法還原 screen guard WindowProc')
        self._screen_guard_hwnd=None
        self._screen_guard_prev_wndproc=None
        self._screen_guard_proc=None

    def _set_display_awake(self,enabled):
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.SetThreadExecutionState.argtypes=[ctypes.c_ulong]
        api.SetThreadExecutionState.restype=ctypes.c_ulong
        if not api.SetThreadExecutionState(0x80000000 | (3 if enabled else 0)):
            raise ctypes.WinError(ctypes.get_last_error())

    def _drain_ui_events(self):
        self._ui_event_after_id=None
        if self._is_closing(): return
        for _ in range(100):
            try: callback,args,kwargs=self._ui_event_queue.get_nowait()
            except queue.Empty: break
            try: callback(*args,**kwargs)
            except Exception:
                self.report_callback_exception(*sys.exc_info())
            if self._is_closing(): return
        self._schedule_ui_event_poll()

    def _forward_captured_whiteboard_key(self,*args,**kwargs):
        # The hook thread reads only a flag maintained by Tk focus events.
        if self._composer_focused: return False
        return super()._forward_captured_whiteboard_key(*args,**kwargs)

    def enter_fullscreen(self):
        self.update_idletasks()
        self.minsize(0,0)
        self.attributes('-fullscreen',True)
        self.update_idletasks()
        # Tk recreates its wrapper HWND when entering fullscreen on Windows.
        host=FullscreenHost(self.winfo_id())
        self._fullscreen_host=host
        host.fit()
        self._native_root=host.hwnd
        self._schedule_fullscreen_fit()

    def _schedule_fullscreen_fit(self,event=None):
        if event is not None and event.widget is not self: return
        if self._is_closing() or not self._fullscreen_host or self._fullscreen_resize_job: return
        self._fullscreen_resize_job=self.after_idle(self._fit_fullscreen)

    def _fit_fullscreen(self):
        self._fullscreen_resize_job=None
        if not self._is_closing() and self._fullscreen_host:
            self._fullscreen_host.fit()

    def start_session(self,cfg,settings):
        if self.controller or self._is_closing(): return
        try:
            self.budget=HtmlBudget(self.runtime/'html-budget.json',cfg.html_minutes*60)
            self.budget.save()  # Prove persistence works before enabling HTML.
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.startup.status.configure(text=f'額度讀取失敗：{exc}')
            return
        self.settings=deepcopy(settings)
        # Read-only process-local config for the reused input monitor.
        with isolated_config._save_lock:
            isolated_config._config=deepcopy(settings)
        self.controller=SessionController(cfg)
        self.service=DemoTurnService(self,lambda:cfg.voice_output and not self.controller.speaker_muted)
        # The app owns all resources once this transition begins. If startup
        # fails, the entrypoint's exception handler closes the entire preview.
        self.startup.pack_forget()
        self._build_main(cfg)
        self.update_idletasks()
        api=ctypes.windll.user32
        api.GetAncestor.argtypes=[ctypes.c_void_p,ctypes.c_uint]
        api.GetAncestor.restype=ctypes.c_void_p
        self._native_root=api.GetAncestor(self.winfo_id(),2)
        self.input_monitor=PreviewInputMonitor(lambda source:self._post_to_ui(self.on_activity,source),widget=self)
        self.last_activity_prompt=time.monotonic()
        self.input_monitor.start()
        if not self.input_monitor._started:
            raise RuntimeError('Input monitor 未成功啟動')
        if not self.smoke:
            self.enter_fullscreen()
            self._set_display_awake(True)
            self._set_screensaver_block(True)
            getter,_=self._get_window_long_accessors()
            proc=self.__dict__.get('_screen_guard_proc')
            if proc is None or getter(self._screen_guard_hwnd,-4)!=ctypes.cast(proc,ctypes.c_void_p).value:
                raise RuntimeError('screen guard 未成功啟動')
            self._set_keyboard_shortcut_block(True)
            if not self.__dict__.get('_keyboard_hook_handle'):
                raise RuntimeError('全螢幕 keyboard guard 未成功啟動')
        self.startup.destroy()
        self.animator.set_state(State.IDLE_LISTEN)
        self.refresh()
        self._tick_job=self.after(250,self.tick)
        self.schedule_resize()

    def _build_main(self,cfg):
        self.shell=ctk.CTkFrame(self,fg_color=MAIN_BG,corner_radius=0)
        self.shell.pack(fill='both',expand=True)
        self.shell.grid_columnconfigure(0,weight=1)
        self.shell.grid_columnconfigure(1,weight=0,minsize=380)
        self.shell.grid_rowconfigure(1,weight=1)
        header=ctk.CTkFrame(self.shell,fg_color=CHROME,corner_radius=0,height=58)
        header.grid(row=0,column=0,columnspan=2,sticky='ew')
        brand=ctk.CTkFrame(header,width=38,height=38,corner_radius=12,fg_color='#36546D')
        brand.pack(side='left',padx=(22,11),pady=12);brand.pack_propagate(False)
        ctk.CTkLabel(brand,text='',width=24,height=24,
            image=icon_image('chat',color='#F4F7FA',size=23)).place(relx=.5,rely=.5,anchor='center')
        label(header,'愛管家',21,weight='bold',color='#F4F7FA').pack(side='left',pady=14)
        pill(header,f'{cfg.backend.replace("_cli","").title()}  /  {cfg.model}',
             color='#D9E5EF',bg='#304D66').pack(side='right',padx=22)
        # A small, static composition adds warmth without competing with content.
        accents=ctk.CTkFrame(header,width=94,height=34,fg_color='transparent')
        accents.pack(side='right',padx=(12,4));accents.pack_propagate(False)
        for x,y,width,color in ((0,7,45,'#819EAF'),(20,16,55,'#B8C9C1'),(8,25,28,'#D4B882')):
            ctk.CTkFrame(accents,width=width,height=3,corner_radius=2,fg_color=color).place(x=x,y=y)
        ctk.CTkFrame(accents,width=7,height=7,corner_radius=4,fg_color='#D4B882').place(x=81,y=6)
        ctk.CTkFrame(header,height=2,corner_radius=0,fg_color='#B6C9CC').place(relx=0,rely=1,relwidth=1,y=-2,anchor='sw')
        self.stage=card(self.shell)
        self.stage.grid(row=1,column=0,sticky='nsew',padx=(14,8),pady=14)
        self.stage.grid_rowconfigure(0,weight=1)
        self.stage.grid_columnconfigure(0,weight=1)
        self.scene=ctk.CTkFrame(self.stage,fg_color=PANEL,corner_radius=0)
        self.scene.grid(row=0,column=0,sticky='nsew',padx=8,pady=8)
        self.scene_label=ctk.CTkLabel(self.scene,text='')
        self.scene_label.place(relx=.5,rely=.5,anchor='center')
        self.animator=AnimationController(self.scene_label,
            interval_ms=int(self.settings['ui']['animation_interval_ms']),
            foreground_y_offset_px=int(self.settings['ui']['animation_foreground_y_offset_px']))
        self.scene.bind('<Configure>',self.schedule_resize)
        self.restore_button=IconButton(self.scene,'board',self.restore_board,tip='展開白板',
            width=52,height=52,fg_color=WARM_TINT,border_color='#D9C8A7',hover_color='#EEE5D5')
        self.board=ctk.CTkFrame(self.stage,fg_color=PANEL,corner_radius=12)
        self.board.grid_rowconfigure(2,weight=1)
        self.board.grid_columnconfigure(0,weight=1)
        toolbar=ctk.CTkFrame(self.board,fg_color=BLUE_TINT,corner_radius=11)
        toolbar.grid(row=0,column=0,sticky='ew',padx=15,pady=10)
        board_mark=ctk.CTkFrame(toolbar,width=32,height=32,corner_radius=10,fg_color='#F3EADC')
        board_mark.pack(side='left',padx=(10,0),pady=6);board_mark.pack_propagate(False)
        ctk.CTkLabel(board_mark,text='',width=22,height=22,
            image=icon_image('board',color='#987746',size=21)).place(relx=.5,rely=.5,anchor='center')
        self.board_title=label(toolbar,'白板',17,weight='bold')
        self.board_title.pack(side='left',padx=10)
        IconButton(toolbar,'close',self.close_board,tip='關閉白板').pack(side='right',padx=(4,4))
        IconButton(toolbar,'hide',self.hide_board,tip='隱藏白板').pack(side='right')
        self.quota_row=ctk.CTkFrame(self.board,fg_color=NAV,corner_radius=9)
        self.quota_row.grid(row=1,column=0,sticky='ew',padx=15,pady=(0,10))
        self.quota_bar=ctk.CTkProgressBar(self.quota_row,progress_color=GREEN,fg_color=LINE,height=5,corner_radius=3)
        self.quota_bar.pack(side='left',fill='x',expand=True,padx=14,pady=12)
        self.quota_label=label(self.quota_row,'30:00',13,color=MUTED)
        self.quota_label.pack(side='right',padx=14)
        self.board_body=ctk.CTkFrame(self.board,fg_color=PANEL,corner_radius=0)
        self.board_body.grid(row=2,column=0,sticky='nsew',padx=15,pady=(0,15))
        self.board_body.bind('<Configure>',self.resize_html)
        self.markdown=OwnedMarkdownRenderer()

        self.chat=card(self.shell,width=400)
        self.chat.grid(row=1,column=1,sticky='nsew',padx=(6,14),pady=14)
        self.chat.grid_propagate(False)
        self.chat.grid_columnconfigure(0,weight=1)
        self.chat.grid_rowconfigure(1,weight=1)
        chat_header=ctk.CTkFrame(self.chat,fg_color=BLUE_TINT,corner_radius=12)
        chat_header.grid(row=0,column=0,sticky='ew',padx=14,pady=(14,10))
        chat_mark=ctk.CTkFrame(chat_header,width=32,height=32,corner_radius=10,fg_color=SAGE_TINT)
        chat_mark.pack(side='left',padx=(10,9),pady=10);chat_mark.pack_propagate(False)
        ctk.CTkLabel(chat_mark,text='',width=22,height=22,
            image=icon_image('chat',color=SAGE,size=21)).place(relx=.5,rely=.5,anchor='center')
        label(chat_header,'對話',20,weight='bold').pack(side='left')
        badge=ctk.CTkFrame(chat_header,fg_color=PANEL,corner_radius=11)
        badge.pack(side='right',padx=10)
        self.phase_label=label(badge,'●  待機',12,color='#557B70')
        self.phase_label.pack(padx=11,pady=5)
        self.messages=ctk.CTkScrollableFrame(self.chat,fg_color=PANEL,scrollbar_fg_color=PANEL,
            scrollbar_button_color='#D0DAE6',scrollbar_button_hover_color='#B5C6DA')
        self.messages.grid(row=1,column=0,sticky='nsew',padx=10,pady=(4,10))
        self.empty_state=ctk.CTkFrame(self.messages,fg_color='transparent')
        self.empty_state.pack(fill='x',pady=60)
        empty_mark=ctk.CTkFrame(self.empty_state,width=52,height=52,corner_radius=18,fg_color=SAGE_TINT)
        empty_mark.pack(pady=(0,12));empty_mark.pack_propagate(False)
        ctk.CTkLabel(empty_mark,text='',width=28,height=28,
            image=icon_image('chat',color=SAGE)).place(relx=.5,rely=.5,anchor='center')
        label(self.empty_state,'尚無對話',13,color=MUTED).pack()
        self.queue_frame=ctk.CTkFrame(self.chat,fg_color='#FCF5EC',corner_radius=12,
            border_width=1,border_color='#EEDFCB')
        self.queue_frame.grid(row=2,column=0,sticky='ew',padx=15,pady=7)
        self.queue_frame.grid_remove()
        self._queue_signature=None
        composer=ctk.CTkFrame(self.chat,fg_color=NAV,corner_radius=17,
            border_width=1,border_color=LINE)
        composer.grid(row=3,column=0,sticky='ew',padx=16,pady=(8,18))
        self.input=ctk.CTkTextbox(composer,height=100,font=(FONT,19),
            fg_color=NAV,text_color=INK,border_width=0,corner_radius=12,
            scrollbar_button_color='#BAC8D8',scrollbar_button_hover_color='#94ACC7')
        self.input.pack(fill='x',padx=12,pady=(12,0))
        self.input.bind('<Control-Return>',lambda event:self.send())
        def focus_in(_):
            self._composer_focused=True
            self._release_whiteboard_keyboard_capture()
            composer.configure(border_color='#94ACC7')
        def focus_out(_):
            self._composer_focused=False
            composer.configure(border_color=LINE)
        self.input.bind('<FocusIn>',focus_in)
        self.input.bind('<FocusOut>',focus_out)
        ctk.CTkFrame(composer,fg_color=LINE,height=1,corner_radius=0).pack(fill='x',padx=15,pady=(9,0))
        controls=ctk.CTkFrame(composer,fg_color='transparent')
        controls.pack(fill='x',padx=12,pady=(10,12))
        self.mic=IconButton(controls,'mic',self.toggle_mic)
        self.mic.pack(side='left',padx=(0,8))
        self.speaker=IconButton(controls,'speaker',self.toggle_speaker)
        self.speaker.pack(side='left')
        self.send_button=IconButton(controls,'send',self.send,tip='送出 · Ctrl+Enter')
        self.send_button.pack(side='right')
        self.notice=label(self.chat,'',11,color=MUTED,wraplength=345,anchor='w')
        self.notice.grid(row=4,column=0,sticky='ew',padx=20,pady=(0,10))
        self.notice.grid_remove()
        if self.review_tools:
            self.build_review_tools()
            self.add_message('月亮為什麼有時候圓圓的，有時候彎彎的？','user')
            self.add_message('月亮的形狀沒有改變。\n\n我們看見的，是它被太陽照亮的不同部分。')

    def build_review_tools(self):
        tools=ctk.CTkFrame(self.shell,fg_color=SOFT,corner_radius=0)
        tools.grid(row=2,column=0,columnspan=2,sticky='ew')
        label(tools,'Review',12).pack(side='left',padx=12)
        for name,callback in [('Markdown',lambda:self.show_board('md')),
                              ('圖片',lambda:self.show_board('image')),
                              ('HTML',lambda:self.show_board('html')),
                              ('朗讀',lambda:self.enqueue_demo('語音測試')),
                              ('剩 10 秒',self.ten_seconds),
                              ('重設額度',self.reset_budget)]:
            control=button(tools,name,callback,width=90,height=32)
            control.pack(side='left',padx=3,pady=5)
            if name=='HTML': self._review_html_button=control
        self._review_quota_label=label(tools,'',12,color=MUTED)
        self._review_quota_label.pack(side='left',padx=10)
        self.animation_override=ctk.StringVar(value='AUTO')
        ctk.CTkOptionMenu(tools,values=['AUTO']+[s.name for s in State],
            variable=self.animation_override,command=lambda _:self.refresh(),width=150,
            fg_color=GREEN).pack(side='right',padx=12)
        self._sync_review_budget()

    def _sync_review_budget(self):
        if not hasattr(self,'_review_html_button'): return
        remaining=math.ceil(self.budget.remaining)
        if not self.settings['whiteboard']['enabled']:
            status='白板已停用'
        elif self._budget_failed:
            status='HTML 已停用 · 儲存失敗'
        elif not remaining:
            status='HTML 00:00 · 今日已用完'
        else:
            status=f'HTML {remaining//60:02}:{remaining%60:02}'
        enabled=bool(remaining and not self._budget_failed and self.settings['whiteboard']['enabled'])
        self._review_html_button.configure(state='normal' if enabled else 'disabled')
        self._review_quota_label.configure(text=status)

    def schedule_resize(self,event=None):
        if self._resize_job: self.after_cancel(self._resize_job)
        self._resize_job=self.after(100,self.resize_stage)

    def resize_stage(self):
        self._resize_job=None
        if self.animator and not self._is_closing():
            # AnimationController preserves source aspect ratio and frame timing.
            scale=self.scene._get_widget_scaling()
            self.animator.set_image_size(max(1,int(self.scene.winfo_width()/scale)),max(1,int(self.scene.winfo_height()/scale)))

    def add_message(self,text,role='assistant'):
        if self.empty_state.winfo_exists(): self.empty_state.destroy()
        block=ctk.CTkFrame(self.messages,fg_color='transparent')
        block.pack(fill='x',padx=(6,18) if role=='assistant' else (22,6),pady=(10,14))
        self._message_blocks.append(block)
        # Bound widget/image retention for a session lasting all day.
        if len(self._message_blocks)>200:
            self._message_blocks.pop(0).destroy()
        label(block,'愛管家' if role=='assistant' else '你',12,color=MUTED,
            anchor='w' if role=='assistant' else 'e').pack(fill='x',padx=3,pady=(0,6))
        wrapper=ctk.CTkFrame(block,fg_color=WARM_TINT if role=='assistant' else '#EAF1FB',
            border_width=1,border_color='#EBE3D6' if role=='assistant' else '#D8E5F3',corner_radius=16)
        wrapper.pack(fill='x')
        content=label(wrapper,text,self.controller.config.chat_font,justify='left',anchor='w',wraplength=300)
        content.pack(fill='x',padx=18,pady=15)
        wrapper.bind('<Configure>',lambda event:content.configure(wraplength=max(100,int(event.width/self.scene._get_widget_scaling())-36)))
        # Preserve reading position when the user scrolls into older messages.
        if self.messages._parent_canvas.yview()[1]>.95:
            if self._scroll_job: self.after_cancel(self._scroll_job)
            self._scroll_job=self.after_idle(self._scroll_to_end)

    def _scroll_to_end(self):
        self._scroll_job=None
        if not self._is_closing(): self.messages._parent_canvas.yview_moveto(1)

    def send(self):
        try:
            if self.controller.enqueue(self.input.get('1.0','end')):
                self.input.delete('1.0','end')
                self.dispatch()
        except ValueError as exc:
            self.notify(str(exc))
        return 'break'

    def enqueue_demo(self,text):
        self.controller.enqueue(text)
        self.dispatch()

    def dispatch(self):
        next_turn=self.controller.take_next()
        if next_turn:
            item,generation=next_turn
            self.add_message(item.text,'user')
            self.generation_done=False
            self.playback_done=False
            self._turn_timeout_job=self.after(int(self.settings['llm']['response_timeout_seconds']*1000),lambda:self.on_turn_event(generation,'error','回覆逾時'))
            try:
                self.service.start(item.text,lambda kind,payload:self._post_to_ui(self.on_turn_event,generation,kind,payload))
            except Exception:
                self.on_turn_event(generation,'error','無法啟動回覆')
                return
            if '白板' in item.text or 'Markdown' in item.text: self.show_board('md')
            if '圖片' in item.text: self.show_board('image')
            if 'HTML' in item.text or '遊戲' in item.text: self.show_board('html')
        self.refresh()

    def on_turn_event(self,generation,kind,payload):
        if self._is_closing() or generation!=self.controller.generation or self.controller.phase not in (Phase.THINKING,Phase.SPEAKING): return
        if kind=='text': self.add_message(payload)
        elif kind=='generation_done': self.generation_done=True
        elif kind=='playback_started':
            if not self.playback_done: self.controller.phase=Phase.SPEAKING
        elif kind=='playback_done': self.playback_done=True
        elif kind=='error':
            self.service.cancel()
            self.cancel_turn_timeout()
            self.controller.interrupt()
            self.notify(payload)
            # A persistent backend failure must not drain and lose the queue.
            self.refresh()
            return
        if self.generation_done and self.playback_done:
            self.cancel_turn_timeout()
            self.controller.finish(generation)
            self.dispatch()
        else: self.refresh()

    def cancel_turn_timeout(self):
        if self._turn_timeout_job:
            self.after_cancel(self._turn_timeout_job)
            self._turn_timeout_job=None

    def toggle_mic(self):
        outcome=self.controller.toggle_mic()
        if outcome=='locked': self.notify('固定文字輸入')
        elif outcome=='interrupt':
            self.cancel_turn_timeout()
            self.service.cancel()
            self.begin_capture_timeout()
        elif self.controller.phase==Phase.IDLE:
            if self._capture_job:
                self.after_cancel(self._capture_job);self._capture_job=None
            self.dispatch()
        self.refresh()

    def begin_capture_timeout(self):
        if self._capture_job: self.after_cancel(self._capture_job)
        generation=self.controller.generation
        self._capture_job=self.after(5000,lambda:self.finish_capture(generation))

    def finish_capture(self,generation):
        self._capture_job=None
        if self.controller.phase==Phase.LISTENING and generation==self.controller.generation:
            self.controller.phase=Phase.IDLE
            self.dispatch()

    def toggle_speaker(self):
        if self.controller.toggle_speaker()=='locked': self.notify('固定文字輸出')
        elif self.controller.speaker_muted: self.service.mute_output()
        self.refresh()

    def interrupt_send(self):
        self.cancel_turn_timeout()
        self.service.cancel()
        self.controller.interrupt()
        if self._capture_job:
            self.after_cancel(self._capture_job);self._capture_job=None
        self.dispatch()

    def refresh(self):
        c=self.controller
        if not c: return
        mic_tip='固定文字輸入' if not c.config.voice_input else '打斷並收音' if c.phase==Phase.SPEAKING else '開啟麥克風' if c.manual_mute else '關閉麥克風'
        self.mic.set_status(c.mic_muted,not c.config.voice_input,mic_tip)
        self.speaker.set_status(c.speaker_muted,not c.config.voice_output,'固定文字輸出' if not c.config.voice_output else '開啟朗讀' if c.speaker_muted else '停止朗讀')
        self.phase_label.configure(text='●  '+{Phase.IDLE:'待機',Phase.LISTENING:'收音中',Phase.THINKING:'思考中',Phase.SPEAKING:'朗讀中'}[c.phase])
        state={Phase.IDLE:State.IDLE_LISTEN,Phase.LISTENING:State.COLLECTING,Phase.THINKING:State.SENDING,Phase.SPEAKING:State.SPEAKING}[c.phase]
        if self.review_tools and self.animation_override.get()!='AUTO':
            state=State[self.animation_override.get()]
        self.animator.set_state(state)
        if self.html_whiteboard_renderer:
            self.html_whiteboard_renderer.set_ducked(c.phase==Phase.SPEAKING)
        self._sync_activity_monitor()
        signature=tuple((q.id,q.text) for q in c.pending)
        if signature!=self._queue_signature:
            self._queue_signature=signature
            for child in self.queue_frame.winfo_children(): child.destroy()
            if c.pending:
                self.queue_frame.grid()
                button(self.queue_frame,f'打斷並送出 · {len(c.pending)}',self.interrupt_send,height=32).pack(fill='x',padx=10,pady=8)
                for item in list(c.pending)[:3]:
                    row=ctk.CTkFrame(self.queue_frame,fg_color='transparent')
                    row.pack(fill='x',padx=10,pady=2)
                    label(row,item.text[:30],12,wraplength=235,anchor='w').pack(side='left',fill='x',expand=True)
                    button(row,'×',lambda ident=item.id:self.cancel_message(ident),width=30,height=28).pack(side='right')
                if len(c.pending)>3:
                    button(self.queue_frame,'檢視全部',self.show_queue,width=100,height=28).pack(pady=5)
            else: self.queue_frame.grid_remove()
            if hasattr(self,'queue_overlay') and self.queue_overlay.winfo_exists(): self.show_queue()

    def show_queue(self):
        # In-session panel, no top-level window with an OS close/minimize menu.
        if hasattr(self,'queue_overlay') and self.queue_overlay.winfo_exists(): self.queue_overlay.destroy()
        self.queue_overlay=ctk.CTkFrame(self.chat,fg_color=PANEL,border_width=1,border_color=SOFT)
        self.queue_overlay.place(relx=0,rely=0,relwidth=1,relheight=1)
        button(self.queue_overlay,'返回對話',self.queue_overlay.destroy).pack(pady=15)
        listing=ctk.CTkScrollableFrame(self.queue_overlay,fg_color=PANEL)
        listing.pack(fill='both',expand=True)
        for item in list(self.controller.pending):
            label(listing,item.text,16,wraplength=300,justify='left').pack(fill='x',padx=15,pady=8)
            button(listing,'取消',lambda ident=item.id:self.cancel_and_rebuild_queue(ident),height=30).pack(pady=5)

    def cancel_and_rebuild_queue(self,ident):
        self.cancel_message(ident);self.show_queue()

    def cancel_message(self,ident):
        self.controller.cancel_pending(ident);self.refresh()

    def on_activity(self,source):
        if not self.controller or not self.settings['user_activity_prompt']['enabled']: return
        # Also reject activity queued immediately before the board was opened.
        if self.board_visible: return
        c=self.controller
        if c.phase!=Phase.IDLE or c.mic_muted: return
        now=time.monotonic()
        if now-self.last_activity_prompt<15: return
        self.last_activity_prompt=now
        self.add_message(self.settings['user_activity_prompt']['text'])
        c.phase=Phase.LISTENING
        self.begin_capture_timeout()
        self.refresh()

    def _sync_activity_monitor(self):
        if self.input_monitor and self.controller:
            c=self.controller
            self.input_monitor.set_activity_paused(self.board_visible or c.phase!=Phase.IDLE or c.mic_muted)

    def notify(self,text):
        self.notice.configure(text=text)
        self.notice.grid()
        if self._notice_job: self.after_cancel(self._notice_job)
        self._notice_job=self.after(4500,self._hide_notice)

    def _hide_notice(self):
        self._notice_job=None
        if not self._is_closing(): self.notice.grid_remove()

    def _clear_board_view(self):
        self._board_source_image=None
        self.markdown.clear()
        if self.html_whiteboard_renderer:
            renderer=self.html_whiteboard_renderer
            self.html_whiteboard_renderer=None
            renderer.stop()
        for child in self.board_body.winfo_children(): child.destroy()

    def show_board(self,kind):
        if kind not in ('md','image','html'):
            raise ValueError('不支援的白板格式')
        if not self.settings['whiteboard']['enabled']:
            self.notify('白板已停用');return
        self.account_budget()
        if kind=='html' and (self.budget.remaining<=0 or self._budget_failed):
            self.notify('HTML 額度存檔失敗，請重啟' if self._budget_failed else '今日 HTML 額度已用完');return
        self._clear_board_view()
        self.board_kind=kind;self.board_visible=True
        self._sync_activity_monitor()
        self._budget_charge=False
        self._whiteboard_current_state={'content_type':'html' if kind=='html' else kind}
        self.board.grid(row=0,column=0,sticky='nsew',padx=8,pady=8)
        self.board.tkraise()
        self.restore_button.place_forget()
        self.board_title.configure(text={'md':'月亮的形狀','image':'圖片','html':'數字練習'}[kind])
        self.update_idletasks()
        if kind=='html':
            self.quota_row.grid()
            self.html_host=tk.Frame(self.board_body,bg=PANEL)
            self.html_host.pack(fill='both',expand=True)
            self.update_idletasks()
            try:
                self.html_whiteboard_renderer=NativeHtmlRenderer(self.runtime/'whiteboard',
                    duck_volume=self.settings['whiteboard']['html_audio_duck_volume'],ui_post=self._post_to_ui)
                self.html_whiteboard_renderer.set_ducked(self.controller.phase==Phase.SPEAKING)
                self.html_whiteboard_renderer.show(self.html_host.winfo_id(),NATIVE/'web_assets/game.html',
                    self.html_host.winfo_width(),self.html_host.winfo_height())
            except Exception as exc:
                self.board_visible=False
                self.notify(f'HTML 開啟失敗：{exc}')
                self.hide_board()
        else:
            self.quota_row.grid_remove()
            if kind=='md':
                # CTkMarkdown already owns a scrolling textbox. A surrounding
                # scrollable frame leaves its viewport at the default height.
                self.markdown.render(self.board_body,'# 月亮為什麼有不同形狀？\n\n月亮反射太陽光，我們看見被照亮的不同部分。\n\n## 觀察\n\n- 新月\n- 上弦月\n- 滿月\n- 下弦月\n\n用手電筒照球，從不同角度觀察亮面。')
            else:
                with Image.open(APP/'assets/states/layers/background.png') as source:
                    img=source.copy()
                self._board_source_image=img
                self.board_image=ctk.CTkImage(img,size=(100,100))
                ctk.CTkLabel(self.board_body,text='',image=self.board_image).pack(expand=True)
                self._resize_html_now()

    def hide_board(self):
        self.account_budget()
        self.board_visible=False
        self._sync_activity_monitor()
        self._budget_charge=False
        # Strong pause: unload HTML process, not merely hide a live game.
        # Demo game checkpoints on every action to its isolated Edge localStorage.
        if self.html_whiteboard_renderer:
            renderer=self.html_whiteboard_renderer
            self.html_whiteboard_renderer=None
            try:
                renderer.set_muted(True)
                renderer.set_keyboard_capture(False)
            finally:
                renderer.stop()
        self._whiteboard_current_state={}
        self.board.grid_remove()
        if self.board_kind:
            self.restore_button.place(x=18,rely=1,y=-18,anchor='sw')
            self.restore_button.lift()
        self.save_budget()

    def restore_board(self):
        if self.board_visible or not self.board_kind: return
        if self.board_kind=='html':
            self.show_board('html')
        else:
            # Retain the existing document/image and its reading position.
            self.board_visible=True
            self._whiteboard_current_state={'content_type':self.board_kind}
            self.board.grid();self.board.tkraise()
            self.restore_button.place_forget()
            self._sync_activity_monitor()

    def close_board(self):
        try:
            self.hide_board()
        finally:
            self.board_kind=None
            self.restore_button.place_forget()
            self._clear_board_view()

    def resize_html(self,event=None):
        if self._html_resize_job: self.after_cancel(self._html_resize_job)
        self._html_resize_job=self.after(80,self._resize_html_now)

    def _resize_html_now(self):
        self._html_resize_job=None
        if self.html_whiteboard_renderer and self.board_visible:
            self.html_whiteboard_renderer.resize(self.html_host.winfo_id(),self.html_host.winfo_width(),self.html_host.winfo_height())
        elif self.board_kind=='image' and self.board_visible and self._board_source_image:
            img=self._board_source_image
            scale=self.scene._get_widget_scaling()
            width=max(1,int(self.board_body.winfo_width()/scale)-20)
            height=max(1,int(self.board_body.winfo_height()/scale)-20)
            ratio=min(width/img.width,height/img.height)
            self.board_image.configure(size=(max(1,int(img.width*ratio)),max(1,int(img.height*ratio))))

    def account_budget(self):
        if not self.controller: return
        # Charge only after the embedded renderer has actually attached.
        rendering=bool(self.html_whiteboard_renderer and self.html_whiteboard_renderer.is_attached)
        active=self.board_kind=='html' and self.board_visible and rendering and self.state()!='iconic' and desktop_available()
        # A newly attached browser begins accounting at this observation, rather
        # than charging its startup delay. Hide/close settle before changing state.
        self.budget.tick(self._budget_charge and active)
        self._budget_charge=active

    def save_budget(self,force=True):
        if self._budget_failed: return False
        stamp=time.monotonic()
        if not force and stamp-self._budget_save_stamp<1: return True
        try:
            self.budget.save()
            self._budget_save_stamp=stamp
            return True
        except OSError:
            self._budget_failed=True
            # No recursive save attempts while closing a board after I/O failure.
            if self.board_kind=='html': self.close_board()
            self.notify('無法保存額度，HTML 已停用至重啟')
            return False

    def tick(self):
        self._tick_job=None
        if self._is_closing(): return
        if self.html_whiteboard_renderer:
            self.html_whiteboard_renderer.ensure_layout()
        self.account_budget()
        remaining=math.ceil(self.budget.remaining)
        self.quota_label.configure(text=f'{remaining//60:02}:{remaining%60:02}')
        self.quota_bar.set(self.budget.remaining/max(1,self.budget.limit))
        self.quota_bar.configure(progress_color=GOLD if self.budget.remaining<=self.budget.limit*.15 else GREEN)
        if self.board_kind=='html' and not remaining:
            self.close_board();self.notify('今日 HTML 額度已用完')
        if self.html_whiteboard_renderer and self.html_whiteboard_renderer.last_error:
            error=self.html_whiteboard_renderer.last_error
            self.close_board();self.notify(f'HTML：{error}')
        self.save_budget(force=False)
        self._sync_review_budget()
        self._tick_job=self.after(250,self.tick)

    def ten_seconds(self):
        self.budget.used=max(0,self.budget.limit-10)
        self.budget.save();self.show_board('html')

    def reset_budget(self):
        self.account_budget()
        self.budget.used=0
        if self.save_budget(): self.notify('Demo 額度已重設')
        self._sync_review_budget()

    def close(self):
        if self._is_closing(): return 'break'
        self._closing_event.set()
        def cleanup(name,action):
            try: action()
            except Exception as exc:
                self.cleanup_errors.append((name,type(exc).__name__))
        if self.controller:
            cleanup('turn service',self.service.cancel)
            cleanup('budget accounting',self.account_budget)
            cleanup('budget save',self.budget.save)
        for attr in ('_tick_job','_capture_job','_resize_job','_html_resize_job','_notice_job','_scroll_job','_turn_timeout_job','_fullscreen_resize_job','_startup_position_job'):
            job=getattr(self,attr,None)
            if job:
                cleanup(attr,lambda job=job:self.after_cancel(job))
                setattr(self,attr,None)
        if self.input_monitor: cleanup('input monitor',self.input_monitor.stop)
        if self.html_whiteboard_renderer: cleanup('HTML renderer',self.html_whiteboard_renderer.stop)
        if self.animator: cleanup('animation',self.animator.destroy)
        if hasattr(self,'markdown'): cleanup('Markdown callbacks',self.markdown.clear)
        cleanup('keyboard guard',self._remove_fullscreen_keyboard_guard)
        cleanup('screen guard',lambda:self._set_screensaver_block(False))
        cleanup('display awake',lambda:self._set_display_awake(False))
        cleanup('UI event queue',self._cancel_ui_event_poll)
        # CTk/Markdown also schedule jobs without exposing their IDs. This root
        # owns the Tcl interpreter, so cancel its remaining jobs before destroy.
        cleanup('remaining Tk timers',self._cancel_all_tk_jobs)
        cleanup('Tk widgets',self.destroy)
        return 'break'

    def _cancel_all_tk_jobs(self):
        for job in self.tk.call('after','info'):
            # Do not delete another widget's registered Python command through
            # this root: its own destroy() must remove that command exactly once.
            self.tk.call('after','cancel',job)
