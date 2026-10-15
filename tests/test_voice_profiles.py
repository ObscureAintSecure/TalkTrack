# tests/test_voice_profiles.py
"""Voice profiles: recognise named speakers across recordings (#128)."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

from app.transcription import voice_profiles as vp


def _vec(*values):
    return np.array(values, dtype=np.float64)


# Three well-separated "voices" in a toy 3-D embedding space.
ALICE = _vec(1.0, 0.0, 0.0)
BOB = _vec(0.0, 1.0, 0.0)
CAROL = _vec(0.0, 0.0, 1.0)


def _near(vec, noise=0.1, seed=0):
    rng = np.random.default_rng(seed)
    return vec + rng.normal(0, noise, size=vec.shape)


class TestCleanEmbedding(unittest.TestCase):
    def test_accepts_list(self):
        np.testing.assert_array_equal(vp.clean_embedding([1, 2, 3]), [1.0, 2.0, 3.0])

    def test_rejects_zero_vector(self):
        """pyannote pads centroids with zero rows for speakers it couldn't embed."""
        self.assertIsNone(vp.clean_embedding([0.0, 0.0, 0.0]))

    def test_rejects_non_finite(self):
        self.assertIsNone(vp.clean_embedding([1.0, float("nan"), 0.0]))
        self.assertIsNone(vp.clean_embedding([1.0, float("inf"), 0.0]))

    def test_rejects_wrong_shape_and_garbage(self):
        self.assertIsNone(vp.clean_embedding([[1.0, 0.0]]))
        self.assertIsNone(vp.clean_embedding([]))
        self.assertIsNone(vp.clean_embedding(None))
        self.assertIsNone(vp.clean_embedding("abc"))


class TestSpeakerEmbeddingsByLabel(unittest.TestCase):
    def _diarization(self, labels):
        d = MagicMock()
        d.labels.return_value = labels
        return d

    def test_rows_follow_label_order(self):
        output = SimpleNamespace(speaker_embeddings=np.array([ALICE, BOB]))
        result = vp.speaker_embeddings_by_label(
            output, self._diarization(["SPEAKER_00", "SPEAKER_01"]))
        np.testing.assert_array_equal(result["SPEAKER_00"], ALICE)
        np.testing.assert_array_equal(result["SPEAKER_01"], BOB)

    def test_zero_padded_rows_are_skipped(self):
        output = SimpleNamespace(speaker_embeddings=np.array([ALICE, np.zeros(3)]))
        result = vp.speaker_embeddings_by_label(
            output, self._diarization(["SPEAKER_00", "SPEAKER_01"]))
        self.assertEqual(list(result), ["SPEAKER_00"])

    def test_fewer_rows_than_labels(self):
        output = SimpleNamespace(speaker_embeddings=np.array([ALICE]))
        result = vp.speaker_embeddings_by_label(
            output, self._diarization(["SPEAKER_00", "SPEAKER_01"]))
        self.assertEqual(list(result), ["SPEAKER_00"])

    def test_output_without_embeddings(self):
        """Older pyannote returns a bare Annotation."""
        self.assertEqual(
            vp.speaker_embeddings_by_label(object(), self._diarization(["SPEAKER_00"])), {})


class TestMatchSpeakers(unittest.TestCase):
    PROFILES = {"Alice": ALICE, "Bob": BOB}

    def test_matches_close_voices(self):
        matches = vp.match_speakers(
            {"SPEAKER_00": _near(BOB, seed=1), "SPEAKER_01": _near(ALICE, seed=2)},
            self.PROFILES, threshold=0.6)
        self.assertEqual(matches["SPEAKER_00"][0], "Bob")
        self.assertEqual(matches["SPEAKER_01"][0], "Alice")

    def test_unknown_voice_stays_unmatched(self):
        matches = vp.match_speakers({"SPEAKER_00": CAROL}, self.PROFILES, threshold=0.6)
        self.assertEqual(matches, {})

    def test_one_to_one_best_score_wins(self):
        """Two speakers close to the same profile: only the closer one gets the name."""
        closer = ALICE + 0.05 * BOB
        farther = ALICE + 0.4 * BOB
        matches = vp.match_speakers(
            {"SPEAKER_00": farther, "SPEAKER_01": closer}, {"Alice": ALICE}, threshold=0.6)
        self.assertEqual(list(matches), ["SPEAKER_01"])

    def test_excluded_names_are_never_assigned(self):
        matches = vp.match_speakers(
            {"SPEAKER_00": ALICE}, self.PROFILES, threshold=0.6, exclude_names={"Alice"})
        self.assertEqual(matches, {})

    def test_dimension_mismatch_is_ignored(self):
        matches = vp.match_speakers(
            {"SPEAKER_00": _vec(1.0, 0.0)}, self.PROFILES, threshold=0.6)
        self.assertEqual(matches, {})

    def test_score_is_cosine_similarity(self):
        matches = vp.match_speakers({"SPEAKER_00": 5 * ALICE}, self.PROFILES, threshold=0.6)
        self.assertAlmostEqual(matches["SPEAKER_00"][1], 1.0)


