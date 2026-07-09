"""Tests for TranscriptSegment and TranscriptResult."""
import math
import sys
import unittest
from unittest.mock import MagicMock, patch

from app.transcription.transcriber import TranscriptSegment, TranscriptResult


class _FwMocks:
    """Build a mocked faster_whisper module returning given segments.

    Wires both the sequential path (``WhisperModel.transcribe``) and the
    batched path (``BatchedInferencePipeline(model=...).transcribe``).
    """

    def __init__(self, segments=(), duration=5.0):
        segs = list(segments)
        self.module = MagicMock()
        self.model = MagicMock()
        self.module.WhisperModel.return_value = self.model
        info = MagicMock(language="en", duration=duration)
        self.model.transcribe.return_value = (iter(segs), info)
        # Batched pipeline: BatchedInferencePipeline(model=...).transcribe(...)
        self.pipeline = MagicMock()
        self.module.BatchedInferencePipeline.return_value = self.pipeline
        self.pipeline.transcribe.return_value = (iter(segs), info)


class TestWhisperModelCache(unittest.TestCase):
    def test_same_params_reuse_model(self):
        fw = _FwMocks()
        with patch.dict(sys.modules, {"faster_whisper": fw.module}):
            import app.transcription.transcriber as tr
            tr._MODEL_CACHE.clear()
            m1 = tr._get_model("base", "cpu", "int8")
            m2 = tr._get_model("base", "cpu", "int8")
        self.assertIs(m1, m2)
        self.assertEqual(fw.module.WhisperModel.call_count, 1)

    def test_different_params_create_new_model(self):
        fw = _FwMocks()
        with patch.dict(sys.modules, {"faster_whisper": fw.module}):
            import app.transcription.transcriber as tr
            tr._MODEL_CACHE.clear()
            tr._get_model("base", "cpu", "int8")
            tr._get_model("small", "cpu", "int8")
        self.assertEqual(fw.module.WhisperModel.call_count, 2)


class TestRunSegmentMapping(unittest.TestCase):
    def _run_worker(self, segments):
        # batch_size=1 exercises the classic sequential path (model.transcribe).
        fw = _FwMocks(segments=segments)
        with patch.dict(sys.modules, {"faster_whisper": fw.module}):
            import app.transcription.transcriber as tr
            tr._MODEL_CACHE.clear()
            worker = tr.TranscriptionWorker(
                "a.wav", model_size="base", device="cpu", batch_size=1
            )
            results = []
            worker.finished.connect(results.append)
            worker.run()
        return results, fw.model

    def test_confidence_populated_from_avg_logprob(self):
        seg = MagicMock(start=0.0, end=1.0, text=" hi ", avg_logprob=-0.5)
        results, _ = self._run_worker([seg])
        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(
            results[0].segments[0].confidence, math.exp(-0.5), places=5
        )

    def test_word_timestamps_not_requested(self):
        _, model = self._run_worker([])
        kwargs = model.transcribe.call_args.kwargs
        self.assertNotIn("word_timestamps", kwargs)


class TestBatchedInference(unittest.TestCase):
    """batch_size selects BatchedInferencePipeline (>1) vs the sequential path (1)."""

    def _run(self, batch_size, segments=()):
        fw = _FwMocks(segments=segments)
        with patch.dict(sys.modules, {"faster_whisper": fw.module}):
            import app.transcription.transcriber as tr
            tr._MODEL_CACHE.clear()
            worker = tr.TranscriptionWorker(
                "a.wav", model_size="base", device="cpu", batch_size=batch_size
            )
            results = []
            worker.finished.connect(results.append)
            worker.run()
        return results, fw

    def test_batched_path_used_when_batch_size_gt_1(self):
        _, fw = self._run(8)
        fw.module.BatchedInferencePipeline.assert_called_once_with(model=fw.model)
        self.assertEqual(fw.pipeline.transcribe.call_args.kwargs.get("batch_size"), 8)
        fw.model.transcribe.assert_not_called()

    def test_batched_transcribe_enables_vad(self):
        _, fw = self._run(4)
        self.assertTrue(fw.pipeline.transcribe.call_args.kwargs.get("vad_filter"))

    def test_sequential_path_when_batch_size_1(self):
        _, fw = self._run(1)
        fw.module.BatchedInferencePipeline.assert_not_called()
        fw.model.transcribe.assert_called_once()

    def test_batched_segments_mapped_to_result(self):
        seg = MagicMock(start=0.0, end=2.0, text=" hi ", avg_logprob=-0.2)
        results, _ = self._run(8, segments=[seg])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].segments[0].text, "hi")
        self.assertAlmostEqual(
            results[0].segments[0].confidence, math.exp(-0.2), places=5
        )


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

    def test_from_dict_ignores_unknown_keys(self):
        """from_dict should ignore extra keys like speaker_name."""
        data = {"start": 1.0, "end": 2.0, "text": "hello", "speaker": "SPEAKER_00",
                "confidence": 0.9, "speaker_name": "Alice", "extra_field": 42}
        seg = TranscriptSegment.from_dict(data)
        self.assertEqual(seg.text, "hello")
        self.assertEqual(seg.speaker, "SPEAKER_00")
        self.assertFalse(hasattr(seg, "speaker_name"))


