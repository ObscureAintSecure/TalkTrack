import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory


class TestTextSearch(unittest.TestCase):
    def test_keyword_search(self):
        from app.ai.search_index import text_search
        transcripts = {
            "rec1": [
                {"text": "Let's discuss the budget", "start": 0.0, "speaker": "Alice"},
                {"text": "Revenue is up", "start": 5.0, "speaker": "Bob"},
            ],
            "rec2": [
                {"text": "Budget meeting tomorrow", "start": 0.0, "speaker": "Carol"},
            ],
        }
        results = text_search("budget", transcripts)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["recording_id"], "rec1")
        self.assertEqual(results[1]["recording_id"], "rec2")

    def test_keyword_search_no_matches(self):
        from app.ai.search_index import text_search
        transcripts = {
            "rec1": [{"text": "Hello world", "start": 0.0, "speaker": ""}],
        }
        results = text_search("budget", transcripts)
        self.assertEqual(len(results), 0)

    def test_keyword_search_case_insensitive(self):
        from app.ai.search_index import text_search
        transcripts = {
            "rec1": [{"text": "BUDGET review", "start": 0.0, "speaker": ""}],
        }
        results = text_search("budget", transcripts)
        self.assertEqual(len(results), 1)


class TestLoadTranscripts(unittest.TestCase):
    def test_load_from_directory(self):
        from app.ai.search_index import load_all_transcripts
        with TemporaryDirectory() as tmpdir:
            rec_dir = Path(tmpdir) / "recording_20260308_120000"
            rec_dir.mkdir()
            transcript = {
                "segments": [
                    {"start": 0.0, "end": 5.0, "text": "Hello", "speaker": "A"}
                ]
            }
            with open(rec_dir / "transcript.json", "w") as f:
                json.dump(transcript, f)
            meta = {"directory": str(rec_dir), "name": "Test Recording"}
            with open(rec_dir / "metadata.json", "w") as f:
                json.dump(meta, f)

            result = load_all_transcripts(Path(tmpdir))
            self.assertIn(rec_dir.name, result)
            self.assertEqual(len(result[rec_dir.name]), 1)


if __name__ == "__main__":
    unittest.main()
