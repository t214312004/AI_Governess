import builtins
import os
import wave

import numpy as np

from core.speaker_recognizer import SpeakerRecognizer


def _write_sine_wave(path, frequency_hz, sample_rate=16000, duration_seconds=1.0):
    t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    waveform = (0.2 * np.sin(2 * np.pi * frequency_hz * t)).astype(np.float32)
    pcm_int16 = (waveform * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_int16.tobytes())


def test_speaker_recognizer_identifies_matching_profile(tmp_path):
    profile_dir = tmp_path / "voice_profiles"
    personb_dir = profile_dir / "PersonB"
    personb_dir.mkdir(parents=True)
    _write_sine_wave(str(personb_dir / "sample_01.wav"), 220.0)

    recognizer = SpeakerRecognizer(str(profile_dir), threshold=0.9, sample_rate=16000)
    audio = 0.2 * np.sin(2 * np.pi * 220.0 * np.linspace(0, 1.0, 16000, endpoint=False))

    result = recognizer.identify(audio.astype(np.float32))

    assert result == "PersonB"


def test_speaker_recognizer_returns_none_when_no_profiles(tmp_path):
    profile_dir = tmp_path / "voice_profiles"
    profile_dir.mkdir(parents=True)

    recognizer = SpeakerRecognizer(str(profile_dir), sample_rate=16000)

    assert recognizer.identify(np.zeros(16000, dtype=np.float32)) is None


def test_speaker_recognizer_ignores_tts_asset_directories(tmp_path):
    profile_dir = tmp_path / "voice_profiles"
    person_dir = profile_dir / "PersonA"
    prompt_dir = profile_dir / "tts_prompts"
    hidden_dir = profile_dir / ".cache"
    person_dir.mkdir(parents=True)
    prompt_dir.mkdir()
    hidden_dir.mkdir()
    _write_sine_wave(str(person_dir / "sample_01.wav"), 220.0)
    _write_sine_wave(str(prompt_dir / "prompt.wav"), 330.0)
    _write_sine_wave(str(hidden_dir / "cached.wav"), 440.0)

    recognizer = SpeakerRecognizer(str(profile_dir), threshold=0.9, sample_rate=16000)

    assert recognizer._list_profile_names() == ["PersonA"]
    assert recognizer.get_active_profile_names() == ["PersonA"]


def test_speaker_recognizer_requires_min_score_margin(tmp_path):
    profile_dir = tmp_path / "voice_profiles"
    profile_dir.mkdir(parents=True)

    recognizer = SpeakerRecognizer(
        str(profile_dir),
        threshold=0.8,
        sample_rate=10,
        min_duration_seconds=0.1,
        min_score_margin=0.02,
        custom_embedder=lambda audio, sample_rate: np.array([1.0, 0.0], dtype=np.float32),
    )
    recognizer.profile_embeddings = {
        "Alice": np.array([1.0, 0.0], dtype=np.float32),
        "Bob": recognizer._normalize_embedding(np.array([0.99995, 0.01], dtype=np.float32)),
    }

    result = recognizer.identify(np.ones(2, dtype=np.float32))

    assert result is None


def test_speaker_recognizer_accepts_match_when_margin_is_sufficient(tmp_path):
    profile_dir = tmp_path / "voice_profiles"
    profile_dir.mkdir(parents=True)

    recognizer = SpeakerRecognizer(
        str(profile_dir),
        threshold=0.8,
        sample_rate=10,
        min_duration_seconds=0.1,
        min_score_margin=0.02,
        custom_embedder=lambda audio, sample_rate: np.array([1.0, 0.0], dtype=np.float32),
    )
    recognizer.profile_embeddings = {
        "Alice": np.array([1.0, 0.0], dtype=np.float32),
        "Bob": recognizer._normalize_embedding(np.array([0.8, 0.6], dtype=np.float32)),
    }

    result = recognizer.identify(np.ones(2, dtype=np.float32))

    assert result == "Alice"


def test_speaker_recognizer_default_resemblyzer_failure_falls_back_to_mfcc(tmp_path, monkeypatch):
    profile_dir = tmp_path / "voice_profiles"
    profile_dir.mkdir(parents=True)

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "resemblyzer":
            raise ImportError("blocked for test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    recognizer = SpeakerRecognizer(str(profile_dir), sample_rate=16000)

    assert recognizer.backend_name == "mfcc"


def test_speaker_recognizer_resemblyzer_request_falls_back_to_mfcc(tmp_path, monkeypatch):
    profile_dir = tmp_path / "voice_profiles"
    profile_dir.mkdir(parents=True)

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "resemblyzer":
            raise ImportError("blocked for test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    recognizer = SpeakerRecognizer(
        str(profile_dir),
        sample_rate=16000,
        preferred_backend="resemblyzer",
    )

    assert recognizer.backend_name == "mfcc"


def test_speaker_recognizer_detects_new_profile_without_restart(tmp_path):
    profile_dir = tmp_path / "voice_profiles"
    profile_dir.mkdir(parents=True)
    recognizer = SpeakerRecognizer(str(profile_dir), threshold=0.9, sample_rate=16000)

    dad_dir = profile_dir / "Dad"
    dad_dir.mkdir()
    _write_sine_wave(str(dad_dir / "sample_01.wav"), 330.0)
    audio = 0.2 * np.sin(2 * np.pi * 330.0 * np.linspace(0, 1.0, 16000, endpoint=False))

    result = recognizer.identify(audio.astype(np.float32))

    assert result == "Dad"

