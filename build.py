"""Build TalkTrack.exe — a lightweight launcher (~1.6 MB) with the custom icon.

Double-click TalkTrack.exe to launch the app. It finds system Python
and runs main.py automatically. No bundled dependencies.

Usage: python build.py
Requires: pip install pyinstaller
"""
import subprocess
import shutil
import sys
from pathlib import Path

APP_DIR = Path(__file__).parent.resolve()
ICON = APP_DIR / "resources" / "talktrack.ico"

LAUNCHER_CODE = """\
# -*- coding: utf-8 -*-
\"\"\"TalkTrack launcher - finds system Python and runs main.py.\"\"\"
import os
import sys
import shutil
import subprocess


def find_pythonw():
    \"\"\"Find the system pythonw.exe (not this exe).\"\"\"
    pythonw = shutil.which("pythonw")
    if pythonw:
        return pythonw
    python = shutil.which("python")
    if python:
        candidate = os.path.join(os.path.dirname(python), "pythonw.exe")
        if os.path.exists(candidate):
            return candidate
        return python
    return None


def main():
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    main_py = os.path.join(exe_dir, "main.py")

    if not os.path.exists(main_py):
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, "Cannot find main.py in:\\\\n" + exe_dir, "TalkTrack", 0x10
        )
        sys.exit(1)

    pythonw = find_pythonw()
    if not pythonw:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, "Cannot find Python. Please install Python 3.10+.", "TalkTrack", 0x10
        )
        sys.exit(1)

    subprocess.Popen([pythonw, main_py], cwd=exe_dir)


if __name__ == "__main__":
    main()
"""

# Heavy modules to exclude (launcher only needs os, sys, shutil, subprocess)
EXCLUDES = [
    "torch", "PyQt6", "numpy", "scipy", "pyannote", "transformers",
    "faster_whisper", "sounddevice", "pydub", "comtypes", "psutil",
    "pycaw", "win32com", "yt_dlp", "torchaudio", "sentence_transformers",
]


def build():
    launcher = APP_DIR / "launcher.py"
    launcher.write_text(LAUNCHER_CODE, encoding="utf-8")

    try:
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--name", "TalkTrack",
            "--onedir",
            "--noconsole",
            "--icon", str(ICON),
            "--distpath", str(APP_DIR),
        ]
        for mod in EXCLUDES:
            cmd.extend(["--exclude-module", mod])
        cmd.append(str(launcher))

        print("Building TalkTrack.exe (lightweight launcher) ...")
        result = subprocess.run(cmd, cwd=str(APP_DIR))

        if result.returncode != 0:
            print("\nBuild failed.")
            sys.exit(1)

        # Move exe and _internal to project root
        build_dir = APP_DIR / "TalkTrack"
        exe_src = build_dir / "TalkTrack.exe"
        internal_src = build_dir / "_internal"

        exe_dst = APP_DIR / "TalkTrack.exe"
        internal_dst = APP_DIR / "_internal"

        # Clean previous build
        if exe_dst.exists():
            exe_dst.unlink()
        if internal_dst.exists():
            shutil.rmtree(internal_dst)

        shutil.move(str(exe_src), str(exe_dst))
        shutil.move(str(internal_src), str(internal_dst))

        size_mb = exe_dst.stat().st_size / (1024 * 1024)
        print(f"\nBuild successful: {exe_dst} ({size_mb:.1f} MB)")
        print("Double-click TalkTrack.exe to launch the app.")
    finally:
        # Clean up build artifacts
        launcher.unlink(missing_ok=True)
        for name in ["TalkTrack", "build", "TalkTrack.spec"]:
            target = APP_DIR / name
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.is_file():
                target.unlink(missing_ok=True)


if __name__ == "__main__":
    build()