def _at_cosine(profile, other, cosine):
    """A vector at exactly `cosine` similarity to unit `profile`, leaning toward `other`."""
    return cosine * profile + np.sqrt(1 - cosine ** 2) * other


class TestDefaultThreshold(unittest.TestCase):
    """Scores seen in real meetings (see the notes on MATCH_THRESHOLD)."""

    def _match(self, cosine):
        return vp.match_speakers({"SPEAKER_00": _at_cosine(ALICE, BOB, cosine)},
                                 {"Alice": ALICE})

    def test_different_people_seen_in_real_meetings_stay_unnamed(self):
        # 0.627 auto-filled a person who was not in the meeting under 0.6.
        for cosine in (0.605, 0.627, 0.631, 0.7):
            with self.subTest(cosine=cosine):
                self.assertEqual(self._match(cosine), {})

    def test_same_person_in_another_meeting_is_still_recognised(self):
        for cosine in (0.849, 0.857, 0.908, 0.95):
            with self.subTest(cosine=cosine):
                self.assertEqual(self._match(cosine)["SPEAKER_00"][0], "Alice")


class TestTrainedNames(unittest.TestCase):
    def test_untouched_auto_fill_does_not_train(self):
        names = {"SPEAKER_00": "Alice"}
        matches = {"SPEAKER_00": {"name": "Alice", "score": 0.8}}
        self.assertEqual(vp.trained_names(names, matches), {})

    def test_corrected_auto_fill_trains(self):
        names = {"SPEAKER_00": "Bob"}
        matches = {"SPEAKER_00": {"name": "Alice", "score": 0.8}}
        self.assertEqual(vp.trained_names(names, matches), {"SPEAKER_00": "Bob"})

    def test_manual_names_train_and_blanks_do_not(self):
        names = {"SPEAKER_00": " Alice ", "SPEAKER_01": "  ", "SPEAKER_02": ""}
        self.assertEqual(vp.trained_names(names, {}), {"SPEAKER_00": "Alice"})


