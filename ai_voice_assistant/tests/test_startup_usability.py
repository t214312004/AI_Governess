"""Startup workflow regressions; public defaults and temporary private state only."""
from copy import deepcopy
import json
import os
from pathlib import Path
import threading
import time
from unittest.mock import Mock

import numpy as np
import pytest

from config import Config
from core.session_settings import assign, parse_field, validate_settings
from core.settings_schema import public_defaults, SettingsError
from ui.setup_managers import atomic_write, profile_directory, save_profile_sample, validate_keywords
from utils.audio_devices import resolve_audio_device, check_audio_devices
from utils.startup_diagnostics import safe_error, validate_local_selection


def defaults():
    return deepcopy(public_defaults())


@pytest.mark.parametrize('duration,seconds', [('5m0s', 300), ('250ms', .25)])
def test_migrated_timeout_survives_startup_validation_and_editing(tmp_path, duration, seconds):
    local = tmp_path/'config.local.json'
    local.write_text(json.dumps({'llm': {'antigravity_cli': {'print_timeout': duration}}}), encoding='utf-8')
    cfg = Config(str(Path(__file__).resolve().parents[1]/'config.default.json'), str(local))
    draft = cfg.snapshot()
    validate_settings(draft, draft)
    path = ('llm', 'response_timeout_seconds')
    assign(draft, path, parse_field(str(seconds), draft['llm']['response_timeout_seconds'], path))
    cfg.apply_snapshot(validate_settings(draft, cfg.snapshot()))
    cfg.load()
    assert cfg.get(*path) == seconds


@pytest.mark.parametrize('path,value',[
    (('audio','input_sample_rate'),22050),
    (('audio','input_block_size'),1024),
    (('whisper','model_size'),'nonsense'),
    (('whisper','device'),'nonsense'),
    (('whisper','compute_type'),'int3'),
    (('tts','rate'),'fast'),
    (('tts','rate'),'+31%'),
    (('vad','min_silence_duration_ms'),-1),
    (('llm','codex_cli','sandbox'),'nonsense'),
])
def test_schema_rejects_runtime_incompatible_fields(path,value):
    draft=defaults()
    assign(draft,path,value)
    with pytest.raises(SettingsError) as error:
        validate_settings(draft,defaults())
    assert error.value.path==path


def test_nullable_seed_and_device_can_be_restored_after_reload(tmp_path):
    local=tmp_path/'config.local.json'
    cfg=Config(str(Path(__file__).resolve().parents[1]/'config.default.json'),str(local))
    draft=cfg.snapshot()
    draft['tts']['bluemagpie']['seed']=42
    draft['audio']['input_device']={'name':'USB mic','hostapi':'Windows WASAPI'}
    cfg.apply_snapshot(draft)
    cfg.load()
    previous=cfg.snapshot()
    seed=parse_field('',previous['tts']['bluemagpie']['seed'],('tts','bluemagpie','seed'))
    draft=deepcopy(previous)
    draft['tts']['bluemagpie']['seed']=seed
    draft['audio']['input_device']=None
    cfg.apply_snapshot(validate_settings(draft,previous))
    cfg.load()
    assert cfg.get('tts','bluemagpie','seed') is None
    assert cfg.get('audio','input_device') is None


def test_device_identity_resolves_after_indexes_change_and_never_falls_back(monkeypatch):
    import utils.audio_devices as devices
    monkeypatch.setattr(devices.sd,'query_hostapis',lambda:[{'name':'Windows WASAPI'}])
    monkeypatch.setattr(devices.sd,'query_devices',lambda:[
        {'name':'Other','hostapi':0,'max_input_channels':1,'max_output_channels':0},
        {'name':'USB mic','hostapi':0,'max_input_channels':1,'max_output_channels':0}])
    assert resolve_audio_device({'name':'USB mic','hostapi':'Windows WASAPI'},'input')==1
    with pytest.raises(ValueError,match='已離線'):
        resolve_audio_device({'name':'Missing','hostapi':'Windows WASAPI'},'input')
    check=Mock()
    monkeypatch.setattr(devices.sd,'check_input_settings',check)
    draft=defaults()
    draft['interaction']['voice_output']=False
    draft['audio']['input_device']={'name':'USB mic','hostapi':'Windows WASAPI'}
    check_audio_devices(draft)
    assert check.call_args.kwargs['device']==1


def test_text_only_device_checks_do_not_touch_hardware(monkeypatch):
    import utils.audio_devices as devices
    monkeypatch.setattr(devices.sd,'query_devices',Mock(side_effect=AssertionError('hardware queried')))
    draft=defaults()
    draft['interaction'].update(voice_input=False,voice_output=False)
    check_audio_devices(draft)


