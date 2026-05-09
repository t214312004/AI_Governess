from __future__ import annotations

import shutil
from pathlib import Path

from utils.logger import get_logger

logger = get_logger(__name__)

APP_DIR = Path(__file__).resolve().parent
AGENT_WORKSPACE_DIR = APP_DIR / "agent_workspace"
AGENT_WORKSPACE_TEMPLATE_DIR = APP_DIR / "agent_workspace_template"
PRIVATE_DIRS = (
    AGENT_WORKSPACE_DIR,
    APP_DIR / "voice_profiles",
    APP_DIR / "whisper_audio_archive",
)


def _copy_template_file(source: Path, destination_root: Path) -> bool:
    relative_path = source.relative_to(AGENT_WORKSPACE_TEMPLATE_DIR)
    destination = destination_root / relative_path
    if destination.exists():
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def ensure_private_state() -> None:
    for directory in PRIVATE_DIRS:
        directory.mkdir(parents=True, exist_ok=True)

    if not AGENT_WORKSPACE_TEMPLATE_DIR.exists():
        return

    copied = 0
    for source in AGENT_WORKSPACE_TEMPLATE_DIR.rglob("*"):
        if source.is_file() and _copy_template_file(source, AGENT_WORKSPACE_DIR):
            copied += 1

    if copied:
        logger.info(
            "Initialized private agent workspace from template. "
            f"Created {copied} file(s)."
        )
