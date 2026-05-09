import os
import wave
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ArchiveRecord:
    utterance_id: str
    wav_path: str


class WhisperAudioArchive:
    def __init__(
        self,
        base_dir: str,
        sample_rate: int = 16000,
        write_transcript_sidecar: bool = True,
    ):
        self.base_dir = os.path.abspath(base_dir)
        self.sample_rate = sample_rate
        self.sidecar_enabled = write_transcript_sidecar
        os.makedirs(self.base_dir, exist_ok=True)

    def save(
        self,
        audio_np_float32: np.ndarray,
        utterance_id: str | None = None,
    ) -> ArchiveRecord | None:
        audio = self._normalize_audio(audio_np_float32)
        if audio.size == 0:
            return None

        utterance_id = utterance_id or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        wav_path = os.path.join(self.base_dir, f"utterance_{utterance_id}.wav")
        self._write_wav(wav_path, audio)
        logger.debug(
            f"Archived Whisper input audio, utterance_id={utterance_id}, wav_path={wav_path}"
        )
        return ArchiveRecord(utterance_id=utterance_id, wav_path=wav_path)

    def write_transcript_sidecar(
        self,
        archive_record: ArchiveRecord | None,
        transcript: str,
        speaker_name: str | None = None,
    ) -> str | None:
        if not self.sidecar_enabled or archive_record is None:
            return None

        sidecar_path = os.path.splitext(archive_record.wav_path)[0] + ".txt"
        lines = [
            f"utterance_id: {archive_record.utterance_id}",
            f"wav_path: {archive_record.wav_path}",
            f"speaker_name: {speaker_name or 'unknown'}",
            "transcript:",
            transcript or "",
        ]
        with open(sidecar_path, "w", encoding="utf-8") as sidecar_file:
            sidecar_file.write("\n".join(lines).strip() + "\n")
        logger.debug(
            "Wrote Whisper archive sidecar, "
            f"utterance_id={archive_record.utterance_id}, txt_path={sidecar_path}"
        )
        return sidecar_path

    def _normalize_audio(self, audio_np_float32: np.ndarray) -> np.ndarray:
        if audio_np_float32 is None:
            return np.array([], dtype=np.float32)

        audio = np.asarray(audio_np_float32, dtype=np.float32)
        if audio.ndim > 1:
            audio = np.squeeze(audio)
        if audio.ndim != 1:
            audio = audio.reshape(-1)
        return np.clip(audio, -1.0, 1.0)

    def _write_wav(self, wav_path: str, audio_np_float32: np.ndarray):
        pcm = np.clip(audio_np_float32, -1.0, 1.0)
        pcm_int16 = (pcm * 32767.0).astype(np.int16)
        with wave.open(wav_path, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(pcm_int16.tobytes())
