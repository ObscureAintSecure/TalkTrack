"""Individual transcript segment row widget."""
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction


# Speaker colors — must match transcript_viewer.py and speaker_name_panel.py
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


def _format_time(seconds):
    """Format seconds as HH:MM:SS."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _display_speaker(speaker_id, speaker_names):
    """Return display name for a speaker, falling back to ID."""
    if not speaker_id:
        return ""
    if speaker_names and speaker_id in speaker_names and speaker_names[speaker_id]:
        return speaker_names[speaker_id]
    return speaker_id


class EditHistory:
    """Undo/redo stack for segment text edits."""

    def __init__(self, initial_text: str, max_depth: int = 20):
        self._stack = [initial_text]
        self._pos = 0
        self._max_depth = max_depth

    def current(self) -> str:
        return self._stack[self._pos]

    def original(self) -> str:
        return self._stack[0]

    def is_modified(self) -> bool:
        return self._pos > 0

    def can_undo(self) -> bool:
        return self._pos > 0

    def can_redo(self) -> bool:
        return self._pos < len(self._stack) - 1

    def push(self, text: str):
        self._stack = self._stack[:self._pos + 1]
        self._stack.append(text)
        self._pos += 1
        if len(self._stack) > self._max_depth + 1:
            trim = len(self._stack) - self._max_depth - 1
            self._stack = self._stack[trim:]
            self._pos -= trim

    def undo(self) -> str:
        if self.can_undo():
            self._pos -= 1
        return self.current()

    def redo(self) -> str:
        if self.can_redo():
            self._pos += 1
        return self.current()


class SegmentWidget(QWidget):
    """A single transcript segment row: [play] [timestamp] [speaker] [text].

    Supports:
    - Play button to trigger audio playback
    - Double-click text to edit inline
    - Right-click context menu with "Revert to Original"
    - Speaker label click to focus speaker name panel
    """

    play_requested = pyqtSignal(int)       # segment index
    stop_requested = pyqtSignal()
    text_edited = pyqtSignal(int, str)     # segment index, new text
    text_reverted = pyqtSignal(int)        # segment index
    speaker_clicked = pyqtSignal(str)      # speaker ID

    def __init__(self, index, segment, speaker_color="#cdd6f4",
                 speaker_name="", parent=None):
        super().__init__(parent)
        self._index = index
        self._segment = segment
        self._speaker_color = speaker_color
        self._speaker_name = speaker_name
        self._editing = False
        self._playing = False
        self._history = EditHistory(segment.text)
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        # Play button
        self.play_btn = QPushButton("\u25b6")
        self.play_btn.setObjectName("segmentPlayBtn")
        self.play_btn.setFixedSize(28, 28)
        self.play_btn.setStyleSheet(
            "QPushButton { font-size: 11px; border-radius: 14px; "
            "background-color: #313244; border: 1px solid #45475a; padding: 0; }"
            "QPushButton:hover { background-color: #45475a; }"
        )
        self.play_btn.clicked.connect(self._on_play_clicked)
        layout.addWidget(self.play_btn)

        # Timestamp
        start_ts = _format_time(self._segment.start)
        end_ts = _format_time(self._segment.end)
        self.timestamp_label = QLabel(f"[{start_ts} \u2192 {end_ts}]")
        self.timestamp_label.setStyleSheet(
            "color: #6c7086; font-family: Consolas; font-size: 11px;"
        )
        self.timestamp_label.setFixedWidth(160)
        layout.addWidget(self.timestamp_label)

        # Speaker label
        display_name = self._speaker_name or self._segment.speaker
        self.speaker_label = QLabel(f"{display_name}:" if display_name else "")
        self.speaker_label.setStyleSheet(
            f"color: {self._speaker_color}; font-weight: bold; font-size: 13px;"
        )
        if display_name:
            self.speaker_label.setFixedWidth(120)
            self.speaker_label.setCursor(Qt.CursorShape.PointingHandCursor)
            self.speaker_label.mousePressEvent = self._on_speaker_clicked
        else:
            self.speaker_label.setFixedWidth(0)
        layout.addWidget(self.speaker_label)

        # Text label (normal mode)
        self.text_label = QLabel(self._segment.text)
        self.text_label.setStyleSheet("color: #cdd6f4; font-size: 13px;")
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.text_label.mouseDoubleClickEvent = self._on_text_double_clicked
        self.text_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.text_label.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.text_label, 1)

        # Text edit (edit mode) — hidden by default
        self.text_edit = QLineEdit()
        self.text_edit.hide()
        self.text_edit.returnPressed.connect(self._finish_edit)
        layout.addWidget(self.text_edit, 1)

        # Edit indicator
        self.edit_indicator = QLabel("\u270e")  # pencil icon
        self.edit_indicator.setStyleSheet("color: #f9e2af; font-size: 12px;")
        self.edit_indicator.setFixedWidth(16)
        self.edit_indicator.setToolTip("This segment has been edited")
        self.edit_indicator.setVisible(bool(self._segment.original_text))
        layout.addWidget(self.edit_indicator)

    def update_speaker(self, speaker_names):
        """Update the displayed speaker name."""
        display = _display_speaker(self._segment.speaker, speaker_names)
        if display:
            self.speaker_label.setText(f"{display}:")
            self.speaker_label.setFixedWidth(120)
        else:
            self.speaker_label.setText("")
            self.speaker_label.setFixedWidth(0)

    def set_playing(self, playing):
        """Update play button state."""
        self._playing = playing
        self.play_btn.setText("\u23f9" if playing else "\u25b6")

    def _on_play_clicked(self):
        if self._playing:
            self.stop_requested.emit()
        else:
            self.play_requested.emit(self._index)

    def _on_speaker_clicked(self, event):
        if self._segment.speaker:
            self.speaker_clicked.emit(self._segment.speaker)

    def _on_text_double_clicked(self, event):
        self._start_edit()

    def _start_edit(self):
        if self._editing:
            return
        self._editing = True
        self.text_edit.setText(self.text_label.text())
        self.text_label.hide()
        self.text_edit.show()
        self.text_edit.setFocus()
        self.text_edit.selectAll()

    def _finish_edit(self):
        if not self._editing:
            return
        self._editing = False
        new_text = self.text_edit.text().strip()
        if new_text and new_text != self._history.current():
            self._history.push(new_text)
            self.text_label.setText(new_text)
            self.text_edited.emit(self._index, new_text)
            self.edit_indicator.setVisible(self._history.is_modified())
        self.text_edit.hide()
        self.text_label.show()

    def cancel_edit(self):
        """Cancel editing without saving."""
        if not self._editing:
            return
        self._editing = False
        self.text_edit.hide()
        self.text_label.show()

    def undo(self):
        if self._history.can_undo():
            text = self._history.undo()
            self.text_label.setText(text)
            self.edit_indicator.setVisible(self._history.is_modified())
            self.text_edited.emit(self._index, text)

    def redo(self):
        if self._history.can_redo():
            text = self._history.redo()
            self.text_label.setText(text)
            self.edit_indicator.setVisible(self._history.is_modified())
            self.text_edited.emit(self._index, text)

    def _show_context_menu(self, pos):
        menu = QMenu(self)

        edit_action = QAction("Edit Text", self)
        edit_action.triggered.connect(self._start_edit)
        menu.addAction(edit_action)

        if self._history.can_undo():
            undo_action = QAction("Undo", self)
            undo_action.triggered.connect(self.undo)
            menu.addAction(undo_action)

        if self._history.can_redo():
            redo_action = QAction("Redo", self)
            redo_action.triggered.connect(self.redo)
            menu.addAction(redo_action)

        if self._history.is_modified():
            revert_action = QAction("Revert to Original", self)
            revert_action.triggered.connect(self._revert_to_original)
            menu.addAction(revert_action)

        menu.exec(self.text_label.mapToGlobal(pos))

    def _revert_to_original(self):
        original = self._history.original()
        self._history = EditHistory(original)
        self.text_label.setText(original)
        self.edit_indicator.setVisible(False)
        self.text_reverted.emit(self._index)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._editing:
            self.cancel_edit()
        else:
            super().keyPressEvent(event)
