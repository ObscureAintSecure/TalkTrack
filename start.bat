@echo off
cd /d "%~dp0"

:: TalkTrack launcher.
:: Preferred path: uv manages an isolated .venv from pyproject.toml / uv.lock,
:: so dependencies never pollute your global Python install.

where uv >nul 2>&1
if %errorlevel%==0 (
    if not exist ".venv\" (
        echo ============================================
        echo   TalkTrack - First Time Setup ^(uv^)
        echo ============================================
        echo.
        echo Creating an isolated environment and installing
        echo dependencies with uv. This only happens once and
        echo may take a few minutes.
        echo.
        uv sync
        if errorlevel 1 (
            echo.
            echo Failed to sync dependencies with uv. Check the output above.
            pause
            exit /b 1
        )
        echo.
        echo Dependencies installed. Launching TalkTrack...
        echo.
    )
    start "" /b uv run pythonw main.py
    goto :eof
)

:: Fallback: uv not installed. Use a LOCAL venv with pip (still no global pollution).
echo uv was not found on PATH. Install it for the best experience:
echo   https://docs.astral.sh/uv/getting-started/installation/
echo.
echo Falling back to a local virtual environment via pip...
echo.

if not exist ".venv\" (
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment. Is Python installed?
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
python -c "import PyQt6, sounddevice, numpy" 2>nul
if errorlevel 1 (
    echo Installing dependencies into .venv...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Failed to install dependencies. Check the output above.
        pause
        exit /b 1
    )
)

start "" /b pythonw main.py
