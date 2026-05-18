"""Legacy helper for old top-level composed PNG state frames.

This helper expects source frames named assets/states/<state>_<n>.png and writes
aligned foreground layers plus a fixed background to assets/states/layers/.
Current generated layered assets should use build_generated_state_layers.py.

The runtime does not depend on OpenCV; this script only needs it when
regenerating layers from legacy PNG frames.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
STATES_DIR = PROJECT_ROOT / "assets" / "states"
LAYERS_DIR = STATES_DIR / "layers"
DIAGNOSTICS_DIR = STATES_DIR / "_diagnostics"
TMP_OPENCV = REPO_ROOT / ".codex_tmp" / "opencv"

if TMP_OPENCV.exists():
    sys.path.insert(0, str(TMP_OPENCV))

try:
    import cv2
except ImportError as exc:  # pragma: no cover - only used when regenerating assets
    raise SystemExit(
        "OpenCV is required to regenerate state layers. Install it into a temporary "
        "target first, for example: python -m pip install --target .codex_tmp/opencv "
        "opencv-python-headless"
    ) from exc


@dataclass(frozen=True)
class StateMaskSpec:
    polygon: tuple[tuple[int, int], ...]
    foreground_seeds: tuple[tuple[int, int, int, int], ...]
    probable_background: tuple[tuple[int, int, int, int], ...] = ()


DEFAULT_SEEDS = (
    (455, 110, 650, 325),
    (430, 345, 690, 690),
    (425, 735, 690, 940),
)

STATE_SPECS: dict[str, StateMaskSpec] = {
    "idle_listen": StateMaskSpec(
        polygon=((500, 40), (665, 55), (770, 170), (820, 420), (875, 930), (720, 1005), (390, 1005), (255, 930), (290, 450), (350, 180)),
        foreground_seeds=DEFAULT_SEEDS + ((330, 575, 440, 820), (650, 575, 780, 820)),
        probable_background=((230, 40, 430, 260), (675, 50, 900, 310), (230, 250, 335, 700), (790, 300, 910, 720)),
    ),
    "hot_listen": StateMaskSpec(
        polygon=((500, 40), (670, 55), (785, 185), (835, 470), (875, 950), (720, 1010), (385, 1010), (245, 950), (285, 470), (350, 185)),
        foreground_seeds=DEFAULT_SEEDS + ((410, 510, 710, 820),),
        probable_background=((230, 40, 430, 260), (685, 50, 900, 320), (225, 265, 335, 720), (800, 310, 915, 720)),
    ),
    "collecting": StateMaskSpec(
        polygon=((505, 35), (675, 55), (790, 180), (850, 550), (855, 990), (690, 1010), (345, 1010), (215, 950), (240, 435), (355, 145)),
        foreground_seeds=DEFAULT_SEEDS + ((250, 330, 435, 770), (620, 520, 805, 880)),
        probable_background=((220, 40, 415, 250), (690, 45, 915, 320), (795, 300, 930, 740)),
    ),
    "sending": StateMaskSpec(
        polygon=((500, 40), (665, 55), (775, 175), (835, 500), (875, 965), (720, 1010), (365, 1010), (245, 955), (275, 500), (350, 175)),
        foreground_seeds=DEFAULT_SEEDS + ((300, 515, 500, 830), (560, 520, 805, 850)),
        probable_background=((230, 40, 430, 260), (690, 50, 900, 315), (820, 300, 930, 760)),
    ),
    "speaking": StateMaskSpec(
        polygon=((505, 40), (675, 55), (790, 175), (990, 455), (900, 665), (845, 1005), (345, 1005), (235, 665), (105, 455), (350, 175)),
        foreground_seeds=DEFAULT_SEEDS + ((140, 385, 360, 650), (760, 385, 990, 650), (345, 515, 470, 850), (650, 515, 785, 850)),
        probable_background=((220, 40, 430, 245), (700, 45, 920, 280), (80, 660, 250, 940), (880, 660, 1040, 940)),
    ),
}


def state_prefix(path: Path) -> str:
    return "_".join(path.stem.split("_")[:-1])


def numbered_pngs(directory: Path, prefix: str) -> list[Path]:
    def frame_number(path: Path) -> int:
        return int(path.stem.rsplit("_", 1)[1])

    return sorted(directory.glob(f"{prefix}_*.png"), key=frame_number)


def alpha_from_grabcut(path: Path, spec: StateMaskSpec) -> Image.Image:
    rgb = np.array(Image.open(path).convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    height, width = bgr.shape[:2]

    mask = np.full((height, width), cv2.GC_BGD, dtype=np.uint8)
    polygon = np.array(spec.polygon, dtype=np.int32)
    cv2.fillPoly(mask, [polygon], cv2.GC_PR_FGD)

    for x1, y1, x2, y2 in spec.probable_background:
        mask[y1:y2, x1:x2] = cv2.GC_PR_BGD

    for x1, y1, x2, y2 in spec.foreground_seeds:
        mask[y1:y2, x1:x2] = cv2.GC_FGD

    bgd_model = np.zeros((1, 65), dtype=np.float64)
    fgd_model = np.zeros((1, 65), dtype=np.float64)
    cv2.grabCut(bgr, mask, None, bgd_model, fgd_model, 8, cv2.GC_INIT_WITH_MASK)

    binary = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype("uint8")
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((5, 5), dtype=np.uint8), iterations=2)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((3, 3), dtype=np.uint8), iterations=1)
    binary = keep_relevant_components(binary)
    return Image.fromarray(binary).filter(ImageFilter.GaussianBlur(0.7))


def keep_relevant_components(mask: np.ndarray) -> np.ndarray:
    component_count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    if component_count <= 1:
        return mask

    areas = stats[:, cv2.CC_STAT_AREA]
    largest = 1 + int(np.argmax(areas[1:]))
    kept = np.zeros_like(mask)
    for component in range(1, component_count):
        x, y, width, height, area = stats[component]
        center_x, center_y = centroids[component]
        if component == largest or (area > 1500 and 80 < center_x < 1040 and 40 < center_y < 1010):
            kept[labels == component] = 255
    return kept


def create_cutout(path: Path, alpha: Image.Image) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    image.putalpha(alpha)
    return image


def alpha_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    bbox = image.getchannel("A").point(lambda px: 255 if px > 16 else 0).getbbox()
    if bbox is None:
        return (0, 0, image.width, image.height)
    return bbox


def anchor_for(image: Image.Image) -> tuple[float, float]:
    alpha = np.array(image.getchannel("A"))
    ys, xs = np.nonzero(alpha > 32)
    if len(xs) == 0:
        return (image.width / 2, 0)

    top = float(ys.min())
    head_limit = min(image.height, int(top) + 340)
    head_pixels = (alpha > 32) & (np.indices(alpha.shape)[0] <= head_limit)
    head_ys, head_xs = np.nonzero(head_pixels)
    if len(head_xs) == 0:
        return (float(np.median(xs)), top)
    return (float(np.median(head_xs)), top)


def shift_rgba(image: Image.Image, dx: int, dy: int) -> Image.Image:
    shifted = Image.new("RGBA", image.size, (0, 0, 0, 0))
    src_left = max(0, -dx)
    src_top = max(0, -dy)
    src_right = min(image.width, image.width - dx) if dx >= 0 else image.width
    src_bottom = min(image.height, image.height - dy) if dy >= 0 else image.height
    if src_right <= src_left or src_bottom <= src_top:
        return shifted
    crop = image.crop((src_left, src_top, src_right, src_bottom))
    shifted.alpha_composite(crop, (max(0, dx), max(0, dy)))
    return shifted


def tween_rgba(first: Image.Image, second: Image.Image, amount: float = 0.5) -> Image.Image:
    a = np.asarray(first).astype(np.float32) / 255.0
    b = np.asarray(second).astype(np.float32) / 255.0
    alpha_a = a[..., 3:4]
    alpha_b = b[..., 3:4]
    premul_a = a[..., :3] * alpha_a
    premul_b = b[..., :3] * alpha_b
    alpha = alpha_a * (1.0 - amount) + alpha_b * amount
    premul = premul_a * (1.0 - amount) + premul_b * amount
    rgb = np.divide(premul, np.maximum(alpha, 1e-6))
    out = np.concatenate([rgb, alpha], axis=2)
    return Image.fromarray(np.clip(out * 255.0, 0, 255).astype(np.uint8), "RGBA")


def frame_difference(first: Image.Image, second: Image.Image) -> float:
    a = np.asarray(first).astype(np.int16)
    b = np.asarray(second).astype(np.int16)
    alpha_union = (a[..., 3] > 12) | (b[..., 3] > 12)
    if not np.any(alpha_union):
        return 0.0
    diff = np.abs(a[..., :4] - b[..., :4])
    return float(diff[alpha_union].mean())


def build_background(base_path: Path, alpha: Image.Image) -> Image.Image:
    rgb = np.array(Image.open(base_path).convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    mask = np.array(alpha.point(lambda px: 255 if px > 8 else 0), dtype=np.uint8)
    mask = cv2.dilate(mask, np.ones((11, 11), dtype=np.uint8), iterations=3)
    inpainted = cv2.inpaint(bgr, mask, 5, cv2.INPAINT_TELEA)
    return Image.fromarray(cv2.cvtColor(inpainted, cv2.COLOR_BGR2RGB)).convert("RGBA")


def make_contact_sheet(state: str, frames: list[Image.Image], background: Image.Image) -> None:
    thumb_w, thumb_h = 224, 203
    label_h = 26
    columns = 4
    rows = math.ceil(len(frames) / columns)
    sheet = Image.new("RGB", (columns * thumb_w, rows * (thumb_h + label_h)), "white")
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
    sheet.save(DIAGNOSTICS_DIR / f"{state}_layered_contact.jpg", quality=92)


def main() -> None:
    LAYERS_DIR.mkdir(exist_ok=True)
    DIAGNOSTICS_DIR.mkdir(exist_ok=True)

    states: dict[str, list[Path]] = {}
    for path in sorted(STATES_DIR.glob("*.png")):
        states.setdefault(state_prefix(path), []).append(path)

    if not states:
        raise SystemExit(
            "No legacy top-level state PNGs found in assets/states. "
            "Use build_generated_state_layers.py for current generated layered assets."
        )

    cutouts_by_source: dict[Path, Image.Image] = {}
    cutouts_by_hash: dict[str, Image.Image] = {}
    anchors: list[tuple[float, float]] = []
    source_info = {}

    for state, paths in states.items():
        spec = STATE_SPECS[state]
        for path in numbered_pngs(STATES_DIR, state):
            digest = hashlib.md5(path.read_bytes()).hexdigest()
            if digest in cutouts_by_hash:
                cutout = cutouts_by_hash[digest].copy()
            else:
                alpha = alpha_from_grabcut(path, spec)
                cutout = create_cutout(path, alpha)
                cutouts_by_hash[digest] = cutout.copy()
            cutouts_by_source[path] = cutout
            anchors.append(anchor_for(cutout))
            source_info[path.name] = {
                "md5": digest,
                "bbox": alpha_bbox(cutout),
                "anchor": anchor_for(cutout),
            }

    target_x = round(float(np.median([anchor[0] for anchor in anchors])))
    target_y = round(float(np.median([anchor[1] for anchor in anchors])))

    base_path = STATES_DIR / "idle_listen_1.png"
    background = build_background(base_path, cutouts_by_source[base_path].getchannel("A"))
    background.save(LAYERS_DIR / "background.png")

    output_manifest: dict[str, list[dict[str, str | int | float]]] = {}
    for state in sorted(states):
        output_frames: list[Image.Image] = []
        output_manifest[state] = []
        previous_frame: Image.Image | None = None
        previous_source = ""

        for path in numbered_pngs(STATES_DIR, state):
            cutout = cutouts_by_source[path]
            anchor_x, anchor_y = anchor_for(cutout)
            aligned = shift_rgba(cutout, target_x - round(anchor_x), target_y - round(anchor_y))

            output_frames.append(aligned)
            diff_score = frame_difference(previous_frame, aligned) if previous_frame is not None else 0.0
            output_manifest[state].append(
                {
                    "source": path.name,
                    "kind": "source",
                    "difference_from_previous": round(diff_score, 2),
                }
            )
            previous_frame = aligned
            previous_source = path.name

        for existing in LAYERS_DIR.glob(f"{state}_*.png"):
            existing.unlink()
        for index, frame in enumerate(output_frames, start=1):
            frame.save(LAYERS_DIR / f"{state}_{index}.png")
        make_contact_sheet(state, output_frames, background)

    (LAYERS_DIR / "source_map.json").write_text(
        json.dumps(
            {
                "target_anchor": {"x": target_x, "y": target_y},
                "sources": source_info,
                "outputs": output_manifest,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Wrote layered state assets to {LAYERS_DIR}")


if __name__ == "__main__":
    main()
