# tests/test_recordings_salvage.py
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf


class TestSalvageOrphanedRecordings(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _make_dir(self, name, wavs=(), metadata=None, age_seconds=None):
        d = self.root / name
        d.mkdir()
        for wav in wavs:
            data = np.zeros(16000, dtype=np.float32)  # 1s at 16 kHz
            sf.write(str(d / wav), data, 16000)
        if metadata is not None:
            with open(d / "metadata.json", "w", encoding="utf-8") as f:
                json.dump(metadata, f)
        if age_seconds is not None:
            old = time.time() - age_seconds
            os.utime(d, (old, old))
        return d

    def test_orphan_with_audio_gets_metadata(self):
        from app.ui.recordings_list import salvage_orphaned_recordings
        d = self._make_dir("recording_20260101_120000",
                           wavs=["mic_audio.wav", "combined_audio.wav"],
                           age_seconds=3600)
        salvaged = salvage_orphaned_recordings(self.root, min_age_seconds=600)
        self.assertEqual(salvaged, [str(d)])
        meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["directory"], str(d))
        self.assertIn("Recovered", meta["name"])
        self.assertAlmostEqual(meta["duration"], 1.0, places=1)
        self.assertIn("combined", meta["audio_files"])
        self.assertTrue(meta["recovered"])

    def test_dir_with_metadata_untouched(self):
        from app.ui.recordings_list import salvage_orphaned_recordings
        original = {"id": "x", "directory": "y", "name": "Keep me"}
        d = self._make_dir("recording_a", wavs=["mic_audio.wav"],
                           metadata=original, age_seconds=3600)
        salvaged = salvage_orphaned_recordings(self.root, min_age_seconds=600)
        self.assertEqual(salvaged, [])
        meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["name"], "Keep me")

    def test_recent_orphan_skipped(self):
        from app.ui.recordings_list import salvage_orphaned_recordings
        d = self._make_dir("recording_b", wavs=["mic_audio.wav"])  # fresh mtime
        salvaged = salvage_orphaned_recordings(self.root, min_age_seconds=600)
        self.assertEqual(salvaged, [])
        self.assertFalse((d / "metadata.json").exists())

    def test_empty_orphan_left_alone(self):
        from app.ui.recordings_list import salvage_orphaned_recordings
        d = self._make_dir("recording_c", age_seconds=3600)
        salvaged = salvage_orphaned_recordings(self.root, min_age_seconds=600)
        self.assertEqual(salvaged, [])
        self.assertFalse((d / "metadata.json").exists())
        self.assertTrue(d.exists())


if __name__ == "__main__":
    unittest.main()
