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


if __name__ == "__main__":
    unittest.main()
