# Transcript Enhancement Suite — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the transcript viewer from a read-only display into an interactive editing and review tool with speaker naming, inline editing, audio playback, and recording info header.

**Architecture:** Four new UI components (SegmentWidget, SpeakerNamePanel, RecordingHeader, SegmentPlayer) replace the monolithic QTextEdit in TranscriptViewer. Data flows through TranscriptResult which gains speaker_names and original_text support. All persistence is per-session in the recording directory.

**Tech Stack:** PyQt6 (UI widgets, signals/slots), sounddevice + soundfile (audio playback), JSON (persistence)

---

## Task 1: TranscriptSegment — Add `original_text` Field

**Files:**
- Modify: `app/transcription/transcriber.py:7-22`
- Test: `tests/test_transcriber.py` (new file)

**Step 1: Write the failing tests**

Create `tests/test_transcriber.py`:

```python
"""Tests for TranscriptSegment and TranscriptResult."""
import unittest
from app.transcription.transcriber import TranscriptSegment, TranscriptResult


class TestTranscriptSegment(unittest.TestCase):

    def test_to_dict_without_original_text(self):
        seg = TranscriptSegment(start=1.0, end=2.0, text="hello")
        d = seg.to_dict()
        self.assertEqual(d["text"], "hello")
        self.assertNotIn("original_text", d)

    def test_to_dict_with_original_text(self):
        seg = TranscriptSegment(start=1.0, end=2.0, text="Q4", original_text="quarterly")
        d = seg.to_dict()
        self.assertEqual(d["text"], "Q4")
        self.assertEqual(d["original_text"], "quarterly")

    def test_to_dict_with_empty_original_text_omits_it(self):
        seg = TranscriptSegment(start=1.0, end=2.0, text="hello", original_text="")
        d = seg.to_dict()
        self.assertNotIn("original_text", d)

    def test_from_dict_with_original_text(self):
        """TranscriptSegment(**dict) should accept original_text."""
        data = {"start": 1.0, "end": 2.0, "text": "Q4", "original_text": "quarterly",
                "speaker": "", "confidence": 0.0}
        seg = TranscriptSegment(**data)
        self.assertEqual(seg.original_text, "quarterly")

    def test_from_dict_without_original_text(self):
        data = {"start": 1.0, "end": 2.0, "text": "hello", "speaker": "", "confidence": 0.0}
        seg = TranscriptSegment(**data)
        self.assertEqual(seg.original_text, "")


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_transcriber.py -v`
Expected: FAIL — `TranscriptSegment.__init__() got an unexpected keyword argument 'original_text'`

**Step 3: Add `original_text` field to TranscriptSegment**

In `app/transcription/transcriber.py`, modify the `TranscriptSegment` dataclass:

```python
@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: str = ""
    confidence: float = 0.0
    original_text: str = ""

    def to_dict(self):
        d = {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "speaker": self.speaker,
            "confidence": self.confidence,
        }
        if self.original_text:
            d["original_text"] = self.original_text
        return d
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_transcriber.py -v`
Expected: All 5 PASS

**Step 5: Run all existing tests to check for regressions**

Run: `python -m pytest tests/ -v`
Expected: All pass (no regressions — original_text defaults to "" so existing callers unaffected)

**Step 6: Commit**

```bash
git add app/transcription/transcriber.py tests/test_transcriber.py
git commit -m "feat: add original_text field to TranscriptSegment for edit undo"
```

---

## Task 2: TranscriptResult — Speaker-Name-Aware Exports

**Files:**
- Modify: `app/transcription/transcriber.py:25-56`
- Test: `tests/test_transcriber.py` (append)

**Step 1: Write the failing tests**

Append to `tests/test_transcriber.py`:

```python
class TestTranscriptResultExports(unittest.TestCase):

    def _make_result(self):
        return TranscriptResult(
            segments=[
                TranscriptSegment(start=0.0, end=5.0, text="Hello everyone", speaker="SPEAKER_00"),
                TranscriptSegment(start=5.0, end=10.0, text="Hi there", speaker="SPEAKER_01"),
            ],
            language="en",
            duration=10.0,
        )

    def test_to_text_without_speaker_names(self):
        result = self._make_result()
        text = result.to_text()
        self.assertIn("[SPEAKER_00]", text)
        self.assertIn("[SPEAKER_01]", text)

    def test_to_text_with_speaker_names(self):
        result = self._make_result()
        names = {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"}
        text = result.to_text(speaker_names=names)
        self.assertIn("[Alice]", text)
        self.assertIn("[Bob]", text)
        self.assertNotIn("SPEAKER_00", text)

    def test_to_text_with_partial_speaker_names(self):
        result = self._make_result()
        names = {"SPEAKER_00": "Alice"}
        text = result.to_text(speaker_names=names)
        self.assertIn("[Alice]", text)
        self.assertIn("[SPEAKER_01]", text)

    def test_to_srt_with_speaker_names(self):
        result = self._make_result()
        names = {"SPEAKER_00": "Alice"}
        srt = result.to_srt(speaker_names=names)
        self.assertIn("[Alice]", srt)
        self.assertIn("[SPEAKER_01]", srt)

    def test_to_dict_with_speaker_names(self):
        result = self._make_result()
        names = {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"}
        d = result.to_dict(speaker_names=names)
        self.assertEqual(d["segments"][0]["speaker_name"], "Alice")
        self.assertEqual(d["segments"][1]["speaker_name"], "Bob")
        # Original speaker IDs preserved
        self.assertEqual(d["segments"][0]["speaker"], "SPEAKER_00")

    def test_to_dict_without_speaker_names_has_no_speaker_name_key(self):
        result = self._make_result()
        d = result.to_dict()
        self.assertNotIn("speaker_name", d["segments"][0])
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_transcriber.py::TestTranscriptResultExports -v`
Expected: FAIL — `to_text() got an unexpected keyword argument 'speaker_names'`

**Step 3: Update export methods to accept speaker_names**

In `app/transcription/transcriber.py`, modify `TranscriptResult`:

