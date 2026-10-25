"""One cancellable startup preview job; worker threads never access Tk."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
import queue
import threading
import time

import av
import httpx
import numpy as np

from utils.gemini_audio import GeminiAPIError, resolve_api_key
from utils.gemini_transport import bounded, response_error
from utils.audio_devices import resolve_audio_device


class DraftConfig:
    def __init__(self, settings):
        self.settings = deepcopy(settings)

    def get(self, *keys, default=None):
        value = self.settings
        for key in keys:
            if not isinstance(value, dict) or key not in value:
                return default
            value = value[key]
        return value


class PreviewSignal:
    """Adapt a thread-safe UI cancellation flag to the engines' async Event API."""
    def __init__(self, event):
        self.event = event

    def is_set(self):
        return self.event.is_set()

    async def wait(self):
        while not self.is_set():
            await asyncio.sleep(.02)
        return True


class AudioPreviewController:
    def __init__(self):
        self.events = queue.SimpleQueue()
        self.thread = None
        self.token = 0
        self.cancel_event = threading.Event()
        self._resources = []
        self._lock = threading.Lock()

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, work):
        if self.busy:
            return None
        self.token += 1
        token = self.token
        self.cancel_event = threading.Event()
        cancel = self.cancel_event
        def worker():
            try:
                result = work(cancel, self)
                self.events.put((token, "cancelled" if cancel.is_set() else "ok", result))
            except asyncio.CancelledError:
                self.events.put((token, "cancelled", None))
            except Exception as exc:
                reason = str(exc) if isinstance(exc, (GeminiAPIError, ValueError)) else type(exc).__name__
                self.events.put((token, "error", reason))
            finally:
                with self._lock:
                    self._resources.clear()
        self.thread = threading.Thread(target=worker, name="audio-preview", daemon=True)
        self.thread.start()
        return token

    def own(self, resource):
        with self._lock:
            self._resources.append(resource)
        if self.cancel_event.is_set():
            self.cancel()

    def progress(self, message, level=None):
        self.events.put((self.token, 'progress', {'message':message, 'level':level}))

    def cancel(self):
        self.cancel_event.set()
        with self._lock:
            resources = tuple(self._resources)
        for resource in resources:
            method = getattr(resource, "interrupt", None) or getattr(resource, "cancel", None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass  # Worker finally owns potentially blocking resource cleanup.


def read_audio(path, sample_rate, max_seconds):
    frames, count = [], 0
    with av.open(str(path)) as source:
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=sample_rate)
        for decoded in source.decode(audio=0):
            for frame in resampler.resample(decoded):
                pcm = frame.to_ndarray().reshape(-1)
                count += len(pcm)
                if count > max_seconds*sample_rate:
                    raise GeminiAPIError("audio_too_long")
                frames.append(pcm)
        for frame in resampler.resample(None):
            frames.append(frame.to_ndarray().reshape(-1))
    result = np.concatenate(frames).astype(np.float32) if frames else np.empty(0, np.float32)
    if len(result) > max_seconds*sample_rate:
        raise GeminiAPIError("audio_too_long")
    return result


