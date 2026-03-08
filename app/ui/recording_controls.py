from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont

from app.recording.recorder import RecordingState


class RecordingControls(QWidget):
    """Recording control buttons and timer display."""

    record_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._blink_state = True
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._toggle_indicator)
        self.set_state(RecordingState.IDLE)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Timer row
        timer_row = QHBoxLayout()

        self.recording_indicator = QLabel("")
        self.recording_indicator.setObjectName("recordingIndicator")
        self.recording_indicator.setFixedWidth(30)
        self.recording_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timer_row.addWidget(self.recording_indicator)

        self.timer_label = QLabel("00:00:00")
        self.timer_label.setObjectName("timerLabel")
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timer_row.addWidget(self.timer_label)

        timer_row.addStretch()
        layout.addLayout(timer_row)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.record_btn = QPushButton("Record")
        self.record_btn.setObjectName("recordButton")
        self.record_btn.clicked.connect(self.record_clicked.emit)
        btn_row.addWidget(self.record_btn)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setObjectName("pauseButton")
        self.pause_btn.clicked.connect(self.pause_clicked.emit)
        btn_row.addWidget(self.pause_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("stopButton")
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        btn_row.addWidget(self.stop_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

    def set_state(self, state):
        if state == RecordingState.IDLE:
            self.record_btn.setEnabled(True)
            self.record_btn.setText("Record")
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.recording_indicator.setText("")
            self._blink_timer.stop()
        elif state == RecordingState.RECORDING:
            self.record_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.pause_btn.setText("Pause")
            self.stop_btn.setEnabled(True)
            self._blink_timer.start(500)
        elif state == RecordingState.PAUSED:
            self.record_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.pause_btn.setText("Resume")
            self.stop_btn.setEnabled(True)
            self.recording_indicator.setText("||")
            self._blink_timer.stop()
        elif state == RecordingState.STOPPING:
            self.record_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.recording_indicator.setText("")
            self._blink_timer.stop()

    def update_time(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        self.timer_label.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def _toggle_indicator(self):
        self._blink_state = not self._blink_state
        self.recording_indicator.setText("\u25cf" if self._blink_state else "")

    def reset_timer(self):
        self.timer_label.setText("00:00:00")
