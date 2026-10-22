"""System tray icon for TalkTrack.

Pure helpers are module-level and unit-testable. The Qt widget class (TrayIcon)
comes in a later task and will compose them with QSystemTrayIcon.
"""
from app.recording.recorder import RecordingState

from pathlib import Path

from PyQt6.QtCore import pyqtSignal, QObject
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon


def format_tray_tooltip(state, elapsed_seconds):
    """Build the tray icon tooltip for a given recording state and elapsed time."""
    if state == RecordingState.RECORDING:
        return f"TalkTrack \u2014 Recording {_format_elapsed(elapsed_seconds)}"
    if state == RecordingState.PAUSED:
        return f"TalkTrack \u2014 Paused {_format_elapsed(elapsed_seconds)}"
    return "TalkTrack"


def _format_elapsed(seconds):
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def tray_action_visibility(state):
    """Map of tray menu action visibility keyed by action name.

    Returns dict with keys: record, pause, resume, stop.
    """
    return {
        "record": state == RecordingState.IDLE,
        "pause": state == RecordingState.RECORDING,
        "resume": state == RecordingState.PAUSED,
        "stop": state in (RecordingState.RECORDING, RecordingState.PAUSED),
    }


def resolve_overlay(has_success, has_error):
    """Overlay color for pending notifications. Errors win over successes."""
    if has_error:
        return "red"
    if has_success:
        return "green"
    return None


_ICON_PATH = Path(__file__).parent.parent.parent / "resources" / "talktrack.ico"

_DOT_COLORS = {
    "green": QColor("#a6e3a1"),
    "red": QColor("#f38ba8"),
}


class TrayIcon(QObject):
    """System tray icon wrapper.

    Emits signals for menu actions; owner (MainWindow) wires them to the
    same slots as the main recording controls.
    """

    show_requested = pyqtSignal()
    record_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._base_icon = QIcon(str(_ICON_PATH))
        self._current_overlay = None

        self._tray = QSystemTrayIcon(self._base_icon, parent)
        self._tray.setToolTip("TalkTrack")
        self._tray.activated.connect(self._on_activated)

        self._menu = QMenu()
        self._action_show = QAction("Show TalkTrack", self._menu)
        self._action_show.triggered.connect(self.show_requested)
        self._menu.addAction(self._action_show)
        self._menu.addSeparator()

        self._action_record = QAction("Record", self._menu)
        self._action_record.triggered.connect(self.record_requested)
        self._action_pause = QAction("Pause", self._menu)
        self._action_pause.triggered.connect(self.pause_requested)
        self._action_resume = QAction("Resume", self._menu)
        self._action_resume.triggered.connect(self.resume_requested)
        self._action_stop = QAction("Stop", self._menu)
        self._action_stop.triggered.connect(self.stop_requested)
        for a in (self._action_record, self._action_pause, self._action_resume, self._action_stop):
            self._menu.addAction(a)

        self._menu.addSeparator()
        self._action_quit = QAction("Quit", self._menu)
        self._action_quit.triggered.connect(self.quit_requested)
        self._menu.addAction(self._action_quit)

        self._tray.setContextMenu(self._menu)
        self.set_state(RecordingState.IDLE, 0)

    def is_supported(self):
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self):
        self._tray.show()

    def hide(self):
        self._tray.hide()

    def set_state(self, state, elapsed_seconds):
        """Update tooltip and menu visibility for the current recording state."""
        self._tray.setToolTip(format_tray_tooltip(state, elapsed_seconds))
        vis = tray_action_visibility(state)
        self._action_record.setVisible(vis["record"])
        self._action_pause.setVisible(vis["pause"])
        self._action_resume.setVisible(vis["resume"])
        self._action_stop.setVisible(vis["stop"])

    def set_overlay(self, color):
        """Apply an overlay dot. color in {None, 'green', 'red'}."""
        if color == self._current_overlay:
            return
        self._current_overlay = color
        if color is None:
            self._tray.setIcon(self._base_icon)
        else:
            self._tray.setIcon(self._compose_icon_with_dot(_DOT_COLORS[color]))

    def show_hint_balloon(self):
        """One-time welcome balloon shown on first tray hide."""
        self._tray.showMessage(
            "TalkTrack is still running",
            "Right-click the tray icon for options. Disable this in Settings > General.",
            QSystemTrayIcon.MessageIcon.Information,
            5000,
        )

    def show_message(self, title, message, msecs=10000):
        """A tray notification (shows even when the window is hidden)."""
        self._tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, msecs)

    def _on_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_requested.emit()

    def _compose_icon_with_dot(self, color):
        """Return a QIcon with a colored dot overlaid on the base icon."""
        size = 64
        pixmap = self._base_icon.pixmap(size, size)
        canvas = QPixmap(pixmap)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        diameter = int(size * 0.4)
        margin = 2
        x = size - diameter - margin
        y = size - diameter - margin
        painter.setPen(QPen(QColor("#1e1e2e"), 1))
        painter.setBrush(color)
        painter.drawEllipse(x, y, diameter, diameter)
        painter.end()
        return QIcon(canvas)
