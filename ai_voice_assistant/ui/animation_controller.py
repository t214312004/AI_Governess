"""State animation loading and playback for the assistant stage."""

import json
import re
from pathlib import Path

from core.state_machine import State
from utils.logger import get_logger

logger = get_logger(__name__)

ASSETS_DIR = Path(__file__).parent.parent / "assets" / "states"
ANIMATION_MANIFEST = ASSETS_DIR / "animation_manifest.json"

STATE_IMAGE_PREFIX = {
    State.IDLE_LISTEN: "idle_listen",
    State.COLLECTING: "collecting",
    State.SENDING: "sending",
    State.SPEAKING: "speaking",
    State.HOT_LISTEN: "hot_listen",
}


class AnimationController:
    """Loads state animations first, then falls back to numbered PNG frames."""

    def __init__(
        self,
        label_widget,
        interval_ms: int = 500,
        image_size: tuple[int, int] = (640, 640),
        background_label_widget=None,
    ):
        self.label = label_widget
        self.background_label = background_label_widget
        self.interval_ms = interval_ms
        self.image_size = image_size
        self._current_state: State = State.IDLE_LISTEN
        self._frame_index: int = 0
        self._images: list = []
        self._durations_ms: list[int] = []
        self._after_id = None
        self._tk_images_cache: dict = {}
        self._cache_size_order: list = []
        self._max_cache_sizes: int = 2
        self._has_images: bool = False
        self._animation_extensions: tuple[str, ...] = (".webp", ".gif")
        self._manifest: dict | None = None
        self._background_image = None
        self._background_pil_cache: dict[Path, object] = {}

    def set_state(self, state: State):
        if state == self._current_state and self._has_images:
            return
        self._current_state = state
        self._frame_index = 0
        self._load_images(state)
        self._stop_timer()
        if self._has_images:
            self._tick()

    def start(self):
        if self._has_images and self._after_id is None:
            self._tick()

    def set_image_size(self, width: int, height: int):
        new_size = (max(1, int(width)), max(1, int(height)))
        if new_size == self.image_size:
            return
        self.image_size = new_size
        self._frame_index = 0
        self._load_images(self._current_state)
        if self._has_images:
            try:
                self.label.configure(image=self._images[0], text="")
            except Exception as e:
                logger.warning("Failed to update animation image after resize: %s", e)

    def destroy(self):
        self._stop_timer()

    def _load_images(self, state: State):
        try:
            import customtkinter as ctk
            from PIL import Image, ImageSequence
        except ImportError:
            logger.warning("customtkinter or PIL is unavailable; animation images cannot be loaded.")
            self._set_loaded_frames([], [])
            return

        prefix = STATE_IMAGE_PREFIX.get(state, "idle_listen")
        self._clear_background_image()

        for extension in self._animation_extensions:
            animation_path = ASSETS_DIR / f"{prefix}{extension}"
            if not animation_path.exists():
                continue
            images, durations = self._load_animation_frames(animation_path, prefix, ctk, Image, ImageSequence)
            if images:
                self._set_loaded_frames(images, durations)
                return
            logger.warning("Falling back because animation could not be loaded: %s", animation_path.name)

        images = self._load_png_frames(prefix, ctk, Image)
        if images:
            self._set_loaded_frames(images, [self.interval_ms] * len(images))
            return

        layered_images = self._load_layered_png_frames(prefix, ctk, Image)
        self._set_loaded_frames(layered_images, [self.interval_ms] * len(layered_images))

    def _load_animation_frames(self, path: Path, prefix: str, ctk, image_module, image_sequence) -> tuple[list, list[int]]:
        cache_key = (path, self.image_size, path.suffix.lower())
        if cache_key in self._tk_images_cache:
            return self._tk_images_cache[cache_key]

        loaded = []
        durations = []
        try:
            with image_module.open(path) as animation:
                for frame_index, frame in enumerate(image_sequence.Iterator(animation)):
                    pil_img = frame.convert("RGBA")
                    loaded.append(ctk.CTkImage(pil_img, size=self.image_size))
                    durations.append(
                        self._resolve_frame_duration_ms(
                            prefix,
                            path.suffix.lower(),
                            frame_index,
                            frame.info.get("duration"),
                        )
                    )
        except Exception as e:
            logger.warning("Failed to load animation %s: %s", path.name, e)
            return [], []

        self._remember_cache_entry(cache_key, (loaded, durations))
        return loaded, durations

    def _load_layered_png_frames(self, prefix: str, ctk, image_module) -> list:
        layered_assets_dir = ASSETS_DIR / "layers"
        layered_background = layered_assets_dir / "background.png"
        if not layered_background.exists():
            return []

        matched_paths = self._matched_png_paths(layered_assets_dir, prefix, allow_multi_digit=True)
        if not matched_paths:
            return []

        background_pil = self._load_background_pil(image_module, layered_background)
        if background_pil is None:
            return []

        loaded = []
        for _index, path in matched_paths:
            cache_key = (path, self.image_size, "layered_png")
            if cache_key in self._tk_images_cache:
                loaded.append(self._tk_images_cache[cache_key])
                continue
            try:
                foreground = image_module.open(path).convert("RGBA")
                pil_img = background_pil.copy()
                pil_img.alpha_composite(foreground)
                ctk_img = ctk.CTkImage(pil_img, size=self.image_size)
                self._remember_cache_entry(cache_key, ctk_img)
                loaded.append(ctk_img)
                logger.debug("Loaded layered animation frame: %s", path.name)
            except Exception as e:
                logger.warning("Failed to load layered animation frame %s: %s", path.name, e)

        if loaded:
            self._clear_background_image()
        return loaded

    def _load_background_pil(self, image_module, layered_background: Path):
        if layered_background in self._background_pil_cache:
            return self._background_pil_cache[layered_background]
        try:
            pil_img = image_module.open(layered_background).convert("RGBA")
            self._background_pil_cache[layered_background] = pil_img
            return pil_img
        except Exception as e:
            logger.warning("Failed to load layered animation background: %s", e)
            return None

    def _set_background_image(self, image):
        self._background_image = image
        if self.background_label is None:
            return
        try:
            self.background_label.configure(image=image, text="")
        except Exception as e:
            logger.warning("Failed to set layered animation background: %s", e)

    def _clear_background_image(self):
        self._background_image = None
        if self.background_label is None:
            return
        try:
            self.background_label.configure(image=None, text="")
        except Exception:
            pass

    def _matched_png_paths(self, directory: Path, prefix: str, allow_multi_digit: bool = False) -> list[tuple[int, Path]]:
        frame_pattern = r"[1-9][0-9]*" if allow_multi_digit else r"[1-9]"
        pattern = re.compile(rf"^{re.escape(prefix)}_({frame_pattern})\.png$")
        return sorted(
            (
                (int(match.group(1)), path)
                for path in directory.glob(f"{prefix}_*.png")
                if (match := pattern.match(path.name))
            ),
            key=lambda item: item[0],
        )

    def _load_png_frames(self, prefix: str, ctk, image_module) -> list:
        loaded = []
        matched_paths = self._matched_png_paths(ASSETS_DIR, prefix)

        for _index, path in matched_paths:
            cache_key = (path, self.image_size, "png")
            if cache_key in self._tk_images_cache:
                loaded.append(self._tk_images_cache[cache_key])
                continue
            try:
                pil_img = image_module.open(path)
                ctk_img = ctk.CTkImage(pil_img, size=self.image_size)
                self._remember_cache_entry(cache_key, ctk_img)
                loaded.append(ctk_img)
                logger.debug("Loaded animation frame: %s", path.name)
            except Exception as e:
                logger.warning("Failed to load animation frame %s: %s", path.name, e)

        return loaded

    def _set_loaded_frames(self, images: list, durations_ms: list[int]):
        self._images = images
        self._durations_ms = durations_ms
        self._has_images = bool(images)

    def _resolve_frame_duration_ms(self, prefix: str, extension: str, frame_index: int, encoded_duration_ms) -> int:
        try:
            encoded_duration = int(encoded_duration_ms)
        except (TypeError, ValueError):
            encoded_duration = 0
        if encoded_duration > 0:
            return self._normalize_duration_ms(encoded_duration)

        manifest = self._load_manifest()
        state_manifest = manifest.get(prefix, {})
        extension_manifest = state_manifest.get(extension.lstrip("."), {})
        durations = extension_manifest.get("durations_ms")
        if isinstance(durations, list) and durations:
            try:
                return self._normalize_duration_ms(durations[frame_index % len(durations)])
            except (TypeError, ValueError):
                pass

        default_duration = extension_manifest.get("duration_ms", state_manifest.get("duration_ms"))
        return self._normalize_duration_ms(default_duration)

    def _load_manifest(self) -> dict:
        if self._manifest is not None:
            return self._manifest

        try:
            with ANIMATION_MANIFEST.open("r", encoding="utf-8") as f:
                manifest = json.load(f)
        except FileNotFoundError:
            manifest = {}
        except Exception as e:
            logger.warning("Failed to load animation manifest: %s", e)
            manifest = {}

        self._manifest = manifest if isinstance(manifest, dict) else {}
        return self._manifest

    def _remember_cache_entry(self, cache_key, value):
        self._tk_images_cache[cache_key] = value
        size = cache_key[1]
        if size not in self._cache_size_order:
            self._cache_size_order.append(size)
            while len(self._cache_size_order) > self._max_cache_sizes:
                oldest_size = self._cache_size_order.pop(0)
                keys_to_del = [k for k in self._tk_images_cache if k[1] == oldest_size]
                for key in keys_to_del:
                    del self._tk_images_cache[key]

    def _tick(self):
        if not self._has_images or not self._images:
            return
        try:
            img = self._images[self._frame_index % len(self._images)]
            delay_ms = self._get_current_frame_duration()
            self.label.configure(image=img, text="")
            self._frame_index = (self._frame_index + 1) % len(self._images)
            self._after_id = self.label.after(delay_ms, self._tick)
        except Exception as e:
            logger.warning("Animation tick failed: %s", e)
            self._stop_timer()

    def _get_current_frame_duration(self) -> int:
        if not self._durations_ms:
            return self.interval_ms
        index = self._frame_index % len(self._durations_ms)
        return self._normalize_duration_ms(self._durations_ms[index])

    def _normalize_duration_ms(self, duration_ms) -> int:
        try:
            duration = int(duration_ms)
        except (TypeError, ValueError):
            duration = self.interval_ms
        return max(20, duration)

    def _stop_timer(self):
        if self._after_id is not None:
            try:
                self.label.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