@pytest.mark.parametrize('backend',['local','groq'])
def test_low_rate_input_is_resampled_for_whisper(backend,monkeypatch):
    from core.transcriber import BackgroundTranscriber
    engine=Mock()
    engine.transcribe.return_value='test'
    monkeypatch.setattr('core.transcriber.Transcriber',lambda **kwargs:engine)
    monkeypatch.setattr('core.transcriber.GroqWhisperTranscriber',lambda **kwargs:engine)
    transcriber=BackgroundTranscriber(backend=backend,input_sample_rate=8000)
    try:
        assert transcriber.wait_until_ready(1)
        assert transcriber.transcribe(np.ones(8000,np.float32))=='test'
        pcm=engine.transcribe.call_args.args[0]
        assert len(pcm)==16000 and pcm.dtype==np.float32
    finally: transcriber.close()


def test_auto_language_uses_provider_detection(monkeypatch):
    from core.transcriber import Transcriber, GroqWhisperTranscriber
    model=Mock()
    model.transcribe.return_value=([],None)
    monkeypatch.setattr('core.transcriber.WhisperModel',lambda *args,**kwargs:model)
    local=Transcriber(language='auto')
    local._transcribe_once(np.zeros(16000,np.float32),initial_prompt=None)
    assert model.transcribe.call_args.kwargs['language'] is None
    groq=GroqWhisperTranscriber(api_key='unit-test-key',language='auto')
    client=Mock()
    client.post.return_value.json.return_value={'text':'test'}
    groq._request_transcription(client,b'audio')
    assert 'language' not in client.post.call_args.kwargs['data']


@pytest.mark.parametrize('name',['../escape','..','CON','LPT1','bad/name','bad\\name',' trailing','trailing.'])
def test_enrollment_rejects_unsafe_profile_names(tmp_path,name):
    with pytest.raises(ValueError): profile_directory(tmp_path,name)


def test_enrollment_validates_audio_and_creates_private_wav(tmp_path):
    with pytest.raises(ValueError,match='至少'):
        save_profile_sample(tmp_path,'PersonA',np.ones(8000),16000,2)
    with pytest.raises(ValueError,match='音量'):
        save_profile_sample(tmp_path,'PersonA',np.zeros(32000),16000,2)
    result=save_profile_sample(tmp_path,'PersonA',np.full(32000,.1,np.float32),16000,2)
    assert result.parent==tmp_path/'PersonA'
    import wave
    with wave.open(str(result)) as sample:
        assert sample.getnframes()==32000 and sample.getframerate()==16000


def test_keyword_editor_validates_format_tokens_and_preserves_original_on_write_failure(tmp_path,monkeypatch):
    tokens=tmp_path/'tokens.txt'
    tokens.write_text('ài 1\ng 2\nuǎn 3\nj 4\niā 5\n',encoding='utf-8')
    value='ài g uǎn j iā :3.0 #0.15 @愛管家'
    assert validate_keywords(value,tokens)==value+'\n'
    for invalid in ('','plain text','unknown :3.0 #0.15 @test',value+'\n'+value):
        with pytest.raises(ValueError): validate_keywords(invalid,tokens)
    path=tmp_path/'keywords.txt'
    path.write_bytes(b'old')
    monkeypatch.setattr(os,'replace',Mock(side_effect=OSError('disk full')))
    with pytest.raises(OSError): atomic_write(path,b'new')
    assert path.read_bytes()==b'old'


def test_diagnostics_masks_local_and_environment_credentials(monkeypatch):
    draft=defaults()
    draft['gemini']['api_key']='local-secret-123'
    monkeypatch.setenv('GROQ_API_KEY','env-secret-456')
    error=ValueError('401 local-secret-123 env-secret-456 Authorization=Bearer abcdef')
    text=safe_error(error,draft)
    assert 'local-secret-123' not in text and 'env-secret-456' not in text
    assert 'abcdef' not in text


native=pytest.mark.skipif(os.environ.get('AI_GOVERNESS_NATIVE_TESTS')!='1',reason='Opt-in native Tk workflow tests')


@pytest.fixture
def startup_ui(monkeypatch):
    import customtkinter as ctk
    from ui.startup import StartupView
    monkeypatch.setattr('ui.audio_settings.list_audio_devices',lambda kind:[('USB '+kind,{'name':'USB '+kind,'hostapi':'Test API'})])
    root=ctk.CTk()
    root.geometry('640x480')
    view=StartupView(root,defaults(),Mock(),catalog=Mock(),on_save=Mock())
    view.pack(fill='both',expand=True)
    errors=[]
    root.report_callback_exception=lambda typ,value,trace:errors.append(str(value))
    def settle():
        until=time.monotonic()+.25
        while time.monotonic()<until:
            root.update()
            time.sleep(.01)
    settle()
    yield root,view,settle
    view.destroy()
    for job in root.tk.call('after','info'): root.after_cancel(job)
    root.destroy()
    assert not errors


