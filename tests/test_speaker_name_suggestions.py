"""Tests for the Speakers panel name suggestions (no Qt)."""
import json
import tempfile
import unittest
from pathlib import Path

from app.ui.speaker_name_suggestions import fold, known_speaker_names, matching_names


def _write(root, recording, names):
    d = Path(root) / recording
    d.mkdir(parents=True, exist_ok=True)
    (d / "speaker_names.json").write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")


class TestFold(unittest.TestCase):

    def test_ignores_case_accents_and_spacing(self):
        self.assertEqual(fold("  Fábio   FETI "), "fabio feti")
        self.assertEqual(fold("Júlio César"), fold("julio cesar"))

    def test_empty(self):
        self.assertEqual(fold(None), "")
        self.assertEqual(fold("   "), "")


class TestKnownSpeakerNames(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_most_used_first(self):
        _write(self.root, "recording_1", {"SPEAKER_00": "Ana", "SPEAKER_01": "Bruno"})
        _write(self.root, "recording_2", {"SPEAKER_00": "Bruno"})
        _write(self.root, "recording_3", {"SPEAKER_02": "Bruno", "SPEAKER_00": "Carla"})
        self.assertEqual(known_speaker_names(self.root), ["Bruno", "Ana", "Carla"])

    def test_spelling_variants_are_one_name_shown_as_the_most_used(self):
        _write(self.root, "recording_1", {"SPEAKER_00": "Fábio Feti"})
        _write(self.root, "recording_2", {"SPEAKER_00": "fabio feti"})
        _write(self.root, "recording_3", {"SPEAKER_01": "Fábio  Feti"})
        self.assertEqual(known_speaker_names(self.root), ["Fábio Feti"])

    def test_tie_between_spellings_goes_to_the_latest_recording(self):
        _write(self.root, "recording_20261013_100000", {"SPEAKER_00": "fabio"})
        _write(self.root, "recording_20261015_100000", {"SPEAKER_00": "Fábio"})
        self.assertEqual(known_speaker_names(self.root), ["Fábio"])

    def test_same_name_twice_in_one_recording_counts_once(self):
        _write(self.root, "recording_1", {"SPEAKER_00": "Ana", "SPEAKER_03": "Ana"})
        _write(self.root, "recording_2", {"SPEAKER_00": "Bruno"})
        _write(self.root, "recording_3", {"SPEAKER_00": "Bruno"})
        self.assertEqual(known_speaker_names(self.root), ["Bruno", "Ana"])

    def test_skips_blank_corrupt_and_non_string_entries(self):
        _write(self.root, "recording_1", {"SPEAKER_00": "  ", "SPEAKER_01": 3, "SPEAKER_02": "Ana"})
        bad = Path(self.root) / "recording_2"
        bad.mkdir()
        (bad / "speaker_names.json").write_text("{not json", encoding="utf-8")
        listed = Path(self.root) / "recording_3"
        listed.mkdir()
        (listed / "speaker_names.json").write_text('["Ana"]', encoding="utf-8")
        self.assertEqual(known_speaker_names(self.root), ["Ana"])

    def test_missing_or_unset_directory(self):
        self.assertEqual(known_speaker_names(Path(self.root) / "nope"), [])
        self.assertEqual(known_speaker_names(None), [])
        self.assertEqual(known_speaker_names(""), [])

    def test_extra_names_are_added_once(self):
        _write(self.root, "recording_1", {"SPEAKER_00": "Ana"})
        names = known_speaker_names(self.root, extra_names=["ana", "Diego", " ", None])
        self.assertEqual(names, ["Ana", "Diego"])


class TestMatchingNames(unittest.TestCase):

    NAMES = ["Edivaldo Santos", "Fábio Ferreira Feti", "Milton Salles (Cabelo)", "Ana Fabiola"]

    def test_word_start_before_substring(self):
        self.assertEqual(matching_names(self.NAMES, "fab"), ["Fábio Ferreira Feti", "Ana Fabiola"])
        self.assertEqual(matching_names(["Rafabio", "Fabio"], "fab"), ["Fabio", "Rafabio"])

    def test_matches_any_word_ignoring_case_and_accents(self):
        self.assertEqual(matching_names(self.NAMES, "FETI"), ["Fábio Ferreira Feti"])
        self.assertEqual(matching_names(self.NAMES, "cabelo"), ["Milton Salles (Cabelo)"])
        self.assertEqual(matching_names(["Júlio César"], "cesar"), ["Júlio César"])

    def test_substring_inside_a_word(self):
        self.assertEqual(matching_names(self.NAMES, "valdo"), ["Edivaldo Santos"])

    def test_names_used_by_other_speakers_are_left_out(self):
        self.assertEqual(matching_names(self.NAMES, "fab", exclude=["fabio ferreira feti"]),
                         ["Ana Fabiola"])

    def test_nothing_for_blank_text_or_an_exact_match(self):
        self.assertEqual(matching_names(self.NAMES, "  "), [])
        self.assertEqual(matching_names(self.NAMES, "edivaldo santos"), [])

    def test_limit(self):
        names = [f"Name {i}" for i in range(30)]
        self.assertEqual(len(matching_names(names, "name")), 10)
        self.assertEqual(matching_names(names, "name", limit=2), ["Name 0", "Name 1"])


class TestShowSuggestions(unittest.TestCase):
    """SpeakerNamePanel._show_suggestions against a stub panel (no widgets)."""

    def test_names_of_the_other_speakers_are_not_offered(self):
        from unittest.mock import MagicMock
        from app.ui.speaker_name_panel import SpeakerNamePanel
        stub = MagicMock()
        stub._known_names = ["Fabio Feti", "Ana Fabiola", "Bruno"]
        stub.get_speaker_names.return_value = {"SPEAKER_00": "fab", "SPEAKER_01": "Ana Fabiola"}
        model, completer = MagicMock(), MagicMock()
        SpeakerNamePanel._show_suggestions(stub, "SPEAKER_00", "fab", model, completer)
        model.setStringList.assert_called_once_with(["Fabio Feti"])
        completer.complete.assert_called_once()

    def test_popup_hides_when_nothing_matches(self):
        from unittest.mock import MagicMock
        from app.ui.speaker_name_panel import SpeakerNamePanel
        stub = MagicMock()
        stub._known_names = ["Bruno"]
        stub.get_speaker_names.return_value = {}
        model, completer = MagicMock(), MagicMock()
        SpeakerNamePanel._show_suggestions(stub, "SPEAKER_00", "zz", model, completer)
        completer.complete.assert_not_called()
        completer.popup().hide.assert_called_once()


if __name__ == "__main__":
    unittest.main()
