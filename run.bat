@echo off
rem Cloudflare-worker VPN console — Windows launcher.
rem Double-click or run from cmd/PowerShell. Creates .venv on first run.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtualenv (first run)...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create .venv. Install Python 3.10+ and ensure 'python' is on PATH.
        pause
        exit /b 1
    )
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install textual requests pyperclip
    if errorlevel 1 (
        echo [ERROR] Dependency install failed. Check your network.
        pause
        exit /b 1
    )
)

.venv\Scripts\python.exe run.py %*
set RC=%ERRORLEVEL%
exit /b %RC%
