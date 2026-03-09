"""Search bar for recordings list sidebar."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QPushButton


class SearchBar(QWidget):
    """Search input with text/semantic mode toggle."""

    search_requested = pyqtSignal(str, bool)  # query, is_semantic
    cleared = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_semantic = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Search recordings...")
        self._input.returnPressed.connect(self._do_search)
        self._input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._input)

        self._mode_btn = QPushButton("Aa")
        self._mode_btn.setToolTip("Text search (click for semantic)")
        self._mode_btn.setFixedWidth(30)
        self._mode_btn.setCheckable(True)
        self._mode_btn.toggled.connect(self._toggle_mode)
        layout.addWidget(self._mode_btn)

    def _toggle_mode(self, checked):
        self._is_semantic = checked
        self._mode_btn.setText("AI" if checked else "Aa")
        self._mode_btn.setToolTip(
            "Semantic search" if checked else "Text search (click for semantic)"
        )

    def _do_search(self):
        query = self._input.text().strip()
        if query:
            self.search_requested.emit(query, self._is_semantic)

    def _on_text_changed(self, text):
        if not text.strip():
            self.cleared.emit()
