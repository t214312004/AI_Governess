from copy import deepcopy
import json
import os
from pathlib import Path
import threading
import time

import httpx
import numpy as np
import pytest

from config import Config, config
from core.pipeline.composition import PipelineCompositionRoot
from core.session_settings import validate_settings
from tts.factory import create_tts_engine, normalize_tts_backend_name
from ui.audio_preview import AudioPreviewController, DraftConfig, PreviewSignal, google_catalog, read_audio, validate_google_selection
from utils.gemini_audio import GeminiAPIError, wav_bytes
from utils.gemini_settings import audio_settings


def defaults():
    return json.loads(Path(config.default_path).read_text(encoding='utf-8'))


@pytest.mark.parametrize('stt', ['local', 'groq', 'gemini'])
@pytest.mark.parametrize('tts', ['edge', 'bluemagpie', 'gemini'])
def test_backend_composition_resolves_independent_audio_choices(stt, tts):
    settings = defaults()
    settings['whisper']['backend'], settings['tts']['backend'] = stt, tts
    composition = PipelineCompositionRoot.build(DraftConfig(settings))
    assert composition.backend_selection.stt == stt
    assert composition.backend_selection.tts == tts
    assert validate_settings(settings, defaults()) == settings


def test_gemini_factory_passes_voice_settings_and_does_not_require_key_for_text_only(monkeypatch, tmp_path):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    settings = defaults()
    settings['interaction']['voice_output'] = False
    settings['tts']['backend'] = 'gemini'
    engine = create_tts_engine(DraftConfig(settings), app_dir=str(tmp_path), sample_rate=16000)
    assert engine.settings['voice'] == audio_settings('tts')['voice'] == 'Leda'
    engine.close()
    settings['tts']['gemini']['voice'] = 'Puck'
    settings['tts']['gemini']['style'] = '說慢一點'
    settings['pipeline_v2_5']['streaming_tts'] = True
    engine = create_tts_engine(DraftConfig(settings), app_dir=str(tmp_path), sample_rate=16000)
    assert engine.backend == 'gemini' and engine.streaming
    assert engine.settings['voice'] == 'Puck'
    assert engine.settings['style'] == '說慢一點'
    assert engine.sample_rate == 16000
    engine.close()
    with pytest.raises(ValueError, match='Unsupported TTS backend'):
        normalize_tts_backend_name('gemni')


@pytest.mark.parametrize('kind,changes', [
    ('stt', {'thinking_level': 'off'}), ('stt', {'max_output_tokens': 0}),
    ('stt', {'speech_gate_threshold': 1.1}), ('stt', {'vocabulary_hints': [42]}),
    ('stt', {'max_retries': 2}), ('stt', {'model': 'gemini-../invalid'}),
    ('tts', {'volume_gain': 3.0}), ('tts', {'audio_format': 'mp3'}),
    ('tts', {'api_sample_rate': 44100}), ('tts', {'chunk_min_chars': 999, 'chunk_max_chars': 998}),
    ('tts', {'min_request_interval_seconds': -1.0}),
    ('tts', {'total_timeout_seconds': float('nan')}),
])
def test_audio_settings_reject_unsupported_or_unbounded_values(kind, changes):
    with pytest.raises(ValueError):
        audio_settings(kind, changes)


def test_preview_controller_cancels_and_keeps_results_in_queue():
    controller = AudioPreviewController()
    entered = threading.Event()
    class Resource:
        def __init__(self): self.closed = False
        def cancel(self): self.closed = True
    resource = Resource()
    def work(cancel, owner):
        owner.own(resource)
        entered.set()
        cancel.wait(1)
        return {'message': 'finished'}
    token = controller.start(work)
    assert entered.wait(1)
    assert controller.start(work) is None
    controller.cancel()
    controller.thread.join(1)
    assert resource.closed and not controller.busy
    assert controller.events.get_nowait()[:2] == (token, 'cancelled')


def test_audio_preview_reader_resamples_and_enforces_duration(tmp_path):
    path = tmp_path/'audio.wav'
    path.write_bytes(wav_bytes(np.ones(16000, np.float32)*.1))
    audio = read_audio(path, 8000, 2)
    assert audio.dtype == np.float32 and len(audio) == 8000
    with pytest.raises(GeminiAPIError, match='audio_too_long'):
        read_audio(path, 8000, .5)


def test_google_startup_preflight_only_gets_active_model_metadata(monkeypatch):
    original = httpx.AsyncClient
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == 'GET'
        assert request.headers['x-goog-api-key'] == 'test-key'
        return httpx.Response(200, json={'name': 'model'})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(**dict(kwargs, transport=httpx.MockTransport(handler))))
    settings = defaults()
    settings['gemini']['api_key'] = 'test-key'
    settings['whisper']['backend'] = settings['tts']['backend'] = 'gemini'
    validate_google_selection(settings)
    assert len(calls) == 2
    settings['interaction']['voice_input'] = settings['interaction']['voice_output'] = False
    settings['gemini']['api_key'] = ''
    validate_google_selection(settings)
    assert len(calls) == 2