class _TmpDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class TestVoiceProfileStore(_TmpDirTest):
    def setUp(self):
        super().setUp()
        self.store = vp.VoiceProfileStore(self.dir / "voice_profiles.json")

    def test_empty_store(self):
        self.assertEqual(self.store.profiles(), {})
        self.assertEqual(self.store.summary(), [])

    def test_profile_is_mean_of_unit_contributions(self):
        self.store.set_recording("rec1", {"SPEAKER_00": ("Alice", 10 * ALICE)})
        self.store.set_recording("rec2", {"SPEAKER_03": ("Alice", _vec(1.0, 1.0, 0.0))})
        profile = self.store.profiles()["Alice"]
        expected = ALICE + _vec(1.0, 1.0, 0.0) / np.sqrt(2)
        np.testing.assert_allclose(profile, expected / np.linalg.norm(expected), atol=1e-6)

    def test_set_recording_is_idempotent(self):
        """The speaker panel reports every keystroke; repeats must not pile up."""
        self.assertTrue(self.store.set_recording("rec1", {"SPEAKER_00": ("Alice", ALICE)}))
        self.assertFalse(self.store.set_recording("rec1", {"SPEAKER_00": ("Alice", ALICE)}))
        self.assertEqual(self.store.summary(), [("Alice", 1)])

    def test_rename_moves_the_voice(self):
        self.store.set_recording("rec1", {"SPEAKER_00": ("Alic", ALICE)})
        self.store.set_recording("rec1", {"SPEAKER_00": ("Alice", ALICE)})
        self.assertEqual(self.store.summary(), [("Alice", 1)])

    def test_clearing_a_name_removes_the_contribution(self):
        self.store.set_recording("rec1", {"SPEAKER_00": ("Alice", ALICE)})
        self.store.set_recording("rec1", {})
        self.assertEqual(self.store.profiles(), {})

    def test_other_recordings_are_untouched(self):
        self.store.set_recording("rec1", {"SPEAKER_00": ("Alice", ALICE)})
        self.store.set_recording("rec2", {"SPEAKER_00": ("Bob", BOB)})
        self.store.set_recording("rec2", {})
        self.assertEqual(self.store.summary(), [("Alice", 1)])

    def test_other_model_is_never_mixed_in(self):
        self.store.set_recording("rec1", {"SPEAKER_00": ("Alice", ALICE)}, model_id="old-model")
        self.assertEqual(self.store.profiles(), {})
        self.assertIn("Alice", self.store.profiles(model_id="old-model"))

    def test_delete_profile_and_clear(self):
        self.store.set_recording("rec1", {"SPEAKER_00": ("Alice", ALICE),
                                          "SPEAKER_01": ("Bob", BOB)})
        self.store.delete_profile("Alice")
        self.assertEqual(self.store.summary(), [("Bob", 1)])
        self.store.clear()
        self.assertEqual(self.store.summary(), [])

    def test_summary_counts_recordings(self):
        self.store.set_recording("rec1", {"SPEAKER_00": ("bob", BOB)})
        self.store.set_recording("rec2", {"SPEAKER_01": ("bob", BOB)})
        self.store.set_recording("rec2", {"SPEAKER_01": ("bob", BOB),
                                          "SPEAKER_02": ("Alice", ALICE)})
        self.assertEqual(self.store.summary(), [("Alice", 1), ("bob", 2)])

    def test_two_instances_never_overwrite_each_other(self):
        """Settings deletes through its own instance; MainWindow's must see it."""
        other = vp.VoiceProfileStore(self.store.path)
        self.store.set_recording("rec1", {"SPEAKER_00": ("Alice", ALICE)})
        other.delete_profile("Alice")
        self.store.set_recording("rec2", {"SPEAKER_00": ("Bob", BOB)})
        self.assertEqual(self.store.summary(), [("Bob", 1)])

    def test_corrupt_file_is_backed_up_not_crashing(self):
        self.store.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.store.profiles(), {})
        self.assertTrue(self.store.path.with_name("voice_profiles.json.bak").exists())

    def test_invalid_contributions_are_dropped(self):
        self.store.path.write_text(json.dumps({"version": 1, "contributions": [
            {"recording": "r", "speaker": "S", "name": "Alice", "model": vp.EMBEDDING_MODEL_ID,
             "embedding": [0, 0, 0]},
            {"recording": "r", "speaker": "T", "name": "Bob", "model": vp.EMBEDDING_MODEL_ID,
             "embedding": [0, 1, 0]},
            "garbage",
        ]}), encoding="utf-8")
        self.assertEqual(list(self.store.profiles()), ["Bob"])


class TestRecordingFiles(_TmpDirTest):
    def test_embeddings_round_trip(self):
        vp.save_recording_embeddings(self.dir, {"SPEAKER_00": ALICE})
        loaded = vp.load_recording_embeddings(self.dir)
        np.testing.assert_allclose(loaded["SPEAKER_00"], ALICE)

    def test_embeddings_from_another_model_are_ignored(self):
        vp.save_recording_embeddings(self.dir, {"SPEAKER_00": ALICE}, model_id="old-model")
        self.assertEqual(vp.load_recording_embeddings(self.dir), {})

    def test_missing_or_corrupt_files_read_as_empty(self):
        self.assertEqual(vp.load_recording_embeddings(self.dir), {})
        self.assertEqual(vp.load_voice_matches(self.dir), {})
        (self.dir / vp.MATCHES_FILE).write_text("[1, 2", encoding="utf-8")
        self.assertEqual(vp.load_voice_matches(self.dir), {})

    def test_matches_round_trip(self):
        vp.save_voice_matches(self.dir, {"SPEAKER_00": ("Álvaro", 0.81234)})
        self.assertEqual(vp.load_voice_matches(self.dir),
                         {"SPEAKER_00": {"name": "Álvaro", "score": 0.812}})


