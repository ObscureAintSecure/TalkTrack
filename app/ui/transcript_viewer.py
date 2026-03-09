"""Transcript viewer with interactive segment editing, playback, and speaker naming."""
import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QProgressBar, QFileDialog, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QShortcut, QKeySequence

from app.transcription.transcriber import TranscriptResult, TranscriptSegment
from app.ui.transcript_search_bar import TranscriptSearchBar


# Speaker colors for visual distinction — shared constant
SPEAKER_COLORS = [
    "#89b4fa",  # blue
    "#a6e3a1",  # green
    "#fab387",  # peach
    "#f5c2e7",  # pink
    "#94e2d5",  # teal
    "#f9e2af",  # yellow
    "#cba6f7",  # mauve
    "#f38ba8",  # red
]


class TranscriptViewer(QWidget):
    """Displays transcription results with interactive segments.

    Features:
    - Per-segment play buttons for audio clip playback
    - Inline text editing with undo (original_text preservation)
    - Speaker name panel for mapping IDs to friendly names
    - Export to TXT, SRT, JSON with speaker names
    """

    transcribe_requested = pyqtSignal(str)  # audio file path
    transcript_changed = pyqtSignal()       # emitted when text or names change
    speaker_names_changed = pyqtSignal(dict)  # emitted when speaker names change

    def __init__(self, parent=None):
        super().__init__(parent)
        self._transcript = None
        self._speaker_colors = {}
        self._speaker_names = {}
        self._segment_widgets = []
        self._audio_path = None
        self._player = None
        self._playing_index = -1
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Header row: title + transcribe button
        header = QHBoxLayout()
        title = QLabel("Transcript")
        title.setObjectName("sectionHeader")
        header.addWidget(title)
        header.addStretch()

        self.transcribe_btn = QPushButton("Transcribe")
        self.transcribe_btn.setEnabled(False)
        self.transcribe_btn.clicked.connect(self._on_transcribe_clicked)
        header.addWidget(self.transcribe_btn)

        layout.addLayout(header)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.hide()
        layout.addWidget(self.status_label)

        # Speaker name panel
        from app.ui.speaker_name_panel import SpeakerNamePanel
        self.speaker_panel = SpeakerNamePanel()
        self.speaker_panel.names_changed.connect(self._on_speaker_names_changed)
        layout.addWidget(self.speaker_panel)

        # Find/replace bar
        self.search_bar = TranscriptSearchBar()
        self.search_bar.navigate_to_match.connect(self._highlight_match)
        self.search_bar.replace_requested.connect(self._replace_match)
        layout.addWidget(self.search_bar)

        # Ctrl+F shortcut
        find_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        find_shortcut.activated.connect(self._show_search)

        # Scroll area for segment widgets
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet(
            "QScrollArea { border: 1px solid #313244; border-radius: 6px; "
            "background-color: #181825; }"
        )

        self._segments_container = QWidget()
        self._segments_container.setStyleSheet("background-color: #181825;")
        self._segments_layout = QVBoxLayout(self._segments_container)
        self._segments_layout.setContentsMargins(8, 8, 8, 8)
        self._segments_layout.setSpacing(2)
        self._segments_layout.addStretch()

        self.scroll_area.setWidget(self._segments_container)

        # Placeholder text
        self._placeholder = QLabel(
            "Transcript will appear here after recording and transcription..."
        )
        self._placeholder.setStyleSheet("color: #585b70; padding: 20px;")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._segments_layout.insertWidget(0, self._placeholder)

        layout.addWidget(self.scroll_area, 1)

        # Export buttons
        export_row = QHBoxLayout()
        export_row.addStretch()

        self.export_txt_btn = QPushButton("Export TXT")
        self.export_txt_btn.setEnabled(False)
        self.export_txt_btn.clicked.connect(lambda: self._export("txt"))
        export_row.addWidget(self.export_txt_btn)

        self.export_srt_btn = QPushButton("Export SRT")
        self.export_srt_btn.setEnabled(False)
        self.export_srt_btn.clicked.connect(lambda: self._export("srt"))
        export_row.addWidget(self.export_srt_btn)

        self.export_json_btn = QPushButton("Export JSON")
        self.export_json_btn.setEnabled(False)
        self.export_json_btn.clicked.connect(lambda: self._export("json"))
        export_row.addWidget(self.export_json_btn)

        layout.addLayout(export_row)

    def _ensure_player(self):
        """Lazily create the SegmentPlayer."""
        if self._player is None:
            from app.audio.segment_player import SegmentPlayer
            self._player = SegmentPlayer(self)
            self._player.playback_finished.connect(self._on_playback_finished)

    def set_audio_path(self, path):
        self._audio_path = path
        self.transcribe_btn.setEnabled(path is not None)
        if self._player:
            self._player.stop()
            self._player.clear_cache()

    def set_speaker_names(self, names):
        """Set speaker names from loaded speaker_names.json."""
        self._speaker_names = dict(names) if names else {}

    def _on_transcribe_clicked(self):
        if self._audio_path:
            self.transcribe_requested.emit(self._audio_path)

    def show_progress(self, message):
        self.progress_bar.show()
        self.status_label.setText(message)
        self.status_label.show()

    def hide_progress(self):
        self.progress_bar.hide()
        self.status_label.hide()

    def display_transcript(self, transcript, speaker_names=None):
        """Render transcript with interactive segment widgets."""
        self._transcript = transcript
        if speaker_names is not None:
            self._speaker_names = dict(speaker_names)

        # Stop any playing audio
        if self._player:
            self._player.stop()
        self._playing_index = -1

        # Assign colors to speakers
        speakers = sorted(set(s.speaker for s in transcript.segments if s.speaker))
        self._speaker_colors = {}
        for i, speaker in enumerate(speakers):
            self._speaker_colors[speaker] = SPEAKER_COLORS[i % len(SPEAKER_COLORS)]

        # Clear existing segment widgets
        self._segment_widgets.clear()
        while self._segments_layout.count():
            item = self._segments_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Build segment widgets
        from app.ui.segment_widget import SegmentWidget

        for i, seg in enumerate(transcript.segments):
            color = self._speaker_colors.get(seg.speaker, "#cdd6f4")
            name = self._speaker_names.get(seg.speaker, "")

            widget = SegmentWidget(
                index=i,
                segment=seg,
                speaker_color=color,
                speaker_name=name,
                parent=self._segments_container,
            )
            widget.play_requested.connect(self._on_play_requested)
            widget.stop_requested.connect(self._on_stop_requested)
            widget.text_edited.connect(self._on_text_edited)
            widget.text_reverted.connect(self._on_text_reverted)
            widget.speaker_clicked.connect(self._on_speaker_label_clicked)

            self._segment_widgets.append(widget)
            self._segments_layout.addWidget(widget)

        self._segments_layout.addStretch()

        # Update speaker panel
        self.speaker_panel.set_speakers(transcript.segments, self._speaker_names)

        # Enable export buttons
        self.export_txt_btn.setEnabled(True)
        self.export_srt_btn.setEnabled(True)
        self.export_json_btn.setEnabled(True)

    def get_speaker_count(self):
        """Return number of unique speakers in current transcript."""
        if not self._transcript:
            return 0
        return len(set(s.speaker for s in self._transcript.segments if s.speaker))

    # --- Audio playback ---

    def _on_play_requested(self, index):
        if not self._audio_path:
            return
        self._ensure_player()

        # Stop previous
        if self._playing_index >= 0 and self._playing_index < len(self._segment_widgets):
            self._segment_widgets[self._playing_index].set_playing(False)

        seg = self._transcript.segments[index]
        self._player.play_segment(self._audio_path, seg.start, seg.end)
        self._playing_index = index
        self._segment_widgets[index].set_playing(True)

    def _on_stop_requested(self):
        if self._player:
            self._player.stop()
        if self._playing_index >= 0 and self._playing_index < len(self._segment_widgets):
            self._segment_widgets[self._playing_index].set_playing(False)
        self._playing_index = -1

    def _on_playback_finished(self):
        if self._playing_index >= 0 and self._playing_index < len(self._segment_widgets):
            self._segment_widgets[self._playing_index].set_playing(False)
        self._playing_index = -1

    # --- Text editing ---

    def _on_text_edited(self, index, new_text):
        seg = self._transcript.segments[index]
        if not seg.original_text:
            seg.original_text = seg.text
        seg.text = new_text
        self.transcript_changed.emit()

    def _on_text_reverted(self, index):
        seg = self._transcript.segments[index]
        if seg.original_text:
            seg.text = seg.original_text
            seg.original_text = ""
        self.transcript_changed.emit()

    # --- Speaker names ---

    def _on_speaker_names_changed(self, names):
        self._speaker_names = names
        for widget in self._segment_widgets:
            widget.update_speaker(names)
        self.speaker_names_changed.emit(names)

    def _on_speaker_label_clicked(self, speaker_id):
        self.speaker_panel.focus_speaker(speaker_id)

    # --- Find/replace ---

    def _show_search(self):
        texts = [seg.text for seg in self._transcript.segments] if self._transcript else []
        self.search_bar.set_texts(texts)
        self.search_bar.show_bar()

    def _highlight_match(self, seg_idx, start, end):
        if 0 <= seg_idx < len(self._segment_widgets):
            widget = self._segment_widgets[seg_idx]
            self.scroll_area.ensureWidgetVisible(widget)
            widget.highlight_match(start, end)

    def _replace_match(self, seg_idx, new_text, start, end):
        if 0 <= seg_idx < len(self._segment_widgets):
            seg = self._transcript.segments[seg_idx]
            updated = seg.text[:start] + new_text + seg.text[end:]
            self._segment_widgets[seg_idx]._history.push(updated)
            self._segment_widgets[seg_idx].text_label.setText(updated)
            self._segment_widgets[seg_idx].edit_indicator.setVisible(
                self._segment_widgets[seg_idx]._history.is_modified()
            )
            seg.text = updated
            self.transcript_changed.emit()
            texts = [s.text for s in self._transcript.segments]
            self.search_bar.set_texts(texts)

    # --- Export ---

    def _export(self, format_type):
        if not self._transcript:
            return

        filters = {
            "txt": "Text Files (*.txt)",
            "srt": "SRT Subtitle Files (*.srt)",
            "json": "JSON Files (*.json)",
        }

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Transcript", "", filters[format_type]
        )

        if not path:
            return

        names = self._speaker_names

        if format_type == "txt":
            content = self._transcript.to_text(speaker_names=names)
        elif format_type == "srt":
            content = self._transcript.to_srt(speaker_names=names)
        elif format_type == "json":
            content = json.dumps(
                self._transcript.to_dict(speaker_names=names), indent=2
            )

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
