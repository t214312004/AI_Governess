import io
import json

import numpy as np

from tools.bluemagpie_tts_worker import BlueMagpieWorker, run_jsonl_loop


class FakeCuda:
    def __init__(self):
        self.seed = None

    def is_available(self):
        return True

    def manual_seed_all(self, seed):
        self.seed = seed


class FakeInferenceMode:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeTorch:
    def __init__(self):
        self.seed = None
        self.cuda = FakeCuda()

    def manual_seed(self, seed):
        self.seed = seed

    def inference_mode(self):
        return FakeInferenceMode()


class FakeModel:
    sample_rate = 24000

    def __init__(self, outputs=None):
        self.outputs = list(outputs or [])
        self.generate_calls = []
        self.generate_kwargs = None

    def generate(self, **kwargs):
        self.generate_kwargs = kwargs
        self.generate_calls.append(kwargs)
        if self.outputs:
            return self.outputs.pop(0)
        return np.ones(24, dtype=np.float32) * 0.5


def build_worker(tmp_path):
    return BlueMagpieWorker(
        model_dir=str(tmp_path / "models" / "bluemagpie"),
        hf_repo="OpenFormosa/BlueMagpie-TTS",
        hf_token_env="HF_TOKEN",
        device="cpu",
        output_dir=str(tmp_path / "logs" / "tts_tmp"),
    )


def test_float_to_int16_normalizes_only_when_needed(tmp_path):
    worker = build_worker(tmp_path)

    pcm = worker._float_to_int16(np.array([-2.0, 0.0, 2.0], dtype=np.float32))

    assert pcm.dtype == np.int16
    assert pcm.tolist() == [-32767, 0, 32767]


def test_resample_fallback_preserves_duration_when_librosa_unavailable(tmp_path, mocker):
    worker = build_worker(tmp_path)
    mocker.patch.dict("sys.modules", {"librosa": None})
    waveform = np.ones(48000, dtype=np.float32)

    resampled = worker._resample_if_needed(
        waveform,
        source_sample_rate=48000,
        output_sample_rate=24000,
    )

    assert resampled.dtype == np.float32
    assert len(resampled) == 24000


def test_apply_tail_processing_fades_and_appends_silence(tmp_path):
    worker = build_worker(tmp_path)

    processed = worker._apply_tail_processing(
        np.ones(10, dtype=np.float32),
        sample_rate=1000,
        fade_out_ms=4,
        tail_silence_ms=5,
    )

    assert len(processed) == 15
    assert processed[0] == 1.0
    assert processed[9] == 0.0
    assert processed[-5:].tolist() == [0.0] * 5


def test_warmup_loads_model_and_validates_prompt_without_generating(tmp_path):
    worker = build_worker(tmp_path)
    fake_model = FakeModel()
    fake_torch = FakeTorch()
    prompt_path = tmp_path / "prompt.wav"
    prompt_path.write_bytes(b"not-a-real-wav-for-mocked-model")
    worker.model = fake_model
    worker.torch = fake_torch

    response = worker.warmup(
        {
            "request_id": "warm",
            "prompt_text": "prompt",
            "prompt_wav_path": str(prompt_path),
        }
    )

    assert response["ok"] is True
    assert response["request_id"] == "warm"
    assert response["sample_rate"] == 24000
    assert response["prompt_wav_used"] is True
    assert fake_model.generate_calls == []