class TestApplyAndTrain(_TmpDirTest):
    """The two entry points MainWindow calls."""

    def setUp(self):
        super().setUp()
        self.store = vp.VoiceProfileStore(self.dir / "voice_profiles.json")
        self.rec = self.dir / "recording_20261013_164947"
        self.rec.mkdir()

    def test_first_recording_named_by_hand_trains_the_store(self):
        filled, matches = vp.apply_to_recording(
            self.rec, {"SPEAKER_00": ALICE, "SPEAKER_01": BOB}, {}, self.store)
        self.assertEqual((filled, matches), ({}, {}))

        vp.train_from_names(self.rec, {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"}, self.store)
        self.assertEqual(self.store.summary(), [("Alice", 1), ("Bob", 1)])

    def test_next_recording_is_auto_filled_and_does_not_train(self):
        self.store.set_recording("old", {"SPEAKER_00": ("Alice", ALICE),
                                         "SPEAKER_01": ("Bob", BOB)})
        filled, matches = vp.apply_to_recording(
            self.rec, {"SPEAKER_00": _near(BOB, seed=3), "SPEAKER_01": CAROL},
            {}, self.store)

        self.assertEqual(filled, {"SPEAKER_00": "Bob"})
        self.assertEqual(list(matches), ["SPEAKER_00"])
        self.assertEqual(vp.load_voice_matches(self.rec)["SPEAKER_00"]["name"], "Bob")
        # The auto-fill is a suggestion: it must not have trained the store.
        self.assertEqual(self.store.summary(), [("Alice", 1), ("Bob", 1)])

    def test_correcting_an_auto_fill_trains_the_corrected_name(self):
        self.store.set_recording("old", {"SPEAKER_00": ("Alice", ALICE)})
        vp.apply_to_recording(self.rec, {"SPEAKER_00": ALICE}, {}, self.store)

        vp.train_from_names(self.rec, {"SPEAKER_00": "Alicia"}, self.store)
        self.assertEqual(self.store.summary(), [("Alice", 1), ("Alicia", 1)])

    def test_existing_names_are_kept_and_never_reassigned(self):
        """Re-transcribing a named recording keeps its names and trains on them."""
        self.store.set_recording("old", {"SPEAKER_00": ("Alice", ALICE)})
        filled, matches = vp.apply_to_recording(
            self.rec, {"SPEAKER_00": BOB, "SPEAKER_01": ALICE},
            {"SPEAKER_00": "Alice"}, self.store)

        self.assertEqual(filled, {"SPEAKER_00": "Alice"})   # Alice not given twice
        self.assertEqual(matches, {})
        self.assertEqual(self.store.summary(), [("Alice", 2)])

    def test_retranscribing_never_promotes_old_auto_fills_to_training(self):
        """Last run's untouched suggestion is re-matched, not learned as the user's."""
        self.store.set_recording("old", {"SPEAKER_00": ("Alice", ALICE)})
        filled, _ = vp.apply_to_recording(self.rec, {"SPEAKER_00": ALICE}, {}, self.store)
        self.assertEqual(filled, {"SPEAKER_00": "Alice"})

        # Re-transcription: labels shuffled, the stale auto-fill is still on disk.
        filled, matches = vp.apply_to_recording(
            self.rec, {"SPEAKER_00": BOB, "SPEAKER_01": ALICE}, filled, self.store)

        self.assertEqual(filled, {"SPEAKER_01": "Alice"})
        self.assertEqual(list(matches), ["SPEAKER_01"])
        self.assertEqual(self.store.summary(), [("Alice", 1)])   # only "old" trains

    def test_train_without_embeddings_is_a_no_op(self):
        """Recordings diarized before the feature was enabled have no centroids."""
        self.assertFalse(vp.train_from_names(self.rec, {"SPEAKER_00": "Alice"}, self.store))
        self.assertEqual(self.store.summary(), [])


if __name__ == "__main__":
    unittest.main()
