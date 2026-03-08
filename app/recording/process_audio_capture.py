"""Per-process audio capture using Windows 11 COM API.

Windows 11 (Build 22000+) introduced per-process audio loopback capture
via ActivateAudioInterfaceAsync with AUDIOCLIENT_ACTIVATION_PARAMS.
This module provides a pipeline for capturing audio from specific PIDs
and mixing the results into a single output stream.
"""
import threading
import time
import numpy as np
import soundfile as sf

from app.utils.platform_info import is_windows_11


def stereo_to_mono(data):
    """Downmix multi-channel audio to mono by averaging channels.

    Args:
        data: numpy array of shape (samples, channels)

    Returns:
        numpy array of shape (samples,) with averaged channels
    """
    if data.ndim == 1:
        return data
    return data.mean(axis=1).astype(np.float32)


def mix_audio_chunks(chunks):
    """Mix multiple audio arrays by averaging, with zero-padding for length alignment.

    Args:
        chunks: list of 1D numpy float32 arrays

    Returns:
        numpy array with mixed audio, or empty array if no chunks
    """
    if not chunks:
        return np.array([], dtype=np.float32)

    if len(chunks) == 1:
        return chunks[0].copy()

    # Find the maximum length across all chunks
    max_len = max(len(c) for c in chunks)

    # Pad shorter chunks with zeros to match the longest
    padded = []
    for chunk in chunks:
        if len(chunk) < max_len:
            padded.append(np.pad(chunk, (0, max_len - len(chunk))).astype(np.float32))
        else:
            padded.append(chunk.astype(np.float32))

    # Average all chunks
    stacked = np.stack(padded, axis=0)
    return stacked.mean(axis=0).astype(np.float32)


class ProcessCaptureStream:
    """Captures audio from a single process by PID using Win11 COM API.

    Uses ActivateAudioInterfaceAsync with AUDIOCLIENT_ACTIVATION_PARAMS
    to capture loopback audio from a specific process. The actual COM
    capture loop (_read_audio_packets) is a placeholder until the
    full COM interop is implemented.
    """

    def __init__(self, pid, sample_rate=16000, channels=1):
        self.pid = pid
        self.sample_rate = sample_rate
        self.channels = channels
        self._recording = False
        self._paused = False
        self._all_chunks = []
        self._thread = None
        self._lock = threading.Lock()

    def start(self):
        """Start capturing audio from the target process."""
        if not is_windows_11():
            raise RuntimeError(
                "Per-process audio capture requires Windows 11 (Build 22000+)"
            )
        self._recording = True
        self._paused = False
        self._all_chunks = []
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self):
        """Background thread: initialize COM, capture audio, clean up."""
        try:
            # COM initialization would happen here:
            # comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            self._read_audio_packets()
        finally:
            # COM cleanup would happen here:
            # comtypes.CoUninitialize()
            pass

    def _read_audio_packets(self):
        """Placeholder for COM-based audio packet reading.

        In the full implementation, this would:
        1. Create AUDIOCLIENT_ACTIVATION_PARAMS for the target PID
        2. Call ActivateAudioInterfaceAsync to get an IAudioClient
        3. Initialize the client in loopback mode
        4. Read audio packets in a loop, converting to float32
        """
        while self._recording:
            time.sleep(0.01)

    def pause(self):
        """Pause audio capture (stops storing chunks)."""
        self._paused = True

    def resume(self):
        """Resume audio capture after pause."""
        self._paused = False

    def stop(self):
        """Stop capturing and wait for background thread to finish."""
        self._recording = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def get_audio_data(self):
        """Return all captured audio as a mono numpy array."""
        with self._lock:
            if not self._all_chunks:
                return np.array([], dtype=np.float32)
            data = np.concatenate(self._all_chunks, axis=0)
        if data.ndim > 1:
            data = stereo_to_mono(data)
        return data

    def save_to_file(self, filepath):
        """Save captured audio to a WAV file."""
        data = self.get_audio_data()
        if data.size == 0:
            return None
        sf.write(str(filepath), data, self.sample_rate)
        return str(filepath)

    @property
    def is_active(self):
        """Whether the capture stream is currently recording."""
        return self._recording


class ProcessAudioCapture:
    """Manages multiple ProcessCaptureStreams and mixes their output.

    Provides the same interface as AudioStream (start/stop/pause/resume/
    get_audio_data/save_to_file) so it can be used as a drop-in replacement
    for loopback capture in DualAudioCapture.
    """

    def __init__(self, pids, sample_rate=16000):
        self.pids = list(pids)
        self.sample_rate = sample_rate
        self._streams = {}
        self._recording = False

    def start(self):
        """Create and start a ProcessCaptureStream for each PID."""
        self._recording = True
        for pid in self.pids:
            stream = ProcessCaptureStream(
                pid=pid, sample_rate=self.sample_rate
            )
            stream.start()
            self._streams[pid] = stream

    def add_pid(self, pid):
        """Add a new PID to capture during a live recording session."""
        if pid in self._streams:
            return
        stream = ProcessCaptureStream(pid=pid, sample_rate=self.sample_rate)
        if self._recording:
            stream.start()
        self._streams[pid] = stream
        if pid not in self.pids:
            self.pids.append(pid)

    def remove_pid(self, pid):
        """Remove a PID from capture during a live recording session."""
        if pid in self._streams:
            self._streams[pid].stop()
            del self._streams[pid]
        if pid in self.pids:
            self.pids.remove(pid)

    def pause(self):
        """Pause all active capture streams."""
        for stream in self._streams.values():
            stream.pause()

    def resume(self):
        """Resume all capture streams."""
        for stream in self._streams.values():
            stream.resume()

    def stop(self):
        """Stop all capture streams."""
        self._recording = False
        for stream in self._streams.values():
            stream.stop()

    def get_audio_data(self):
        """Collect audio from all streams and return mixed result."""
        chunks = []
        for stream in self._streams.values():
            data = stream.get_audio_data()
            if data.size > 0:
                chunks.append(data)
        return mix_audio_chunks(chunks)

    def save_to_file(self, filepath):
        """Save mixed audio from all streams to a WAV file."""
        data = self.get_audio_data()
        if data.size == 0:
            return None
        sf.write(str(filepath), data, self.sample_rate)
        return str(filepath)

    @property
    def is_active(self):
        """Whether any capture stream is currently recording."""
        return any(s.is_active for s in self._streams.values())

    @property
    def active_pids(self):
        """List of PIDs with active capture streams."""
        return [pid for pid, s in self._streams.items() if s.is_active]
