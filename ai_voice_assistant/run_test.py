import sys
import subprocess

try:
    result = subprocess.run(
        ["python", "-m", "pytest", "--cov=core", "--cov=llm", "--cov=tts", "--cov=utils", "--cov-report=term-missing", "tests/"],
        capture_output=True
    )
    with open("pytest_clean_output.txt", "w", encoding="utf-8", errors="ignore") as f:
        f.write("STDOUT:\n")
        f.write(result.stdout.decode('utf-8', errors='ignore'))
        f.write("\nSTDERR:\n")
        f.write(result.stderr.decode('utf-8', errors='ignore'))
except Exception as e:
    with open("pytest_clean_output.txt", "w", encoding="utf-8") as f:
        f.write(f"Failed: {e}")
