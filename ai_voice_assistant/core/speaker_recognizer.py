import glob
import math
import os
import wave

import logging
import numpy as np
import torch

from utils.logger import get_logger, log_event

logger = get_logger(__name__)


class SpeakerRecognizer:
    def __init__(
        self,
        profile_dir: str,
        threshold: float = 0.75,
        sample_rate: int = 16000,
        min_duration_seconds: float = 0.8,
        min_score_margin: float = 0.0,
        custom_embedder=None,
        preferred_backend: str = "resemblyzer",
    ):
        self.profile_dir = os.path.abspath(profile_dir)
        self.threshold = float(threshold)
        self.sample_rate = int(sample_rate)
        self.min_duration_seconds = float(min_duration_seconds)
        self.min_samples = int(self.sample_rate * self.min_duration_seconds)
        self.min_score_margin = max(0.0, float(min_score_margin))
        self.custom_embedder = custom_embedder
        self.preferred_backend = self._normalize_backend_name(preferred_backend)
        self.profile_embeddings: dict[str, np.ndarray] = {}
        self.backend_name = "unavailable"
        self._profile_signature = None
        self._resemblyzer_encoder = None
        self._resemblyzer_preprocess = None
        self._mfcc_transform = None
        self._mfcc_filterbank = None
        self._mfcc_dct = None

        os.makedirs(self.profile_dir, exist_ok=True)
        self._initialize_backend()
        self.reload_profiles(force=True)

    def is_available(self) -> bool:
        return self.backend_name != "unavailable"

    def get_active_profile_names(self) -> list[str]:
        return sorted(self.profile_embeddings.keys())

    @staticmethod
    def _normalize_backend_name(preferred_backend: str | None) -> str:
        normalized = str(preferred_backend or "resemblyzer").strip().lower()
        if normalized in {"mfcc", "resemblyzer"}:
            return normalized
        return "resemblyzer"

    def reload_profiles(self, force: bool = False) -> dict[str, np.ndarray]:
        if not self.is_available():
            self.profile_embeddings = {}
            return self.profile_embeddings

        signature = self._snapshot_profile_tree()
        if not force and signature == self._profile_signature:
            return self.profile_embeddings
        if force:
            log_event(
                logger,
                logging.DEBUG,
                "speaker_profiles.load_started",
                profile_dir=self.profile_dir,
            )
        else:
            log_event(
                logger,
                logging.DEBUG,
                "speaker_profiles.reload_started",
                profile_dir=self.profile_dir,
            )

        embeddings: dict[str, np.ndarray] = {}
        for speaker_name in self._list_profile_names():
            speaker_dir = os.path.join(self.profile_dir, speaker_name)
            sample_embeddings = []
            for wav_path in sorted(glob.glob(os.path.join(speaker_dir, "*.wav"))):
                try:
                    sample_audio = self._load_audio_file(wav_path)
                except Exception as e:
                    logger.warning(f"Skipping unreadable speaker profile '{wav_path}': {e}")
                    continue

                try:
                    embedding = self._embed_audio(sample_audio)
                except Exception as e:
                    if self.backend_name == "resemblyzer":
                        self._fallback_to_mfcc(e)
                        return self.reload_profiles(force=force)
                    logger.warning(f"Skipping speaker profile '{wav_path}': {e}")
                    continue

                if embedding is not None:
                    sample_embeddings.append(embedding)
                else:
                    duration_seconds = self._duration_seconds(sample_audio)
                    logger.warning(
                        "Skipping speaker profile "
                        f"'{wav_path}': audio_too_short ({duration_seconds:.3f}s < "
                        f"{self.min_duration_seconds:.3f}s)"
                    )

            if sample_embeddings:
                embeddings[speaker_name] = self._normalize_embedding(
                    np.mean(sample_embeddings, axis=0)
                )

        self.profile_embeddings = embeddings
        self._profile_signature = signature
        if self.profile_embeddings:
            log_event(
                logger,
                logging.DEBUG,
                "speaker_profiles.loaded",
                backend=self.backend_name,
                profile_dir=self.profile_dir,
                profile_count=len(self.profile_embeddings),
                active_profiles=self.get_active_profile_names(),
            )
        else:
            log_event(
                logger,
                logging.DEBUG,
                "speaker_profiles.empty",
                backend=self.backend_name,
                profile_dir=self.profile_dir,
            )
        return self.profile_embeddings

    def identify(
        self,
        audio_data_np: np.ndarray,
        utterance_id: str | None = None,
    ) -> str | None:
        log_prefix = self._build_log_prefix(utterance_id)
        if not self.is_available():
            logger.debug(f"{log_prefix}Speaker recognition skipped, reason=backend_unavailable")
            return None

        self.reload_profiles()
        if not self.profile_embeddings:
            logger.debug(f"{log_prefix}Speaker recognition skipped, reason=no_profiles")
            return None

        duration_seconds = self._duration_seconds(audio_data_np)
        try:
            embedding = self._embed_audio(audio_data_np)
        except Exception as e:
            if self.backend_name != "resemblyzer":
                raise
            self._fallback_to_mfcc(e)
            self.reload_profiles(force=True)
            if not self.profile_embeddings:
                return None
            embedding = self._embed_audio(audio_data_np)
        if embedding is None:
            logger.debug(
                f"{log_prefix}Speaker recognition skipped, reason=audio_too_short, "
                f"duration={duration_seconds:.3f}s, min_duration={self.min_duration_seconds:.3f}s"
            )
            return None

        best_name = None
        best_score = -1.0
        second_best_score = -1.0
        for speaker_name, reference_embedding in self.profile_embeddings.items():
            score = self._cosine_similarity(embedding, reference_embedding)
            if score > best_score:
                second_best_score = best_score
                best_name = speaker_name
                best_score = score
            elif score > second_best_score:
                second_best_score = score

        score_margin = (
            best_score - second_best_score
            if second_best_score >= 0.0
            else float("inf")
        )

        logger.debug(
            f"{log_prefix}Speaker recognition best_match={best_name or 'none'}, "
            f"score={best_score:.4f}, threshold={self.threshold:.4f}, "
            f"score_margin={score_margin:.4f}, min_score_margin={self.min_score_margin:.4f}"
        )
        if (
            best_name is not None
            and best_score >= self.threshold
            and score_margin >= self.min_score_margin
        ):
            return best_name
        return None

    def _initialize_backend(self):
        if self.custom_embedder is not None:
            self.backend_name = "custom"
            return

        if self.preferred_backend == "mfcc":
            self._initialize_mfcc_backend()
            return

        try:
            from resemblyzer import VoiceEncoder, preprocess_wav

            self._resemblyzer_encoder = VoiceEncoder()
            self._resemblyzer_preprocess = preprocess_wav
            self.backend_name = "resemblyzer"
            log_event(
                logger,
                logging.DEBUG,
                "speaker_backend.selected",
                backend=self.backend_name,
            )
            return
        except Exception as e:
            log_event(
                logger,
                logging.INFO,
                "speaker_backend.fallback",
                requested_backend="resemblyzer",
                fallback_backend="mfcc",
                reason=e,
            )

        self._initialize_mfcc_backend()

    def _initialize_mfcc_backend(self):
        self._mfcc_transform = self._compute_mfcc
        self.backend_name = "mfcc"
        log_event(
            logger,
            logging.DEBUG,
            "speaker_backend.selected",
            backend=self.backend_name,
        )

    def _fallback_to_mfcc(self, reason: Exception):
        log_event(
            logger,
            logging.INFO,
            "speaker_backend.fallback",
            requested_backend="resemblyzer",
            fallback_backend="mfcc",
            reason=reason,
        )
        self._resemblyzer_encoder = None
        self._resemblyzer_preprocess = None
        self._initialize_mfcc_backend()

    def _snapshot_profile_tree(self):
        snapshot = []
        for speaker_name in self._list_profile_names():
            speaker_dir = os.path.join(self.profile_dir, speaker_name)
            for wav_path in sorted(glob.glob(os.path.join(speaker_dir, "*.wav"))):
                try:
                    stat = os.stat(wav_path)
                except OSError:
                    continue
                snapshot.append(
                    (
                        speaker_name,
                        os.path.basename(wav_path),
                        stat.st_mtime_ns,
                        stat.st_size,
                    )
                )
        return tuple(snapshot)

    def _list_profile_names(self):
        if not os.path.isdir(self.profile_dir):
            return []
        return [
            entry
            for entry in sorted(os.listdir(self.profile_dir))
            if (
                os.path.isdir(os.path.join(self.profile_dir, entry))
                and self._is_speaker_profile_dir(entry)
            )
        ]

    @staticmethod
    def _is_speaker_profile_dir(entry: str) -> bool:
        normalized = str(entry or "").strip().lower()
        if not normalized:
            return False
        if normalized.startswith("."):
            return False
        if normalized.startswith("tts_"):
            return False
        return True

    def _build_log_prefix(self, utterance_id: str | None) -> str:
        if not utterance_id:
            return ""
        return f"utterance_id={utterance_id}, "

    def _load_audio_file(self, wav_path: str) -> np.ndarray:
        with wave.open(wav_path, "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            raw_bytes = wav_file.readframes(frame_count)

        waveform = self._bytes_to_waveform(raw_bytes, sample_width, channels)
        if waveform.numel() == 0:
            raise ValueError("empty waveform")
        waveform = self._prepare_waveform_tensor(waveform, sample_rate)
        return waveform.squeeze(0).cpu().numpy().astype(np.float32)

    def _bytes_to_waveform(
        self,
        raw_bytes: bytes,
        sample_width: int,
        channels: int,
    ) -> torch.Tensor:
        if sample_width == 1:
            waveform = (np.frombuffer(raw_bytes, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        elif sample_width == 2:
            waveform = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        elif sample_width == 4:
            waveform = np.frombuffer(raw_bytes, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            raise ValueError(f"unsupported sample width: {sample_width}")

        if channels > 1:
            waveform = waveform.reshape(-1, channels).mean(axis=1)
        return torch.from_numpy(waveform).unsqueeze(0)

    def _prepare_waveform_tensor(self, waveform: torch.Tensor, sample_rate: int) -> torch.Tensor:
        if waveform.ndim == 1:
            waveform = waveform.unsqueeze(0)
        if waveform.size(0) > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        if sample_rate != self.sample_rate:
            from scipy.signal import resample_poly

            source = waveform.squeeze(0).cpu().numpy()
            common_divisor = math.gcd(int(sample_rate), self.sample_rate)
            resampled = resample_poly(
                source,
                up=self.sample_rate // common_divisor,
                down=int(sample_rate) // common_divisor,
            ).astype(np.float32, copy=False)
            waveform = torch.from_numpy(resampled).unsqueeze(0)
        return waveform

    def _compute_mfcc(self, waveform: torch.Tensor) -> torch.Tensor:
        audio = waveform.squeeze(0).cpu().numpy().astype(np.float32, copy=False)
        n_fft = 400
        hop_length = 160
        n_mels = 40
        n_mfcc = 40
        if audio.size < n_fft:
            audio = np.pad(audio, (0, n_fft - audio.size))

        frame_count = 1 + max(0, (audio.size - n_fft) // hop_length)
        frame_offsets = np.arange(frame_count)[:, None] * hop_length
        sample_offsets = np.arange(n_fft)[None, :]
        frames = audio[frame_offsets + sample_offsets]
        frames = frames * np.hanning(n_fft).astype(np.float32)
        spectrum = np.fft.rfft(frames, n=n_fft, axis=1)
        power = (np.abs(spectrum) ** 2).astype(np.float32)

        if self._mfcc_filterbank is None:
            self._mfcc_filterbank = self._build_mel_filterbank(n_fft, n_mels)
        if self._mfcc_dct is None:
            mel_index = np.arange(n_mels, dtype=np.float32) + 0.5
            cepstral_index = np.arange(n_mfcc, dtype=np.float32)[:, None]
            self._mfcc_dct = np.cos(
                (np.pi / n_mels) * cepstral_index * mel_index[None, :]
            ).astype(np.float32)

        mel_energy = power @ self._mfcc_filterbank.T
        log_mel = np.log(np.maximum(mel_energy, 1e-10))
        mfcc = self._mfcc_dct @ log_mel.T
        return torch.from_numpy(np.asarray(mfcc, dtype=np.float32)).unsqueeze(0)

    def _build_mel_filterbank(self, n_fft: int, n_mels: int) -> np.ndarray:
        def hz_to_mel(hz):
            return 2595.0 * np.log10(1.0 + hz / 700.0)

        def mel_to_hz(mel):
            return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

        min_mel = hz_to_mel(0.0)
        max_mel = hz_to_mel(self.sample_rate / 2.0)
        mel_points = np.linspace(min_mel, max_mel, n_mels + 2)
        hz_points = mel_to_hz(mel_points)
        bins = np.floor((n_fft + 1) * hz_points / self.sample_rate).astype(int)
        bins = np.clip(bins, 0, n_fft // 2)

        filters = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
        for index in range(n_mels):
            left, center, right = bins[index : index + 3]
            if center <= left:
                center = min(left + 1, n_fft // 2)
            if right <= center:
                right = min(center + 1, n_fft // 2)
            if center > left:
                filters[index, left:center] = (
                    np.arange(left, center) - left
                ) / float(center - left)
            if right > center:
                filters[index, center:right] = (
                    right - np.arange(center, right)
                ) / float(right - center)
        return filters

    def _embed_audio(self, audio_data_np: np.ndarray) -> np.ndarray | None:
        audio = np.asarray(audio_data_np, dtype=np.float32)
        if audio.ndim > 1:
            audio = np.squeeze(audio)
        if audio.ndim != 1:
            audio = audio.reshape(-1)
        if audio.size < self.min_samples:
            return None

        if self.custom_embedder is not None:
            embedding = self.custom_embedder(audio, self.sample_rate)
            if embedding is None:
                return None
            return self._normalize_embedding(np.asarray(embedding, dtype=np.float32))

        if self.backend_name == "resemblyzer":
            processed_audio = self._resemblyzer_preprocess(audio, source_sr=self.sample_rate)
            embedding = self._resemblyzer_encoder.embed_utterance(processed_audio)
            return self._normalize_embedding(np.asarray(embedding, dtype=np.float32))

        waveform = torch.from_numpy(audio).unsqueeze(0)
        mfcc = self._mfcc_transform(waveform).squeeze(0)
        mean = mfcc.mean(dim=-1)
        std = mfcc.std(dim=-1, unbiased=False)
        energy = torch.tensor(
            [waveform.abs().mean(), waveform.square().mean().sqrt()],
            dtype=waveform.dtype,
        )
        embedding = torch.cat([mean, std, energy], dim=0).cpu().numpy().astype(np.float32)
        return self._normalize_embedding(embedding)

    def _duration_seconds(self, audio_data_np: np.ndarray) -> float:
        audio = np.asarray(audio_data_np)
        if audio.ndim > 1:
            audio = np.squeeze(audio)
        if audio.ndim != 1:
            audio = audio.reshape(-1)
        if self.sample_rate <= 0:
            return 0.0
        return float(audio.size) / float(self.sample_rate)

    def _normalize_embedding(self, embedding: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(embedding)
        if norm <= 0:
            return embedding
        return embedding / norm

    def _cosine_similarity(self, left: np.ndarray, right: np.ndarray) -> float:
        denominator = np.linalg.norm(left) * np.linalg.norm(right)
        if denominator <= 0:
            return -1.0
        return float(np.dot(left, right) / denominator)
