"""Per-process audio capture using Windows 11 COM API.

Windows 11 (Build 22000+) introduced per-process audio loopback capture
via ActivateAudioInterfaceAsync with AUDIOCLIENT_ACTIVATION_PARAMS.
This module provides a pipeline for capturing audio from specific PIDs
and mixing the results into a single output stream.
"""
import logging
import threading
import time
from math import gcd
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from app.utils.platform_info import is_windows_11
from app.recording._process_com import (
    activate_process_loopback as _default_activator,
    hresult_name,
)

logger = logging.getLogger(__name__)


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


def _trim_and_mix(per_stream_chunks):
    """Trim every stream's chunk to the shortest length, mix with equal-weight mean,
    return (mixed_chunk, tails_per_stream).

    Args:
        per_stream_chunks: {pid: np.ndarray(float32)}.

    Returns:
        (mixed: np.ndarray, tails: {pid: np.ndarray}) — tails may be empty arrays
        when a stream happened to produce exactly the minimum length this tick.
    """
    if not per_stream_chunks:
        return np.array([], dtype=np.float32), {}

    lengths = {pid: len(c) for pid, c in per_stream_chunks.items()}
    min_len = min(lengths.values())

    aligned = []
    tails = {}
    for pid, c in per_stream_chunks.items():
        aligned.append(c[:min_len])
        tails[pid] = c[min_len:] if len(c) > min_len else np.array([], dtype=np.float32)

    if min_len == 0:
        return np.array([], dtype=np.float32), tails
    mixed = np.mean(np.stack(aligned, axis=0), axis=0).astype(np.float32)
    return mixed, tails


def _convert_dtype(raw_bytes, format_tag, bits_per_sample):
    """Convert a packed byte buffer from Windows into a float32 numpy array.

    Args:
        raw_bytes: bytes from IAudioCaptureClient.GetBuffer.
        format_tag: "float32", "s16", or "s24".
        bits_per_sample: container width (32 for s24-in-s32, 16 for s16, 32 for float32).

    Returns:
        1D float32 numpy array (interleaved channels flattened — caller reshapes).

    Raises:
        ValueError: for unknown formats. We only support formats process-loopback
        is documented to emit.
    """
    if format_tag == "float32":
        return np.frombuffer(raw_bytes, dtype=np.float32).copy()
    if format_tag == "s16":
        samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32)
        return samples / 32768.0
    if format_tag == "s24":
        # 24-bit samples in 32-bit containers: high 24 bits are the data.
        samples = np.frombuffer(raw_bytes, dtype=np.int32).astype(np.float32)
        return (samples / 256.0) / 8388608.0   # >>8 then /2^23
    raise ValueError(f"Unsupported format_tag: {format_tag!r}")


