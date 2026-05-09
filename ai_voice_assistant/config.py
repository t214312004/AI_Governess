import json
import os
import threading
from copy import deepcopy

from utils.logger import get_logger

logger = get_logger(__name__)

APP_DIR = os.path.dirname(__file__)
DEFAULT_CONFIG_PATH = os.path.join(APP_DIR, "config.default.json")
CONFIG_PATH = os.path.join(
    APP_DIR,
    os.environ.get("AI_GOVERNESS_CONFIG", "config.local.json"),
)
_SAVE_DEBOUNCE_SECONDS = 0.5
_MISSING = object()


def _deep_merge(base, override):
    if not isinstance(base, dict) or not isinstance(override, dict):
        return deepcopy(override)

    merged = deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _read_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class Config:
    def __init__(self, default_path=None, config_path=None):
        self.default_path = default_path or DEFAULT_CONFIG_PATH
        self.config_path = config_path or CONFIG_PATH
        self._config = {}
        self.loaded_paths = []
        self._save_timer: threading.Timer | None = None
        self._save_lock = threading.Lock()
        self._dirty = False
        self.load()

    def load(self):
        loaded_config = {}
        loaded_paths = []

        if self.default_path and os.path.exists(self.default_path):
            try:
                loaded_config = _read_json_file(self.default_path)
                loaded_paths.append(self.default_path)
            except Exception as exc:
                logger.error(f"Failed to load default config: {exc}")
                self._config = {}
                self.loaded_paths = []
                self._dirty = False
                return

        if self.config_path and os.path.exists(self.config_path):
            try:
                private_config = _read_json_file(self.config_path)
                loaded_config = _deep_merge(loaded_config, private_config)
                loaded_paths.append(self.config_path)
            except Exception as exc:
                logger.error(f"Failed to load config: {exc}")
                self._config = {}
                self.loaded_paths = []
                self._dirty = False
                return
        else:
            logger.warning(
                f"Private config file not found: {self.config_path}. "
                "Using default configuration only."
            )

        self._config = loaded_config
        self.loaded_paths = loaded_paths
        if loaded_paths:
            logger.info(
                "Configuration loaded from: "
                + ", ".join(os.path.basename(path) for path in loaded_paths)
            )
        self._dirty = False

    def save(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            self._dirty = False
            logger.info(f"Configuration saved: {self.config_path}")
        except Exception as exc:
            logger.error(f"Failed to save config: {exc}")

    def _schedule_save(self):
        with self._save_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(_SAVE_DEBOUNCE_SECONDS, self._do_save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def _do_save(self):
        with self._save_lock:
            self._save_timer = None
        self.save()

    def flush(self):
        should_save = False
        with self._save_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
            should_save = self._dirty
        if should_save:
            self.save()

    def get(self, *keys, default=None):
        value = self._config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def set(self, *keys, value=None):
        node = self._config
        for key in keys[:-1]:
            if key not in node:
                node[key] = {}
            node = node[key]

        old_value = node.get(keys[-1], _MISSING)
        if old_value is not _MISSING and old_value == value:
            return False

        node[keys[-1]] = value
        self._dirty = True
        self._schedule_save()
        return True


config = Config()
