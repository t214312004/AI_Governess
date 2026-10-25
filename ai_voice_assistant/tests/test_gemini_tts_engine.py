import asyncio
import base64
import io
import json
import threading
import time
import wave

import httpx
import numpy as np
import pytest

from core.audio_player import AudioPlayer
from tts.gemini_tts_engine import GeminiTTSEngine


def audio_event(data):
    return {'event_type': 'step.delta', 'delta': {'type': 'audio', 'data': base64.b64encode(data).decode()}}


COMPLETE = {'event_type': 'interaction.completed', 'interaction': {'status': 'completed', 'usage': {'total_output_tokens': 2}}}


class SSEStream(httpx.AsyncByteStream):
    def __init__(self, events=(), stall=False):
        self.events, self.stall, self.closed = events, stall, False

    async def __aiter__(self):
        for event in self.events:
            encoded = ('data: '+json.dumps(event)+'\n\n').encode()
            yield encoded[:7]
            yield encoded[7:]
        if self.stall:
            await asyncio.sleep(10)

    async def aclose(self):
        self.closed = True


@pytest.fixture
def mock_http(monkeypatch):
    original = httpx.AsyncClient
    def install(handler):
        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(
            **dict(kwargs, transport=httpx.MockTransport(handler))))
    return install


def engine(**settings):
    return GeminiTTSEngine(api_key='test-key', settings=dict(min_request_interval_seconds=0.0, **settings))


@pytest.mark.asyncio
async def test_stream_reassembles_pcm_and_preserves_generation_and_unknown_length(mock_http):
    stream = SSEStream([audio_event(b'\x01'), audio_event(b'\x00'+np.arange(1,1200, dtype='<i2').tobytes()), COMPLETE])
    mock_http(lambda request: httpx.Response(200, stream=stream))
    instance = engine()
    chunks = [chunk async for chunk in instance.synthesize_stream('朗讀測試', response_generation=9, turn_id='turn')]
    assert np.concatenate([c.pcm_data for c in chunks]).tolist() == [1]+list(range(1,1200))
    assert all(c.response_generation == 9 and c.turn_id == 'turn' for c in chunks)
    assert all(c.metadata.total_samples == 0 for c in chunks[:-1])
    assert chunks[-1].metadata.total_samples == 1200
    player = AudioPlayer()
    player._advance_playback_progress(chunks[0].metadata, len(chunks[0].pcm_data))
    assert player._capture_progress_snapshot().heard_text == ''
    assert instance.last_diagnostics['status'] == 'ok'
    assert stream.closed


@pytest.mark.asyncio
async def test_unary_wav_decodes_header_and_resamples_with_gain(mock_http):
    target = io.BytesIO()
    with wave.open(target, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes((np.ones(320, dtype='<i2')*100).tobytes())
    def handler(request):
        payload = json.loads(request.content)
        assert payload['response_format']['mime_type'] == 'audio/wav'
        assert 'thinking' not in json.dumps(payload)
        return httpx.Response(200, json={'status': 'completed', 'steps': [{'type': 'model_output',
            'content': [{'type': 'audio', 'mime_type': 'audio/wav', 'data': base64.b64encode(target.getvalue()).decode()}]}]})
    mock_http(handler)
    instance = GeminiTTSEngine(api_key='test-key', sample_rate=24000, streaming=False,
        settings={'audio_format': 'audio/wav', 'volume_gain': 2.0})
    chunks = [chunk async for chunk in instance.synthesize_stream('測試')]
    pcm = np.concatenate([c.pcm_data for c in chunks])
    assert len(pcm) == 480
    assert np.max(pcm) < 250
    assert np.median(pcm) == pytest.approx(200, abs=2)


@pytest.mark.asyncio
async def test_stream_error_after_audio_never_retries_or_repeats_same_generation(mock_http):
    calls = []
    def handler(request):
        calls.append(request)
        events = [audio_event(np.ones(1500, dtype='<i2').tobytes()),
            {'event_type': 'error'}] if len(calls)==1 else [audio_event(b'\x01\x00'*100), COMPLETE]
        return httpx.Response(200, stream=SSEStream(events))
    mock_http(handler)
    instance = engine()
    chunks = [c async for c in instance.synthesize_stream('first', response_generation=1)]
    assert chunks and len(calls) == 1
    assert instance.last_diagnostics['status'] == 'error'
    assert not [c async for c in instance.synthesize_stream('next sentence', response_generation=1)]
    assert len(calls) == 1
    assert [c async for c in instance.synthesize_stream('new turn', response_generation=2)]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_stream_retries_temporary_error_only_before_first_yield(mock_http):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503) if len(calls)==1 else httpx.Response(200,
            stream=SSEStream([audio_event(b'\x01\x00'*100), COMPLETE]))
    mock_http(handler)
    instance = engine()
    assert [c async for c in instance.synthesize_stream('test')]
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('events,reason', [
    ([audio_event(b'\x01'), COMPLETE], 'invalid_pcm_tail'),
    ([audio_event(b'\x01\x00')], 'incomplete_audio_stream'),
    ([COMPLETE], 'empty_audio'),
])
async def test_stream_rejects_incomplete_audio(mock_http, events, reason):
    stream = SSEStream(events)
    mock_http(lambda request: httpx.Response(200, stream=stream))
    instance = engine()
    assert not [c async for c in instance.synthesize_stream('test')]
    assert instance.last_diagnostics['reason'] == reason
    assert stream.closed


