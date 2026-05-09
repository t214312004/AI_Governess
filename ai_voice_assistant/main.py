import argparse
import sys

from utils.logger import configure_logging, get_logger

configure_logging()

from core.assistant import VoiceAssistant
from private_state import ensure_private_state
from ui.main_window import VoiceAssistantUI

logger = get_logger(__name__)

def _hide_console_window():
    if sys.platform != "win32":
        return False

    try:
        import ctypes

        console_window = ctypes.windll.kernel32.GetConsoleWindow()
        if not console_window:
            return False
        ctypes.windll.user32.ShowWindow(console_window, 0)
        return True
    except Exception:
        logger.debug("Failed to hide console window.", exc_info=True)
        return False


def _print_startup_status(message: str):
    print(f"[STARTUP] {message}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ready-before-gui",
        action="store_true",
        help="Run startup preparation in the console before showing the GUI.",
    )
    args = parser.parse_args(argv)

    logger.info("Starting AI Voice Assistant with GUI...")
    assistant = None
    try:
        ensure_private_state()
        assistant = VoiceAssistant()
        if args.ready_before_gui:
            assistant.prepare_for_gui(status_callback=_print_startup_status)
        app = VoiceAssistantUI(assistant)
        if args.ready_before_gui:
            _hide_console_window()
        app.run()
        return 0
    except Exception:
        logger.exception("應用程式執行失敗。")
        if args.ready_before_gui:
            print("[ERROR] AI Voice Assistant startup failed. See logs for details.", flush=True)
        if assistant is not None and args.ready_before_gui:
            try:
                assistant.shutdown_prepared_resources()
            except Exception:
                logger.debug("Failed to clean up prepared resources.", exc_info=True)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
