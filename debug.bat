@echo off
setlocal EnableExtensions
chcp 65001 >nul

call :check_already_running
if errorlevel 1 (
    pause
    exit /b 0
)

pushd "%~dp0ai_voice_assistant" >nul 2>&1
if errorlevel 1 (
    echo.
    echo ===================================================
    echo [ERROR] Folder not found: ai_voice_assistant
    echo Make sure this batch file is next to the project folder.
    echo ===================================================
    echo.
    pause
    set "AI_GOVERNESS_EXIT_CODE=1"
    goto :end
)
set "AI_GOVERNESS_PUSHD_OK=1"

call :check_runtime
if errorlevel 1 (
    set "AI_GOVERNESS_EXIT_CODE=1"
    goto :end
)

set "AI_GOVERNESS_CONSOLE_LOG_LEVEL=INFO"
set "AI_GOVERNESS_FILE_LOG_LEVEL=DEBUG"
set "AI_GOVERNESS_LOG_RETENTION_DAYS=5"

echo.
echo ===================================================
echo Starting AI Voice Assistant in debug mode...
echo Console log level: INFO
echo File log level: DEBUG
echo Log retention: 5 days
echo ===================================================
echo.

call :check_already_running
if errorlevel 1 (
    pause
    set "AI_GOVERNESS_EXIT_CODE=0"
    goto :end
)

"%CD%\venv\Scripts\python.exe" "%CD%\main.py"
set "AI_GOVERNESS_EXIT_CODE=%errorlevel%"

if not "%AI_GOVERNESS_EXIT_CODE%"=="0" (
    echo.
    echo ===================================================
    echo [ERROR] AI Voice Assistant exited with code %AI_GOVERNESS_EXIT_CODE%.
    echo ===================================================
    echo.
)

pause
goto :end

:check_runtime
if not exist "venv\Scripts\python.exe" (
    echo.
    echo ===================================================
    echo [ERROR] Missing file: venv\Scripts\python.exe
    echo Run setup_shared_venv.bat from the project root first.
    echo ===================================================
    echo.
    pause
    exit /b 1
)

if not exist "main.py" (
    echo.
    echo ===================================================
    echo [ERROR] Missing file: main.py
    echo ===================================================
    echo.
    pause
    exit /b 1
)

exit /b 0

:check_already_running
set "AI_GOVERNESS_MAIN_PATH=%~dp0ai_voice_assistant\main.py"
for /f %%N in ('powershell -NoProfile -Command "$target=[regex]::Escape([Environment]::GetEnvironmentVariable('AI_GOVERNESS_MAIN_PATH')); @(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match $target }).Count"') do (
    if %%N GTR 0 (
        echo.
        echo ===================================================
        echo [INFO] AI Voice Assistant is already running.
        echo        Another instance will NOT be started.
        echo ===================================================
        echo.
        exit /b 1
    )
)
exit /b 0

:end
if not defined AI_GOVERNESS_EXIT_CODE set "AI_GOVERNESS_EXIT_CODE=%errorlevel%"
if defined AI_GOVERNESS_PUSHD_OK popd >nul 2>&1
endlocal & exit /b %AI_GOVERNESS_EXIT_CODE%
