"""Build state animation layers from an AI-generated background and sprite sheet."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATES_DIR = PROJECT_ROOT / "assets" / "states"
SOURCES_DIR = STATES_DIR / "generated_sources"
LAYERS_DIR = STATES_DIR / "layers"
BACKUP_DIR = STATES_DIR / "layers_v1_cutout_backup"
DIAGNOSTICS_DIR = STATES_DIR / "_diagnostics"

CANVAS_SIZE = (1118, 1012)
GRID_COLUMNS = 7
GRID_ROWS = 5
DEFAULT_VERSION = "v2"
STATE_ROWS = {
    "idle_listen": 0,
    "collecting": 1,
    "sending": 2,
    "speaking": 3,
    "hot_listen": 4,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        default=DEFAULT_VERSION,
        help="Generated source version suffix, for example v2 or v5.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Write to layers_<version>_preview instead of the runtime layers directory.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Override the layer output directory.",
    )
    parser.add_argument(
        "--background-source",
        type=Path,
        help="Override the generated background source image.",
    )
    parser.add_argument(
        "--sprite-source",
        type=Path,
        help="Override the generated sprite sheet source image.",
    )
    parser.add_argument(
        "--source-columns",
        type=int,
        default=GRID_COLUMNS,
        help="Number of columns in the generated source sheet. Output still uses 7 frames per state.",
    )
    return parser.parse_args()


def cover_resize(image: Image.Image, target_size: tuple[int, int]) -> Image.Image:
    target_w, target_h = target_size
    scale = max(target_w / image.width, target_h / image.height)
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.Resampling.LANCZOS,
    )
    left = (resized.width - target_w) // 2
    top = (resized.height - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h)).convert("RGBA")


def light_line_centers(image: Image.Image, axis: str, threshold: float = 0.45) -> list[int]:
    arr = np.asarray(image.convert("RGB"))
    light = (arr[..., 0] > 200) & (arr[..., 1] > 200) & (arr[..., 2] > 200)
    ratios = light.mean(axis=0 if axis == "x" else 1)
    indexes = [index for index, value in enumerate(ratios) if value > threshold]
    if not indexes:
        return []

    ranges: list[tuple[int, int]] = []
    start = previous = indexes[0]
    for index in indexes[1:]:
        if index <= previous + 1:
            previous = index
            continue
        ranges.append((start, previous))
        start = previous = index
    ranges.append((start, previous))
    return [round((start + end) / 2) for start, end in ranges]


def best_grid_bounds(candidates: list[int], expected_cells: int, limit: int) -> list[int]:
    all_candidates = sorted(set([0, limit - 1, limit] + [value for value in candidates if 0 <= value <= limit]))
    all_candidates = [0 if value <= 2 else limit if value >= limit - 3 else value for value in all_candidates]
    all_candidates = sorted(set(all_candidates))

    needed = expected_cells + 1
    if len(all_candidates) < needed:
        return [round(index * limit / expected_cells) for index in range(needed)]

    best_window = None
    best_score = None
    for start in range(0, len(all_candidates) - needed + 1):
        window = all_candidates[start : start + needed]
        widths = np.diff(window)
        if np.any(widths <= 0):
            continue
        mean_width = float(widths.mean())
        score = float(widths.std() / max(mean_width, 1.0))
        if best_score is None or score < best_score:
            best_score = score
            best_window = window

    return list(best_window) if best_window is not None else [round(index * limit / expected_cells) for index in range(needed)]


def detect_grid_bounds(sprite_sheet: Image.Image, source_columns: int) -> tuple[list[int], list[int]]:
    x_bounds = refined_grid_bounds(sprite_sheet, "x", source_columns)
    y_bounds = refined_grid_bounds(sprite_sheet, "y", GRID_ROWS)
    return x_bounds, y_bounds


def refined_grid_bounds(image: Image.Image, axis: str, expected_cells: int) -> list[int]:
    """Find grid boundaries near equal divisions, falling back when no line is visible."""
    limit = image.width if axis == "x" else image.height
    estimated = [round(index * limit / expected_cells) for index in range(expected_cells + 1)]
    bounds = [0]
    window_radius = max(8, round(limit * 0.02))
    arr = np.asarray(image.convert("RGB"))
    light = (arr[..., 0] > 200) & (arr[..., 1] > 200) & (arr[..., 2] > 200)

    for index in range(1, expected_cells):
        estimate = estimated[index]
        start = max(1, estimate - window_radius)
        end = min(limit - 1, estimate + window_radius)
        if axis == "x":
            scores = light[:, start:end].mean(axis=0)
        else:
            scores = light[start:end, :].mean(axis=1)
        if scores.size == 0:
            bounds.append(estimate)
            continue
        best_offset = int(np.argmax(scores))
        best_score = float(scores[best_offset])
        bounds.append(start + best_offset if best_score >= 0.35 else estimate)

    bounds.append(limit)
    if any(bounds[index] <= bounds[index - 1] for index in range(1, len(bounds))):
        return estimated
    return bounds


def cell_bounds(
    x_bounds: list[int],
    y_bounds: list[int],
    column: int,
    row: int,
    image_size: tuple[int, int],
    source_columns: int,
) -> tuple[int, int, int, int]:
    # Generated sheets often violate exact grid boundaries, especially vertically.
    expand_x = 10
    expand_y = 82
    image_width, image_height = image_size
    left = max(0, x_bounds[column] - expand_x)
    right = min(image_width, x_bounds[column + 1] + expand_x)
    top = max(0, y_bounds[row] - expand_y)
    bottom = min(image_height, y_bounds[row + 1] + expand_y)
    return left, top, right, bottom


def remove_chroma_key(cell: Image.Image) -> Image.Image:
    rgba = cell.convert("RGBA")
    arr = np.asarray(rgba).copy()
    rgb = arr[..., :3].astype(np.int32)

    green = rgb[..., 1]
    red = rgb[..., 0]
    blue = rgb[..., 2]
    green_dominance = green - np.maximum(red, blue)

    alpha = np.full(green.shape, 255, dtype=np.uint8)
    alpha[(green > 145) & (green_dominance > 60)] = 0
    edge = (green > 95) & (green_dominance > 35)
    alpha[edge] = np.minimum(alpha[edge], 90).astype(np.uint8)

    # Remove the generated grid lines at cell edges.
    alpha[:3, :] = 0
    alpha[-3:, :] = 0
    alpha[:, :3] = 0
    alpha[:, -3:] = 0

    alpha_img = Image.fromarray(alpha, "L")
    alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(0.35))

    # Basic green despill near antialiased edges.
    arr[..., 1] = np.where(alpha < 255, np.minimum(arr[..., 1], np.maximum(arr[..., 0], arr[..., 2]) + 18), arr[..., 1])
    arr[..., 3] = np.asarray(alpha_img)
    return keep_largest_alpha_component(Image.fromarray(arr, "RGBA"))


def keep_largest_alpha_component(image: Image.Image, threshold: int = 12) -> Image.Image:
    """Remove disconnected artifacts from neighboring generated sprite cells."""
    arr = np.asarray(image.convert("RGBA")).copy()
    mask = arr[..., 3] > threshold
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    largest: list[tuple[int, int]] = []

    for y in range(height):
        for x in range(width):
            if visited[y, x] or not mask[y, x]:
                continue
            stack = [(x, y)]
            visited[y, x] = True
            component: list[tuple[int, int]] = []
            while stack:
                cx, cy = stack.pop()
                component.append((cx, cy))
                for ny in range(max(0, cy - 1), min(height, cy + 2)):
                    for nx in range(max(0, cx - 1), min(width, cx + 2)):
                        if visited[ny, nx] or not mask[ny, nx]:
                            continue
                        visited[ny, nx] = True
                        stack.append((nx, ny))
            if len(component) > len(largest):
                largest = component

    if not largest:
        return image

    keep = np.zeros_like(mask, dtype=bool)
    ys = [point[1] for point in largest]
    xs = [point[0] for point in largest]
    keep[ys, xs] = True
    arr[..., 3] = np.where(keep, arr[..., 3], 0).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def alpha_bbox(image: Image.Image, threshold: int = 12) -> tuple[int, int, int, int] | None:
    bbox = image.getchannel("A").point(lambda value: 255 if value > 12 else 0).getbbox()
    return bbox


def trim_transparent(image: Image.Image) -> Image.Image:
    bbox = alpha_bbox(image)
    if bbox is None:
        return image
    return image.crop(bbox)


def alpha_center_x(image: Image.Image) -> float:
    alpha = np.asarray(image.getchannel("A"))
    ys, xs = np.nonzero(alpha > 12)
    if xs.size == 0:
        return image.width / 2
    return float(np.median(xs))


def build_canvas(sprite: Image.Image, scale: float, top: int, bottom: int, center_x: int) -> Image.Image:
    trimmed = trim_transparent(sprite)
    resized = trimmed.resize(
        (round(trimmed.width * scale), round(trimmed.height * scale)),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    bbox = alpha_bbox(resized)
    if bbox is None:
        return canvas
    sprite_center_x = alpha_center_x(resized)
    head_top = bbox[1]
    sprite_bottom = bbox[3]
    x = round(center_x - sprite_center_x)
    y_from_top = top - head_top
    y_from_bottom = bottom - sprite_bottom
    y = round((y_from_top + y_from_bottom) / 2)
    canvas.alpha_composite(resized, (x, y))
    return canvas


def make_contact_sheet(
    background: Image.Image,
    frames_by_state: dict[str, list[Image.Image]],
    version: str,
    output_dir: Path,
) -> None:
    thumb_w, thumb_h = 224, 203
    label_h = 26
    columns = 4
    for state, frames in frames_by_state.items():
        rows = (len(frames) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * thumb_w, rows * (thumb_h + label_h)), "white")
        from PIL import ImageDraw

        draw = ImageDraw.Draw(sheet)
        for index, frame in enumerate(frames, start=1):
            composed = background.copy()
            composed.alpha_composite(frame)
            thumb = composed.convert("RGB").resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
            x = ((index - 1) % columns) * thumb_w
            y = ((index - 1) // columns) * (thumb_h + label_h)
            sheet.paste(thumb, (x, y))
            draw.rectangle((x, y, x + thumb_w - 1, y + thumb_h - 1), outline=(180, 180, 180))
            draw.text((x + 6, y + thumb_h + 6), f"{state}_{index}.png", fill=(0, 0, 0))
        suffix = "preview_contact" if output_dir.name.endswith("_preview") else "contact"
        sheet.save(DIAGNOSTICS_DIR / f"{state}_generated_{version}_{suffix}.jpg", quality=92)


def main() -> None:
    args = parse_args()
    version = args.version.lower().lstrip("_")
    background_source = (args.background_source or SOURCES_DIR / f"background_{version}_source.png").resolve()
    sprite_source = (args.sprite_source or SOURCES_DIR / f"character_sprite_sheet_{version}_source.png").resolve()
    output_dir = (args.output_dir or (STATES_DIR / f"layers_{version}_preview" if args.preview else LAYERS_DIR)).resolve()

    if not background_source.exists() or not sprite_source.exists():
        raise SystemExit("Missing generated source images in assets/states/generated_sources.")

    output_dir.mkdir(exist_ok=True)
    DIAGNOSTICS_DIR.mkdir(exist_ok=True)
    if output_dir == LAYERS_DIR and not BACKUP_DIR.exists() and any(LAYERS_DIR.glob("*.png")):
        shutil.copytree(LAYERS_DIR, BACKUP_DIR)

    background = cover_resize(Image.open(background_source).convert("RGB"), CANVAS_SIZE)
    background.save(output_dir / "background.png")

    sprite_sheet = Image.open(sprite_source).convert("RGB")
    if args.source_columns < GRID_COLUMNS:
        raise SystemExit("--source-columns must be at least 7.")

    x_bounds, y_bounds = detect_grid_bounds(sprite_sheet, args.source_columns)
    raw_sprites: dict[str, list[Image.Image]] = {}
    trimmed_sizes: list[tuple[int, int]] = []

    for state, row in STATE_ROWS.items():
        raw_sprites[state] = []
        for column in range(GRID_COLUMNS):
            cell = sprite_sheet.crop(cell_bounds(x_bounds, y_bounds, column, row, sprite_sheet.size, args.source_columns))
            sprite = remove_chroma_key(cell)
            raw_sprites[state].append(sprite)
            trimmed = trim_transparent(sprite)
            trimmed_sizes.append(trimmed.size)

    max_width = max(width for width, _height in trimmed_sizes)
    max_height = max(height for _width, height in trimmed_sizes)
    scale = min(930 / max_width, 900 / max_height)

    for existing in output_dir.glob("*.png"):
        if existing.name != "background.png":
            existing.unlink()

    frames_by_state: dict[str, list[Image.Image]] = {}
    for state, sprites in raw_sprites.items():
        frames_by_state[state] = []
        scaled_heights = [round(trim_transparent(sprite).height * scale) for sprite in sprites]
        target_top = 62
        target_bottom = target_top + round(float(np.median(scaled_heights)))
        for index, sprite in enumerate(sprites, start=1):
            frame = build_canvas(sprite, scale=scale, top=target_top, bottom=target_bottom, center_x=559)
            frame.save(output_dir / f"{state}_{index}.png")
            frames_by_state[state].append(frame)

    make_contact_sheet(background, frames_by_state, version, output_dir)
    (output_dir / "source_map.json").write_text(
        json.dumps(
            {
                "version": f"generated_{version}",
                "background_source": str(background_source.relative_to(PROJECT_ROOT)),
                "sprite_source": str(sprite_source.relative_to(PROJECT_ROOT)),
                "output_dir": str(output_dir.relative_to(PROJECT_ROOT)),
                "canvas_size": CANVAS_SIZE,
                "grid": {"columns": GRID_COLUMNS, "rows": GRID_ROWS},
                "source_grid": {"columns": args.source_columns, "rows": GRID_ROWS},
                "grid_bounds": {"x": x_bounds, "y": y_bounds},
                "states": {state: {"row": row, "frames": GRID_COLUMNS} for state, row in STATE_ROWS.items()},
                "scale": scale,
                "top": 62,
                "center_x": 559,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote generated {version} layers to {output_dir}")


if __name__ == "__main__":
    main()
