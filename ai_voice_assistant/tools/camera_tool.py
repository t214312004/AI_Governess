"""Tracked Windows camera implementation used by the private agent workspace wrapper."""

from __future__ import annotations

import argparse
import json
import queue
import re
import sys
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

import av
import av.error
import av.logging
from PIL import Image

DEVICE_LINE_PATTERN = re.compile(r'^"(?P<name>.+)" \((?P<kind>video|audio)\)$')
ALT_NAME_PATTERN = re.compile(r'^Alternative name "(?P<name>.+)"$')
MODE_LINE_PATTERN = re.compile(
    r"pixel_format=(?P<pixel_format>[A-Za-z0-9_]+) "
    r"min s=(?P<width>\d+)x(?P<height>\d+) fps=(?P<min_fps>[0-9.]+) "
    r"max s=(?P<max_width>\d+)x(?P<max_height>\d+) fps=(?P<max_fps>[0-9.]+)"
)
RESOLUTION_PATTERN = re.compile(r"^(?P<width>\d+)x(?P<height>\d+)$")
RESOLUTION_ALIASES = {
    "auto": None,
    "max": None,
    "highest": None,
    "best": None,
    "high": None,
    "medium": "medium",
    "mid": "medium",
    "low": "low",
    "fhd": (1920, 1080),
    "fullhd": (1920, 1080),
    "hd": (1280, 720),
    "vga": (640, 480),
}
DEFAULT_SETTLE_FRAMES = 6
DEFAULT_CAPTURE_TIMEOUT_SECONDS = 15.0
APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = APP_DIR / "agent_workspace" / "tools" / "camera" / "camera_capture"
DEFAULT_EXTENSION = ".jpg"


class CameraToolError(RuntimeError):
    pass


@dataclass(slots=True)
class CameraDevice:
    name: str
    alternative_name: str | None = None


@dataclass(slots=True)
class CameraResolution:
    width: int
    height: int
    min_fps: float
    max_fps: float
    pixel_formats: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def pixels(self) -> int:
        return self.width * self.height


def _sorted_resolutions(resolutions: Iterable[CameraResolution]) -> list[CameraResolution]:
    return sorted(
        resolutions,
        key=lambda item: (item.pixels, item.max_fps, item.width, item.height),
        reverse=True,
    )


def _normalize_log_lines(
    log_entries: Iterable[tuple[int, str, str]],
    *,
    module: str = "dshow",
) -> list[str]:
    text = "".join(message for _, source, message in log_entries if source == module)
    return [re.sub(r"\s+", " ", line.strip()) for line in text.splitlines() if line.strip()]


def _probe_dshow(
    target: str,
    *,
    options: dict[str, str],
) -> tuple[list[tuple[int, str, str]], Exception | None]:
    av.logging.set_level(av.logging.INFO)
    with av.logging.Capture() as logs:
        try:
            container = av.open(target, format="dshow", mode="r", options=options)
            container.close()
        except av.error.ExitError:
            return list(logs), None
        except av.error.FFmpegError as exc:
            return list(logs), exc
    return list(logs), None


def _parse_video_devices(log_entries: Iterable[tuple[int, str, str]]) -> list[CameraDevice]:
    devices: list[CameraDevice] = []
    current_device: CameraDevice | None = None
    for line in _normalize_log_lines(log_entries):
        match = DEVICE_LINE_PATTERN.match(line)
        if match:
            current_device = None
            if match.group("kind") == "video":
                current_device = CameraDevice(name=match.group("name"))
                devices.append(current_device)
            continue
        alt_match = ALT_NAME_PATTERN.match(line)
        if alt_match and current_device is not None:
            current_device.alternative_name = alt_match.group("name")
    return devices


def _parse_resolutions(
    log_entries: Iterable[tuple[int, str, str]],
) -> list[CameraResolution]:
    by_size: dict[tuple[int, int], CameraResolution] = {}
    for line in _normalize_log_lines(log_entries):
        match = MODE_LINE_PATTERN.search(line)
        if not match:
            continue
        width = int(match.group("width"))
        height = int(match.group("height"))
        if (width, height) != (
            int(match.group("max_width")),
            int(match.group("max_height")),
        ):
            continue
        key = (width, height)
        pixel_format = match.group("pixel_format")
        min_fps = float(match.group("min_fps"))
        max_fps = float(match.group("max_fps"))
        item = by_size.get(key)
        if item is None:
            by_size[key] = CameraResolution(
                width=width,
                height=height,
                min_fps=min_fps,
                max_fps=max_fps,
                pixel_formats=[pixel_format],
            )
            continue
        item.min_fps = min(item.min_fps, min_fps)
        item.max_fps = max(item.max_fps, max_fps)
        if pixel_format not in item.pixel_formats:
            item.pixel_formats.append(pixel_format)
    return _sorted_resolutions(by_size.values())


