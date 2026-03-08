"""Tests for SegmentWidget logic."""
import unittest
from app.transcription.transcriber import TranscriptSegment


class TestSegmentWidgetHelpers(unittest.TestCase):

    def test_format_time(self):
        from app.ui.segment_widget import _format_time
        self.assertEqual(_format_time(0), "00:00:00")
        self.assertEqual(_format_time(65), "00:01:05")
        self.assertEqual(_format_time(3661), "01:01:01")

    def test_display_speaker_with_name(self):
        from app.ui.segment_widget import _display_speaker
        self.assertEqual(
            _display_speaker("SPEAKER_00", {"SPEAKER_00": "Alice"}),
            "Alice"
        )

    def test_display_speaker_without_name(self):
        from app.ui.segment_widget import _display_speaker
        self.assertEqual(
            _display_speaker("SPEAKER_00", {}),
            "SPEAKER_00"
        )

    def test_display_speaker_empty(self):
        from app.ui.segment_widget import _display_speaker
        self.assertEqual(_display_speaker("", {}), "")

    def test_display_speaker_empty_name_value(self):
        from app.ui.segment_widget import _display_speaker
        self.assertEqual(
            _display_speaker("SPEAKER_00", {"SPEAKER_00": ""}),
            "SPEAKER_00"
        )


if __name__ == "__main__":
    unittest.main()
