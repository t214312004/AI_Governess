import asyncio
import subprocess
from unittest.mock import AsyncMock

import numpy as np
import pytest

from core.audio_player import PlaybackChunk
from tts.bluemagpie_tts_engine import BlueMagpieTTSEngine


class MockAudioPlayer:
    sample_rate = 24000

    def __init__(self):
        self.played_data = []

    def play(self, data):
        self.played_data.append(data)


class FakeWorkerStdin:
    def __init__(self):
        self.writes = []

    def is_closing(self):
        return False

    def write(self, data):
        self.writes.append(data)

    async def drain(self):
        return None


class FakeWorkerProcess:
    def __init__(self):
        self.stdin = FakeWorkerStdin()
        self.returncode = None
        self.wait_count = 0
        self.terminated = False
        self.killed = False

    async def wait(self):
        self.wait_count += 1
        self.returncode = 0
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def build_engine(tmp_path, **overrides):
    kwargs = {
        "app_dir": str(tmp_path),
        "enabled": True,
        "worker_python": str(tmp_path / ".venv-bluemagpie" / "Scripts" / "python.exe"),
        "worker_script": str(tmp_path / "tools" / "bluemagpie_tts_worker.py"),
        "model_dir": str(tmp_path / "models" / "bluemagpie"),
        "hf_repo": "OpenFormosa/BlueMagpie-TTS",
        "hf_token_env": "HF_TOKEN",
        "device": "cuda",
        "cfg_value": 2.8,
        "inference_timesteps": 9,
        "max_len": 2000,
        "retry_badcase": True,
        "seed": None,
        "fade_out_ms": 30.0,
        "tail_silence_ms": 220.0,
        "speaker_centroid_path": "",
        "prompt_text": "",
        "prompt_wav_path": "",
        "seed_retry_count": 5,
        "min_rms": 0.0005,
        "min_nonzero_ratio": 0.001,
        "warm_on_start": False,
        "request_timeout_seconds": 30.0,
        "output_sample_rate": 24000,
        "temp_dir": str(tmp_path / "logs" / "tts_tmp"),
        "chunk_samples": 4,
    }
    kwargs.update(overrides)
    return BlueMagpieTTSEngine(**kwargs)


@pytest.mark.asyncio
async def test_bluemagpie_disabled_skips_without_worker(tmp_path):
    engine = build_engine(tmp_path, enabled=False)
    player = MockAudioPlayer()

    result = await engine.speak_stream("你好", player)

    assert result.played is False
    assert result.reason == "disabled"
    assert player.played_data == []


@pytest.mark.asyncio
async def test_bluemagpie_missing_worker_python_fails_without_crashing(tmp_path):
    engine = build_engine(tmp_path)
    player = MockAudioPlayer()

    result = await engine.speak_stream("你好", player)

    assert result.played is False
    assert result.reason == "worker_python_missing"
    assert player.played_data == []


@pytest.mark.asyncio
async def test_bluemagpie_speak_stream_loads_pcm_and_attaches_ratio_metadata(tmp_path, mocker):
    pcm_path = tmp_path / "tts.npy"
    np.save(pcm_path, np.arange(10, dtype=np.int16))
    engine = build_engine(tmp_path)
    log_event = mocker.patch("tts.bluemagpie_tts_engine.log_event")
    mocker.patch.object(
        engine,
        "_send_worker_request",
        new=AsyncMock(
            return_value={
                "ok": True,
                "sample_rate": 24000,
                "pcm_path": str(pcm_path),
                "duration_seconds": 0.25,
                "generation_seconds": 1.5,
                "rtf": 6.0,
                "speaker_centroid_used": True,
                "prompt_wav_used": True,
                "seed": 20260627,
                "base_seed": 20260627,
                "seed_attempt": 0,
                "seed_retry_count": 5,
                "fade_out_ms": 30.0,
                "tail_silence_ms": 220.0,
                "audio_rms": 0.125,
                "audio_peak": 0.5,
                "audio_nonzero_ratio": 0.9,
            }
        ),
    )
    player = MockAudioPlayer()

    result = await engine.speak_stream("測試句子", player)

    assert result.played is True
    assert not pcm_path.exists()
    assert len(player.played_data) == 3
    assert all(isinstance(chunk, PlaybackChunk) for chunk in player.played_data)
    first_chunk = player.played_data[0]
    assert first_chunk.metadata is not None
    assert first_chunk.metadata.sentence_text == "測試句子"
    assert first_chunk.metadata.boundaries == ()
    assert first_chunk.metadata.total_samples == 10
    generated_calls = [
        call for call in log_event.call_args_list
        if call.args[2] == "tts.bluemagpie.sentence_generated"
    ]
    assert len(generated_calls) == 1
    generated = generated_calls[0]
    assert generated.kwargs["text_chars"] == 4
    assert generated.kwargs["generation_seconds"] == 1.5
    assert generated.kwargs["rtf"] == 6.0
    assert generated.kwargs["speaker_centroid_used"] is True
    assert generated.kwargs["prompt_wav_used"] is True
    assert generated.kwargs["seed"] == 20260627
    assert "text" not in generated.kwargs
    assert "prompt_text" not in generated.kwargs


