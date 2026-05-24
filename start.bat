@echo off
setlocal EnableExtensions
chcp 65001 >nul

call :check_already_running
if errorlevel 1 (
    timeout /t 5 >nul
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

call :load_active_backend
if errorlevel 1 (
    set "AI_GOVERNESS_EXIT_CODE=1"
    goto :end
)

call :prepare_backend
if errorlevel 1 (
    set "AI_GOVERNESS_EXIT_CODE=1"
    goto :end
)

echo.
echo ===================================================
echo Preparing AI Voice Assistant...
echo Active backend: %AI_GOVERNESS_ACTIVE_BACKEND%
echo The GUI will open after Whisper and LLM are ready.
echo ===================================================
echo.

call :check_already_running
if errorlevel 1 (
    timeout /t 5 >nul
    set "AI_GOVERNESS_EXIT_CODE=0"
    goto :end
)

start "AI Voice Assistant" /D "%CD%" "%CD%\venv\Scripts\pythonw.exe" "main.py" --ready-before-gui
set "AI_GOVERNESS_EXIT_CODE=%errorlevel%"

if not "%AI_GOVERNESS_EXIT_CODE%"=="0" (
    echo.
    echo ===================================================
    echo [ERROR] AI Voice Assistant exited with code %AI_GOVERNESS_EXIT_CODE%.
    echo ===================================================
    echo.
    pause
)
goto :end

:check_runtime
if not exist "venv\Scripts\pythonw.exe" (
    echo.
    echo ===================================================
    echo [ERROR] Missing file: venv\Scripts\pythonw.exe
    echo Run setup_shared_venv.bat from the project root first.
    echo ===================================================
    echo.
    pause
    exit /b 1
)

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

:load_active_backend
set "AI_GOVERNESS_ACTIVE_BACKEND=gemini_cli"

for /f "usebackq delims=" %%I in (`venv\Scripts\python.exe -c "from config import config; print(config.get('llm', 'active_backend', default='gemini_cli') or 'gemini_cli')" 2^>nul`) do (
    set "AI_GOVERNESS_ACTIVE_BACKEND=%%I"
)

if not defined AI_GOVERNESS_ACTIVE_BACKEND set "AI_GOVERNESS_ACTIVE_BACKEND=gemini_cli"
echo [INFO] Selected backend: %AI_GOVERNESS_ACTIVE_BACKEND%
exit /b 0

:prepare_backend
if /i "%AI_GOVERNESS_ACTIVE_BACKEND%"=="gemini_cli" (
    call :ensure_gemini
    if errorlevel 1 exit /b 1
    call :check_gemini_login
    if errorlevel 1 exit /b 1
    exit /b 0
)

if /i "%AI_GOVERNESS_ACTIVE_BACKEND%"=="codex_cli" (
    call :ensure_codex
    if errorlevel 1 exit /b 1
    call :check_codex_login
    if errorlevel 1 exit /b 1
    exit /b 0
)

if /i "%AI_GOVERNESS_ACTIVE_BACKEND%"=="opencode_cli" (
    call :ensure_opencode
    if errorlevel 1 exit /b 1
    call :check_opencode_login
    if errorlevel 1 exit /b 1
    exit /b 0
)

if /i "%AI_GOVERNESS_ACTIVE_BACKEND%"=="openclaw" (
    echo [INFO] OpenClaw backend selected. Skipping local CLI checks.
    exit /b 0
)

if /i "%AI_GOVERNESS_ACTIVE_BACKEND%"=="claude_code" (
    echo [INFO] Claude Code backend selected. No pre-launch check is configured in this batch file yet.
    exit /b 0
)

echo [WARN] Unknown backend: %AI_GOVERNESS_ACTIVE_BACKEND%
echo [WARN] Starting without backend-specific preflight checks.
exit /b 0

:ensure_gemini
where npm >nul 2>&1
if errorlevel 1 (
    echo.
    echo ===================================================
    echo [ERROR] npm was not found. Gemini CLI cannot be installed or updated.
    echo Please install Node.js 18 or newer first:
    echo https://nodejs.org/
    echo ===================================================
    echo.
    pause
    exit /b 1
)

echo [INFO] Updating Gemini CLI...
call npm i -g @google/gemini-cli@latest
if errorlevel 1 (
    echo.
    echo ===================================================
    echo [ERROR] Gemini CLI update failed.
    echo Please run: npm i -g @google/gemini-cli@latest
    echo ===================================================
    echo.
    pause
    exit /b 1
)

where gemini >nul 2>&1
if errorlevel 1 (
    echo.
    echo ===================================================
    echo [ERROR] Gemini CLI still was not found after install.
    echo Reopen the terminal and try again.
    echo ===================================================
    echo.
    pause
    exit /b 1
)

echo [OK] Gemini CLI installed and updated.
exit /b 0

:check_gemini_login
echo [INFO] Checking Gemini CLI login...
"venv\Scripts\python.exe" "tools\gemini_auth_probe.py"
if not errorlevel 1 (
    echo [OK] Gemini CLI login is ready.
    exit /b 0
)

echo.
echo ===================================================
echo Gemini CLI login check failed.
echo Opening Gemini CLI so you can sign in or refresh auth.
echo When login is done, type /quit or close the Gemini CLI window.
echo ===================================================
echo.

call :login_gemini
if errorlevel 1 exit /b 1

echo [INFO] Rechecking Gemini CLI login...
"venv\Scripts\python.exe" "tools\gemini_auth_probe.py"
if errorlevel 1 (
    echo.
    echo ===================================================
    echo [ERROR] Gemini CLI login still is not ready.
    echo Please finish Gemini login, then run this batch file again.
    echo ===================================================
    echo.
    pause
    exit /b 1
)

echo [OK] Gemini CLI login is ready.
exit /b 0

:login_gemini
echo.
echo ===================================================
echo Opening Gemini CLI for login...
echo If you are not signed in, follow the Gemini CLI prompts.
echo When login is done, type /quit or close the Gemini CLI window.
echo The GUI will start right after the Gemini CLI window closes.
echo ===================================================
echo.

2>nul (
    echo N|start "Gemini Login" /wait "%ComSpec%" /c "gemini"
)
set "AI_GOVERNESS_GEMINI_EXIT=%errorlevel%"

if not "%AI_GOVERNESS_GEMINI_EXIT%"=="0" (
    echo.
    echo ===================================================
    echo [WARN] Gemini CLI exited with code %AI_GOVERNESS_GEMINI_EXIT%.
    echo If login did not finish, the GUI may not work with Gemini.
    echo Press any key to continue starting the GUI.
    echo ===================================================
    echo.
    pause >nul
)

exit /b 0

:ensure_codex
where codex >nul 2>&1
if not errorlevel 1 (
    goto :update_codex
)

echo [INFO] Codex CLI not found. Trying to install it...

where npm >nul 2>&1
if errorlevel 1 (
    echo.
    echo ===================================================
    echo [ERROR] npm was not found. Codex CLI cannot be installed.
    echo Please install Node.js 18 or newer first:
    echo https://nodejs.org/
    echo ===================================================
    echo.
    pause
    exit /b 1
)

call npm i -g @openai/codex@latest
if errorlevel 1 (
    echo.
    echo ===================================================
    echo [ERROR] Codex CLI installation failed.
    echo Please run: npm i -g @openai/codex@latest
    echo ===================================================
    echo.
    pause
    exit /b 1
)

where codex >nul 2>&1
if errorlevel 1 (
    echo.
    echo ===================================================
    echo [ERROR] Codex CLI still was not found after install.
    echo Reopen the terminal and try again.
    echo ===================================================
    echo.
    pause
    exit /b 1
)

echo [OK] Codex CLI installed.

:update_codex
echo [INFO] Updating Codex CLI...
call codex update
if errorlevel 1 (
    echo.
    echo ===================================================
    echo [ERROR] Codex CLI update failed.
    echo Please run: codex update
    echo ===================================================
    echo.
    pause
    exit /b 1
)

echo [OK] Codex CLI installed and updated.
exit /b 0

:check_codex_login
set "AI_GOVERNESS_CODEX_STATUS="
set "AI_GOVERNESS_CODEX_LOGGED_IN="

for /f "usebackq delims=" %%I in (`codex login status 2^>^&1`) do (
    if not defined AI_GOVERNESS_CODEX_STATUS set "AI_GOVERNESS_CODEX_STATUS=%%I"
    echo %%I | findstr /I /R /C:"^Logged in" >nul
    if not errorlevel 1 set "AI_GOVERNESS_CODEX_LOGGED_IN=1"
)

if defined AI_GOVERNESS_CODEX_STATUS (
    echo [INFO] %AI_GOVERNESS_CODEX_STATUS%
)

if defined AI_GOVERNESS_CODEX_LOGGED_IN (
    echo [OK] Codex CLI login is ready.
    exit /b 0
)

echo.
echo ===================================================
echo [ERROR] Codex CLI is installed but not logged in.
echo Please run: codex login
echo After login finishes, run this batch file again.
echo.
echo If you want to use another backend instead, change
echo ai_voice_assistant\config.local.json and set llm.active_backend.
echo ===================================================
echo.
pause
exit /b 1

:ensure_opencode
where opencode >nul 2>&1
if not errorlevel 1 (
    echo [OK] OpenCode CLI found.
    exit /b 0
)

echo.
echo ===================================================
echo [ERROR] OpenCode CLI was not found on PATH.
echo Please install OpenCode and finish login first:
echo https://opencode.ai/
echo ===================================================
echo.
pause
exit /b 1

:check_opencode_login
echo [INFO] Checking OpenCode CLI ACP session...
"venv\Scripts\python.exe" "tools\opencode_auth_probe.py"
if not errorlevel 1 (
    echo [OK] OpenCode CLI is ready.
    exit /b 0
)

echo.
echo ===================================================
echo [ERROR] OpenCode CLI ACP check failed.
echo Please run: opencode
echo Finish login or account setup, then run this batch file again.
echo ===================================================
echo.
pause
exit /b 1

:check_already_running
for /f %%N in ('powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'main\.py' }).Count"') do (
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
