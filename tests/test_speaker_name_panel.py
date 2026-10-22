"""Tests for SpeakerNamePanel logic."""
import unittest


class TestSpeakerNamePanelLogic(unittest.TestCase):

    def test_build_speaker_list_from_segments(self):
        """Extract unique sorted speakers from segments."""
        from app.ui.speaker_name_panel import _extract_speakers
        from app.transcription.transcriber import TranscriptSegment
        segments = [
            TranscriptSegment(start=0, end=1, text="a", speaker="SPEAKER_01"),
            TranscriptSegment(start=1, end=2, text="b", speaker="SPEAKER_00"),
            TranscriptSegment(start=2, end=3, text="c", speaker="SPEAKER_01"),
            TranscriptSegment(start=3, end=4, text="d", speaker=""),
        ]
        speakers = _extract_speakers(segments)
        self.assertEqual(speakers, ["SPEAKER_00", "SPEAKER_01"])

    def test_build_speaker_list_empty_segments(self):
        from app.ui.speaker_name_panel import _extract_speakers
        self.assertEqual(_extract_speakers([]), [])


def _segs(*speakers):
    from app.transcription.transcriber import TranscriptSegment
    return [TranscriptSegment(start=i * 2, end=i * 2 + 1.5, text=str(i), speaker=s)
            for i, s in enumerate(speakers)]


class TestSpeakerTurns(unittest.TestCase):

    def test_a_turn_starts_where_the_speaker_takes_over(self):
        from app.ui.speaker_name_panel import speaker_turns
        segs = _segs("A", "A", "B", "A", "B", "B", "A")
        self.assertEqual(speaker_turns(segs, "A"), [0, 3, 6])
        self.assertEqual(speaker_turns(segs, "B"), [2, 4])

    def test_unknown_speaker_has_no_turns(self):
        from app.ui.speaker_name_panel import speaker_turns
        self.assertEqual(speaker_turns(_segs("A", "B"), "C"), [])
        self.assertEqual(speaker_turns([], "A"), [])

    def test_unlabelled_segment_between_breaks_the_turn(self):
        from app.ui.speaker_name_panel import speaker_turns
        self.assertEqual(speaker_turns(_segs("A", "", "A"), "A"), [0, 2])


class TestNextTurn(unittest.TestCase):

    def test_first_click_goes_to_the_first_turn(self):
        from app.ui.speaker_name_panel import next_turn
        self.assertEqual(next_turn([2, 4, 9], -1), (2, 1))

    def test_walks_forward_from_the_last_jump(self):
        from app.ui.speaker_name_panel import next_turn
        self.assertEqual(next_turn([2, 4, 9], 2), (4, 2))
        self.assertEqual(next_turn([2, 4, 9], 5), (9, 3))

    def test_wraps_after_the_last_turn(self):
        from app.ui.speaker_name_panel import next_turn
        self.assertEqual(next_turn([2, 4, 9], 9), (2, 1))

    def test_no_turns(self):
        from app.ui.speaker_name_panel import next_turn
        self.assertIsNone(next_turn([], -1))


class TestSpeakerSummary(unittest.TestCase):

    def test_turns_and_talk_time(self):
        from app.ui.speaker_name_panel import _speaker_summary
        segs = _segs("A", "B", "A")
        self.assertTrue(_speaker_summary(segs, "A").startswith("2 turns, 3 s of speech."))
        self.assertTrue(_speaker_summary(segs, "B").startswith("1 turn, 2 s of speech."))

    def test_minutes(self):
        from app.ui.speaker_name_panel import _speaker_summary
        from app.transcription.transcriber import TranscriptSegment
        segs = [TranscriptSegment(start=0, end=125, text="x", speaker="A")]
        self.assertTrue(_speaker_summary(segs, "A").startswith("1 turn, 2 min 05 s"))

class TestJumpToSpeaker(unittest.TestCase):
    """TranscriptViewer._jump_to_speaker against a stub viewer (no widgets)."""

    def _viewer(self, *speakers):
        from unittest.mock import MagicMock
        stub = MagicMock()
        stub._transcript.segments = _segs(*speakers)
        stub._segment_widgets = [MagicMock(**{"y.return_value": 100 * i}) for i in range(len(speakers))]
        stub._jump_speaker = None
        stub._jump_index = -1
        return stub

    def _jump(self, stub, speaker):
        from app.ui.transcript_viewer import TranscriptViewer
        TranscriptViewer._jump_to_speaker(stub, speaker)
        return stub._jump_index

    def test_repeated_clicks_walk_the_turns_and_wrap(self):
        stub = self._viewer("A", "B", "A", "A", "B", "A")
        self.assertEqual([self._jump(stub, "A") for _ in range(4)], [0, 2, 5, 0])
        stub.speaker_panel.set_turn_position.assert_called_with("A", 1, 3)

    def test_another_speaker_starts_at_their_first_turn(self):
        stub = self._viewer("A", "B", "A", "A", "B", "A")
        self._jump(stub, "A")
        self._jump(stub, "A")
        self.assertEqual(self._jump(stub, "B"), 1)
        stub.speaker_panel.set_turn_position.assert_called_with("B", 1, 2)

    def test_scrolls_the_turn_near_the_top_and_flashes_it(self):
        stub = self._viewer("A", "B", "B")
        self._jump(stub, "B")
        stub.scroll_area.verticalScrollBar().setValue.assert_called_with(60)
        stub._flash_segment.assert_called_with(1)

    def test_nothing_happens_without_a_transcript(self):
        stub = self._viewer("A")
        stub._transcript = None
        self.assertEqual(self._jump(stub, "A"), -1)
        stub.speaker_panel.set_turn_position.assert_not_called()

if __name__ == "__main__":
    unittest.main()