class TestTranscriptResultExports(unittest.TestCase):

    def _make_result(self):
        return TranscriptResult(
            segments=[
                TranscriptSegment(start=0.0, end=5.0, text="Hello everyone", speaker="SPEAKER_00"),
                TranscriptSegment(start=5.0, end=10.0, text="Hi there", speaker="SPEAKER_01"),
            ],
            language="en",
            duration=10.0,
        )

    def test_to_text_without_speaker_names(self):
        result = self._make_result()
        text = result.to_text()
        self.assertIn("[SPEAKER_00]", text)
        self.assertIn("[SPEAKER_01]", text)

    def test_to_text_with_speaker_names(self):
        result = self._make_result()
        names = {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"}
        text = result.to_text(speaker_names=names)
        self.assertIn("[Alice]", text)
        self.assertIn("[Bob]", text)
        self.assertNotIn("SPEAKER_00", text)

    def test_to_text_with_partial_speaker_names(self):
        result = self._make_result()
        names = {"SPEAKER_00": "Alice"}
        text = result.to_text(speaker_names=names)
        self.assertIn("[Alice]", text)
        self.assertIn("[SPEAKER_01]", text)

    def test_to_srt_with_speaker_names(self):
        result = self._make_result()
        names = {"SPEAKER_00": "Alice"}
        srt = result.to_srt(speaker_names=names)
        self.assertIn("[Alice]", srt)
        self.assertIn("[SPEAKER_01]", srt)

    def test_to_dict_with_speaker_names(self):
        result = self._make_result()
        names = {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"}
        d = result.to_dict(speaker_names=names)
        self.assertEqual(d["segments"][0]["speaker_name"], "Alice")
        self.assertEqual(d["segments"][1]["speaker_name"], "Bob")
        # Original speaker IDs preserved
        self.assertEqual(d["segments"][0]["speaker"], "SPEAKER_00")

    def test_to_dict_without_speaker_names_has_no_speaker_name_key(self):
        result = self._make_result()
        d = result.to_dict()
        self.assertNotIn("speaker_name", d["segments"][0])


class TestToPlainText(unittest.TestCase):
    """TranscriptResult.to_plain_text: clipboard-friendly, no timestamps."""

    def _make_result(self, segs):
        return TranscriptResult(segments=segs, language="en", duration=10.0)

    def test_empty_transcript_returns_empty_string(self):
        r = self._make_result([])
        self.assertEqual(r.to_plain_text(), "")

    def test_uses_raw_speaker_id_when_no_name_mapping(self):
        segs = [TranscriptSegment(0.0, 1.0, "Hi there.", speaker="SPEAKER_00")]
        r = self._make_result(segs)
        self.assertEqual(r.to_plain_text(), "SPEAKER_00: Hi there.")

    def test_uses_friendly_name_when_provided(self):
        segs = [TranscriptSegment(0.0, 1.0, "Hi there.", speaker="SPEAKER_00")]
        r = self._make_result(segs)
        out = r.to_plain_text(speaker_names={"SPEAKER_00": "Alice"})
        self.assertEqual(out, "Alice: Hi there.")

    def test_empty_friendly_name_falls_back_to_raw_id(self):
        segs = [TranscriptSegment(0.0, 1.0, "Hi.", speaker="SPEAKER_00")]
        r = self._make_result(segs)
        out = r.to_plain_text(speaker_names={"SPEAKER_00": ""})
        self.assertEqual(out, "SPEAKER_00: Hi.")

    def test_segment_without_speaker_has_no_prefix(self):
        segs = [TranscriptSegment(0.0, 1.0, "Unidentified line.")]
        r = self._make_result(segs)
        self.assertEqual(r.to_plain_text(), "Unidentified line.")

    def test_blank_line_between_speaker_changes(self):
        segs = [
            TranscriptSegment(0.0, 1.0, "One.", speaker="SPEAKER_00"),
            TranscriptSegment(1.0, 2.0, "Two.", speaker="SPEAKER_00"),
            TranscriptSegment(2.0, 3.0, "Three.", speaker="SPEAKER_01"),
            TranscriptSegment(3.0, 4.0, "Four.", speaker="SPEAKER_00"),
        ]
        r = self._make_result(segs)
        names = {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"}
        out = r.to_plain_text(speaker_names=names)
        expected = (
            "Alice: One.\n"
            "Alice: Two.\n"
            "\n"
            "Bob: Three.\n"
            "\n"
            "Alice: Four."
        )
        self.assertEqual(out, expected)

    def test_no_timestamps_in_output(self):
        segs = [
            TranscriptSegment(0.0, 1.5, "Hello.", speaker="SPEAKER_00"),
            TranscriptSegment(1.5, 3.0, "World.", speaker="SPEAKER_00"),
        ]
        r = self._make_result(segs)
        out = r.to_plain_text(speaker_names={"SPEAKER_00": "Alice"})
        # No digits-colon-digits timestamps and no square brackets
        self.assertNotIn("[", out)
        self.assertNotIn("]", out)
        self.assertNotIn("->", out)

    def test_no_trailing_newline(self):
        segs = [TranscriptSegment(0.0, 1.0, "Hi.", speaker="SPEAKER_00")]
        r = self._make_result(segs)
        out = r.to_plain_text()
        self.assertFalse(out.endswith("\n"))

    def test_text_is_stripped_of_leading_whitespace(self):
        """Whisper often emits leading spaces on segment text."""
        segs = [TranscriptSegment(0.0, 1.0, " Hello.", speaker="SPEAKER_00")]
        r = self._make_result(segs)
        self.assertEqual(r.to_plain_text(), "SPEAKER_00: Hello.")


if __name__ == "__main__":
    unittest.main()