@pytest.mark.asyncio
async def test_cancel_during_read_closes_http_stream(mock_http):
    stream = SSEStream(stall=True)
    mock_http(lambda request: httpx.Response(200, stream=stream))
    instance = engine()
    cancel = threading.Event()
    async def collect():
        return [c async for c in instance.synthesize_stream('test', cancel)]
    task = asyncio.create_task(collect())
    await asyncio.sleep(.02)
    cancel.set()
    assert await asyncio.wait_for(task, .5) == []
    assert stream.closed
    await instance.aclose()
    assert not [c async for c in instance.synthesize_stream('closed')]


@pytest.mark.asyncio
async def test_engine_cancel_can_retire_request_without_disabling_next_turn(mock_http):
    streams = [SSEStream(stall=True), SSEStream([audio_event(b'\x01\x00'*100), COMPLETE])]
    mock_http(lambda request: httpx.Response(200, stream=streams.pop(0)))
    instance = engine()
    async def collect():
        return [c async for c in instance.synthesize_stream('test')]
    task = asyncio.create_task(collect())
    await asyncio.sleep(.02)
    instance.cancel()
    assert await asyncio.wait_for(task, .5) == []
    assert instance.last_diagnostics['status'] == 'cancelled'
    assert await collect()
    assert instance.last_diagnostics['status'] == 'ok'


@pytest.mark.asyncio
async def test_consumer_closing_after_first_chunk_releases_response_and_marks_cancelled(mock_http):
    stream = SSEStream([audio_event(b'\x01\x00'*1500), COMPLETE])
    mock_http(lambda request: httpx.Response(200, stream=stream))
    instance = engine()
    source = instance.synthesize_stream('test')
    assert len((await anext(source)).pcm_data) == 480
    instance.cancel()
    await source.aclose()
    assert stream.closed and not instance._clients and not instance._calls
    assert instance.last_diagnostics['status'] == 'cancelled'


@pytest.mark.asyncio
async def test_first_audio_timeout_is_not_reset_by_metadata_events(mock_http):
    class MetadataStream(SSEStream):
        async def __aiter__(self):
            while True:
                yield b'data: {"event_type":"step.start"}\n\n'
                await asyncio.sleep(.005)
    stream = MetadataStream()
    mock_http(lambda request: httpx.Response(200, stream=stream))
    instance = engine(first_audio_timeout_seconds=.03)
    started = time.monotonic()
    assert not [c async for c in instance.synthesize_stream('test')]
    assert time.monotonic()-started < .5
    assert instance.last_diagnostics['reason'] == 'timeout'
    assert stream.closed


@pytest.mark.asyncio
async def test_rate_limit_longer_than_deadline_does_not_retry(mock_http):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={'Retry-After':'60'})
    mock_http(handler)
    instance = engine(total_timeout_seconds=.1)
    assert not [c async for c in instance.synthesize_stream('test')]
    assert len(calls) == 1
    assert instance.last_diagnostics['http_status'] == 429
    assert not [c async for c in instance.synthesize_stream('next', response_generation=3)]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_cancel_at_lock_acquisition_releases_lock_for_next_turn(mock_http):
    mock_http(lambda request: httpx.Response(200,
        stream=SSEStream([audio_event(b'\x01\x00'*100), COMPLETE])))
    instance = engine()
    cancel = threading.Event()

    class CancelOnAcquire(asyncio.Lock):
        async def acquire(self):
            result = await super().acquire()
            cancel.set()
            return result

    instance._lock = CancelOnAcquire()
    assert not [c async for c in instance.synthesize_stream('cancelled', cancel)]
    assert not instance._lock.locked()
    assert instance.last_diagnostics['status'] == 'cancelled'
    # No interrupt signal on the new turn: the engine must remain usable.
    async def next_turn():
        return [c async for c in instance.synthesize_stream('next turn')]
    assert await asyncio.wait_for(next_turn(), 1)
