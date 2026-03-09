@echo off
cd /d "%~dp0"
python main.py
if errorlevel 1 (
    echo.
    echo TalkTrack exited with an error. Check the output above.
    pause
)
