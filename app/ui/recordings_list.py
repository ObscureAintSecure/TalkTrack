import json
import os
import subprocess
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction


class RecordingsList(QWidget):
    """Browse and manage past recordings."""

    recording_selected = pyqtSignal(dict)  # metadata dict

    def __init__(self, recordings_dir, parent=None):
        super().__init__(parent)
        self.recordings_dir = Path(recordings_dir)
        self._recordings = []
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QHBoxLayout()
        title = QLabel("Recordings")
        title.setObjectName("sectionHeader")
        header.addWidget(title)
        header.addStretch()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self.refresh_btn)

        layout.addLayout(header)

        # List
        self.list_widget = QListWidget()
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.list_widget)

    def refresh(self):
        self.list_widget.clear()
        self._recordings = []

        if not self.recordings_dir.exists():
            return

        for entry in sorted(self.recordings_dir.iterdir(), reverse=True):
            if not entry.is_dir():
                continue
            meta_path = entry / "metadata.json"
            if not meta_path.exists():
                continue

            try:
                with open(meta_path) as f:
                    metadata = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            self._recordings.append(metadata)

            # Format display text
            name = metadata.get("name", "")
            started = metadata.get("started_at", "")
            try:
                dt = datetime.fromisoformat(started)
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                date_str = started

            duration = metadata.get("duration", 0)
            dur_str = self._format_duration(duration)

            has_transcript = (Path(metadata["directory"]) / "transcript.json").exists()
            transcript_indicator = " [T]" if has_transcript else ""

            if name:
                text = f"{name}  |  {date_str}  |  {dur_str}{transcript_indicator}"
            else:
                text = f"{date_str}  |  {dur_str}{transcript_indicator}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, metadata)
            self.list_widget.addItem(item)

    def _on_item_double_clicked(self, item):
        metadata = item.data(Qt.ItemDataRole.UserRole)
        if metadata:
            self.recording_selected.emit(metadata)

    def _show_context_menu(self, position):
        item = self.list_widget.itemAt(position)
        if not item:
            return

        metadata = item.data(Qt.ItemDataRole.UserRole)
        if not metadata:
            return

        menu = QMenu(self)

        open_folder = QAction("Open Folder", self)
        open_folder.triggered.connect(
            lambda: self._open_folder(metadata["directory"])
        )
        menu.addAction(open_folder)

        view_action = QAction("View / Transcribe", self)
        view_action.triggered.connect(lambda: self.recording_selected.emit(metadata))
        menu.addAction(view_action)

        play_action = QAction("Play Audio", self)
        play_action.triggered.connect(lambda: self._play_audio(metadata))
        menu.addAction(play_action)

        menu.exec(self.list_widget.mapToGlobal(position))

    def _open_folder(self, directory):
        os.startfile(directory)

    def _play_audio(self, metadata):
        audio_files = metadata.get("audio_files", {})
        audio_path = audio_files.get("combined") or audio_files.get("system") or audio_files.get("mic")
        if audio_path and os.path.exists(audio_path):
            os.startfile(audio_path)

    def _format_duration(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        if h > 0:
            return f"{h}h {m}m {s}s"
        elif m > 0:
            return f"{m}m {s}s"
        return f"{s}s"
