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
        """Play audio from start_sec to end_sec of the given file."""
        self.stop()

        # Load and cache audio
        if self._cached_path != audio_path:
            data, sr = sf.read(audio_path, dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
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
