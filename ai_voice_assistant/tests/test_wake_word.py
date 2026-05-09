import os
import numpy as np
import pytest
import core.wake_word as wake_word_module
from core.wake_word import WakeWordDetector

@pytest.fixture
def mock_sherpa(mocker):

    mock_sherpa_onnx = mocker.patch("core.wake_word.sherpa_onnx")


    mock_spotter_instance = mocker.MagicMock()
    mock_sherpa_onnx.keyword_spotter.KeywordSpotter.return_value = mock_spotter_instance


    mock_stream_instance = mocker.MagicMock()
    mock_spotter_instance.create_stream.return_value = mock_stream_instance

    return mock_sherpa_onnx, mock_spotter_instance, mock_stream_instance

@pytest.fixture
def setup_files(tmp_path):
    keywords_file = tmp_path / "keywords.txt"
    keywords_file.write_text("ài guǎn jiā :3.0 #0.25 @愛管家", encoding="utf-8")

    model_dir = tmp_path / "models"
    model_dir.mkdir()

    return str(keywords_file), str(model_dir)

def test_init_success(mock_sherpa, setup_files):
    keywords_file, model_dir = setup_files
    _, mock_spotter, _ = mock_sherpa

    detector = WakeWordDetector(keywords_file, model_dir)

    assert detector.keyword_spotter is not None
    assert detector.stream is not None

def test_init_missing_model_dir(setup_files, mocker):
    keywords_file, _ = setup_files
    logger_mock = mocker.patch.object(wake_word_module, "logger")

    detector = WakeWordDetector(keywords_file, "non_existent_dir")

    assert detector.keyword_spotter is None
    logger_mock.error.assert_called_once_with("找不著喚醒詞模型目錄: non_existent_dir，請先下載模型！")

def test_init_missing_model_dir_config(mocker):
    logger_mock = mocker.patch.object(wake_word_module, "logger")
    detector = WakeWordDetector("keywords.txt", None)

    assert detector.keyword_spotter is None
    logger_mock.error.assert_called_once_with("Wake-word model directory is not configured.")

def test_init_missing_keywords_file(setup_files, mocker):
    _, model_dir = setup_files
    logger_mock = mocker.patch.object(wake_word_module, "logger")

    detector = WakeWordDetector("non_existent_file.txt", model_dir)

    assert detector.keyword_spotter is None
    logger_mock.error.assert_called_once_with("找不著喚醒詞設定檔: non_existent_file.txt！")

def test_init_exception(mock_sherpa, setup_files, mocker):
    keywords_file, model_dir = setup_files
    mock_sherpa_onnx, _, _ = mock_sherpa
    mock_sherpa_onnx.keyword_spotter.KeywordSpotter.side_effect = Exception("Mock Error")
    logger_mock = mocker.patch.object(wake_word_module, "logger")

    detector = WakeWordDetector(keywords_file, model_dir)

    assert detector.keyword_spotter is None
    logger_mock.error.assert_called_once_with("初始化喚醒詞模型失敗: Mock Error")

def test_detect_not_initialized():

    detector = WakeWordDetector("dummy", "dummy")
    assert detector.keyword_spotter is None

    audio_chunk = np.zeros(160, dtype=np.int16)
    result = detector.detect(audio_chunk)
    assert result is None

def test_detect_no_keyword(mock_sherpa, setup_files):
    keywords_file, model_dir = setup_files
    _, mock_spotter_instance, mock_stream_instance = mock_sherpa


    mock_spotter_instance.is_ready.side_effect = [True, False]
    mock_spotter_instance.get_result.return_value = ""

    detector = WakeWordDetector(keywords_file, model_dir)

    audio_chunk = np.zeros(160, dtype=np.int16)
    result = detector.detect(audio_chunk)

    assert result is None
    mock_stream_instance.accept_waveform.assert_called_once()
    mock_spotter_instance.decode_stream.assert_called_once_with(mock_stream_instance)

def test_detect_keyword_found(mock_sherpa, setup_files):
    keywords_file, model_dir = setup_files
    _, mock_spotter_instance, mock_stream_instance = mock_sherpa


    mock_spotter_instance.is_ready.side_effect = [True, False]
    mock_spotter_instance.get_result.return_value = "愛管家"

    detector = WakeWordDetector(keywords_file, model_dir)


    audio_chunk = np.zeros((160, 1), dtype=np.int16)
    result = detector.detect(audio_chunk)

    assert result == "愛管家"

    assert mock_spotter_instance.create_stream.call_count == 2

