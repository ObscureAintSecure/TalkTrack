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


class FakeSink:
    """Records put() chunks — stands in for ChunkWriter in callback tests."""

    def __init__(self):
        self.chunks = []

    def put(self, chunk):
        self.chunks.append(chunk)


class TestAudioStreamMute(unittest.TestCase):
    """AudioStream.set_muted zeros audio chunks but preserves length."""

    def _make_stream(self):
        from app.recording.audio_capture import AudioStream
        stream = AudioStream(device_index=None, sample_rate=16000, channels=1,
                             sink=FakeSink())
        # Simulate active recording without opening a real device
        stream._recording = True
        stream._paused = False
        return stream

    def test_unmuted_writes_original_samples(self):
        stream = self._make_stream()
        chunk = np.ones((256, 1), dtype=np.float32) * 0.5
        stream._audio_callback(chunk, 256, None, None)
        written = stream._sink.chunks[0]
        self.assertEqual(written.shape, (256, 1))
        self.assertAlmostEqual(float(written.max()), 0.5)

    def test_muted_zeros_samples_but_preserves_length(self):
        stream = self._make_stream()
        stream.set_muted(True)
        chunk = np.ones((256, 1), dtype=np.float32) * 0.5
        stream._audio_callback(chunk, 256, None, None)
        written = stream._sink.chunks[0]
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
        self.assertEqual(float(stream._sink.chunks[0].max()), 0.0)
        self.assertAlmostEqual(float(stream._sink.chunks[1].max()), 0.7)

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
        stream = AudioStream(device_index=None, sample_rate=16000, channels=1,
                             sink=FakeSink())
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
        self.assertAlmostEqual(float(stream._sink.chunks[0].max()), 0.3, places=5)

    def test_gain_multiplies_samples(self):
        stream = self._make_stream(gain=2.0)
        chunk = np.ones((64, 1), dtype=np.float32) * 0.3
        stream._audio_callback(chunk, 64, None, None)
        self.assertAlmostEqual(float(stream._sink.chunks[0].max()), 0.6, places=5)

    def test_gain_clips_at_positive_one(self):
        stream = self._make_stream(gain=3.0)
        chunk = np.ones((64, 1), dtype=np.float32) * 0.5
        stream._audio_callback(chunk, 64, None, None)
        self.assertEqual(float(stream._sink.chunks[0].max()), 1.0)

    def test_gain_clips_at_negative_one(self):
        stream = self._make_stream(gain=3.0)
        chunk = np.ones((64, 1), dtype=np.float32) * -0.5
        stream._audio_callback(chunk, 64, None, None)
        self.assertEqual(float(stream._sink.chunks[0].min()), -1.0)

    def test_gain_below_one_attenuates(self):
        stream = self._make_stream(gain=0.5)
        chunk = np.ones((64, 1), dtype=np.float32) * 0.8
        stream._audio_callback(chunk, 64, None, None)
        self.assertAlmostEqual(float(stream._sink.chunks[0].max()), 0.4, places=5)

    def test_mute_beats_gain(self):
        stream = self._make_stream(gain=5.0)
        stream.set_muted(True)
        chunk = np.ones((64, 1), dtype=np.float32) * 0.5
        stream._audio_callback(chunk, 64, None, None)
        self.assertEqual(float(stream._sink.chunks[0].max()), 0.0)

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
            cap.stop()   # release writer file handles for tmpdir cleanup

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
            cap.stop()

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
            # The failed start must not leak an open/empty system track.
            import os
            self.assertEqual(os.listdir(self.output_dir), [])

    def test_per_app_empty_pids_falls_through_to_none(self):
        from app.recording.audio_capture import DualAudioCapture

        cap = DualAudioCapture(
            mic_device=None, loopback_device=None,
            sample_rate=16000, capture_mode="per_app",
            app_pids=[],
        )
        cap.start(output_dir=self.output_dir)
        self.assertIsNone(cap.system_stream)
        cap.stop()


