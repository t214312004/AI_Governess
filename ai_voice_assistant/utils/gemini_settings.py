"""Supported Gemini audio settings, shared by runtime and startup validation."""
from copy import deepcopy
import math
import re

from utils.gemini_audio import STT_MODEL, TTS_MODEL, TRANSCRIPTION_PROMPT

DEFAULT_VOICES = ("Leda", "Zephyr")
STT_DEFAULTS = {
    "model": STT_MODEL, "thinking_level": "low", "transcription_prompt": TRANSCRIPTION_PROMPT,
    "vocabulary_hints": [], "max_output_tokens": 4096, "max_audio_seconds": 60.0,
    "connect_timeout_seconds": 5.0, "request_timeout_seconds": 15.0,
    "total_timeout_seconds": 20.0, "max_retries": 1,
    "speech_gate_enabled": True, "speech_gate_threshold": 0.5,
    "speech_gate_min_ms": 100, "max_chars_per_second": 40.0,
    "repetition_limit": 6,
}
TTS_DEFAULTS = {
    "model": TTS_MODEL, "voice": "Leda",
    "style": "以自然、溫暖的台灣華語朗讀，速度適中，英文照原文發音。",
    "volume_gain": 1.0, "audio_format": "audio/l16", "api_sample_rate": 24000,
    "connect_timeout_seconds": 5.0, "first_audio_timeout_seconds": 15.0,
    "stream_idle_timeout_seconds": 10.0, "total_timeout_seconds": 660.0,
    "max_retries": 1, "min_request_interval_seconds": 8.0,
    "max_audio_seconds": 600.0, "first_chunk_min_chars": 200,
    "chunk_min_chars": 800, "chunk_max_chars": 1800,
}


def audio_settings(kind: str, values=None) -> dict:
    defaults = STT_DEFAULTS if kind == "stt" else TTS_DEFAULTS
    settings = deepcopy(defaults)
    if values is not None:
        if not isinstance(values, dict):
            raise ValueError("Gemini 設定必須是 object")
        settings.update(values)
    for key, default in defaults.items():
        value = settings[key]
        if type(value) is not type(default):
            # JSON integers are acceptable for explicitly floating settings.
            if type(default) is float and type(value) is int:
                settings[key] = value = float(value)
            else:
                raise ValueError(f"Gemini {key}：型別不符")
        if type(value) in (int, float) and not math.isfinite(value):
            raise ValueError(f"Gemini {key}：必須是有限數值")
        if ("timeout_seconds" in key or key in ("max_audio_seconds", "max_output_tokens",
                "speech_gate_min_ms", "max_chars_per_second", "repetition_limit",
                "first_chunk_min_chars", "chunk_min_chars", "chunk_max_chars")) and value <= 0:
            raise ValueError(f"Gemini {key}：必須大於 0")
    if not re.fullmatch(r"gemini-[A-Za-z0-9._-]+", settings["model"]):
        raise ValueError("請輸入 Gemini 模型 ID")
    if settings["max_retries"] not in (0, 1):
        raise ValueError("Gemini 重試次數只能是 0 或 1")
    if settings["max_audio_seconds"] > 600:
        raise ValueError("Gemini 音訊上限不得超過 600 秒")
    if kind == "stt":
        if settings["thinking_level"] not in ("low", "medium", "high"):
            raise ValueError("Gemini STT thinking 只支援 low／medium／high")
        if not settings["transcription_prompt"].strip():
            raise ValueError("Gemini 轉錄指示不可空白")
        if not all(isinstance(v, str) for v in settings["vocabulary_hints"]):
            raise ValueError("Gemini 詞彙提示必須是字串清單")
        if not 0 < settings["speech_gate_threshold"] < 1:
            raise ValueError("Gemini 人聲門檻必須介於 0–1（不含端點）")
        if not 64 <= settings["max_output_tokens"] <= 65536:
            raise ValueError("Gemini STT output tokens 必須介於 64–65536")
        if not 2 <= settings["repetition_limit"] <= 20:
            raise ValueError("Gemini 重複片段門檻必須介於 2–20")
    else:
        if not settings["voice"].strip():
            raise ValueError("Gemini 音色不可空白")
        if settings["audio_format"] not in ("audio/l16", "audio/wav"):
            raise ValueError("Gemini 音訊格式只支援 audio/l16／audio/wav")
        if settings["api_sample_rate"] not in (8000, 16000, 24000):
            raise ValueError("Gemini API sample rate 只支援 8000／16000／24000")
        if not 0 <= settings["volume_gain"] <= 2:
            raise ValueError("Gemini 播放音量必須介於 0–2")
        if not 0 <= settings["min_request_interval_seconds"] <= 120:
            raise ValueError("Gemini 呼叫間隔必須介於 0–120 秒")
        if not settings["first_chunk_min_chars"] <= settings["chunk_max_chars"] or not settings["chunk_min_chars"] <= settings["chunk_max_chars"]:
            raise ValueError("Gemini TTS 最少分段字數不得大於最大字數")
        if settings["chunk_max_chars"] > 2000:
            raise ValueError("Gemini TTS 每段最多 2000 字")
        if settings["min_request_interval_seconds"] >= settings["total_timeout_seconds"]:
            raise ValueError("Gemini 呼叫間隔必須小於總逾時秒數")
    return settings
