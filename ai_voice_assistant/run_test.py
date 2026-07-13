import sys
import subprocess
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = APP_DIR / "pytest_clean_output.txt"


def main() -> int:
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--cov=core",
                "--cov=llm",
                "--cov=tts",
                "--cov=utils",
                "--cov-report=term-missing",
                "tests/",
            ],
            cwd=APP_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        with OUTPUT_PATH.open("w", encoding="utf-8", newline="\n") as f:
            f.write("STDOUT:\n")
            f.write(result.stdout)
            f.write("\nSTDERR:\n")
            f.write(result.stderr)
        return result.returncode
    except Exception as exc:
        OUTPUT_PATH.write_text(f"Failed: {exc}", encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
