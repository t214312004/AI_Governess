"""Private-workspace entrypoint for the tracked camera implementation."""

from pathlib import Path
import sys

APP_DIR = Path(__file__).resolve().parents[3]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from tools.camera_tool import main


if __name__ == "__main__":
    raise SystemExit(main())