class TestNoDeadBuffer(unittest.TestCase):
    """The unconsumed _buffer queue doubled mic memory — must stay gone."""

    def test_audio_stream_has_no_queue_buffer(self):
        from app.recording.audio_capture import AudioStream
        stream = AudioStream(device_index=None, sample_rate=16000, channels=1)
        self.assertFalse(hasattr(stream, "_buffer"))

    def test_callback_puts_single_detached_copy(self):
        from app.recording.audio_capture import AudioStream
        sink = FakeSink()
        stream = AudioStream(device_index=None, sample_rate=16000, channels=1,
                             sink=sink)
        stream._recording = True
        stream._paused = False
        indata = np.ones((64, 1), dtype=np.float32)
        stream._audio_callback(indata, 64, None, None)
        self.assertEqual(len(sink.chunks), 1)
        self.assertIsNot(sink.chunks[0], indata)   # detached from device buffer

    def test_stream_holds_no_chunk_accumulator(self):
        # The RAM-until-stop design is gone (#32) — streams must not
        # accumulate audio in memory.
        from app.recording.audio_capture import AudioStream
        stream = AudioStream(device_index=None, sample_rate=16000, channels=1)
        self.assertFalse(hasattr(stream, "_all_chunks"))


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
            # Writers discarded — no stray track files left behind.
            import os
            self.assertEqual(os.listdir(self.output_dir), [])

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
    """One failing stream or writer must not abort the rest of stop()."""

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

    def _live_writer(self, filename, data=None):
        from pathlib import Path
        from app.recording.chunk_writer import ChunkWriter
        w = ChunkWriter(Path(self.output_dir) / filename, sample_rate=16000)
        w.release(prepad_frames=0)
        if data is not None:
            w.put(data)
        return w

    def test_mic_stop_failure_still_stops_and_saves_system(self):
        import os
        cap = self._make_capture()
        mic = MagicMock()
        mic.stop.side_effect = RuntimeError("device unplugged")
        system = MagicMock()
        cap.mic_stream = mic
        cap.system_stream = system
        cap._writers = {
            "mic": self._live_writer("mic_audio.wav"),   # no data arrived
            "system": self._live_writer(
                "system_audio.wav", np.full(16, 0.1, dtype=np.float32)),
        }

        results = cap.stop()

        system.stop.assert_called_once()
        self.assertEqual(
            results["system"],
            str(os.path.join(self.output_dir, "system_audio.wav")),
        )
        self.assertTrue(os.path.exists(results["system"]))
        self.assertIsNone(results["mic"])

    def test_mic_writer_error_still_saves_system_and_combined(self):
        cap = self._make_capture()
        cap.mic_stream = MagicMock()
        cap.system_stream = MagicMock()
        mic_writer = self._live_writer("mic_audio.wav")
        mic_writer.error = "disk full"   # writer died mid-recording
        cap._writers = {
            "mic": mic_writer,
            "system": self._live_writer(
                "system_audio.wav", np.full(16, 0.1, dtype=np.float32)),
        }

        results = cap.stop()

        self.assertIsNotNone(results["system"])
        self.assertIsNone(results["mic"])
        self.assertIsNotNone(results["combined"])


class TestAlignmentPrepad(unittest.TestCase):
    """The later-starting mic gets a leading-silence prepad at release time."""

    def _make_capture(self):
        from app.recording.audio_capture import DualAudioCapture
        return DualAudioCapture(mic_device=None, loopback_device=None,
                                sample_rate=16000)

    def test_mic_started_later_gets_prepad(self):
        cap = self._make_capture()
        cap._system_start_ts = 100.0
        pad = cap._alignment_prepad_frames(101.0)   # mic started 1s later
        self.assertEqual(pad, 16000)

    def test_no_system_stream_means_no_prepad(self):
        cap = self._make_capture()
        cap._system_start_ts = None
        self.assertEqual(cap._alignment_prepad_frames(101.0), 0)

    def test_mic_started_first_means_no_prepad(self):
        cap = self._make_capture()
        cap._system_start_ts = 100.5
        self.assertEqual(cap._alignment_prepad_frames(100.0), 0)

    def test_implausible_offset_skipped(self):
        cap = self._make_capture()
        cap._system_start_ts = 100.0
        self.assertEqual(cap._alignment_prepad_frames(200.0), 0)


