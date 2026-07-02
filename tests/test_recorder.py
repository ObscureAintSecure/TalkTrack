# tests/test_recorder.py
import subprocess
import unittest
from unittest.mock import MagicMock, patch


class TestConvertToMp3(unittest.TestCase):
    def _make_recorder(self):
        from app.recording.recorder import Recorder
        return Recorder(config=MagicMock())

    def test_ffmpeg_called_with_timeout(self):
        rec = self._make_recorder()
        files = {"mic": "a.wav"}
        with patch("app.recording.recorder.subprocess.run") as run:
            rec._convert_to_mp3(files)
        self.assertGreater(run.call_args.kwargs.get("timeout", 0), 0)

    def test_timeout_expired_keeps_wav_and_does_not_raise(self):
        rec = self._make_recorder()
        files = {"mic": "a.wav"}
        with patch(
            "app.recording.recorder.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=300),
        ):
            rec._convert_to_mp3(files)
        self.assertNotIn("mic_mp3", files)
        self.assertEqual(files["mic"], "a.wav")


if __name__ == "__main__":
    unittest.main()
