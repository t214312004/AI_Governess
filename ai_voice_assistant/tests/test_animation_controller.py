from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image

from core.state_machine import State
from ui.animation_controller import AnimationController


def make_controller():
    label = MagicMock()
    label.after = MagicMock(return_value="after-token")
    label.after_cancel = MagicMock()
    return AnimationController(label, interval_ms=250, image_size=(320, 320))


def test_load_images_detects_only_matching_numbered_pngs(mocker, tmp_path):
    states_dir = tmp_path / "states"
    states_dir.mkdir()
    for filename in (
        "idle_listen_1.png",
        "idle_listen_2.png",
        "idle_listen_4.png",
        "idle_listen_9.png",
        "idle_listen_0.png",
        "idle_listen_10.png",
        "idle_listen_pic.png",
        "idle_listen_3.jpg",
        "collecting_1.png",
    ):
        (states_dir / filename).write_bytes(b"test")

    mock_ctk_image = mocker.patch(
        "customtkinter.CTkImage",
        side_effect=lambda image, size: f"{Path(image.filename).name}@{size}",
    )
    mocker.patch("PIL.Image.open", side_effect=lambda path: MagicMock(filename=str(path)))
    mocker.patch("ui.animation_controller.ASSETS_DIR", states_dir)

    controller = make_controller()

    controller._load_images(State.IDLE_LISTEN)

    assert controller._has_images is True
    assert controller._images == [
        "idle_listen_1.png@(320, 320)",
        "idle_listen_2.png@(320, 320)",
        "idle_listen_4.png@(320, 320)",
        "idle_listen_9.png@(320, 320)",
        "idle_listen_10.png@(320, 320)",
    ]
    assert mock_ctk_image.call_count == 5


def test_load_images_supports_different_frame_counts_per_state(mocker, tmp_path):
    states_dir = tmp_path / "states"
    states_dir.mkdir()
    for filename in ("collecting_1.png", "collecting_2.png", "speaking_1.png"):
        (states_dir / filename).write_bytes(b"test")

    mocker.patch(
        "customtkinter.CTkImage",
        side_effect=lambda image, size: f"{Path(image.filename).name}@{size}",
    )
    mocker.patch("PIL.Image.open", side_effect=lambda path: MagicMock(filename=str(path)))
    mocker.patch("ui.animation_controller.ASSETS_DIR", states_dir)

    controller = make_controller()

    controller._load_images(State.COLLECTING)
    collecting_images = list(controller._images)
    controller._load_images(State.SPEAKING)
    speaking_images = list(controller._images)

    assert collecting_images == [
        "collecting_1.png@(320, 320)",
        "collecting_2.png@(320, 320)",
    ]
    assert speaking_images == ["speaking_1.png@(320, 320)"]


def test_layered_png_frames_preserve_source_aspect_ratio(mocker, tmp_path):
    states_dir = tmp_path / "states"
    layers_dir = states_dir / "layers"
    layers_dir.mkdir(parents=True)

    Image.new("RGBA", (1118, 1012), (255, 240, 230, 255)).save(layers_dir / "background.png")
    Image.new("RGBA", (1118, 1012), (0, 0, 0, 0)).save(layers_dir / "idle_listen_1.png")

    mocker.patch(
        "customtkinter.CTkImage",
        side_effect=lambda image, size: f"{image.size}@{size}",
    )
    mocker.patch("ui.animation_controller.ASSETS_DIR", states_dir)

    controller = make_controller()

    controller._load_images(State.IDLE_LISTEN)

    assert controller._images == ["(1118, 1012)@(320, 290)"]


def test_layered_png_frames_apply_configured_foreground_y_offset(mocker, tmp_path):
    states_dir = tmp_path / "states"
    layers_dir = states_dir / "layers"
    layers_dir.mkdir(parents=True)

    Image.new("RGBA", (4, 4), (255, 255, 255, 255)).save(layers_dir / "background.png")
    foreground = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    foreground.putpixel((1, 0), (0, 0, 255, 255))
    foreground.save(layers_dir / "idle_listen_1.png")

    rendered_images = []
    mocker.patch(
        "customtkinter.CTkImage",
        side_effect=lambda image, size: rendered_images.append(image.copy()) or "frame",
    )
    mocker.patch("ui.animation_controller.ASSETS_DIR", states_dir)

    controller = AnimationController(
        MagicMock(),
        image_size=(4, 4),
        foreground_y_offset_px=-1,
    )

    controller._load_images(State.IDLE_LISTEN)

    assert rendered_images[0].getpixel((1, 0)) == (255, 255, 255, 255)
    assert rendered_images[0].getpixel((1, 1)) == (0, 0, 255, 255)


def test_layered_png_frames_center_smaller_foreground_on_background(mocker, tmp_path):
    states_dir = tmp_path / "states"
    layers_dir = states_dir / "layers"
    layers_dir.mkdir(parents=True)

    Image.new("RGBA", (6, 6), (255, 255, 255, 255)).save(layers_dir / "background.png")
    foreground = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
    foreground.putpixel((0, 0), (0, 0, 255, 255))
    foreground.save(layers_dir / "idle_listen_1.png")

    rendered_images = []
    mocker.patch(
        "customtkinter.CTkImage",
        side_effect=lambda image, size: rendered_images.append(image.copy()) or "frame",
    )
    mocker.patch("ui.animation_controller.ASSETS_DIR", states_dir)

    controller = AnimationController(MagicMock(), image_size=(6, 6))

    controller._load_images(State.IDLE_LISTEN)

    assert rendered_images[0].getpixel((0, 0)) == (255, 255, 255, 255)
    assert rendered_images[0].getpixel((2, 2)) == (0, 0, 255, 255)


