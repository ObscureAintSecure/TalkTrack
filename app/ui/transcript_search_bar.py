"""Find/replace toolbar for transcript viewer."""

import re
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton, QLabel, QCheckBox,
)


def find_matches(pattern, texts, case_sensitive=False, use_regex=False):
    """Find all matches across a list of text strings.
    Returns list of (segment_index, start_char, end_char) tuples.
    """
    matches = []
    flags = 0 if case_sensitive else re.IGNORECASE
    if not use_regex:
        pattern = re.escape(pattern)
    try:
        compiled = re.compile(pattern, flags)
    except re.error:
        return []
    for i, text in enumerate(texts):
        for m in compiled.finditer(text):
            matches.append((i, m.start(), m.end()))
    return matches


class TranscriptSearchBar(QWidget):
    """Collapsible find/replace bar for transcript segments."""

    navigate_to_match = pyqtSignal(int, int, int)  # segment_idx, start, end
    replace_requested = pyqtSignal(int, str, int, int)  # segment_idx, new_text, start, end
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._matches = []
        self._current_match = -1
        self._texts = []
        self._setup_ui()
        self.setVisible(False)

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Find...")
        self.find_input.setMinimumWidth(150)
        self.find_input.returnPressed.connect(self.find_next)
        self.find_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.find_input)

        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Replace...")
        self.replace_input.setMinimumWidth(150)
        layout.addWidget(self.replace_input)

        self.case_cb = QCheckBox("Aa")
        self.case_cb.setToolTip("Case sensitive")
        self.case_cb.toggled.connect(self._on_text_changed)
        layout.addWidget(self.case_cb)

        self.regex_cb = QCheckBox(".*")
        self.regex_cb.setToolTip("Use regex")
        self.regex_cb.toggled.connect(self._on_text_changed)
        layout.addWidget(self.regex_cb)

        self.prev_btn = QPushButton("<")
        self.prev_btn.setFixedWidth(30)
        self.prev_btn.clicked.connect(self.find_prev)
        layout.addWidget(self.prev_btn)

        self.next_btn = QPushButton(">")
        self.next_btn.setFixedWidth(30)
        self.next_btn.clicked.connect(self.find_next)
        layout.addWidget(self.next_btn)

        self.match_label = QLabel("")
        self.match_label.setStyleSheet("color: #a6adc8; font-size: 11px;")
        layout.addWidget(self.match_label)

        self.replace_btn = QPushButton("Replace")
        self.replace_btn.clicked.connect(self._do_replace)
        layout.addWidget(self.replace_btn)

        close_btn = QPushButton("X")
        close_btn.setFixedWidth(24)
        close_btn.clicked.connect(self.hide_bar)
        layout.addWidget(close_btn)

    def show_bar(self):
        self.setVisible(True)
        self.find_input.setFocus()
        self.find_input.selectAll()

    def hide_bar(self):
        self.setVisible(False)
        self._matches = []
        self._current_match = -1
        self.closed.emit()

    def set_texts(self, texts):
        self._texts = texts
        self._on_text_changed()

    def _on_text_changed(self):
        query = self.find_input.text()
        if not query:
            self._matches = []
            self._current_match = -1
            self.match_label.setText("")
            return
        self._matches = find_matches(
            query, self._texts,
            case_sensitive=self.case_cb.isChecked(),
            use_regex=self.regex_cb.isChecked(),
        )
        if self._matches:
            self._current_match = 0
            self._navigate_current()
        else:
            self._current_match = -1
        self._update_label()

    def find_next(self):
        if not self._matches:
            return
        self._current_match = (self._current_match + 1) % len(self._matches)
        self._navigate_current()
        self._update_label()

    def find_prev(self):
        if not self._matches:
            return
        self._current_match = (self._current_match - 1) % len(self._matches)
        self._navigate_current()
        self._update_label()

    def _navigate_current(self):
        if 0 <= self._current_match < len(self._matches):
            seg_idx, start, end = self._matches[self._current_match]
            self.navigate_to_match.emit(seg_idx, start, end)

    def _update_label(self):
        if not self._matches:
            query = self.find_input.text()
            self.match_label.setText("No matches" if query else "")
        else:
            self.match_label.setText(f"{self._current_match + 1} of {len(self._matches)}")

    def _do_replace(self):
        if not self._matches or self._current_match < 0:
            return
        seg_idx, start, end = self._matches[self._current_match]
        new_text = self.replace_input.text()
        self.replace_requested.emit(seg_idx, new_text, start, end)
        self._on_text_changed()
