"""Asks whether to stop the recording once the meeting app left the call."""
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

# Stop on its own if nobody answers: the usual reason the question comes up
# is that the user already walked away from a finished meeting.
DEFAULT_COUNTDOWN_SECONDS = 60


def format_apps(apps):
    """"Microsoft Teams" / "Zoom and Google Chrome" / "A, B and C"."""
    apps = list(apps)
    if len(apps) <= 1:
        return apps[0] if apps else "The meeting app"
    return ", ".join(apps[:-1]) + " and " + apps[-1]


class MeetingEndDialog(QDialog):
    """Stay-on-top prompt with a countdown that stops the recording.

    Not modal: the meeting app is usually in front, and the question must
    not block TalkTrack's own window either.
    """

    stop_requested = pyqtSignal()
    keep_requested = pyqtSignal()

    def __init__(self, apps, countdown_seconds=DEFAULT_COUNTDOWN_SECONDS, parent=None):
        super().__init__(parent)
        self._remaining = countdown_seconds
        self._answered = False
        self.setWindowTitle("TalkTrack - Meeting ended?")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setModal(False)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        message = QLabel(
            f"<b>{format_apps(apps)}</b> stopped using the microphone.<br>"
            "Did the meeting end? TalkTrack is still recording."
        )
        message.setWordWrap(True)
        layout.addWidget(message)

        self._countdown_label = QLabel()
        self._countdown_label.setStyleSheet("color: #a6adc8;")
        layout.addWidget(self._countdown_label)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.keep_btn = QPushButton("Keep recording")
        self.keep_btn.clicked.connect(self._keep)
        buttons.addWidget(self.keep_btn)
        self.stop_btn = QPushButton("Stop recording")
        self.stop_btn.setDefault(True)
        self.stop_btn.clicked.connect(self._stop)
        buttons.addWidget(self.stop_btn)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._update_countdown()
        self._timer.start()

    def _update_countdown(self):
        self._countdown_label.setText(
            f"Stopping automatically in {self._remaining} s."
        )

    def _tick(self):
        self._remaining -= 1
        if self._remaining <= 0:
            self._stop()
            return
        self._update_countdown()

    def _stop(self):
        self._answer(self.stop_requested)

    def _keep(self):
        self._answer(self.keep_requested)

    def _answer(self, signal):
        if self._answered:
            return
        self._answered = True
        self._timer.stop()
        signal.emit()
        self.done(0)  # done(), not close(): close() would come back through reject()

    def reject(self):
        """Esc or the close button: keep recording, the safe answer."""
        self._keep()

    def dismiss(self):
        """Close without answering (the recording already stopped)."""
        self._answered = True
        self._timer.stop()
        self.done(0)