@pytest.mark.asyncio
async def test_bluemagpie_speak_stream_rejects_sample_rate_mismatch(tmp_path, mocker):
    pcm_path = tmp_path / "tts.npy"
    np.save(pcm_path, np.arange(10, dtype=np.int16))
    engine = build_engine(tmp_path)
    mocker.patch.object(
        engine,
        "_send_worker_request",
        new=AsyncMock(
            return_value={
                "ok": True,
                "sample_rate": 48000,
                "pcm_path": str(pcm_path),
            }
        ),
    )
    player = MockAudioPlayer()

    result = await engine.speak_stream("測試句子", player)

    assert result.played is False
    assert result.reason == "sample_rate_mismatch"
    assert player.played_data == []
    assert not pcm_path.exists()


@pytest.mark.asyncio
async def test_bluemagpie_speak_stream_respects_pre_request_interrupt(tmp_path, mocker):
    engine = build_engine(tmp_path)
    send = mocker.patch.object(engine, "_send_worker_request", new=AsyncMock())
    player = MockAudioPlayer()
    interrupt_signal = asyncio.Event()
    interrupt_signal.set()

    result = await engine.speak_stream("測試句子", player, interrupt_signal)

    assert result.played is False
    assert result.reason == "interrupted"
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_bluemagpie_warm_up_sends_warmup_payload(tmp_path, mocker):
    engine = build_engine(
        tmp_path,
        prompt_text="fixed prompt",
        prompt_wav_path=str(tmp_path / "prompt.wav"),
        speaker_centroid_path=str(tmp_path / "style.pt"),
    )
    send = mocker.patch.object(
        engine,
        "_send_worker_payload",
        new=AsyncMock(
            return_value={
                "ok": True,
                "warmup_seconds": 1.25,
                "speaker_centroid_used": True,
                "prompt_wav_used": True,
            }
        ),
    )

    response = await engine.warm_up()

    assert response["ok"] is True
    send.assert_awaited_once()
    payload = send.await_args.args[0]
    assert payload["command"] == "warmup"
    assert payload["prompt_text"] == "fixed prompt"
    assert payload["prompt_wav_path"].endswith("prompt.wav")
    assert payload["speaker_centroid_path"].endswith("style.pt")


@pytest.mark.asyncio
async def test_bluemagpie_aclose_sends_worker_shutdown(tmp_path):
    engine = build_engine(tmp_path)
    process = FakeWorkerProcess()
    engine._worker_process = process

    await engine.aclose(timeout_seconds=0.1)

    assert engine._worker_process is None
    assert process.wait_count == 1
    assert process.terminated is False
    assert process.killed is False
    assert process.stdin.writes == [b'{"command": "shutdown"}\n']


@pytest.mark.asyncio
async def test_bluemagpie_worker_starts_hidden_on_windows(tmp_path, mocker):
    engine = build_engine(tmp_path)
    worker_python = tmp_path / ".venv-bluemagpie" / "Scripts" / "python.exe"
    worker_script = tmp_path / "tools" / "bluemagpie_tts_worker.py"
    worker_python.parent.mkdir(parents=True)
    worker_script.parent.mkdir(parents=True)
    worker_python.write_text("", encoding="utf-8")
    worker_script.write_text("", encoding="utf-8")
    create_process = mocker.patch(
        "tts.bluemagpie_tts_engine.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=FakeWorkerProcess()),
    )

    status = await engine._ensure_worker()

    assert status["ok"] is True
    kwargs = create_process.await_args.kwargs
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
    else:
        assert "creationflags" not in kwargs
