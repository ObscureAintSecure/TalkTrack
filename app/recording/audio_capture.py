import logging
import threading
import time
import queue
import numpy as np
import sounddevice as sd
import soundfile as sf
from pathlib import Path

logger = logging.getLogger(__name__)


class AudioStream:
    """Captures audio from a single input device (mic) using sounddevice."""

    def __init__(self, device_index, sample_rate=16000, channels=1,
                 level_callback=None):
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.channels = channels
        self._level_callback = level_callback
        self._stream = None
        self._buffer = queue.Queue()
        self._recording = False
        self._paused = False
        self._all_chunks = []

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.debug("Audio stream status: %s", status)
        if self._recording and not self._paused:
            chunk = indata.copy()
            self._buffer.put(chunk)
            self._all_chunks.append(chunk)
            if self._level_callback is not None:
                self._level_callback(chunk)

    def start(self):
        self._recording = True
        self._paused = False
        self._all_chunks = []

        try:
            self._stream = sd.InputStream(
                device=self.device_index,
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=self._audio_callback,
                dtype="float32",
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


class LoopbackStream:
    """Captures system audio via WASAPI loopback using PyAudioWPatch."""

    def __init__(self, device_name=None, sample_rate=16000, level_callback=None):
        self._device_name = device_name
        self._target_rate = sample_rate
        self._level_callback = level_callback
        self._stream = None
        self._pa = None
        self._recording = False
        self._paused = False
        self._all_chunks = []
        self._native_rate = None
        self._native_channels = None

    def _find_loopback_device(self):
        """Find the WASAPI loopback device matching the selected output."""
        import pyaudiowpatch as pyaudio
        self._pa = pyaudio.PyAudio()

        # Find WASAPI host API
        wasapi_idx = None
        for i in range(self._pa.get_host_api_count()):
            api = self._pa.get_host_api_info_by_index(i)
            if "WASAPI" in api["name"]:
                wasapi_idx = i
                break

        if wasapi_idx is None:
            raise RuntimeError("WASAPI host API not found")

        # Find loopback device
        target_name = self._device_name
        for loopback in self._pa.get_loopback_device_info_generator():
            if target_name and target_name in loopback["name"]:
                return loopback

        # If no match, use default output's loopback
        wasapi_info = self._pa.get_host_api_info_by_index(wasapi_idx)
        default_output = self._pa.get_device_info_by_index(
            wasapi_info["defaultOutputDevice"]
        )
        for loopback in self._pa.get_loopback_device_info_generator():
            if default_output["name"] in loopback["name"]:
                return loopback

        # Last resort: first available loopback device
        for loopback in self._pa.get_loopback_device_info_generator():
            return loopback

        raise RuntimeError("No WASAPI loopback device found")

    def start(self):
        import pyaudiowpatch as pyaudio

        self._recording = True
        self._paused = False
        self._all_chunks = []

        loopback_dev = self._find_loopback_device()
        self._native_rate = int(loopback_dev["defaultSampleRate"])
        self._native_channels = loopback_dev["maxInputChannels"]

        logger.info(
            "WASAPI loopback: %s (index=%d, rate=%d, ch=%d)",
            loopback_dev["name"], loopback_dev["index"],
            self._native_rate, self._native_channels,
        )

        self._stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=self._native_channels,
            rate=self._native_rate,
            input=True,
            input_device_index=loopback_dev["index"],
            frames_per_buffer=1024,
            stream_callback=self._callback,
        )
        self._stream.start_stream()

    def _callback(self, in_data, frame_count, time_info, status):
        import pyaudiowpatch as pyaudio

        if self._recording and not self._paused:
            # Convert bytes to float32 numpy array
            chunk = np.frombuffer(in_data, dtype=np.float32).copy()
            chunk = chunk.reshape(-1, self._native_channels)

            # Downmix to mono
            if self._native_channels > 1:
                mono = chunk.mean(axis=1).astype(np.float32)
            else:
                mono = chunk.flatten()

            # Resample if needed
            if self._native_rate != self._target_rate:
                from scipy.signal import resample
                target_len = int(len(mono) * self._target_rate / self._native_rate)
                mono = resample(mono, target_len).astype(np.float32)

            self._all_chunks.append(mono)
            if self._level_callback is not None:
                self._level_callback(mono)

        return (None, pyaudio.paContinue)

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def stop(self):
        self._recording = False
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._pa:
            self._pa.terminate()
            self._pa = None

    def get_audio_data(self):
        if not self._all_chunks:
            return np.array([], dtype=np.float32)
        return np.concatenate(self._all_chunks, axis=0)

    def save_to_file(self, filepath):
        data = self.get_audio_data()
        if data.size == 0:
            return None
        sf.write(str(filepath), data, self._target_rate)
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
        self._mic_level_callback = None
        self._system_level_callback = None

    def set_level_callbacks(self, mic_callback, system_callback):
        """Set callbacks to receive audio level data from each channel."""
        self._mic_level_callback = mic_callback
        self._system_level_callback = system_callback

    def start(self, output_dir):
        """Start recording both mic and system audio."""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "DualAudioCapture.start: mic_device=%s, loopback_device=%s, "
            "capture_mode=%s",
            self.mic_device, self.loopback_device, self.capture_mode,
        )

        # Microphone capture (sounddevice)
        if self.mic_device is not None:
            self.mic_stream = AudioStream(
                device_index=self.mic_device,
                sample_rate=self.sample_rate,
                channels=1,
                level_callback=self._mic_level_callback,
            )
            self.mic_stream.start()
            logger.info("Mic stream started on device %s", self.mic_device)
        else:
            logger.warning("No mic device selected")

        # System audio capture (PyAudioWPatch WASAPI loopback)
        if self.loopback_device is not None:
            try:
                # Get device name for matching to loopback device
                dev_info = sd.query_devices(self.loopback_device)
                device_name = dev_info.get("name", "")
                logger.info("System audio: looking for loopback of '%s'", device_name)

                self.loopback_stream = LoopbackStream(
                    device_name=device_name,
                    sample_rate=self.sample_rate,
                    level_callback=self._system_level_callback,
                )
                self.loopback_stream.start()
            except Exception as e:
                logger.error("Failed to start system audio capture: %s", e)
                self.loopback_stream = None
        else:
            logger.warning("No system audio device selected")

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
