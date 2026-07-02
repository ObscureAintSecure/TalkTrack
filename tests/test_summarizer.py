import unittest
import json


class TestSummaryPromptBuilder(unittest.TestCase):
    def test_build_summary_prompt(self):
        from app.ai.summarizer import build_summary_prompt
        from app.transcription.transcriber import TranscriptSegment
        segments = [
            TranscriptSegment(0.0, 5.0, "Let's discuss the budget.", speaker="Alice"),
            TranscriptSegment(5.0, 10.0, "I think we need more funding.", speaker="Bob"),
        ]
        prompt = build_summary_prompt(segments, {"Alice": "Alice", "Bob": "Bob"})
        self.assertIn("Alice", prompt)
        self.assertIn("budget", prompt)

    def test_build_summary_prompt_with_notes(self):
        from app.ai.summarizer import build_summary_prompt
        from app.transcription.transcriber import TranscriptSegment
        segments = [
            TranscriptSegment(0.0, 5.0, "Let's discuss the budget.", speaker="Alice"),
        ]
        prompt = build_summary_prompt(segments, {"Alice": "Alice"}, notes="Ask about Q3 numbers")
        self.assertIn("Ask about Q3 numbers", prompt)
        self.assertIn("USER NOTES", prompt)

    def test_build_summary_prompt_without_notes(self):
        from app.ai.summarizer import build_summary_prompt
        from app.transcription.transcriber import TranscriptSegment
        segments = [
            TranscriptSegment(0.0, 5.0, "Hello.", speaker="Alice"),
        ]
        prompt = build_summary_prompt(segments, {"Alice": "Alice"}, notes="")
        self.assertNotIn("USER NOTES", prompt)

    def test_build_action_items_prompt(self):
        from app.ai.summarizer import build_action_items_prompt
        from app.transcription.transcriber import TranscriptSegment
        segments = [
            TranscriptSegment(0.0, 5.0, "Bob, can you send the report by Friday?", speaker="Alice"),
        ]
        prompt = build_action_items_prompt(segments, {"Alice": "Alice", "Bob": "Bob"})
        self.assertIn("action item", prompt.lower())
        self.assertIn("report", prompt)


class TestParseActionItems(unittest.TestCase):
    def test_parse_json_response(self):
        from app.ai.summarizer import parse_action_items
        response = json.dumps([
            {"task": "Send report", "assignee": "Bob", "deadline": "Friday"},
            {"task": "Review budget", "assignee": "Alice", "deadline": ""},
        ])
        items = parse_action_items(response)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["task"], "Send report")

    def test_parse_malformed_response(self):
        from app.ai.summarizer import parse_action_items
        items = parse_action_items("This is not JSON")
        self.assertEqual(items, [])


class TestParseActionItemsHardening(unittest.TestCase):
    def test_prose_wrapped_array_without_fences(self):
        from app.ai.summarizer import parse_action_items
        response = 'Here are the items:\n[{"task": "Send report", "assignee": "Bob", "deadline": ""}]\nLet me know!'
        items = parse_action_items(response)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["task"], "Send report")

    def test_non_dict_entries_filtered(self):
        from app.ai.summarizer import parse_action_items
        response = '[{"task": "A", "assignee": "", "deadline": ""}, "stray string", 42]'
        items = parse_action_items(response)
        self.assertEqual(len(items), 1)

    def test_items_without_task_filtered(self):
        from app.ai.summarizer import parse_action_items
        response = '[{"assignee": "Bob"}, {"task": "Real one"}]'
        items = parse_action_items(response)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["task"], "Real one")

    def test_missing_fields_coerced_to_empty_strings(self):
        from app.ai.summarizer import parse_action_items
        items = parse_action_items('[{"task": "A"}]')
        self.assertEqual(items[0]["assignee"], "")
        self.assertEqual(items[0]["deadline"], "")

    def test_object_response_returns_empty(self):
        from app.ai.summarizer import parse_action_items
        self.assertEqual(parse_action_items('{"task": "not a list"}'), [])


class TestTranscriptTruncation(unittest.TestCase):
    def test_short_text_unchanged(self):
        from app.ai.summarizer import truncate_transcript
        text = "short transcript"
        self.assertEqual(truncate_transcript(text, 1000), text)

    def test_long_text_keeps_head_and_tail(self):
        from app.ai.summarizer import truncate_transcript
        text = "HEAD " + ("x" * 10000) + " TAIL"
        out = truncate_transcript(text, 2000)
        self.assertLessEqual(len(out), 2000)
        self.assertTrue(out.startswith("HEAD"))
        self.assertTrue(out.endswith("TAIL"))
        self.assertIn("truncated", out)

    def test_build_summary_prompt_respects_cap(self):
        from app.ai.summarizer import build_summary_prompt
        from app.transcription.transcriber import TranscriptSegment
        segments = [
            TranscriptSegment(float(i), float(i + 1), "word " * 50, speaker="A")
            for i in range(500)
        ]
        prompt = build_summary_prompt(
            segments, {}, max_transcript_chars=5000
        )
        # Prompt = instructions + capped transcript; generous upper bound.
        self.assertLess(len(prompt), 7000)
        self.assertIn("truncated", prompt)

    def test_build_summary_prompt_uncapped_by_default(self):
        from app.ai.summarizer import build_summary_prompt
        from app.transcription.transcriber import TranscriptSegment
        segments = [
            TranscriptSegment(0.0, 1.0, "hello world", speaker="A"),
        ]
        prompt = build_summary_prompt(segments, {})
        self.assertNotIn("truncated", prompt)


if __name__ == "__main__":
    unittest.main()
