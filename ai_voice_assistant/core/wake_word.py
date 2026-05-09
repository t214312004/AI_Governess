import os

import numpy as np
import sherpa_onnx

from utils.logger import get_logger

logger = get_logger(__name__)


class WakeWordDetector:
    def __init__(self, keywords_file: str, model_dir: str):
        """
        Initialize the Sherpa-ONNX keyword spotter.

        `keywords_file` and `model_dir` must already be resolved paths.
        """
        self.keywords_file = keywords_file
        self.model_dir = model_dir
        self.keyword_spotter = None
        self.stream = None
        self._init_model()

    def _init_model(self):
        if not self.model_dir:
            logger.error("Wake-word model directory is not configured.")
            return

        if not os.path.exists(self.model_dir):
            logger.error(f"找不著喚醒詞模型目錄: {self.model_dir}，請先下載模型！")
            return

        if not os.path.exists(self.keywords_file):
            logger.error(f"找不著喚醒詞設定檔: {self.keywords_file}！")
            return

        logger.info(f"正在載入 Sherpa-ONNX 喚醒詞模型：{self.model_dir}")

        encoder_path = os.path.join(self.model_dir, "encoder-epoch-12-avg-2-chunk-16-left-64.onnx")
        decoder_path = os.path.join(self.model_dir, "decoder-epoch-12-avg-2-chunk-16-left-64.onnx")
        joiner_path = os.path.join(self.model_dir, "joiner-epoch-12-avg-2-chunk-16-left-64.onnx")
        tokens_path = os.path.join(self.model_dir, "tokens.txt")

        try:
            self.keyword_spotter = sherpa_onnx.keyword_spotter.KeywordSpotter(
                tokens=tokens_path,
                encoder=encoder_path,
                decoder=decoder_path,
                joiner=joiner_path,
                keywords_file=self.keywords_file,
                num_threads=2,
                sample_rate=16000,
                feature_dim=80,
                provider="cpu",
            )
            self.stream = self.keyword_spotter.create_stream()
            logger.info("喚醒詞模型已載入。")
        except Exception as e:
            logger.error(f"初始化喚醒詞模型失敗: {e}")

    def detect(self, audio_chunk_int16: np.ndarray, sample_rate: int = 16000) -> str:
        """
        Run wake-word detection on one audio chunk.

        Return the detected keyword string, or `None`.
        """
        if not self.keyword_spotter or not self.stream:
            return None

        samples_float32 = audio_chunk_int16.astype(np.float32) / 32768.0

        if samples_float32.ndim > 1:
            samples_float32 = np.squeeze(samples_float32)

        self.stream.accept_waveform(sample_rate, samples_float32)

        while self.keyword_spotter.is_ready(self.stream):
            self.keyword_spotter.decode_stream(self.stream)

        result = self.keyword_spotter.get_result(self.stream)
        if result:
            # Replace the stream immediately to avoid duplicate hits.
            self.stream = self.keyword_spotter.create_stream()
            return result

        return None
