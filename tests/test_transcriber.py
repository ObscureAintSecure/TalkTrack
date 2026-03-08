"""Tests for TranscriptSegment and TranscriptResult."""
import unittest
from app.transcription.transcriber import TranscriptSegment, TranscriptResult


class TestTranscriptSegment(unittest.TestCase):

    def test_to_dict_without_original_text(self):
        seg = TranscriptSegment(start=1.0, end=2.0, text="hello")
        d = seg.to_dict()
        self.assertEqual(d["text"], "hello")
        self.assertNotIn("original_text", d)

    def test_to_dict_with_original_text(self):
        seg = TranscriptSegment(start=1.0, end=2.0, text="Q4", original_text="quarterly")
        d = seg.to_dict()
        self.assertEqual(d["text"], "Q4")
        self.assertEqual(d["original_text"], "quarterly")

    def test_to_dict_with_empty_original_text_omits_it(self):
        seg = TranscriptSegment(start=1.0, end=2.0, text="hello", original_text="")
        d = seg.to_dict()
        self.assertNotIn("original_text", d)

    def test_from_dict_with_original_text(self):
        """TranscriptSegment(**dict) should accept original_text."""
        data = {"start": 1.0, "end": 2.0, "text": "Q4", "original_text": "quarterly",
                "speaker": "", "confidence": 0.0}
        seg = TranscriptSegment(**data)
        self.assertEqual(seg.original_text, "quarterly")

    def test_from_dict_without_original_text(self):
        data = {"start": 1.0, "end": 2.0, "text": "hello", "speaker": "", "confidence": 0.0}
        seg = TranscriptSegment(**data)
        self.assertEqual(seg.original_text, "")


if __name__ == "__main__":
    unittest.main()
