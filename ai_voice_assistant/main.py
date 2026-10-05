import argparse
import sys

from utils.logger import configure_logging, get_logger

configure_logging()

from private_state import ensure_private_state
from ui.startup_window import StartupWindow

logger = get_logger(__name__)


def _safe_console_print(message: str):
    stream = getattr(sys, "stdout", None)
    if stream is None:
        return
    try:
        print(message, flush=True)
    except Exception:
        logger.debug("Failed to write startup status to console.", exc_info=True)


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
    _safe_console_print(f"[STARTUP] {message}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ready-before-gui",
        action="store_true",
        help="Hide the launch console after startup settings have been confirmed.",
    )
    args = parser.parse_args(argv)

    logger.info("Starting AI Voice Assistant with GUI...")
    assistant = None
    try:
        ensure_private_state()
        def assistant_factory():
            from core.assistant import VoiceAssistant
            return VoiceAssistant()
        prepared = StartupWindow(assistant_factory).prepare()
        if prepared is None:
            return 0
        assistant, session = prepared
        from ui.session_window import VoiceAssistantUI
        app = VoiceAssistantUI(assistant, session)
        if args.ready_before_gui:
            _hide_console_window()
        app.run()
        return 0
    except Exception:
        logger.exception("應用程式執行失敗。")
        if args.ready_before_gui:
            _safe_console_print("[ERROR] AI Voice Assistant startup failed. See logs for details.")
        if assistant is not None:
            try:
                assistant.shutdown_prepared_resources()
            except Exception:
                logger.debug("Failed to clean up prepared resources.", exc_info=True)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
