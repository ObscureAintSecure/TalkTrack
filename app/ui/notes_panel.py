import json
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel
)
from PyQt6.QtCore import Qt


class NotesPanel(QWidget):
    """Panel for taking notes during a call/recording."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session_dir = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QHBoxLayout()
        title = QLabel("Call Notes")
        title.setObjectName("sectionHeader")
        header.addWidget(title)
        header.addStretch()

        self.timestamp_btn = QPushButton("+ Timestamp")
        self.timestamp_btn.setToolTip("Insert current timestamp")
        self.timestamp_btn.clicked.connect(self._insert_timestamp)
        header.addWidget(self.timestamp_btn)

        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save_notes)
        header.addWidget(self.save_btn)

        layout.addLayout(header)

        # Notes editor
        self.editor = QTextEdit()
        self.editor.setPlaceholderText(
            "Type your call notes here...\n\n"
            "Use the Timestamp button to mark important moments."
        )
        layout.addWidget(self.editor)

        self._recording_start = None

    def set_session_dir(self, directory):
        self._session_dir = directory
        # Load existing notes if any
        if directory:
            notes_path = Path(directory) / "notes.txt"
            if notes_path.exists():
                self.editor.setPlainText(notes_path.read_text(encoding="utf-8"))

    def set_recording_start(self, start_time):
        self._recording_start = start_time

    def _insert_timestamp(self):
        now = datetime.now().strftime("%H:%M:%S")
        cursor = self.editor.textCursor()
        cursor.insertText(f"\n[{now}] ")
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def save_notes(self):
        if not self._session_dir:
            return
        notes_path = Path(self._session_dir) / "notes.txt"
        notes_path.write_text(self.editor.toPlainText(), encoding="utf-8")

    def clear(self):
        self.editor.clear()
        self._session_dir = None
        self._recording_start = None

    def get_text(self):
        return self.editor.toPlainText()
