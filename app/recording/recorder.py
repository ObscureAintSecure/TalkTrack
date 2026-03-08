import os
import time
import json
import subprocess
from datetime import datetime
from pathlib import Path
from enum import Enum

from PyQt6.QtCore import QObject, pyqtSignal, QThread

from app.recording.audio_capture import DualAudioCapture


class RecordingState(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PAUSED = "paused"
    STOPPING = "stopping"
    PROCESSING = "processing"


class Recorder(QObject):
    """Orchestrates audio recording with state management."""

    state_changed = pyqtSignal(RecordingState)
    time_updated = pyqtSignal(float)
    recording_finished = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self._state = RecordingState.IDLE
        self._capture = None
        self._timer_thread = None
        self._current_session = None

    @property
    def state(self):
        return self._state

    def _set_state(self, state):
        self._state = state
        self.state_changed.emit(state)

    def start_recording(self, mic_device=None, loopback_device=None):
        """Start a new recording session."""
        if self._state != RecordingState.IDLE:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(self.config.get("output", "directory"))
        session_dir = output_dir / f"recording_{timestamp}"
        session_dir.mkdir(parents=True, exist_ok=True)

        self._current_session = {
            "id": timestamp,
            "directory": str(session_dir),
            "started_at": datetime.now().isoformat(),
            "mic_device": mic_device,
            "loopback_device": loopback_device,
        }

        sample_rate = self.config.get("audio", "sample_rate")

        self._capture = DualAudioCapture(
            mic_device=mic_device,
            loopback_device=loopback_device,
            sample_rate=sample_rate,
        )

        try:
            self._capture.start(session_dir)
            self._set_state(RecordingState.RECORDING)
            self._start_timer()
        except Exception as e:
            self.error_occurred.emit(str(e))
            self._set_state(RecordingState.IDLE)

    def pause_recording(self):
        if self._state != RecordingState.RECORDING:
            return
        self._capture.pause()
        self._set_state(RecordingState.PAUSED)

    def resume_recording(self):
        if self._state != RecordingState.PAUSED:
            return
        self._capture.resume()
        self._set_state(RecordingState.RECORDING)

    def stop_recording(self):
        """Stop recording and save files."""
        if self._state not in (RecordingState.RECORDING, RecordingState.PAUSED):
            return

        self._set_state(RecordingState.STOPPING)
        self._stop_timer()

        try:
            audio_files = self._capture.stop()

            self._current_session["stopped_at"] = datetime.now().isoformat()
            self._current_session["duration"] = self._capture.get_elapsed_time()
            self._current_session["audio_files"] = audio_files

            # Convert to output format if needed
            output_format = self.config.get("output", "format")
            if output_format == "mp3":
                self._convert_to_mp3(audio_files)

            # Save session metadata
            meta_path = Path(self._current_session["directory"]) / "metadata.json"
            with open(meta_path, "w") as f:
                json.dump(self._current_session, f, indent=2)

            self._set_state(RecordingState.IDLE)
            self.recording_finished.emit(self._current_session)
        except Exception as e:
            self.error_occurred.emit(f"Error stopping recording: {e}")
            self._set_state(RecordingState.IDLE)

    def _convert_to_mp3(self, audio_files):
        """Convert WAV files to MP3 using FFmpeg."""
        for key, wav_path in audio_files.items():
            if wav_path and wav_path.endswith(".wav"):
                mp3_path = wav_path.replace(".wav", ".mp3")
                try:
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", wav_path, "-codec:a", "libmp3lame",
                         "-qscale:a", "2", mp3_path],
                        capture_output=True, check=True,
                    )
                    audio_files[key + "_mp3"] = mp3_path
                except (subprocess.CalledProcessError, FileNotFoundError):
                    pass  # FFmpeg not available or conversion failed

    def _start_timer(self):
        self._timer_running = True
        self._timer_thread = TimerThread(self._capture)
        self._timer_thread.time_tick.connect(self.time_updated.emit)
        self._timer_thread.start()

    def _stop_timer(self):
        self._timer_running = False
        if self._timer_thread:
            self._timer_thread.stop()
            self._timer_thread.wait()
            self._timer_thread = None

    def get_elapsed_time(self):
        if self._capture:
            return self._capture.get_elapsed_time()
        return 0


class TimerThread(QThread):
    time_tick = pyqtSignal(float)

    def __init__(self, capture):
        super().__init__()
        self._capture = capture
        self._running = True

    def run(self):
        while self._running:
            self.time_tick.emit(self._capture.get_elapsed_time())
            self.msleep(100)

    def stop(self):
        self._running = False