class _Resampler:
    """Polyphase resampler that accumulates odd-length inputs across calls.

    resample_poly produces cleanest output when the input length is a multiple
    of `down`. We buffer the remainder across calls so short packets (common
    when WASAPI hands over partial ticks) don't introduce clicks at boundaries.
    """

    def __init__(self, native_rate, target_rate):
        self.native_rate = native_rate
        self.target_rate = target_rate
        g = gcd(native_rate, target_rate)
        self._up = target_rate // g
        self._down = native_rate // g
        self._buf = np.array([], dtype=np.float32)

    def push(self, arr):
        """Append arr to the internal buffer, resample a multiple of down, return it."""
        if arr.size == 0 and self._buf.size == 0:
            return np.array([], dtype=np.float32)
        if self._up == self._down:
            # Passthrough fast path.
            if self._buf.size > 0:
                out = np.concatenate([self._buf, arr])
                self._buf = np.array([], dtype=np.float32)
                return out
            return arr.astype(np.float32, copy=False)

        combined = np.concatenate([self._buf, arr]) if self._buf.size else arr
        # Take the largest multiple of down; carry the rest.
        usable = (len(combined) // self._down) * self._down
        if usable == 0:
            self._buf = combined
            return np.array([], dtype=np.float32)
        chunk = combined[:usable]
        self._buf = combined[usable:]
        return resample_poly(chunk, self._up, self._down).astype(np.float32)


class ProcessCaptureStream:
    """Captures audio from a single process. Owns the COM objects.

    activate/read/release is synchronous and non-thread-owning — the caller
    (ProcessAudioCapture) provides the single polling thread. Keeping this
    class stateless re: threading makes it easy to unit-test with fakes.
    """

    def __init__(self, pid, sample_rate=16000, activator=None):
        self.pid = pid
        self.sample_rate = sample_rate
        self.is_active = False
        self.native_rate = 0
        self.native_channels = 0
        self.native_format = "float32"
        self.last_error = None
        # True once any non-silent sample has arrived. Conferencing apps that
        # opt out of process-loopback deliver only SILENT-flagged packets, so
        # this flag never flips — the UI uses it to warn the user.
        self.received_audio = False
        self._client = None
        self._capture_client = None
        self._native_frame_bytes = None
        self._resampler = None
        self._pre_resample_buf = np.array([], dtype=np.float32)
        self._post_mix_tail = np.array([], dtype=np.float32)
        self._activator = activator if activator is not None else _default_activator

    def activate(self):
        """Synchronously activate the per-process audio client.

        Returns True on success, False on any failure. On failure, last_error
        holds the HRESULT name (never raises).
        """
        try:
            result = self._activator(self.pid)
        except Exception as e:
            self.last_error = f"activation_exception: {e}"
            return False

        # Real path returns (_ActivatedContext, hr); fakes return (obj, hr)
        # where obj has native_rate/channels/format attrs directly.
        client, hr = result

        if hr != 0 or client is None:
            self.last_error = hresult_name(hr) if hr != 0 else "activation_null_client"
            return False

        # Resolve the underlying audio_client: for _ActivatedContext this is
        # the actual IAudioClient pointer; for fakes without an audio_client
        # attribute, fall back to the container itself.
        self._client = getattr(client, "audio_client", client)
        self._capture_client = getattr(client, "capture_client", None)
        self._native_frame_bytes = getattr(client, "native_frame_bytes", None)
        self.native_rate = getattr(client, "native_rate", 48000)
        self.native_channels = getattr(client, "native_channels", 2)
        self.native_format = getattr(client, "native_format", "float32")
        self._resampler = _Resampler(self.native_rate, self.sample_rate)
        self.is_active = True
        return True

    def put_back_tail(self, tail):
        if tail.size > 0:
            if self._post_mix_tail.size:
                self._post_mix_tail = np.concatenate([self._post_mix_tail, tail])
            else:
                self._post_mix_tail = tail

    def read_available(self):
        """Drain all ready packets from the capture client. Non-blocking.

        Returns a list of 16 kHz mono float32 chunks, ready for the mixer.
        On device invalidation, marks is_active=False and returns whatever
        was already drained this call.
        """
        chunks = []

        if self._post_mix_tail.size > 0:
            chunks.append(self._post_mix_tail)
            self._post_mix_tail = np.array([], dtype=np.float32)

        if not self.is_active:
            return chunks

        # Test path: pull from an injected iterator. Real path: re-enter
        # read_next_packet until it reports "no more packets". The real path
        # MUST NOT cache a generator — process-loopback clients produce
        # packets continuously, and a generator that returns once goes dead.
        try:
            if hasattr(self, "_packet_source") and self._packet_source is not None:
                packets = self._drain_test_source()
            else:
                packets = self._drain_real_source()
        except Exception as e:
            logger.exception("ProcessCaptureStream %s drain error", self.pid)
            self.is_active = False
            self.last_error = f"read_exception: {e}"
            return chunks

        for pkt in packets:
            hr = pkt.get("hr", 0)
            if hr == 0x88890004:   # AUDCLNT_E_DEVICE_INVALIDATED
                self.is_active = False
                self.last_error = hresult_name(hr)
                break
            raw = pkt.get("raw")
            frames = pkt.get("frames", 0)
            flags = pkt.get("flags", 0)
            if raw is None or frames == 0:
                continue

            if flags & 0x2:   # AUDCLNT_BUFFERFLAGS_SILENT
                mono_native = np.zeros(frames, dtype=np.float32)
            else:
                arr = _convert_dtype(
                    raw,
                    format_tag=self.native_format,
                    bits_per_sample=self._bits_for_format(self.native_format),
                )
                if self.native_channels > 1:
                    arr = arr.reshape(-1, self.native_channels).mean(axis=1)
                mono_native = arr.astype(np.float32)
                if not self.received_audio and np.any(mono_native):
                    self.received_audio = True

            resampled = self._resampler.push(mono_native)
            if resampled.size > 0:
                chunks.append(resampled)

        return chunks

    def _drain_test_source(self):
        """Pull all remaining packets from the test-injected iterator."""
        packets = []
        while True:
            try:
                pkt = next(self._packet_source)
            except StopIteration:
                break
            if pkt is None:
                break
            packets.append(pkt)
        return packets

    def _drain_real_source(self):
        """Real-COM path: loop read_next_packet until no more packets are ready."""
        if self._capture_client is None or self._native_frame_bytes is None:
            return []
        from app.recording._process_com import read_next_packet
        packets = []
        while True:
            data, frames, flags, hr = read_next_packet(
                self._capture_client, self._native_frame_bytes,
            )
            if hr != 0:
                # Device invalidated or other error — surface it via a sentinel
                # packet so the processing loop marks us inactive uniformly.
                packets.append({"raw": None, "frames": 0, "flags": 0, "hr": hr})
                break
            if data is None and frames == 0:
                break   # no more packets ready this tick
            packets.append({"raw": data, "frames": frames, "flags": flags, "hr": 0})
        return packets

    @staticmethod
    def _bits_for_format(fmt):
        return {"float32": 32, "s16": 16, "s24": 32}.get(fmt, 32)

    def release(self):
        # Best-effort Stop() on the real IAudioClient; fakes without a Stop
        # method are silently skipped.
        if self._client is not None:
            stopper = getattr(self._client, "Stop", None)
            if callable(stopper):
                try:
                    stopper()
                except Exception:
                    logger.exception("Error stopping audio client for PID %s", self.pid)
        self.is_active = False
        self._client = None
        self._capture_client = None
        self._native_frame_bytes = None
        self._resampler = None
        self._pre_resample_buf = np.array([], dtype=np.float32)
        self._post_mix_tail = np.array([], dtype=np.float32)
        if hasattr(self, "_packet_source"):
            self._packet_source = None


class ProcessAudioCapture:
    """Mixer for N per-process loopback streams. Owns a single polling thread.

    PIDs are fixed at construction time; add/remove during a session is
    deliberately out of scope (see design Q3). Pause/resume drains the client
    buffers but discards the data, matching AudioStream / LoopbackStream.
    """

    def __init__(self, pids, sample_rate=16000, level_callback=None,
                 enable_buffer=True, pid_lost_callback=None,
                 capture_lost_callback=None):
        self.pids = list(pids)
        self.sample_rate = sample_rate
        self._level_callback = level_callback
        self._pid_lost_callback = pid_lost_callback
        self._capture_lost_callback = capture_lost_callback
        self._enable_buffer = enable_buffer
        self._streams = {}                     # {pid: ProcessCaptureStream}
        self._running = False
        self._paused = False
        self._all_chunks = []
        self._thread = None
        self._active_last_tick = set()
        self._crashed = False
        self.capture_status = {}

    def set_level_callback(self, fn):
        self._level_callback = fn

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def _mixer_loop(self):
        try:
            while self._running:
                if self._paused:
                    for s in list(self._streams.values()):
                        if s.is_active:
                            try:
                                s.read_available()
                            except Exception:
                                logger.exception("Stream %s crashed during paused drain", s.pid)
                                s.is_active = False
                    time.sleep(0.010)
                    continue

                per_stream_chunks = {}
                for pid, s in list(self._streams.items()):
                    was_active = pid in self._active_last_tick
                    if not s.is_active:
                        if was_active:
                            self._active_last_tick.discard(pid)
                            self._emit_pid_lost(pid, s.last_error)
                        continue
                    self._active_last_tick.add(pid)
                    try:
                        chunks = s.read_available()
                        if chunks:
                            per_stream_chunks[pid] = np.concatenate(chunks)
                    except Exception as e:
                        logger.exception("Stream %s crashed", pid)
                        s.is_active = False
                        s.last_error = f"exception: {e}"
                        self._active_last_tick.discard(pid)
                        self._emit_pid_lost(pid, s.last_error)

                if per_stream_chunks:
                    mixed, tails = _trim_and_mix(per_stream_chunks)
                    for pid, tail in tails.items():
                        self._streams[pid].put_back_tail(tail)
                    if mixed.size > 0:
                        if self._enable_buffer:
                            self._all_chunks.append(mixed)
                        if self._level_callback:
                            self._level_callback(mixed)

                if self._streams and not any(s.is_active for s in self._streams.values()):
                    self._emit_capture_lost()
                    break

                time.sleep(0.010)
        except Exception:
            logger.exception("Mixer loop crashed unexpectedly")
            self._crashed = True

    def _emit_pid_lost(self, pid, error):
        if self._pid_lost_callback:
            try:
                self._pid_lost_callback(pid, error or "unknown")
            except Exception:
                logger.exception("pid_lost callback raised")

    def _emit_capture_lost(self):
        if self._capture_lost_callback:
            try:
                self._capture_lost_callback()
            except Exception:
                logger.exception("capture_lost callback raised")

    def start(self, skip_stream_creation=False):
        """Activate all streams in parallel, launch mixer thread.

        Returns:
            {"total": N, "active": K, "failures": {pid: error_name}}

        The caller (DualAudioCapture) is expected to raise RuntimeError when
        active == 0 AND the caller considers that a hard failure. This method
        never raises for partial failures.
        """
        from concurrent.futures import ThreadPoolExecutor

        if not skip_stream_creation:
            # Real path: create ProcessCaptureStream instances for each pid.
            self._streams = {
                pid: ProcessCaptureStream(pid=pid, sample_rate=self.sample_rate)
                for pid in self.pids
            }

        failures = {}
        if self._streams:
            with ThreadPoolExecutor(max_workers=max(len(self._streams), 1)) as ex:
                futures = {
                    pid: ex.submit(s.activate)
                    for pid, s in self._streams.items()
                }
                for pid, fut in futures.items():
                    try:
                        ok = fut.result(timeout=6.0)
                    except Exception as e:
                        ok = False
                        self._streams[pid].last_error = f"activation_exception: {e}"
                    if not ok:
                        failures[pid] = self._streams[pid].last_error or "unknown"

        active_pids = {pid for pid, s in self._streams.items() if s.is_active}
        self._active_last_tick = set(active_pids)

        status = {
            "total": len(self._streams),
            "active": len(active_pids),
            "failures": failures,
        }
        self.capture_status = status

        # Launch the mixer only if at least one stream is active.
        if active_pids:
            self._running = True
            self._thread = threading.Thread(target=self._mixer_loop, daemon=True)
            self._thread.start()

        return status

    def stop(self):
        """Stop the mixer thread and release all streams. Returns a result dict."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

        for s in self._streams.values():
            try:
                s.release()
            except Exception:
                logger.exception("Error releasing stream %s", s.pid)

        mixed = (np.concatenate(self._all_chunks, axis=0)
                 if self._all_chunks else np.array([], dtype=np.float32))

        result = {
            "mixed_audio": mixed,
            "active_pids": self.active_pids,
            "crashed": self._crashed,
        }
        return result

    def save_to_file(self, filepath):
        """Write buffered mixed audio to a WAV file. Returns the path, or None if empty."""
        import soundfile as sf
        if not self._all_chunks:
            return None
        data = np.concatenate(self._all_chunks, axis=0)
        if data.size == 0:
            return None
        sf.write(str(filepath), data, self.sample_rate)
        return str(filepath)

    def get_audio_data(self):
        """Return buffered mixed audio as a mono float32 array."""
        if not self._all_chunks:
            return np.array([], dtype=np.float32)
        return np.concatenate(self._all_chunks, axis=0)

    @property
    def is_active(self):
        return self._running and any(s.is_active for s in self._streams.values())

    @property
    def has_received_audio(self):
        """True once any stream has produced a non-silent sample."""
        return any(
            getattr(s, "received_audio", False) for s in self._streams.values()
        )

    @property
    def active_pids(self):
        return [pid for pid, s in self._streams.items() if s.is_active]