```python
@dataclass
class TranscriptResult:
    segments: list = field(default_factory=list)
    language: str = ""
    duration: float = 0.0

    def _display_speaker(self, seg, speaker_names=None):
        """Return the display name for a segment's speaker."""
        if not seg.speaker:
            return ""
        if speaker_names and seg.speaker in speaker_names and speaker_names[seg.speaker]:
            return speaker_names[seg.speaker]
        return seg.speaker

    def to_dict(self, speaker_names=None):
        segments = []
        for s in self.segments:
            d = s.to_dict()
            if speaker_names and s.speaker in speaker_names and speaker_names[s.speaker]:
                d["speaker_name"] = speaker_names[s.speaker]
            segments.append(d)
        return {
            "segments": segments,
            "language": self.language,
            "duration": self.duration,
        }

    def to_text(self, speaker_names=None):
        lines = []
        for seg in self.segments:
            display = self._display_speaker(seg, speaker_names)
            speaker = f"[{display}] " if display else ""
            timestamp = f"[{_format_time(seg.start)} -> {_format_time(seg.end)}]"
            lines.append(f"{timestamp} {speaker}{seg.text}")
        return "\n".join(lines)

    def to_srt(self, speaker_names=None):
        lines = []
        for i, seg in enumerate(self.segments, 1):
            start_ts = _format_srt_time(seg.start)
            end_ts = _format_srt_time(seg.end)
            display = self._display_speaker(seg, speaker_names)
            speaker = f"[{display}] " if display else ""
            lines.append(f"{i}")
            lines.append(f"{start_ts} --> {end_ts}")
            lines.append(f"{speaker}{seg.text}")
            lines.append("")
        return "\n".join(lines)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_transcriber.py -v`
Expected: All PASS (both old and new tests)

**Step 5: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All pass

**Step 6: Commit**

```bash
git add app/transcription/transcriber.py tests/test_transcriber.py
git commit -m "feat: add speaker_names support to transcript export methods"
```

---

## Task 3: SegmentPlayer — Audio Clip Playback

**Files:**
- Create: `app/audio/__init__.py`
- Create: `app/audio/segment_player.py`
- Test: `tests/test_segment_player.py` (new file)

**Step 1: Write the failing tests**

Create `tests/test_segment_player.py`:

```python
"""Tests for SegmentPlayer audio clip playback."""
import unittest
from unittest.mock import patch, MagicMock
import numpy as np


class TestSegmentPlayer(unittest.TestCase):

    @patch("app.audio.segment_player.sf")
    @patch("app.audio.segment_player.sd")
    def test_play_segment_extracts_correct_samples(self, mock_sd, mock_sf):
        """Playing from 1.0s to 2.0s at 16000Hz should extract samples 16000-32000."""
        from app.audio.segment_player import SegmentPlayer

        # Simulate 5 seconds of audio at 16000Hz
        audio_data = np.zeros(80000, dtype=np.float32)
        mock_sf.read.return_value = (audio_data, 16000)

        player = SegmentPlayer()
        player.play_segment("test.wav", 1.0, 2.0)

        mock_sd.play.assert_called_once()
        played_data = mock_sd.play.call_args[0][0]
        self.assertEqual(len(played_data), 16000)  # 1 second of audio
        self.assertEqual(mock_sd.play.call_args[1]["samplerate"], 16000)

    @patch("app.audio.segment_player.sf")
    @patch("app.audio.segment_player.sd")
    def test_stop_calls_sounddevice_stop(self, mock_sd, mock_sf):
        from app.audio.segment_player import SegmentPlayer

        player = SegmentPlayer()
        player.stop()
        mock_sd.stop.assert_called_once()

    @patch("app.audio.segment_player.sf")
    @patch("app.audio.segment_player.sd")
    def test_play_segment_caches_audio_file(self, mock_sd, mock_sf):
        """Loading the same file twice should only call sf.read once."""
        from app.audio.segment_player import SegmentPlayer

        audio_data = np.zeros(80000, dtype=np.float32)
        mock_sf.read.return_value = (audio_data, 16000)

        player = SegmentPlayer()
        player.play_segment("test.wav", 0.0, 1.0)
        player.play_segment("test.wav", 1.0, 2.0)

        self.assertEqual(mock_sf.read.call_count, 1)

    @patch("app.audio.segment_player.sf")
    @patch("app.audio.segment_player.sd")
    def test_play_segment_stops_previous_before_playing(self, mock_sd, mock_sf):
        from app.audio.segment_player import SegmentPlayer

        audio_data = np.zeros(80000, dtype=np.float32)
        mock_sf.read.return_value = (audio_data, 16000)

        player = SegmentPlayer()
        player.play_segment("test.wav", 0.0, 1.0)
        player.play_segment("test.wav", 1.0, 2.0)

        # stop() called before second play
        self.assertEqual(mock_sd.stop.call_count, 2)  # once per play_segment call

    @patch("app.audio.segment_player.sf")
    @patch("app.audio.segment_player.sd")
    def test_play_clamps_to_audio_length(self, mock_sd, mock_sf):
        """End time beyond audio length should clamp to end of file."""
        from app.audio.segment_player import SegmentPlayer

        audio_data = np.zeros(16000, dtype=np.float32)  # 1 second
        mock_sf.read.return_value = (audio_data, 16000)

        player = SegmentPlayer()
        player.play_segment("test.wav", 0.5, 5.0)  # end beyond file length

        played_data = mock_sd.play.call_args[0][0]
        self.assertEqual(len(played_data), 8000)  # only 0.5s available


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_segment_player.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.audio'`

**Step 3: Create the SegmentPlayer**

Create `app/audio/__init__.py` (empty file).

Create `app/audio/segment_player.py`:

```python
"""Audio segment playback using sounddevice."""
import sounddevice as sd
import soundfile as sf
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal, QTimer


class SegmentPlayer(QObject):
    """Plays audio clips for transcript segments using sounddevice.

    Caches the loaded audio file to avoid re-reading for each segment.
    Emits playback_finished when a clip finishes playing.
    """

    playback_finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cached_path = None
        self._cached_data = None
        self._cached_sr = None
        self._playing = False
        self._check_timer = QTimer(self)
        self._check_timer.setInterval(100)
        self._check_timer.timeout.connect(self._check_playback)

    def play_segment(self, audio_path, start_sec, end_sec):
        """Play audio from start_sec to end_sec of the given file.

        Stops any currently playing clip first.
        Caches the audio file for repeated segment plays.
        """
        self.stop()

        # Load and cache audio
        if self._cached_path != audio_path:
            data, sr = sf.read(audio_path, dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)  # mix to mono
            self._cached_data = data
            self._cached_sr = sr
            self._cached_path = audio_path

        # Extract segment
        start_sample = int(start_sec * self._cached_sr)
        end_sample = int(end_sec * self._cached_sr)
        start_sample = max(0, min(start_sample, len(self._cached_data)))
        end_sample = max(start_sample, min(end_sample, len(self._cached_data)))

        segment = self._cached_data[start_sample:end_sample]
        if len(segment) == 0:
            return

        sd.play(segment, samplerate=self._cached_sr)
        self._playing = True
        self._check_timer.start()

    def stop(self):
        """Stop any currently playing audio."""
        sd.stop()
        self._playing = False
        self._check_timer.stop()

    def is_playing(self):
        """Return True if audio is currently playing."""
        return self._playing

    def _check_playback(self):
        """Poll sounddevice to detect when playback finishes."""
        import sounddevice as sd
        stream = sd.get_stream()
        if stream is None or not stream.active:
            self._playing = False
            self._check_timer.stop()
            self.playback_finished.emit()

    def clear_cache(self):
        """Clear cached audio data."""
        self._cached_path = None
        self._cached_data = None
        self._cached_sr = None
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_segment_player.py -v`
Expected: All 5 PASS

