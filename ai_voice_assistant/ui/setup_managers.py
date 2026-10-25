"""Explicit local file and speaker enrollment actions for the startup window."""
import asyncio
from copy import deepcopy
import os
from pathlib import Path
import re
import tempfile
from tkinter import filedialog, messagebox
from uuid import uuid4

import customtkinter as ctk
import numpy as np

from ui.audio_preview import AudioPreviewController, record_audio, read_audio
from ui.components import label, button, OwnedComboBox, MUTED, NAV, FONT
from ui.settings_fields import TextValue
from utils.gemini_audio import wav_bytes
from utils.startup_diagnostics import app_path, safe_error


def atomic_write(path, data):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    handle,temporary=tempfile.mkstemp(dir=path.parent,prefix='.setup-',suffix='.tmp')
    try:
        with os.fdopen(handle,'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def show_guide(parent,path,links=()):
    """Read-only in-app help, including on machines without a Markdown file association."""
    dialog=ctk.CTkToplevel(parent)
    dialog.title('設定與排除問題')
    dialog.geometry('740x620')
    dialog.minsize(480,400)
    dialog.transient(parent.winfo_toplevel())
    text=ctk.CTkTextbox(dialog,wrap='word',font=(FONT,14))
    text.pack(fill='both',expand=True,padx=18,pady=15)
    try: content=Path(path).read_text(encoding='utf-8')
    except OSError: content='找不到說明文件；請由專案 docs/startup_setup_guide.md 查看設定方式。'
    text.insert('1.0',content)
    text.configure(state='disabled')
    import webbrowser
    for title,url in links:
        button(dialog,title,lambda url=url:webbrowser.open(url),height=34).pack(fill='x',padx=18,pady=4)
    button(dialog,'返回設定',dialog.destroy,height=36).pack(fill='x',padx=18,pady=(6,15))
    dialog.bind('<Escape>',lambda _:dialog.destroy())
    dialog.grab_set()
    return dialog


def validate_keywords(text, tokens_file=None):
    lines=[line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    if not lines: raise ValueError('至少需要一個喚醒詞。')
    if len(lines)>100: raise ValueError('最多 100 個喚醒詞。')
    tokens=None
    if tokens_file and Path(tokens_file).is_file():
        tokens={line.split()[0] for line in Path(tokens_file).read_text(encoding='utf-8').splitlines() if line.split()}
    names=set()
    for number,line in enumerate(lines,1):
        match=re.fullmatch(r'(.+?)\s+:(\d+(?:\.\d+)?)\s+#(\d+(?:\.\d+)?)\s+@([^\s@]+)',line)
        if not match: raise ValueError(f'第 {number} 行：請依「發音 tokens :加權 #門檻 @名稱」格式填寫。')
        pronunciation,boost,threshold,name=match.groups()
        if not 0<float(boost)<=10 or not 0<float(threshold)<1: raise ValueError(f'第 {number} 行：加權需大於 0 且不超過 10，門檻需介於 0–1。')
        if name in names: raise ValueError(f'第 {number} 行：名稱重複。')
        names.add(name)
        if tokens is not None and any(token not in tokens for token in pronunciation.split()):
            raise ValueError(f'第 {number} 行：發音含模型 tokens.txt 不支援的 token。')
    return text.rstrip('\r\n')+'\n'


def profile_directory(root,name):
    root=Path(root).resolve()
    if not name or name!=name.strip() or len(name)>60 or re.search(r'[<>:"/\\|?*\x00-\x1f]',name) or name.endswith(('.', ' ')):
        raise ValueError('名稱請填 1–60 字，不可包含路徑或 Windows 檔名特殊字元。')
    if name.upper().split('.')[0] in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        raise ValueError('請使用其他名稱。')
    folder=(root/name).resolve()
    if folder.parent!=root: raise ValueError('聲紋資料夾必須位於指定的 profile 目錄中。')
    return folder


def save_profile_sample(root,name,audio,sample_rate,min_seconds):
    folder=profile_directory(root,name)
    if len(audio)/sample_rate < min_seconds: raise ValueError(f'樣本至少需要 {min_seconds:g} 秒。')
    if not np.isfinite(audio).all() or float(np.sqrt(np.mean(audio**2))) < .0001:
        raise ValueError('樣本沒有足夠的人聲音量，請靠近麥克風重新錄音。')
    target=folder/f'sample_{uuid4().hex}.wav'
    atomic_write(target,wav_bytes(audio,sample_rate))
    return target


class LocalTextEditor(ctk.CTkToplevel):
    def __init__(self,parent,title,path,*,validator=None):
        super().__init__(parent)
        self.title(title)
        self.geometry('720x580')
        self.minsize(480,400)
        self.transient(parent.winfo_toplevel())
        self.path=Path(path)
        self.validator=validator
        label(self,str(self.path),12,color=MUTED,wraplength=440,anchor='w').pack(fill='x',padx=20,pady=12)
        hint=('每行格式：發音 tokens :加權 #門檻 @名稱\n例如：ài g uǎn j iā :3.0 #0.15 @愛管家\n發音需符合喚醒模型 tokens；按「驗證並儲存」才會寫入。' if validator else
            '角色指令／記憶只在按「儲存檔案」後寫入本機；啟動設定的取消不會回復此檔案。')
        label(self,hint,13,color=MUTED,wraplength=440,anchor='w').pack(fill='x',padx=20,pady=6)
        self.text=ctk.CTkTextbox(self,font=(FONT,14),wrap='word')
        self.text.pack(fill='both',expand=True,padx=20,pady=8)
        self.value=TextValue(self.text)
        self.status=label(self,'',12,color=MUTED,wraplength=440,anchor='w')
        self.status.pack(fill='x',padx=20,pady=4)
        self.initial=''
        self.read_failed=False
        try:
            self.initial=self.path.read_text(encoding='utf-8') if self.path.exists() else ''
            self.value.set(self.initial)
        except Exception as exc:
            self.read_failed=True
            self.status.configure(text='無法讀取檔案：'+type(exc).__name__)
            self.text.configure(state='disabled')
        button(self,'驗證並儲存' if validator else '儲存檔案',self.save,primary=True).pack(anchor='e',padx=20,pady=12)
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.bind('<Escape>',lambda _:self.close())

    def save(self):
        try:
            if self.read_failed: raise ValueError('檔案未成功載入；請關閉後重新開啟，不可覆寫原檔。')
            value=self.value.get()
            if self.validator: value=self.validator(value)
            atomic_write(self.path,value.encode('utf-8'))
            self.initial=value
            self.value.set(value)
            self.status.configure(text='已儲存至本機。')
        except Exception as exc:
            self.status.configure(text=str(exc) if isinstance(exc,ValueError) else '無法寫入檔案，原有內容保持不變。')

    def close(self):
        if self.value.get()!=self.initial and not messagebox.askyesno('尚未儲存','放棄此檔案尚未儲存的修改？',parent=self): return False
        self.destroy()
        return True


class VoiceProfilesEditor(ctk.CTkToplevel):
    def __init__(self,parent,settings):
        super().__init__(parent)
        self.title('家人聲紋')
        self.geometry('660x580')
        self.minsize(480,440)
        self.transient(parent.winfo_toplevel())
        self.settings=deepcopy(settings)
        self.folder=app_path(settings['speaker_recognition']['profile_dir'])
        self.controller=AudioPreviewController()
        self.token=None
        self.job=None
        self.closing=False
        label(self,'新增姓名，再匯入音檔或錄音 5 秒。樣本只保存在本機，立即生效。',14,wraplength=430,anchor='w').pack(fill='x',padx=20,pady=15)
        label(self,str(self.folder),12,color=MUTED,wraplength=430,anchor='w').pack(fill='x',padx=20)
        self.name=ctk.StringVar(value='')
        self.name_menu=OwnedComboBox(self,variable=self.name,values=[],state='normal')
        self.name_menu.pack(fill='x',padx=20,pady=10)
        button(self,'匯入音檔',self.import_sample).pack(fill='x',padx=20,pady=4)
        button(self,'錄音 5 秒並新增',lambda:self.start(None)).pack(fill='x',padx=20,pady=4)
        button(self,'停止錄音',self.controller.cancel).pack(fill='x',padx=20,pady=4)
        self.status=label(self,'',12,color=MUTED,wraplength=430,anchor='w')
        self.status.pack(fill='x',padx=20,pady=8)
        self.listing=ctk.CTkTextbox(self,height=130,font=(FONT,13),fg_color=NAV)
        self.listing.pack(fill='both',expand=True,padx=20,pady=10)
        self.refresh()
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.bind('<Escape>',lambda _:self.close())

    def refresh(self):
        names=[]
        lines=[]
        if self.folder.is_dir():
            for child in sorted(self.folder.iterdir()):
                if child.is_dir() and list(child.glob('*.wav')):
                    names.append(child.name)
                    lines.append(f'{child.name}：{len(list(child.glob("*.wav")))} 個 WAV 樣本')
        self.name_menu.configure(values=names)
        self.listing.configure(state='normal')
        self.listing.delete('1.0','end')
        self.listing.insert('1.0','\n'.join(lines) or '尚無樣本；請新增一位家人。')
        self.listing.configure(state='disabled')

    def import_sample(self):
        path=filedialog.askopenfilename(parent=self,title='匯入聲紋樣本',filetypes=[('Audio','*.wav *.mp3 *.flac *.m4a *.ogg')])
        if path: self.start(path)

    def start(self,path):
        if self.controller.busy:
            self.status.configure(text='上一筆操作尚在結束，請稍候。')
            return
        name=self.name.get()
        try: profile_directory(self.folder,name)
        except ValueError as exc:
            self.status.configure(text=str(exc))
            return
        def work(cancel,owner):
            sr=self.settings['audio']['input_sample_rate']
            audio=read_audio(path,sr,120) if path else record_audio(self.settings,cancel,owner)
            if cancel.is_set(): raise asyncio.CancelledError
            target=save_profile_sample(self.folder,name,audio,sr,self.settings['speaker_recognition']['min_duration_seconds'])
            return {'message':f'已新增 {name} 的樣本：{target.name}'}
        self.token=self.controller.start(work)
        self.status.configure(text='正在處理；可隨時停止。')
        self.job=self.after(100,self.poll)

    def poll(self):
        self.job=None
        while not self.controller.events.empty():
            token,status,result=self.controller.events.get()
            if token!=self.token: continue
            self.status.configure(text=result['message'] if status in ('ok','progress') else
                '已停止。' if status=='cancelled' else '無法新增樣本：'+safe_error(ValueError(result),self.settings))
            if status=='ok': self.refresh()
        if self.controller.busy:
            self.job=self.after(100,self.poll)
        elif self.closing:
            self.destroy()

    def close(self):
        self.controller.cancel()
        if self.controller.busy:
            self.closing=True
            self.status.configure(text='正在停止錄音…')
            if self.job is None: self.job=self.after(100,self.poll)
        else:
            if self.job: self.after_cancel(self.job)
            self.destroy()
