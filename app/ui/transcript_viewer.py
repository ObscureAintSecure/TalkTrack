import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QProgressBar, QFileDialog, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QTextCharFormat, QColor, QFont, QTextCursor

from app.transcription.transcriber import TranscriptResult


# Speaker colors for visual distinction
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
    """Displays transcription results with speaker labels and colors."""

    transcribe_requested = pyqtSignal(str)  # audio file path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._transcript = None
        self._speaker_colors = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
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

        # Transcript display
        self.text_view = QTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setPlaceholderText(
            "Transcript will appear here after recording and transcription..."
        )
        layout.addWidget(self.text_view)

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

        self._audio_path = None

    def set_audio_path(self, path):
        self._audio_path = path
        self.transcribe_btn.setEnabled(path is not None)

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

    def display_transcript(self, transcript):
        """Render transcript with speaker colors."""
        self._transcript = transcript
        self.text_view.clear()

        # Assign colors to speakers
        speakers = list(set(s.speaker for s in transcript.segments if s.speaker))
        self._speaker_colors = {}
        for i, speaker in enumerate(sorted(speakers)):
            self._speaker_colors[speaker] = SPEAKER_COLORS[i % len(SPEAKER_COLORS)]

        cursor = self.text_view.textCursor()

        for seg in transcript.segments:
            # Timestamp
            ts_format = QTextCharFormat()
            ts_format.setForeground(QColor("#6c7086"))
            ts_format.setFontFamily("Consolas")
            ts_format.setFontPointSize(10)

            start_ts = self._format_time(seg.start)
            end_ts = self._format_time(seg.end)
            cursor.insertText(f"[{start_ts} -> {end_ts}] ", ts_format)

            # Speaker label
            if seg.speaker:
                spk_format = QTextCharFormat()
                color = self._speaker_colors.get(seg.speaker, "#cdd6f4")
                spk_format.setForeground(QColor(color))
                spk_format.setFontWeight(QFont.Weight.Bold)
                cursor.insertText(f"{seg.speaker}: ", spk_format)

            # Text
            text_format = QTextCharFormat()
            text_format.setForeground(QColor("#cdd6f4"))
            cursor.insertText(f"{seg.text}\n\n", text_format)

        self.text_view.setTextCursor(cursor)

        # Enable export buttons
        self.export_txt_btn.setEnabled(True)
        self.export_srt_btn.setEnabled(True)
        self.export_json_btn.setEnabled(True)

    def _format_time(self, seconds):
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

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

        if format_type == "txt":
            content = self._transcript.to_text()
        elif format_type == "srt":
            content = self._transcript.to_srt()
        elif format_type == "json":
            content = json.dumps(self._transcript.to_dict(), indent=2)

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