**Step 5: Commit**

```bash
git add app/audio/__init__.py app/audio/segment_player.py tests/test_segment_player.py
git commit -m "feat: add SegmentPlayer for audio clip playback"
```

---

## Task 4: RecordingHeader Widget

**Files:**
- Create: `app/ui/recording_header.py`
- Test: `tests/test_recording_header.py` (new file)

**Step 1: Write the failing tests**

Create `tests/test_recording_header.py`:

```python
"""Tests for RecordingHeader widget."""
import unittest
from unittest.mock import patch, MagicMock


class TestRecordingHeader(unittest.TestCase):

    @patch("app.ui.recording_header.QWidget.__init__", return_value=None)
    def test_set_recording_shows_name(self, _):
        """Skipping full Qt init — test logic only."""
        # Test the name extraction logic directly
        from app.ui.recording_header import _display_name_from_metadata
        metadata = {"name": "Sprint Planning", "directory": "C:/recordings/rec_2024"}
        self.assertEqual(_display_name_from_metadata(metadata), "Sprint Planning")

    @patch("app.ui.recording_header.QWidget.__init__", return_value=None)
    def test_display_name_falls_back_to_directory(self, _):
        from app.ui.recording_header import _display_name_from_metadata
        metadata = {"directory": "C:/recordings/recording_20240308_1430"}
        self.assertEqual(_display_name_from_metadata(metadata), "recording_20240308_1430")

    def test_format_duration(self):
        from app.ui.recording_header import _format_duration
        self.assertEqual(_format_duration(0), "0s")
        self.assertEqual(_format_duration(65), "1m 5s")
        self.assertEqual(_format_duration(3661), "1h 1m 1s")


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_recording_header.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ui.recording_header'`

**Step 3: Create RecordingHeader widget**

Create `app/ui/recording_header.py`:

```python
"""Recording info header with rename capability."""
import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal


def _display_name_from_metadata(metadata):
    """Extract display name from metadata, falling back to directory name."""
    name = metadata.get("name", "")
    if name:
        return name
    directory = metadata.get("directory", "")
    return Path(directory).name if directory else "Untitled Recording"


def _format_duration(seconds):
    """Format seconds as human-readable duration string."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


class RecordingHeader(QWidget):
    """Displays recording info (name, date, duration) with rename capability."""

    name_changed = pyqtSignal(str)  # emitted when user renames the recording

    def __init__(self, parent=None):
        super().__init__(parent)
        self._metadata = None
        self._editing = False
        self._setup_ui()
        self.hide()  # hidden until a recording is loaded

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 4)

        # Top row: name + rename button
        top_row = QHBoxLayout()

        self.name_label = QLabel("")
        self.name_label.setObjectName("recordingName")
        self.name_label.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #cdd6f4;"
        )
        top_row.addWidget(self.name_label)

        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("recordingNameEdit")
        self.name_edit.hide()
        self.name_edit.returnPressed.connect(self._finish_rename)
        top_row.addWidget(self.name_edit)

        top_row.addStretch()

        self.rename_btn = QPushButton("Rename")
        self.rename_btn.setObjectName("renameButton")
        self.rename_btn.setFixedWidth(70)
        self.rename_btn.clicked.connect(self._start_rename)
        top_row.addWidget(self.rename_btn)

        layout.addLayout(top_row)

        # Bottom row: date, duration, speaker count
        self.info_label = QLabel("")
        self.info_label.setObjectName("recordingInfo")
        self.info_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(self.info_label)

    def set_recording(self, metadata, speaker_count=0):
        """Display info for the given recording metadata."""
        self._metadata = metadata
        if metadata is None:
            self.hide()
            return

        self.show()

        name = _display_name_from_metadata(metadata)
        self.name_label.setText(name)

        # Build info line
        parts = []
        started = metadata.get("started_at", "")
        if started:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(started)
                parts.append(dt.strftime("%Y-%m-%d %H:%M"))
            except (ValueError, TypeError):
                parts.append(started)

        duration = metadata.get("duration", 0)
        if duration:
            parts.append(f"Duration: {_format_duration(duration)}")

        if speaker_count > 0:
            parts.append(f"{speaker_count} speaker{'s' if speaker_count != 1 else ''}")

        self.info_label.setText("  |  ".join(parts))

    def _start_rename(self):
        if self._editing:
            self._finish_rename()
            return

        self._editing = True
        self.name_edit.setText(self.name_label.text())
        self.name_label.hide()
        self.name_edit.show()
        self.name_edit.setFocus()
        self.name_edit.selectAll()
        self.rename_btn.setText("Save")

    def _finish_rename(self):
        self._editing = False
        new_name = self.name_edit.text().strip()
        if new_name:
            self.name_label.setText(new_name)
            self.name_changed.emit(new_name)
        self.name_edit.hide()
        self.name_label.show()
        self.rename_btn.setText("Rename")
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_recording_header.py -v`
Expected: All 3 PASS

**Step 5: Commit**

```bash
git add app/ui/recording_header.py tests/test_recording_header.py
git commit -m "feat: add RecordingHeader widget with rename capability"
```

---

## Task 5: SpeakerNamePanel Widget

**Files:**
- Create: `app/ui/speaker_name_panel.py`
- Test: `tests/test_speaker_name_panel.py` (new file)

**Step 1: Write the failing tests**

Create `tests/test_speaker_name_panel.py`:

```python
"""Tests for SpeakerNamePanel logic."""
import unittest


class TestSpeakerNamePanelLogic(unittest.TestCase):

    def test_build_speaker_list_from_segments(self):
        """Extract unique sorted speakers from segments."""
        from app.ui.speaker_name_panel import _extract_speakers
        from app.transcription.transcriber import TranscriptSegment
        segments = [
            TranscriptSegment(start=0, end=1, text="a", speaker="SPEAKER_01"),
            TranscriptSegment(start=1, end=2, text="b", speaker="SPEAKER_00"),
            TranscriptSegment(start=2, end=3, text="c", speaker="SPEAKER_01"),
            TranscriptSegment(start=3, end=4, text="d", speaker=""),
        ]
        speakers = _extract_speakers(segments)
        self.assertEqual(speakers, ["SPEAKER_00", "SPEAKER_01"])

    def test_build_speaker_list_empty_segments(self):
        from app.ui.speaker_name_panel import _extract_speakers
        self.assertEqual(_extract_speakers([]), [])


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_speaker_name_panel.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Create SpeakerNamePanel widget**

Create `app/ui/speaker_name_panel.py`:

```python
"""Collapsible speaker name editing panel."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from app.ui.transcript_viewer import SPEAKER_COLORS


def _extract_speakers(segments):
    """Extract unique speaker IDs from segments, sorted."""
    speakers = set()
    for seg in segments:
        if seg.speaker:
            speakers.add(seg.speaker)
    return sorted(speakers)


class SpeakerNamePanel(QWidget):
    """Collapsible panel for mapping speaker IDs to friendly names.

    Emits names_changed whenever any name is edited.
    """

    names_changed = pyqtSignal(dict)  # {speaker_id: name}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._speaker_ids = []
        self._name_edits = {}  # speaker_id -> QLineEdit
        self._speaker_names = {}  # speaker_id -> name str
        self._collapsed = False
        self._setup_ui()
        self.hide()  # hidden until speakers exist

    def _setup_ui(self):
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(4)

        # Header row with toggle
        header_row = QHBoxLayout()
        self._toggle_btn = QPushButton("\u25bc Speakers")
        self._toggle_btn.setObjectName("speakerPanelToggle")
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setStyleSheet(
            "text-align: left; font-weight: bold; color: #89b4fa; "
            "font-size: 13px; padding: 4px 0; border: none;"
        )
        self._toggle_btn.clicked.connect(self._toggle_collapsed)
        header_row.addWidget(self._toggle_btn)
        header_row.addStretch()
        self._main_layout.addLayout(header_row)

        # Container for speaker rows (collapsible)
        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(8, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        self._main_layout.addWidget(self._rows_container)

    def set_speakers(self, segments, speaker_names=None):
        """Populate panel from transcript segments and optional existing names.

        Args:
            segments: list of TranscriptSegment
            speaker_names: dict of {speaker_id: name} or None
        """
        self._speaker_ids = _extract_speakers(segments)
        self._speaker_names = dict(speaker_names) if speaker_names else {}

        if not self._speaker_ids:
            self.hide()
            return

        self.show()
        self._toggle_btn.setText(f"\u25bc Speakers ({len(self._speaker_ids)} detected)")

        # Clear existing rows
        self._name_edits.clear()
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Build rows
        for i, speaker_id in enumerate(self._speaker_ids):
            row = QHBoxLayout()
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 2, 0, 2)

            # Color swatch
            color = SPEAKER_COLORS[i % len(SPEAKER_COLORS)]
            swatch = QLabel("\u25cf")
            swatch.setStyleSheet(f"color: {color}; font-size: 16px;")
            swatch.setFixedWidth(20)
            row_layout.addWidget(swatch)

            # Speaker ID label
            id_label = QLabel(speaker_id)
            id_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
            id_label.setFixedWidth(100)
            row_layout.addWidget(id_label)

            # Arrow
            arrow = QLabel("\u2192")
            arrow.setStyleSheet("color: #585b70;")
            arrow.setFixedWidth(20)
            row_layout.addWidget(arrow)

            # Name edit
            name_edit = QLineEdit()
            name_edit.setPlaceholderText("Enter name...")
            name_edit.setMaximumHeight(28)
            existing_name = self._speaker_names.get(speaker_id, "")
            if existing_name:
                name_edit.setText(existing_name)
            name_edit.textChanged.connect(self._on_name_changed)
            row_layout.addWidget(name_edit)

            self._name_edits[speaker_id] = name_edit
            self._rows_layout.addWidget(row_widget)

    def get_speaker_names(self):
        """Return current speaker name mappings (only non-empty names)."""
        names = {}
        for speaker_id, edit in self._name_edits.items():
            name = edit.text().strip()
            if name:
                names[speaker_id] = name
        return names

    def focus_speaker(self, speaker_id):
        """Focus the name edit for the given speaker ID."""
        if speaker_id in self._name_edits:
            if self._collapsed:
                self._toggle_collapsed()
            self._name_edits[speaker_id].setFocus()
            self._name_edits[speaker_id].selectAll()

    def _on_name_changed(self, text):
        """Emit names_changed whenever any name field changes."""
        self.names_changed.emit(self.get_speaker_names())

    def _toggle_collapsed(self):
        self._collapsed = not self._collapsed
        self._rows_container.setVisible(not self._collapsed)
        arrow = "\u25b6" if self._collapsed else "\u25bc"
        count = len(self._speaker_ids)
        self._toggle_btn.setText(f"{arrow} Speakers ({count} detected)")
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_speaker_name_panel.py -v`
Expected: All 2 PASS

**Step 5: Commit**

```bash
git add app/ui/speaker_name_panel.py tests/test_speaker_name_panel.py
git commit -m "feat: add SpeakerNamePanel widget for speaker name mapping"
```

---

## Task 6: SegmentWidget — Individual Transcript Row

**Files:**
- Create: `app/ui/segment_widget.py`
- Test: `tests/test_segment_widget.py` (new file)

**Step 1: Write the failing tests**

Create `tests/test_segment_widget.py`:

```python
"""Tests for SegmentWidget logic."""
import unittest
from app.transcription.transcriber import TranscriptSegment


class TestSegmentWidgetHelpers(unittest.TestCase):

    def test_format_time(self):
        from app.ui.segment_widget import _format_time
        self.assertEqual(_format_time(0), "00:00:00")
        self.assertEqual(_format_time(65), "00:01:05")
        self.assertEqual(_format_time(3661), "01:01:01")

    def test_display_speaker_with_name(self):
        from app.ui.segment_widget import _display_speaker
        self.assertEqual(
            _display_speaker("SPEAKER_00", {"SPEAKER_00": "Alice"}),
            "Alice"
        )

    def test_display_speaker_without_name(self):
        from app.ui.segment_widget import _display_speaker
        self.assertEqual(
            _display_speaker("SPEAKER_00", {}),
            "SPEAKER_00"
        )

    def test_display_speaker_empty(self):
        from app.ui.segment_widget import _display_speaker
        self.assertEqual(_display_speaker("", {}), "")


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_segment_widget.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Create SegmentWidget**

Create `app/ui/segment_widget.py`:

```python
"""Individual transcript segment row widget."""
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction

from app.ui.transcript_viewer import SPEAKER_COLORS


def _format_time(seconds):
    """Format seconds as HH:MM:SS."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _display_speaker(speaker_id, speaker_names):
    """Return display name for a speaker, falling back to ID."""
    if not speaker_id:
        return ""
    if speaker_names and speaker_id in speaker_names and speaker_names[speaker_id]:
        return speaker_names[speaker_id]
    return speaker_id


