"""Breeze isolation, offline loading, preparation integrity, and native UI round trips."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import numpy as np
import pytest

from core.local_asr import BREEZE_DEFAULTS, resolve_local_profile
from utils import breeze_model as assets


@pytest.mark.parametrize('language', ['auto', 'en', 'zh'])
def test_breeze_profile_overrides_only_local_decoder(language, tmp_path, monkeypatch):
    from core.transcriber import BackgroundTranscriber
    monkeypatch.setattr('core.local_asr.readiness', lambda _: None)
    monkeypatch.setattr('core.local_asr.available_memory_bytes', lambda: 4 * 1024**3)
    with patch('core.transcriber.Transcriber') as local, patch('core.transcriber.GroqWhisperTranscriber') as cloud:
        worker = BackgroundTranscriber(local_profile='breeze_asr25', language='zh', initial_prompt='standard prompt',
            breeze_settings={'model_dir': str(tmp_path), 'language': language})
        assert worker.wait_until_ready(2)
        options = local.call_args.kwargs
        assert options['model_size'] == str(tmp_path.resolve())
        assert options['language'] == language and options['initial_prompt'] == ''
        assert options['local_files_only'] is True
        assert options['compute_type'] == 'int8_float16'
        cloud.assert_not_called()
        worker.close()
        cloud_worker = BackgroundTranscriber(backend='groq', local_profile='breeze_asr25',
            groq_api_key='test', language='zh', initial_prompt='cloud prompt')
        assert cloud_worker.wait_until_ready(2)
        assert cloud.call_args.kwargs['language'] == 'zh'
        assert cloud.call_args.kwargs['initial_prompt'] == 'cloud prompt'
        assert local.call_count == 1
        cloud_worker.close()


def test_missing_breeze_never_downloads_or_falls_back(tmp_path):
    from core.transcriber import BackgroundTranscriber
    with patch('core.transcriber.WhisperModel') as model, patch('core.transcriber.GroqWhisperTranscriber') as cloud:
        worker = BackgroundTranscriber(local_profile='breeze_asr25', breeze_settings={'model_dir': str(tmp_path)})
        assert not worker.wait_until_ready(2)
        assert worker.last_diagnostics['status'] == 'error'
        assert '尚未準備' in worker.last_diagnostics['message']
        assert worker.transcribe(np.zeros(16000, np.float32)) == ''
        model.assert_not_called()
        cloud.assert_not_called()


def test_low_memory_rejected_before_native_load(monkeypatch):
    monkeypatch.setattr('core.local_asr.readiness', lambda _: None)
    monkeypatch.setattr('core.local_asr.available_memory_bytes', lambda: 512 * 1024**2)
    with pytest.raises(ValueError, match='RAM'):
        resolve_local_profile('breeze_asr25', {})
    assert resolve_local_profile('standard', {'language': 'zh'}) == {'language': 'zh'}


def test_local_decoder_consumes_generator_and_preserves_failure_diagnostics():
    from core.transcriber import Transcriber
    segment = SimpleNamespace(text='請用 Python 開啟檔案', avg_logprob=-.2, no_speech_prob=.01)
    with patch('core.transcriber.WhisperModel') as constructor:
        native = constructor.return_value
        native.transcribe.return_value = (iter([segment]), SimpleNamespace(language='en', language_probability=.9))
        transcriber = Transcriber(language='auto', initial_prompt='', local_files_only=True,
                                  decoding_options={'beam_size': 1})
        assert transcriber.transcribe(np.ones(16000, np.float32)) == segment.text
        assert native.transcribe.call_args.kwargs['language'] is None
        assert native.transcribe.call_args.kwargs['beam_size'] == 1
        assert transcriber.last_diagnostics['language'] == 'en'
        assert transcriber.last_diagnostics['avg_logprob'] == -.2
        def broken():
            raise RuntimeError('CUDA out of memory')
            yield
        native.transcribe.return_value = (broken(), None)
        assert transcriber.transcribe(np.ones(16000, np.float32)) == ''
        assert transcriber.last_diagnostics['status'] == 'error'
        assert transcriber.last_diagnostics['reason'] == 'local_inference_failed'
        transcriber.close()
        native.model.unload_model.assert_called_once()


def test_close_during_native_inference_unloads_after_completion():
    from core.transcriber import Transcriber
    entered, finish = threading.Event(), threading.Event()
    def segments():
        entered.set()
        finish.wait(2)
        yield SimpleNamespace(text='obsolete')
    with patch('core.transcriber.WhisperModel') as constructor:
        native = constructor.return_value
        native.transcribe.return_value = (segments(), None)
        transcriber = Transcriber(initial_prompt='')
        results = []
        thread = threading.Thread(target=lambda: results.append(transcriber.transcribe(np.ones(16000, np.float32))))
        thread.start()
        assert entered.wait(1)
        transcriber.close()
        native.model.unload_model.assert_not_called()
        finish.set()
        thread.join(2)
        assert results == ['']
        native.model.unload_model.assert_called_once()


@pytest.fixture
def small_assets(monkeypatch):
    contents = {'model.bin': b'test weights', 'config.json': b'{"model_type":"Whisper"}'}
    specs = {name: (len(data), 'sha256', hashlib.sha256(data).hexdigest()) for name, data in contents.items()}
    monkeypatch.setattr(assets, 'FILES', specs)
    monkeypatch.setattr(assets.shutil, 'disk_usage', lambda _: SimpleNamespace(free=4 * 1024**3))
    original = httpx.Client
    calls = []
    def install(corrupt=False, cancel=None):
        def handler(request):
            calls.append(str(request.url))
            if cancel is not None:
                cancel.set()
            data = contents[request.url.path.rsplit('/', 1)[-1]]
            return httpx.Response(200, content=b'x' * len(data) if corrupt else data)
        monkeypatch.setattr(assets.httpx, 'Client', lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)))
    install()
    return contents, calls, install


def test_preparation_pins_source_verifies_and_reuses_completed_files(tmp_path, small_assets):
    contents, calls, _ = small_assets
    assets.prepare_model(tmp_path)
    assert assets.readiness(tmp_path, verify=True) is None
    assert all(assets.REVISION in url and '/int8_float16/' in url for url in calls)
    assert json.loads((tmp_path / assets.MANIFEST).read_text()) == assets.expected_manifest()
    (tmp_path / assets.MANIFEST).write_text('corrupt', encoding='utf-8')
    assets.prepare_model(tmp_path)
    assert len(calls) == len(contents)
    assert assets.readiness(tmp_path) is None
    (tmp_path / 'model.bin').write_bytes(b'x' * len(contents['model.bin']))
    assert assets.readiness(tmp_path, verify=True)
    assets.prepare_model(tmp_path)
    assert assets.readiness(tmp_path, verify=True) is None


def test_corrupt_download_never_publishes_readiness(tmp_path, small_assets):
    _, _, install = small_assets
    install(corrupt=True)
    with pytest.raises(ValueError, match='校驗失敗'):
        assets.prepare_model(tmp_path)
    assert not (tmp_path / assets.MANIFEST).exists()
    assert not list(tmp_path.glob('*.part')) and not (tmp_path / '.breeze-download.lock').exists()


def test_preparation_leaves_other_model_configs_intact(tmp_path, small_assets):
    _, calls, _ = small_assets
    other_config = tmp_path / 'config.json'
    other_config.write_text('{"model_type": "unrelated"}', encoding='utf-8')
    with pytest.raises(ValueError, match='其他模型檔案'):
        assets.prepare_model(tmp_path)
    assert other_config.read_text(encoding='utf-8') == '{"model_type": "unrelated"}'
    assert not calls


def test_interrupted_repair_keeps_model_marked_unready(tmp_path, small_assets):
    contents, _, install = small_assets
    assets.prepare_model(tmp_path)
    (tmp_path / 'model.bin').write_bytes(b'x' * len(contents['model.bin']))
    install(corrupt=True)
    with pytest.raises(ValueError, match='校驗失敗'):
        assets.prepare_model(tmp_path)
    assert assets.readiness(tmp_path)
    install()
    assets.prepare_model(tmp_path)
    assert assets.readiness(tmp_path, verify=True) is None


def test_cancelled_preparation_cleans_partial_and_lock(tmp_path, small_assets):
    import asyncio
    _, _, install = small_assets
    cancel = threading.Event()
    install(cancel=cancel)
    with pytest.raises(asyncio.CancelledError):
        assets.prepare_model(tmp_path, cancel=cancel)
    assert not (tmp_path / assets.MANIFEST).exists()
    assert not list(tmp_path.glob('*.part')) and not (tmp_path / '.breeze-download.lock').exists()


def test_settings_round_trip_keeps_cloud_and_standard_fields():
    from core.session_settings import validate_settings
    from ui.audio_preview import DraftConfig
    from core.local_asr import local_profile_kwargs
    defaults = json.loads((Path(__file__).parents[1] / 'config.default.json').read_text(encoding='utf-8'))
    draft = deepcopy(defaults)
    draft['whisper'].update(backend='local', local_profile='breeze_asr25')
    assert validate_settings(draft, defaults) == draft
    assert local_profile_kwargs(DraftConfig(draft))['breeze_settings'] == BREEZE_DEFAULTS
    assert draft['whisper']['language'] == defaults['whisper']['language'] == 'zh'
    draft['whisper']['breeze_asr25']['beam_size'] = 0
    with pytest.raises(ValueError, match='1–5'):
        validate_settings(draft, defaults)


@pytest.mark.skipif(os.environ.get('AI_GOVERNESS_NATIVE_TESTS') != '1', reason='Opt-in native Tk test')
def test_native_breeze_selection_and_round_trip():
    # Keep Tcl/CustomTkinter globals out of other tests' interpreters.
    import subprocess
    import sys
    code = '''
import json
from copy import deepcopy
from pathlib import Path
import customtkinter as ctk
from ui.audio_preview import AudioPreviewController
from ui.audio_settings import AudioSettingsEditor
settings = json.loads(Path('config.default.json').read_text(encoding='utf-8'))
root = ctk.CTk()
root.withdraw()
controller = AudioPreviewController()
editor = AudioSettingsEditor(root, settings, controller, lambda: settings, lambda: None)
try:
    editor.values['whisper', 'local_profile'].set('breeze_asr25')
    editor.refresh_sections()
    assert editor.breeze_details.winfo_manager() == 'pack'
    assert editor.standard_details.winfo_manager() == ''
    draft = deepcopy(settings)
    editor.apply_to(draft)
    assert draft['whisper']['local_profile'] == 'breeze_asr25'
    assert draft['whisper']['breeze_asr25']['language'] == 'auto'
    assert draft['whisper']['language'] == 'zh'
    root.update_idletasks()
finally:
    editor.destroy()
    root.destroy()
'''
    result = subprocess.run([sys.executable, '-B', '-c', code], cwd=Path(__file__).parents[1],
                            capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
