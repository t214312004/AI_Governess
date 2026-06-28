from tts.bluemagpie_tts_engine import BlueMagpieTTSEngine
from tts.edge_tts_engine import EdgeTTSEngine
from tts.factory import create_tts_engine


class DictConfig:
    def __init__(self, values):
        self.values = values

    def get(self, *keys, default=None):
        value = self.values
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value


def test_create_tts_engine_defaults_to_edge(tmp_path):
    cfg = DictConfig(
        {
            "tts": {
                "voice": "zh-TW-HsiaoChenNeural",
                "rate": "+10%",
                "volume": "+5%",
            }
        }
    )

    engine = create_tts_engine(cfg, app_dir=str(tmp_path), sample_rate=24000)

    assert isinstance(engine, EdgeTTSEngine)
    assert engine.sample_rate == 24000
    assert engine.rate == "+10%"


def test_create_tts_engine_builds_bluemagpie_with_app_relative_paths(tmp_path):
    cfg = DictConfig(
        {
            "tts": {
                "backend": "bluemagpie",
                "bluemagpie": {
                    "enabled": True,
                    "worker_python": ".venv-bluemagpie/Scripts/python.exe",
                    "worker_script": "tools/bluemagpie_tts_worker.py",
                    "model_dir": "models/bluemagpie",
                    "temp_dir": "logs/tts_tmp",
                    "speaker_centroid_path": "",
                    "prompt_text": "fixed voice prompt",
                    "prompt_wav_path": "voice_profiles/tts_prompts/example_prompt.wav",
                    "seed_retry_count": 7,
                    "min_rms": 0.0007,
                    "min_nonzero_ratio": 0.002,
                    "warm_on_start": True,
                    "seed": 1234,
                    "fade_out_ms": 25,
                    "tail_silence_ms": 180,
                },
            }
        }
    )

    engine = create_tts_engine(cfg, app_dir=str(tmp_path), sample_rate=24000)

    assert isinstance(engine, BlueMagpieTTSEngine)
    assert engine.enabled is True
    assert engine.worker_python.replace("\\", "/").endswith(".venv-bluemagpie/Scripts/python.exe")
    assert engine.worker_script.replace("\\", "/").endswith("tools/bluemagpie_tts_worker.py")
    assert engine.model_dir.replace("\\", "/").endswith("models/bluemagpie")
    assert engine.speaker_centroid_path == ""
    assert engine.prompt_text == "fixed voice prompt"
    assert engine.prompt_wav_path.replace("\\", "/").endswith(
        "voice_profiles/tts_prompts/example_prompt.wav"
    )
    assert engine.seed_retry_count == 7
    assert engine.min_rms == 0.0007
    assert engine.min_nonzero_ratio == 0.002
    assert engine.warm_on_start is True
    assert engine.request_timeout_seconds == 120.0
    assert engine.seed == 1234
    assert engine.fade_out_ms == 25.0
    assert engine.tail_silence_ms == 180.0


def test_create_tts_engine_parses_bluemagpie_string_settings(tmp_path):
    cfg = DictConfig(
        {
            "tts": {
                "backend": "bluemagpie",
                "bluemagpie": {
                    "enabled": "false",
                    "retry_badcase": "false",
                    "warm_on_start": "false",
                    "cfg_value": "",
                    "inference_timesteps": "",
                    "max_len": "",
                    "fade_out_ms": "",
                    "tail_silence_ms": "",
                    "request_timeout_seconds": "",
                    "output_sample_rate": "",
                },
            }
        }
    )

    engine = create_tts_engine(cfg, app_dir=str(tmp_path), sample_rate=24000)

    assert isinstance(engine, BlueMagpieTTSEngine)
    assert engine.enabled is False
    assert engine.retry_badcase is False
    assert engine.warm_on_start is False
    assert engine.cfg_value == 2.8
    assert engine.inference_timesteps == 9
    assert engine.max_len == 2000
    assert engine.fade_out_ms == 30.0
    assert engine.tail_silence_ms == 220.0
    assert engine.request_timeout_seconds == 120.0
    assert engine.output_sample_rate == 24000
