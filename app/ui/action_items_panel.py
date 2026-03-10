"""Action items display panel."""

import json
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QPushButton, QScrollArea,
)


class ActionItemWidget(QWidget):
    toggled = pyqtSignal(int, bool)

    def __init__(self, index, item, parent=None):
        super().__init__(parent)
        self._index = index
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self._checkbox = QCheckBox()
        self._checkbox.toggled.connect(lambda checked: self.toggled.emit(index, checked))
        layout.addWidget(self._checkbox)

        text = item.get("task", "")
        assignee = item.get("assignee", "")
        deadline = item.get("deadline", "")

        label_parts = [text]
        if assignee:
            label_parts.append(f"({assignee})")
        if deadline:
            label_parts.append(f"- {deadline}")

        label = QLabel(" ".join(label_parts))
        label.setWordWrap(True)
        label.setStyleSheet("color: #cdd6f4; font-size: 13px;")
        layout.addWidget(label, 1)


class ActionItemsPanel(QWidget):
    regenerate_requested = pyqtSignal()
    items_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._status = QLabel("No action items extracted yet.")
        self._status.setStyleSheet("color: #a6adc8; padding: 8px;")
        layout.addWidget(self._status)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setVisible(False)
        self._container = QWidget()
        self._items_layout = QVBoxLayout(self._container)
        self._items_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll)

        btn_row = QHBoxLayout()
        self._gen_btn = QPushButton("Extract Action Items")
        self._gen_btn.clicked.connect(self.regenerate_requested.emit)
        self._gen_btn.setVisible(False)
        btn_row.addWidget(self._gen_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def set_items(self, items):
        self._items = items
        while self._items_layout.count():
            item = self._items_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, item_data in enumerate(items):
            widget = ActionItemWidget(i, item_data)
            widget.toggled.connect(self._on_toggled)
            self._items_layout.addWidget(widget)

        self._items_layout.addStretch()
        self._scroll.setVisible(True)
        self._gen_btn.setText("Regenerate")
        self._gen_btn.setVisible(True)
        self._status.setVisible(False)

    def clear(self):
        """Reset to initial empty state."""
        self._items = []
        while self._items_layout.count():
            item = self._items_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._scroll.setVisible(False)
        self._gen_btn.setVisible(False)
        self._status.setText("No action items extracted yet.")
        self._status.setVisible(True)

    def set_ready(self):
        """Show generate button when a transcript is available but no items yet."""
        if not self._scroll.isVisible():
            self._gen_btn.setText("Extract Action Items")
            self._gen_btn.setVisible(True)

    def set_loading(self):
        self._status.setText("Extracting action items...")
        self._status.setVisible(True)
        self._gen_btn.setVisible(False)
        self._scroll.setVisible(False)

    def _on_toggled(self, index, checked):
        if 0 <= index < len(self._items):
            self._items[index]["completed"] = checked
            self.items_changed.emit(self._items)

    def get_items(self):
        return self._items
