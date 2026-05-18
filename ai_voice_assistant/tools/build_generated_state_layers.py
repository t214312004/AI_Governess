"""Build state animation layers from AI-generated background and character sources."""

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
STRIP_CELL_OVERLAP = 24
STRIP_BOUNDARY_SEARCH_RADIUS = 56
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
        "--state-strip-source",
        action="append",
        default=[],
        metavar="STATE=PATH",
        help=(
            "Use a 7-column x 1-row sprite strip for one state. "
            "May be repeated, for example --state-strip-source idle_listen=path.png."
        ),
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


def detect_grid_bounds(
    sprite_sheet: Image.Image,
    source_columns: int,
    source_rows: int = GRID_ROWS,
) -> tuple[list[int], list[int]]:
    x_bounds = refined_grid_bounds(sprite_sheet, "x", source_columns)
    y_bounds = refined_grid_bounds(sprite_sheet, "y", source_rows)
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
    source_rows: int = GRID_ROWS,
) -> tuple[int, int, int, int]:
    # Generated sheets often violate exact grid boundaries, especially vertically.
    expand_x = 0 if source_rows == 1 else 10
    expand_y = 12 if source_rows == 1 else 82
    image_width, image_height = image_size
    left = max(0, x_bounds[column] - expand_x)
    right = min(image_width, x_bounds[column + 1] + expand_x)
    top = max(0, y_bounds[row] - expand_y)
    bottom = min(image_height, y_bounds[row + 1] + expand_y)
    return left, top, right, bottom


def remove_chroma_key(
    cell: Image.Image,
    strip_cell_bounds: tuple[int, int] | None = None,
) -> Image.Image:
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
    if strip_cell_bounds is not None:
        keep_left, keep_right = strip_keep_bounds(alpha, strip_cell_bounds)
        alpha[:, :keep_left] = 0
        alpha[:, keep_right:] = 0

    # Clean disconnected neighboring-cell artifacts before softening the matte.
    # Blurring first can bridge tiny gaps and make the artifact look connected.
    arr[..., 3] = alpha
    cleaned = keep_largest_alpha_component(Image.fromarray(arr, "RGBA"))
    arr = np.asarray(cleaned).copy()
    alpha = arr[..., 3]
    alpha_img = Image.fromarray(alpha, "L").filter(ImageFilter.GaussianBlur(0.35))

    # Basic green despill near antialiased edges.
    arr[..., 1] = np.where(alpha < 255, np.minimum(arr[..., 1], np.maximum(arr[..., 0], arr[..., 2]) + 18), arr[..., 1])
    arr[..., 3] = np.asarray(alpha_img)
    return Image.fromarray(arr, "RGBA")


def strip_keep_bounds(alpha: np.ndarray, strip_cell_bounds: tuple[int, int]) -> tuple[int, int]:
    """Find asymmetric keep bounds for a wide-cropped 7x1 strip cell."""
    original_left, original_right = strip_cell_bounds
    height, width = alpha.shape
    projection = (alpha > 12).sum(axis=0).astype(np.float32)
    kernel = np.ones(5, dtype=np.float32) / 5
    smoothed = np.convolve(projection, kernel, mode="same")
    outside_threshold = max(20.0, height * 0.1)

    keep_left = 0
    if original_left > 0 and projection[:original_left].sum() > outside_threshold:
        keep_left = strip_boundary_cut(smoothed, original_left, side="left")

    keep_right = width
    if original_right < width and projection[original_right:].sum() > outside_threshold:
        keep_right = strip_boundary_cut(smoothed, original_right, side="right")

    if keep_right <= keep_left:
        return 0, width
    return keep_left, keep_right


