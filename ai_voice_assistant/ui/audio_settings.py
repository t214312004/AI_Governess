"""Startup audio selection and previews, using the same engines as production."""
from copy import deepcopy
import json
from tkinter import filedialog

import customtkinter as ctk

from core.session_settings import assign, parse_field
from ui.audio_preview import google_catalog, stt_preview, tts_preview
from ui.components import INK, MUTED, NAV, FONT, OwnedComboBox, label, button
from ui.settings_fields import SettingsField
from ui.google_credentials import GoogleCredentialsEditor
from utils.audio_devices import list_audio_devices, check_audio_devices
from utils.startup_diagnostics import bluemagpie_readiness, safe_error, validate_local_selection
from utils.gemini_settings import DEFAULT_VOICES, STT_DEFAULTS, TTS_DEFAULTS

OWNED_PATHS = {
    ('whisper', 'backend'), ('tts', 'backend'), ('pipeline_v2_5', 'streaming_tts'),
    ('tts', 'voice'), ('tts', 'rate'), ('tts', 'volume'),
    *(('whisper', 'gemini', key) for key in ('model', 'thinking_level', 'transcription_prompt', 'vocabulary_hints')),
    *(('tts', 'gemini', key) for key in ('model', 'voice', 'style', 'volume_gain')),
    *(('whisper',key) for key in ('model_size','device','compute_type','language','initial_prompt')),
    *(('whisper','groq',key) for key in ('api_key','api_key_env','model')),
    *(('tts','bluemagpie',key) for key in ('enabled','worker_python','worker_script','model_dir','device','speaker_centroid_path','prompt_text','prompt_wav_path')),
    ('audio','input_device'),('audio','output_device'),
}


class TextValue:
    def __init__(self, widget):
        self.widget = widget

    def get(self):
        return self.widget.get('1.0', 'end-1c')

    def set(self, value):
        self.widget.delete('1.0', 'end')
        self.widget.insert('1.0', value)


class DeviceValue:
    def __init__(self,picker): self.picker=picker
    def get(self): return json.dumps(self.picker.choices.get(self.picker.variable.get(),self.picker.saved),ensure_ascii=False)
    def set(self,value):
        self.picker.saved=json.loads(value)
        self.picker.refresh(initial=True)


class DevicePicker(ctk.CTkFrame):
    def __init__(self,parent,kind,saved,changed):
        super().__init__(parent,fg_color='transparent',height=1)
        self.kind,self.saved,self.changed=kind,saved,changed
        self.variable=ctk.StringVar(value='Windows 預設裝置')
        self.choices={'Windows 預設裝置':None}
        self.menu=OwnedComboBox(self,variable=self.variable,values=list(self.choices),state='readonly',command=lambda _:self.changed())
        self.menu.pack(fill='x')
        button(self,'重新偵測裝置',self.refresh,width=130,height=32).pack(anchor='w',pady=4)
        self.status=label(self,'',12,color=MUTED,wraplength=300,anchor='w')
        self.status.pack(fill='x')
        self.refresh(initial=True)

    def refresh(self,initial=False):
        selected=self.saved if initial else self.choices.get(self.variable.get(),self.saved)
        self.choices={'Windows 預設裝置':None}
        try:
            self.choices.update(dict(list_audio_devices(self.kind)))
            self.status.configure(text='重新插拔裝置後可按「重新偵測裝置」。')
        except Exception:
            self.status.configure(text='目前無法取得裝置清單；可稍後重新偵測。')
        name=next((name for name,value in self.choices.items() if value==selected),None)
        if name is None:
            name='已離線：'+str(selected.get('name','先前裝置')) if isinstance(selected,dict) else '先前裝置設定無效，請重新選擇'
            self.choices[name]=selected
        self.saved=selected
        self.menu.configure(values=list(self.choices))
        self.variable.set(name)


