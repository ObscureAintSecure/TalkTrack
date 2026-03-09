"""Real-time audio level meter widget with peak hold."""

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QLinearGradient
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QVBoxLayout


# Floor in dB — anything below this reads as silence
DB_FLOOR = -60.0


def compute_rms_db(audio_chunk: np.ndarray) -> float:
    """Compute RMS level in dB from a normalized [-1.0, 1.0] float audio chunk."""
    if audio_chunk.size == 0:
        return DB_FLOOR
    rms = np.sqrt(np.mean(audio_chunk.astype(np.float64) ** 2))
    if rms < 1e-10:
        return DB_FLOOR
    db = 20.0 * np.log10(rms)
    return max(db, DB_FLOOR)


def db_to_fraction(db: float) -> float:
    """Convert dB value to 0.0-1.0 fraction for display."""
    return max(0.0, min(1.0, (db - DB_FLOOR) / -DB_FLOOR))


class LevelBar(QWidget):
    """A single horizontal level bar with gradient coloring and peak hold."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._level = 0.0  # 0.0 to 1.0
        self._peak = 0.0
        self._peak_hold_frames = 0
        self.setMinimumHeight(12)
        self.setMaximumHeight(16)

    def reset(self):
        self._level = 0.0
        self._peak = 0.0
        self._peak_hold_frames = 0
        self.update()

    def set_level(self, fraction: float):
        self._level = max(0.0, min(1.0, fraction))
        # Peak hold: hold for ~30 frames (~1.5s at 20fps), then decay
        if self._level >= self._peak:
            self._peak = self._level
            self._peak_hold_frames = 30
        else:
            if self._peak_hold_frames > 0:
                self._peak_hold_frames -= 1
            else:
                self._peak = max(self._level, self._peak - 0.02)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # Background
        painter.fillRect(0, 0, w, h, QColor("#1e1e2e"))

        if w <= 0:
            painter.end()
            return

        # Level bar with gradient: green -> yellow -> red
        bar_width = int(w * self._level)
        if bar_width > 0:
            gradient = QLinearGradient(0, 0, w, 0)
            gradient.setColorAt(0.0, QColor("#a6e3a1"))   # green
            gradient.setColorAt(0.6, QColor("#f9e2af"))   # yellow
            gradient.setColorAt(1.0, QColor("#f38ba8"))   # red
            painter.fillRect(0, 0, bar_width, h, gradient)

        # Peak indicator (thin white line)
        peak_x = int(w * self._peak)
        if peak_x > 0 and self._peak > 0.01:
            painter.setPen(QColor("#cdd6f4"))
            painter.drawLine(peak_x, 0, peak_x, h)

        painter.end()


class LevelMeter(QWidget):
    """Dual-channel level meter (Mic + System)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(2)

        # Mic meter
        mic_row = QHBoxLayout()
        mic_row.setSpacing(4)
        mic_label = QLabel("Mic")
        mic_label.setFixedWidth(45)
        mic_label.setStyleSheet("color: #a6adc8; font-size: 11px;")
        mic_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._mic_bar = LevelBar()
        mic_row.addWidget(mic_label)
        mic_row.addWidget(self._mic_bar)
        layout.addLayout(mic_row)

        # System meter
        sys_row = QHBoxLayout()
        sys_row.setSpacing(4)
        sys_label = QLabel("System")
        sys_label.setFixedWidth(45)
        sys_label.setStyleSheet("color: #a6adc8; font-size: 11px;")
        sys_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._sys_bar = LevelBar()
        sys_row.addWidget(sys_label)
        sys_row.addWidget(self._sys_bar)
        layout.addLayout(sys_row)

    def update_mic_level(self, audio_chunk: np.ndarray):
        db = compute_rms_db(audio_chunk)
        self._mic_bar.set_level(db_to_fraction(db))

    def update_system_level(self, audio_chunk: np.ndarray):
        db = compute_rms_db(audio_chunk)
        self._sys_bar.set_level(db_to_fraction(db))

    def reset(self):
        self._mic_bar.reset()
        self._sys_bar.reset()
