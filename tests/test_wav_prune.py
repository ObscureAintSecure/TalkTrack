# tests/test_wav_prune.py
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf


def _tone(seconds=2.0, sr=16000):
    t = np.arange(int(sr * seconds)) / sr
    return (0.3 * np.sin(2 * np.pi * 440 * t)).astype("float32")


class _RecordingDir:
    """Builds a recording directory with whatever tracks a test needs."""

    def __init__(self, root, name="recording_20260101_120000"):
        self.path = Path(root) / name
        self.path.mkdir()

    def wav(self, stem, seconds=2.0):
        p = self.path / f"{stem}.wav"
        sf.write(str(p), _tone(seconds), 16000, subtype="PCM_16")
        return p

    def mp3(self, stem, seconds=2.0):
        p = self.path / f"{stem}.mp3"
        sf.write(str(p), _tone(seconds), 16000, format="MP3")
        return p

    def raw_mp3(self, stem, data=b"ID3"):
        p = self.path / f"{stem}.mp3"
        p.write_bytes(data)
        return p

    def metadata(self, audio_files, **extra):
        meta = {"id": "x", "directory": str(self.path), "audio_files": audio_files}
        meta.update(extra)
        (self.path / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        return meta

    def read_metadata(self):
        return json.loads((self.path / "metadata.json").read_text(encoding="utf-8"))


class PruneTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _rec(self, name="recording_20260101_120000"):
        return _RecordingDir(self.root, name)


class TestPlanRecording(PruneTestCase):
    """plan_recording decides what is safe to delete. It never touches disk."""

    def test_matching_mp3_is_prunable(self):
        from app.utils.wav_prune import plan_recording
        rec = self._rec()
        wav = rec.wav("combined_audio")
        rec.mp3("combined_audio")
        rec.metadata({"combined": str(wav)})

        plan = plan_recording(rec.path)
        self.assertEqual([p["key"] for p in plan.prunable], ["combined"])
        self.assertTrue(wav.exists())  # planning must not delete

    def test_wav_without_mp3_is_kept(self):
        from app.utils.wav_prune import plan_recording
        rec = self._rec()
        wav = rec.wav("combined_audio")
        rec.metadata({"combined": str(wav)})

        plan = plan_recording(rec.path)
        self.assertEqual(plan.prunable, [])

    def test_unreadable_mp3_is_kept(self):
        from app.utils.wav_prune import plan_recording
        rec = self._rec()
        wav = rec.wav("combined_audio")
        rec.raw_mp3("combined_audio", b"not really an mp3")
        rec.metadata({"combined": str(wav)})

        plan = plan_recording(rec.path)
        self.assertEqual(plan.prunable, [])
        self.assertTrue(any("unreadable" in s["reason"] for s in plan.skipped))

    def test_empty_mp3_is_kept(self):
        from app.utils.wav_prune import plan_recording
        rec = self._rec()
        wav = rec.wav("combined_audio")
        rec.raw_mp3("combined_audio", b"")
        rec.metadata({"combined": str(wav)})

        self.assertEqual(plan_recording(rec.path).prunable, [])

    def test_truncated_mp3_is_kept(self):
        """A crash mid-conversion leaves a short MP3 — that WAV must survive."""
        from app.utils.wav_prune import plan_recording
        rec = self._rec()
        wav = rec.wav("combined_audio", seconds=30.0)
        rec.mp3("combined_audio", seconds=2.0)
        rec.metadata({"combined": str(wav)})

        plan = plan_recording(rec.path)
        self.assertEqual(plan.prunable, [])
        self.assertTrue(any("duration" in s["reason"] for s in plan.skipped))

    def test_recording_without_metadata_is_skipped_entirely(self):
        """No metadata means nothing to repoint, so leave the whole dir alone."""
        from app.utils.wav_prune import plan_recording
        rec = self._rec()
        rec.wav("combined_audio")
        rec.mp3("combined_audio")

        plan = plan_recording(rec.path)
        self.assertEqual(plan.prunable, [])
        self.assertTrue(any("metadata" in s["reason"] for s in plan.skipped))

    def test_all_three_tracks_planned(self):
        from app.utils.wav_prune import plan_recording
        rec = self._rec()
        files = {}
        for key, stem in (("mic", "mic_audio"), ("system", "system_audio"),
                          ("combined", "combined_audio")):
            files[key] = str(rec.wav(stem))
            rec.mp3(stem)
        rec.metadata(files)

        plan = plan_recording(rec.path)
        self.assertEqual(sorted(p["key"] for p in plan.prunable),
                         ["combined", "mic", "system"])
        self.assertGreater(plan.reclaimed_bytes, 0)


class TestApplyPlan(PruneTestCase):
    """apply_plan repoints metadata first, then deletes."""

    def _prepared(self):
        from app.utils.wav_prune import plan_recording
        rec = self._rec()
        wav = rec.wav("combined_audio")
        mp3 = rec.mp3("combined_audio")
        rec.metadata({"combined": str(wav)}, combined_mp3=str(mp3))
        return rec, wav, mp3, plan_recording(rec.path)

    def test_wav_deleted_and_metadata_repointed(self):
        from app.utils.wav_prune import apply_plan
        rec, wav, mp3, plan = self._prepared()
        apply_plan(plan)

        self.assertFalse(wav.exists())
        self.assertTrue(mp3.exists())
        self.assertEqual(rec.read_metadata()["audio_files"]["combined"], str(mp3))

    def test_redundant_mp3_key_dropped(self):
        from app.utils.wav_prune import apply_plan
        rec, _, _, plan = self._prepared()
        apply_plan(plan)
        self.assertNotIn("combined_mp3", rec.read_metadata()["audio_files"])

    def test_metadata_failure_leaves_wav_alone(self):
        """If the metadata rewrite fails the audio must still be there."""
        from unittest.mock import patch
        from app.utils.wav_prune import apply_plan
        rec, wav, _, plan = self._prepared()
        with patch("app.utils.wav_prune.atomic_write_json",
                   side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                apply_plan(plan)
        self.assertTrue(wav.exists())

    def test_apply_is_idempotent(self):
        from app.utils.wav_prune import apply_plan, plan_recording
        rec, wav, mp3, plan = self._prepared()
        apply_plan(plan)
        second = plan_recording(rec.path)
        self.assertEqual(second.prunable, [])
        apply_plan(second)
        self.assertTrue(mp3.exists())
        self.assertEqual(rec.read_metadata()["audio_files"]["combined"], str(mp3))


class TestPlanLibrary(PruneTestCase):
    def test_scans_every_recording_dir(self):
        from app.utils.wav_prune import plan_library
        for name in ("recording_a", "recording_b"):
            rec = self._rec(name)
            wav = rec.wav("combined_audio")
            rec.mp3("combined_audio")
            rec.metadata({"combined": str(wav)})

        plans = plan_library(self.root)
        self.assertEqual(len(plans), 2)
        self.assertTrue(all(p.prunable for p in plans))

    def test_ignores_non_recording_entries(self):
        from app.utils.wav_prune import plan_library
        (self.root / "notes.txt").write_text("hi", encoding="utf-8")
        self.assertEqual(plan_library(self.root), [])


if __name__ == "__main__":
    unittest.main()
