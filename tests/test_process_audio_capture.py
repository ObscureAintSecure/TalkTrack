"""Tests for ProcessAudioCapture."""
import unittest
import numpy as np


class TestMiscHelpers(unittest.TestCase):

    def test_stereo_to_mono_downmix(self):
        from app.recording.process_audio_capture import stereo_to_mono
        stereo = np.array([[0.8, 0.2], [0.6, 0.4]], dtype=np.float32)
        mono = stereo_to_mono(stereo)
        np.testing.assert_array_almost_equal(mono, [0.5, 0.5])

class TestTrimAndMix(unittest.TestCase):
    def test_trim_to_shortest_and_mean_mix(self):
        from app.recording.process_audio_capture import _trim_and_mix
        chunks = {
            1: np.array([1.0, 1.0, 1.0], dtype=np.float32),
            2: np.array([0.0, 0.0], dtype=np.float32),
        }
        mixed, tails = _trim_and_mix(chunks)
        np.testing.assert_array_almost_equal(mixed, [0.5, 0.5])
        self.assertEqual(len(tails), 2)
        np.testing.assert_array_almost_equal(tails[1], [1.0])
        np.testing.assert_array_almost_equal(tails[2], [])

    def test_all_equal_length_no_tails(self):
        from app.recording.process_audio_capture import _trim_and_mix
        a = np.array([1.0, 1.0], dtype=np.float32)
        b = np.array([0.0, 0.0], dtype=np.float32)
        mixed, tails = _trim_and_mix({1: a, 2: b})
        np.testing.assert_array_almost_equal(mixed, [0.5, 0.5])
        self.assertEqual(tails[1].size, 0)
        self.assertEqual(tails[2].size, 0)

    def test_single_stream(self):
        from app.recording.process_audio_capture import _trim_and_mix
        c = np.array([0.3, -0.3, 0.0], dtype=np.float32)
        mixed, tails = _trim_and_mix({7: c})
        np.testing.assert_array_almost_equal(mixed, c)
        self.assertEqual(tails[7].size, 0)

    def test_empty_input_returns_empty(self):
        from app.recording.process_audio_capture import _trim_and_mix
        mixed, tails = _trim_and_mix({})
        self.assertEqual(mixed.size, 0)
        self.assertEqual(tails, {})


class TestConvertDtype(unittest.TestCase):
    def test_float32_passthrough(self):
        from app.recording.process_audio_capture import _convert_dtype
        raw = np.array([0.5, -0.25, 0.0, 1.0], dtype=np.float32).tobytes()
        arr = _convert_dtype(raw, format_tag="float32", bits_per_sample=32)
        np.testing.assert_array_almost_equal(arr, [0.5, -0.25, 0.0, 1.0])
        self.assertEqual(arr.dtype, np.float32)

    def test_s16_scaled_to_float32(self):
        from app.recording.process_audio_capture import _convert_dtype
        raw = np.array([0, 16384, -32768, 32767], dtype=np.int16).tobytes()
        arr = _convert_dtype(raw, format_tag="s16", bits_per_sample=16)
        # 16384/32768 = 0.5 ; -32768/32768 = -1.0 ; 32767/32768 ≈ 0.99997
        self.assertAlmostEqual(float(arr[0]), 0.0, places=5)
        self.assertAlmostEqual(float(arr[1]), 0.5, places=5)
        self.assertAlmostEqual(float(arr[2]), -1.0, places=5)
        self.assertAlmostEqual(float(arr[3]), 0.99997, places=4)
        self.assertEqual(arr.dtype, np.float32)

    def test_s24_in_32bit_container_shifted_and_scaled(self):
        from app.recording.process_audio_capture import _convert_dtype
        # s24 in 32-bit container: high 24 bits hold the sample.
        # Value 4194304 (0x400000) in the high 24 bits → 0.5 full scale.
        raw = np.array([0, 0x400000 << 8, -0x800000 << 8], dtype=np.int32).tobytes()
        arr = _convert_dtype(raw, format_tag="s24", bits_per_sample=32)
        self.assertAlmostEqual(float(arr[0]), 0.0, places=5)
        self.assertAlmostEqual(float(arr[1]), 0.5, places=5)
        self.assertAlmostEqual(float(arr[2]), -1.0, places=5)
        self.assertEqual(arr.dtype, np.float32)

    def test_unknown_format_raises(self):
        from app.recording.process_audio_capture import _convert_dtype
        with self.assertRaises(ValueError):
            _convert_dtype(b"\x00", format_tag="mu-law", bits_per_sample=8)