@native
def test_native_service_sections_collapse_and_bluemagpie_selection_enables(startup_ui):
    root,view,settle=startup_ui
    view.navigate(1)
    settle()
    editor=view.audio_editor
    assert not editor.stt_details.winfo_ismapped()
    assert not editor.tts_details.winfo_ismapped()
    assert editor.local_details.winfo_ismapped()
    assert editor.edge_details.winfo_ismapped()
    assert editor.local_details.master is editor.input_frame
    assert editor.edge_details.master is editor.output_frame
    old_height=editor.winfo_height()
    editor.values['whisper','backend'].set('gemini')
    editor.values['tts','backend'].set('gemini')
    settle()
    assert editor.google_details.winfo_ismapped()
    assert not editor.local_details.winfo_ismapped()
    assert not editor.edge_details.winfo_ismapped()
    editor.values['whisper','backend'].set('local')
    editor.values['tts','backend'].set('edge')
    settle()
    assert editor.winfo_height()<=old_height+2
    editor.values['tts','backend'].set('bluemagpie')
    assert view.collect()
    assert view.settings['tts']['bluemagpie']['enabled'] is True


@native
def test_native_scroll_footer_seed_reset_and_save_without_query(startup_ui):
    root,view,settle=startup_ui
    view.navigate(3)
    view.show_all=True
    view.render_group('tts')
    settle()
    field=view.field_controls['tts','bluemagpie','seed']
    field.variable.set('42')
    assert view.collect()
    view.render_group('tts')
    view.field_controls['tts','bluemagpie','seed'].variable.set('')
    assert view.collect()
    assert view.settings['tts']['bluemagpie']['seed'] is None
    view.content._parent_canvas.yview_moveto(1)
    view.navigate(2)
    settle()
    assert view.content._parent_canvas.yview()[0]==0
    view.status.configure(text='很長的錯誤訊息。'*100)
    settle()
    for control in (view.next,view.previous,view.save_button):
        assert control.winfo_ismapped()
        assert control.winfo_width()>=control.winfo_reqwidth()-2
    assert len(view.status.full_text)>len(view.status.cget('text'))
    assert not view.ready
    view.save_draft()
    view.on_save.assert_called_once()
    assert view.on_save.call_args.args[0]['interaction']['update_cli'] is False


@native
def test_native_error_identifies_field_and_restore_recovers(startup_ui):
    root,view,settle=startup_ui
    view.navigate(3)
    view.render_group('audio')
    field=view.field_controls['audio','input_block_size']
    field.variable.set('abc')
    assert not view.collect()
    settle()
    assert view.error_path==('audio','input_block_size')
    assert field.error.winfo_ismapped()
    view.restore_group()
    assert view.collect()
    assert view.settings['audio']['input_block_size']==512


@native
def test_native_preexisting_invalid_setting_can_be_repaired(startup_ui,monkeypatch):
    root,view,settle=startup_ui
    monkeypatch.setattr('tkinter.messagebox.askyesno',lambda *args,**kwargs:True)
    view.settings['audio']['input_block_size']=1024
    assert not view.collect()
    view.show_diagnostics()
    assert view.step==3 and ('audio','input_block_size') in view.field_controls
    view.field_controls['audio','input_block_size'].variable.set('512')
    assert view.collect()
    view.minutes.set('invalid')
    assert not view.collect()
    view.show_diagnostics()
    assert view.step==2
    view.minutes.set('30')
    assert view.collect()
    view.settings['whisper']['gemini']['vocabulary_hints']=None
    assert not view.collect()
    view.show_diagnostics()
    view.field_controls['whisper','gemini','vocabulary_hints'].variable.set('["Python"]')
    assert view.collect()
    view.settings['audio']['input_device']='invalid'
    assert not view.collect()
    view.show_diagnostics()
    assert view.step==1
    for path,variable,_ in view.audio_editor.editors:
        if path==('audio','input_device'):
            variable.picker.variable.set('Windows 預設裝置')
    assert view.collect()
    assert view.settings['audio']['input_device'] is None


@native
def test_native_file_transcription_does_not_claim_microphone_was_tested(startup_ui):
    root,view,settle=startup_ui
    view.navigate(1)
    editor=view.audio_editor
    editor.job_token=101
    editor.job_kind='stt'
    view.audio_preview.events.put((101,'ok',{'message':'ok','text':'hello'}))
    editor.poll()
    assert view.test_states['stt']=='通過'
    assert 'microphone_stt' not in view.test_states
    editor.job_token=102
    editor.job_kind='microphone_stt'
    view.audio_preview.events.put((102,'ok',{'message':'empty','text':'','check_passed':False}))
    editor.poll()
    assert view.test_states['microphone_stt']!='通過'