def test_synthesize_applies_seed_and_tail_metadata(tmp_path):
    worker = build_worker(tmp_path)
    fake_model = FakeModel()
    fake_torch = FakeTorch()
    worker.model = fake_model
    worker.torch = fake_torch

    response = worker.synthesize(
        {
            "request_id": "seeded",
            "text": "hello",
            "seed": 1234,
            "fade_out_ms": 1,
            "tail_silence_ms": 1,
            "output_sample_rate": 24000,
        }
    )

    assert response["ok"] is True
    assert response["seed"] == 1234
    assert response["base_seed"] == 1234
    assert response["seed_attempt"] == 0
    assert response["attempted_seeds"] == [1234]
    assert response["fade_out_ms"] == 1.0
    assert response["tail_silence_ms"] == 1.0
    assert response["audio_rms"] > 0.0
    assert response["audio_peak"] > 0.0
    assert response["audio_nonzero_ratio"] > 0.0
    assert fake_torch.seed == 1234
    assert fake_torch.cuda.seed == 1234
    pcm = np.load(response["pcm_path"])
    assert len(pcm) == 48


def test_synthesize_retries_seed_when_audio_is_silent(tmp_path):
    worker = build_worker(tmp_path)
    fake_model = FakeModel(
        outputs=[
            np.zeros(24, dtype=np.float32),
            np.ones(24, dtype=np.float32) * 0.25,
        ]
    )
    fake_torch = FakeTorch()
    worker.model = fake_model
    worker.torch = fake_torch

    response = worker.synthesize(
        {
            "request_id": "retry-silent",
            "text": "hello",
            "seed": 20260627,
            "seed_retry_count": 1,
            "min_rms": 0.0005,
            "min_nonzero_ratio": 0.001,
            "output_sample_rate": 24000,
        }
    )

    assert response["ok"] is True
    assert response["seed"] == 20260628
    assert response["base_seed"] == 20260627
    assert response["seed_attempt"] == 1
    assert response["attempted_seeds"] == [20260627, 20260628]
    assert response["audio_rms"] > 0.0
    assert len(fake_model.generate_calls) == 2
    assert fake_torch.seed == 20260628


def test_synthesize_passes_prompt_conditioning_when_both_fields_are_set(tmp_path):
    worker = build_worker(tmp_path)
    fake_model = FakeModel()
    fake_torch = FakeTorch()
    prompt_path = tmp_path / "prompt.wav"
    prompt_path.write_bytes(b"not-a-real-wav-for-mocked-model")
    worker.model = fake_model
    worker.torch = fake_torch

    response = worker.synthesize(
        {
            "request_id": "prompted",
            "text": "hello",
            "prompt_text": "prompt",
            "prompt_wav_path": str(prompt_path),
            "output_sample_rate": 24000,
        }
    )

    assert response["ok"] is True
    assert response["prompt_wav_used"] is True
    assert fake_model.generate_kwargs["prompt_text"] == "prompt"
    assert fake_model.generate_kwargs["prompt_wav_path"] == str(prompt_path)


def test_jsonl_loop_decodes_utf8_requests_and_writes_utf8_responses():
    class FakeWorker:
        def __init__(self):
            self.request = None

        def synthesize(self, request):
            self.request = request
            return {
                "request_id": request["request_id"],
                "ok": True,
                "echo": request["text"],
            }

        def warmup(self, request):
            raise AssertionError("warmup should not be called")

    request = {
        "request_id": "utf8",
        "text": "你好，這是測試。",
        "prompt_text": "這是一段提示文字。",
    }
    input_buffer = io.BytesIO((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
    output_buffer = io.BytesIO()
    worker = FakeWorker()

    run_jsonl_loop(worker, input_buffer, output_buffer)

    assert worker.request["text"] == "你好，這是測試。"
    output = json.loads(output_buffer.getvalue().decode("utf-8"))
    assert output["ok"] is True
    assert output["echo"] == "你好，這是測試。"


def test_synthesize_parses_retry_badcase_string_false(tmp_path):
    worker = build_worker(tmp_path)
    fake_model = FakeModel()
    fake_torch = FakeTorch()
    worker.model = fake_model
    worker.torch = fake_torch

    response = worker.synthesize(
        {
            "request_id": "retry-string-false",
            "text": "hello",
            "retry_badcase": "false",
            "output_sample_rate": 24000,
        }
    )

    assert response["ok"] is True
    assert fake_model.generate_kwargs["retry_badcase"] is False