def record_audio(settings, cancel, owner, seconds=5):
    import sounddevice as sd
    sr=settings['audio']['input_sample_rate']
    parts=[]
    with sd.InputStream(samplerate=sr,channels=1,dtype='float32',blocksize=sr//10,
            device=resolve_audio_device(settings['audio'].get('input_device'),'input')) as stream:
        for tick in range(seconds*10):
            if cancel.is_set(): raise asyncio.CancelledError
            data,_=stream.read(sr//10)
            parts.append(data[:,0].copy())
            owner.progress(f'錄音中：{(tick+1)/10:.1f} / {seconds} 秒',min(1.,float(np.sqrt(np.mean(data**2)))*8))
    return np.concatenate(parts)


def stt_preview(settings, path=None):
    def work(cancel, owner):
        from core.transcriber import BackgroundTranscriber, NOISY_TRANSCRIPT_PLACEHOLDER
        cfg = DraftConfig(settings)
        sr = cfg.get("audio", "input_sample_rate", default=16000)
        if path is None:
            audio = record_audio(settings,cancel,owner)
        else:
            audio = read_audio(path, sr, cfg.get("whisper", "gemini", "max_audio_seconds", default=60.0))
        if cancel.is_set():
            raise asyncio.CancelledError
        groq = cfg.get("whisper", "groq", default={})
        gate = groq.get("confidence_gate", {})
        transcriber = BackgroundTranscriber(backend=cfg.get("whisper", "backend", default="local"),
            model_size=cfg.get("whisper", "model_size", default="small"),
            device=cfg.get("whisper", "device", default="cpu"),
            compute_type=cfg.get("whisper", "compute_type", default="int8"),
            language=cfg.get("whisper", "language", default="zh"),
            initial_prompt=cfg.get("whisper", "initial_prompt", default=""),
            gemini_api_key=cfg.get("gemini", "api_key", default=""),
            gemini_api_key_env=cfg.get("gemini", "api_key_env", default="GEMINI_API_KEY"),
            gemini_settings=cfg.get("whisper", "gemini", default={}), input_sample_rate=sr,
            groq_api_key=groq.get("api_key"), groq_api_key_env=groq.get("api_key_env", "GROQ_API_KEY"),
            groq_model=groq.get("model", "whisper-large-v3"),
            groq_api_url=groq.get("api_url", "https://api.groq.com/openai/v1/audio/transcriptions"),
            groq_timeout_seconds=groq.get("timeout_seconds", 30),
            **{"groq_confidence_gate_"+key: value for key, value in gate.items() if key in
                ("enabled", "avg_logprob_threshold", "no_speech_prob_threshold", "temperature_threshold", "min_transcript_similarity")})
        owner.own(transcriber)
        started = time.monotonic()
        try:
            deadline = time.monotonic()+180
            while not transcriber.wait_until_ready(.05):
                if cancel.is_set():
                    raise asyncio.CancelledError
                if transcriber.load_error:
                    raise GeminiAPIError("stt_initialization_failed")
                if time.monotonic() >= deadline:
                    raise GeminiAPIError("timeout")
            if cancel.is_set():
                raise asyncio.CancelledError
            text = transcriber.transcribe(audio)
            diagnostics = transcriber.last_diagnostics
            if diagnostics.get("status") == "error":
                raise GeminiAPIError(diagnostics["reason"])
            return {"message": f"辨識完成，耗時 {(time.monotonic()-started):.2f} 秒；{diagnostics.get('attempts', 1)} 次請求",
                    "text": text or "（沒有可辨識的人聲）", 'check_passed':bool(text and text!=NOISY_TRANSCRIPT_PLACEHOLDER)}
        finally:
            transcriber.close()
    return work


def tts_preview(settings, text):
    def work(cancel, owner):
        from core.audio_player import AudioPlayer
        from tts.factory import create_tts_engine
        cfg = DraftConfig(settings)
        player = AudioPlayer(sample_rate=cfg.get("audio", "output_sample_rate", default=24000),
            device=resolve_audio_device(cfg.get('audio','output_device'),'output'))
        engine = create_tts_engine(cfg, app_dir=str(Path(__file__).resolve().parents[1]), sample_rate=player.sample_rate)
        owner.own(engine)
        owner.own(player)
        async def run():
            try:
                if cancel.is_set():
                    raise asyncio.CancelledError
                player.start()
                result = await engine.speak_stream(text, player, PreviewSignal(cancel))
                diagnostics = getattr(engine, "last_diagnostics", {})
                if diagnostics.get("status") == "error":
                    raise GeminiAPIError(diagnostics["reason"], diagnostics.get("http_status"))
                if result is not None and not result.played and not cancel.is_set():
                    raise ValueError('語音輸出未播放：'+str(result.reason or 'empty_audio'))
                while player.is_playing and not cancel.is_set():
                    await asyncio.sleep(.03)
                return {"message": "試聽完成", "text": text}
            finally:
                player.stop()
                close = getattr(engine, "aclose", None)
                if callable(close):
                    await close()
                elif callable(getattr(engine, "close", None)):
                    engine.close()
        return asyncio.run(run())
    return work


def google_catalog(settings, kind):
    def work(cancel, owner):
        cfg = DraftConfig(settings)
        key = resolve_api_key(cfg.get("gemini", "api_key", default=""), cfg.get("gemini", "api_key_env", default="GEMINI_API_KEY"))
        async def run():
            async with httpx.AsyncClient(timeout=15) as client:
                endpoint = "voices" if kind == "voices" else "models"
                names, voices, seen = [], [], set()
                token = None
                deadline = time.monotonic()+15
                for _ in range(10):
                    params = {('page_token' if kind == 'voices' else 'pageToken'): token} if token else None
                    response = await bounded(client.get("https://generativelanguage.googleapis.com/v1beta/"+endpoint,
                        headers={"x-goog-api-key": key}, params=params), signal=cancel, deadline=deadline)
                    response_error(response)
                    payload = response.json()
                    if not isinstance(payload, dict) or not isinstance(payload.get(endpoint, []), list):
                        raise GeminiAPIError("invalid_response")
                    for item in payload.get(endpoint, []):
                        if not isinstance(item, dict):
                            continue
                        name = item.get("id") or item.get("name") or item.get("voice_id") or item.get("voice")
                        if isinstance(name, str) and name:
                            identifier = name.rsplit("/", 1)[-1]
                            if identifier not in names:
                                names.append(identifier)
                                if kind == 'voices':
                                    voices.append({'id': identifier, 'display_name': item.get('display_name', identifier),
                                                   'language_code': item.get('language_code', '')})
                        if len(names) >= 500:
                            break
                    token = payload.get('next_page_token') or payload.get('nextPageToken')
                    if not token or token in seen or len(names) >= 500:
                        break
                    seen.add(token)
                message = f'Google 連線成功；已取得 {len(names)} 筆'+('音色' if kind == 'voices' else '模型')
                if token:
                    message += '（清單有上限，可另外輸入 ID）'
                return {"message": message, "catalog_kind": kind, "names": names, 'voices': voices}
        return asyncio.run(run())
    return work


def validate_google_selection(settings, cancel_event=None):
    """Read-only startup preflight; never generates billable speech."""
    cfg = DraftConfig(settings)
    models = []
    if cfg.get('interaction', 'voice_input', default=True) and cfg.get('whisper', 'backend') == 'gemini':
        models.append(cfg.get('whisper', 'gemini', 'model', default='gemini-3.8-flash'))
    if cfg.get('interaction', 'voice_output', default=True) and cfg.get('tts', 'backend') == 'gemini':
        models.append(cfg.get('tts', 'gemini', 'model', default='gemini-3.8-flash-tts'))
    if not models:
        return
    key = resolve_api_key(cfg.get('gemini', 'api_key', default=''), cfg.get('gemini', 'api_key_env', default='GEMINI_API_KEY'))
    async def check():
        async with httpx.AsyncClient(timeout=10) as client:
            deadline = time.monotonic()+15
            for model in dict.fromkeys(models):
                response = await bounded(client.get('https://generativelanguage.googleapis.com/v1beta/models/'+model,
                    headers={'x-goog-api-key': key}), signal=cancel_event, deadline=deadline)
                response_error(response)
    try:
        asyncio.run(check())
    except asyncio.CancelledError:
        raise GeminiAPIError('cancelled') from None
    except GeminiAPIError:
        raise
    except Exception:
        raise GeminiAPIError('preflight_failed') from None
