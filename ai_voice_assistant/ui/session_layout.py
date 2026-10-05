"""Sophia's warm session layout, independent of backend execution."""
import customtkinter as ctk

from ui.animation_controller import AnimationController
from ui.components import FONT, icon_image
from ui.session_theme import (
    CANVAS, SURFACE, INK, MUTED, LINE, CHROME, CHROME_SOFT, PRIMARY,
    WARM_SOFT, SAGE, SAGE_SOFT,
    SessionIconButton as IconButton, card, identity_image, label,
)


def build_session_layout(self):
    cfg = self.session
    self.shell = ctk.CTkFrame(self, fg_color=CANVAS, corner_radius=0)
    self.shell.pack(fill='both', expand=True)
    self.shell.grid_columnconfigure(0, weight=1)
    self.shell.grid_columnconfigure(1, weight=0, minsize=380)
    self.shell.grid_rowconfigure(1, weight=1)

    # The original header occupied 66 logical pixels. This one uses 64.
    header = ctk.CTkFrame(self.shell, fg_color=CHROME, corner_radius=0, height=64)
    header.grid(row=0, column=0, columnspan=2, sticky='ew')
    header.grid_propagate(False)
    header.grid_rowconfigure(0, weight=1)
    header.grid_columnconfigure(1, weight=1)
    brand = ctk.CTkFrame(header, width=42, height=42, corner_radius=13,
                        fg_color=CHROME_SOFT, border_width=1, border_color='#75605E')
    brand.grid(row=0, column=0, padx=(20, 12), pady=10)
    brand.grid_propagate(False)
    ctk.CTkLabel(brand, text='', image=identity_image(), width=30, height=30).place(
        relx=.5, rely=.5, anchor='center')
    label(header, 'Sophia  愛管家', 21, weight='bold', color='#FFF8EF', height=27).grid(
        row=0, column=1, sticky='w')
    # Bound long CLI model names so they cannot displace the brand or split.
    model_card = ctk.CTkFrame(header, fg_color=CHROME_SOFT, corner_radius=11,
                            border_width=1, border_color='#705D63', height=36)
    model_card.place(relx=1, rely=.5, relwidth=.38, x=-20, anchor='e')
    model_card.grid_propagate(False)
    model_card.grid_columnconfigure(1, weight=1)
    ctk.CTkLabel(model_card, text='', image=icon_image('backend', color='#D8C1A0', size=19),
                 width=20, height=24).grid(row=0, column=0, padx=(12, 10), pady=6)
    backend = cfg.backend.replace('_cli', '').replace('_', ' ').title()
    label(model_card, f'{backend}  /  {cfg.model}', 12, color='#FFF8EF', height=24,
          anchor='w', width=1).grid(row=0, column=1, sticky='ew', padx=(0, 12), pady=6)
    ctk.CTkFrame(header, height=2, corner_radius=0, fg_color='#C6A483').place(
        relx=0, rely=1, relwidth=1, y=-2, anchor='sw')

    self.stage = card(self.shell)
    self.stage.grid(row=1, column=0, sticky='nsew', padx=(12, 8), pady=10)
    self.stage.grid_rowconfigure(0, weight=1)
    self.stage.grid_columnconfigure(0, weight=1)
    self.scene = ctk.CTkFrame(self.stage, fg_color=SURFACE, corner_radius=0)
    self.scene.grid(row=0, column=0, sticky='nsew', padx=8, pady=8)
    self.scene_label = ctk.CTkLabel(self.scene, text='')
    self.scene_label.place(relx=.5, rely=.5, anchor='center')
    self.animator = AnimationController(self.scene_label,
        interval_ms=int(self.settings['ui']['animation_interval_ms']),
        foreground_y_offset_px=int(self.settings['ui']['animation_foreground_y_offset_px']))
    self.scene.bind('<Configure>', self.schedule_resize)
    self.restore_button = IconButton(self.scene, 'board', self.restore_board, tip='展開白板',
        width=52, height=52, fg_color=WARM_SOFT, border_color='#D4B994', hover_color='#EEE0CF')

    self.board = ctk.CTkFrame(self.stage, fg_color=SURFACE, corner_radius=12)
    self.board.grid_rowconfigure(2, weight=1)
    self.board.grid_columnconfigure(0, weight=1)
    toolbar = ctk.CTkFrame(self.board, fg_color=WARM_SOFT, corner_radius=12)
    self.board_toolbar = toolbar
    toolbar.grid(row=0, column=0, sticky='ew', padx=12, pady=8)
    # Actions precede the expanding title so controls stay visible.
    IconButton(toolbar, 'close', self.close_board, tip='關閉白板').pack(side='right', padx=(2, 4))
    IconButton(toolbar, 'hide', self.hide_board, tip='隱藏白板').pack(side='right')
    board_mark = ctk.CTkFrame(toolbar, width=32, height=32, corner_radius=10, fg_color='#EEDBC2')
    board_mark.pack(side='left', padx=(9, 9), pady=6)
    board_mark.pack_propagate(False)
    ctk.CTkLabel(board_mark, text='', width=22, height=22,
        image=icon_image('board', color='#8B6942', size=21)).place(relx=.5, rely=.5, anchor='center')
    self.board_title = label(toolbar, '白板', 17, weight='bold', anchor='w', width=1)
    self.board_title.pack(side='left', fill='x', expand=True, padx=(0, 8))
    self.quota_row = ctk.CTkFrame(self.board, fg_color='#F4F0EA', corner_radius=9)
    self.quota_row.grid(row=1, column=0, sticky='ew', padx=12, pady=(0, 8))
    self.quota_bar = ctk.CTkProgressBar(self.quota_row, progress_color=PRIMARY,
        fg_color=LINE, height=5, corner_radius=3)
    self.quota_bar.pack(side='left', fill='x', expand=True, padx=12, pady=12)
    self.quota_label = label(self.quota_row, '30:00', 13, color=MUTED)
    self.quota_label.pack(side='right', padx=12)
    self.board_body = ctk.CTkFrame(self.board, fg_color=SURFACE, corner_radius=0)
    self.board_body.grid_rowconfigure(0, weight=1)
    self.board_body.grid_columnconfigure(0, weight=1)
    self.board_body.grid(row=2, column=0, sticky='nsew', padx=12, pady=(0, 12))
    self.board_body.bind('<Configure>', self.resize_html)

    self.chat = card(self.shell, width=400)
    self.chat.grid(row=1, column=1, sticky='nsew', padx=(6, 12), pady=10)
    self.chat.grid_propagate(False)
    self.chat.grid_columnconfigure(0, weight=1)
    self.chat.grid_rowconfigure(1, weight=1)
    chat_header = ctk.CTkFrame(self.chat, fg_color='transparent', corner_radius=0)
    self.chat_header_holder = chat_header
    chat_header.grid(row=0, column=0, sticky='ew', padx=14, pady=(10, 7))
    chat_mark = ctk.CTkFrame(chat_header, width=34, height=34, corner_radius=12,
                           fg_color=WARM_SOFT, border_width=1, border_color=LINE)
    chat_mark.pack(side='left', padx=(0, 10), pady=7)
    chat_mark.pack_propagate(False)
    ctk.CTkLabel(chat_mark, text='', width=22, height=22,
        image=icon_image('chat', color='#956E60', size=21)).place(relx=.5, rely=.5, anchor='center')
    label(chat_header, '對話', 19, weight='bold', height=25).pack(side='left')
    self.phase_label = label(chat_header, '●  待機', 12, color=SAGE,
                            fg_color=SAGE_SOFT, corner_radius=10, height=28, width=70)
    self.phase_label.pack(side='right', padx=(4, 0))
    ctk.CTkFrame(self.chat, fg_color=LINE, height=1, corner_radius=0).grid(
        row=0, column=0, sticky='sew', padx=14)
    self.messages = ctk.CTkScrollableFrame(self.chat, fg_color=SURFACE, scrollbar_fg_color=SURFACE,
        scrollbar_button_color='#DACDC2', scrollbar_button_hover_color='#BDA593')
    self.messages.grid(row=1, column=0, sticky='nsew', padx=8, pady=(4, 8))
    self.empty_state = ctk.CTkFrame(self.messages, fg_color='transparent')
    self.empty_state.pack(fill='x', pady=48)
    empty_mark = ctk.CTkFrame(self.empty_state, width=64, height=64, corner_radius=22,
                            fg_color=WARM_SOFT, border_width=1, border_color=LINE)
    empty_mark.pack(pady=(0, 16))
    empty_mark.pack_propagate(False)
    ctk.CTkLabel(empty_mark, text='', width=38, height=38,
        image=icon_image('chat', color='#A17D63', size=32)).place(relx=.5, rely=.5, anchor='center')
    label(self.empty_state, '尚無對話', 14, color=MUTED).pack()

    self.queue_frame = ctk.CTkFrame(self.chat, fg_color=WARM_SOFT, corner_radius=12,
                                  border_width=1, border_color='#E6D3BD')
    self.queue_frame.grid(row=2, column=0, sticky='ew', padx=14, pady=7)
    self.queue_frame.grid_remove()
    self._queue_signature = None
    composer = ctk.CTkFrame(self.chat, fg_color='#F8F5F0', corner_radius=16,
                          border_width=1, border_color='#DCCFC2')
    composer.grid(row=3, column=0, sticky='ew', padx=14, pady=(6, 14))
    self.input = ctk.CTkTextbox(composer, height=100, font=(FONT, 19),
        fg_color='#F8F5F0', text_color=INK, border_width=0, corner_radius=12,
        scrollbar_button_color='#CCBCAD', scrollbar_button_hover_color='#AF9582')
    self.input.pack(fill='x', padx=12, pady=(12, 0))
    self.input.bind('<Button-1>', self._focus_composer)
    self.input.bind('<Control-Return>', lambda event: self.send())

    def focus_in(_):
        self._composer_focused = True
        self._release_whiteboard_keyboard_capture()
        composer.configure(border_color=PRIMARY)

    def focus_out(_):
        self._composer_focused = False
        composer.configure(border_color='#DCCFC2')

    self.input.bind('<FocusIn>', focus_in)
    self.input.bind('<FocusOut>', focus_out)
    ctk.CTkFrame(composer, fg_color=LINE, height=1, corner_radius=0).pack(
        fill='x', padx=14, pady=(9, 0))
    controls = ctk.CTkFrame(composer, fg_color='transparent')
    controls.pack(fill='x', padx=12, pady=(10, 12))
    self.mic = IconButton(controls, 'mic', self.toggle_mic)
    self.mic.pack(side='left', padx=(0, 8))
    self.speaker = IconButton(controls, 'speaker', self.toggle_speaker)
    self.speaker.pack(side='left')
    self.send_button = IconButton(controls, 'send', self.send, tip='送出 · Ctrl+Enter')
    self.send_button.pack(side='right')
    self.notice = label(self.chat, '', 11, color=MUTED, wraplength=345, anchor='w')
    self.notice.grid(row=4, column=0, sticky='ew', padx=18, pady=(0, 10))
    self.notice.grid_remove()
