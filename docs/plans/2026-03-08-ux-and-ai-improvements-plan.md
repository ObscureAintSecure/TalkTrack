# TalkTrack UX & AI Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add UX refinements (audio meters, waveform, transcript editing) and AI superpowers (summaries, action items, search, chat) to TalkTrack.

**Architecture:** Phase 1 adds three UX features with no new dependencies. Phase 2 introduces an AI provider abstraction (`app/ai/`) that all four AI features plug into, supporting both local models and cloud APIs. A Buy Me a Coffee integration rounds out the work.

**Tech Stack:** PyQt6, numpy, QPainter (Phase 1); anthropic SDK, openai SDK, llama-cpp-python, sentence-transformers (Phase 2)

---

## Task 1: Audio Level Meter Widget

**Files:**
- Create: `app/ui/level_meter.py`
- Create: `tests/test_level_meter.py`

**Step 1: Write the failing tests**

```python
# tests/test_level_meter.py
import unittest
import numpy as np


class TestRMSCalculation(unittest.TestCase):
    def test_rms_of_silence(self):
        from app.ui.level_meter import compute_rms_db
        silence = np.zeros(1600, dtype=np.float32)
        db = compute_rms_db(silence)
        self.assertEqual(db, -60.0)  # Floor value

    def test_rms_of_full_scale(self):
        from app.ui.level_meter import compute_rms_db
        full = np.ones(1600, dtype=np.float32)
        db = compute_rms_db(full)
        self.assertAlmostEqual(db, 0.0, places=1)

    def test_rms_of_half_scale(self):
        from app.ui.level_meter import compute_rms_db
        half = np.full(1600, 0.5, dtype=np.float32)
        db = compute_rms_db(half)
        self.assertAlmostEqual(db, -6.0, delta=0.2)

    def test_rms_clamps_to_floor(self):
        from app.ui.level_meter import compute_rms_db
        tiny = np.full(1600, 0.0001, dtype=np.float32)
        db = compute_rms_db(tiny)
        self.assertEqual(db, -60.0)

    def test_db_to_fraction(self):
        from app.ui.level_meter import db_to_fraction
        self.assertAlmostEqual(db_to_fraction(0.0), 1.0)
        self.assertAlmostEqual(db_to_fraction(-60.0), 0.0)
        self.assertAlmostEqual(db_to_fraction(-30.0), 0.5, delta=0.01)


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_level_meter.py -v`
Expected: FAIL with ImportError

**Step 3: Implement the LevelMeter widget**

```python
# app/ui/level_meter.py
"""Real-time audio level meter widget with peak hold."""

import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QLinearGradient
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QVBoxLayout


# Floor in dB — anything below this reads as silence
DB_FLOOR = -60.0


def compute_rms_db(audio_chunk: np.ndarray) -> float:
    """Compute RMS level in dB from a numpy audio chunk."""
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
        self._mic_bar.set_level(0.0)
        self._mic_bar._peak = 0.0
        self._sys_bar.set_level(0.0)
        self._sys_bar._peak = 0.0
        self._mic_bar.update()
        self._sys_bar.update()
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_level_meter.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add app/ui/level_meter.py tests/test_level_meter.py
git commit -m "feat: add audio level meter widget with RMS computation"
```

---

## Task 2: Wire Level Meters Into Audio Capture Pipeline

**Files:**
- Modify: `app/recording/audio_capture.py` (AudioStream — add level signal callback)
- Modify: `app/main_window.py` (add LevelMeter to left panel, connect signals)
- Modify: `app/recording/recorder.py` (forward level data from capture to UI)

**Step 1: Add level callback to AudioStream**

In `app/recording/audio_capture.py`, modify `AudioStream.__init__` to accept an optional `level_callback`:

```python
def __init__(self, device_index, sample_rate=16000, channels=1,
             is_loopback=False, level_callback=None):
    # ... existing init ...
    self._level_callback = level_callback
```

In `_audio_callback`, after appending chunk, call the level callback:

```python
def _audio_callback(self, indata, frames, time_info, status):
    if status:
        print(f"Audio stream status: {status}")
    if self._recording and not self._paused:
        self._buffer.put(indata.copy())
        self._all_chunks.append(indata.copy())
        if self._level_callback:
            self._level_callback(indata.copy())
```

**Step 2: Add level signals to Recorder**

In `app/recording/recorder.py`, add two new signals to the `Recorder` class:

```python
mic_level = pyqtSignal(object)     # numpy array
system_level = pyqtSignal(object)  # numpy array
```

When creating AudioStream instances in `DualAudioCapture`, pass level callbacks that emit these signals. Add a `set_level_callbacks` method to `DualAudioCapture`:

```python
def set_level_callbacks(self, mic_callback=None, system_callback=None):
    self._mic_level_callback = mic_callback
    self._system_level_callback = system_callback
```

Pass these callbacks when creating streams in `start()`:

```python
if self.mic_device is not None:
    self.mic_stream = AudioStream(
        device_index=self.mic_device,
        sample_rate=self.sample_rate,
        channels=1,
        is_loopback=False,
        level_callback=self._mic_level_callback,
    )
```

In `Recorder.start_recording()`, after creating `DualAudioCapture`, set the callbacks:

```python
self._capture.set_level_callbacks(
    mic_callback=lambda data: self.mic_level.emit(data),
    system_callback=lambda data: self.system_level.emit(data),
)
```

**Step 3: Add LevelMeter to MainWindow**

In `app/main_window.py`, import `LevelMeter` and add it to the left panel layout between the source selector and recording controls:

```python
from app.ui.level_meter import LevelMeter

# In _setup_ui, after source_selector:
self.level_meter = LevelMeter()
left_layout.addWidget(self.level_meter)
# Then recording_controls as before
```

Connect in `_connect_signals`:

```python
self.recorder.mic_level.connect(self.level_meter.update_mic_level)
self.recorder.system_level.connect(self.level_meter.update_system_level)
```

Reset meters when recording stops (in `_on_state_changed`):

```python
if state == RecordingState.IDLE:
    self.level_meter.reset()
```

**Step 4: Manual test**

Run the app, start a recording with mic selected, verify meters animate. Stop recording, verify meters reset.

**Step 5: Commit**

```bash
git add app/recording/audio_capture.py app/recording/recorder.py app/main_window.py
git commit -m "feat: wire audio level meters into recording pipeline"
```

---

## Task 3: Live Waveform Display Widget

**Files:**
- Create: `app/ui/waveform_display.py`
- Create: `tests/test_waveform_display.py`

**Step 1: Write the failing tests**

```python
# tests/test_waveform_display.py
import unittest
import numpy as np


class TestWaveformBuffer(unittest.TestCase):
    def test_ring_buffer_append(self):
        from app.ui.waveform_display import WaveformRingBuffer
        buf = WaveformRingBuffer(max_samples=100)
        chunk = np.ones(50, dtype=np.float32) * 0.5
        buf.append(chunk)
        data = buf.get_data()
        self.assertEqual(len(data), 50)
        self.assertAlmostEqual(data[-1], 0.5)

    def test_ring_buffer_wraps(self):
        from app.ui.waveform_display import WaveformRingBuffer
        buf = WaveformRingBuffer(max_samples=100)
        # Add 150 samples — should keep last 100
        chunk = np.arange(150, dtype=np.float32)
        buf.append(chunk)
        data = buf.get_data()
        self.assertEqual(len(data), 100)
        self.assertAlmostEqual(data[-1], 149.0)
        self.assertAlmostEqual(data[0], 50.0)

    def test_ring_buffer_multiple_appends(self):
        from app.ui.waveform_display import WaveformRingBuffer
        buf = WaveformRingBuffer(max_samples=100)
        for i in range(5):
            chunk = np.full(30, float(i), dtype=np.float32)
            buf.append(chunk)
        data = buf.get_data()
        self.assertEqual(len(data), 100)
        # Last 30 should be 4.0
        self.assertAlmostEqual(data[-1], 4.0)

    def test_ring_buffer_clear(self):
        from app.ui.waveform_display import WaveformRingBuffer
        buf = WaveformRingBuffer(max_samples=100)
        buf.append(np.ones(50, dtype=np.float32))
        buf.clear()
        data = buf.get_data()
        self.assertEqual(len(data), 0)

    def test_downsample_for_display(self):
        from app.ui.waveform_display import downsample_for_display
        data = np.random.randn(1000).astype(np.float32)
        result = downsample_for_display(data, target_points=100)
        self.assertEqual(len(result), 100)


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_waveform_display.py -v`
Expected: FAIL with ImportError