def test_matched_png_paths_sort_multi_digit_frames_numerically(tmp_path):
    for filename in (
        "idle_listen_1.png",
        "idle_listen_10.png",
        "idle_listen_2.png",
        "idle_listen_12.png",
        "idle_listen_0.png",
        "idle_listen_pic.png",
    ):
        (tmp_path / filename).write_bytes(b"test")

    controller = make_controller()

    matched = controller._matched_png_paths(tmp_path, "idle_listen")

    assert [(index, path.name) for index, path in matched] == [
        (1, "idle_listen_1.png"),
        (2, "idle_listen_2.png"),
        (10, "idle_listen_10.png"),
        (12, "idle_listen_12.png"),
    ]


def test_load_images_prefers_state_gif_over_png_sequence(mocker, tmp_path):
    states_dir = tmp_path / "states"
    states_dir.mkdir()

    frames = [
        Image.new("RGBA", (4, 4), (255, 0, 0, 255)),
        Image.new("RGBA", (4, 4), (0, 255, 0, 255)),
    ]
    frames[0].save(
        states_dir / "idle_listen.gif",
        save_all=True,
        append_images=frames[1:],
        duration=[120, 340],
        loop=0,
    )
    (states_dir / "idle_listen_1.png").write_bytes(b"png fallback")

    frame_numbers = iter((1, 2))
    mock_ctk_image = mocker.patch(
        "customtkinter.CTkImage",
        side_effect=lambda image, size: f"gif-frame-{next(frame_numbers)}@{size}",
    )
    mocker.patch("ui.animation_controller.ASSETS_DIR", states_dir)

    controller = make_controller()

    controller._load_images(State.IDLE_LISTEN)

    assert controller._has_images is True
    assert controller._images == [
        "gif-frame-1@(320, 320)",
        "gif-frame-2@(320, 320)",
    ]
    assert controller._durations_ms == [120, 340]
    assert mock_ctk_image.call_count == 2


def test_load_images_prefers_webp_over_gif_and_png(mocker, tmp_path):
    states_dir = tmp_path / "states"
    states_dir.mkdir()

    frames = [
        Image.new("RGBA", (4, 4), (255, 0, 0, 255)),
        Image.new("RGBA", (4, 4), (0, 255, 0, 255)),
    ]
    frames[0].save(
        states_dir / "idle_listen.webp",
        save_all=True,
        append_images=frames[1:],
        duration=[90, 180],
        loop=0,
        lossless=True,
    )
    frames[0].save(
        states_dir / "idle_listen.gif",
        save_all=True,
        append_images=frames[1:],
        duration=[120, 340],
        loop=0,
    )
    (states_dir / "idle_listen_1.png").write_bytes(b"png fallback")

    frame_numbers = iter((1, 2))
    mock_ctk_image = mocker.patch(
        "customtkinter.CTkImage",
        side_effect=lambda image, size: f"webp-frame-{next(frame_numbers)}@{size}",
    )
    mocker.patch("ui.animation_controller.ASSETS_DIR", states_dir)

    controller = make_controller()

    controller._load_images(State.IDLE_LISTEN)

    assert controller._has_images is True
    assert controller._images == [
        "webp-frame-1@(320, 320)",
        "webp-frame-2@(320, 320)",
    ]
    assert controller._durations_ms == [90, 180]
    assert mock_ctk_image.call_count == 2


def test_load_images_uses_manifest_duration_when_animation_has_no_duration(mocker, tmp_path):
    states_dir = tmp_path / "states"
    states_dir.mkdir()
    (states_dir / "animation_manifest.json").write_text(
        '{"idle_listen": {"webp": {"duration_ms": 85}}}',
        encoding="utf-8",
    )
    (states_dir / "idle_listen.webp").write_bytes(b"fake animation")

    class FakeFrame:
        info = {}

        def convert(self, _mode):
            return self

    class FakeImage:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    mocker.patch("PIL.Image.open", return_value=FakeImage())
    mocker.patch("PIL.ImageSequence.Iterator", return_value=[FakeFrame(), FakeFrame()])
    mocker.patch(
        "customtkinter.CTkImage",
        side_effect=lambda image, size: f"manifest-frame@{size}",
    )
    mocker.patch("ui.animation_controller.ASSETS_DIR", states_dir)
    mocker.patch("ui.animation_controller.ANIMATION_MANIFEST", states_dir / "animation_manifest.json")

    controller = make_controller()

    controller._load_images(State.IDLE_LISTEN)

    assert controller._durations_ms == [85, 85]


def test_tick_uses_gif_frame_duration():
    controller = make_controller()
    controller._has_images = True
    controller._images = ["frame-1", "frame-2"]
    controller._durations_ms = [120, 340]

    controller._tick()
    controller._tick()

    controller.label.after.assert_any_call(120, controller._tick)
    controller.label.after.assert_any_call(340, controller._tick)


def test_tick_cycles_through_detected_images_without_fixed_frame_count():
    controller = make_controller()
    controller._has_images = True
    controller._images = ["frame-1", "frame-2", "frame-3", "frame-4"]

    for expected_frame in controller._images:
        controller._tick()
        controller.label.configure.assert_called_with(image=expected_frame, text="")

    controller._tick()

    controller.label.configure.assert_called_with(image="frame-1", text="")
    assert controller._frame_index == 1
    assert controller.label.after.call_count == 5

