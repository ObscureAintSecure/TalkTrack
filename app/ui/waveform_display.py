"""Rolling waveform display for live audio visualization."""

import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QFont
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
    """Dual scrolling waveform widget showing mic and system audio."""

    def __init__(self, seconds=5, sample_rate=16000, parent=None):
        super().__init__(parent)
        max_samples = seconds * sample_rate
        self._mic_buffer = WaveformRingBuffer(max_samples=max_samples)
        self._sys_buffer = WaveformRingBuffer(max_samples=max_samples)
        self._display_points = 300
        self.setMinimumHeight(90)
        self.setMaximumHeight(120)
        self.setVisible(False)

        self._paint_timer = QTimer(self)
        self._paint_timer.timeout.connect(self.update)
        self._paint_timer.setInterval(66)  # ~15fps

    def start(self):
        self._mic_buffer.clear()
        self._sys_buffer.clear()
        self.setVisible(True)
        self._paint_timer.start()

    def stop(self):
        self._paint_timer.stop()
        self.setVisible(False)
        self._mic_buffer.clear()
        self._sys_buffer.clear()

    def append_audio(self, chunk: np.ndarray):
        """Append microphone audio data."""
        self._mic_buffer.append(chunk)

    def append_system_audio(self, chunk: np.ndarray):
        """Append system/app audio data."""
        self._sys_buffer.append(chunk)

    def _draw_waveform(self, painter, data, color, x, y, w, h):
        """Draw a single waveform in the given rect."""
        mid_y = y + h / 2

        # Background
        painter.fillRect(int(x), int(y), int(w), int(h), QColor("#1e1e2e"))

        # Center line
        painter.setPen(QPen(QColor("#45475a"), 1))
        painter.drawLine(int(x), int(mid_y), int(x + w), int(mid_y))

        points = downsample_for_display(data, self._display_points)
        if len(points) == 0:
            return

        painter.setPen(QPen(QColor(color), 1.5))

        x_step = w / max(len(points) - 1, 1)
        max_amp = max(np.max(np.abs(points)), 0.001)
        scale = (h * 0.42) / max_amp

        for i in range(len(points) - 1):
            x1 = int(x + i * x_step)
            x2 = int(x + (i + 1) * x_step)
            y1 = int(mid_y - points[i] * scale)
            y2 = int(mid_y - points[i + 1] * scale)
            painter.drawLine(x1, y1, x2, y2)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        label_w = 28
        wave_w = w - label_w
        half_h = h / 2
        gap = 1

        mic_data = self._mic_buffer.get_data()
        sys_data = self._sys_buffer.get_data()

        mic_color = "#89b4fa"  # Blue
        sys_color = "#a6e3a1"  # Green

        # Draw mic waveform (top half)
        self._draw_waveform(
            painter, mic_data, mic_color,
            label_w, 0, wave_w, half_h - gap,
        )

        # Draw system waveform (bottom half)
        self._draw_waveform(
            painter, sys_data, sys_color,
            label_w, half_h + gap, wave_w, half_h - gap,
        )

        # Labels
        painter.fillRect(0, 0, label_w, h, QColor("#1e1e2e"))
        font = QFont()
        font.setPixelSize(9)
        painter.setFont(font)

        painter.setPen(QColor(mic_color))
        painter.drawText(2, 2, label_w - 4, int(half_h - gap),
                         Qt.AlignmentFlag.AlignCenter, "Mic")

        painter.setPen(QColor(sys_color))
        painter.drawText(2, int(half_h + gap), label_w - 4, int(half_h - gap),
                         Qt.AlignmentFlag.AlignCenter, "Sys")

        # Divider line between the two
        painter.setPen(QPen(QColor("#585b70"), 1))
        painter.drawLine(label_w, int(half_h), w, int(half_h))

        painter.end()