**Step 3: Implement the waveform display**

```python
# app/ui/waveform_display.py
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
            # Take only the last max_samples
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
        # Buffer is full — read from write_pos (oldest) to write_pos (newest)
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
        # Use max absolute value for peak envelope
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
        self.setVisible(False)  # Hidden until recording starts

        # Repaint at ~15fps
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

        # Background
        painter.fillRect(0, 0, w, h, QColor("#1e1e2e"))

        # Center line
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

        # Draw waveform
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
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_waveform_display.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add app/ui/waveform_display.py tests/test_waveform_display.py
git commit -m "feat: add waveform display widget with ring buffer"
```

---

## Task 4: Wire Waveform Display Into Recording Pipeline

**Files:**
- Modify: `app/main_window.py` (add WaveformDisplay to left panel, connect signals)

**Step 1: Add WaveformDisplay to layout**

In `app/main_window.py`, import and add below level meter:

```python
from app.ui.waveform_display import WaveformDisplay

# In _setup_ui, after self.level_meter:
self.waveform = WaveformDisplay(seconds=5, sample_rate=self.config.get("audio", "sample_rate"))
left_layout.addWidget(self.waveform)
```

**Step 2: Connect to audio data**

The waveform needs combined audio data. Add a third signal to `Recorder`:

```python
combined_level = pyqtSignal(object)  # numpy array — combined mic+system for waveform
```

In the mic level callback, also emit combined data. Alternatively, connect the waveform to the mic level signal (since that's the primary audio source the user cares about):

```python
# In _connect_signals:
self.recorder.mic_level.connect(self.waveform.append_audio)
```

**Step 3: Start/stop waveform with recording state**

In `_on_state_changed`:

```python
if state == RecordingState.RECORDING:
    self.waveform.start()
elif state == RecordingState.PAUSED:
    self.waveform._paint_timer.stop()
elif state == RecordingState.IDLE:
    self.waveform.stop()
    self.level_meter.reset()
```

Handle resume (from PAUSED back to RECORDING) — the state_changed handler already covers this since RECORDING restarts the timer.

**Step 4: Manual test**

Run app, start recording with mic, verify waveform scrolls. Pause, verify it stops. Resume, verify it continues. Stop, verify it hides.

**Step 5: Commit**

```bash
git add app/main_window.py app/recording/recorder.py
git commit -m "feat: wire live waveform display into recording pipeline"
```

---

## Task 5: Transcript Undo/Redo History

**Files:**
- Create: `tests/test_edit_history.py`
- Modify: `app/ui/segment_widget.py` (add edit history stack)

**Step 1: Write the failing tests**

```python
# tests/test_edit_history.py
import unittest


class TestEditHistory(unittest.TestCase):
    def test_initial_state(self):
        from app.ui.segment_widget import EditHistory
        h = EditHistory("original")
        self.assertEqual(h.current(), "original")
        self.assertFalse(h.can_undo())
        self.assertFalse(h.can_redo())

    def test_push_and_undo(self):
        from app.ui.segment_widget import EditHistory
        h = EditHistory("original")
        h.push("edit1")
        self.assertEqual(h.current(), "edit1")
        self.assertTrue(h.can_undo())
        result = h.undo()
        self.assertEqual(result, "original")
        self.assertFalse(h.can_undo())

    def test_undo_then_redo(self):
        from app.ui.segment_widget import EditHistory
        h = EditHistory("original")
        h.push("edit1")
        h.push("edit2")
        h.undo()
        self.assertTrue(h.can_redo())
        result = h.redo()
        self.assertEqual(result, "edit2")

    def test_push_clears_redo(self):
        from app.ui.segment_widget import EditHistory
        h = EditHistory("original")
        h.push("edit1")
        h.push("edit2")
        h.undo()
        h.push("edit3")
        self.assertFalse(h.can_redo())
        self.assertEqual(h.current(), "edit3")

    def test_max_depth(self):
        from app.ui.segment_widget import EditHistory
        h = EditHistory("original", max_depth=5)
        for i in range(10):
            h.push(f"edit{i}")
        self.assertEqual(h.current(), "edit9")
        # Should only be able to undo 5 times (max_depth)
        count = 0
        while h.can_undo():
            h.undo()
            count += 1
        self.assertEqual(count, 5)

    def test_is_modified(self):
        from app.ui.segment_widget import EditHistory
        h = EditHistory("original")
        self.assertFalse(h.is_modified())
        h.push("edit1")
        self.assertTrue(h.is_modified())
        h.undo()
        self.assertFalse(h.is_modified())

    def test_original_text(self):
        from app.ui.segment_widget import EditHistory
        h = EditHistory("original")
        h.push("edit1")
        h.push("edit2")
        self.assertEqual(h.original(), "original")


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_edit_history.py -v`
Expected: FAIL with ImportError

**Step 3: Implement EditHistory class**

Add to the top of `app/ui/segment_widget.py` (before the SegmentWidget class):

```python
class EditHistory:
    """Undo/redo stack for segment text edits."""

    def __init__(self, initial_text: str, max_depth: int = 20):
        self._stack = [initial_text]
        self._pos = 0
        self._max_depth = max_depth

    def current(self) -> str:
        return self._stack[self._pos]

    def original(self) -> str:
        return self._stack[0]

    def is_modified(self) -> bool:
        return self._pos > 0

    def can_undo(self) -> bool:
        return self._pos > 0

    def can_redo(self) -> bool:
        return self._pos < len(self._stack) - 1

    def push(self, text: str):
        # Clear any redo entries
        self._stack = self._stack[:self._pos + 1]
        self._stack.append(text)
        self._pos += 1
        # Enforce max depth (keep original + last max_depth edits)
        if len(self._stack) > self._max_depth + 1:
            trim = len(self._stack) - self._max_depth - 1
            self._stack = self._stack[trim:]
            self._pos -= trim

    def undo(self) -> str:
        if self.can_undo():
            self._pos -= 1
        return self.current()

    def redo(self) -> str:
        if self.can_redo():
            self._pos += 1
        return self.current()
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_edit_history.py -v`
Expected: All 7 tests PASS

**Step 5: Integrate EditHistory into SegmentWidget**

In `SegmentWidget.__init__`, create the history:

```python
self._history = EditHistory(segment.text)
```

Modify `_finish_edit` to use history:

```python
def _finish_edit(self):
    if not self._editing:
        return
    self._editing = False
    new_text = self.text_edit.text().strip()
    if new_text and new_text != self._history.current():
        self._history.push(new_text)
        self.text_label.setText(new_text)
        self.text_edited.emit(self._index, new_text)
        self.edit_indicator.setVisible(self._history.is_modified())
    self.text_edit.hide()
    self.text_label.show()
```

Replace `_revert` with undo support and add redo. Add `keyPressEvent` for Ctrl+Z / Ctrl+Shift+Z:

```python
def undo(self):
    if self._history.can_undo():
        text = self._history.undo()
        self.text_label.setText(text)
        self.edit_indicator.setVisible(self._history.is_modified())
        self.text_edited.emit(self._index, text)

def redo(self):
    if self._history.can_redo():
        text = self._history.redo()
        self.text_label.setText(text)
        self.edit_indicator.setVisible(self._history.is_modified())
        self.text_edited.emit(self._index, text)
```

Update context menu to add Undo/Redo options:

```python
def _show_context_menu(self, pos):
    menu = QMenu(self)

    edit_action = QAction("Edit Text", self)
    edit_action.triggered.connect(self._start_edit)
    menu.addAction(edit_action)

    if self._history.can_undo():
        undo_action = QAction("Undo", self)
        undo_action.triggered.connect(self.undo)
        menu.addAction(undo_action)

    if self._history.can_redo():
        redo_action = QAction("Redo", self)
        redo_action.triggered.connect(self.redo)
        menu.addAction(redo_action)

    if self._history.is_modified():
        revert_action = QAction("Revert to Original", self)
        revert_action.triggered.connect(self._revert_to_original)
        menu.addAction(revert_action)

    menu.exec(self.text_label.mapToGlobal(pos))

def _revert_to_original(self):
    original = self._history.original()
    # Reset history back to original
    self._history = EditHistory(original)
    self.text_label.setText(original)
    self.edit_indicator.setVisible(False)
    self.text_reverted.emit(self._index)
```

**Step 6: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add app/ui/segment_widget.py tests/test_edit_history.py
git commit -m "feat: add undo/redo history for transcript segment editing"
```

---

## Task 6: Transcript Find/Replace Bar

**Files:**
- Create: `app/ui/transcript_search_bar.py`
- Create: `tests/test_transcript_search_bar.py`
- Modify: `app/ui/transcript_viewer.py` (integrate search bar)

**Step 1: Write the failing tests**

```python
# tests/test_transcript_search_bar.py
import unittest


class TestSearchLogic(unittest.TestCase):
    def test_find_matches_in_segments(self):
        from app.ui.transcript_search_bar import find_matches
        texts = ["Hello world", "world of code", "nothing here"]
        matches = find_matches("world", texts)
        # Each match: (segment_index, start_char, end_char)
        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0], (0, 6, 11))
        self.assertEqual(matches[1], (1, 0, 5))

    def test_find_matches_case_insensitive(self):
        from app.ui.transcript_search_bar import find_matches
        texts = ["Hello World", "WORLD of code"]
        matches = find_matches("world", texts, case_sensitive=False)
        self.assertEqual(len(matches), 2)

    def test_find_matches_case_sensitive(self):
        from app.ui.transcript_search_bar import find_matches
        texts = ["Hello World", "WORLD of code"]
        matches = find_matches("World", texts, case_sensitive=True)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0][0], 0)

    def test_find_matches_no_results(self):
        from app.ui.transcript_search_bar import find_matches
        texts = ["Hello world"]
        matches = find_matches("xyz", texts)
        self.assertEqual(len(matches), 0)

    def test_find_matches_regex(self):
        from app.ui.transcript_search_bar import find_matches
        texts = ["Hello 123 world", "test 456 end"]
        matches = find_matches(r"\d+", texts, use_regex=True)
        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0], (0, 6, 9))
        self.assertEqual(matches[1], (1, 5, 8))


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_transcript_search_bar.py -v`
Expected: FAIL with ImportError

**Step 3: Implement the search bar**

```python
# app/ui/transcript_search_bar.py
"""Find/replace toolbar for transcript viewer."""