def list_video_devices() -> list[CameraDevice]:
    log_entries, probe_error = _probe_dshow("video=dummy", options={"list_devices": "true"})
    devices = _parse_video_devices(log_entries)
    if devices:
        return devices
    if probe_error is not None:
        raise CameraToolError(f"無法列出攝影機裝置：{probe_error}") from probe_error
    raise CameraToolError("找不到可用的 DirectShow 攝影機裝置。")


def _resolve_device(requested_name: str | None) -> CameraDevice:
    devices = list_video_devices()
    if not devices:
        raise CameraToolError("找不到可用的攝影機裝置。")
    if not requested_name:
        return devices[0]
    normalized = requested_name.casefold()
    for device in devices:
        if device.name.casefold() == normalized:
            return device
        if device.alternative_name and device.alternative_name.casefold() == normalized:
            return device
    known_names = ", ".join(device.name for device in devices)
    raise CameraToolError(f"找不到指定攝影機：{requested_name}。可用裝置：{known_names}")


def list_supported_resolutions(device_name: str) -> list[CameraResolution]:
    log_entries, probe_error = _probe_dshow(
        f"video={device_name}",
        options={"list_options": "true"},
    )
    resolutions = _parse_resolutions(log_entries)
    if resolutions:
        return resolutions
    if probe_error is not None:
        raise CameraToolError(f"無法讀取攝影機解析度：{probe_error}") from probe_error
    raise CameraToolError(f"攝影機 {device_name} 沒有回報可用解析度。")


def _nearest_resolution(
    target_width: int,
    target_height: int,
    resolutions: Iterable[CameraResolution],
) -> CameraResolution:
    return min(
        resolutions,
        key=lambda item: (
            abs(item.width - target_width) + abs(item.height - target_height),
            abs(item.pixels - (target_width * target_height)),
            -item.max_fps,
        ),
    )


def resolve_resolution(
    request: str | None,
    resolutions: Iterable[CameraResolution],
    *,
    fallback: str,
) -> tuple[CameraResolution, str]:
    ordered = _sorted_resolutions(resolutions)
    if not ordered:
        raise CameraToolError("攝影機沒有可用解析度。")
    raw_request = (request or "auto").strip().lower()
    alias_value = RESOLUTION_ALIASES.get(raw_request)
    if raw_request in ("auto", "max", "highest", "best", "high"):
        return ordered[0], "alias"
    if alias_value == "medium":
        return ordered[len(ordered) // 2], "alias"
    if alias_value == "low":
        return ordered[-1], "alias"
    if isinstance(alias_value, tuple):
        target_width, target_height = alias_value
    else:
        match = RESOLUTION_PATTERN.match(raw_request)
        if not match:
            accepted = ", ".join(sorted(RESOLUTION_ALIASES))
            raise CameraToolError(
                f"無法解析解析度要求：{request}。請使用 WIDTHxHEIGHT 或 {accepted}。"
            )
        target_width = int(match.group("width"))
        target_height = int(match.group("height"))
    for item in ordered:
        if item.width == target_width and item.height == target_height:
            return item, "exact"
    if fallback == "nearest":
        return _nearest_resolution(target_width, target_height, ordered), "nearest"
    raise CameraToolError(
        f"攝影機不支援 {target_width}x{target_height}。請先執行 list-resolutions。"
    )


def _build_output_path(output: str | None) -> Path:
    if output:
        target = Path(output).expanduser()
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        unique = uuid.uuid4().hex[:8]
        target = DEFAULT_OUTPUT_DIR / f"capture-{stamp}-{unique}{DEFAULT_EXTENSION}"
    if not target.suffix:
        target = target.with_suffix(DEFAULT_EXTENSION)
    if not target.is_absolute():
        target = Path.cwd() / target
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _save_image(image: Image.Image, output_path: Path) -> None:
    if output_path.suffix.lower() in {".jpg", ".jpeg"}:
        image.convert("RGB").save(output_path, quality=95)
    else:
        image.save(output_path)


def _capture_usable_frame(
    device: CameraDevice,
    resolution: CameraResolution,
    settle_frames: int,
    timeout_seconds: float,
) -> tuple[Image.Image, int]:
    if timeout_seconds <= 0:
        raise CameraToolError("拍照逾時秒數必須大於 0。")
    result_queue: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

    def worker() -> None:
        container = None
        try:
            container = av.open(
                f"video={device.name}",
                format="dshow",
                mode="r",
                options={
                    "video_size": resolution.label,
                    "framerate": f"{resolution.max_fps:g}",
                    "rtbufsize": "256M",
                },
            )
            decoded_frames = 0
            image: Image.Image | None = None
            for frame in container.decode(video=0):
                decoded_frames += 1
                if decoded_frames <= settle_frames:
                    continue
                image = frame.to_image()
                break
            if image is None:
                raise CameraToolError(
                    f"攝影機在略過 {settle_frames} 幀後沒有回傳可用畫面，拍照失敗。"
                )
            result_queue.put(("ok", (image, decoded_frames)))
        except Exception as exc:
            result_queue.put(("error", exc))
        finally:
            if container is not None:
                container.close()

    capture_thread = threading.Thread(target=worker, name="camera-capture", daemon=True)
    capture_thread.start()
    capture_thread.join(timeout_seconds)
    if capture_thread.is_alive():
        raise CameraToolError(f"攝影機在 {timeout_seconds:g} 秒內沒有回傳畫面，拍照逾時。")
    try:
        status, payload = result_queue.get_nowait()
    except queue.Empty as exc:
        raise CameraToolError("攝影機工作執行緒未回傳結果。") from exc
    if status == "error":
        raise payload  # type: ignore[misc]
    return payload  # type: ignore[return-value]


def capture_photo(
    *,
    device_name: str | None,
    resolution_request: str | None,
    output: str | None,
    fallback: str,
    settle_frames: int,
    timeout_seconds: float = DEFAULT_CAPTURE_TIMEOUT_SECONDS,
) -> dict[str, object]:
    device = _resolve_device(device_name)
    selected_resolution, selection_mode = resolve_resolution(
        resolution_request,
        list_supported_resolutions(device.name),
        fallback=fallback,
    )
    output_path = _build_output_path(output)
    image, decoded_frames = _capture_usable_frame(
        device,
        selected_resolution,
        max(0, settle_frames),
        float(timeout_seconds),
    )
    _save_image(image, output_path)
    return {
        "ok": True,
        "command": "capture",
        "device": asdict(device),
        "requested_resolution": resolution_request or "auto",
        "selected_resolution": {**asdict(selected_resolution), "label": selected_resolution.label},
        "selection_mode": selection_mode,
        "output_path": str(output_path),
        "bytes_written": output_path.stat().st_size,
        "decoded_frames": decoded_frames,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
    }


def _emit(payload: dict[str, object]) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _emit_error(message: str) -> int:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2), file=sys.stderr)
    return 1


