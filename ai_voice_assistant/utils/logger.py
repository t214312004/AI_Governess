import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Lock

import colorlog

APP_LOGGER_NAME = "ai_voice_assistant"
LLM_IO_LOGGER_NAME = f"{APP_LOGGER_NAME}.llm_io"
DEFAULT_CONSOLE_LEVEL = "INFO"
DEFAULT_FILE_LEVEL = "DEBUG"
DEFAULT_LOG_DIRNAME = "logs"
DEFAULT_LOG_BASENAME = "ai_voice_assistant"
LLM_IO_LOG_BASENAME = "llm_io"
DEFAULT_RETENTION_DAYS = 5

_DATEFMT = "%Y-%m-%d %H:%M:%S"
_PLAIN_FORMAT = "%(asctime)s | %(levelname)-7s | %(component)s | %(message)s"
_COLOR_FORMAT = "%(log_color)s%(asctime)s | %(levelname)-7s | %(component)s | %(message)s%(reset)s"
_LOG_COLORS = {
    "DEBUG": "cyan",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "bold_red",
}

_CONFIG_LOCK = Lock()
_CONFIG_SIGNATURE = None
_LLM_IO_CONFIG_SIGNATURE = None


def _is_logging_disabled() -> bool:
    raw_value = os.environ.get("AI_GOVERNESS_DISABLE_LOGGING")
    if raw_value is None:
        return False
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


class _ComponentFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        prefix = f"{APP_LOGGER_NAME}."
        if record.name == APP_LOGGER_NAME:
            record.component = "app"
        elif record.name.startswith(prefix):
            record.component = record.name[len(prefix):]
        else:
            record.component = record.name
        return True


class _SafeHandlerMixin:
    def handleError(self, record: logging.LogRecord) -> None:
        if isinstance(sys.exc_info()[1], ValueError):
            return
        super().handleError(record)


class _SafeStreamHandler(_SafeHandlerMixin, logging.StreamHandler):
    pass


class _DailyFileHandler(_SafeHandlerMixin, logging.FileHandler):
    def __init__(
        self,
        log_dir: Path,
        basename: str = DEFAULT_LOG_BASENAME,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        encoding: str = "utf-8-sig",
    ):
        self.log_dir = log_dir
        self.basename = basename
        self.retention_days = max(1, int(retention_days))
        self._current_date = self._today()
        log_path = self._build_log_path(self._current_date)
        super().__init__(str(log_path), encoding=encoding)
        self._cleanup_old_files()

    def _today(self) -> date:
        return date.today()

    def _build_log_path(self, log_date: date) -> Path:
        return self.log_dir / f"{self.basename}-{log_date.isoformat()}.log"

    def _reopen_if_date_changed(self) -> None:
        today = self._today()
        if today == self._current_date:
            return

        self.acquire()
        try:
            today = self._today()
            if today == self._current_date:
                return

            if self.stream:
                self.flush()
                self.stream.close()
                self.stream = None

            self._current_date = today
            self.baseFilename = str(self._build_log_path(today))
            self.stream = self._open()
            self._cleanup_old_files()
        finally:
            self.release()

    def _cleanup_old_files(self) -> None:
        pattern = f"{self.basename}-????-??-??.log"
        existing_logs = sorted(self.log_dir.glob(pattern))
        while len(existing_logs) > self.retention_days:
            oldest = existing_logs.pop(0)
            try:
                oldest.unlink()
            except FileNotFoundError:
                pass

    def emit(self, record: logging.LogRecord) -> None:
        self._reopen_if_date_changed()
        super().emit(record)


def _app_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_level(raw_level, default: str) -> int:
    if raw_level is None:
        raw_level = default
    if isinstance(raw_level, int):
        return raw_level

    level_name = str(raw_level).strip().upper()
    if not level_name:
        level_name = default

    level_value = logging.getLevelNamesMapping().get(level_name)
    if level_value is None:
        level_value = logging.getLevelNamesMapping()[default]
    return level_value


