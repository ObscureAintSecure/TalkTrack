import sys
import os
import warnings
from pathlib import Path

# Suppress noisy torchcodec warnings (we use soundfile for audio loading).
# pyannote.audio tries to import torchcodec at module level. Since torchcodec
# requires FFmpeg DLLs we don't have, it spews a massive wall of traceback text.
# Setting PYANNOTE_AUDIO_NO_TORCHCODEC_WARNING doesn't exist, so we suppress
# ALL warnings from that specific module file.
warnings.filterwarnings("ignore", module=r"pyannote\.audio\.core\.io")
warnings.filterwarnings("ignore", message=".*std\\(\\).*degrees of freedom.*")

# Fix DLL search path for PyTorch before QApplication init.
# QApplication modifies the Windows DLL search order, which prevents
# torch's c10.dll from finding its dependencies when loaded in a
# QThread (e.g., during transcription). Adding torch's lib directory
# explicitly restores the search path.
try:
    import torch as _torch
    _torch_lib = os.path.join(os.path.dirname(_torch.__file__), "lib")
    if os.path.isdir(_torch_lib):
        os.add_dll_directory(_torch_lib)
    del _torch, _torch_lib
except ImportError:
    pass

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

from app.main_window import MainWindow


def load_stylesheet():
    style_path = Path(__file__).parent / "resources" / "style.qss"
    if style_path.exists():
        return style_path.read_text()
    return ""


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("TalkTrack")
    app.setOrganizationName("TalkTrack")

    # Apply dark theme stylesheet
    stylesheet = load_stylesheet()
    if stylesheet:
        app.setStyleSheet(stylesheet)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
