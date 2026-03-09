"""Rolling waveform display for live audio visualization."""

import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class WaveformRingBuffer:
    """Fixed-size ring buffer for audio samples."""

    def __init__(self, max_samples=80000):
        self._max = max_samples
        self._buffer = np.zeros(max_samples, dtype=np.float32)
        self._write_pos = 0
        self._count = 0

    def append(self, chunk: np.ndarray):
        flat = chunk.flatten()
        n = len(flat)
        if n == 0:
            return
        if n >= self._max:
            flat = flat[-self._max:]
            n = self._max
            self._buffer[:] = flat
            self._write_pos = 0
            self._count = self._max
            return

        end = self._write_pos + n
        if end <= self._max:
            self._buffer[self._write_pos:end] = flat
        else:
            first = self._max - self._write_pos
            self._buffer[self._write_pos:] = flat[:first]
            self._buffer[:n - first] = flat[first:]
        self._write_pos = end % self._max
        self._count = min(self._count + n, self._max)

    def get_data(self) -> np.ndarray:
        if self._count == 0:
            return np.array([], dtype=np.float32)
        if self._count < self._max:
            return self._buffer[:self._count].copy()
        return np.roll(self._buffer, -self._write_pos)[:self._count].copy()

    def clear(self):
        self._write_pos = 0
        self._count = 0


def downsample_for_display(data: np.ndarray, target_points: int = 200) -> np.ndarray:
    """Downsample audio data to target points using peak envelope."""
    if len(data) == 0:
        return np.array([], dtype=np.float32)
    if len(data) <= target_points:
        return data.copy()
    chunk_size = len(data) // target_points
    result = np.zeros(target_points, dtype=np.float32)
    for i in range(target_points):
        start = i * chunk_size
        end = start + chunk_size
        segment = data[start:end]
        result[i] = np.max(np.abs(segment)) if len(segment) > 0 else 0.0
    return result


class WaveformDisplay(QWidget):
    """Scrolling waveform widget showing recent audio."""

    def __init__(self, seconds=5, sample_rate=16000, parent=None):
        super().__init__(parent)
        self._buffer = WaveformRingBuffer(max_samples=seconds * sample_rate)
        self._display_points = 300
        self.setMinimumHeight(60)
        self.setMaximumHeight(80)
        self.setVisible(False)

        self._paint_timer = QTimer(self)
        self._paint_timer.timeout.connect(self.update)
        self._paint_timer.setInterval(66)  # ~15fps

    def start(self):
        self._buffer.clear()
        self.setVisible(True)
        self._paint_timer.start()

    def stop(self):
        self._paint_timer.stop()
        self.setVisible(False)
        self._buffer.clear()

    def append_audio(self, chunk: np.ndarray):
        self._buffer.append(chunk)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        mid_y = h / 2

        painter.fillRect(0, 0, w, h, QColor("#1e1e2e"))

        painter.setPen(QPen(QColor("#45475a"), 1))
        painter.drawLine(0, int(mid_y), w, int(mid_y))

        data = self._buffer.get_data()
        if len(data) == 0:
            painter.end()
            return

        points = downsample_for_display(data, self._display_points)
        if len(points) == 0:
            painter.end()
            return

        pen = QPen(QColor("#89b4fa"), 1.5)
        painter.setPen(pen)

        x_step = w / max(len(points) - 1, 1)
        max_amp = max(np.max(np.abs(points)), 0.001)
        scale = (h * 0.45) / max_amp

        for i in range(len(points) - 1):
            x1 = int(i * x_step)
            x2 = int((i + 1) * x_step)
            y1 = int(mid_y - points[i] * scale)
            y2 = int(mid_y - points[i + 1] * scale)
            painter.drawLine(x1, y1, x2, y2)

        painter.end()
