"""Meeting summary display panel."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout, QLabel,
    QApplication,
)


class SummaryPanel(QWidget):
    regenerate_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._status = QLabel("No summary generated yet.")
        self._status.setStyleSheet("color: #a6adc8; padding: 8px;")
        layout.addWidget(self._status)

        self._text = QTextEdit()
        self._text.setReadOnly(False)
        self._text.setStyleSheet(
            "QTextEdit { background-color: #1e1e2e; color: #cdd6f4; "
            "border: none; padding: 8px; font-size: 13px; }"
        )
        self._text.setVisible(False)
        layout.addWidget(self._text)

        btn_row = QHBoxLayout()
        self._copy_btn = QPushButton("Copy")
        self._copy_btn.clicked.connect(self._copy)
        self._copy_btn.setVisible(False)
        btn_row.addWidget(self._copy_btn)

        self._regen_btn = QPushButton("Regenerate")
        self._regen_btn.clicked.connect(self.regenerate_requested.emit)
        self._regen_btn.setVisible(False)
        btn_row.addWidget(self._regen_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

    def set_summary(self, text):
        self._text.setMarkdown(text)
        self._text.setVisible(True)
        self._copy_btn.setVisible(True)
        self._regen_btn.setVisible(True)
        self._status.setVisible(False)

    def set_loading(self):
        self._status.setText("Generating summary...")
        self._status.setVisible(True)
        self._text.setVisible(False)

    def get_text(self):
        return self._text.toPlainText()

    def _copy(self):
        QApplication.clipboard().setText(self._text.toPlainText())