def strip_boundary_cut(projection: np.ndarray, boundary: int, side: str) -> int:
    width = projection.shape[0]
    start = max(3, boundary - STRIP_BOUNDARY_SEARCH_RADIUS)
    end = min(width - 3, boundary + STRIP_BOUNDARY_SEARCH_RADIUS)
    if end <= start:
        return 0 if side == "left" else width

    window = projection[start:end]
    low_threshold = 14.0
    low_indexes = np.nonzero(window <= low_threshold)[0] + start
    groups: list[tuple[int, int]] = []
    if low_indexes.size:
        group_start = previous = int(low_indexes[0])
        for raw_index in low_indexes[1:]:
            index = int(raw_index)
            if index <= previous + 1:
                previous = index
                continue
            groups.append((group_start, previous))
            group_start = previous = index
        groups.append((group_start, previous))

    if side == "left":
        groups = [(left, right) for left, right in groups if left > 4]
        if groups:
            left, right = min(groups, key=lambda item: abs(((item[0] + item[1]) / 2) - boundary))
            return min(width, right + 1)
    else:
        groups = [(left, right) for left, right in groups if right < width - 5]
        if groups:
            left, _right = min(groups, key=lambda item: abs(((item[0] + item[1]) / 2) - boundary))
            return max(0, left)

    best_index = int(np.argmin(window)) + start
    best_score = float(projection[best_index])
    high_score = float(np.percentile(window, 90))
    if best_score <= max(28.0, high_score * 0.35):
        return min(width, best_index + 1) if side == "left" else max(0, best_index)

    return 0 if side == "left" else width


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
    suffix = "preview_contact" if output_dir.name.endswith("_preview") else "contact"
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
        sheet.save(DIAGNOSTICS_DIR / f"{state}_generated_{version}_{suffix}.jpg", quality=92)

    all_thumb_w, all_thumb_h = 186, 168
    all_label_h = 22
    left_label_w = 92
    rows = len(STATE_ROWS)
    sheet = Image.new(
        "RGB",
        (left_label_w + GRID_COLUMNS * all_thumb_w, rows * (all_thumb_h + all_label_h)),
        "white",
    )
    from PIL import ImageDraw

    draw = ImageDraw.Draw(sheet)
    for row, state in enumerate(STATE_ROWS):
        y = row * (all_thumb_h + all_label_h)
        draw.text((6, y + 6), state, fill=(0, 0, 0))
        for column, frame in enumerate(frames_by_state[state], start=1):
            composed = background.copy()
            composed.alpha_composite(frame)
            thumb = composed.convert("RGB").resize((all_thumb_w, all_thumb_h), Image.Resampling.LANCZOS)
            x = left_label_w + (column - 1) * all_thumb_w
            sheet.paste(thumb, (x, y))
            draw.rectangle((x, y, x + all_thumb_w - 1, y + all_thumb_h - 1), outline=(180, 180, 180))
            draw.text((x + 6, y + all_thumb_h + 4), str(column), fill=(0, 0, 0))
    sheet.save(DIAGNOSTICS_DIR / f"all_states_generated_{version}_{suffix}.jpg", quality=92)


