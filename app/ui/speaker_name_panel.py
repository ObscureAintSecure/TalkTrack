"""Collapsible speaker name editing panel."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal


# Speaker colors — must match the list in transcript_viewer.py
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


def _extract_speakers(segments):
    """Extract unique speaker IDs from segments, sorted."""
    speakers = set()
    for seg in segments:
        if seg.speaker:
            speakers.add(seg.speaker)
    return sorted(speakers)


class SpeakerNamePanel(QWidget):
    """Collapsible panel for mapping speaker IDs to friendly names.

    Emits names_changed whenever any name is edited.
    """

    names_changed = pyqtSignal(dict)  # {speaker_id: name}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._speaker_ids = []
        self._name_edits = {}  # speaker_id -> QLineEdit
        self._speaker_names = {}  # speaker_id -> name str
        self._collapsed = False
        self._setup_ui()
        self.hide()  # hidden until speakers exist

    def _setup_ui(self):
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(4)

        # Header row with toggle
        header_row = QHBoxLayout()
        self._toggle_btn = QPushButton("\u25bc Speakers")
        self._toggle_btn.setObjectName("speakerPanelToggle")
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setStyleSheet(
            "text-align: left; font-weight: bold; color: #89b4fa; "
            "font-size: 13px; padding: 4px 0; border: none;"
        )
        self._toggle_btn.clicked.connect(self._toggle_collapsed)
        header_row.addWidget(self._toggle_btn)
        header_row.addStretch()
        self._main_layout.addLayout(header_row)

        # Container for speaker rows (collapsible)
        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(8, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        self._main_layout.addWidget(self._rows_container)

    def set_speakers(self, segments, speaker_names=None):
        """Populate panel from transcript segments and optional existing names.

        Args:
            segments: list of TranscriptSegment
            speaker_names: dict of {speaker_id: name} or None
        """
        self._speaker_ids = _extract_speakers(segments)
        self._speaker_names = dict(speaker_names) if speaker_names else {}

        if not self._speaker_ids:
            self.hide()
            return

        self.show()
        self._toggle_btn.setText(f"\u25bc Speakers ({len(self._speaker_ids)} detected)")

        # Clear existing rows
        self._name_edits.clear()
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Build rows
        for i, speaker_id in enumerate(self._speaker_ids):
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 2, 0, 2)

            # Color swatch
            color = SPEAKER_COLORS[i % len(SPEAKER_COLORS)]
            swatch = QLabel("\u25cf")
            swatch.setStyleSheet(f"color: {color}; font-size: 16px;")
            swatch.setFixedWidth(20)
            row_layout.addWidget(swatch)

            # Speaker ID label
            id_label = QLabel(speaker_id)
            id_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
            id_label.setFixedWidth(100)
            row_layout.addWidget(id_label)

            # Arrow
            arrow = QLabel("\u2192")
            arrow.setStyleSheet("color: #585b70;")
            arrow.setFixedWidth(20)
            row_layout.addWidget(arrow)

            # Name edit
            name_edit = QLineEdit()
            name_edit.setPlaceholderText("Enter name...")
            name_edit.setMaximumHeight(28)
            existing_name = self._speaker_names.get(speaker_id, "")
            if existing_name:
                name_edit.setText(existing_name)
            name_edit.textChanged.connect(self._on_name_changed)
            row_layout.addWidget(name_edit)

            self._name_edits[speaker_id] = name_edit
            self._rows_layout.addWidget(row_widget)

    def get_speaker_names(self):
        """Return current speaker name mappings (only non-empty names)."""
        names = {}
        for speaker_id, edit in self._name_edits.items():
            name = edit.text().strip()
            if name:
                names[speaker_id] = name
        return names

    def focus_speaker(self, speaker_id):
        """Focus the name edit for the given speaker ID."""
        if speaker_id in self._name_edits:
            if self._collapsed:
                self._toggle_collapsed()
            self._name_edits[speaker_id].setFocus()
            self._name_edits[speaker_id].selectAll()

    def _on_name_changed(self, text):
        """Emit names_changed whenever any name field changes."""
        self.names_changed.emit(self.get_speaker_names())

    def _toggle_collapsed(self):
        self._collapsed = not self._collapsed
        self._rows_container.setVisible(not self._collapsed)
        arrow = "\u25b6" if self._collapsed else "\u25bc"
        count = len(self._speaker_ids)
        self._toggle_btn.setText(f"{arrow} Speakers ({count} detected)")
