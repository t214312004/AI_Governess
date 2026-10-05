import json
import os
import tempfile
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
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValueError(f"Configuration root must be a JSON object: {path}")
    return value


class Config:
    def __init__(self, default_path=None, config_path=None):
        self.default_path = default_path or DEFAULT_CONFIG_PATH
        self.config_path = config_path or CONFIG_PATH
        self._defaults = {}
        self._overrides = {}
        self._config = {}
        self.loaded_paths = []
        self._save_timer: threading.Timer | None = None
        self._save_lock = threading.RLock()
        self._dirty = False
        self.load()

    def load(self):
        default_config = {}
        private_config = {}
        loaded_paths = []

        if self.default_path and os.path.exists(self.default_path):
            try:
                default_config = _read_json_file(self.default_path)
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
                loaded_paths.append(self.config_path)
            except Exception as exc:
                logger.error(f"Failed to load config: {exc}")
                private_config = {}
        else:
            logger.warning(
                f"Private config file not found: {self.config_path}. "
                "Using default configuration only."
            )

        with self._save_lock:
            self._defaults = deepcopy(default_config)
            self._overrides = deepcopy(private_config)
            self._config = _deep_merge(default_config, private_config)
            self.loaded_paths = loaded_paths
            self._dirty = False
        if loaded_paths:
            logger.info(
                "Configuration loaded from: "
                + ", ".join(os.path.basename(path) for path in loaded_paths)
            )

    def save(self):
        temp_path = None
        try:
            with self._save_lock:
                target_dir = os.path.dirname(os.path.abspath(self.config_path))
                fd, temp_path = tempfile.mkstemp(
                    dir=target_dir,
                    prefix=f".{os.path.basename(self.config_path)}.",
                    suffix=".tmp",
                )
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                    json.dump(self._overrides, f, indent=2, ensure_ascii=False)
                    f.write("\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, self.config_path)
                temp_path = None
                self._dirty = False
            logger.info(f"Configuration saved: {self.config_path}")
        except Exception as exc:
            logger.error(f"Failed to save config: {exc}")
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

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
        with self._save_lock:
            value = self._config
            for key in keys:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return default
            return value

    def snapshot(self):
        """Return an independent draft containing defaults and every local override."""
        with self._save_lock:
            return deepcopy(self._config)

    def apply_snapshot(self, draft):
        """Persist an entire startup draft atomically before publishing it in memory.

        A failed write leaves both the active configuration and the old file intact.
        Local overrides, including keys unknown to this version, are preserved.
        """
        if not isinstance(draft, dict):
            raise ValueError("Configuration root must be an object.")
        draft = deepcopy(draft)
        json.dumps(draft, allow_nan=False)
        with self._save_lock:
            if draft == self._config:
                return False
            overrides = deepcopy(self._overrides)

            def changed(node, previous, target):
                for key in previous.keys() - node.keys():
                    target.pop(key, None)
                for key, value in node.items():
                    old = previous.get(key, _MISSING)
                    if isinstance(value, dict) and isinstance(old, dict):
                        branch = target.setdefault(key, {})
                        changed(value, old, branch)
                    elif old is _MISSING or old != value:
                        target[key] = deepcopy(value)
            changed(draft, self._config, overrides)
            fd, temporary = tempfile.mkstemp(
                dir=os.path.dirname(os.path.abspath(self.config_path)),
                prefix=".startup-config-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    json.dump(overrides, handle, indent=2, ensure_ascii=False, allow_nan=False)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.config_path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
            self._overrides = overrides
            self._config = draft
            self._dirty = False
            return True

    def set(self, *keys, value=None):
        if not keys:
            raise ValueError("At least one config key is required.")

        with self._save_lock:
            node = self._config
            for key in keys[:-1]:
                if not isinstance(node.get(key), dict):
                    node[key] = {}
                node = node[key]

            old_value = node.get(keys[-1], _MISSING)
            if old_value is not _MISSING and old_value == value:
                return False

            node[keys[-1]] = deepcopy(value)

            override_node = self._overrides
            for key in keys[:-1]:
                if not isinstance(override_node.get(key), dict):
                    override_node[key] = {}
                override_node = override_node[key]
            override_node[keys[-1]] = deepcopy(value)
            self._dirty = True
            self._schedule_save()
        return True


config = Config()