import re
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton, QLabel, QCheckBox,
)


def find_matches(pattern, texts, case_sensitive=False, use_regex=False):
    """Find all matches across a list of text strings.

    Returns list of (segment_index, start_char, end_char) tuples.
    """
    matches = []
    flags = 0 if case_sensitive else re.IGNORECASE

    if not use_regex:
        pattern = re.escape(pattern)

    try:
        compiled = re.compile(pattern, flags)
    except re.error:
        return []

    for i, text in enumerate(texts):
        for m in compiled.finditer(text):
            matches.append((i, m.start(), m.end()))

    return matches


class TranscriptSearchBar(QWidget):
    """Collapsible find/replace bar for transcript segments."""

    navigate_to_match = pyqtSignal(int, int, int)  # segment_idx, start, end
    replace_requested = pyqtSignal(int, str, int, int)  # segment_idx, new_text, start, end
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._matches = []
        self._current_match = -1
        self._setup_ui()
        self.setVisible(False)

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Find field
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Find...")
        self.find_input.setMinimumWidth(150)
        self.find_input.returnPressed.connect(self.find_next)
        self.find_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.find_input)

        # Replace field
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Replace...")
        self.replace_input.setMinimumWidth(150)
        layout.addWidget(self.replace_input)

        # Options
        self.case_cb = QCheckBox("Aa")
        self.case_cb.setToolTip("Case sensitive")
        self.case_cb.toggled.connect(self._on_text_changed)
        layout.addWidget(self.case_cb)

        self.regex_cb = QCheckBox(".*")
        self.regex_cb.setToolTip("Use regex")
        self.regex_cb.toggled.connect(self._on_text_changed)
        layout.addWidget(self.regex_cb)

        # Navigation
        self.prev_btn = QPushButton("<")
        self.prev_btn.setFixedWidth(30)
        self.prev_btn.clicked.connect(self.find_prev)
        layout.addWidget(self.prev_btn)

        self.next_btn = QPushButton(">")
        self.next_btn.setFixedWidth(30)
        self.next_btn.clicked.connect(self.find_next)
        layout.addWidget(self.next_btn)

        # Match count
        self.match_label = QLabel("")
        self.match_label.setStyleSheet("color: #a6adc8; font-size: 11px;")
        layout.addWidget(self.match_label)

        # Replace button
        self.replace_btn = QPushButton("Replace")
        self.replace_btn.clicked.connect(self._do_replace)
        layout.addWidget(self.replace_btn)

        # Close
        close_btn = QPushButton("X")
        close_btn.setFixedWidth(24)
        close_btn.clicked.connect(self.hide_bar)
        layout.addWidget(close_btn)

    def show_bar(self):
        self.setVisible(True)
        self.find_input.setFocus()
        self.find_input.selectAll()

    def hide_bar(self):
        self.setVisible(False)
        self._matches = []
        self._current_match = -1
        self.closed.emit()

    def set_texts(self, texts):
        """Update the segment texts to search through."""
        self._texts = texts
        self._on_text_changed()

    def _on_text_changed(self):
        query = self.find_input.text()
        if not query:
            self._matches = []
            self._current_match = -1
            self.match_label.setText("")
            return

        self._matches = find_matches(
            query,
            getattr(self, '_texts', []),
            case_sensitive=self.case_cb.isChecked(),
            use_regex=self.regex_cb.isChecked(),
        )
        if self._matches:
            self._current_match = 0
            self._navigate_current()
        else:
            self._current_match = -1
        self._update_label()

    def find_next(self):
        if not self._matches:
            return
        self._current_match = (self._current_match + 1) % len(self._matches)
        self._navigate_current()
        self._update_label()

    def find_prev(self):
        if not self._matches:
            return
        self._current_match = (self._current_match - 1) % len(self._matches)
        self._navigate_current()
        self._update_label()

    def _navigate_current(self):
        if 0 <= self._current_match < len(self._matches):
            seg_idx, start, end = self._matches[self._current_match]
            self.navigate_to_match.emit(seg_idx, start, end)

    def _update_label(self):
        if not self._matches:
            query = self.find_input.text()
            self.match_label.setText("No matches" if query else "")
        else:
            self.match_label.setText(
                f"{self._current_match + 1} of {len(self._matches)}"
            )

    def _do_replace(self):
        if not self._matches or self._current_match < 0:
            return
        seg_idx, start, end = self._matches[self._current_match]
        new_text = self.replace_input.text()
        self.replace_requested.emit(seg_idx, new_text, start, end)
        # Re-search after replacement
        self._on_text_changed()
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_transcript_search_bar.py -v`
Expected: All 5 tests PASS

**Step 5: Integrate into TranscriptViewer**

In `app/ui/transcript_viewer.py`:

1. Import: `from app.ui.transcript_search_bar import TranscriptSearchBar`
2. Add search bar above the segments scroll area:

```python
self.search_bar = TranscriptSearchBar()
# Add before the scroll area in the layout
```

3. Connect signals:

```python
self.search_bar.navigate_to_match.connect(self._highlight_match)
self.search_bar.replace_requested.connect(self._replace_match)
```

4. Add Ctrl+F shortcut:

```python
from PyQt6.QtGui import QShortcut, QKeySequence
find_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
find_shortcut.activated.connect(self._show_search)
```

5. Implement handlers:

```python
def _show_search(self):
    texts = [seg.text for seg in self._transcript.segments] if self._transcript else []
    self.search_bar.set_texts(texts)
    self.search_bar.show_bar()

def _highlight_match(self, seg_idx, start, end):
    if 0 <= seg_idx < len(self._segment_widgets):
        widget = self._segment_widgets[seg_idx]
        # Scroll to widget
        self._segments_scroll.ensureWidgetVisible(widget)
        widget.highlight_match(start, end)

def _replace_match(self, seg_idx, new_text, start, end):
    if 0 <= seg_idx < len(self._segment_widgets):
        seg = self._transcript.segments[seg_idx]
        updated = seg.text[:start] + new_text + seg.text[end:]
        self._segment_widgets[seg_idx]._history.push(updated)
        self._segment_widgets[seg_idx].text_label.setText(updated)
        seg.text = updated
        self.transcript_changed.emit()
        # Update search texts
        texts = [s.text for s in self._transcript.segments]
        self.search_bar.set_texts(texts)
