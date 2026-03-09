import unittest


class TestChatContextBuilder(unittest.TestCase):
    def test_build_context_short_transcript(self):
        from app.ai.chat import build_chat_context
        from app.transcription.transcriber import TranscriptSegment
        segments = [
            TranscriptSegment(0.0, 5.0, "Hello everyone", speaker="Alice"),
            TranscriptSegment(5.0, 10.0, "Hi Alice", speaker="Bob"),
        ]
        context = build_chat_context(segments, {"Alice": "Alice", "Bob": "Bob"})
        self.assertIn("Alice", context)
        self.assertIn("Hello everyone", context)

    def test_build_context_truncates_long_transcript(self):
        from app.ai.chat import build_chat_context, MAX_CONTEXT_CHARS
        from app.transcription.transcriber import TranscriptSegment
        segments = [
            TranscriptSegment(float(i), float(i + 1), f"Segment number {i} " * 20, speaker="A")
            for i in range(200)
        ]
        context = build_chat_context(segments, {})
        self.assertLessEqual(len(context), MAX_CONTEXT_CHARS + 500)

    def test_format_chat_prompt(self):
        from app.ai.chat import format_chat_prompt
        history = [
            {"role": "user", "content": "What was discussed?"},
            {"role": "assistant", "content": "The budget was discussed."},
        ]
        prompt = format_chat_prompt("Who mentioned the deadline?", history)
        self.assertIn("deadline", prompt)


if __name__ == "__main__":
    unittest.main()
