import logging
import threading
import time
import numpy as np
import sounddevice as sd
import soundfile as sf
from pathlib import Path

from app.recording.process_audio_capture import ProcessAudioCapture, _Resampler

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
        self._recording = False
        self._paused = False
        self._all_chunks = []
        self._muted = False
        self._gain = 1.0

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.debug("Audio stream status: %s", status)
        if self._recording and not self._paused:
            chunk = indata.copy()
            if self._gain != 1.0:
                chunk *= self._gain
                np.clip(chunk, -1.0, 1.0, out=chunk)
            if self._muted:
                chunk.fill(0.0)
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

    def set_muted(self, muted):
        """Mute or unmute the mic. Muted streams keep recording but write silence."""
        self._muted = bool(muted)

    def set_gain(self, gain):
        """Set the mic gain multiplier. Values outside [-1, 1] after multiplication are hard-clipped."""
        self._gain = float(gain)

    def stop(self):
        self._recording = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                logger.exception("Error closing audio stream on device %s",
                                 self.device_index)
            finally:
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
        # Polyphase resampler built on start() once native_rate is known.
        # Stateful across callback invocations — the previous FFT-based
        # scipy.signal.resample call resampled each chunk in isolation,
        # producing discontinuities at chunk boundaries that sounded like
        # faint crackle during remote speech.
        self._resampler = None

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

        try:
            loopback_dev = self._find_loopback_device()
            self._native_rate = int(loopback_dev["defaultSampleRate"])
            self._native_channels = loopback_dev["maxInputChannels"]

            logger.info(
                "WASAPI loopback: %s (index=%d, rate=%d, ch=%d)",
                loopback_dev["name"], loopback_dev["index"],
                self._native_rate, self._native_channels,
            )

            self._resampler = _Resampler(self._native_rate, self._target_rate)

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
        except Exception:
            # _find_loopback_device creates self._pa before it can fail —
            # don't leak the PyAudio instance on any startup error.
            self._recording = False
            self.stop()
            raise

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

            # Stateful polyphase resample. _Resampler carries odd-length
            # remainders across callbacks so there's no discontinuity at
            # chunk boundaries.
            if self._resampler is not None:
                mono = self._resampler.push(mono)

            if mono.size == 0:
                return (None, pyaudio.paContinue)

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
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                logger.exception("Error closing loopback stream")
            finally:
                self._stream = None
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                logger.exception("Error terminating PyAudio")
            finally:
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
                 capture_mode="legacy", app_pids=None, mic_device_2=None):
        self.sample_rate = sample_rate
        self.mic_device = mic_device
        self.mic_device_2 = mic_device_2
        self.loopback_device = loopback_device
        self.mic_stream = None
        self.mic_stream_2 = None
        self.system_stream = None
        self._recording = False
        self._start_time = None
        self._elapsed = 0
        self.capture_mode = capture_mode
        self.app_pids = app_pids or []
        self._mic_level_callback = None
        self._system_level_callback = None
        # Silence detection on system audio — guarded by mic activity.
        # If the user is talking (mic RMS > threshold) anywhere inside the
        # silence window, the silence timer resets. Prevents auto-stop
        # during a monologue when the remote is muted or on dead air.
        self._silence_threshold = 0.005  # RMS below this = silence
        self._silence_duration = 30  # seconds of silence before firing
        self._silence_callback = None
        self._silent_since = None  # timestamp when silence started
        self._silence_fired = False  # only fire once per silence stretch
        self._last_mic_active_time = None  # updated from mic callbacks
        self._muted = False
        self.mic_gain = 1.0
        self._pid_lost_callback = None
        self._capture_lost_callback = None
        self._capture_status = None
        # Wall-clock capture start per stream (time.monotonic). The system
        # side can start ~1s before the mic (per-app COM activation); tracks
        # are front-pad aligned at stop so t=0 matches across files.
        self._mic_start_ts = None
        self._system_start_ts = None

    def set_capture_event_callbacks(self, pid_lost=None, capture_lost=None):
        """Register callbacks for ProcessAudioCapture events (per-app mode only)."""
        self._pid_lost_callback = pid_lost
        self._capture_lost_callback = capture_lost

    def set_level_callbacks(self, mic_callback, system_callback):
        """Set callbacks to receive audio level data from each channel."""
        self._mic_level_callback = mic_callback
        self._system_level_callback = system_callback

    def set_muted(self, muted):
        """Mute or unmute all microphone streams in this capture session."""
        self._muted = bool(muted)
        if self.mic_stream is not None:
            self.mic_stream.set_muted(self._muted)
        if self.mic_stream_2 is not None:
            self.mic_stream_2.set_muted(self._muted)

    def set_gain(self, gain):
        """Set the mic gain multiplier for all microphone streams in this capture session."""
        self.mic_gain = float(gain)
        if self.mic_stream is not None:
            self.mic_stream.set_gain(self.mic_gain)
        if self.mic_stream_2 is not None:
            self.mic_stream_2.set_gain(self.mic_gain)

    @property
    def is_muted(self):
        return self._muted

    def set_silence_detection(self, threshold, duration, callback):
        """Configure silence detection on the system audio stream.

        Args:
            threshold: RMS level below which audio counts as silence.
            duration: Seconds of continuous silence before callback fires.
            callback: Called (with silence duration) when silence threshold met.
        """
        self._silence_threshold = threshold
        self._silence_duration = duration
        self._silence_callback = callback
        self._silent_since = None
        self._silence_fired = False

    def start(self, output_dir):
        """Start recording both mic and system audio."""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "DualAudioCapture.start: mic_device=%s, loopback_device=%s, "
            "capture_mode=%s",
            self.mic_device, self.loopback_device, self.capture_mode,
        )

        # System audio capture. In per-app mode with PIDs, use ProcessAudioCapture.
        # Otherwise use WASAPI loopback if a device is set.
        # Note: system capture activates BEFORE mic capture so a total per-app
        # failure raises before the mic stream is opened.
        self.system_stream = None
        self._capture_status = None
        self._mic_start_ts = None
        self._system_start_ts = None

        def _system_cb(chunk):
            if self._system_level_callback is not None:
                self._system_level_callback(chunk)
            self._check_silence(chunk)

        if self.capture_mode == "per_app" and self.app_pids:
            self.system_stream = ProcessAudioCapture(
                pids=self.app_pids,
                sample_rate=self.sample_rate,
                level_callback=_system_cb,
                pid_lost_callback=self._pid_lost_callback,
                capture_lost_callback=self._capture_lost_callback,
            )
            status = self.system_stream.start()
            self._capture_status = status
            if status["active"] == 0:
                raise RuntimeError(
                    f"Per-app capture failed for all selected apps: {status['failures']}"
                )
            self._system_start_ts = time.monotonic()
        elif self.loopback_device is not None:
            try:
                dev_info = sd.query_devices(self.loopback_device)
                device_name = dev_info.get("name", "")
                logger.info("System audio: looking for loopback of '%s'", device_name)

                self.system_stream = LoopbackStream(
                    device_name=device_name,
                    sample_rate=self.sample_rate,
                    level_callback=_system_cb,
                )
                self.system_stream.start()
                self._system_start_ts = time.monotonic()
            except Exception as e:
                logger.error("Failed to start system audio capture: %s", e)
                self.system_stream = None
        else:
            logger.warning("No system audio device selected")

        # Wrap the outer mic level callback so every chunk also updates
        # _last_mic_active_time for the silence-guard check.
        def _mic_cb(chunk):
            self._note_mic_activity(chunk)
            if self._mic_level_callback is not None:
                self._mic_level_callback(chunk)

        # Microphone capture (sounddevice). A mic failure must not orphan the
        # already-running system capture (COM clients / PyAudio / mixer thread).
        try:
            if self.mic_device is not None:
                self.mic_stream = AudioStream(
                    device_index=self.mic_device,
                    sample_rate=self.sample_rate,
                    channels=1,
                    level_callback=_mic_cb,
                )
                self.mic_stream.start()
                self._mic_start_ts = time.monotonic()
                if self._muted:
                    self.mic_stream.set_muted(True)
                if self.mic_gain != 1.0:
                    self.mic_stream.set_gain(self.mic_gain)
                logger.info("Mic stream started on device %s", self.mic_device)
            else:
                logger.warning("No mic device selected")

            # Second microphone capture (optional)
            if self.mic_device_2 is not None:
                self.mic_stream_2 = AudioStream(
                    device_index=self.mic_device_2,
                    sample_rate=self.sample_rate,
                    channels=1,
                    level_callback=_mic_cb,
                )
                self.mic_stream_2.start()
                if self._muted:
                    self.mic_stream_2.set_muted(True)
                if self.mic_gain != 1.0:
                    self.mic_stream_2.set_gain(self.mic_gain)
                logger.info("Mic stream 2 started on device %s", self.mic_device_2)
        except Exception:
            self._stop_streams_quietly()
            raise

        self._recording = True
        self._start_time = time.time()

    def _stop_streams_quietly(self):
        """Best-effort stop of every started stream; never raises."""
        for stream in (self.mic_stream, self.mic_stream_2, self.system_stream):
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    logger.exception("Error stopping stream during cleanup")
        self.mic_stream = None
        self.mic_stream_2 = None
        self.system_stream = None

    def pause(self):
        if self.mic_stream:
            self.mic_stream.pause()
        if self.mic_stream_2:
            self.mic_stream_2.pause()
        if self.system_stream:
            self.system_stream.pause()
        if self._start_time:
            self._elapsed += time.time() - self._start_time
            self._start_time = None
        self._silent_since = None  # don't count paused time as silence

    def resume(self):
        if self.mic_stream:
            self.mic_stream.resume()
        if self.mic_stream_2:
            self.mic_stream_2.resume()
        if self.system_stream:
            self.system_stream.resume()
        self._start_time = time.time()
        self._silent_since = None
        self._silence_fired = False  # allow re-detection after resume

    def stop(self):
        """Stop recording and return paths to saved audio files.

        Every stop/save step is individually guarded: a failing device (e.g.
        mic unplugged mid-call) or file write must not prevent stopping the
        other streams or saving the other tracks.
        """
        self._recording = False
        if self._start_time:
            self._elapsed += time.time() - self._start_time
            self._start_time = None

        results = {"mic": None, "system": None, "combined": None}

        # Stop all streams first so nothing keeps capturing while we save.
        for label, stream in (("mic", self.mic_stream),
                              ("mic 2", self.mic_stream_2),
                              ("system", self.system_stream)):
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    logger.exception("Failed to stop %s stream", label)

        try:
            mic_data = self._get_mixed_mic_data()
        except Exception:
            logger.exception("Failed to read mic audio")
            mic_data = np.array([], dtype=np.float32)

        sys_data = np.array([], dtype=np.float32)
        if self.system_stream:
            try:
                sys_data = self.system_stream.get_audio_data()
                if sys_data.ndim > 1:
                    sys_data = sys_data.mean(axis=1).astype(np.float32)
            except Exception:
                logger.exception("Failed to read system audio")

        # Align tracks on wall-clock start so the remote side doesn't lead
        # the mic by the system-activation delay for the whole recording.
        mic_data, sys_data = self._apply_start_alignment(mic_data, sys_data)

        try:
            if mic_data.size > 0:
                mic_path = self.output_dir / "mic_audio.wav"
                sf.write(str(mic_path), mic_data, self.sample_rate)
                results["mic"] = str(mic_path)
        except Exception:
            logger.exception("Failed to save mic audio")

        try:
            if sys_data.size > 0:
                sys_path = self.output_dir / "system_audio.wav"
                sf.write(str(sys_path), sys_data, self.sample_rate)
                results["system"] = str(sys_path)
        except Exception:
            logger.exception("Failed to save system audio")

        # Create combined audio for transcription
        try:
            combined = self._create_combined_audio(mic_data, sys_data)
            if combined is not None:
                combined_path = self.output_dir / "combined_audio.wav"
                sf.write(str(combined_path), combined, self.sample_rate)
                results["combined"] = str(combined_path)
        except Exception:
            logger.exception("Failed to create combined audio")

        return results

    # Offsets beyond this are clock anomalies, not real startup skew.
    _MAX_ALIGNMENT_SECONDS = 30.0

    def _apply_start_alignment(self, mic_data, sys_data):
        """Front-pad the later-starting track so t=0 matches wall-clock."""
        if self._mic_start_ts is None or self._system_start_ts is None:
            return mic_data, sys_data
        if mic_data.size == 0 or sys_data.size == 0:
            return mic_data, sys_data
        delta = self._mic_start_ts - self._system_start_ts
        if abs(delta) > self._MAX_ALIGNMENT_SECONDS:
            logger.warning("Implausible stream start offset %.1fs — skipping alignment", delta)
            return mic_data, sys_data
        pad = int(round(abs(delta) * self.sample_rate))
        if pad <= 0:
            return mic_data, sys_data
        zeros = np.zeros(pad, dtype=np.float32)
        if delta > 0:   # mic started later — it's missing leading audio
            mic_data = np.concatenate([zeros, mic_data])
        else:
            sys_data = np.concatenate([zeros, sys_data])
        return mic_data, sys_data

    def _get_mixed_mic_data(self):
        """Get audio from all mic streams, mixed together."""
        mic1 = self.mic_stream.get_audio_data() if self.mic_stream else np.array([], dtype=np.float32)
        mic2 = self.mic_stream_2.get_audio_data() if self.mic_stream_2 else np.array([], dtype=np.float32)

        if mic1.size == 0 and mic2.size == 0:
            return np.array([], dtype=np.float32)
        if mic2.size == 0:
            if mic1.ndim > 1:
                return mic1.mean(axis=1).astype(np.float32)
            return mic1
        if mic1.size == 0:
            if mic2.ndim > 1:
                return mic2.mean(axis=1).astype(np.float32)
            return mic2

        # Both mics have data — ensure mono then mix
        if mic1.ndim > 1:
            mic1 = mic1.mean(axis=1).astype(np.float32)
        if mic2.ndim > 1:
            mic2 = mic2.mean(axis=1).astype(np.float32)

        max_len = max(len(mic1), len(mic2))
        if len(mic1) < max_len:
            mic1 = np.pad(mic1, (0, max_len - len(mic1)))
        if len(mic2) < max_len:
            mic2 = np.pad(mic2, (0, max_len - len(mic2)))

        mixed = mic1 + mic2
        peak = np.abs(mixed).max()
        if peak > 1.0:
            mixed = mixed / peak * 0.95
        return mixed

    def _create_combined_audio(self, mic_data, sys_data):
        """Mix already-aligned mono mic and system tracks into one."""
        if mic_data.size == 0 and sys_data.size == 0:
            return None

        if mic_data.size == 0:
            return sys_data

        if sys_data.size == 0:
            return mic_data

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

    def _note_mic_activity(self, chunk):
        """Called from wrapped mic callbacks. Stamps mic activity.

        Only chunks whose RMS exceeds the silence threshold count as
        activity — ambient noise floor under the threshold is ignored.
        """
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        if rms >= self._silence_threshold:
            self._last_mic_active_time = time.time()

    def _check_silence(self, chunk):
        """Check system audio chunk for silence, fire callback if sustained.

        Mic-aware: if the mic was active within the silence window, reset
        the silence anchor. The callback never fires while the user is
        talking, even if the remote side is dead air.
        """
        if not self._silence_callback or self._silence_fired:
            return
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        now = time.time()
        mic_recent = (
            self._last_mic_active_time is not None
            and (now - self._last_mic_active_time) < self._silence_duration
        )
        if rms < self._silence_threshold and not mic_recent:
            if self._silent_since is None:
                self._silent_since = now
            elif now - self._silent_since >= self._silence_duration:
                self._silence_fired = True
                self._silence_callback(now - self._silent_since)
        else:
            self._silent_since = None

    def system_audio_received(self):
        """True once the system stream has produced any non-silent audio.

        Only meaningful for per-app capture (streams exposing
        has_received_audio). Legacy loopback and no-system configurations
        return True so callers never warn.
        """
        stream = self.system_stream
        if stream is None or not hasattr(stream, "has_received_audio"):
            return True
        return bool(stream.has_received_audio)

    def get_elapsed_time(self):
        """Return elapsed recording time in seconds."""
        if self._start_time:
            return self._elapsed + (time.time() - self._start_time)
        return self._elapsed

    @property
    def is_recording(self):
        return self._recording
