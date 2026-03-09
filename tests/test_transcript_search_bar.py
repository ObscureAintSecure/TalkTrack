import unittest


class TestSearchLogic(unittest.TestCase):
    def test_find_matches_in_segments(self):
        from app.ui.transcript_search_bar import find_matches
        texts = ["Hello world", "world of code", "nothing here"]
        matches = find_matches("world", texts)
        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0], (0, 6, 11))
        self.assertEqual(matches[1], (1, 0, 5))

    def test_find_matches_case_insensitive(self):
        from app.ui.transcript_search_bar import find_matches
        texts = ["Hello World", "WORLD of code"]
        matches = find_matches("world", texts, case_sensitive=False)
        self.assertEqual(len(matches), 2)

    def test_find_matches_case_sensitive(self):
        from app.ui.transcript_search_bar import find_matches
        texts = ["Hello World", "WORLD of code"]
        matches = find_matches("World", texts, case_sensitive=True)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0][0], 0)

    def test_find_matches_no_results(self):
        from app.ui.transcript_search_bar import find_matches
        texts = ["Hello world"]
        matches = find_matches("xyz", texts)
        self.assertEqual(len(matches), 0)

    def test_find_matches_regex(self):
        from app.ui.transcript_search_bar import find_matches
        texts = ["Hello 123 world", "test 456 end"]
        matches = find_matches(r"\d+", texts, use_regex=True)
        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0], (0, 6, 9))
        self.assertEqual(matches[1], (1, 5, 8))


if __name__ == "__main__":
    unittest.main()