def handle_list_devices(_args: argparse.Namespace) -> int:
    return _emit({"ok": True, "command": "list-devices", "devices": [asdict(item) for item in list_video_devices()]})


def handle_list_resolutions(args: argparse.Namespace) -> int:
    device = _resolve_device(args.device)
    resolutions = [
        {**asdict(item), "label": item.label}
        for item in list_supported_resolutions(device.name)
    ]
    return _emit(
        {"ok": True, "command": "list-resolutions", "device": asdict(device), "resolutions": resolutions}
    )


def handle_capture(args: argparse.Namespace) -> int:
    return _emit(
        capture_photo(
            device_name=args.device,
            resolution_request=args.resolution,
            output=args.output,
            fallback=args.fallback,
            settle_frames=args.settle_frames,
            timeout_seconds=args.timeout_seconds,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Windows camera utility for agent-driven photo capture.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_devices_parser = subparsers.add_parser("list-devices", help="List DirectShow camera devices.")
    list_devices_parser.set_defaults(command_handler=handle_list_devices)
    list_resolutions_parser = subparsers.add_parser("list-resolutions", help="List supported resolutions for a camera.")
    list_resolutions_parser.add_argument("--device")
    list_resolutions_parser.set_defaults(command_handler=handle_list_resolutions)
    capture_parser = subparsers.add_parser("capture", help="Capture a photo.")
    capture_parser.add_argument("--device")
    capture_parser.add_argument("--resolution", default="auto")
    capture_parser.add_argument("--output")
    capture_parser.add_argument("--fallback", default="nearest", choices=("nearest", "error"))
    capture_parser.add_argument("--settle-frames", type=int, default=DEFAULT_SETTLE_FRAMES)
    capture_parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_CAPTURE_TIMEOUT_SECONDS,
        help="Maximum time to wait for camera open and frame decode.",
    )
    capture_parser.set_defaults(command_handler=handle_capture)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.command_handler(args)
    except CameraToolError as exc:
        return _emit_error(str(exc))
    except av.error.FFmpegError as exc:
        return _emit_error(f"FFmpeg/PyAV 攝影機操作失敗：{exc}")
    except KeyboardInterrupt:
        return _emit_error("已取消拍照。")
    except Exception as exc:
        return _emit_error(f"攝影機操作失敗：{exc}")


if __name__ == "__main__":
    raise SystemExit(main())
