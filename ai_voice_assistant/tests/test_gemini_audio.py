import base64
import io
import json
import wave

import httpx
import numpy as np
import pytest

from utils.gemini_audio import (GeminiAPIError, check_response, estimated_cost,
    model_content, read_key_file, resolve_api_key, stt_payload, transcribe_wav,
    tts_payload, wav_bytes, sse_messages)
from tools.benchmark_audio_backends import edit_distance, normalize, summarize


def test_key_file_accepts_opaque_labeled_key_and_rejects_ambiguity(tmp_path):
    path = tmp_path / "key.txt"
    path.write_text("[Google AI Studio]\nAPI Key: opaque-test-key\nName: demo\n", encoding="utf-8")
    assert read_key_file(path) == "opaque-test-key"
    path.write_text("API Key: one\nAPI Key: two\n", encoding="utf-8")
    with pytest.raises(GeminiAPIError, match="ambiguous_key_file"):
        read_key_file(path)


def test_key_precedence_and_missing_key(monkeypatch):
    monkeypatch.setenv("EXAMPLE_GOOGLE_KEY", "env-test-key")
    assert resolve_api_key("stored-test-key", "EXAMPLE_GOOGLE_KEY") == "stored-test-key"
    assert resolve_api_key("", "EXAMPLE_GOOGLE_KEY") == "env-test-key"
    with pytest.raises(GeminiAPIError, match="missing_api_key"):
        resolve_api_key("", "MISSING_TEST_KEY")


def test_wav_encoding_clips_and_rejects_invalid_samples():
    encoded = wav_bytes(np.array([-2, 0, 2], dtype=np.float32))
    with wave.open(io.BytesIO(encoded), "rb") as source:
        assert (source.getframerate(), source.getnchannels(), source.getsampwidth()) == (16000, 1, 2)
        assert np.frombuffer(source.readframes(3), dtype="<i2").tolist() == [-32767, 0, 32767]
    with pytest.raises(ValueError):
        wav_bytes(np.array([np.nan]))


def test_gemini_payload_keeps_prompt_and_tts_style_out_of_transcript():
    payload = stt_payload(b"wav", vocabulary_hints=["API"])
    assert payload["store"] is False
    assert payload["generation_config"] == {"thinking_level": "low", "max_output_tokens": 4096}
    assert base64.b64decode(payload["input"][1]["data"]) == b"wav"
    assert "temperature" not in json.dumps(payload)
    with pytest.raises(ValueError):
        stt_payload(b"wav", thinking_level="minimal")
    speech = tts_payload("要朗讀的文字", style="溫暖", stream=True)
    assert speech["generation_config"]["speech_config"] == [{"voice": "Leda"}]
    assert speech["input"][0]["content"][0]["text"] == "要朗讀的文字"
    assert speech["input"][0]["content"][0]["annotations"][0]["style"] == "溫暖"
    assert "thinking" not in json.dumps(speech)


def test_transcription_reads_only_model_text_and_preserves_empty_text():
    payload = {"status": "completed", "usage": {"total_input_tokens": 10}, "steps": [
        {"type": "user_input", "content": [{"type": "text", "text": "prompt"}]},
        {"type": "thought", "content": [{"type": "text", "text": "reasoning"}]},
        {"type": "model_output", "content": [{"type": "text", "text": ""}]}]}
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as client:
        assert transcribe_wav(client, "test-key", b"wav") == ("", {"total_input_tokens": 10})
    with pytest.raises(GeminiAPIError, match="incomplete_response"):
        model_content({"status": "incomplete", "steps": []}, "text")


def test_errors_do_not_expose_provider_body_or_key():
    response = httpx.Response(403, json={"error": {"message": "test-secret-in-provider-body"}})
    with pytest.raises(GeminiAPIError) as error:
        check_response(response)
    assert error.value.status_code == 403
    assert "secret" not in str(error.value)


def test_benchmark_normalization_does_not_hide_traditional_simplified_errors():
    assert normalize(" API，測試！ ") == "api測試"
    assert normalize("臺灣") != normalize("台湾")
    assert edit_distance("不要開", "要開") == 1
    assert summarize([])["gemini"]["p50_ms"] is None
    assert estimated_cost({"total_input_tokens": 100, "total_output_tokens": 20,
        "total_thought_tokens": 5}) == pytest.approx(.00016875)


def test_sse_parser_supports_comments_multiline_and_trailing_event():
    events = list(sse_messages([
        ": keepalive", "event: step.delta", 'data: {"event_type":"step.delta",',
        'data: "delta":{"type":"audio","data":"AA=="}}', "",
        "data: [DONE]", "", 'data: {"event_type":"interaction.completed"}',
    ]))
    assert events[0]["delta"]["data"] == "AA=="
    assert events[1]["event_type"] == "interaction.completed"


def test_review_escapes_manifest_and_audio_urls_and_handles_partial_tts(tmp_path):
    from tools.audio_benchmark_review import audio_tag, make_review
    from html.parser import HTMLParser
    stt, tts = tmp_path/'stt', tmp_path/'tts'
    stt.mkdir()
    tts.mkdir()
    sample_id = '<script>alert("untrusted")</script>'
    (stt/'manifest.json').write_text(json.dumps([{
        'sample_id': sample_id, 'sha256': '" data-extra="untrusted',
        'duration_s': 1, 'path': str(stt/'audio #1%.wav'), 'reference': '<untrusted>',
    }]), encoding='utf-8')
    (tts/'results.jsonl').write_text(json.dumps({'text_id': 1, 'round': 2})+'\n', encoding='utf-8')
    page = make_review(stt, tts).read_text(encoding='utf-8')
    assert '<script>alert(' not in page
    assert '&lt;script&gt;' in page
    assert 'src="audio%20%231%25.wav"' in page
    class Attributes(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == 'section' and dict(attrs).get('data-id') == sample_id:
                assert set(dict(attrs)) == {'data-id', 'data-hash'}
    Attributes().feed(page)
    assert 'audio%20%231%25.wav' in audio_tag(stt/'audio #1%.wav', stt)


def test_tts_stream_handles_split_pcm_and_completion(monkeypatch):
    from tools.benchmark_gemini_tts import gemini_speech
    events = [
        {"event_type": "step.delta", "delta": {"type": "audio", "data": base64.b64encode(b"\x01").decode()}},
        {"event_type": "step.delta", "delta": {"type": "audio", "data": base64.b64encode(b"\x00\x02\x00").decode()}},
        {"event_type": "interaction.completed", "interaction": {"status": "completed", "usage": {"total_output_tokens": 2}}},
    ]
    class Response:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def iter_lines(self):
            for event in events:
                yield "data: " + json.dumps(event)
                yield ""
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def stream(self, *a, **kwargs): return Response()
    monkeypatch.setattr("tools.benchmark_gemini_tts.httpx.Client", Client)
    frames, metrics = gemini_speech("test-key", "test", "Kore", "")
    assert np.concatenate(frames).tolist() == [1, 2]
    assert metrics["first_nonzero_ms"] is not None
    assert metrics["usage"]["total_output_tokens"] == 2
    events.pop()
    with pytest.raises(GeminiAPIError, match="incomplete_audio_stream"):
        gemini_speech("test-key", "test", "Kore", "")
