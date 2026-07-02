import json
import logging
import os
import stat
import subprocess
import time
from pathlib import Path
from datetime import datetime

import shutil

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QMenu, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction

from app.ui.search_bar import SearchBar

logger = logging.getLogger(__name__)


class _SearchWorker(QThread):
    """Runs recording search off the GUI thread.

    Semantic search loads an embedding model and embeds the whole corpus —
    seconds to minutes on first use. Inline, that froze the window.
    """

    results_ready = pyqtSignal(list)

    def __init__(self, recordings_dir, query, is_semantic):
        super().__init__()
        self._recordings_dir = recordings_dir
        self._query = query
        self._is_semantic = is_semantic

    def run(self):
        from app.ai.search_index import load_all_transcripts, text_search
        transcripts = load_all_transcripts(self._recordings_dir)

        results = None
        if self._is_semantic:
            try:
                from app.ai.search_index import semantic_search
                from app.ai.provider_factory import create_provider
                from app.utils.config import Config
                config = Config()
                ai_config = config.data.get("ai", {})
                provider = create_provider(ai_config)
                if provider is not None:
                    results = semantic_search(self._query, transcripts, provider)
            except Exception:
                logger.exception("Semantic search failed — falling back to text")
        if results is None:
            results = text_search(self._query, transcripts)

        self.results_ready.emit(results)


def salvage_orphaned_recordings(recordings_dir, min_age_seconds=600):
    """Give crash-orphaned recording dirs minimal metadata.

    The recorder creates the session dir before capture and writes
    metadata.json only on successful stop, so a crash mid-recording leaves
    WAVs in a directory the list skips — invisible forever. Synthesize
    metadata so the audio shows up as a "Recovered" recording instead of
    deleting user audio. Recent dirs are skipped: they may belong to a
    recording in progress. Returns the list of salvaged directories.
    """
    recordings_dir = Path(recordings_dir)
    if not recordings_dir.exists():
        return []

    salvaged = []
    now = time.time()
    for entry in recordings_dir.iterdir():
        if not entry.is_dir() or (entry / "metadata.json").exists():
            continue

        audio_files = {}
        for key, fname in (("mic", "mic_audio.wav"),
                           ("system", "system_audio.wav"),
                           ("combined", "combined_audio.wav")):
            path = entry / fname
            if path.exists():
                audio_files[key] = str(path)
        if not audio_files:
            continue

        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if now - mtime < min_age_seconds:
            continue

        duration = 0.0
        best_audio = (audio_files.get("combined") or audio_files.get("system")
                      or audio_files.get("mic"))
        try:
            import soundfile as sf
            duration = float(sf.info(best_audio).duration)
        except Exception:
            logger.exception("Could not read duration for %s", best_audio)

        created = datetime.fromtimestamp(mtime)
        metadata = {
            "id": entry.name.replace("recording_", ""),
            "directory": str(entry),
            "name": f"Recovered {created.strftime('%Y-%m-%d %H:%M')}",
            "started_at": created.isoformat(),
            "stopped_at": created.isoformat(),
            "duration": duration,
            "audio_files": audio_files,
            "recovered": True,
        }
        try:
            with open(entry / "metadata.json", "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)
            salvaged.append(str(entry))
            logger.info("Salvaged orphaned recording: %s", entry)
        except OSError:
            logger.exception("Failed to salvage %s", entry)
    return salvaged


def _rmtree_robust(directory, retries=4, initial_delay=0.1):
    """shutil.rmtree with Windows-friendly retry + read-only handling.

    Windows holds transient locks from Explorer/indexer/Defender on just-
    touched audio files. A plain rmtree races with those locks and can
    leave the folder intact. This retries with exponential backoff and
    chmods read-only files writable before removing.
    """
    def onerror(func, path, exc_info):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass

    last_exc = None
    delay = initial_delay
    for attempt in range(retries):
        try:
            shutil.rmtree(directory, onerror=onerror)
            if not Path(directory).exists():
                return
            last_exc = OSError(f"rmtree returned but path still exists: {directory}")
        except Exception as e:
            last_exc = e
        logger.warning(
            "rmtree attempt %d failed for %s: %s", attempt + 1, directory, last_exc
        )
        time.sleep(delay)
        delay *= 2
    raise last_exc


class RecordingsList(QWidget):
    """Browse and manage past recordings."""

    recording_selected = pyqtSignal(dict)  # metadata dict
    about_to_delete = pyqtSignal(str)      # directory path — emitted BEFORE rmtree
                                           # so main_window can release caches and
                                           # stop playback on the target files
    recording_deleted = pyqtSignal(str)    # directory path of deleted recording
    search_result_selected = pyqtSignal(str, float)  # recording_id, timestamp

    def __init__(self, recordings_dir, parent=None):
        super().__init__(parent)
        self.recordings_dir = Path(recordings_dir)
        self._recordings = []
        self._search_worker = None
        self._pending_search = None
        try:
            salvage_orphaned_recordings(self.recordings_dir)
        except Exception:
            logger.exception("Orphan salvage failed")
        self._setup_ui()
        self.refresh()

    def active_search_worker(self):
        """Return the in-flight search worker, if any (for shutdown handling)."""
        return self._search_worker

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

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

            if not metadata.get("directory"):
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

        # Notify listeners FIRST so they can stop playback, clear caches,
        # and release any file handles before the tree comes down.
        self.about_to_delete.emit(directory)

        try:
            _rmtree_robust(directory)
        except Exception as e:
            logger.exception("Failed to delete recording dir: %s", directory)
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
            self.about_to_delete.emit(directory)
            try:
                _rmtree_robust(directory)
                self.recording_deleted.emit(directory)
            except Exception as e:
                logger.exception("Failed to delete recording dir: %s", directory)
                QMessageBox.warning(self, "Error", f"Failed to delete {Path(directory).name}: {e}")

        self.refresh()

    def _play_audio(self, metadata):
        audio_files = metadata.get("audio_files", {})
        audio_path = audio_files.get("combined") or audio_files.get("system") or audio_files.get("mic")
        if audio_path and os.path.exists(audio_path):
            os.startfile(audio_path)

    def _on_search(self, query, is_semantic):
        # Only the latest query matters; typing while a search runs replaces
        # the pending one, and the runner picks it up when the worker frees.
        self._pending_search = (query, is_semantic)
        self._maybe_start_search()

    def _maybe_start_search(self):
        if self._search_worker is not None and self._search_worker.isRunning():
            return
        if self._pending_search is None:
            return
        query, is_semantic = self._pending_search
        self._pending_search = None
        self._search_worker = _SearchWorker(self.recordings_dir, query, is_semantic)
        self._search_worker.results_ready.connect(self._on_search_finished)
        self._search_worker.start()

    def _on_search_finished(self, results):
        self._show_search_results(results)
        self._maybe_start_search()

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
