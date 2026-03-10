"""Recording info header with rename capability."""
import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal


def _display_name_from_metadata(metadata):
    """Extract display name from metadata, falling back to directory name."""
    name = metadata.get("name", "")
    if name:
        return name
    directory = metadata.get("directory", "")
    return Path(directory).name if directory else "Untitled Recording"


def _format_duration(seconds):
    """Format seconds as human-readable duration string."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


class RecordingHeader(QWidget):
    """Displays recording info (name, date, duration) with rename capability."""

    name_changed = pyqtSignal(str)  # emitted when user renames the recording

    def __init__(self, parent=None):
        super().__init__(parent)
        self._metadata = None
        self._editing = False
        self._setup_ui()
        self.hide()  # hidden until a recording is loaded

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 4)

        # Top row: name + rename button
        top_row = QHBoxLayout()

        self.name_label = QLabel("")
        self.name_label.setObjectName("recordingName")
        self.name_label.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #cdd6f4;"
        )
        top_row.addWidget(self.name_label)

        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("recordingNameEdit")
        self.name_edit.hide()
        self.name_edit.returnPressed.connect(self._finish_rename)
        top_row.addWidget(self.name_edit)

        top_row.addStretch()

        self.rename_btn = QPushButton("Rename")
        self.rename_btn.setObjectName("renameButton")
        self.rename_btn.setFixedWidth(70)
        self.rename_btn.clicked.connect(self._start_rename)
        top_row.addWidget(self.rename_btn)

        layout.addLayout(top_row)

        # Bottom row: date, duration, speaker count
        self.info_label = QLabel("")
        self.info_label.setObjectName("recordingInfo")
        self.info_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(self.info_label)

    def set_recording(self, metadata, speaker_count=0):
        """Display info for the given recording metadata."""
        self._metadata = metadata
        if metadata is None:
            self.hide()
            return

        self.show()

        name = _display_name_from_metadata(metadata)
        self.name_label.setText(name)

        # Build info line
        parts = []
        started = metadata.get("started_at", "")
        if started:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(started)
                parts.append(dt.strftime("%Y-%m-%d %H:%M"))
            except (ValueError, TypeError):
                parts.append(started)

        duration = metadata.get("duration", 0)
        if duration:
            parts.append(f"Duration: {_format_duration(duration)}")

        if speaker_count > 0:
            parts.append(f"{speaker_count} speaker{'s' if speaker_count != 1 else ''}")

        self.info_label.setText("  |  ".join(parts))

    def clear(self):
        """Clear the header, hiding it."""
        self.set_recording(None)

    def _start_rename(self):
        if self._editing:
            self._finish_rename()
            return

        self._editing = True
        self.name_edit.setText(self.name_label.text())
        self.name_label.hide()
        self.name_edit.show()
        self.name_edit.setFocus()
        self.name_edit.selectAll()
        self.rename_btn.setText("Save")

    def _finish_rename(self):
        self._editing = False
        new_name = self.name_edit.text().strip()
        if new_name:
            self.name_label.setText(new_name)
            self.name_changed.emit(new_name)
        self.name_edit.hide()
        self.name_label.show()
        self.rename_btn.setText("Rename")
