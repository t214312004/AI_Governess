import os
import wave

import numpy as np

from core.whisper_audio_archive import WhisperAudioArchive


def test_whisper_audio_archive_saves_wav_and_sidecar(tmp_path):
    archive = WhisperAudioArchive(str(tmp_path), sample_rate=16000, write_transcript_sidecar=True)

    record = archive.save(
        np.linspace(-0.2, 0.2, 1600, dtype=np.float32),
        utterance_id="test_utterance",
    )

    assert record is not None
    assert record.utterance_id == "test_utterance"
    assert os.path.exists(record.wav_path)

    with wave.open(record.wav_path, "rb") as wav_file:
        assert wav_file.getframerate() == 16000
        assert wav_file.getnchannels() == 1

    sidecar_path = archive.write_transcript_sidecar(record, transcript="hello", speaker_name="ViVi")

    assert os.path.exists(sidecar_path)
    with open(sidecar_path, "r", encoding="utf-8") as sidecar_file:
        sidecar_text = sidecar_file.read()

    assert "utterance_id: test_utterance" in sidecar_text
    assert "speaker_name: ViVi" in sidecar_text
    assert "hello" in sidecar_text


def test_whisper_audio_archive_skips_empty_audio(tmp_path):
    archive = WhisperAudioArchive(str(tmp_path), sample_rate=16000)

    record = archive.save(np.array([], dtype=np.float32))

    assert record is None

