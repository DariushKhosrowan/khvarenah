@echo off
REM Khvarenah Windows launcher — creates a venv, installs, and runs.
REM Usage: run.bat [args...]

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
)

echo Installing Khvarenah...
.venv\Scripts\pip install --quiet -e .
if errorlevel 1 exit /b 1

.venv\Scripts\khvarenah %*