```

6. Add `highlight_match` method to `SegmentWidget`:

```python
def highlight_match(self, start, end):
    """Briefly flash the segment to show the match."""
    self.setStyleSheet("background-color: #45475a;")
    QTimer.singleShot(1500, lambda: self.setStyleSheet(""))
```

**Step 6: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add app/ui/transcript_search_bar.py tests/test_transcript_search_bar.py app/ui/transcript_viewer.py app/ui/segment_widget.py
git commit -m "feat: add find/replace toolbar for transcript viewer"
```

---

## Task 7: Buy Me a Coffee Integration

**Files:**
- Create: `.github/FUNDING.yml`
- Create: `app/ui/about_dialog.py`
- Modify: `app/main_window.py` (add Help menu items)
- Modify: `README.md` (add badge)

**Step 1: Create FUNDING.yml**

```yaml
# .github/FUNDING.yml
buy_me_a_coffee: YOUR_USERNAME
```

Replace `YOUR_USERNAME` with your actual Buy Me a Coffee username after account creation.

**Step 2: Create About dialog**

```python
# app/ui/about_dialog.py
"""About TalkTrack dialog."""

import webbrowser
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
)

BMAC_URL = "https://buymeacoffee.com/YOUR_USERNAME"
VERSION = "1.0.0"


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About TalkTrack")
        self.setFixedSize(400, 280)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Title
        title = QLabel("TalkTrack")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #cdd6f4;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Version
        version = QLabel(f"Version {VERSION}")
        version.setStyleSheet("font-size: 13px; color: #a6adc8;")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)

        # Description
        desc = QLabel(
            "AI-powered call recording, transcription, and speaker\n"
            "diarization for Windows. Free and offline."
        )
        desc.setStyleSheet("font-size: 12px; color: #bac2de;")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addSpacing(8)

        # Buy Me a Coffee button
        bmac_btn = QPushButton("Buy Me a Coffee")
        bmac_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #f9e2af; color: #1e1e2e; font-weight: bold;"
            "  padding: 10px 20px; border-radius: 6px; font-size: 14px;"
            "}"
            "QPushButton:hover {"
            "  background-color: #f2d68a;"
            "}"
        )
        bmac_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        bmac_btn.clicked.connect(lambda: webbrowser.open(BMAC_URL))

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(bmac_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addStretch()

        # Close
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)
```

**Step 3: Add Help menu items to MainWindow**

In `app/main_window.py`, the existing Help menu has an "About" action at line 82. Replace the `_show_about` method to use the new dialog, and add "Support TalkTrack":

```python
from app.ui.about_dialog import AboutDialog, BMAC_URL

# In _setup_menu, in the Help menu section, add before "About":
support_action = QAction("Support TalkTrack", self)
support_action.triggered.connect(lambda: webbrowser.open(BMAC_URL))
help_menu.addAction(support_action)
help_menu.addSeparator()

# Update _show_about:
def _show_about(self):
    dialog = AboutDialog(self)
    dialog.exec()
```

**Step 4: Add README badge**

At the top of `README.md`, add the badge (after the title):

```markdown
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-yellow?logo=buymeacoffee)](https://buymeacoffee.com/YOUR_USERNAME)
```

**Step 5: Commit**

```bash
git add .github/FUNDING.yml app/ui/about_dialog.py app/main_window.py README.md
git commit -m "feat: add Buy Me a Coffee donation link and About dialog"
```

---

## Task 8: AI Provider Abstraction

**Files:**
- Create: `app/ai/__init__.py`
- Create: `app/ai/provider.py`
- Create: `app/ai/claude_provider.py`
- Create: `app/ai/openai_provider.py`
- Create: `app/ai/local_provider.py`
- Create: `app/ai/provider_factory.py`
- Create: `tests/test_ai_provider.py`

**Step 1: Write the failing tests**

```python
# tests/test_ai_provider.py
import unittest
from unittest.mock import patch, MagicMock


class TestProviderFactory(unittest.TestCase):
    def test_create_claude_provider(self):
        from app.ai.provider_factory import create_provider
        config = {"provider": "claude", "api_key": "test-key", "model": "claude-sonnet-4-6"}
        provider = create_provider(config)
        from app.ai.claude_provider import ClaudeProvider
        self.assertIsInstance(provider, ClaudeProvider)

    def test_create_openai_provider(self):
        from app.ai.provider_factory import create_provider
        config = {"provider": "openai", "api_key": "test-key", "model": "gpt-4o"}
        provider = create_provider(config)
        from app.ai.openai_provider import OpenAIProvider
        self.assertIsInstance(provider, OpenAIProvider)

    def test_create_unknown_provider_raises(self):
        from app.ai.provider_factory import create_provider
        config = {"provider": "unknown"}
        with self.assertRaises(ValueError):
            create_provider(config)

    def test_create_none_provider(self):
        from app.ai.provider_factory import create_provider
        config = {"provider": "none"}
        provider = create_provider(config)
        self.assertIsNone(provider)


class TestClaudeProvider(unittest.TestCase):
    @patch("app.ai.claude_provider.Anthropic")
    def test_complete(self, mock_anthropic_cls):
        from app.ai.claude_provider import ClaudeProvider
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Summary of meeting")]
        mock_client.messages.create.return_value = mock_response

        provider = ClaudeProvider(api_key="test", model="claude-sonnet-4-6")
        result = provider.complete("Summarize this", "transcript text")
        self.assertEqual(result, "Summary of meeting")
        mock_client.messages.create.assert_called_once()


class TestOpenAIProvider(unittest.TestCase):
    @patch("app.ai.openai_provider.OpenAI")
    def test_complete(self, mock_openai_cls):
        from app.ai.openai_provider import OpenAIProvider
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="AI response"))]
        mock_client.chat.completions.create.return_value = mock_response

        provider = OpenAIProvider(api_key="test", model="gpt-4o")
        result = provider.complete("Summarize", "transcript")
        self.assertEqual(result, "AI response")


class TestProviderInterface(unittest.TestCase):
    def test_base_class_is_abstract(self):
        from app.ai.provider import AIProvider
        with self.assertRaises(TypeError):
            AIProvider()


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ai_provider.py -v`
Expected: FAIL with ImportError

**Step 3: Implement the provider system**

```python
# app/ai/__init__.py
"""AI provider abstraction for TalkTrack."""
```

```python
# app/ai/provider.py
"""Base class for AI providers."""

from abc import ABC, abstractmethod


class AIProvider(ABC):
    """Abstract base class for AI completion and embedding providers."""

    @abstractmethod
    def complete(self, prompt: str, context: str = "") -> str:
        """Send a prompt with optional context, return completion text."""
        ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts, return list of embedding vectors."""
        ...

    def test_connection(self) -> bool:
        """Test if the provider is configured and reachable."""
        try:
            result = self.complete("Say 'ok'.", "")
            return bool(result)
        except Exception:
            return False
```

```python
# app/ai/claude_provider.py
"""Claude API provider."""

from app.ai.provider import AIProvider


class ClaudeProvider(AIProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        from anthropic import Anthropic
        self._client = Anthropic(api_key=api_key)
        self._model = model

    def complete(self, prompt: str, context: str = "") -> str:
        messages = []
        if context:
            messages.append({"role": "user", "content": context})
            messages.append({"role": "assistant", "content": "I've read the transcript. What would you like to know?"})
        messages.append({"role": "user", "content": prompt})

        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            messages=messages,
        )
        return response.content[0].text

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Claude API doesn't have embeddings — use a local fallback
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        embeddings = model.encode(texts)
        return [e.tolist() for e in embeddings]
```

```python
# app/ai/openai_provider.py
"""OpenAI API provider."""

from app.ai.provider import AIProvider


class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._embed_model = "text-embedding-3-small"

    def complete(self, prompt: str, context: str = "") -> str:
        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": prompt})

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
        )
        return response.choices[0].message.content

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(
            model=self._embed_model,
            input=texts,
        )
        return [item.embedding for item in response.data]
```