class TestResampler(unittest.TestCase):
    def test_48k_to_16k_sine_frequency_preserved(self):
        """The chipmunk-bug guard: 440 Hz in must be 440 Hz out, not 1320."""
        from app.recording.process_audio_capture import _Resampler
        rs = _Resampler(native_rate=48000, target_rate=16000)
        t = np.linspace(0, 1.0, 48000, endpoint=False)
        sine = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        out = rs.push(sine)
        self.assertEqual(len(out), 16000)  # 1 second at 16 kHz
        # FFT peak
        fft = np.abs(np.fft.rfft(out))
        peak_bin = int(np.argmax(fft))
        peak_hz = peak_bin * (16000 / len(out))
        self.assertAlmostEqual(peak_hz, 440, delta=2)

    def test_non_multiple_length_carries_residual(self):
        from app.recording.process_audio_capture import _Resampler
        rs = _Resampler(native_rate=48000, target_rate=16000)
        # 100 samples at 48 kHz is not a multiple of down=3 → residual of 1
        first = rs.push(np.zeros(100, dtype=np.float32))
        # next push of 200 samples: buffer holds 1 + 200 = 201 → 67 output frames, 0 residual
        second = rs.push(np.zeros(200, dtype=np.float32))
        self.assertEqual(len(first), 33)   # 99 / 3
        self.assertEqual(len(second), 67)  # 201 / 3

    def test_passthrough_when_rates_match(self):
        from app.recording.process_audio_capture import _Resampler
        rs = _Resampler(native_rate=16000, target_rate=16000)
        data = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
        out = rs.push(data)
        np.testing.assert_array_almost_equal(out, data)

    def test_empty_push_returns_empty(self):
        from app.recording.process_audio_capture import _Resampler
        rs = _Resampler(native_rate=48000, target_rate=16000)
        out = rs.push(np.array([], dtype=np.float32))
        self.assertEqual(len(out), 0)


import time
import threading


class FakeStream:
    """Test double for ProcessCaptureStream used by the mixer loop tests."""
    def __init__(self, pid, queued_chunks=None, activate_result=True, error=None):
        self.pid = pid
        self.is_active = True
        self.last_error = error
        self._activate_result = activate_result
        self._queue = list(queued_chunks or [])
        self._post_mix_tail = np.array([], dtype=np.float32)
        self.released = False
        self._lock = threading.Lock()

    def activate(self):
        self.is_active = self._activate_result
        if not self._activate_result and self.last_error is None:
            self.last_error = "activation_failed"
        return self._activate_result

    def read_available(self):
        with self._lock:
            chunks = []
            if self._post_mix_tail.size > 0:
                chunks.append(self._post_mix_tail)
                self._post_mix_tail = np.array([], dtype=np.float32)
            if self._queue:
                chunks.append(self._queue.pop(0))
            return chunks

    def put_back_tail(self, tail):
        if tail.size > 0:
            self._post_mix_tail = tail

    def release(self):
        self.released = True
        self.is_active = False

    def die(self, error):
        self.is_active = False
        self.last_error = error