class SegmentWidget(QWidget):
    """A single transcript segment row: [play] [timestamp] [speaker] [text].

    Supports:
    - Play button to trigger audio playback
    - Double-click text to edit inline
    - Right-click context menu with "Revert to Original"
    - Speaker label click to focus speaker name panel
    """

    play_requested = pyqtSignal(int)       # segment index
    stop_requested = pyqtSignal()
    text_edited = pyqtSignal(int, str)     # segment index, new text
    text_reverted = pyqtSignal(int)        # segment index
    speaker_clicked = pyqtSignal(str)      # speaker ID

    def __init__(self, index, segment, speaker_color="#cdd6f4",
                 speaker_name="", parent=None):
        super().__init__(parent)
        self._index = index
        self._segment = segment
        self._speaker_color = speaker_color
        self._speaker_name = speaker_name
        self._editing = False
        self._playing = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        # Play button
        self.play_btn = QPushButton("\u25b6")
        self.play_btn.setObjectName("segmentPlayBtn")
        self.play_btn.setFixedSize(28, 28)
        self.play_btn.setStyleSheet(
            "QPushButton { font-size: 11px; border-radius: 14px; "
            "background-color: #313244; border: 1px solid #45475a; padding: 0; }"
            "QPushButton:hover { background-color: #45475a; }"
        )
        self.play_btn.clicked.connect(self._on_play_clicked)
        layout.addWidget(self.play_btn)

        # Timestamp
        start_ts = _format_time(self._segment.start)
        end_ts = _format_time(self._segment.end)
        self.timestamp_label = QLabel(f"[{start_ts} \u2192 {end_ts}]")
        self.timestamp_label.setStyleSheet(
            "color: #6c7086; font-family: Consolas; font-size: 11px;"
        )
        self.timestamp_label.setFixedWidth(160)
        layout.addWidget(self.timestamp_label)

        # Speaker label
        display_name = self._speaker_name or self._segment.speaker
        self.speaker_label = QLabel(f"{display_name}:" if display_name else "")
        self.speaker_label.setStyleSheet(
            f"color: {self._speaker_color}; font-weight: bold; font-size: 13px;"
        )
        if display_name:
            self.speaker_label.setFixedWidth(120)
            self.speaker_label.setCursor(Qt.CursorShape.PointingHandCursor)
            self.speaker_label.mousePressEvent = self._on_speaker_clicked
        else:
            self.speaker_label.setFixedWidth(0)
        layout.addWidget(self.speaker_label)

        # Text label (normal mode)
        self.text_label = QLabel(self._segment.text)
        self.text_label.setStyleSheet("color: #cdd6f4; font-size: 13px;")
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.text_label.mouseDoubleClickEvent = self._on_text_double_clicked
        self.text_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.text_label.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.text_label, 1)

        # Text edit (edit mode) — hidden by default
        self.text_edit = QLineEdit()
        self.text_edit.hide()
        self.text_edit.returnPressed.connect(self._finish_edit)
        layout.addWidget(self.text_edit, 1)

        # Edit indicator
        self.edit_indicator = QLabel("\u270e")  # pencil icon
        self.edit_indicator.setStyleSheet("color: #f9e2af; font-size: 12px;")
        self.edit_indicator.setFixedWidth(16)
        self.edit_indicator.setToolTip("This segment has been edited")
        self.edit_indicator.setVisible(bool(self._segment.original_text))
        layout.addWidget(self.edit_indicator)

    def update_speaker(self, speaker_names):
        """Update the displayed speaker name."""
        display = _display_speaker(self._segment.speaker, speaker_names)
        if display:
            self.speaker_label.setText(f"{display}:")
            self.speaker_label.setFixedWidth(120)
        else:
            self.speaker_label.setText("")
            self.speaker_label.setFixedWidth(0)

    def set_playing(self, playing):
        """Update play button state."""
        self._playing = playing
        self.play_btn.setText("\u23f9" if playing else "\u25b6")

    def _on_play_clicked(self):
        if self._playing:
            self.stop_requested.emit()
        else:
            self.play_requested.emit(self._index)

    def _on_speaker_clicked(self, event):
        if self._segment.speaker:
            self.speaker_clicked.emit(self._segment.speaker)

    def _on_text_double_clicked(self, event):
        self._start_edit()

    def _start_edit(self):
        if self._editing:
            return
        self._editing = True
        self.text_edit.setText(self.text_label.text())
        self.text_label.hide()
        self.text_edit.show()
        self.text_edit.setFocus()
        self.text_edit.selectAll()

    def _finish_edit(self):
        if not self._editing:
            return
        self._editing = False
        new_text = self.text_edit.text().strip()
        if new_text and new_text != self._segment.text:
            self.text_label.setText(new_text)
            self.text_edited.emit(self._index, new_text)
            self.edit_indicator.setVisible(True)
        self.text_edit.hide()
        self.text_label.show()

    def cancel_edit(self):
        """Cancel editing without saving."""
        if not self._editing:
            return
        self._editing = False
        self.text_edit.hide()
        self.text_label.show()

    def _show_context_menu(self, pos):
        menu = QMenu(self)

        edit_action = QAction("Edit Text", self)
        edit_action.triggered.connect(self._start_edit)
        menu.addAction(edit_action)

        if self._segment.original_text:
            revert_action = QAction("Revert to Original", self)
            revert_action.triggered.connect(lambda: self._revert())
            menu.addAction(revert_action)

        menu.exec(self.text_label.mapToGlobal(pos))

    def _revert(self):
        self.text_label.setText(self._segment.original_text)
        self.edit_indicator.setVisible(False)
        self.text_reverted.emit(self._index)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._editing:
            self.cancel_edit()
        else:
            super().keyPressEvent(event)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_segment_widget.py -v`
Expected: All 4 PASS

**Step 5: Commit**

```bash
git add app/ui/segment_widget.py tests/test_segment_widget.py
git commit -m "feat: add SegmentWidget for interactive transcript rows"
```

---

## Task 7: TranscriptViewer — Rewrite with New Components

This is the largest task. The existing `TranscriptViewer` gets rewritten to use the new sub-components.

**Files:**
- Rewrite: `app/ui/transcript_viewer.py` (full rewrite)

**Step 1: Rewrite TranscriptViewer**

Replace the entire contents of `app/ui/transcript_viewer.py` with:

```python
"""Transcript viewer with interactive segment editing, playback, and speaker naming."""
import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QProgressBar, QFileDialog, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal

