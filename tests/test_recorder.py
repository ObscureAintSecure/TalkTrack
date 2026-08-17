# tests/test_recorder.py
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestMp3ReplacesWav(unittest.TestCase):
    """With MP3 output selected the WAV originals are removed and the
    audio_files entries point at the MP3s. (issue #60)"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _make_recorder(self):
        from app.recording.recorder import Recorder
        return Recorder(config=MagicMock())

    def _wav(self, name="mic_audio.wav"):
        p = self.root / name
        p.write_bytes(b"RIFF" + b"\0" * 100)
        return str(p)

    def _run(self, files, side_effect=None):
        """Run the conversion with ffmpeg faked out."""
        def fake_run(cmd, **kwargs):
            if side_effect is not None:
                return side_effect(cmd)
            Path(cmd[-1]).write_bytes(b"ID3" + b"\0" * 50)  # plausible MP3
            return MagicMock(returncode=0)

        rec = self._make_recorder()
        with patch("app.recording.recorder.subprocess.run", side_effect=fake_run):
            rec._convert_to_mp3(files)
        return files

    def test_wav_deleted_and_key_repointed(self):
        wav = self._wav()
        files = self._run({"mic": wav})
        self.assertTrue(files["mic"].endswith(".mp3"))
        self.assertTrue(os.path.exists(files["mic"]))
        self.assertFalse(os.path.exists(wav))

    def test_all_tracks_converted(self):
        files = {k: self._wav(f"{k}_audio.wav")
                 for k in ("mic", "system", "combined")}
        wavs = list(files.values())
        files = self._run(files)
        for key in ("mic", "system", "combined"):
            self.assertTrue(files[key].endswith(".mp3"), key)
        self.assertFalse(any(os.path.exists(w) for w in wavs))

    def test_wav_kept_when_ffmpeg_fails(self):
        wav = self._wav()

        def boom(cmd):
            raise subprocess.CalledProcessError(1, cmd)

        files = self._run({"mic": wav}, side_effect=boom)
        self.assertEqual(files["mic"], wav)
        self.assertTrue(os.path.exists(wav))

    def test_wav_kept_when_mp3_never_written(self):
        """ffmpeg exited 0 but produced nothing — never drop the original."""
        wav = self._wav()
        files = self._run({"mic": wav}, side_effect=lambda cmd: MagicMock(returncode=0))
        self.assertEqual(files["mic"], wav)
        self.assertTrue(os.path.exists(wav))

    def test_wav_kept_when_mp3_is_empty(self):
        wav = self._wav()

        def empty(cmd):
            Path(cmd[-1]).write_bytes(b"")
            return MagicMock(returncode=0)

        files = self._run({"mic": wav}, side_effect=empty)
        self.assertEqual(files["mic"], wav)
        self.assertTrue(os.path.exists(wav))

    def test_missing_and_non_wav_entries_ignored(self):
        files = self._run({"mic": None, "note": "notes.txt"})
        self.assertIsNone(files["mic"])
        self.assertEqual(files["note"], "notes.txt")


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
