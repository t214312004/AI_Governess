import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from utils.logger import (
    APP_LOGGER_NAME,
    configure_llm_io_logging,
    configure_logging,
    get_llm_io_log_file_path,
    get_log_file_path,
    get_logger,
    log_llm_io,
)


def _enable_test_logging(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_GOVERNESS_DISABLE_LOGGING", raising=False)
    configure_logging(log_dir=tmp_path)


def test_get_logger(monkeypatch, tmp_path):
    _enable_test_logging(monkeypatch, tmp_path)
    logger = get_logger("test_logger")
    assert isinstance(logger, logging.Logger)
    assert logger.name == f"{APP_LOGGER_NAME}.test_logger"
    assert len(logger.handlers) == 0
    assert logger.propagate is True

    app_logger = logging.getLogger(APP_LOGGER_NAME)
    assert len(app_logger.handlers) == 2
    assert get_log_file_path(tmp_path).name == f"ai_voice_assistant-{date.today().isoformat()}.log"


    logger2 = get_logger("test_logger")
    assert len(logger2.handlers) == 0
    assert logger is logger2


def test_configure_logging_skips_console_handler_without_stderr(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_GOVERNESS_DISABLE_LOGGING", raising=False)
    monkeypatch.setattr(sys, "stderr", None)

    configure_logging(log_dir=tmp_path)

    app_logger = logging.getLogger(APP_LOGGER_NAME)
    assert len(app_logger.handlers) == 1
    assert isinstance(app_logger.handlers[0], logging.FileHandler)


def test_daily_log_files_keep_latest_five_days(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_GOVERNESS_DISABLE_LOGGING", raising=False)
    for days_ago in range(6, -1, -1):
        log_date = date.today() - timedelta(days=days_ago)
        log_path = tmp_path / f"ai_voice_assistant-{log_date.isoformat()}.log"
        log_path.write_text(f"log for {log_date.isoformat()}", encoding="utf-8")

    configure_logging(log_dir=tmp_path)

    remaining_logs = sorted(path.name for path in Path(tmp_path).glob("ai_voice_assistant-*.log"))
    expected_logs = [
        f"ai_voice_assistant-{(date.today() - timedelta(days=days_ago)).isoformat()}.log"
        for days_ago in range(4, -1, -1)
    ]
    assert remaining_logs == expected_logs


def test_llm_io_log_writes_raw_content(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_GOVERNESS_DISABLE_LOGGING", raising=False)

    log_llm_io(
        "llm_input",
        "(系統提示: 目前時間：2026年04月15日 14:23（Wednesday）)\nhello",
        actor="PersonB",
        mode="voice",
        request_id="req-1",
        speaker="PersonB",
        log_dir=tmp_path,
    )
    log_llm_io(
        "llm_output",
        "raw\nresponse",
        actor="LLM",
        mode="voice",
        request_id="req-1",
        status="completed",
        log_dir=tmp_path,
    )

    log_text = get_llm_io_log_file_path(tmp_path).read_text(encoding="utf-8-sig")

    assert "LLM_INPUT" in log_text
    assert "actor=PersonB" in log_text
    assert "speaker=PersonB" in log_text
    assert "(系統提示: 目前時間：2026年04月15日 14:23（Wednesday）)\nhello" in log_text
    assert "LLM_OUTPUT" in log_text
    assert "status=completed" in log_text
    assert "raw\nresponse" in log_text


def test_llm_io_log_files_keep_latest_five_days(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_GOVERNESS_DISABLE_LOGGING", raising=False)
    for days_ago in range(6, -1, -1):
        log_date = date.today() - timedelta(days=days_ago)
        log_path = tmp_path / f"llm_io-{log_date.isoformat()}.log"
        log_path.write_text(f"log for {log_date.isoformat()}", encoding="utf-8")

    configure_llm_io_logging(log_dir=tmp_path)

    remaining_logs = sorted(path.name for path in Path(tmp_path).glob("llm_io-*.log"))
    expected_logs = [
        f"llm_io-{(date.today() - timedelta(days=days_ago)).isoformat()}.log"
        for days_ago in range(4, -1, -1)
    ]
    assert remaining_logs == expected_logs


def test_sparse_old_app_log_is_removed_by_calendar_age(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_GOVERNESS_DISABLE_LOGGING", raising=False)
    old_log = tmp_path / f"ai_voice_assistant-{(date.today() - timedelta(days=30)).isoformat()}.log"
    old_log.write_text("old", encoding="utf-8")

    configure_logging(log_dir=tmp_path)

    assert not old_log.exists()


def test_sparse_old_llm_io_log_is_removed_by_calendar_age(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_GOVERNESS_DISABLE_LOGGING", raising=False)
    old_log = tmp_path / f"llm_io-{(date.today() - timedelta(days=30)).isoformat()}.log"
    old_log.write_text("old", encoding="utf-8")

    configure_llm_io_logging(log_dir=tmp_path)

    assert not old_log.exists()

