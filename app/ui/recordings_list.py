import json
import os
import subprocess
from pathlib import Path
from datetime import datetime

import shutil

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QMenu, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction

from app.ui.search_bar import SearchBar


class RecordingsList(QWidget):
    """Browse and manage past recordings."""

    recording_selected = pyqtSignal(dict)  # metadata dict
    recording_deleted = pyqtSignal(str)    # directory path of deleted recording
    search_result_selected = pyqtSignal(str, float)  # recording_id, timestamp

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
        title = QLabel("Recordings")
        title.setObjectName("sectionHeader")
        layout.addWidget(title)

        # Search bar
        self.search_bar = SearchBar()
        self.search_bar.search_requested.connect(self._on_search)
        self.search_bar.cleared.connect(self.refresh)
        layout.addWidget(self.search_bar)

        # List
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(100)
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.list_widget, 1)

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
        data = item.data(Qt.ItemDataRole.UserRole)
        if data is None:
            return
        if "recording_id" in data and "directory" not in data:
            # This is a search result
            self.search_result_selected.emit(data["recording_id"], data.get("start", 0.0))
        else:
            self.recording_selected.emit(data)

    def _show_context_menu(self, position):
        item = self.list_widget.itemAt(position)
        if not item:
            return

        selected_items = self.list_widget.selectedItems()
        metadata = item.data(Qt.ItemDataRole.UserRole)
        if not metadata:
            return

        menu = QMenu(self)

        if len(selected_items) > 1:
            # Multi-select context menu
            count = len(selected_items)
            delete_action = QAction(f"Delete {count} Recordings", self)
            delete_action.triggered.connect(
                lambda: self._delete_selected_recordings(selected_items)
            )
            menu.addAction(delete_action)
        else:
            # Single item context menu
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

            menu.addSeparator()

            delete_action = QAction("Delete Recording", self)
            delete_action.triggered.connect(lambda: self._delete_recording(metadata))
            menu.addAction(delete_action)

        menu.exec(self.list_widget.mapToGlobal(position))

    def _open_folder(self, directory):
        os.startfile(directory)

    def _delete_recording(self, metadata):
        directory = metadata.get("directory", "")
        name = metadata.get("name", "") or Path(directory).name

        reply = QMessageBox.question(
            self, "Delete Recording",
            f"Delete \"{name}\" and all its files?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            shutil.rmtree(directory)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to delete: {e}")
            return

        self.recording_deleted.emit(directory)
        self.refresh()

    def _delete_selected_recordings(self, items):
        """Delete multiple selected recordings."""
        recordings = []
        for item in items:
            meta = item.data(Qt.ItemDataRole.UserRole)
            if meta and "directory" in meta:
                recordings.append(meta)

        if not recordings:
            return

        count = len(recordings)
        reply = QMessageBox.question(
            self, "Delete Recordings",
            f"Delete {count} recording{'s' if count > 1 else ''} and all their files?\n\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        for meta in recordings:
            directory = meta.get("directory", "")
            try:
                shutil.rmtree(directory)
                self.recording_deleted.emit(directory)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to delete {Path(directory).name}: {e}")

        self.refresh()

    def _play_audio(self, metadata):
        audio_files = metadata.get("audio_files", {})
        audio_path = audio_files.get("combined") or audio_files.get("system") or audio_files.get("mic")
        if audio_path and os.path.exists(audio_path):
            os.startfile(audio_path)

    def _on_search(self, query, is_semantic):
        from app.ai.search_index import load_all_transcripts, text_search
        transcripts = load_all_transcripts(self.recordings_dir)

        if is_semantic:
            try:
                from app.ai.search_index import semantic_search
                from app.ai.provider_factory import create_provider
                from app.utils.config import Config
                config = Config()
                ai_config = config.data.get("ai", {})
                provider = create_provider(ai_config)
                if provider is not None:
                    results = semantic_search(query, transcripts, provider)
                else:
                    results = text_search(query, transcripts)
            except Exception:
                results = text_search(query, transcripts)
        else:
            results = text_search(query, transcripts)

        self._show_search_results(results)

    def _show_search_results(self, results):
        self.list_widget.clear()
        for result in results[:50]:
            rec_id = result["recording_id"]
            speaker = result.get("speaker", "")
            text = result["text"]
            display = f"{rec_id}\n"
            if speaker:
                display += f"  [{speaker}] "
            display += text[:80]
            if len(text) > 80:
                display += "..."
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, result)
            self.list_widget.addItem(item)

    def _format_duration(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        if h > 0:
            return f"{h}h {m}m {s}s"
        elif m > 0:
            return f"{m}m {s}s"
        return f"{s}s"
