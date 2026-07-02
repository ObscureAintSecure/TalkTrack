"""Tests for DualAudioCapture per-app mode integration."""
import unittest


class TestDualAudioCaptureMode(unittest.TestCase):

    def test_accepts_capture_mode_parameter(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(
            mic_device=None, loopback_device=None,
            sample_rate=16000, capture_mode="legacy"
        )
        self.assertEqual(cap.capture_mode, "legacy")

    def test_defaults_to_legacy_mode(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        self.assertEqual(cap.capture_mode, "legacy")

    def test_accepts_per_app_mode_with_pids(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(
            mic_device=None, loopback_device=None,
            sample_rate=16000, capture_mode="per_app",
            app_pids=[123, 456]
        )
        self.assertEqual(cap.capture_mode, "per_app")
        self.assertEqual(cap.app_pids, [123, 456])


import numpy as np


class TestAudioStreamMute(unittest.TestCase):
    """AudioStream.set_muted zeros audio chunks but preserves length."""

    def _make_stream(self):
        from app.recording.audio_capture import AudioStream
        stream = AudioStream(device_index=None, sample_rate=16000, channels=1)
        # Simulate active recording without opening a real device
        stream._recording = True
        stream._paused = False
        return stream

    def test_unmuted_writes_original_samples(self):
        stream = self._make_stream()
        chunk = np.ones((256, 1), dtype=np.float32) * 0.5
        stream._audio_callback(chunk, 256, None, None)
        written = stream._all_chunks[0]
        self.assertEqual(written.shape, (256, 1))
        self.assertAlmostEqual(float(written.max()), 0.5)

    def test_muted_zeros_samples_but_preserves_length(self):
        stream = self._make_stream()
        stream.set_muted(True)
        chunk = np.ones((256, 1), dtype=np.float32) * 0.5
        stream._audio_callback(chunk, 256, None, None)
        written = stream._all_chunks[0]
        self.assertEqual(written.shape, (256, 1))
        self.assertEqual(float(written.max()), 0.0)
        self.assertEqual(float(written.min()), 0.0)

    def test_unmute_restores_capture(self):
        stream = self._make_stream()
        stream.set_muted(True)
        stream._audio_callback(
            np.ones((128, 1), dtype=np.float32), 128, None, None
        )
        stream.set_muted(False)
        stream._audio_callback(
            np.ones((128, 1), dtype=np.float32) * 0.7, 128, None, None
        )
        self.assertEqual(float(stream._all_chunks[0].max()), 0.0)
        self.assertAlmostEqual(float(stream._all_chunks[1].max()), 0.7)

    def test_level_callback_receives_zeroed_chunk_when_muted(self):
        received = []
        from app.recording.audio_capture import AudioStream
        stream = AudioStream(
            device_index=None, sample_rate=16000, channels=1,
            level_callback=lambda c: received.append(c),
        )
        stream._recording = True
        stream._paused = False
        stream.set_muted(True)
        stream._audio_callback(
            np.ones((64, 1), dtype=np.float32), 64, None, None
        )
        self.assertEqual(len(received), 1)
        self.assertEqual(float(received[0].max()), 0.0)


class TestDualAudioCaptureMute(unittest.TestCase):
    """DualAudioCapture.set_muted propagates to both mic streams."""

    def _fake_stream(self):
        """Return an AudioStream instance that is not backed by a real device."""
        from app.recording.audio_capture import AudioStream
        s = AudioStream(device_index=None, sample_rate=16000, channels=1)
        return s

    def test_set_muted_single_mic(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        cap.mic_stream = self._fake_stream()
        cap.set_muted(True)
        self.assertTrue(cap.mic_stream._muted)
        self.assertTrue(cap.is_muted)

    def test_set_muted_propagates_to_second_mic(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        cap.mic_stream = self._fake_stream()
        cap.mic_stream_2 = self._fake_stream()
        cap.set_muted(True)
        self.assertTrue(cap.mic_stream._muted)
        self.assertTrue(cap.mic_stream_2._muted)

    def test_unmute_propagates(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        cap.mic_stream = self._fake_stream()
        cap.mic_stream_2 = self._fake_stream()
        cap.set_muted(True)
        cap.set_muted(False)
        self.assertFalse(cap.mic_stream._muted)
        self.assertFalse(cap.mic_stream_2._muted)
        self.assertFalse(cap.is_muted)

    def test_set_muted_with_no_streams_does_not_raise(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        # mic_stream and mic_stream_2 are both None
        cap.set_muted(True)
        self.assertTrue(cap.is_muted)

    def test_default_is_not_muted(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        self.assertFalse(cap.is_muted)


class TestAudioStreamGain(unittest.TestCase):
    """AudioStream.set_gain multiplies samples and clips to [-1, 1]."""

    def _make_stream(self, gain=None):
        from app.recording.audio_capture import AudioStream
        stream = AudioStream(device_index=None, sample_rate=16000, channels=1)
        stream._recording = True
        stream._paused = False
        if gain is not None:
            stream.set_gain(gain)
        return stream

    def test_default_gain_is_1(self):
        from app.recording.audio_capture import AudioStream
        stream = AudioStream(device_index=None, sample_rate=16000, channels=1)
        self.assertEqual(stream._gain, 1.0)

    def test_gain_1_does_not_change_samples(self):
        stream = self._make_stream(gain=1.0)
        chunk = np.ones((64, 1), dtype=np.float32) * 0.3
        stream._audio_callback(chunk, 64, None, None)
        self.assertAlmostEqual(float(stream._all_chunks[0].max()), 0.3, places=5)

    def test_gain_multiplies_samples(self):
        stream = self._make_stream(gain=2.0)
        chunk = np.ones((64, 1), dtype=np.float32) * 0.3
        stream._audio_callback(chunk, 64, None, None)
        self.assertAlmostEqual(float(stream._all_chunks[0].max()), 0.6, places=5)

    def test_gain_clips_at_positive_one(self):
        stream = self._make_stream(gain=3.0)
        chunk = np.ones((64, 1), dtype=np.float32) * 0.5
        stream._audio_callback(chunk, 64, None, None)
        self.assertEqual(float(stream._all_chunks[0].max()), 1.0)

    def test_gain_clips_at_negative_one(self):
        stream = self._make_stream(gain=3.0)
        chunk = np.ones((64, 1), dtype=np.float32) * -0.5
        stream._audio_callback(chunk, 64, None, None)
        self.assertEqual(float(stream._all_chunks[0].min()), -1.0)

    def test_gain_below_one_attenuates(self):
        stream = self._make_stream(gain=0.5)
        chunk = np.ones((64, 1), dtype=np.float32) * 0.8
        stream._audio_callback(chunk, 64, None, None)
        self.assertAlmostEqual(float(stream._all_chunks[0].max()), 0.4, places=5)

    def test_mute_beats_gain(self):
        stream = self._make_stream(gain=5.0)
        stream.set_muted(True)
        chunk = np.ones((64, 1), dtype=np.float32) * 0.5
        stream._audio_callback(chunk, 64, None, None)
        self.assertEqual(float(stream._all_chunks[0].max()), 0.0)

    def test_set_gain_coerces_to_float(self):
        stream = self._make_stream()
        stream.set_gain(2)
        self.assertEqual(stream._gain, 2.0)
        self.assertIsInstance(stream._gain, float)

    def test_level_callback_receives_gained_chunk(self):
        received = []
        from app.recording.audio_capture import AudioStream
        stream = AudioStream(
            device_index=None, sample_rate=16000, channels=1,
            level_callback=lambda c: received.append(c),
        )
        stream._recording = True
        stream._paused = False
        stream.set_gain(2.0)
        stream._audio_callback(
            np.ones((32, 1), dtype=np.float32) * 0.3, 32, None, None
        )
        self.assertEqual(len(received), 1)
        self.assertAlmostEqual(float(received[0].max()), 0.6, places=5)


class TestDualAudioCaptureGain(unittest.TestCase):
    """DualAudioCapture.set_gain propagates to both mic streams."""

    def _fake_stream(self):
        from app.recording.audio_capture import AudioStream
        return AudioStream(device_index=None, sample_rate=16000, channels=1)

    def test_default_gain_is_1(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        self.assertEqual(cap.mic_gain, 1.0)

    def test_set_gain_single_mic(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        cap.mic_stream = self._fake_stream()
        cap.set_gain(2.5)
        self.assertEqual(cap.mic_gain, 2.5)
        self.assertEqual(cap.mic_stream._gain, 2.5)

    def test_set_gain_propagates_to_second_mic(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        cap.mic_stream = self._fake_stream()
        cap.mic_stream_2 = self._fake_stream()
        cap.set_gain(3.0)
        self.assertEqual(cap.mic_stream._gain, 3.0)
        self.assertEqual(cap.mic_stream_2._gain, 3.0)

    def test_set_gain_with_no_streams_does_not_raise(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        cap.set_gain(2.0)
        self.assertEqual(cap.mic_gain, 2.0)

    def test_set_gain_coerces_to_float(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        cap.set_gain(2)
        self.assertEqual(cap.mic_gain, 2.0)
        self.assertIsInstance(cap.mic_gain, float)


import tempfile
from unittest.mock import MagicMock, patch


class TestDualAudioCaptureDispatch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.output_dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_per_app_mode_uses_process_audio_capture(self):
        from app.recording.audio_capture import DualAudioCapture

        with patch("app.recording.audio_capture.ProcessAudioCapture") as MockPAC:
            mock_instance = MagicMock()
            mock_instance.start.return_value = {
                "total": 2, "active": 2, "failures": {}
            }
            MockPAC.return_value = mock_instance

            cap = DualAudioCapture(
                mic_device=None, loopback_device=None,
                sample_rate=16000, capture_mode="per_app",
                app_pids=[123, 456],
            )
            cap.start(output_dir=self.output_dir)
            MockPAC.assert_called_once()
            mock_instance.start.assert_called_once()
            self.assertEqual(cap._capture_status["active"], 2)

    def test_legacy_mode_uses_loopback_stream(self):
        from app.recording.audio_capture import DualAudioCapture

        with patch("app.recording.audio_capture.LoopbackStream") as MockLS, \
             patch("app.recording.audio_capture.sd.query_devices",
                   return_value={"name": "Speakers"}):
            mock_instance = MagicMock()
            MockLS.return_value = mock_instance

            cap = DualAudioCapture(
                mic_device=None, loopback_device=0,
                sample_rate=16000, capture_mode="legacy",
            )
            cap.start(output_dir=self.output_dir)
            MockLS.assert_called_once()

    def test_per_app_zero_active_raises(self):
        from app.recording.audio_capture import DualAudioCapture

        with patch("app.recording.audio_capture.ProcessAudioCapture") as MockPAC:
            mock_instance = MagicMock()
            mock_instance.start.return_value = {
                "total": 1, "active": 0, "failures": {123: "E_ACCESSDENIED"}
            }
            MockPAC.return_value = mock_instance

            cap = DualAudioCapture(
                mic_device=None, loopback_device=None,
                sample_rate=16000, capture_mode="per_app",
                app_pids=[123],
            )
            with self.assertRaises(RuntimeError) as ctx:
                cap.start(output_dir=self.output_dir)
            self.assertIn("E_ACCESSDENIED", str(ctx.exception))

    def test_per_app_empty_pids_falls_through_to_none(self):
        from app.recording.audio_capture import DualAudioCapture

        cap = DualAudioCapture(
            mic_device=None, loopback_device=None,
            sample_rate=16000, capture_mode="per_app",
            app_pids=[],
        )
        cap.start(output_dir=self.output_dir)
        self.assertIsNone(cap.system_stream)


class TestStartFailureCleanup(unittest.TestCase):
    """A mic-start failure must stop the already-started system stream."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.output_dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_mic_failure_stops_per_app_system_stream(self):
        from app.recording.audio_capture import DualAudioCapture

        with patch("app.recording.audio_capture.ProcessAudioCapture") as MockPAC, \
             patch("app.recording.audio_capture.AudioStream") as MockMic:
            system = MagicMock()
            system.start.return_value = {"total": 1, "active": 1, "failures": {}}
            MockPAC.return_value = system
            mic = MagicMock()
            mic.start.side_effect = RuntimeError("mic busy")
            MockMic.return_value = mic

            cap = DualAudioCapture(
                mic_device=1, loopback_device=None,
                sample_rate=16000, capture_mode="per_app", app_pids=[123],
            )
            with self.assertRaises(RuntimeError):
                cap.start(output_dir=self.output_dir)
            system.stop.assert_called_once()

    def test_second_mic_failure_stops_first_mic(self):
        from app.recording.audio_capture import DualAudioCapture

        mic1 = MagicMock()
        mic2 = MagicMock()
        mic2.start.side_effect = RuntimeError("mic 2 busy")
        with patch("app.recording.audio_capture.AudioStream",
                   side_effect=[mic1, mic2]):
            cap = DualAudioCapture(
                mic_device=1, mic_device_2=2, loopback_device=None,
                sample_rate=16000, capture_mode="legacy",
            )
            with self.assertRaises(RuntimeError):
                cap.start(output_dir=self.output_dir)
            mic1.stop.assert_called_once()


class TestStopResilience(unittest.TestCase):
    """One failing stream or file write must not abort the rest of stop()."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.output_dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _make_capture(self):
        from pathlib import Path
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        cap.output_dir = Path(self.output_dir)
        return cap

    def test_mic_stop_failure_still_stops_and_saves_system(self):
        import os
        cap = self._make_capture()
        mic = MagicMock()
        mic.stop.side_effect = RuntimeError("device unplugged")
        mic.get_audio_data.return_value = np.array([], dtype=np.float32)
        system = MagicMock()
        sys_path = os.path.join(self.output_dir, "system_audio.wav")
        system.save_to_file.return_value = sys_path
        system.get_audio_data.return_value = np.zeros(16, dtype=np.float32)
        cap.mic_stream = mic
        cap.system_stream = system

        results = cap.stop()

        system.stop.assert_called_once()
        self.assertEqual(results["system"], sys_path)
        self.assertIsNone(results["mic"])

    def test_mic_write_failure_still_saves_system(self):
        import os
        cap = self._make_capture()
        mic = MagicMock()
        mic.get_audio_data.return_value = np.full(16, 0.5, dtype=np.float32)
        system = MagicMock()
        sys_path = os.path.join(self.output_dir, "system_audio.wav")
        system.save_to_file.return_value = sys_path
        system.get_audio_data.return_value = np.zeros(16, dtype=np.float32)
        cap.mic_stream = mic
        cap.system_stream = system

        with patch("app.recording.audio_capture.sf.write",
                   side_effect=OSError("disk full")):
            results = cap.stop()

        system.stop.assert_called_once()
        self.assertEqual(results["system"], sys_path)
        self.assertIsNone(results["mic"])
        self.assertIsNone(results["combined"])


class TestSystemAudioReceived(unittest.TestCase):
    """system_audio_received() flags per-app captures that never got audio."""

    def _make_capture(self):
        from app.recording.audio_capture import DualAudioCapture
        return DualAudioCapture(mic_device=None, loopback_device=None)

    def test_no_system_stream_reports_received(self):
        cap = self._make_capture()
        cap.system_stream = None
        self.assertTrue(cap.system_audio_received())

    def test_legacy_stream_without_flag_reports_received(self):
        cap = self._make_capture()
        cap.system_stream = object()   # LoopbackStream has no flag
        self.assertTrue(cap.system_audio_received())

    def test_per_app_stream_silent_reports_false(self):
        import types
        cap = self._make_capture()
        cap.system_stream = types.SimpleNamespace(has_received_audio=False)
        self.assertFalse(cap.system_audio_received())

    def test_per_app_stream_with_audio_reports_true(self):
        import types
        cap = self._make_capture()
        cap.system_stream = types.SimpleNamespace(has_received_audio=True)
        self.assertTrue(cap.system_audio_received())


class TestSilenceDetectionMicGuard(unittest.TestCase):
    """Silence auto-stop must not fire while the mic is active.

    Scenario: remote is muted / dead air but the user is monologuing.
    The old behavior fired silence-stop after silence_duration of quiet
    system audio regardless of mic. Now mic activity inside the window
    resets the silence timer so the recording keeps going.
    """

    def _make_capture(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(
            mic_device=None, loopback_device=None,
            sample_rate=16000, capture_mode="legacy",
        )
        self.fired = []
        cap.set_silence_detection(
            threshold=0.005,
            duration=1.0,
            callback=lambda secs: self.fired.append(secs),
        )
        return cap

    def test_silence_fires_without_mic_activity(self):
        cap = self._make_capture()
        silent = np.zeros(1600, dtype=np.float32)  # 0.1s
        # Simulate 1.5s of silent system chunks, well past the 1.0s threshold.
        import time
        for _ in range(5):
            cap._check_silence(silent)
            time.sleep(0.25)
        cap._check_silence(silent)
        self.assertEqual(len(self.fired), 1)

    def test_mic_activity_resets_silence_timer(self):
        cap = self._make_capture()
        silent = np.zeros(1600, dtype=np.float32)
        loud_mic = np.full(1600, 0.3, dtype=np.float32)
        import time
        # 0.5s of system silence
        cap._check_silence(silent)
        time.sleep(0.5)
        cap._check_silence(silent)
        # Mic spikes — should reset the silence anchor.
        cap._note_mic_activity(loud_mic)
        # Another 0.8s of system silence. Under 1.0s from the mic spike,
        # so silence must NOT fire yet even though total elapsed > duration.
        time.sleep(0.8)
        cap._check_silence(silent)
        self.assertEqual(self.fired, [])

    def test_quiet_mic_does_not_reset(self):
        cap = self._make_capture()
        silent_sys = np.zeros(1600, dtype=np.float32)
        quiet_mic = np.full(1600, 0.001, dtype=np.float32)  # below threshold
        import time
        cap._check_silence(silent_sys)
        time.sleep(0.3)
        cap._note_mic_activity(quiet_mic)
        time.sleep(0.8)
        cap._check_silence(silent_sys)
        self.assertEqual(len(self.fired), 1)


if __name__ == "__main__":
    unittest.main()