from app.transcription.transcriber import TranscriptResult, TranscriptSegment


# Speaker colors for visual distinction — shared with other modules
SPEAKER_COLORS = [
    "#89b4fa",  # blue
    "#a6e3a1",  # green
    "#fab387",  # peach
    "#f5c2e7",  # pink
    "#94e2d5",  # teal
    "#f9e2af",  # yellow
    "#cba6f7",  # mauve
    "#f38ba8",  # red
]


class TranscriptViewer(QWidget):
    """Displays transcription results with interactive segments.

    Features:
    - Per-segment play buttons for audio clip playback
    - Inline text editing with undo (original_text preservation)
    - Speaker name panel for mapping IDs to friendly names
    - Recording info header with rename
    """

    transcribe_requested = pyqtSignal(str)  # audio file path
    transcript_changed = pyqtSignal()       # emitted when text or names change
    speaker_names_changed = pyqtSignal(dict)  # emitted when speaker names change

    def __init__(self, parent=None):
        super().__init__(parent)
        self._transcript = None
        self._speaker_colors = {}
        self._speaker_names = {}
        self._segment_widgets = []
        self._audio_path = None
        self._player = None
        self._playing_index = -1
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Recording header (set by main_window)
        # Placeholder — actual RecordingHeader added by main_window above the tabs

        # Header row: title + transcribe button
        header = QHBoxLayout()
        title = QLabel("Transcript")
        title.setObjectName("sectionHeader")
        header.addWidget(title)
        header.addStretch()

        self.transcribe_btn = QPushButton("Transcribe")
        self.transcribe_btn.setEnabled(False)
        self.transcribe_btn.clicked.connect(self._on_transcribe_clicked)
        header.addWidget(self.transcribe_btn)

        layout.addLayout(header)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.hide()
        layout.addWidget(self.status_label)

        # Speaker name panel
        from app.ui.speaker_name_panel import SpeakerNamePanel
        self.speaker_panel = SpeakerNamePanel()
        self.speaker_panel.names_changed.connect(self._on_speaker_names_changed)
        layout.addWidget(self.speaker_panel)

        # Scroll area for segment widgets
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet(
            "QScrollArea { border: 1px solid #313244; border-radius: 6px; "
            "background-color: #181825; }"
        )

        self._segments_container = QWidget()
        self._segments_container.setStyleSheet("background-color: #181825;")
        self._segments_layout = QVBoxLayout(self._segments_container)
        self._segments_layout.setContentsMargins(8, 8, 8, 8)
        self._segments_layout.setSpacing(2)
        self._segments_layout.addStretch()

        self.scroll_area.setWidget(self._segments_container)

        # Placeholder text
        self._placeholder = QLabel(
            "Transcript will appear here after recording and transcription..."
        )
        self._placeholder.setStyleSheet("color: #585b70; padding: 20px;")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._segments_layout.insertWidget(0, self._placeholder)

        layout.addWidget(self.scroll_area, 1)

        # Export buttons
        export_row = QHBoxLayout()
        export_row.addStretch()

        self.export_txt_btn = QPushButton("Export TXT")
        self.export_txt_btn.setEnabled(False)
        self.export_txt_btn.clicked.connect(lambda: self._export("txt"))
        export_row.addWidget(self.export_txt_btn)

        self.export_srt_btn = QPushButton("Export SRT")
        self.export_srt_btn.setEnabled(False)
        self.export_srt_btn.clicked.connect(lambda: self._export("srt"))
        export_row.addWidget(self.export_srt_btn)

        self.export_json_btn = QPushButton("Export JSON")
        self.export_json_btn.setEnabled(False)
        self.export_json_btn.clicked.connect(lambda: self._export("json"))
        export_row.addWidget(self.export_json_btn)

        layout.addLayout(export_row)

    def _ensure_player(self):
        """Lazily create the SegmentPlayer."""
        if self._player is None:
            from app.audio.segment_player import SegmentPlayer
            self._player = SegmentPlayer(self)
            self._player.playback_finished.connect(self._on_playback_finished)

    def set_audio_path(self, path):
        self._audio_path = path
        self.transcribe_btn.setEnabled(path is not None)
        if self._player:
            self._player.stop()
            self._player.clear_cache()

    def set_speaker_names(self, names):
        """Set speaker names from loaded speaker_names.json."""
        self._speaker_names = dict(names) if names else {}

    def _on_transcribe_clicked(self):
        if self._audio_path:
            self.transcribe_requested.emit(self._audio_path)

    def show_progress(self, message):
        self.progress_bar.show()
        self.status_label.setText(message)
        self.status_label.show()

    def hide_progress(self):
        self.progress_bar.hide()
        self.status_label.hide()

    def display_transcript(self, transcript, speaker_names=None):
        """Render transcript with interactive segment widgets."""
        self._transcript = transcript
        if speaker_names is not None:
            self._speaker_names = dict(speaker_names)

        # Stop any playing audio
        if self._player:
            self._player.stop()
        self._playing_index = -1

        # Assign colors to speakers
        speakers = sorted(set(s.speaker for s in transcript.segments if s.speaker))
        self._speaker_colors = {}
        for i, speaker in enumerate(speakers):
            self._speaker_colors[speaker] = SPEAKER_COLORS[i % len(SPEAKER_COLORS)]

        # Clear existing segment widgets
        self._segment_widgets.clear()
        while self._segments_layout.count():
            item = self._segments_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Hide placeholder
        self._placeholder = None

        # Build segment widgets
        from app.ui.segment_widget import SegmentWidget

        for i, seg in enumerate(transcript.segments):
            color = self._speaker_colors.get(seg.speaker, "#cdd6f4")
            name = self._speaker_names.get(seg.speaker, "")

            widget = SegmentWidget(
                index=i,
                segment=seg,
                speaker_color=color,
                speaker_name=name,
                parent=self._segments_container,
            )
            widget.play_requested.connect(self._on_play_requested)
            widget.stop_requested.connect(self._on_stop_requested)
            widget.text_edited.connect(self._on_text_edited)
            widget.text_reverted.connect(self._on_text_reverted)
            widget.speaker_clicked.connect(self._on_speaker_label_clicked)

            self._segment_widgets.append(widget)
            self._segments_layout.addWidget(widget)

        self._segments_layout.addStretch()

        # Update speaker panel
        self.speaker_panel.set_speakers(transcript.segments, self._speaker_names)

        # Enable export buttons
        self.export_txt_btn.setEnabled(True)
        self.export_srt_btn.setEnabled(True)
        self.export_json_btn.setEnabled(True)

    def get_speaker_count(self):
        """Return number of unique speakers in current transcript."""
        if not self._transcript:
            return 0
        return len(set(s.speaker for s in self._transcript.segments if s.speaker))

    # --- Audio playback ---

    def _on_play_requested(self, index):
        if not self._audio_path:
            return
        self._ensure_player()

        # Stop previous
        if self._playing_index >= 0 and self._playing_index < len(self._segment_widgets):
            self._segment_widgets[self._playing_index].set_playing(False)

        seg = self._transcript.segments[index]
        self._player.play_segment(self._audio_path, seg.start, seg.end)
        self._playing_index = index
        self._segment_widgets[index].set_playing(True)

    def _on_stop_requested(self):
        if self._player:
            self._player.stop()
        if self._playing_index >= 0 and self._playing_index < len(self._segment_widgets):
            self._segment_widgets[self._playing_index].set_playing(False)
        self._playing_index = -1

    def _on_playback_finished(self):
        if self._playing_index >= 0 and self._playing_index < len(self._segment_widgets):
            self._segment_widgets[self._playing_index].set_playing(False)
        self._playing_index = -1

    # --- Text editing ---

    def _on_text_edited(self, index, new_text):
        seg = self._transcript.segments[index]
        if not seg.original_text:
            seg.original_text = seg.text
        seg.text = new_text
        self.transcript_changed.emit()

    def _on_text_reverted(self, index):
        seg = self._transcript.segments[index]
        if seg.original_text:
            seg.text = seg.original_text
            seg.original_text = ""
        self.transcript_changed.emit()

    # --- Speaker names ---

    def _on_speaker_names_changed(self, names):
        self._speaker_names = names
        for widget in self._segment_widgets:
            widget.update_speaker(names)
        self.speaker_names_changed.emit(names)

    def _on_speaker_label_clicked(self, speaker_id):
        self.speaker_panel.focus_speaker(speaker_id)

    # --- Export ---

    def _export(self, format_type):
        if not self._transcript:
            return

        filters = {
            "txt": "Text Files (*.txt)",
            "srt": "SRT Subtitle Files (*.srt)",
            "json": "JSON Files (*.json)",
        }

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Transcript", "", filters[format_type]
        )

        if not path:
            return

        names = self._speaker_names

        if format_type == "txt":
            content = self._transcript.to_text(speaker_names=names)
        elif format_type == "srt":
            content = self._transcript.to_srt(speaker_names=names)
        elif format_type == "json":
            content = json.dumps(
                self._transcript.to_dict(speaker_names=names), indent=2
            )

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def _format_time(self, seconds):
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
```

**Important:** The `SPEAKER_COLORS` list stays at the top of this file since `speaker_name_panel.py` and `segment_widget.py` import it from here.

**Step 2: Fix imports in segment_widget.py and speaker_name_panel.py**

Both files import `SPEAKER_COLORS` from `app.ui.transcript_viewer`. Since we're rewriting `transcript_viewer.py`, the import path stays the same — no change needed.

**Step 3: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All pass

**Step 4: Commit**

```bash
git add app/ui/transcript_viewer.py
git commit -m "feat: rewrite TranscriptViewer with interactive segment widgets"
```

---

## Task 8: MainWindow — Integration

Wire up the new components: RecordingHeader, speaker_names.json load/save, transcript editing save, recording rename.

**Files:**
- Modify: `app/main_window.py`

**Step 1: Update imports and setup**

Add to the imports at the top of `app/main_window.py`:

```python
from app.ui.recording_header import RecordingHeader
```

**Step 2: Add RecordingHeader to UI setup**

In `_setup_ui()`, add the recording header above the tabs (after line 111 `right_layout.setContentsMargins(8, 8, 8, 8)`):

```python
        # Recording header (above tabs)
        self.recording_header = RecordingHeader()
        right_layout.addWidget(self.recording_header)
