import sys
import os
import logging
import logging.handlers
import platform
import traceback
import warnings
import ctypes
from pathlib import Path

# Set Windows AppUserModelID so the taskbar shows our icon, not Python's.
# Must be called before QApplication is created. Uses explicit arg/res types
# to ensure the wide string is passed correctly.
try:
    _SetAppID = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    _SetAppID.argtypes = [ctypes.c_wchar_p]
    _SetAppID.restype = ctypes.HRESULT
    _SetAppID("TalkTrack.TalkTrack.1")
except Exception:
    pass

# --- Logging setup (before anything else) ---
LOG_DIR = Path.home() / ".talktrack"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "talktrack.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        ),
    ],
)
logger = logging.getLogger("talktrack")
logger.info("TalkTrack starting — Python %s on %s", sys.version, platform.platform())

# Redirect stderr to log file so uncaught tracebacks are captured
class _StderrToLog:
    def __init__(self, logger):
        self._logger = logger
        self._buf = ""

    def write(self, msg):
        if msg and msg.strip():
            self._logger.error(msg.rstrip())

    def flush(self):
        pass

sys.stderr = _StderrToLog(logger)

# Suppress noisy torchcodec warnings (we use soundfile for audio loading).
warnings.filterwarnings("ignore", module=r"pyannote\.audio\.core\.io")
warnings.filterwarnings("ignore", message=".*std\\(\\).*degrees of freedom.*")

# Fix DLL search path for PyTorch before QApplication init.
try:
    import torch as _torch
    _torch_lib = os.path.join(os.path.dirname(_torch.__file__), "lib")
    if os.path.isdir(_torch_lib):
        os.add_dll_directory(_torch_lib)
    del _torch, _torch_lib
except ImportError:
    pass

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QIcon

from app.main_window import MainWindow


def get_log_file():
    """Return the path to the log file."""
    return LOG_FILE


def get_log_tail(lines=30):
    """Return the last N lines of the log file."""
    try:
        text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
        return "\n".join(text.splitlines()[-lines:])
    except OSError:
        return "(could not read log file)"


def build_bug_report_url(error_text=""):
    """Build a GitHub issue URL pre-filled with system info and error details."""
    import urllib.parse

    body_parts = [
        "## Description",
        "(Describe what you were doing when the problem occurred)",
        "",
        "## System Info",
        f"- **OS:** {platform.platform()}",
        f"- **Python:** {sys.version.split()[0]}",
    ]

    try:
        import torch
        body_parts.append(f"- **PyTorch:** {torch.__version__}")
        body_parts.append(f"- **CUDA available:** {torch.cuda.is_available()}")
    except ImportError:
        body_parts.append("- **PyTorch:** not installed")

    if error_text:
        body_parts.extend([
            "",
            "## Error",
            "```",
            error_text[-1500:],  # Trim to avoid URL length limits
            "```",
        ])

    body_parts.extend([
        "",
        "## Recent Log",
        "```",
        get_log_tail(15),
        "```",
    ])

    body = "\n".join(body_parts)
    params = urllib.parse.urlencode({
        "title": "[Bug] ",
        "body": body,
        "labels": "bug",
    })
    return f"https://github.com/ObscureAintSecure/TalkTrack/issues/new?{params}"


def _exception_handler(exc_type, exc_value, exc_tb):
    """Global exception handler — log the error and show a crash dialog."""
    if exc_type == KeyboardInterrupt:
        sys.exit(0)

    error_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.critical("Uncaught exception:\n%s", error_text)

    try:
        import webbrowser
        msg = QMessageBox()
        msg.setWindowTitle("TalkTrack — Unexpected Error")
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setText("TalkTrack encountered an unexpected error.")
        msg.setInformativeText(str(exc_value))
        msg.setDetailedText(error_text)

        report_btn = msg.addButton("Report Bug", QMessageBox.ButtonRole.ActionRole)
        open_log_btn = msg.addButton("Open Log", QMessageBox.ButtonRole.HelpRole)
        msg.addButton(QMessageBox.StandardButton.Close)

        msg.exec()

        clicked = msg.clickedButton()
        if clicked == report_btn:
            webbrowser.open(build_bug_report_url(error_text))
        elif clicked == open_log_btn:
            os.startfile(str(LOG_FILE))
    except Exception:
        pass


def load_stylesheet():
    style_path = Path(__file__).parent / "resources" / "style.qss"
    if style_path.exists():
        return style_path.read_text()
    return ""


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("TalkTrack")
    app.setOrganizationName("TalkTrack")

    # Set app icon
    from PyQt6.QtGui import QIcon
    icon_path = Path(__file__).parent / "resources" / "talktrack.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Install global exception handler
    sys.excepthook = _exception_handler

    # Apply dark theme stylesheet
    stylesheet = load_stylesheet()
    if stylesheet:
        app.setStyleSheet(stylesheet)

    window = MainWindow()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()

    # Force taskbar icon via Win32 API (needed for Microsoft Store Python)
    if icon_path.exists():
        try:
            WM_SETICON = 0x0080
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            LR_DEFAULTSIZE = 0x0040
            hwnd = int(window.winId())
            hicon_big = ctypes.windll.user32.LoadImageW(
                None, str(icon_path), IMAGE_ICON, 48, 48,
                LR_LOADFROMFILE,
            )
            hicon_small = ctypes.windll.user32.LoadImageW(
                None, str(icon_path), IMAGE_ICON, 16, 16,
                LR_LOADFROMFILE,
            )
            if hicon_big:
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 1, hicon_big)
            if hicon_small:
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 0, hicon_small)
        except Exception:
            pass

    logger.info("TalkTrack UI ready")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
