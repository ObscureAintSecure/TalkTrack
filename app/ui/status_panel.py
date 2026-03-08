"""Startup system status dialog showing dependency health."""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QWidget
)
from PyQt6.QtCore import Qt

from app.utils.dependency_checker import DependencyChecker


class StatusRow(QFrame):
    """A single status check row with icon, name, message, and optional action."""

    def __init__(self, check_result, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("statusRow")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)

        # Status icon
        if check_result["passed"]:
            icon_text = "\u2705"
        elif check_result["level"] == "warn":
            icon_text = "\u26a0\ufe0f"
        else:
            icon_text = "\u274c"

        icon_label = QLabel(icon_text)
        icon_label.setFixedWidth(30)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        # Name and message
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        name_label = QLabel(check_result["name"])
        name_label.setObjectName("statusName")
        name_font = name_label.font()
        name_font.setBold(True)
        name_label.setFont(name_font)
        text_layout.addWidget(name_label)

        msg_label = QLabel(check_result["message"])
        msg_label.setObjectName("statusMessage")
        msg_label.setWordWrap(True)
        text_layout.addWidget(msg_label)

        if check_result.get("action"):
            action_label = QLabel(check_result["action"])
            action_label.setObjectName("statusAction")
            action_label.setWordWrap(True)
            text_layout.addWidget(action_label)

        layout.addLayout(text_layout, 1)


class SystemStatusDialog(QDialog):
    """Dialog showing system dependency status."""

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("System Status")
        self.setMinimumSize(500, 400)
        self.setMaximumSize(600, 600)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        header = QLabel("System Status")
        header.setObjectName("sectionHeader")
        layout.addWidget(header)

        desc = QLabel("TalkTrack checks that all components are ready.")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        self.checks_layout = QVBoxLayout(scroll_content)
        self.checks_layout.setSpacing(6)
        self.checks_layout.setContentsMargins(0, 0, 0, 0)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)

        checker = DependencyChecker(config)
        results = checker.run_all_checks()

        for result in results:
            row = StatusRow(result)
            self.checks_layout.addWidget(row)

        self.checks_layout.addStretch()

        passed = sum(1 for r in results if r["passed"])
        total = len(results)
        critical_fails = [r for r in results if not r["passed"] and r["level"] == "critical"]

        if critical_fails:
            summary_text = f"{passed}/{total} checks passed. {len(critical_fails)} critical issue(s)."
            summary_style = "color: #f38ba8;"
        elif passed < total:
            summary_text = f"{passed}/{total} checks passed. Optional features may be limited."
            summary_style = "color: #fab387;"
        else:
            summary_text = f"All {total} checks passed. TalkTrack is fully configured!"
            summary_style = "color: #a6e3a1;"

        summary = QLabel(summary_text)
        summary.setStyleSheet(summary_style)
        summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(summary)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setMinimumWidth(100)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    @staticmethod
    def should_show_on_startup(config=None):
        checker = DependencyChecker(config)
        results = checker.run_all_checks()
        critical_fails = [r for r in results if not r["passed"] and r["level"] == "critical"]
        return len(critical_fails) > 0