def relative_to_project(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def parse_state_strip_sources(entries: list[str], version: str) -> dict[str, Path]:
    explicit_sources: dict[str, Path] = {}
    for entry in entries:
        if "=" not in entry:
            raise SystemExit("--state-strip-source must use STATE=PATH.")
        state, raw_path = entry.split("=", 1)
        state = state.strip()
        if state not in STATE_ROWS:
            valid = ", ".join(STATE_ROWS)
            raise SystemExit(f"Unknown state '{state}' in --state-strip-source. Expected one of: {valid}.")
        explicit_sources[state] = Path(raw_path).resolve()

    if explicit_sources:
        missing_states = [state for state in STATE_ROWS if state not in explicit_sources]
        if missing_states:
            raise SystemExit(f"Missing --state-strip-source for: {', '.join(missing_states)}")
        return explicit_sources

    default_sources = {
        state: (SOURCES_DIR / f"character_{state}_strip_{version}_source.png").resolve() for state in STATE_ROWS
    }
    return default_sources if all(path.exists() for path in default_sources.values()) else {}


def crop_sprites_from_source(
    source_image: Image.Image,
    state_rows: dict[str, int],
    source_columns: int,
    source_rows: int,
) -> dict[str, list[Image.Image]]:
    x_bounds, y_bounds = detect_grid_bounds(source_image, source_columns, source_rows)
    raw_sprites: dict[str, list[Image.Image]] = {}

    for state, row in state_rows.items():
        raw_sprites[state] = []
        for column in range(GRID_COLUMNS):
            cell = source_image.crop(
                cell_bounds(x_bounds, y_bounds, column, row, source_image.size, source_columns, source_rows)
            )
            raw_sprites[state].append(remove_chroma_key(cell))

    return raw_sprites


def crop_sprites_from_state_strips(strip_sources: dict[str, Path]) -> tuple[dict[str, list[Image.Image]], dict[str, dict]]:
    raw_sprites: dict[str, list[Image.Image]] = {}
    strip_metadata: dict[str, dict] = {}

    for state, source_path in strip_sources.items():
        if not source_path.exists():
            raise SystemExit(f"Missing generated strip source image: {source_path}")

        strip = Image.open(source_path).convert("RGB")
        x_bounds, y_bounds = detect_grid_bounds(strip, GRID_COLUMNS, 1)
        raw_sprites[state] = []
        for column in range(GRID_COLUMNS):
            cell_width = x_bounds[column + 1] - x_bounds[column]
            source_center_x = (x_bounds[column] + x_bounds[column + 1]) / 2
            left = max(0, x_bounds[column] - STRIP_CELL_OVERLAP)
            right = min(strip.width, x_bounds[column + 1] + STRIP_CELL_OVERLAP)
            top = max(0, y_bounds[0] - 12)
            bottom = min(strip.height, y_bounds[1] + 12)
            cell = strip.crop((left, top, right, bottom))
            raw_sprites[state].append(
                remove_chroma_key(
                    cell,
                    strip_cell_bounds=(x_bounds[column] - left, x_bounds[column + 1] - left),
                )
            )

        strip_metadata[state] = {
            "source": relative_to_project(source_path),
            "grid": {"columns": GRID_COLUMNS, "rows": 1},
            "grid_bounds": {"x": x_bounds, "y": y_bounds},
            "crop": {
                "overlap": STRIP_CELL_OVERLAP,
                "boundary_search_radius": STRIP_BOUNDARY_SEARCH_RADIUS,
                "strategy": "wide_crop_asymmetric_alpha_valley",
            },
        }

    return raw_sprites, strip_metadata


def main() -> None:
    args = parse_args()
    version = args.version.lower().lstrip("_")
    background_source = (args.background_source or SOURCES_DIR / f"background_{version}_source.png").resolve()
    sprite_source = (args.sprite_source or SOURCES_DIR / f"character_sprite_sheet_{version}_source.png").resolve()
    state_strip_sources = parse_state_strip_sources(args.state_strip_source, version)
    output_dir = (args.output_dir or (STATES_DIR / f"layers_{version}_preview" if args.preview else LAYERS_DIR)).resolve()

    if not background_source.exists() or (not state_strip_sources and not sprite_source.exists()):
        raise SystemExit("Missing generated source images in assets/states/generated_sources.")

    output_dir.mkdir(exist_ok=True)
    DIAGNOSTICS_DIR.mkdir(exist_ok=True)
    if output_dir == LAYERS_DIR and not BACKUP_DIR.exists() and any(LAYERS_DIR.glob("*.png")):
        shutil.copytree(LAYERS_DIR, BACKUP_DIR)

    background = cover_resize(Image.open(background_source).convert("RGB"), CANVAS_SIZE)
    background.save(output_dir / "background.png")

    if args.source_columns < GRID_COLUMNS:
        raise SystemExit("--source-columns must be at least 7.")

    strip_metadata: dict[str, dict] = {}
    if state_strip_sources:
        raw_sprites, strip_metadata = crop_sprites_from_state_strips(state_strip_sources)
        source_grid = {"columns": GRID_COLUMNS, "rows": 1, "mode": "state_strips"}
    else:
        sprite_sheet = Image.open(sprite_source).convert("RGB")
        raw_sprites = crop_sprites_from_source(sprite_sheet, STATE_ROWS, args.source_columns, GRID_ROWS)
        source_grid = {"columns": args.source_columns, "rows": GRID_ROWS, "mode": "sprite_sheet"}

    trimmed_sizes: list[tuple[int, int]] = []
    for sprites in raw_sprites.values():
        for sprite in sprites:
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
                "background_source": relative_to_project(background_source),
                "sprite_source": None if state_strip_sources else relative_to_project(sprite_source),
                "state_strip_sources": strip_metadata or None,
                "output_dir": relative_to_project(output_dir),
                "canvas_size": CANVAS_SIZE,
                "grid": {"columns": GRID_COLUMNS, "rows": GRID_ROWS},
                "source_grid": source_grid,
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
