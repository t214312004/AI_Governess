@echo off
setlocal
"%~dp0..\..\ai_voice_assistant\venv\Scripts\python.exe" -B "%~dp0native\main.py" --review-tools
if errorlevel 1 pause
