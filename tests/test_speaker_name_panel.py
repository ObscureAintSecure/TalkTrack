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


if __name__ == "__main__":
    unittest.main()
