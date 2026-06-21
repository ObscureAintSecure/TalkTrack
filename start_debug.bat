@echo off
cd /d "%~dp0"

:: TalkTrack debug launcher — same environment as start.bat, but runs with a
:: console window (python, not pythonw) so log output is visible.

where uv >nul 2>&1
if %errorlevel%==0 (
    if not exist ".venv\" (
        echo Creating isolated environment with uv...
        uv sync
        if errorlevel 1 (
            echo.
            echo Failed to sync dependencies with uv. Check the output above.
            pause
            exit /b 1
        )
    )
    uv run python main.py
    if errorlevel 1 (
        echo.
        echo TalkTrack exited with an error. Check the output above.
        pause
    )
    goto :eof
)

:: Fallback: uv not installed. Use a LOCAL venv with pip (no global pollution).
echo uv was not found on PATH. Falling back to a local venv via pip...
echo Install uv for the best experience: https://docs.astral.sh/uv/getting-started/installation/
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

python main.py
if errorlevel 1 (
    echo.
    echo TalkTrack exited with an error. Check the output above.
    pause
)