class TestMixWavFiles(unittest.TestCase):
    """Block-wise WAV mixing must match the old in-RAM array math."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        from pathlib import Path
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, data):
        import soundfile as sf
        path = self.dir / name
        sf.write(str(path), data, 16000)
        return path

    def _read(self, path):
        import soundfile as sf
        data, sr = sf.read(str(path), dtype="float32")
        return data

    def test_combined_mixes_half_half_and_normalizes(self):
        from app.recording.audio_capture import mix_wav_files
        mic = np.full(16000, 0.8, dtype=np.float32)
        system = np.full(16000, 0.4, dtype=np.float32)
        a = self._write("a.wav", mic)
        b = self._write("b.wav", system)
        out = self.dir / "combined.wav"
        mix_wav_files([a, b], out, weights=[0.5, 0.5], sample_rate=16000,
                      normalize="always", block_frames=1000)
        data = self._read(out)
        self.assertEqual(len(data), 16000)
        # Old math: 0.5*0.8 + 0.5*0.4 = 0.6 peak -> scaled to 0.95
        self.assertAlmostEqual(float(data.max()), 0.95, places=3)

    def test_unequal_lengths_pad_shorter_with_silence(self):
        from app.recording.audio_capture import mix_wav_files
        a = self._write("a.wav", np.full(8000, 0.5, dtype=np.float32))
        b = self._write("b.wav", np.full(16000, 0.5, dtype=np.float32))
        out = self.dir / "combined.wav"
        mix_wav_files([a, b], out, weights=[0.5, 0.5], sample_rate=16000,
                      normalize="always", block_frames=3000)
        data = self._read(out)
        self.assertEqual(len(data), 16000)
        # Second half is 0.5*0 + 0.5*0.5 = half the first half's level.
        self.assertAlmostEqual(float(data[:8000].max()),
                               2 * float(data[12000]), places=2)

    def test_dual_mic_sum_without_clipping_stays_unscaled(self):
        from app.recording.audio_capture import mix_wav_files
        a = self._write("m1.wav", np.full(4000, 0.3, dtype=np.float32))
        b = self._write("m2.wav", np.full(4000, 0.4, dtype=np.float32))
        out = self.dir / "mixed.wav"
        mix_wav_files([a, b], out, weights=[1.0, 1.0], sample_rate=16000,
                      normalize="if_clipping", block_frames=1024)
        data = self._read(out)
        # Old math: sum 0.7, peak <= 1.0 -> untouched.
        self.assertAlmostEqual(float(data.max()), 0.7, places=3)

    def test_dual_mic_sum_clipping_normalized_to_095(self):
        from app.recording.audio_capture import mix_wav_files
        a = self._write("m1.wav", np.full(4000, 0.8, dtype=np.float32))
        b = self._write("m2.wav", np.full(4000, 0.6, dtype=np.float32))
        out = self.dir / "mixed.wav"
        mix_wav_files([a, b], out, weights=[1.0, 1.0], sample_rate=16000,
                      normalize="if_clipping", block_frames=1024)
        data = self._read(out)
        # Old math: sum 1.4 > 1.0 -> scaled to 0.95 peak.
        self.assertAlmostEqual(float(data.max()), 0.95, places=3)

    def test_single_source_copied_verbatim(self):
        from app.recording.audio_capture import mix_wav_files
        a = self._write("only.wav", np.full(4000, 0.5, dtype=np.float32))
        out = self.dir / "combined.wav"
        mix_wav_files([a], out, weights=[1.0], sample_rate=16000,
                      normalize="never", block_frames=1024)
        data = self._read(out)
        self.assertEqual(len(data), 4000)
        self.assertAlmostEqual(float(data.max()), 0.5, places=3)


class TestStreamingStop(unittest.TestCase):
    """stop() closes writers and assembles mic/system/combined from disk."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        from pathlib import Path
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _capture_with_writers(self, mic_data=None, sys_data=None):
        from app.recording.audio_capture import DualAudioCapture
        from app.recording.chunk_writer import ChunkWriter
        cap = DualAudioCapture(mic_device=None, loopback_device=None,
                               sample_rate=16000)
        cap.output_dir = self.dir
        cap.mic_stream = MagicMock()
        cap.system_stream = MagicMock()
        cap._writers = {}
        if mic_data is not None:
            w = ChunkWriter(self.dir / "mic_audio.wav", sample_rate=16000)
            w.release(prepad_frames=0)
            w.put(mic_data)
            cap._writers["mic"] = w
        if sys_data is not None:
            w = ChunkWriter(self.dir / "system_audio.wav", sample_rate=16000)
            w.release(prepad_frames=0)
            w.put(sys_data)
            cap._writers["system"] = w
        return cap

    def test_both_tracks_produce_three_files(self):
        import soundfile as sf
        cap = self._capture_with_writers(
            mic_data=np.full(16000, 0.5, dtype=np.float32),
            sys_data=np.full(16000, 0.25, dtype=np.float32),
        )
        results = cap.stop()
        self.assertIsNotNone(results["mic"])
        self.assertIsNotNone(results["system"])
        self.assertIsNotNone(results["combined"])
        combined, _ = sf.read(results["combined"], dtype="float32")
        # 0.5*0.5 + 0.5*0.25 = 0.375 peak -> normalized to 0.95
        self.assertAlmostEqual(float(combined.max()), 0.95, places=3)

    def test_mic_only_combined_is_copy_of_mic(self):
        import soundfile as sf
        cap = self._capture_with_writers(
            mic_data=np.full(8000, 0.5, dtype=np.float32))
        results = cap.stop()
        self.assertIsNone(results["system"])
        self.assertIsNotNone(results["combined"])
        combined, _ = sf.read(results["combined"], dtype="float32")
        self.assertEqual(len(combined), 8000)
        self.assertAlmostEqual(float(combined.max()), 0.5, places=3)

    def test_no_audio_returns_all_none(self):
        cap = self._capture_with_writers()
        results = cap.stop()
        self.assertIsNone(results["mic"])
        self.assertIsNone(results["system"])
        self.assertIsNone(results["combined"])

    def test_dual_mic_temps_mixed_and_removed(self):
        import soundfile as sf
        from app.recording.chunk_writer import ChunkWriter
        cap = self._capture_with_writers()
        w1 = ChunkWriter(self.dir / "mic1_raw.wav", sample_rate=16000)
        w1.release(prepad_frames=0)
        w1.put(np.full(4000, 0.3, dtype=np.float32))
        w2 = ChunkWriter(self.dir / "mic2_raw.wav", sample_rate=16000)
        w2.release(prepad_frames=0)
        w2.put(np.full(4000, 0.4, dtype=np.float32))
        cap._writers = {"mic": w1, "mic2": w2}
        results = cap.stop()
        self.assertIsNotNone(results["mic"])
        mixed, _ = sf.read(results["mic"], dtype="float32")
        self.assertAlmostEqual(float(mixed.max()), 0.7, places=3)   # no clip -> unscaled
        self.assertFalse((self.dir / "mic1_raw.wav").exists())
        self.assertFalse((self.dir / "mic2_raw.wav").exists())


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