```

**Step 3: Connect new signals in `_connect_signals()`**

Add after line 151:

```python
        # Recording header
        self.recording_header.name_changed.connect(self._on_recording_renamed)

        # Transcript editing
        self.transcript_viewer.transcript_changed.connect(self._save_transcript)
        self.transcript_viewer.speaker_names_changed.connect(self._save_speaker_names)
```

**Step 4: Update `_on_recording_finished()` to set recording header**

After line 226 (`self.tabs.setCurrentWidget(self.transcript_viewer)`), add:

```python
        # Update recording header
        self.recording_header.set_recording(session)
```

**Step 5: Update `_display_final_transcript()` to load/save speaker names**

Replace the existing `_display_final_transcript` method:

```python
    def _display_final_transcript(self, result):
        self.transcript_viewer.hide_progress()

        # Load speaker names if available
        speaker_names = {}
        if self._current_session:
            names_path = Path(self._current_session["directory"]) / "speaker_names.json"
            if names_path.exists():
                try:
                    with open(names_path, "r", encoding="utf-8") as f:
                        speaker_names = json.load(f)
                except (json.JSONDecodeError, OSError):
                    pass

        self.transcript_viewer.display_transcript(result, speaker_names=speaker_names)
        self.status_label.setText("Transcription complete.")

        # Update recording header with speaker count
        if self._current_session:
            self.recording_header.set_recording(
                self._current_session,
                speaker_count=self.transcript_viewer.get_speaker_count()
            )

        # Save transcript
        self._save_transcript()
