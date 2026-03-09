"""Chat panel for asking questions about transcripts."""

import json
from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QLabel, QScrollArea,
)


class ChatMessage(QWidget):
    def __init__(self, role, content, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        label = QLabel(content)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        if role == "user":
            label.setStyleSheet(
                "background-color: #313244; color: #cdd6f4; "
                "padding: 8px; border-radius: 8px; font-size: 13px;"
            )
        else:
            label.setStyleSheet(
                "background-color: #1e1e2e; color: #cdd6f4; "
                "padding: 8px; border-radius: 8px; font-size: 13px;"
            )

        layout.addWidget(label)


class ChatWorker(QThread):
    response_ready = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, provider, context, prompt):
        super().__init__()
        self._provider = provider
        self._context = context
        self._prompt = prompt

    def run(self):
        try:
            result = self._provider.complete(self._prompt, self._context)
            self.response_ready.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class ChatPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._history = []
        self._context = ""
        self._provider = None
        self._worker = None
        self._session_dir = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._no_provider_label = QLabel(
            "AI provider not configured. Go to Settings > AI Assistant to set up."
        )
        self._no_provider_label.setStyleSheet("color: #a6adc8; padding: 16px;")
        self._no_provider_label.setWordWrap(True)
        layout.addWidget(self._no_provider_label)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setVisible(False)
        self._messages_container = QWidget()
        self._messages_layout = QVBoxLayout(self._messages_container)
        self._messages_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._messages_container)
        layout.addWidget(self._scroll, 1)

        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Ask about this recording...")
        self._input.returnPressed.connect(self._send_message)
        input_row.addWidget(self._input)

        self._send_btn = QPushButton("Send")
        self._send_btn.clicked.connect(self._send_message)
        input_row.addWidget(self._send_btn)

        layout.addLayout(input_row)

    def set_provider(self, provider):
        self._provider = provider
        has_provider = provider is not None
        self._no_provider_label.setVisible(not has_provider)
        self._scroll.setVisible(has_provider)

    def set_context(self, context):
        self._context = context

    def set_session_dir(self, session_dir):
        self._session_dir = session_dir
        self._load_history()

    def clear_chat(self):
        self._history = []
        while self._messages_layout.count():
            item = self._messages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _send_message(self):
        text = self._input.text().strip()
        if not text or not self._provider:
            return

        self._input.clear()
        self._add_message("user", text)

        from app.ai.chat import format_chat_prompt
        prompt = format_chat_prompt(text, self._history[:-1])

        self._send_btn.setEnabled(False)
        self._worker = ChatWorker(self._provider, self._context, prompt)
        self._worker.response_ready.connect(self._on_response)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_response(self, response):
        self._add_message("assistant", response)
        self._send_btn.setEnabled(True)
        self._save_history()

    def _on_error(self, error):
        self._add_message("assistant", f"Error: {error}")
        self._send_btn.setEnabled(True)

    def _add_message(self, role, content):
        self._history.append({"role": role, "content": content})
        widget = ChatMessage(role, content)
        self._messages_layout.addWidget(widget)
        self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        )

    def _save_history(self):
        if not self._session_dir:
            return
        path = Path(self._session_dir) / "chat_history.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._history, f, indent=2)

    def _load_history(self):
        self.clear_chat()
        if not self._session_dir:
            return
        path = Path(self._session_dir) / "chat_history.json"
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                history = json.load(f)
            for msg in history:
                self._add_message(msg["role"], msg["content"])
        except (json.JSONDecodeError, OSError):
            pass