def test_voice_catalog_reads_ids_and_pages_without_exposing_credentials(monkeypatch):
    original = httpx.AsyncClient
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={'voices':[{'id':'voice_one','display_name':'Test','language_code':'zh-TW'}], 'next_page_token':'next'})
        assert request.url.params['page_token'] == 'next'
        return httpx.Response(200, json={'voices':[{'id':'voice_two','display_name':'Test Two','language_code':'en-US'}]})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(**dict(kwargs, transport=httpx.MockTransport(handler))))
    settings = defaults()
    settings['gemini']['api_key'] = 'test-key'
    result = google_catalog(settings, 'voices')(None, None)
    assert result['names'] == ['voice_one', 'voice_two']
    assert result['voices'][0]['language_code'] == 'zh-TW'
    assert 'test-key' not in str(result)


@pytest.mark.asyncio
async def test_preview_signal_wait_is_async_and_cancellable():
    import asyncio
    event = threading.Event()
    signal = PreviewSignal(event)
    waiter = asyncio.create_task(signal.wait())
    await asyncio.sleep(.01)
    assert not waiter.done()
    event.set()
    assert await asyncio.wait_for(waiter, .5)


@pytest.mark.skipif(os.environ.get('AI_GOVERNESS_NATIVE_TESTS') != '1', reason='Opt-in native Tk test')
def test_native_audio_settings_round_trip_stop_and_catalog_preserve_voice(tmp_path, monkeypatch):
    import customtkinter as ctk
    from ui.startup import StartupView
    from utils.google_credentials import save_google_api_key
    local = tmp_path/'config.local.json'
    local.write_text('{"custom":{"keep":true}}', encoding='utf-8')
    cfg = Config(config.default_path, str(local))
    root = ctk.CTk()
    root.withdraw()
    view = StartupView(root, cfg.snapshot(), lambda *args: None,
        save_google_key=lambda key: save_google_api_key(cfg, key))
    view.pack(fill='both', expand=True)
    errors = []
    root.report_callback_exception = lambda typ, value, trace: errors.append(str(value))
    try:
        view.navigate(1)
        editor = view.audio_editor
        assert editor.voice_menu.cget('values') == ['Leda', 'Zephyr']
        assert editor.values['tts', 'gemini', 'voice'].get() == 'Leda'
        editor.voice_search.set('Kore')
        assert editor.voice_menu.cget('values') == []
        editor.voice_search.set('')
        editor.values['whisper', 'backend'].set('gemini')
        editor.values['tts', 'backend'].set('gemini')
        editor.values['tts', 'gemini', 'voice'].set('custom-voice')
        editor.values['tts', 'gemini', 'style'].set('自然台灣華語')
        editor.values['tts', 'gemini', 'volume_gain'].set('1.2')
        editor.values['whisper', 'gemini', 'vocabulary_hints'].set('["Python","Gemini"]')
        assert view.collect()
        assert view.settings['tts']['gemini']['volume_gain'] == 1.2
        editor.job_token = 42
        view.audio_preview.events.put((42, 'ok', {'message':'updated', 'catalog_kind':'voices',
            'names':['Kore', 'voice_zh_tw'], 'voices':[
                {'id':'Kore', 'display_name':'Kore', 'language_code':'en-US'},
                {'id':'voice_zh_tw', 'display_name':'Taiwan Test', 'language_code':'zh-TW'}]}))
        editor.poll()
        assert editor.values['tts', 'gemini', 'voice'].get() == 'custom-voice'
        assert editor.voice_menu.cget('values')[:2] == ['Leda', 'Zephyr']
        editor.voice_search.set('Kore')
        assert editor.voice_menu.cget('values') == ['Kore (en-US) · Kore']
        editor.voice_search.set('zh-TW')
        assert editor.voice_menu.cget('values') == ['Taiwan Test (zh-TW) · voice_zh_tw']
        editor._voice_selected(editor.voice_menu.cget('values')[0])
        assert editor.values['tts', 'gemini', 'voice'].get() == 'voice_zh_tw'
        editor.restore('tts')
        assert editor.values['tts', 'gemini', 'voice'].get() == 'Leda'
        editor.values['tts', 'gemini', 'voice'].set('custom-voice')
        view.navigate(3)
        view.navigate(1)
        assert view.audio_editor.values['tts', 'gemini', 'voice'].get() == 'custom-voice'
        view.set_preparing(True)
        assert view.audio_editor.tts_model_menu.cget('state') == 'disabled'
        view.set_preparing(False)
        view.navigate(4)
        cfg.apply_snapshot(view.settings)
        saved = Config(config.default_path, str(local))
        assert saved.get('whisper','backend') == 'gemini'
        assert saved.get('tts','gemini','voice') == 'custom-voice'
        assert saved.get('custom','keep') is True
        assert not errors
    finally:
        view.destroy()
        for job in root.tk.call('after', 'info'):
            root.after_cancel(job)
        root.destroy()