class AudioSettingsEditor(ctk.CTkFrame):
    def __init__(self, parent, settings, controller, snapshot, changed, save_google_key=None, google_changed=None, test_states=None, show_inactive=False):
        super().__init__(parent, fg_color='transparent')
        self.settings, self.controller = settings, controller
        self.snapshot, self.changed = snapshot, changed
        self.editors, self.values = [], {}
        self.pending_defaults = {}
        self.job_token = None
        self.poll_job = None
        self.dead = False
        self.field_controls={}
        self.test_states=test_states if test_states is not None else {}
        self.input_enabled=settings.get('interaction',{}).get('voice_input',True)
        self.output_enabled=settings.get('interaction',{}).get('voice_output',True)
        self.show_inactive=show_inactive
        self.input_frame=ctk.CTkFrame(self,fg_color='transparent',height=1)
        self.input_frame.pack(fill='x')
        self._device(self.input_frame,'麥克風','input')
        self._field(self.input_frame, '語音辨識服務', ('whisper', 'backend'), ['local', 'groq', 'gemini'], readonly=True)
        label(self.input_frame,'local 在本機辨識；Groq／Gemini 會傳送音訊至雲端並需要 API key。',12,color=MUTED,wraplength=300,anchor='w').pack(fill='x',pady=6)
        self.local_details=ctk.CTkFrame(self.input_frame,fg_color='transparent',height=1)
        self.local_details.pack(fill='x')
        for key,title in (('model_size','Whisper 模型'),('device','運算裝置'),('compute_type','運算精度'),('language','辨識語言'),('initial_prompt','辨識提示')):
            self._field(self.local_details,title,('whisper',key))
        self.groq_details=ctk.CTkFrame(self.input_frame,fg_color='transparent',height=1)
        self.groq_details.pack(fill='x')
        self._field(self.groq_details,'Groq API key（留白可使用環境變數）',('whisper','groq','api_key'))
        self._field(self.groq_details,'環境變數名稱',('whisper','groq','api_key_env'))
        self.groq_source=label(self.groq_details,'',12,color=MUTED,wraplength=300,anchor='w')
        self.groq_source.pack(fill='x')
        self._field(self.groq_details,'Groq 辨識模型',('whisper','groq','model'),['whisper-large-v3','whisper-large-v3-turbo'])
        self.google_details=ctk.CTkFrame(self,fg_color='transparent',height=1)
        self.google_details.pack(fill='x',before=self.input_frame)
        label(self.google_details,'Google API key（Gemini 共用）',15,weight='bold',anchor='w').pack(fill='x',pady=8)
        GoogleCredentialsEditor(self.google_details,settings,save_google_key,google_changed or (lambda _:None)).pack(fill='x')
        self.stt_details = ctk.CTkFrame(self.input_frame, fg_color='transparent',height=1)
        self.stt_details.pack(fill='x')
        self.stt_model_menu = self._field(self.stt_details, 'Gemini STT 模型', ('whisper', 'gemini', 'model'), ['gemini-3.8-flash'])
        self._field(self.stt_details, 'STT thinking', ('whisper', 'gemini', 'thinking_level'), ['low', 'medium', 'high'], readonly=True)
        self._field(self.stt_details, '轉錄指示', ('whisper', 'gemini', 'transcription_prompt'), multiline=True)
        label(self.stt_details, 'Gemini 的辨識語言由轉錄指示設定；Whisper 的 language／initial_prompt 不套用。',
            12, color=MUTED, wraplength=300, anchor='w').pack(fill='x', pady=(6, 0))
        self._field(self.stt_details, '詞彙提示（逐項新增）', ('whisper', 'gemini', 'vocabulary_hints'))
        button(self.stt_details, '還原 Gemini 辨識設定', lambda: self.restore('stt')).pack(anchor='w', pady=10)
        self.output_frame=ctk.CTkFrame(self,fg_color='transparent',height=1)
        self.output_frame.pack(fill='x',pady=(16,0))
        self._device(self.output_frame,'喇叭／耳機','output')
        self._field(self.output_frame, '語音輸出服務', ('tts', 'backend'), ['edge', 'bluemagpie', 'gemini'], readonly=True)
        label(self.output_frame,'Edge／Gemini 使用雲端合成；BlueMagpie 在本機合成，需要額外環境。',12,color=MUTED,wraplength=300,anchor='w').pack(fill='x',pady=6)
        self.tts_details = ctk.CTkFrame(self.output_frame, fg_color='transparent',height=1)
        self.tts_details.pack(fill='x')
        self.tts_model_menu = self._field(self.tts_details, 'Gemini TTS 模型', ('tts', 'gemini', 'model'),
            ['gemini-3.8-flash-tts', 'gemini-3.8-flash-lite-tts'])
        self.voice_menu = self._field(self.tts_details, 'Gemini 音色（也可輸入 voice ID）', ('tts', 'gemini', 'voice'), list(DEFAULT_VOICES))
        self.voice_choices = {voice: voice for voice in DEFAULT_VOICES}
        self.voice_menu.configure(command=self._voice_selected)
        label(self.tts_details, '預設音色為 Leda；按「更新 Google 音色」查詢並載入其他音色。',
            12, color=MUTED, wraplength=300, anchor='w').pack(fill='x', pady=(6, 0))
        self.voice_search = ctk.StringVar(value='')
        ctk.CTkEntry(self.tts_details, textvariable=self.voice_search,
            placeholder_text='搜尋音色名稱或語言（例如 zh、Taiwan）', height=38).pack(fill='x', pady=(6, 0))
        self.voice_search.trace_add('write', lambda *_: self._filter_voices())
        self._field(self.tts_details, '語氣、口音與節奏', ('tts', 'gemini', 'style'), multiline=True)
        self._field(self.tts_details, '播放音量倍率（0–2）', ('tts', 'gemini', 'volume_gain'))
        button(self.tts_details, '還原 Gemini 語音設定', lambda: self.restore('tts')).pack(anchor='w', pady=10)
        self.edge_details = ctk.CTkFrame(self.output_frame, fg_color='transparent',height=1)
        self.edge_details.pack(fill='x')
        self._field(self.edge_details, 'Edge 音色', ('tts', 'voice'),
            ['zh-TW-HsiaoChenNeural', 'zh-TW-HsiaoYuNeural', 'zh-TW-YunJheNeural'])
        self._percent_slider(self.edge_details,'Edge 語速',('tts','rate'),-30,30)
        self._percent_slider(self.edge_details,'Edge 音量（100% 為原音量）',('tts','volume'),0,200,offset=100)
        self.blue_details=ctk.CTkFrame(self.output_frame,fg_color='transparent',height=1)
        self.blue_details.pack(fill='x')
        self.blue_status=label(self.blue_details,'',12,color=MUTED,wraplength=300,anchor='w')
        self.blue_status.pack(fill='x',pady=6)
        button(self.blue_details,'開啟 BlueMagpie 設定指南',self.open_blue_guide,height=34).pack(fill='x')
        for key,title in (('worker_python','Worker Python'),('worker_script','Worker 腳本'),('model_dir','模型資料夾'),('device','運算裝置'),
                ('speaker_centroid_path','聲音特徵檔（選用）'),('prompt_wav_path','參考音檔（選用）'),('prompt_text','參考音檔逐字稿')):
            self._field(self.blue_details,title,('tts','bluemagpie',key))
        self._field(self.output_frame, '串流 TTS', ('pipeline_v2_5', 'streaming_tts'), boolean=True)
        label(self, 'timeout、重試、人聲門檻、格式與分段字數可在「進階設定」調整。',
            12, color=MUTED, wraplength=300, anchor='w').pack(fill='x', pady=12)
        self.stt_test_frame=ctk.CTkFrame(self,fg_color='transparent',height=1)
        self.stt_test_frame.pack(fill='x')
        row = ctk.CTkFrame(self.stt_test_frame, fg_color='transparent')
        row.pack(fill='x', pady=(8, 0))
        button(row, '選擇音檔辨識', self.test_file, width=150).pack(side='left', padx=(0, 8))
        button(row, '錄音 5 秒並辨識', lambda: self.test_stt(None), width=155).pack(side='left')
        self.tts_test_frame=ctk.CTkFrame(self,fg_color='transparent',height=1)
        self.tts_test_frame.pack(fill='x')
        label(self.tts_test_frame, '試聽文字', 13, color=MUTED, anchor='w').pack(fill='x', pady=(16, 5))
        self.preview_text = ctk.CTkEntry(self.tts_test_frame, height=42, placeholder_text='輸入想聽的文字')
        self.preview_text.insert(0, '你好，我是愛管家。今天有什麼需要我幫忙的嗎？')
        self.preview_text.pack(fill='x')
        row = ctk.CTkFrame(self.tts_test_frame, fg_color='transparent')
        row.pack(fill='x', pady=10)
        button(row, '試聽', self.test_tts, width=100).pack(side='left', padx=(0, 8))
        button(row, '停止測試／試聽', self.stop, width=155).pack(side='left')
        self.google_test_frame=ctk.CTkFrame(self,fg_color='transparent',height=1)
        self.google_test_frame.pack(fill='x')
        row = ctk.CTkFrame(self.google_test_frame, fg_color='transparent')
        row.pack(fill='x', pady=5)
        button(row, 'Google 連線與模型', lambda: self.catalog('models'), width=165).pack(fill='x', pady=(0, 8))
        button(row, '更新 Google 音色', lambda: self.catalog('voices'), width=165).pack(fill='x')
        self.meter=ctk.CTkProgressBar(self,height=8)
        self.meter.set(0)
        self.meter.pack(fill='x',pady=6)
        self.device_test_button=button(self,'檢查所選裝置',self.test_devices,height=34)
        self.device_test_button.pack(fill='x',pady=6)
        if not self.input_enabled and not self.output_enabled: self.device_test_button.configure(state='disabled')
        label(self, '辨識與試聽使用目前草稿；Google key 另按儲存立即生效。啟動時也會檢查連線。',
            12, color=MUTED, wraplength=300, anchor='w').pack(fill='x', pady=10)
        self.status = label(self, '', 12, color=MUTED, wraplength=300, anchor='w')
        self.status.pack(fill='x')
        self.result = ctk.CTkTextbox(self, height=110, fg_color=NAV, text_color=INK, font=(FONT, 14))
        self.result.pack(fill='x', pady=(8, 0))
        self.result.configure(state='disabled')
        self._pack_orders={owner:tuple((w,w.pack_info()) for w in owner.pack_slaves())
            for owner in (self,self.input_frame,self.output_frame)}
        self.refresh_sections()

    def _field(self, parent, title, path, options=None, *, multiline=False, boolean=False, readonly=False):
        original = self.settings
        for key in path:
            original = original[key]
        field=SettingsField(parent,path,original,title,changed=self.invalidate,options=options,
            readonly=True if readonly else (False if options else None))
        field.pack(fill='x')
        widget,variable=field.widget,field.variable
        self.field_controls[path]=field
        self.editors.append((path, variable, original))
        self.values[path] = variable
        return widget

    def _device(self,parent,title,kind):
        label(parent,title,13,color=MUTED,anchor='w').pack(fill='x',pady=(12,5))
        path=('audio',kind+'_device')
        picker=DevicePicker(parent,kind,self.settings['audio'].get(kind+'_device'),self.invalidate)
        picker.pack(fill='x')
        self.editors.append((path,DeviceValue(picker),None))

    def _percent_slider(self,parent,title,path,low,high,offset=0):
        original=self.settings[path[0]][path[1]]
        variable=ctk.StringVar(value=original)
        label(parent,title,13,color=MUTED,anchor='w').pack(fill='x',pady=(12,5))
        display=label(parent,'',13,anchor='w')
        display.pack(fill='x')
        def update(value):
            number=round(float(value))
            variable.set(f'{number-offset:+d}%')
            display.configure(text=f'{number}%' if offset else f'{number:+d}%')
            self.invalidate()
        slider=ctk.CTkSlider(parent,from_=low,to=high,number_of_steps=high-low,command=update)
        slider.set(max(low,min(high,int(original.rstrip('%'))+offset)))
        display.configure(text=f'{int(original.rstrip("%"))+offset}%')
        slider.pack(fill='x',pady=8)
        self.values[path]=variable
        self.editors.append((path,variable,original))

    def open_blue_guide(self):
        from pathlib import Path
        from ui.setup_managers import show_guide
        show_guide(self,Path(__file__).resolve().parents[2]/'docs'/'bluemagpie_tts_setup.md')

    def test_devices(self):
        def factory(draft):
            def work(cancel,owner):
                check_audio_devices(draft)
                return {'message':'裝置格式檢查通過；請再錄音與試聽確認實際聲音。','check_kind':'devices'}
            return work
        self._start(factory,'devices')

    def apply_to(self, candidate):
        for kind, defaults in self.pending_defaults.items():
            candidate['whisper' if kind == 'stt' else 'tts']['gemini'].update(deepcopy(defaults))
        for path, variable, original in self.editors:
            field=self.field_controls.get(path)
            assign(candidate, path, field.parse() if field else parse_field(variable.get(), original,path))
        if candidate['tts']['backend']=='bluemagpie':
            candidate['tts']['bluemagpie']['enabled']=True

    def summary_values(self):
        stt = self.values['whisper', 'backend'].get()
        tts = self.values['tts', 'backend'].get()
        return stt, tts, self.values['tts', 'gemini', 'voice'].get()

    def refresh_sections(self):
        if not hasattr(self,'_pack_orders'): return
        stt,tts,_=self.summary_values()
        google=(self.input_enabled or self.show_inactive) and stt=='gemini' or (self.output_enabled or self.show_inactive) and tts=='gemini'
        visibility={self.input_frame:self.input_enabled or self.show_inactive,self.output_frame:self.output_enabled or self.show_inactive,
            self.stt_test_frame:self.input_enabled,self.tts_test_frame:self.output_enabled,
            self.google_details:google,self.google_test_frame:google,
            self.local_details:stt=='local',self.groq_details:stt=='groq',self.stt_details:stt=='gemini',
            self.tts_details:tts=='gemini',self.edge_details:tts=='edge',self.blue_details:tts=='bluemagpie'}
        for owner,order in self._pack_orders.items():
            for widget,_ in order: widget.pack_forget()
            for widget,options in order:
                if visibility.get(widget,True): widget.pack(**options)
        import os
        key=self.values['whisper','groq','api_key'].get().strip()
        env=self.values['whisper','groq','api_key_env'].get().strip()
        self.groq_source.configure(text='使用本機 key；啟動／儲存設定後生效。' if key else
            f'使用環境變數 {env}。' if os.environ.get(env) else f'尚未設定 key；也可設定環境變數 {env}。')
        blue_draft={'tts':{'bluemagpie':dict(self.settings['tts']['bluemagpie'])}}
        for path,variable,_ in self.editors:
            if path[:2]==('tts','bluemagpie'):
                blue_draft['tts']['bluemagpie'][path[-1]]=variable.get()
        missing=bluemagpie_readiness(blue_draft)
        self.blue_status.configure(text='選用後自動啟用。'+('尚缺：'+'、'.join(missing) if missing else 'Worker 路徑已備妥；請試聽確認模型與 GPU。'))

    def invalidate(self):
        self.test_states.clear()
        self.stop()
        self.refresh_sections()
        self.changed()
        if hasattr(self, 'status'):
            self.status.configure(text='設定已調整；測試時會使用目前草稿。')

    def restore(self, kind):
        defaults = deepcopy(STT_DEFAULTS if kind == 'stt' else TTS_DEFAULTS)
        self.pending_defaults[kind] = defaults
        group = 'whisper' if kind == 'stt' else 'tts'
        for path, variable, original in self.editors:
            if path[:2] == (group, 'gemini'):
                value = defaults[path[-1]]
                variable.set(json.dumps(value, ensure_ascii=False) if isinstance(value, list) else str(value))
        self.invalidate()
        self.status.configure(text='已還原 Gemini 設定；啟動時儲存。')

    def _start(self, factory, kind='catalog'):
        draft = self.snapshot()
        if draft is None:
            return
        if kind in ('tts','stt','microphone_stt'):
            check=deepcopy(draft)
            check['interaction'].update(voice_input=kind!='tts',voice_output=kind=='tts')
            try:
                validate_local_selection(check)
                provider=check['tts']['backend'] if kind=='tts' else check['whisper']['backend']
                if provider=='gemini':
                    from utils.gemini_audio import resolve_api_key
                    resolve_api_key(check['gemini']['api_key'],check['gemini']['api_key_env'])
            except Exception as exc:
                self.status.configure(text='請先完成服務設定：'+safe_error(exc,draft))
                return
        if self.controller.busy:
            self.status.configure(text='上一筆測試尚在結束，請稍候。')
            return
        work=factory(draft)
        def guarded(cancel,owner):
            try: return work(cancel,owner)
            except Exception as exc: raise ValueError(safe_error(exc,draft)) from None
        self.job_kind=kind
        self.job_token = self.controller.start(guarded)
        self.status.configure(text='測試中；可隨時停止。')
        if self.poll_job is None:
            self.poll_job = self.after(100, self.poll)

    def test_file(self):
        path = filedialog.askopenfilename(parent=self.winfo_toplevel(), title='選擇要辨識的音檔',
            filetypes=[('Audio', '*.wav *.mp3 *.m4a *.flac *.ogg'), ('All files', '*.*')])
        if path:
            self.test_stt(path)

    def test_stt(self, path):
        self._start(lambda draft: stt_preview(draft, path),'microphone_stt' if path is None else 'stt')

    def test_tts(self):
        text = self.preview_text.get().strip()
        if not text or len(text) > 1000:
            self.status.configure(text='試聽文字請輸入 1–1000 字。')
            return
        self._start(lambda draft: tts_preview(draft, text),'tts')

    def catalog(self, kind):
        self._start(lambda draft: google_catalog(draft, kind))

    def _voice_selected(self, value):
        self.values['tts', 'gemini', 'voice'].set(self.voice_choices.get(value, value))

    def _filter_voices(self):
        query = self.voice_search.get().strip().lower()
        self.voice_menu.configure(values=[name for name in self.voice_choices if query in name.lower()])

    def poll(self):
        self.poll_job = None
        if self.dead:
            return
        while not self.controller.events.empty():
            token, status, result = self.controller.events.get()
            if token != self.job_token:
                continue
            if status=='progress':
                self.status.configure(text=result['message'])
                if result.get('level') is not None: self.meter.set(result['level'])
                continue
            if status == 'ok':
                checked='通過' if result.get('check_passed',True) else '已完成，未辨識到人聲'
                self.test_states[getattr(self,'job_kind','catalog')]=checked
                if getattr(self,'job_kind',None)=='microphone_stt': self.test_states['stt']=checked
                self.status.configure(text=result['message'])
                if result.get('catalog_kind') == 'voices':
                    self.voice_choices = {voice: voice for voice in DEFAULT_VOICES}
                    for voice in result.get('voices', []):
                        display = f"{voice['display_name']} ({voice['language_code']}) · {voice['id']}"
                        self.voice_choices[display] = voice['id']
                    if not result.get('voices'):
                        self.voice_choices.update({name: name for name in result['names']})
                    self._filter_voices()
                elif result.get('catalog_kind') == 'models':
                    names = result['names']
                    self.stt_model_menu.configure(values=list(dict.fromkeys(['gemini-3.8-flash'] + [n for n in names if n.startswith('gemini-') and not any(x in n for x in ('-tts', '-image', '-live'))])))
                    self.tts_model_menu.configure(values=list(dict.fromkeys(['gemini-3.8-flash-tts', 'gemini-3.8-flash-lite-tts'] + [n for n in names if n.startswith('gemini-3.8') and '-tts' in n])))
                if 'text' in result:
                    self.result.configure(state='normal')
                    self.result.delete('1.0', 'end')
                    self.result.insert('1.0', result['text'])
                    self.result.configure(state='disabled')
            else:
                if status=='error': self.test_states[getattr(self,'job_kind','catalog')]='未通過'
                self.status.configure(text='已停止測試。' if status == 'cancelled' else f'測試失敗：{result}')
        if self.controller.busy:
            self.poll_job = self.after(100, self.poll)

    def stop(self):
        self.job_token = None
        self.controller.cancel()
        if hasattr(self, 'status'):
            self.status.configure(text='已停止測試。')

    def destroy(self):
        self.dead = True
        self.controller.cancel()
        if self.poll_job is not None:
            self.after_cancel(self.poll_job)
        super().destroy()