```python
# app/ai/local_provider.py
"""Local model provider using llama-cpp-python and sentence-transformers."""

from app.ai.provider import AIProvider


class LocalProvider(AIProvider):
    def __init__(self, model_path: str, embed_model: str = "all-MiniLM-L6-v2"):
        self._model_path = model_path
        self._embed_model_name = embed_model
        self._llm = None
        self._embedder = None

    def _get_llm(self):
        if self._llm is None:
            from llama_cpp import Llama
            self._llm = Llama(
                model_path=self._model_path,
                n_ctx=4096,
                n_threads=4,
            )
        return self._llm

    def _get_embedder(self):
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer(self._embed_model_name)
        return self._embedder

    def complete(self, prompt: str, context: str = "") -> str:
        llm = self._get_llm()
        full_prompt = f"{context}\n\n{prompt}" if context else prompt
        response = llm(full_prompt, max_tokens=2048)
        return response["choices"][0]["text"].strip()

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._get_embedder()
        embeddings = model.encode(texts)
        return [e.tolist() for e in embeddings]
```

```python
# app/ai/provider_factory.py
"""Factory for creating AI providers from config."""

from app.ai.provider import AIProvider


def create_provider(config: dict) -> AIProvider | None:
    """Create an AI provider from a config dict.

    Config keys:
        provider: "claude", "openai", "local", or "none"
        api_key: API key (for claude/openai)
        model: Model name or path
    """
    provider_type = config.get("provider", "none")

    if provider_type == "none":
        return None

    if provider_type == "claude":
        from app.ai.claude_provider import ClaudeProvider
        return ClaudeProvider(
            api_key=config["api_key"],
            model=config.get("model", "claude-sonnet-4-6"),
        )

    if provider_type == "openai":
        from app.ai.openai_provider import OpenAIProvider
        return OpenAIProvider(
            api_key=config["api_key"],
            model=config.get("model", "gpt-4o"),
        )

    if provider_type == "local":
        from app.ai.local_provider import LocalProvider
        return LocalProvider(
            model_path=config.get("model", ""),
            embed_model=config.get("embed_model", "all-MiniLM-L6-v2"),
        )

    raise ValueError(f"Unknown AI provider: {provider_type}")
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ai_provider.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add app/ai/ tests/test_ai_provider.py
git commit -m "feat: add AI provider abstraction (Claude, OpenAI, local)"
```

---

## Task 9: AI Settings Tab

**Files:**
- Modify: `app/ui/settings_dialog.py` (add AI Assistant tab)
- Modify: `app/utils/config.py` (add AI default config)

**Step 1: Add AI defaults to config**

In `app/utils/config.py`, add to `DEFAULT_CONFIG`:

```python
"ai": {
    "provider": "none",
    "api_key": "",
    "model": "",
    "local_model_path": "",
    "embed_model": "all-MiniLM-L6-v2",
    "auto_summarize": True,
},
```

**Step 2: Add AI tab to SettingsDialog**

In `app/ui/settings_dialog.py`, add a new tab after the Transcription tab:

```python
# AI Assistant tab
ai_tab = QWidget()
ai_layout = QVBoxLayout(ai_tab)

ai_group = QGroupBox("AI Provider")
ai_form = QFormLayout(ai_group)

self.ai_provider_combo = QComboBox()
self.ai_provider_combo.addItem("None (disabled)", "none")
self.ai_provider_combo.addItem("Claude (Anthropic)", "claude")
self.ai_provider_combo.addItem("OpenAI", "openai")
self.ai_provider_combo.addItem("Local Model", "local")
self.ai_provider_combo.currentIndexChanged.connect(self._on_ai_provider_changed)
ai_form.addRow("Provider:", self.ai_provider_combo)

self.ai_api_key = QLineEdit()
self.ai_api_key.setEchoMode(QLineEdit.EchoMode.Password)
self.ai_api_key.setPlaceholderText("Enter API key...")
ai_form.addRow("API Key:", self.ai_api_key)

self.ai_model = QComboBox()
self.ai_model.setEditable(True)
ai_form.addRow("Model:", self.ai_model)

self.ai_local_path = QLineEdit()
self.ai_local_path.setPlaceholderText("Path to GGUF model file...")
self.ai_local_browse = QPushButton("Browse...")
self.ai_local_browse.clicked.connect(self._browse_local_model)
local_row = QHBoxLayout()
local_row.addWidget(self.ai_local_path)
local_row.addWidget(self.ai_local_browse)
ai_form.addRow("Local Model:", local_row)

self.ai_test_btn = QPushButton("Test Connection")
self.ai_test_btn.clicked.connect(self._test_ai_connection)
ai_form.addRow("", self.ai_test_btn)

ai_layout.addWidget(ai_group)

# Auto features group
features_group = QGroupBox("Automatic Features")
features_form = QFormLayout(features_group)

self.auto_summarize_cb = QCheckBox("Generate summary after transcription")
features_form.addRow(self.auto_summarize_cb)

ai_layout.addWidget(features_group)
ai_layout.addStretch()

tabs.addTab(ai_tab, "AI Assistant")
```

Add helper methods:

```python
def _on_ai_provider_changed(self, index):
    provider = self.ai_provider_combo.currentData()
    self.ai_api_key.setVisible(provider in ("claude", "openai"))
    self.ai_local_path.setVisible(provider == "local")
    self.ai_local_browse.setVisible(provider == "local")

    self.ai_model.clear()
    if provider == "claude":
        self.ai_model.addItems(["claude-sonnet-4-6", "claude-haiku-4-5-20251001", "claude-opus-4-6"])
    elif provider == "openai":
        self.ai_model.addItems(["gpt-4o", "gpt-4o-mini", "gpt-4.1"])
    elif provider == "local":
        self.ai_model.addItem("(set path below)")

def _browse_local_model(self):
    from PyQt6.QtWidgets import QFileDialog
    path, _ = QFileDialog.getOpenFileName(
        self, "Select Model File", "", "GGUF Files (*.gguf);;All Files (*)"
    )
    if path:
        self.ai_local_path.setText(path)

def _test_ai_connection(self):
    from app.ai.provider_factory import create_provider
    from PyQt6.QtWidgets import QMessageBox
    config = {
        "provider": self.ai_provider_combo.currentData(),
        "api_key": self.ai_api_key.text(),
        "model": self.ai_model.currentText(),
        "local_model_path": self.ai_local_path.text(),
    }
    try:
        provider = create_provider(config)
        if provider is None:
            QMessageBox.information(self, "AI", "No provider selected.")
            return
        if provider.test_connection():
            QMessageBox.information(self, "AI", "Connection successful!")
        else:
            QMessageBox.warning(self, "AI", "Connection failed.")
    except Exception as e:
        QMessageBox.critical(self, "AI Error", str(e))
```

Add loading/saving for AI settings in `_load_settings` and `_save_and_close`:

```python
# In _load_settings:
provider = self.config.get("ai", "provider")
idx = self.ai_provider_combo.findData(provider)
if idx >= 0:
    self.ai_provider_combo.setCurrentIndex(idx)
self.ai_api_key.setText(self.config.get("ai", "api_key"))
self.auto_summarize_cb.setChecked(self.config.get("ai", "auto_summarize"))
self.ai_local_path.setText(self.config.get("ai", "local_model_path"))

# In _save_and_close:
self.config.set("ai", "provider", self.ai_provider_combo.currentData())
self.config.set("ai", "api_key", self.ai_api_key.text())
self.config.set("ai", "model", self.ai_model.currentText())
self.config.set("ai", "local_model_path", self.ai_local_path.text())
self.config.set("ai", "auto_summarize", self.auto_summarize_cb.isChecked())
```

**Step 3: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add app/ui/settings_dialog.py app/utils/config.py
git commit -m "feat: add AI Assistant settings tab with provider configuration"
```

---

## Task 10: Meeting Summaries & Action Items

**Files:**
- Create: `app/ai/summarizer.py`
- Create: `app/ui/summary_panel.py`
- Create: `app/ui/action_items_panel.py`
- Create: `tests/test_summarizer.py`
- Modify: `app/ui/transcript_viewer.py` (add Summary and Action Items sub-tabs)
- Modify: `app/main_window.py` (trigger auto-summarize after transcription)

**Step 1: Write the failing tests**

```python
# tests/test_summarizer.py
import unittest
import json
from unittest.mock import MagicMock