def _resolve_positive_int(raw_value, default: int) -> int:
    try:
        resolved = int(raw_value)
    except (TypeError, ValueError):
        resolved = default
    return max(1, resolved)


def _normalize_logger_name(name: str | None) -> str:
    if not name or name == APP_LOGGER_NAME:
        return APP_LOGGER_NAME

    normalized = str(name).strip()
    if normalized == "__main__":
        normalized = "main"

    if normalized.startswith(f"{APP_LOGGER_NAME}."):
        return normalized
    return f"{APP_LOGGER_NAME}.{normalized}"


def _resolve_log_dir(log_dir: str | os.PathLike | None) -> Path:
    if log_dir is None:
        log_dir = os.environ.get("AI_GOVERNESS_LOG_DIR", DEFAULT_LOG_DIRNAME)

    resolved = Path(log_dir)
    if not resolved.is_absolute():
        resolved = _app_root() / resolved
    return resolved


def _use_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    stream = getattr(sys, "stderr", None)
    return bool(stream and hasattr(stream, "isatty") and stream.isatty())


def _console_stream_available() -> bool:
    stream = getattr(sys, "stderr", None)
    return bool(stream and hasattr(stream, "write"))


def _build_console_handler(level: int) -> logging.Handler:
    handler = _SafeStreamHandler()
    handler.setLevel(level)
    handler.addFilter(_ComponentFilter())

    if _use_color():
        formatter = colorlog.ColoredFormatter(
            _COLOR_FORMAT,
            datefmt=_DATEFMT,
            log_colors=_LOG_COLORS,
            reset=True,
        )
    else:
        formatter = logging.Formatter(_PLAIN_FORMAT, datefmt=_DATEFMT)

    handler.setFormatter(formatter)
    return handler


def _build_file_handler(log_dir: Path, level: int, retention_days: int) -> logging.Handler:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = _DailyFileHandler(
        log_dir=log_dir,
        basename=DEFAULT_LOG_BASENAME,
        retention_days=retention_days,
        encoding="utf-8-sig",
    )
    handler.setLevel(level)
    handler.addFilter(_ComponentFilter())
    handler.setFormatter(logging.Formatter(_PLAIN_FORMAT, datefmt=_DATEFMT))
    return handler


def _build_llm_io_file_handler(log_dir: Path, retention_days: int) -> logging.Handler:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = _DailyFileHandler(
        log_dir=log_dir,
        basename=LLM_IO_LOG_BASENAME,
        retention_days=retention_days,
        encoding="utf-8-sig",
    )
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    return handler


def configure_logging(
    *,
    console_level: str | int | None = None,
    file_level: str | int | None = None,
    log_dir: str | os.PathLike | None = None,
) -> logging.Logger:
    global _CONFIG_SIGNATURE

    resolved_console_level = _resolve_level(
        console_level or os.environ.get("AI_GOVERNESS_CONSOLE_LOG_LEVEL"),
        DEFAULT_CONSOLE_LEVEL,
    )
    resolved_file_level = _resolve_level(
        file_level or os.environ.get("AI_GOVERNESS_FILE_LOG_LEVEL"),
        DEFAULT_FILE_LEVEL,
    )
    resolved_retention_days = _resolve_positive_int(
        os.environ.get("AI_GOVERNESS_LOG_RETENTION_DAYS"),
        DEFAULT_RETENTION_DAYS,
    )
    resolved_log_dir = _resolve_log_dir(log_dir)
    logging_disabled = _is_logging_disabled()
    console_stream_available = _console_stream_available()
    config_signature = (
        resolved_console_level,
        resolved_file_level,
        resolved_retention_days,
        str(resolved_log_dir.resolve()),
        _use_color(),
        logging_disabled,
        console_stream_available,
    )

    with _CONFIG_LOCK:
        app_logger = logging.getLogger(APP_LOGGER_NAME)
        if _CONFIG_SIGNATURE == config_signature and app_logger.handlers:
            return app_logger

        for handler in list(app_logger.handlers):
            app_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

        app_logger.setLevel(logging.DEBUG)
        app_logger.propagate = False
        if logging_disabled:
            app_logger.addHandler(logging.NullHandler())
        else:
            if console_stream_available:
                app_logger.addHandler(_build_console_handler(resolved_console_level))
            app_logger.addHandler(
                _build_file_handler(
                    resolved_log_dir,
                    resolved_file_level,
                    resolved_retention_days,
                )
            )

        _CONFIG_SIGNATURE = config_signature
        return app_logger


