@echo off
cd /d "%~dp0"

:: Check if dependencies are installed
python -c "import PyQt6" 2>nul
if errorlevel 1 (
    echo ============================================
    echo   TalkTrack - First Time Setup
    echo ============================================
    echo.
    echo TalkTrack needs to install the following
    echo Python packages. This only happens once
    echo and may take a few minutes.
    echo.
    echo Packages to install:
    echo ----------------------------------------
    type requirements.txt
    echo ----------------------------------------
    echo.
    set /p "CONFIRM=Press Enter to continue or Ctrl+C to cancel..."
    echo.
    echo Installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Failed to install dependencies. Check the output above.
        pause
        exit /b 1
    )
    echo.
    echo Dependencies installed successfully. Launching TalkTrack...
    echo.
)

start "" pythonw main.py
