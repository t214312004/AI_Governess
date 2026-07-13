from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import camera_tool


def _log_entries(text: str) -> list[tuple[int, str, str]]:
    return [(32, "dshow", text)]


def test_list_video_devices_filters_audio(monkeypatch):
    monkeypatch.setattr(
        camera_tool,
        "_probe_dshow",
        lambda target, options: (
            _log_entries(
                '"ASUS FHD webcam" (video)\n'
                '  Alternative name "@device_pnp_1"\n'
                '"Microphone Array" (audio)\n'
                '  Alternative name "@device_audio_1"\n'
            ),
            None,
        ),
    )

    devices = camera_tool.list_video_devices()

    assert [device.name for device in devices] == ["ASUS FHD webcam"]
    assert devices[0].alternative_name == "@device_pnp_1"


def test_list_supported_resolutions_aggregates_pixel_formats(monkeypatch):
    monkeypatch.setattr(
        camera_tool,
        "_probe_dshow",
        lambda target, options: (
            _log_entries(
                "DirectShow video device options (from video devices)\n"
                ' Pin "Capture"\n'
                "  pixel_format=yuyv422  min s=1920x1080 fps=15 max s=1920x1080 fps=30\n"
                "  pixel_format=nv12  min s=1920x1080 fps=15 max s=1920x1080 fps=30\n"
                "  pixel_format=yuyv422  min s=1280x720 fps=15 max s=1280x720 fps=30\n"
            ),
            None,
        ),
    )

    resolutions = camera_tool.list_supported_resolutions("ASUS FHD webcam")

    assert [item.label for item in resolutions] == ["1920x1080", "1280x720"]
    assert resolutions[0].pixel_formats == ["yuyv422", "nv12"]


def test_resolve_resolution_uses_nearest_fallback():
    available = [
        camera_tool.CameraResolution(width=1920, height=1080, min_fps=15, max_fps=30),
        camera_tool.CameraResolution(width=1280, height=720, min_fps=15, max_fps=30),
        camera_tool.CameraResolution(width=640, height=480, min_fps=15, max_fps=30),
    ]

    selected, selection_mode = camera_tool.resolve_resolution(
        "1280x800",
        available,
        fallback="nearest",
    )

    assert selected.label == "1280x720"
    assert selection_mode == "nearest"


def test_capture_photo_uses_default_device_and_writes_file(monkeypatch, tmp_path):
    fake_device = camera_tool.CameraDevice(name="ASUS FHD webcam", alternative_name="@device_pnp_1")
    fake_resolution = camera_tool.CameraResolution(
        width=1280,
        height=720,
        min_fps=15,
        max_fps=30,
        pixel_formats=["nv12"],
    )

    monkeypatch.setattr(camera_tool, "_resolve_device", lambda requested_name: fake_device)
    monkeypatch.setattr(camera_tool, "list_supported_resolutions", lambda device_name: [fake_resolution])

    class FakeFrame:
        def to_image(self):
            return Image.new("RGB", (1280, 720), "white")

    class FakeContainer:
        def decode(self, video=0):
            yield FakeFrame()

        def close(self):
            return None

    monkeypatch.setattr(camera_tool.av, "open", lambda *args, **kwargs: FakeContainer())

    output_path = tmp_path / "capture.jpg"
    result = camera_tool.capture_photo(
        device_name=None,
        resolution_request="hd",
        output=str(output_path),
        fallback="nearest",
        settle_frames=0,
    )

    assert result["ok"] is True
    assert result["selection_mode"] == "exact"
    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_default_output_paths_are_unique(monkeypatch, tmp_path):
    monkeypatch.setattr(camera_tool, "DEFAULT_OUTPUT_DIR", tmp_path)

    first = camera_tool._build_output_path(None)
    second = camera_tool._build_output_path(None)

    assert first != second
    assert first.parent == tmp_path
    assert second.parent == tmp_path


def test_capture_photo_rejects_stream_that_only_contains_settle_frames(monkeypatch, tmp_path):
    fake_device = camera_tool.CameraDevice(name="camera")
    fake_resolution = camera_tool.CameraResolution(640, 480, 15, 30)
    monkeypatch.setattr(camera_tool, "_resolve_device", lambda _name: fake_device)
    monkeypatch.setattr(camera_tool, "list_supported_resolutions", lambda _name: [fake_resolution])

    class FakeFrame:
        def to_image(self):
            return Image.new("RGB", (640, 480), "white")

    class FakeContainer:
        def decode(self, video=0):
            yield FakeFrame()

        def close(self):
            return None

    monkeypatch.setattr(camera_tool.av, "open", lambda *args, **kwargs: FakeContainer())

    import pytest

    with pytest.raises(camera_tool.CameraToolError, match="略過 1 幀後沒有回傳"):
        camera_tool.capture_photo(
            device_name=None,
            resolution_request="vga",
            output=str(tmp_path / "capture.jpg"),
            fallback="nearest",
            settle_frames=1,
        )


def test_capture_photo_times_out_when_decode_stalls(monkeypatch, tmp_path):
    import time
    import pytest

    fake_device = camera_tool.CameraDevice(name="camera")
    fake_resolution = camera_tool.CameraResolution(640, 480, 15, 30)
    monkeypatch.setattr(camera_tool, "_resolve_device", lambda _name: fake_device)
    monkeypatch.setattr(camera_tool, "list_supported_resolutions", lambda _name: [fake_resolution])

    class FakeContainer:
        def decode(self, video=0):
            time.sleep(0.1)
            return iter(())

        def close(self):
            return None

    monkeypatch.setattr(camera_tool.av, "open", lambda *args, **kwargs: FakeContainer())

    with pytest.raises(camera_tool.CameraToolError, match="拍照逾時"):
        camera_tool.capture_photo(
            device_name=None,
            resolution_request="vga",
            output=str(tmp_path / "capture.jpg"),
            fallback="nearest",
            settle_frames=0,
            timeout_seconds=0.01,
        )