class TestSummaryPromptBuilder(unittest.TestCase):
    def test_build_summary_prompt(self):
        from app.ai.summarizer import build_summary_prompt
        from app.transcription.transcriber import TranscriptSegment
        segments = [
            TranscriptSegment(0.0, 5.0, "Let's discuss the budget.", speaker="Alice"),
            TranscriptSegment(5.0, 10.0, "I think we need more funding.", speaker="Bob"),
        ]
        prompt = build_summary_prompt(segments, {"Alice": "Alice", "Bob": "Bob"})
        self.assertIn("Alice", prompt)
        self.assertIn("budget", prompt)

    def test_build_action_items_prompt(self):
        from app.ai.summarizer import build_action_items_prompt
        from app.transcription.transcriber import TranscriptSegment
        segments = [
            TranscriptSegment(0.0, 5.0, "Bob, can you send the report by Friday?", speaker="Alice"),
        ]
        prompt = build_action_items_prompt(segments, {"Alice": "Alice", "Bob": "Bob"})
        self.assertIn("action item", prompt.lower())
        self.assertIn("report", prompt)


class TestParseActionItems(unittest.TestCase):
    def test_parse_json_response(self):
        from app.ai.summarizer import parse_action_items
        response = json.dumps([
            {"task": "Send report", "assignee": "Bob", "deadline": "Friday"},
            {"task": "Review budget", "assignee": "Alice", "deadline": ""},
        ])
        items = parse_action_items(response)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["task"], "Send report")

    def test_parse_malformed_response(self):
        from app.ai.summarizer import parse_action_items
        items = parse_action_items("This is not JSON")
        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_summarizer.py -v`
Expected: FAIL

**Step 3: Implement summarizer**

```python
# app/ai/summarizer.py
"""Meeting summary and action item extraction."""

import json
from app.transcription.transcriber import TranscriptSegment


def _format_transcript(segments: list[TranscriptSegment], speaker_names: dict) -> str:
    """Format transcript segments into readable text for AI consumption."""
    lines = []
    for seg in segments:
        name = speaker_names.get(seg.speaker, seg.speaker) if seg.speaker else "Unknown"
        timestamp = f"[{seg.start:.1f}s]"
        lines.append(f"{timestamp} {name}: {seg.text}")
    return "\n".join(lines)


def build_summary_prompt(segments: list[TranscriptSegment], speaker_names: dict) -> str:
    transcript_text = _format_transcript(segments, speaker_names)
    return (
        "Below is a transcript of a meeting. Please provide a concise summary "
        "covering: key discussion points, decisions made, and outcomes.\n\n"
        "Format as markdown with bullet points.\n\n"
        f"TRANSCRIPT:\n{transcript_text}"
    )


def build_action_items_prompt(segments: list[TranscriptSegment], speaker_names: dict) -> str:
    transcript_text = _format_transcript(segments, speaker_names)
    return (
        "Below is a transcript of a meeting. Extract all action items — tasks, "
        "follow-ups, or commitments made by participants.\n\n"
        "Return a JSON array where each item has:\n"
        '- "task": description of the action item\n'
        '- "assignee": who is responsible (speaker name)\n'
        '- "deadline": mentioned deadline or empty string\n\n'
        "Return ONLY the JSON array, no other text.\n\n"
        f"TRANSCRIPT:\n{transcript_text}"
    )


def parse_action_items(response: str) -> list[dict]:
    """Parse AI response into action items list."""
    # Try to extract JSON from response
    text = response.strip()
    # Handle markdown code blocks
    if "```" in text:
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            text = text[start:end]
    try:
        items = json.loads(text)
        if isinstance(items, list):
            return items
    except (json.JSONDecodeError, ValueError):
        pass
    return []
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_summarizer.py -v`
Expected: All 4 tests PASS

**Step 5: Implement Summary and Action Items panels**

```python
# app/ui/summary_panel.py
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

    def set_summary(self, text: str):
        self._text.setMarkdown(text)
        self._text.setVisible(True)
        self._copy_btn.setVisible(True)
        self._regen_btn.setVisible(True)
        self._status.setVisible(False)

    def set_loading(self):
        self._status.setText("Generating summary...")
        self._status.setVisible(True)
        self._text.setVisible(False)

    def get_text(self) -> str:
        return self._text.toPlainText()

    def _copy(self):
        QApplication.clipboard().setText(self._text.toPlainText())
```

```python
# app/ui/action_items_panel.py
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

        # Scroll area for items
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setVisible(False)
        self._container = QWidget()
        self._items_layout = QVBoxLayout(self._container)
        self._items_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll)

        btn_row = QHBoxLayout()
        self._regen_btn = QPushButton("Regenerate")
        self._regen_btn.clicked.connect(self.regenerate_requested.emit)
        self._regen_btn.setVisible(False)
        btn_row.addWidget(self._regen_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def set_items(self, items: list[dict]):
        self._items = items
        # Clear existing
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
        self._regen_btn.setVisible(True)
        self._status.setVisible(False)

    def set_loading(self):
        self._status.setText("Extracting action items...")
        self._status.setVisible(True)
        self._scroll.setVisible(False)

    def _on_toggled(self, index, checked):
        if 0 <= index < len(self._items):
            self._items[index]["completed"] = checked
            self.items_changed.emit(self._items)

    def get_items(self) -> list[dict]:
        return self._items
```

**Step 6: Integrate into TranscriptViewer**

In `app/ui/transcript_viewer.py`, change the right panel to use a QTabWidget that contains sub-tabs for Transcript, Summary, and Action Items:

```python
from app.ui.summary_panel import SummaryPanel
from app.ui.action_items_panel import ActionItemsPanel

# In _setup_ui, create sub-tabs within the transcript area:
self.summary_panel = SummaryPanel()
self.action_items_panel = ActionItemsPanel()

# Add these as accessible widgets (the parent MainWindow will add them as tabs)
```

The cleaner approach: add Summary and Action Items as additional tabs in the main tab widget in `main_window.py`:

```python
self.summary_panel = SummaryPanel()
self.action_items_panel = ActionItemsPanel()
self.tabs.addTab(self.summary_panel, "Summary")
self.tabs.addTab(self.action_items_panel, "Action Items")
```

**Step 7: Add auto-summarize in MainWindow**

In `app/main_window.py`, after transcription/diarization completes:

```python
def _maybe_auto_summarize(self, transcript):
    if not self.config.get("ai", "auto_summarize"):
        return
    if self.config.get("ai", "provider") == "none":
        return
    self._run_summarize(transcript)

def _run_summarize(self, transcript):
    from app.ai.summarizer import build_summary_prompt, build_action_items_prompt
    from app.ai.provider_factory import create_provider
    from PyQt6.QtCore import QThread, pyqtSignal

    class SummarizeWorker(QThread):
        summary_ready = pyqtSignal(str)
        actions_ready = pyqtSignal(list)
        error = pyqtSignal(str)

        def __init__(self, provider, segments, speaker_names):
            super().__init__()
            self._provider = provider
            self._segments = segments
            self._names = speaker_names

        def run(self):
            try:
                from app.ai.summarizer import parse_action_items
                summary_prompt = build_summary_prompt(self._segments, self._names)
                summary = self._provider.complete(summary_prompt)
                self.summary_ready.emit(summary)

                actions_prompt = build_action_items_prompt(self._segments, self._names)
                actions_response = self._provider.complete(actions_prompt)
                actions = parse_action_items(actions_response)
                self.actions_ready.emit(actions)
            except Exception as e:
                self.error.emit(str(e))

    ai_config = self.config.data.get("ai", {})
    provider = create_provider(ai_config)
    if provider is None:
        return

    self.summary_panel.set_loading()
    self.action_items_panel.set_loading()

    self._summarize_worker = SummarizeWorker(
        provider, transcript.segments, self._speaker_names
    )
    self._summarize_worker.summary_ready.connect(self._on_summary_ready)
    self._summarize_worker.actions_ready.connect(self._on_actions_ready)
    self._summarize_worker.error.connect(
        lambda e: self.status_label.setText(f"AI error: {e}")
    )
    self._summarize_worker.start()

def _on_summary_ready(self, summary):
    self.summary_panel.set_summary(summary)
    # Save to disk
    if self._current_session:
        path = Path(self._current_session["directory"]) / "summary.md"
        with open(path, "w", encoding="utf-8") as f:
            f.write(summary)

def _on_actions_ready(self, items):
    self.action_items_panel.set_items(items)
    if self._current_session:
        path = Path(self._current_session["directory"]) / "action_items.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2)
```

**Step 8: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

**Step 9: Commit**

```bash
git add app/ai/summarizer.py app/ui/summary_panel.py app/ui/action_items_panel.py tests/test_summarizer.py app/ui/transcript_viewer.py app/main_window.py
git commit -m "feat: add AI-powered meeting summaries and action item extraction"
```

---

## Task 11: Searchable History

**Files:**
- Create: `app/ai/search_index.py`
- Create: `app/ui/search_bar.py`
- Create: `tests/test_search_index.py`
- Modify: `app/ui/recordings_list.py` (integrate search bar)
- Modify: `app/main_window.py` (connect search results to recording loading)

**Step 1: Write the failing tests**

```python
# tests/test_search_index.py
import unittest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from tempfile import TemporaryDirectory


class TestTextSearch(unittest.TestCase):
    def test_keyword_search(self):
        from app.ai.search_index import text_search
        transcripts = {
            "rec1": [
                {"text": "Let's discuss the budget", "start": 0.0, "speaker": "Alice"},
                {"text": "Revenue is up", "start": 5.0, "speaker": "Bob"},
            ],
            "rec2": [
                {"text": "Budget meeting tomorrow", "start": 0.0, "speaker": "Carol"},
            ],
        }
        results = text_search("budget", transcripts)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["recording_id"], "rec1")
        self.assertEqual(results[1]["recording_id"], "rec2")

    def test_keyword_search_no_matches(self):
        from app.ai.search_index import text_search
        transcripts = {
            "rec1": [{"text": "Hello world", "start": 0.0, "speaker": ""}],
        }
        results = text_search("budget", transcripts)
        self.assertEqual(len(results), 0)

    def test_keyword_search_case_insensitive(self):
        from app.ai.search_index import text_search
        transcripts = {
            "rec1": [{"text": "BUDGET review", "start": 0.0, "speaker": ""}],
        }
        results = text_search("budget", transcripts)
        self.assertEqual(len(results), 1)


