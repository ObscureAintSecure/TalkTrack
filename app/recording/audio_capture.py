import threading
import time
import queue
import numpy as np
import sounddevice as sd
import soundfile as sf
from pathlib import Path


class AudioStream:
    """Captures audio from a single device (mic or loopback)."""

    def __init__(self, device_index, sample_rate=16000, channels=1, is_loopback=False):
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.channels = channels
        self.is_loopback = is_loopback
        self._stream = None
        self._buffer = queue.Queue()
        self._recording = False
        self._paused = False
        self._all_chunks = []

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            print(f"Audio stream status: {status}")
        if self._recording and not self._paused:
            self._buffer.put(indata.copy())
            self._all_chunks.append(indata.copy())

    def start(self):
        self._recording = True
        self._paused = False
        self._all_chunks = []

        extra_settings = None
        if self.is_loopback:
            extra_settings = sd.WasapiSettings(exclusive=False, auto_convert=True)

        try:
            self._stream = sd.InputStream(
                device=self.device_index,
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=self._audio_callback,
                dtype="float32",
                extra_settings=extra_settings if self.is_loopback else None,
            )
            self._stream.start()
        except Exception as e:
            self._recording = False
            raise RuntimeError(f"Failed to start audio stream on device {self.device_index}: {e}")

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def stop(self):
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def get_audio_data(self):
        """Return all recorded audio as a numpy array."""
        if not self._all_chunks:
            return np.array([], dtype=np.float32)
        return np.concatenate(self._all_chunks, axis=0)

    def save_to_file(self, filepath):
        """Save recorded audio to a WAV file."""
        data = self.get_audio_data()
        if data.size == 0:
            return None
        sf.write(str(filepath), data, self.sample_rate)
        return str(filepath)

    @property
    def is_active(self):
        return self._recording and self._stream is not None


class DualAudioCapture:
    """Captures both microphone and system audio simultaneously."""

    def __init__(self, mic_device=None, loopback_device=None, sample_rate=16000,
                 capture_mode="legacy", app_pids=None):
        self.sample_rate = sample_rate
        self.mic_device = mic_device
        self.loopback_device = loopback_device
        self.mic_stream = None
        self.loopback_stream = None
        self._recording = False
        self._start_time = None
        self._elapsed = 0
        self.capture_mode = capture_mode
        self.app_pids = app_pids or []

    def start(self, output_dir):
        """Start recording both mic and system audio."""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        if self.mic_device is not None:
            self.mic_stream = AudioStream(
                device_index=self.mic_device,
                sample_rate=self.sample_rate,
                channels=1,
                is_loopback=False,
            )
            self.mic_stream.start()

        if self.capture_mode == "per_app" and self.app_pids:
            from app.recording.process_audio_capture import ProcessAudioCapture
            self.loopback_stream = ProcessAudioCapture(
                pids=self.app_pids,
                sample_rate=self.sample_rate,
            )
            self.loopback_stream.start()
        elif self.loopback_device is not None:
            self.loopback_stream = AudioStream(
                device_index=self.loopback_device,
                sample_rate=self.sample_rate,
                channels=1,
                is_loopback=True,
            )
            try:
                self.loopback_stream.start()
            except RuntimeError:
                self.loopback_stream = AudioStream(
                    device_index=self.loopback_device,
                    sample_rate=self.sample_rate,
                    channels=2,
                    is_loopback=True,
                )
                self.loopback_stream.start()

        self._recording = True
        self._start_time = time.time()

    def pause(self):
        if self.mic_stream:
            self.mic_stream.pause()
        if self.loopback_stream:
            self.loopback_stream.pause()
        if self._start_time:
            self._elapsed += time.time() - self._start_time
            self._start_time = None

    def resume(self):
        if self.mic_stream:
            self.mic_stream.resume()
        if self.loopback_stream:
            self.loopback_stream.resume()
        self._start_time = time.time()

    def stop(self):
        """Stop recording and return paths to saved audio files."""
        self._recording = False
        if self._start_time:
            self._elapsed += time.time() - self._start_time
            self._start_time = None

        results = {"mic": None, "system": None, "combined": None}

        if self.mic_stream:
            self.mic_stream.stop()
            mic_path = self.output_dir / "mic_audio.wav"
            results["mic"] = self.mic_stream.save_to_file(mic_path)

        if self.loopback_stream:
            self.loopback_stream.stop()
            sys_path = self.output_dir / "system_audio.wav"
            results["system"] = self.loopback_stream.save_to_file(sys_path)

        # Create combined audio for transcription
        combined = self._create_combined_audio()
        if combined is not None:
            combined_path = self.output_dir / "combined_audio.wav"
            sf.write(str(combined_path), combined, self.sample_rate)
            results["combined"] = str(combined_path)

        return results

    def _create_combined_audio(self):
        """Mix mic and system audio into a single track."""
        mic_data = self.mic_stream.get_audio_data() if self.mic_stream else np.array([])
        sys_data = self.loopback_stream.get_audio_data() if self.loopback_stream else np.array([])

        if mic_data.size == 0 and sys_data.size == 0:
            return None

        if mic_data.size == 0:
            if sys_data.ndim > 1:
                return sys_data.mean(axis=1)
            return sys_data

        if sys_data.size == 0:
            if mic_data.ndim > 1:
                return mic_data.mean(axis=1)
            return mic_data

        # Ensure mono
        if mic_data.ndim > 1:
            mic_data = mic_data.mean(axis=1)
        if sys_data.ndim > 1:
            sys_data = sys_data.mean(axis=1)

        # Pad shorter to match longer
        max_len = max(len(mic_data), len(sys_data))
        if len(mic_data) < max_len:
            mic_data = np.pad(mic_data, (0, max_len - len(mic_data)))
        if len(sys_data) < max_len:
            sys_data = np.pad(sys_data, (0, max_len - len(sys_data)))

        # Mix at equal volume, normalize to prevent clipping
        combined = mic_data * 0.5 + sys_data * 0.5
        peak = np.abs(combined).max()
        if peak > 0:
            combined = combined / peak * 0.95
        return combined

    def get_elapsed_time(self):
        """Return elapsed recording time in seconds."""
        if self._start_time:
            return self._elapsed + (time.time() - self._start_time)
        return self._elapsed

    @property
    def is_recording(self):
        return self._recording
