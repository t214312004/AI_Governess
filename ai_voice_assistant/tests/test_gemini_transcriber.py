import asyncio
import json
import threading
import time

import httpx
import numpy as np
import pytest

from core.gemini_transcriber import GeminiTranscriber
from core.transcriber import BackgroundTranscriber


def response(text='你好', status='completed', usage=None):
    return {'status': status, 'usage': usage or {}, 'steps': [
        {'type': 'thought', 'content': [{'type': 'text', 'text': 'not transcript'}]},
        {'type': 'model_output', 'content': [{'type': 'text', 'text': text}]}]}


@pytest.fixture
def mock_http(monkeypatch):
    original = httpx.AsyncClient
    def install(handler):
        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(
            **dict(kwargs, transport=httpx.MockTransport(handler))))
    return install


def engine(monkeypatch, **settings):
    instance = GeminiTranscriber(api_key='test-key', settings=settings)
    monkeypatch.setattr(instance, '_has_speech', lambda audio: True)
    return instance


def test_stt_only_returns_model_text_and_sends_supported_options(mock_http, monkeypatch):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response())
    mock_http(handler)
    instance = engine(monkeypatch)
    assert instance.transcribe(np.ones(16000, np.float32)*.1) == '你好'
    assert requests[0]['generation_config']['thinking_level'] == 'low'
    assert requests[0]['store'] is False
    assert instance.last_diagnostics['status'] == 'ok'


@pytest.mark.parametrize('payload,reason', [
    (response(status='incomplete'), 'incomplete_response'),
    (response(usage={'total_output_tokens': 4096}), 'truncated_transcript'),
    (dict(response(), errors=[{'code': 'blocked'}]), 'blocked_response'),
    ({'status': 'completed', 'steps': []}, 'missing_text_output'),
    (response('say goodbye '*12), 'repeated_transcript'),
    (response('很長的轉錄'*80), 'excessive_transcript_length'),
])
def test_stt_rejects_incomplete_or_abnormal_results(mock_http, monkeypatch, payload, reason):
    mock_http(lambda request: httpx.Response(200, json=payload))
    instance = engine(monkeypatch)
    assert instance.transcribe(np.ones(80000, np.float32)*.1) == ''
    assert instance.last_diagnostics['reason'] == reason


def test_stt_retries_temporary_error_within_deadline(mock_http, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json=response())
    mock_http(handler)
    instance = engine(monkeypatch, total_timeout_seconds=2.0)
    assert instance.transcribe(np.ones(16000, np.float32)*.1) == '你好'
    assert instance.last_diagnostics['attempts'] == 2


def test_stt_respects_retry_after_and_never_retries_auth_error(mock_http, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={'Retry-After': '60'}, json={'secret': 'do not display'})
    mock_http(handler)
    instance = engine(monkeypatch, total_timeout_seconds=.1)
    assert instance.transcribe(np.ones(16000, np.float32)) == ''
    assert len(calls) == 1
    mock_http(lambda request: httpx.Response(403, json={'error': 'secret'}))
    assert instance.transcribe(np.ones(16000, np.float32)) == ''
    assert instance.last_diagnostics['attempts'] == 1
    assert 'secret' not in str(instance.last_diagnostics)


def test_stt_timeout_is_wall_clock_bounded(mock_http, monkeypatch):
    async def handler(request):
        await asyncio.sleep(10)
        return httpx.Response(200, json=response())
    mock_http(handler)
    instance = engine(monkeypatch, total_timeout_seconds=.03)
    started = time.monotonic()
    assert instance.transcribe(np.ones(16000, np.float32)) == ''
    assert instance.last_diagnostics['reason'] == 'timeout'
    assert time.monotonic()-started < .5


@pytest.mark.asyncio
async def test_stt_cancel_interrupts_network_and_close_prevents_new_calls(mock_http, monkeypatch):
    entered = threading.Event()
    async def handler(request):
        entered.set()
        await asyncio.sleep(10)
        return httpx.Response(200, json=response())
    mock_http(handler)
    instance = engine(monkeypatch)
    task = asyncio.create_task(asyncio.to_thread(instance.transcribe, np.ones(16000, np.float32)))
    while not entered.is_set():
        await asyncio.sleep(.01)
    instance.cancel()
    assert await asyncio.wait_for(task, .5) == ''
    assert instance.last_diagnostics['status'] == 'cancelled'
    instance.close()
    assert instance.transcribe(np.ones(16000, np.float32)) == ''
    assert instance.last_diagnostics['attempts'] == 0


def test_stt_gate_uses_bundled_vad_and_never_sends_known_non_speech(mock_http):
    calls = []
    mock_http(lambda request: calls.append(request))
    instance = GeminiTranscriber(api_key='test-key')
    t = np.arange(32000)/16000
    for audio in (np.zeros(32000), .01*np.sin(2*np.pi*60*t),
                  np.random.default_rng(42).normal(0, .006, 32000),
                  np.where(np.arange(32000)%4000 < 4, .08, 0)):
        assert instance.transcribe(audio.astype(np.float32)) == ''
        assert instance.last_diagnostics['status'] == 'no_speech'
    assert not calls


def test_background_selects_gemini_and_preserves_other_backends(monkeypatch):
    mock = type('Fake', (), {'transcribe': lambda self, audio, cancel_event=None: 'test', 'close': lambda self: None})
    monkeypatch.setattr('core.gemini_transcriber.GeminiTranscriber', lambda **kw: mock())
    transcriber = BackgroundTranscriber(backend='gemini', gemini_api_key='test-key')
    assert transcriber.wait_until_ready(1)
    assert transcriber.transcribe(np.ones(10)) == 'test'
    transcriber.close()
    assert transcriber.transcribe(np.ones(10)) == ''


@pytest.mark.parametrize('action', ['cancel', 'close'])
def test_background_cancel_during_load_retires_waiting_transcription(monkeypatch, action):
    from unittest.mock import Mock
    load_release = threading.Event()
    waiting = threading.Event()
    engine = Mock()
    engine.transcribe.return_value = 'next turn'

    def load(**kwargs):
        assert load_release.wait(3)
        return engine

    monkeypatch.setattr('core.transcriber.Transcriber', load)
    transcriber = BackgroundTranscriber()
    original_wait = transcriber._ready.wait

    def observed_wait(timeout=None):
        waiting.set()
        return original_wait(timeout)

    monkeypatch.setattr(transcriber._ready, 'wait', observed_wait)
    result = []
    worker = threading.Thread(target=lambda: result.append(transcriber.transcribe(np.ones(10))))
    worker.start()
    try:
        assert waiting.wait(1)
        getattr(transcriber, action)()
        worker.join(1)
        assert not worker.is_alive()
        assert result == ['']
        engine.transcribe.assert_not_called()
        load_release.set()
        transcriber._load_thread.join(1)
        assert transcriber.transcribe(np.ones(10)) == ('' if action == 'close' else 'next turn')
    finally:
        load_release.set()
        worker.join(2)
        transcriber.close()