class TestLoadTranscripts(unittest.TestCase):
    def test_load_from_directory(self):
        from app.ai.search_index import load_all_transcripts
        with TemporaryDirectory() as tmpdir:
            rec_dir = Path(tmpdir) / "recording_20260308_120000"
            rec_dir.mkdir()
            transcript = {
                "segments": [
                    {"start": 0.0, "end": 5.0, "text": "Hello", "speaker": "A"}
                ]
            }
            with open(rec_dir / "transcript.json", "w") as f:
                json.dump(transcript, f)
            meta = {"directory": str(rec_dir), "name": "Test Recording"}
            with open(rec_dir / "metadata.json", "w") as f:
                json.dump(meta, f)

            result = load_all_transcripts(Path(tmpdir))
            self.assertIn(rec_dir.name, result)
            self.assertEqual(len(result[rec_dir.name]), 1)


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_search_index.py -v`
Expected: FAIL

**Step 3: Implement search index**

```python
# app/ai/search_index.py
"""Search index for transcript history."""

import json
import re
from pathlib import Path


def load_all_transcripts(recordings_dir: Path) -> dict:
    """Load all transcripts from recordings directory.

    Returns dict mapping recording_id to list of segment dicts.
    """
    transcripts = {}
    if not recordings_dir.exists():
        return transcripts

    for entry in recordings_dir.iterdir():
        if not entry.is_dir():
            continue
        transcript_path = entry / "transcript.json"
        if not transcript_path.exists():
            continue
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            segments = data.get("segments", [])
            transcripts[entry.name] = segments
        except (json.JSONDecodeError, OSError):
            continue

    return transcripts


def text_search(query: str, transcripts: dict) -> list[dict]:
    """Search transcripts by keyword (case-insensitive).

    Returns list of match dicts with recording_id, segment text, timestamp, speaker.
    """
    results = []
    pattern = re.compile(re.escape(query), re.IGNORECASE)

    for rec_id, segments in transcripts.items():
        for seg in segments:
            text = seg.get("text", "")
            if pattern.search(text):
                results.append({
                    "recording_id": rec_id,
                    "text": text,
                    "start": seg.get("start", 0.0),
                    "speaker": seg.get("speaker", ""),
                })

    return results


def semantic_search(query: str, transcripts: dict, provider) -> list[dict]:
    """Search transcripts by semantic similarity using embeddings.

    Requires an AI provider with embed() capability.
    """
    # Build corpus
    corpus = []
    corpus_meta = []
    for rec_id, segments in transcripts.items():
        for seg in segments:
            text = seg.get("text", "").strip()
            if text:
                corpus.append(text)
                corpus_meta.append({
                    "recording_id": rec_id,
                    "text": text,
                    "start": seg.get("start", 0.0),
                    "speaker": seg.get("speaker", ""),
                })

    if not corpus:
        return []

    import numpy as np

    # Embed query and corpus
    all_texts = [query] + corpus
    embeddings = provider.embed(all_texts)
    query_emb = np.array(embeddings[0])
    corpus_embs = np.array(embeddings[1:])

    # Cosine similarity
    query_norm = query_emb / (np.linalg.norm(query_emb) + 1e-10)
    corpus_norms = corpus_embs / (np.linalg.norm(corpus_embs, axis=1, keepdims=True) + 1e-10)
    similarities = corpus_norms @ query_norm

    # Return top 20 results sorted by similarity
    top_indices = np.argsort(similarities)[::-1][:20]
    results = []
    for idx in top_indices:
        if similarities[idx] > 0.3:  # Threshold
            result = dict(corpus_meta[idx])
            result["score"] = float(similarities[idx])
            results.append(result)

    return results
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_search_index.py -v`
Expected: All 4 tests PASS

**Step 5: Implement search bar UI**

```python
# app/ui/search_bar.py
"""Search bar for recordings list sidebar."""

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout,
)


class SearchBar(QWidget):
    """Search box with text/semantic mode toggle."""

    search_requested = pyqtSignal(str, bool)  # query, is_semantic
    cleared = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_semantic = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Search recordings...")
        self._input.returnPressed.connect(self._do_search)
        self._input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._input)

        self._mode_btn = QPushButton("Aa")
        self._mode_btn.setToolTip("Text search (click for semantic)")
        self._mode_btn.setFixedWidth(30)
        self._mode_btn.setCheckable(True)
        self._mode_btn.toggled.connect(self._toggle_mode)
        layout.addWidget(self._mode_btn)

    def _toggle_mode(self, checked):
        self._is_semantic = checked
        self._mode_btn.setText("AI" if checked else "Aa")
        self._mode_btn.setToolTip(
            "Semantic search" if checked else "Text search (click for semantic)"
        )

    def _do_search(self):
        query = self._input.text().strip()
        if query:
            self.search_requested.emit(query, self._is_semantic)

    def _on_text_changed(self, text):
        if not text.strip():
            self.cleared.emit()
```

**Step 6: Integrate into RecordingsList**

In `app/ui/recordings_list.py`:

1. Import `SearchBar`
2. Add search bar above the list widget
3. Connect `search_requested` to a search handler
4. Show results in the list widget, replacing normal recordings
5. Connect `cleared` to restore normal recordings list

```python
from app.ui.search_bar import SearchBar

# In __init__, before list_widget:
self.search_bar = SearchBar()
layout.addWidget(self.search_bar)

# Connect signals
self.search_bar.search_requested.connect(self._on_search)
self.search_bar.cleared.connect(self.refresh)
```

Add search handler and result signal:

```python
search_result_selected = pyqtSignal(str, float)  # recording_id, timestamp

def _on_search(self, query, is_semantic):
    from app.ai.search_index import load_all_transcripts, text_search
    transcripts = load_all_transcripts(self.recordings_dir)

    if is_semantic:
        from app.ai.search_index import semantic_search
        from app.ai.provider_factory import create_provider
        # Provider will need to be passed in or accessed via config
        results = text_search(query, transcripts)  # Fallback for now
    else:
        results = text_search(query, transcripts)

    self._show_search_results(results)

def _show_search_results(self, results):
    self.list_widget.clear()
    for result in results[:50]:
        text = f"{result['recording_id']}\n"
        if result.get('speaker'):
            text += f"  [{result['speaker']}] "
        text += f"{result['text'][:80]}..."
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, result)
        self.list_widget.addItem(item)