```

**Step 6: Add new methods for saving and renaming**

Add these methods to MainWindow:

```python
    def _save_transcript(self):
        """Save current transcript to session directory."""
        if not self._current_session or not self.transcript_viewer._transcript:
            return
        result = self.transcript_viewer._transcript
        names = self.transcript_viewer._speaker_names

        transcript_path = Path(self._current_session["directory"]) / "transcript.json"
        with open(transcript_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(speaker_names=names), f, indent=2, ensure_ascii=False)

        txt_path = Path(self._current_session["directory"]) / "transcript.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(result.to_text(speaker_names=names))

        self.recordings_list.refresh()

    def _save_speaker_names(self, names):
        """Save speaker names to session directory."""
        if not self._current_session:
            return
        names_path = Path(self._current_session["directory"]) / "speaker_names.json"
        with open(names_path, "w", encoding="utf-8") as f:
            json.dump(names, f, indent=2, ensure_ascii=False)

        # Also re-save transcript with updated names
        self._save_transcript()

    def _on_recording_renamed(self, new_name):
        """Handle recording rename from RecordingHeader."""
        if not self._current_session:
            return
        self._current_session["name"] = new_name

        # Update metadata.json
        meta_path = Path(self._current_session["directory"]) / "metadata.json"
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                metadata["name"] = new_name
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, OSError) as e:
                print(f"Failed to save recording name: {e}")

        self.recordings_list.refresh()
```

**Step 7: Update `_on_recording_selected()` to load speaker names and set header**

Replace the existing `_on_recording_selected` method:

```python
    def _on_recording_selected(self, metadata):
        """Load a past recording for viewing/transcription."""
        self._current_session = metadata

        audio_files = metadata.get("audio_files", {})
        audio_path = audio_files.get("combined") or audio_files.get("system") or audio_files.get("mic")
        self.transcript_viewer.set_audio_path(audio_path)

        # Load speaker names
        speaker_names = {}
        names_path = Path(metadata["directory"]) / "speaker_names.json"
        if names_path.exists():
            try:
                with open(names_path, "r", encoding="utf-8") as f:
                    speaker_names = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        # Load existing transcript if available
        transcript_path = Path(metadata["directory"]) / "transcript.json"
        if transcript_path.exists():
            try:
                with open(transcript_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                result = TranscriptResult(
                    segments=[TranscriptSegment(**s) for s in data["segments"]],
                    language=data.get("language", ""),
                    duration=data.get("duration", 0),
                )
                self.transcript_viewer.display_transcript(result, speaker_names=speaker_names)
            except Exception:
                pass

        # Update recording header
        self.recording_header.set_recording(
            metadata,
            speaker_count=self.transcript_viewer.get_speaker_count()
        )

        # Load notes
        self.notes_panel.set_session_dir(metadata["directory"])

        # Switch to transcript tab
        self.tabs.setCurrentWidget(self.transcript_viewer)
```

**Step 8: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All pass

**Step 9: Commit**

```bash
git add app/main_window.py
git commit -m "feat: integrate RecordingHeader, speaker names, and transcript editing into MainWindow"
```

---

## Task 9: RecordingsList — Show Friendly Names

**Files:**
- Modify: `app/ui/recordings_list.py:73-90`

**Step 1: Update the display text in `refresh()` to use friendly name**

In `recordings_list.py`, modify the display text building (around line 73-87):

```python
            # Format display text
            name = metadata.get("name", "")
            started = metadata.get("started_at", "")
            try:
                dt = datetime.fromisoformat(started)
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                date_str = started

            duration = metadata.get("duration", 0)
            dur_str = self._format_duration(duration)

            has_transcript = (Path(metadata["directory"]) / "transcript.json").exists()
            transcript_indicator = " [T]" if has_transcript else ""

            if name:
                text = f"{name}  |  {date_str}  |  {dur_str}{transcript_indicator}"
            else:
                text = f"{date_str}  |  {dur_str}{transcript_indicator}"
```

**Step 2: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All pass

**Step 3: Commit**

```bash
git add app/ui/recordings_list.py
git commit -m "feat: show recording friendly name in recordings list"
```

---

## Task 10: Stylesheet Updates + Final Polish

**Files:**
- Modify: `resources/style.qss`
- Modify: `CLAUDE.md`

**Step 1: Add styles for new widgets to `resources/style.qss`**

Append to end of `style.qss`:

```css
/* Recording Header */
#recordingName {
    font-size: 16px;
    font-weight: bold;
    color: #cdd6f4;
}

#recordingInfo {
    color: #a6adc8;
    font-size: 12px;
}

#renameButton {
    padding: 4px 8px;
    min-height: 16px;
    font-size: 12px;
}

/* Segment Widgets */
#segmentPlayBtn {
    font-size: 11px;
    border-radius: 14px;
    background-color: #313244;
    border: 1px solid #45475a;
    padding: 0;
    min-height: 28px;
    min-width: 28px;
    max-height: 28px;
    max-width: 28px;
}

#segmentPlayBtn:hover {
    background-color: #45475a;
}

/* Speaker Name Panel */
#speakerPanelToggle {
    text-align: left;
    font-weight: bold;
    color: #89b4fa;
    font-size: 13px;
    padding: 4px 0;
    border: none;
    background: transparent;
}
```

**Step 2: Update CLAUDE.md**

Update the "Current Features" section to include the new capabilities. Add to the features list:

```
- Speaker name assignment: map SPEAKER_00/01 to real names (persisted per recording)
- Inline transcript editing: double-click to fix text, with undo to original
- Audio clip playback: play button per segment to verify accuracy
- Recording info header: see which recording is loaded, rename recordings
```

Update the project structure to include new files:

```
    audio/
      __init__.py
      segment_player.py               # Audio clip playback via sounddevice
    ui/
      recording_header.py             # Recording info display + rename
      speaker_name_panel.py           # Collapsible speaker name editing panel
      segment_widget.py               # Individual transcript segment row widget
```

**Step 3: Run all tests to verify everything works**

Run: `python -m pytest tests/ -v`
Expected: All pass

**Step 4: Commit**

```bash
git add resources/style.qss CLAUDE.md
git commit -m "feat: add styles for new transcript widgets, update docs"
```

---

## Task 11: Integration Test — Manual Verification

**Step 1: Launch the application**

Run: `python main.py`

**Step 2: Verify the following manually:**

1. Load a past recording — recording header should appear with name, date, duration
2. Click "Rename" — should be able to enter a new name, recordings list updates
3. Speaker panel should show detected speakers with editable name fields
4. Enter speaker names — transcript should update immediately
5. Double-click a segment's text — should enter edit mode
6. Edit text and press Enter — pencil icon should appear
7. Right-click edited segment — "Revert to Original" should restore original text
8. Click play button on a segment — should hear that audio clip
9. Click play on another segment — previous should stop, new one plays
10. Export TXT/SRT — should use friendly names
11. Close and reopen the recording — names and edits should persist

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat: transcript enhancement suite — complete implementation"
```

---

Plan complete and saved to `docs/plans/2026-03-08-transcript-enhancement-plan.md`. Two execution options:

**1. Subagent-Driven (this session)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** — Open new session with executing-plans, batch execution with checkpoints

Which approach?
