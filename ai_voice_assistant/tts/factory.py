from __future__ import annotations

import os

from tts.bluemagpie_tts_engine import BlueMagpieTTSEngine
from tts.edge_tts_engine import EdgeTTSEngine


def _normalize_backend_name(value: str | None) -> str:
    backend = (value or "edge").strip().lower()
    if backend in {"edge", "edge-tts", "edge_tts"}:
        return "edge"
    if backend in {"bluemagpie", "blue-magpie", "bluemagpie-tts"}:
        return "bluemagpie"
    return "edge"


def _resolve_app_path(app_dir: str, configured_path: str | None, fallback: str) -> str:
    raw_path = configured_path or fallback
    if not raw_path:
        return ""
    if os.path.isabs(raw_path):
        return raw_path
    return os.path.join(app_dir, raw_path)


def _optional_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return int(value)


def _int_setting(value, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, str) and value.strip() == "":
        return default
    return int(value)


def _float_setting(value, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, str) and value.strip() == "":
        return default
    return float(value)


def _bool_setting(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        stripped = value.strip().lower()
        if stripped in {"1", "true", "yes", "on"}:
            return True
        if stripped in {"0", "false", "no", "off", ""}:
            return False
    return bool(value)


def create_tts_engine(config, *, app_dir: str, sample_rate: int):
    backend = _normalize_backend_name(config.get("tts", "backend", default="edge"))
    if backend == "bluemagpie":
        bluemagpie_config = config.get("tts", "bluemagpie", default={}) or {}
        return BlueMagpieTTSEngine(
            app_dir=app_dir,
            enabled=_bool_setting(bluemagpie_config.get("enabled"), False),
            worker_python=_resolve_app_path(
                app_dir,
                bluemagpie_config.get("worker_python"),
                ".venv-bluemagpie/Scripts/python.exe",
            ),
            worker_script=_resolve_app_path(
                app_dir,
                bluemagpie_config.get("worker_script"),
                "tools/bluemagpie_tts_worker.py",
            ),
            model_dir=_resolve_app_path(
                app_dir,
                bluemagpie_config.get("model_dir"),
                "models/bluemagpie",
            ),
            hf_repo=bluemagpie_config.get("hf_repo", "OpenFormosa/BlueMagpie-TTS"),
            hf_token_env=bluemagpie_config.get("hf_token_env", "HF_TOKEN"),
            device=bluemagpie_config.get("device", "cuda"),
            cfg_value=_float_setting(bluemagpie_config.get("cfg_value"), 2.8),
            inference_timesteps=_int_setting(
                bluemagpie_config.get("inference_timesteps"),
                9,
            ),
            max_len=_int_setting(bluemagpie_config.get("max_len"), 2000),
            retry_badcase=_bool_setting(bluemagpie_config.get("retry_badcase"), True),
            seed=_optional_int(bluemagpie_config.get("seed")),
            fade_out_ms=_float_setting(bluemagpie_config.get("fade_out_ms"), 30.0),
            tail_silence_ms=_float_setting(
                bluemagpie_config.get("tail_silence_ms"),
                220.0,
            ),
            speaker_centroid_path=_resolve_app_path(
                app_dir,
                bluemagpie_config.get("speaker_centroid_path") or "",
                "",
            ),
            prompt_text=str(bluemagpie_config.get("prompt_text") or ""),
            prompt_wav_path=_resolve_app_path(
                app_dir,
                bluemagpie_config.get("prompt_wav_path") or "",
                "",
            ),
            seed_retry_count=_int_setting(
                bluemagpie_config.get("seed_retry_count"),
                5,
            ),
            min_rms=_float_setting(bluemagpie_config.get("min_rms"), 0.0005),
            min_nonzero_ratio=_float_setting(
                bluemagpie_config.get("min_nonzero_ratio"),
                0.001,
            ),
            warm_on_start=_bool_setting(
                bluemagpie_config.get("warm_on_start"),
                False,
            ),
            request_timeout_seconds=_float_setting(
                bluemagpie_config.get("request_timeout_seconds"),
                120.0,
            ),
            output_sample_rate=_int_setting(
                bluemagpie_config.get("output_sample_rate"),
                sample_rate,
            ),
            temp_dir=_resolve_app_path(
                app_dir,
                bluemagpie_config.get("temp_dir"),
                "logs/tts_tmp",
            ),
        )

    return EdgeTTSEngine(
        voice=config.get("tts", "voice"),
        sample_rate=sample_rate,
        rate=config.get("tts", "rate", default="+0%"),
        volume=config.get("tts", "volume", default="+0%"),
        streaming_decode=_bool_setting(
            config.get("pipeline_v2_5", "streaming_tts", default=False),
            False,
        ),
        streaming_decode_min_bytes=_int_setting(
            config.get(
                "pipeline_v2_5",
                "streaming_decode_min_bytes",
                default=1440,
            ),
            1440,
        ),
    )