class TestProcessAudioCaptureMixer(unittest.TestCase):
    def _wait_for(self, predicate, timeout=1.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.005)
        return False

    def test_mixer_emits_mixed_chunks_via_level_callback(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        received = []
        a = FakeStream(pid=1, queued_chunks=[np.ones(160, dtype=np.float32)])
        b = FakeStream(pid=2, queued_chunks=[np.zeros(160, dtype=np.float32)])
        cap = ProcessAudioCapture(pids=[1, 2], sample_rate=16000,
                                  level_callback=received.append)
        cap._streams = {1: a, 2: b}
        cap._running = True
        t = threading.Thread(target=cap._mixer_loop, daemon=True)
        t.start()
        self._wait_for(lambda: len(received) > 0)
        cap._running = False
        t.join(timeout=1)
        self.assertGreater(len(received), 0)
        np.testing.assert_array_almost_equal(received[0], np.full(160, 0.5))

    def test_trim_to_shortest_hands_back_tail(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        received = []
        a = FakeStream(pid=1, queued_chunks=[np.ones(200, dtype=np.float32)])
        b = FakeStream(pid=2, queued_chunks=[np.zeros(100, dtype=np.float32)])
        cap = ProcessAudioCapture(pids=[1, 2], sample_rate=16000,
                                  level_callback=received.append)
        cap._streams = {1: a, 2: b}
        cap._running = True
        t = threading.Thread(target=cap._mixer_loop, daemon=True)
        t.start()
        self._wait_for(lambda: len(received) > 0)
        cap._running = False
        t.join(timeout=1)
        # First mix must be length 100 (the shortest).
        self.assertEqual(len(received[0]), 100)
        # a's tail of 100 samples got handed back.
        self.assertEqual(a._post_mix_tail.size, 100)

    def test_paused_drains_but_discards(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        received = []
        a = FakeStream(pid=1, queued_chunks=[np.ones(160, dtype=np.float32)])
        cap = ProcessAudioCapture(pids=[1], sample_rate=16000,
                                  level_callback=received.append)
        cap._streams = {1: a}
        cap._paused = True
        cap._running = True
        t = threading.Thread(target=cap._mixer_loop, daemon=True)
        t.start()
        time.sleep(0.05)   # let the loop tick a few times
        cap._running = False
        t.join(timeout=1)
        # No level callbacks fired while paused, but the queue was drained.
        self.assertEqual(len(received), 0)
        self.assertEqual(len(a._queue), 0)

    def test_crash_in_stream_does_not_kill_loop(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        received = []

        class CrashingStream(FakeStream):
            def read_available(self):
                raise RuntimeError("kaboom")

        bad = CrashingStream(pid=1)
        good = FakeStream(pid=2, queued_chunks=[np.ones(160, dtype=np.float32)])
        cap = ProcessAudioCapture(pids=[1, 2], sample_rate=16000,
                                  level_callback=received.append)
        cap._streams = {1: bad, 2: good}
        cap._running = True
        t = threading.Thread(target=cap._mixer_loop, daemon=True)
        t.start()
        self._wait_for(lambda: len(received) > 0)
        cap._running = False
        t.join(timeout=1)
        # Good stream still produced mixed output, bad one was marked inactive.
        self.assertFalse(bad.is_active)
        self.assertGreater(len(received), 0)

    def test_sink_receives_mixed_chunks(self):
        from app.recording.process_audio_capture import ProcessAudioCapture

        class FakeSink:
            def __init__(self):
                self.chunks = []

            def put(self, chunk):
                self.chunks.append(chunk)

        sink = FakeSink()
        a = FakeStream(pid=1, queued_chunks=[np.ones(160, dtype=np.float32)])
        cap = ProcessAudioCapture(pids=[1], sample_rate=16000, sink=sink)
        cap._streams = {1: a}
        cap._running = True
        t = threading.Thread(target=cap._mixer_loop, daemon=True)
        t.start()
        self._wait_for(lambda: len(sink.chunks) > 0)
        cap._running = False
        t.join(timeout=1)
        self.assertEqual(len(sink.chunks[0]), 160)

    def test_no_sink_still_feeds_level_callback(self):
        # Level-only usage (the old enable_buffer=False) — no accumulation.
        from app.recording.process_audio_capture import ProcessAudioCapture
        received = []
        a = FakeStream(pid=1, queued_chunks=[np.ones(160, dtype=np.float32)])
        cap = ProcessAudioCapture(pids=[1], sample_rate=16000,
                                  level_callback=received.append)
        cap._streams = {1: a}
        cap._running = True
        t = threading.Thread(target=cap._mixer_loop, daemon=True)
        t.start()
        self._wait_for(lambda: len(received) > 0)
        cap._running = False
        t.join(timeout=1)
        self.assertGreater(len(received), 0)
        self.assertFalse(hasattr(cap, "_all_chunks"))


class TestProcessAudioCaptureSignals(unittest.TestCase):
    def _wait_for(self, predicate, timeout=1.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.005)
        return False

    def test_pid_lost_fires_once_per_stream_death(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        lost = []
        a = FakeStream(pid=1, queued_chunks=[np.ones(160, dtype=np.float32)])
        b = FakeStream(pid=2, queued_chunks=[np.ones(160, dtype=np.float32)])
        cap = ProcessAudioCapture(
            pids=[1, 2], sample_rate=16000,
            pid_lost_callback=lambda pid, err: lost.append((pid, err)),
        )
        cap._streams = {1: a, 2: b}
        cap._active_last_tick = {1, 2}
        cap._running = True
        t = threading.Thread(target=cap._mixer_loop, daemon=True)
        t.start()
        # Let one mix tick happen, then kill stream 1.
        self._wait_for(lambda: len(a._queue) == 0)
        a.die("device_invalidated")
        self._wait_for(lambda: len(lost) >= 1)
        cap._running = False
        t.join(timeout=1)
        self.assertEqual(len([e for e in lost if e[0] == 1]), 1)
        self.assertEqual(lost[0][1], "device_invalidated")

    def test_capture_lost_fires_once_when_all_die(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        lost_events = []
        capture_lost_events = []
        a = FakeStream(pid=1, queued_chunks=[])
        b = FakeStream(pid=2, queued_chunks=[])
        cap = ProcessAudioCapture(
            pids=[1, 2], sample_rate=16000,
            pid_lost_callback=lambda pid, err: lost_events.append(pid),
            capture_lost_callback=lambda: capture_lost_events.append(True),
        )
        cap._streams = {1: a, 2: b}
        cap._active_last_tick = {1, 2}
        cap._running = True
        a.die("err_a")
        b.die("err_b")
        t = threading.Thread(target=cap._mixer_loop, daemon=True)
        t.start()
        self._wait_for(lambda: len(capture_lost_events) >= 1, timeout=1.0)
        cap._running = False
        t.join(timeout=1)
        self.assertEqual(len(capture_lost_events), 1)
        self.assertEqual(set(lost_events), {1, 2})


class TestProcessAudioCaptureStart(unittest.TestCase):
    def test_start_returns_status_dict_all_success(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        cap = ProcessAudioCapture(pids=[1, 2], sample_rate=16000)
        # Inject fake streams before start.
        cap._streams = {
            1: FakeStream(pid=1, activate_result=True),
            2: FakeStream(pid=2, activate_result=True),
        }
        status = cap.start(skip_stream_creation=True)
        try:
            self.assertEqual(status["total"], 2)
            self.assertEqual(status["active"], 2)
            self.assertEqual(status["failures"], {})
        finally:
            cap.stop()

    def test_start_tolerates_partial_failures(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        cap = ProcessAudioCapture(pids=[1, 2, 3], sample_rate=16000)
        cap._streams = {
            1: FakeStream(pid=1, activate_result=True),
            2: FakeStream(pid=2, activate_result=False, error="AUDCLNT_E_DEVICE_INVALIDATED"),
            3: FakeStream(pid=3, activate_result=True),
        }
        status = cap.start(skip_stream_creation=True)
        try:
            self.assertEqual(status["total"], 3)
            self.assertEqual(status["active"], 2)
            self.assertEqual(status["failures"], {2: "AUDCLNT_E_DEVICE_INVALIDATED"})
        finally:
            cap.stop()

    def test_start_zero_active_still_returns_status(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        cap = ProcessAudioCapture(pids=[1], sample_rate=16000)
        cap._streams = {
            1: FakeStream(pid=1, activate_result=False, error="E_ACCESSDENIED"),
        }
        status = cap.start(skip_stream_creation=True)
        try:
            self.assertEqual(status["active"], 0)
            self.assertEqual(status["failures"], {1: "E_ACCESSDENIED"})
        finally:
            cap.stop()

    def test_stop_releases_all_streams_and_joins_thread(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        cap = ProcessAudioCapture(pids=[1], sample_rate=16000)
        fs = FakeStream(pid=1, activate_result=True)
        cap._streams = {1: fs}
        cap.start(skip_stream_creation=True)
        result = cap.stop()
        self.assertTrue(fs.released)
        self.assertIn("active_pids", result)
        self.assertFalse(cap._running)


class TestProcessCaptureStreamActivate(unittest.TestCase):
    def test_activate_success_sets_active_and_format(self):
        from app.recording.process_audio_capture import ProcessCaptureStream

        def fake_activate(pid, timeout_ms=5000):
            # Return a sentinel AudioClient + S_OK. Also attach a format.
            client = type("C", (), {})()
            client.native_rate = 48000
            client.native_channels = 2
            client.native_format = "float32"
            return client, 0

        s = ProcessCaptureStream(pid=1234, sample_rate=16000,
                                 activator=fake_activate)
        self.assertTrue(s.activate())
        self.assertTrue(s.is_active)
        self.assertEqual(s.native_rate, 48000)
        self.assertEqual(s.native_channels, 2)
        self.assertEqual(s.native_format, "float32")
        self.assertIsNone(s.last_error)

    def test_activate_failure_returns_false_with_error(self):
        from app.recording.process_audio_capture import ProcessCaptureStream

        def fake_activate(pid, timeout_ms=5000):
            return None, 0x80070005   # E_ACCESSDENIED

        s = ProcessCaptureStream(pid=1234, sample_rate=16000,
                                 activator=fake_activate)
        self.assertFalse(s.activate())
        self.assertFalse(s.is_active)
        self.assertEqual(s.last_error, "E_ACCESSDENIED")

    def test_release_is_idempotent(self):
        from app.recording.process_audio_capture import ProcessCaptureStream
        s = ProcessCaptureStream(pid=1234, sample_rate=16000,
                                 activator=lambda pid, timeout_ms=5000: (None, 0x80004005))
        s.activate()
        s.release()
        s.release()   # no raise


class TestProcessCaptureStreamRead(unittest.TestCase):
    def _make_stream_with_packets(self, packets, format_tag="float32",
                                  bits=32, native_rate=48000, native_channels=2):
        """Build a ProcessCaptureStream with a fake packet source."""
        from app.recording.process_audio_capture import ProcessCaptureStream

        def fake_activate(pid, timeout_ms=5000):
            client = type("C", (), {})()
            client.native_rate = native_rate
            client.native_channels = native_channels
            client.native_format = format_tag
            return client, 0

        s = ProcessCaptureStream(pid=1, sample_rate=16000, activator=fake_activate)
        s.activate()
        # Inject a packet source used by read_available when reading real COM
        # isn't available.
        s._packet_source = iter(packets)
        return s

    def test_read_available_returns_empty_when_no_packets(self):
        s = self._make_stream_with_packets([])
        out = s.read_available()
        self.assertEqual(out, [])

    def test_read_available_converts_and_downmixes_and_resamples(self):
        # Single packet: 480 frames, 2ch, float32 at 48kHz → 160 frames mono 16kHz.
        stereo = np.ones(480 * 2, dtype=np.float32)
        pkt = {"raw": stereo.tobytes(), "frames": 480, "flags": 0}
        s = self._make_stream_with_packets([pkt])
        out = s.read_available()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].dtype, np.float32)
        self.assertEqual(len(out[0]), 160)

    def test_read_available_silent_flag_fast_path(self):
        pkt = {"raw": b"\x00" * 480 * 2 * 4, "frames": 480, "flags": 0x2}
        s = self._make_stream_with_packets([pkt])
        out = s.read_available()
        self.assertEqual(len(out), 1)
        self.assertTrue(np.all(out[0] == 0.0))
        self.assertEqual(len(out[0]), 160)

    def test_read_available_prepends_post_mix_tail(self):
        s = self._make_stream_with_packets([])
        s._post_mix_tail = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        out = s.read_available()
        self.assertEqual(len(out), 1)
        np.testing.assert_array_almost_equal(out[0], [0.1, 0.2, 0.3])
        # Tail must be consumed.
        self.assertEqual(s._post_mix_tail.size, 0)

    def test_read_available_device_invalidated_marks_inactive(self):
        # Sentinel packet with hr=AUDCLNT_E_DEVICE_INVALIDATED.
        pkt = {"raw": None, "frames": 0, "flags": 0, "hr": 0x88890004}
        s = self._make_stream_with_packets([pkt])
        out = s.read_available()
        self.assertFalse(s.is_active)
        self.assertEqual(s.last_error, "AUDCLNT_E_DEVICE_INVALIDATED")


class TestReceivedAudioFlag(unittest.TestCase):
    """ProcessCaptureStream tracks whether any real (non-silent) audio arrived."""

    def _make_stream_with_packets(self, packets):
        from app.recording.process_audio_capture import ProcessCaptureStream

        def fake_activate(pid, timeout_ms=5000):
            client = type("C", (), {})()
            client.native_rate = 48000
            client.native_channels = 2
            client.native_format = "float32"
            return client, 0

        s = ProcessCaptureStream(pid=1, sample_rate=16000, activator=fake_activate)
        s.activate()
        s._packet_source = iter(packets)
        return s

    def test_starts_false(self):
        s = self._make_stream_with_packets([])
        self.assertFalse(s.received_audio)

    def test_silent_flagged_packets_do_not_set_flag(self):
        pkt = {"raw": b"\x00" * 480 * 2 * 4, "frames": 480, "flags": 0x2}
        s = self._make_stream_with_packets([pkt])
        s.read_available()
        self.assertFalse(s.received_audio)

    def test_all_zero_unflagged_packet_does_not_set_flag(self):
        zeros = np.zeros(480 * 2, dtype=np.float32)
        pkt = {"raw": zeros.tobytes(), "frames": 480, "flags": 0}
        s = self._make_stream_with_packets([pkt])
        s.read_available()
        self.assertFalse(s.received_audio)

    def test_real_audio_sets_flag(self):
        audio = np.full(480 * 2, 0.25, dtype=np.float32)
        pkt = {"raw": audio.tobytes(), "frames": 480, "flags": 0}
        s = self._make_stream_with_packets([pkt])
        s.read_available()
        self.assertTrue(s.received_audio)


class TestHasReceivedAudioAggregate(unittest.TestCase):
    def test_false_when_no_stream_received(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        cap = ProcessAudioCapture(pids=[1, 2], sample_rate=16000)
        a, b = FakeStream(pid=1), FakeStream(pid=2)
        a.received_audio = False
        b.received_audio = False
        cap._streams = {1: a, 2: b}
        self.assertFalse(cap.has_received_audio)

    def test_true_when_any_stream_received(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        cap = ProcessAudioCapture(pids=[1, 2], sample_rate=16000)
        a, b = FakeStream(pid=1), FakeStream(pid=2)
        a.received_audio = False
        b.received_audio = True
        cap._streams = {1: a, 2: b}
        self.assertTrue(cap.has_received_audio)

    def test_false_with_no_streams(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        cap = ProcessAudioCapture(pids=[], sample_rate=16000)
        self.assertFalse(cap.has_received_audio)


if __name__ == "__main__":
    unittest.main()
