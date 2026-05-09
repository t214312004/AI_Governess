@echo off
setlocal EnableExtensions
chcp 65001 >nul

if not defined AI_GOVERNESS_SHARED_PYTHON (
    where python >nul 2>&1
    if errorlevel 1 (
        echo.
        echo ===================================================
        echo [ERROR] Python was not found in PATH.
        echo.
        echo Install Python 3.11 or newer, or set:
        echo   set AI_GOVERNESS_SHARED_PYTHON=C:\Path\To\python.exe
        echo ===================================================
        echo.
        pause
        exit /b 1
    )
    for /f "usebackq delims=" %%I in (`where python`) do (
        if not defined AI_GOVERNESS_SHARED_PYTHON set "AI_GOVERNESS_SHARED_PYTHON=%%I"
    )
)

pushd "%~dp0ai_voice_assistant" >nul 2>&1
if errorlevel 1 (
    echo.
    echo ===================================================
    echo [ERROR] Folder not found: ai_voice_assistant
    echo Make sure this batch file is in the project root.
    echo ===================================================
    echo.
    pause
    exit /b 1
)

echo.
echo ===================================================
echo Rebuilding shared venv...
echo Python: %AI_GOVERNESS_SHARED_PYTHON%
echo Target: %CD%\venv
echo ===================================================
echo.

"%AI_GOVERNESS_SHARED_PYTHON%" -m venv --clear venv
if errorlevel 1 goto :fail

"venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail

if exist "requirements-dev.txt" (
    "venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
) else (
    "venv\Scripts\python.exe" -m pip install -r requirements.txt
)
if errorlevel 1 goto :fail

icacls "venv" /grant *S-1-5-32-545:^(OI^)^(CI^)RX /T >nul
if errorlevel 1 (
    echo [WARN] Could not update venv ACL. Try running this batch file as administrator if another user cannot read it.
)

echo.
echo ===================================================
echo [OK] Shared venv is ready.
echo ===================================================
echo.
popd >nul 2>&1
endlocal & exit /b 0

:fail
echo.
echo ===================================================
echo [ERROR] Shared venv setup failed.
echo ===================================================
echo.
popd >nul 2>&1
pause
endlocal & exit /b 1
