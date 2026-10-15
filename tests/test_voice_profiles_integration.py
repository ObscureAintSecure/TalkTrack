# tests/test_voice_profiles_integration.py
"""Voice profiles wired into the worker, the speaker panel and MainWindow (#128).

MainWindow is never constructed: its methods run against a stub self, the same
pattern as test_system_monitor_start.py.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from app.transcription import voice_profiles as vp

ALICE = np.array([1.0, 0.0, 0.0])
BOB = np.array([0.0, 1.0, 0.0])


class TestDiarizationWorkerKeepsEmbeddings(unittest.TestCase):
    def _run(self, pipeline_output):
        from app.transcription.diarizer import DiarizationWorker
        from app.transcription.transcriber import TranscriptResult, TranscriptSegment

        stub = MagicMock()
        stub.audio_path = "a.wav"
        stub.transcript_result = TranscriptResult(
            segments=[TranscriptSegment(start=0.0, end=1.0, text="hi")])
        stub.hf_token = "tok"
        stub.min_speakers = None
        stub.max_speakers = None
        stub.device = "cpu"
        stub._merge_diarization_with_transcript.side_effect = lambda t, s: t

        sf_mod = MagicMock()
        sf_mod.read.return_value = (np.zeros(16000, dtype="float32"), 16000)
        pipeline = MagicMock(return_value=pipeline_output)
        with patch.dict(sys.modules, {"soundfile": sf_mod, "torch": MagicMock()}):
            with patch("app.transcription.diarizer._get_pipeline",
                       return_value=(pipeline, "cpu")):
                DiarizationWorker.run(stub)
        return stub

    def test_centroids_are_mapped_to_labels(self):
        diarization = MagicMock()
        diarization.labels.return_value = ["SPEAKER_00", "SPEAKER_01"]
        diarization.itertracks.return_value = []
        output = SimpleNamespace(speaker_diarization=diarization,
                                 speaker_embeddings=np.array([ALICE, BOB]))
        stub = self._run(output)
        stub.finished.emit.assert_called_once()
        self.assertEqual(sorted(stub.speaker_embeddings), ["SPEAKER_00", "SPEAKER_01"])

    def test_unreadable_embeddings_never_fail_diarization(self):
        diarization = MagicMock()
        diarization.labels.side_effect = RuntimeError("boom")
        diarization.itertracks.return_value = []
        output = SimpleNamespace(speaker_diarization=diarization,
                                 speaker_embeddings=np.array([ALICE]))
        stub = self._run(output)
        stub.error.emit.assert_not_called()
        stub.finished.emit.assert_called_once()
        self.assertEqual(stub.speaker_embeddings, {})


class TestVoiceMatchHint(unittest.TestCase):
    MATCHES = {"SPEAKER_00": {"name": "Alice", "score": 0.81}}

    def test_hint_while_name_is_the_auto_fill(self):
        from app.ui.speaker_name_panel import _voice_match_hint
        text, tooltip = _voice_match_hint("SPEAKER_00", "Alice", self.MATCHES)
        self.assertEqual(text, "recognized by voice")
        self.assertIn("0.81", tooltip)

    def test_no_hint_once_edited_or_unmatched(self):
        from app.ui.speaker_name_panel import _voice_match_hint
        self.assertIsNone(_voice_match_hint("SPEAKER_00", "Alicia", self.MATCHES))
        self.assertIsNone(_voice_match_hint("SPEAKER_00", "", self.MATCHES))
        self.assertIsNone(_voice_match_hint("SPEAKER_01", "Alice", self.MATCHES))
        self.assertIsNone(_voice_match_hint("SPEAKER_00", "Alice", None))


class TestConfigDefault(unittest.TestCase):
    def test_voice_profiles_off_by_default(self):
        """Biometric data: never collected unless the user opts in."""
        from app.utils.config import DEFAULT_CONFIG
        self.assertIs(DEFAULT_CONFIG["diarization"]["voice_profiles"], False)


class _MainWindowStubTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.rec = root / "recording_20261013_164947"
        self.rec.mkdir()
        self.profiles_path = root / "voice_profiles.json"
        patcher = patch.object(vp, "PROFILES_PATH", self.profiles_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = vp.VoiceProfileStore(self.profiles_path)

    def tearDown(self):
        self._tmp.cleanup()

    def _stub(self, enabled=True):
        from app.main_window import MainWindow
        stub = MagicMock()
        stub.config.get.side_effect = lambda *keys: {
            ("diarization", "voice_profiles"): enabled,
        }[keys]
        stub._read_speaker_names = MainWindow._read_speaker_names
        stub._current_session = {"directory": str(self.rec)}
        return stub

    def _names_on_disk(self):
        path = self.rec / "speaker_names.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


class TestApplyVoiceProfiles(_MainWindowStubTest):
    def test_known_voice_is_written_to_speaker_names(self):
        from app.main_window import MainWindow
        self.store.set_recording("old", {"SPEAKER_04": ("Alice", ALICE)})

        recognized = MainWindow._apply_voice_profiles(
            self._stub(), {"directory": str(self.rec)},
            {"SPEAKER_00": ALICE, "SPEAKER_01": BOB})

        self.assertEqual(recognized, ["Alice"])
        self.assertEqual(self._names_on_disk(), {"SPEAKER_00": "Alice"})
        self.assertTrue((self.rec / vp.EMBEDDINGS_FILE).exists())

    def test_disabled_writes_nothing(self):
        from app.main_window import MainWindow
        self.store.set_recording("old", {"SPEAKER_04": ("Alice", ALICE)})

        recognized = MainWindow._apply_voice_profiles(
            self._stub(enabled=False), {"directory": str(self.rec)}, {"SPEAKER_00": ALICE})

        self.assertEqual(recognized, [])
        self.assertIsNone(self._names_on_disk())
        self.assertFalse((self.rec / vp.EMBEDDINGS_FILE).exists())

    def test_failure_is_swallowed(self):
        """A broken profile store must not cost the user the transcript."""
        from app.main_window import MainWindow
        with patch.object(vp, "apply_to_recording", side_effect=OSError("disk full")):
            recognized = MainWindow._apply_voice_profiles(
                self._stub(), {"directory": str(self.rec)}, {"SPEAKER_00": ALICE})
        self.assertEqual(recognized, [])


class TestSaveSpeakerNamesTrains(_MainWindowStubTest):
    def test_user_names_create_profiles(self):
        from app.main_window import MainWindow
        vp.save_recording_embeddings(self.rec, {"SPEAKER_00": ALICE, "SPEAKER_01": BOB})

        MainWindow._save_speaker_names(self._stub(), {"SPEAKER_00": "Alice"})

        self.assertEqual(self._names_on_disk(), {"SPEAKER_00": "Alice"})
        self.assertEqual(self.store.summary(), [("Alice", 1)])

    def test_disabled_does_not_train(self):
        from app.main_window import MainWindow
        vp.save_recording_embeddings(self.rec, {"SPEAKER_00": ALICE})

        MainWindow._save_speaker_names(self._stub(enabled=False), {"SPEAKER_00": "Alice"})

        self.assertEqual(self._names_on_disk(), {"SPEAKER_00": "Alice"})
        self.assertEqual(self.store.summary(), [])


if __name__ == "__main__":
    unittest.main()