@native
def test_native_preview_reports_missing_setup_before_opening_audio(startup_ui,monkeypatch):
    root,view,settle=startup_ui
    monkeypatch.delenv('GROQ_API_KEY',raising=False)
    view.navigate(1)
    editor=view.audio_editor
    editor.values['tts','backend'].set('bluemagpie')
    editor.values['tts','bluemagpie','worker_python'].set('missing/worker.exe')
    editor.test_tts()
    assert not view.audio_preview.busy
    assert 'BlueMagpie' in editor.status.cget('text')
    editor.values['whisper','backend'].set('groq')
    editor.values['whisper','groq','api_key'].set('')
    editor.test_stt('unused.wav')
    assert not view.audio_preview.busy
    assert 'Groq' in editor.status.cget('text')
    editor.values['whisper','backend'].set('local')
    editor._start(lambda draft:lambda cancel,owner:{'message':'ok'},'stt')
    view.audio_preview.thread.join(1)
    editor.poll()
    assert view.test_states['stt']=='通過'


@native
def test_native_query_is_cancellable_and_update_is_explicit(startup_ui):
    root,view,settle=startup_ui
    from llm.model_catalog import ModelInfo
    entered=threading.Event()
    def query(backend,update,*,cancel,timeout):
        assert update is False
        entered.set()
        cancel.wait(1)
        return (ModelInfo('stale',()),)
    view.catalog.query=query
    view.query()
    assert entered.wait(1)
    view.cancel_query()
    view.query_thread.join(1)
    settle()
    assert not view.ready and not view.querying
    assert all(m.id!='stale' for m in view.models)
    view.catalog.query=lambda *args,**kwargs:(ModelInfo('valid',('low',)),)
    view.query(update=True)
    view.query_thread.join(1)
    settle()
    assert view.ready and view.update_cli.get()


@native
def test_native_text_mode_skips_audio_and_all_font_sizes_are_available(startup_ui):
    root,view,settle=startup_ui
    view.voice_in.set('固定文字')
    view.voice_out.set('固定文字')
    view.navigate(1)
    assert view.audio_editor is None
    view.show_inactive_audio=True
    view.render()
    settle()
    assert view.audio_editor.input_frame.winfo_ismapped()
    assert view.audio_editor.output_frame.winfo_ismapped()
    assert view.audio_editor.device_test_button.cget('state')=='disabled'
    view.navigate(2)
    assert view.font_preview.cget('text')
    view.font_size.set('32')
    view.update_font_preview()
    assert view.collect()
    assert view.settings['ui']['chat_font_size']==32


@native
def test_native_global_search_and_local_keyword_save(startup_ui,tmp_path):
    root,view,settle=startup_ui
    view.navigate(3)
    view.search.set('heartbeat')
    view.render_group('__search__')
    assert ('heartbeat','interval_minutes') in view.field_controls
    assert all('heartbeat' in '.'.join(path) for path in view.field_controls)
    keywords=tmp_path/'keywords.txt'
    view.settings['wake_word']['keywords_file']=str(keywords)
    view.settings['wake_word']['model_dir']=str(tmp_path/'missing-model')
    view.open_manager('keywords')
    settle()
    dialog=view.managers[-1]
    dialog.value.set('ài g uǎn j iā :3.0 #0.15 @愛管家')
    dialog.save()
    assert keywords.read_text(encoding='utf-8').endswith('@愛管家\n')
    assert dialog.value.get()==dialog.initial
    assert dialog.close() is True


@native
@pytest.mark.parametrize('scaling',[1.,1.25,1.5,1.75])
def test_native_footer_and_navigation_at_multiple_widget_scales(startup_ui,scaling):
    import customtkinter as ctk
    root,view,settle=startup_ui
    dpi=ctk.ScalingTracker.get_window_dpi_scaling(root)
    ctk.set_widget_scaling(scaling/dpi)
    ctk.set_window_scaling(scaling/dpi)
    try:
        root.geometry('640x480')
        for page in (0,1,2,3,4):
            view.navigate(page)
            view.status.configure(text='這是可開啟詳情的錯誤訊息。'*40)
            settle()
            for control in (view.next,view.previous,view.save_button):
                assert control.winfo_ismapped()
                assert control.winfo_width()>=control.winfo_reqwidth()-2
                assert control.winfo_rootx()+control.winfo_width()<=root.winfo_rootx()+root.winfo_width()+2
        assert abs(view._get_widget_scaling()-scaling)<.01
    finally:
        ctk.set_widget_scaling(1)
        ctk.set_window_scaling(1)
