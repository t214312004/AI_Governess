@echo off
setlocal
set "DEMO_PYTHON=%~dp0..\..\ai_voice_assistant\venv\Scripts\pythonw.exe"
if not exist "%DEMO_PYTHON%" (
  echo Project Python environment not found.
  pause
  exit /b 1
)
start "" "%DEMO_PYTHON%" -B "%~dp0native\main.py" --review-tools
