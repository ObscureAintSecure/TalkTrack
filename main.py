import sys
import os
from pathlib import Path

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