def get_log_file_path(log_dir: str | os.PathLike | None = None) -> Path:
    return _resolve_log_dir(log_dir) / f"{DEFAULT_LOG_BASENAME}-{date.today().isoformat()}.log"


def get_llm_io_log_file_path(log_dir: str | os.PathLike | None = None) -> Path:
    return _resolve_log_dir(log_dir) / f"{LLM_IO_LOG_BASENAME}-{date.today().isoformat()}.log"


def configure_llm_io_logging(
    *,
    log_dir: str | os.PathLike | None = None,
) -> logging.Logger:
    global _LLM_IO_CONFIG_SIGNATURE

    resolved_retention_days = _resolve_positive_int(
        os.environ.get("AI_GOVERNESS_LOG_RETENTION_DAYS"),
        DEFAULT_RETENTION_DAYS,
    )
    resolved_log_dir = _resolve_log_dir(log_dir)
    logging_disabled = _is_logging_disabled()
    config_signature = (
        resolved_retention_days,
        str(resolved_log_dir.resolve()),
        logging_disabled,
    )

    with _CONFIG_LOCK:
        io_logger = logging.getLogger(LLM_IO_LOGGER_NAME)
        if _LLM_IO_CONFIG_SIGNATURE == config_signature and io_logger.handlers:
            return io_logger

        for handler in list(io_logger.handlers):
            io_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

        io_logger.setLevel(logging.INFO)
        io_logger.propagate = False
        if logging_disabled:
            io_logger.addHandler(logging.NullHandler())
        else:
            io_logger.addHandler(
                _build_llm_io_file_handler(
                    resolved_log_dir,
                    resolved_retention_days,
                )
            )

        _LLM_IO_CONFIG_SIGNATURE = config_signature
        return io_logger


def get_logger(name: str | None = None) -> logging.Logger:
    configure_logging()
    logger = logging.getLogger(_normalize_logger_name(name))
    logger.setLevel(logging.NOTSET)
    logger.propagate = True
    return logger


def _format_value(value) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int) or value is None:
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return json.dumps(list(value), ensure_ascii=False)

    text = str(value)
    if any(ch.isspace() or ch in "\"'=|" for ch in text):
        return json.dumps(text, ensure_ascii=False)
    return text


def log_event(logger: logging.Logger, level: int, event: str, **fields) -> None:
    parts = [f"event={event}"]
    if fields:
        rendered_fields = " ".join(
            f"{key}={_format_value(value)}"
            for key, value in fields.items()
            if value is not None
        )
        if rendered_fields:
            parts.append(rendered_fields)
    logger.log(level, " | ".join(parts))


def log_llm_io(
    kind: str,
    content: str | None,
    *,
    actor: str,
    mode: str,
    request_id: str | None = None,
    speaker: str | None = None,
    status: str | None = None,
    log_dir: str | os.PathLike | None = None,
) -> None:
    timestamp = datetime.now().strftime("%H:%M")
    label = str(kind).strip().upper() or "LLM_IO"
    metadata = {
        "actor": actor,
        "mode": mode,
        "request_id": request_id,
        "speaker": speaker,
        "status": status,
    }
    rendered_metadata = " ".join(
        f"{key}={_format_value(value)}"
        for key, value in metadata.items()
        if value is not None
    )
    header = f"[{timestamp}] {label}"
    if rendered_metadata:
        header = f"{header} | {rendered_metadata}"

    body = "" if content is None else str(content)
    entry = f"{header}\n{body}\n--- END {label} ---"
    try:
        configure_llm_io_logging(log_dir=log_dir).info(entry)
    except Exception:
        pass
