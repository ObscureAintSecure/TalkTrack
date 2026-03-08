"""Tests for ProcessAudioCapture."""
import unittest
import numpy as np


class TestProcessAudioMixer(unittest.TestCase):

    def test_mix_single_stream(self):
        from app.recording.process_audio_capture import mix_audio_chunks
        chunk = np.array([0.5, -0.5, 0.3], dtype=np.float32)
        result = mix_audio_chunks([chunk])
        np.testing.assert_array_almost_equal(result, chunk)

    def test_mix_two_streams_averages(self):
        from app.recording.process_audio_capture import mix_audio_chunks
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0], dtype=np.float32)
        result = mix_audio_chunks([a, b])
        np.testing.assert_array_almost_equal(result, [0.5, 0.5])

    def test_mix_empty_returns_empty(self):
        from app.recording.process_audio_capture import mix_audio_chunks
        result = mix_audio_chunks([])
        self.assertEqual(len(result), 0)

    def test_mix_different_lengths_pads_shorter(self):
        from app.recording.process_audio_capture import mix_audio_chunks
        a = np.array([1.0, 1.0, 1.0], dtype=np.float32)
        b = np.array([1.0], dtype=np.float32)
        result = mix_audio_chunks([a, b])
        self.assertEqual(len(result), 3)

    def test_stereo_to_mono_downmix(self):
        from app.recording.process_audio_capture import stereo_to_mono
        stereo = np.array([[0.8, 0.2], [0.6, 0.4]], dtype=np.float32)
        mono = stereo_to_mono(stereo)
        np.testing.assert_array_almost_equal(mono, [0.5, 0.5])

    def test_process_capture_stream_init(self):
        from app.recording.process_audio_capture import ProcessCaptureStream
        stream = ProcessCaptureStream(pid=12345, sample_rate=16000)
        self.assertEqual(stream.pid, 12345)
        self.assertEqual(stream.sample_rate, 16000)
        self.assertFalse(stream.is_active)


if __name__ == "__main__":
    unittest.main()