```

**Step 7: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

**Step 8: Commit**

```bash
git add app/ai/search_index.py app/ui/search_bar.py tests/test_search_index.py app/ui/recordings_list.py app/main_window.py
git commit -m "feat: add searchable history with text and semantic search"
```

---

## Task 12: Chat With Transcript

**Files:**
- Create: `app/ai/chat.py`
- Create: `app/ui/chat_panel.py`
- Create: `tests/test_chat.py`
- Modify: `app/main_window.py` (add Chat tab)

**Step 1: Write the failing tests**

```python
# tests/test_chat.py
import unittest


class TestChatContextBuilder(unittest.TestCase):
    def test_build_context_short_transcript(self):
        from app.ai.chat import build_chat_context
        from app.transcription.transcriber import TranscriptSegment
        segments = [
            TranscriptSegment(0.0, 5.0, "Hello everyone", speaker="Alice"),
            TranscriptSegment(5.0, 10.0, "Hi Alice", speaker="Bob"),
        ]
        context = build_chat_context(segments, {"Alice": "Alice", "Bob": "Bob"})
        self.assertIn("Alice", context)
        self.assertIn("Hello everyone", context)

    def test_build_context_truncates_long_transcript(self):
        from app.ai.chat import build_chat_context, MAX_CONTEXT_CHARS
        from app.transcription.transcriber import TranscriptSegment
        segments = [
            TranscriptSegment(float(i), float(i + 1), f"Segment number {i} " * 20, speaker="A")
            for i in range(200)
        ]
        context = build_chat_context(segments, {})
        self.assertLessEqual(len(context), MAX_CONTEXT_CHARS + 500)  # Some header overhead

    def test_format_chat_history(self):
        from app.ai.chat import format_chat_prompt
        history = [
            {"role": "user", "content": "What was discussed?"},
            {"role": "assistant", "content": "The budget was discussed."},
        ]
        prompt = format_chat_prompt("Who mentioned the deadline?", history)
        self.assertIn("deadline", prompt)


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chat.py -v`
Expected: FAIL

**Step 3: Implement chat module**

```python
# app/ai/chat.py
"""Chat with transcript functionality."""

from app.transcription.transcriber import TranscriptSegment

MAX_CONTEXT_CHARS = 12000


def build_chat_context(segments: list[TranscriptSegment], speaker_names: dict) -> str:
    """Build a context string from transcript segments."""
    lines = []
    total = 0
    header = (
        "You are a helpful assistant. The user is asking about a meeting transcript. "
        "Answer based on the transcript content below.\n\n"
        "TRANSCRIPT:\n"
    )
    total += len(header)

    for seg in segments:
        name = speaker_names.get(seg.speaker, seg.speaker) if seg.speaker else "Unknown"
        line = f"[{seg.start:.1f}s] {name}: {seg.text}"
        if total + len(line) + 1 > MAX_CONTEXT_CHARS:
            lines.append("... (transcript truncated)")
            break
        lines.append(line)
        total += len(line) + 1

    return header + "\n".join(lines)


def format_chat_prompt(question: str, history: list[dict] = None) -> str:
    """Format a chat prompt including conversation history."""
    parts = []
    if history:
        for msg in history[-6:]:  # Keep last 6 messages for context
            role = "User" if msg["role"] == "user" else "Assistant"
            parts.append(f"{role}: {msg['content']}")
    parts.append(f"User: {question}")
    return "\n\n".join(parts)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_chat.py -v`
Expected: All 3 tests PASS

**Step 5: Implement ChatPanel widget**

```python
# app/ui/chat_panel.py
"""Chat panel for asking questions about transcripts."""

import json
from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit,
    QPushButton, QLabel, QScrollArea,
)


class ChatMessage(QWidget):
    """A single chat message bubble."""

    def __init__(self, role: str, content: str, parent=None):
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
    """Chat interface for asking questions about the current transcript."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history = []  # list of {"role": str, "content": str}
        self._context = ""
        self._provider = None
        self._worker = None
        self._session_dir = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Status when no provider
        self._no_provider_label = QLabel(
            "AI provider not configured. Go to Settings > AI Assistant to set up."
        )
        self._no_provider_label.setStyleSheet("color: #a6adc8; padding: 16px;")
        self._no_provider_label.setWordWrap(True)
        layout.addWidget(self._no_provider_label)

        # Chat messages area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setVisible(False)
        self._messages_container = QWidget()
        self._messages_layout = QVBoxLayout(self._messages_container)
        self._messages_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._messages_container)
        layout.addWidget(self._scroll, 1)

        # Input area
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

    def set_context(self, context: str):
        self._context = context

    def set_session_dir(self, session_dir: str):
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
        prompt = format_chat_prompt(text, self._history[:-1])  # Exclude the just-added message

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
        # Scroll to bottom
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
```

**Step 6: Integrate into MainWindow**

In `app/main_window.py`:

```python
from app.ui.chat_panel import ChatPanel
from app.ai.chat import build_chat_context

# In _setup_ui, add Chat tab:
self.chat_panel = ChatPanel()
self.tabs.addTab(self.chat_panel, "Chat")

# When a recording is loaded or transcript displayed, update chat context:
def _update_chat_context(self):
    if self._transcript:
        context = build_chat_context(self._transcript.segments, self._speaker_names)
        self.chat_panel.set_context(context)

    if self._current_session:
        self.chat_panel.set_session_dir(self._current_session["directory"])

    # Set provider
    from app.ai.provider_factory import create_provider
    ai_config = self.config.data.get("ai", {})
    provider = create_provider(ai_config)
    self.chat_panel.set_provider(provider)
```

Call `_update_chat_context()` from `_display_final_transcript()` and from `_load_recording()`.

**Step 7: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

**Step 8: Commit**

```bash
git add app/ai/chat.py app/ui/chat_panel.py tests/test_chat.py app/main_window.py
git commit -m "feat: add chat with transcript panel for AI Q&A"
```

---

## Task 13: Update Dependencies and CLAUDE.md

**Files:**
- Modify: `requirements.txt`
- Modify: `CLAUDE.md`

**Step 1: Update requirements.txt**

Add new optional dependencies:

```
# AI Providers (optional — install based on your preferred provider)
anthropic>=0.40.0
openai>=1.50.0
# llama-cpp-python>=0.3.0  # Uncomment for local model support
```

Note: `sentence-transformers` is already a transitive dependency of pyannote.

**Step 2: Update CLAUDE.md**

Add to Project Structure:
```
    ai/
      __init__.py                      # Package init
      provider.py                      # AIProvider base class
      claude_provider.py               # Claude API implementation
      openai_provider.py               # OpenAI API implementation
      local_provider.py                # Local model (llama-cpp-python)
      provider_factory.py              # Factory for configured provider
      summarizer.py                    # Meeting summary + action items
      search_index.py                  # Transcript search + embeddings
      chat.py                          # Chat context builder
```

Add to Current Features:
```
- **Audio level meters:** real-time VU meters for mic and system audio
- **Live waveform:** scrolling waveform visualization during recording
- **Transcript find/replace:** Ctrl+F search with regex support
- **Transcript undo/redo:** per-segment edit history (Ctrl+Z/Ctrl+Shift+Z)
- **AI meeting summaries:** auto-generated after transcription (configurable provider)
- **AI action items:** extracted tasks with assignees and deadlines
- **Searchable history:** text and semantic search across all recordings
- **Chat with transcript:** ask AI questions about the current recording
- **AI provider choice:** Claude, OpenAI, or local models (Settings > AI Assistant)
- **About dialog:** version info and Buy Me a Coffee donation link
```

**Step 3: Commit**

```bash
git add requirements.txt CLAUDE.md
git commit -m "docs: update requirements and CLAUDE.md for new features"
```

---

## Task 14: Final Integration Test

**Step 1: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

**Step 2: Manual smoke test**

1. Launch app: `python main.py`
2. Verify level meters and waveform appear in left panel
3. Start a recording — verify meters animate, waveform scrolls
4. Stop recording — verify meters reset, waveform hides
5. After transcription: verify Summary and Action Items tabs appear
6. Open Settings > AI Assistant — verify provider options
7. Try Ctrl+F in transcript — verify find/replace bar
8. Edit a segment, right-click — verify Undo/Redo options
9. Try search bar in recordings list
10. Check Help > About and Help > Support TalkTrack
11. Check Chat tab

**Step 3: Final commit if any fixes needed**

```bash
git add -u
git commit -m "fix: integration fixes from smoke testing"
```
