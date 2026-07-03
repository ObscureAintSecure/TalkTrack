"""Tests for the per-recording embedding cache (#33)."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np


class FakeProvider:
    """Deterministic embedder that counts every text it embeds."""

    embed_model_id = "st:fake-model"

    def __init__(self):
        self.embedded_texts = []

    def embed(self, texts):
        self.embedded_texts.extend(texts)
        # Deterministic 4-dim vector derived from the text.
        return [[float(len(t)), float(ord(t[0])), 1.0, 0.5] for t in texts]


class TestCacheRoundTrip(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.rec_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_then_load_returns_vectors(self):
        from app.ai.embedding_cache import save_cache, load_cache, text_hash
        mapping = {
            text_hash("hello"): np.array([1, 2, 3, 4], dtype=np.float32),
            text_hash("world"): np.array([5, 6, 7, 8], dtype=np.float32),
        }
        save_cache(self.rec_dir, "st:fake-model", mapping)
        loaded = load_cache(self.rec_dir, "st:fake-model")
        self.assertEqual(set(loaded), set(mapping))
        np.testing.assert_array_equal(loaded[text_hash("hello")],
                                      mapping[text_hash("hello")])

    def test_model_mismatch_returns_empty(self):
        from app.ai.embedding_cache import save_cache, load_cache, text_hash
        save_cache(self.rec_dir, "st:model-a",
                   {text_hash("x"): np.ones(4, dtype=np.float32)})
        self.assertEqual(load_cache(self.rec_dir, "st:model-b"), {})

    def test_missing_file_returns_empty(self):
        from app.ai.embedding_cache import load_cache
        self.assertEqual(load_cache(self.rec_dir, "st:fake-model"), {})

    def test_corrupt_file_returns_empty(self):
        from app.ai.embedding_cache import load_cache, CACHE_FILENAME
        (self.rec_dir / CACHE_FILENAME).write_bytes(b"not an npz file")
        self.assertEqual(load_cache(self.rec_dir, "st:fake-model"), {})


class TestGetCorpusVectors(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.rec_dir = Path(self._tmp.name)
        self.provider = FakeProvider()

    def tearDown(self):
        self._tmp.cleanup()

    def test_first_call_embeds_all_and_writes_cache(self):
        from app.ai.embedding_cache import get_corpus_vectors, CACHE_FILENAME
        texts = ["alpha", "beta"]
        vecs = get_corpus_vectors(self.rec_dir, texts, self.provider)
        self.assertEqual(vecs.shape, (2, 4))
        self.assertEqual(self.provider.embedded_texts, ["alpha", "beta"])
        self.assertTrue((self.rec_dir / CACHE_FILENAME).exists())

    def test_second_call_embeds_nothing(self):
        from app.ai.embedding_cache import get_corpus_vectors
        texts = ["alpha", "beta"]
        get_corpus_vectors(self.rec_dir, texts, self.provider)
        self.provider.embedded_texts.clear()
        vecs = get_corpus_vectors(self.rec_dir, texts, self.provider)
        self.assertEqual(self.provider.embedded_texts, [])
        self.assertEqual(vecs.shape, (2, 4))

    def test_edited_segment_reembeds_only_the_change(self):
        from app.ai.embedding_cache import get_corpus_vectors
        get_corpus_vectors(self.rec_dir, ["alpha", "beta"], self.provider)
        self.provider.embedded_texts.clear()
        vecs = get_corpus_vectors(self.rec_dir, ["alpha", "beta edited"],
                                  self.provider)
        self.assertEqual(self.provider.embedded_texts, ["beta edited"])
        self.assertEqual(vecs.shape, (2, 4))

    def test_removed_segment_pruned_from_cache(self):
        from app.ai.embedding_cache import (get_corpus_vectors, load_cache,
                                            text_hash)
        get_corpus_vectors(self.rec_dir, ["alpha", "beta"], self.provider)
        get_corpus_vectors(self.rec_dir, ["alpha"], self.provider)
        cached = load_cache(self.rec_dir, self.provider.embed_model_id)
        self.assertIn(text_hash("alpha"), cached)
        self.assertNotIn(text_hash("beta"), cached)

    def test_provider_without_model_id_skips_cache(self):
        from app.ai.embedding_cache import get_corpus_vectors, CACHE_FILENAME

        class Anonymous:
            def embed(self, texts):
                return [[1.0, 2.0] for _ in texts]

        vecs = get_corpus_vectors(self.rec_dir, ["a"], Anonymous())
        self.assertEqual(vecs.shape, (1, 2))
        self.assertFalse((self.rec_dir / CACHE_FILENAME).exists())

    def test_no_rec_dir_skips_cache(self):
        from app.ai.embedding_cache import get_corpus_vectors
        vecs = get_corpus_vectors(None, ["alpha"], self.provider)
        self.assertEqual(vecs.shape, (1, 4))
        self.assertEqual(self.provider.embedded_texts, ["alpha"])

    def test_duplicate_texts_share_one_embedding(self):
        from app.ai.embedding_cache import get_corpus_vectors
        vecs = get_corpus_vectors(self.rec_dir, ["same", "same"], self.provider)
        self.assertEqual(self.provider.embedded_texts, ["same"])
        self.assertEqual(vecs.shape, (2, 4))
        np.testing.assert_array_equal(vecs[0], vecs[1])


class TestSemanticSearchUsesCache(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.recordings_dir = Path(self._tmp.name)
        (self.recordings_dir / "rec1").mkdir()
        self.provider = FakeProvider()
        self.transcripts = {
            "rec1": [
                {"text": "budget talk", "start": 0.0, "speaker": "A"},
                {"text": "revenue is up", "start": 5.0, "speaker": "B"},
            ],
        }

    def tearDown(self):
        self._tmp.cleanup()

    def test_repeat_search_only_embeds_query(self):
        from app.ai.search_index import semantic_search
        semantic_search("budget", self.transcripts, self.provider,
                        recordings_dir=self.recordings_dir)
        self.provider.embedded_texts.clear()
        semantic_search("budget", self.transcripts, self.provider,
                        recordings_dir=self.recordings_dir)
        self.assertEqual(self.provider.embedded_texts, ["budget"])

    def test_without_recordings_dir_still_works(self):
        from app.ai.search_index import semantic_search
        results = semantic_search("budget", self.transcripts, self.provider)
        self.assertIsInstance(results, list)


if __name__ == "__main__":
    unittest.main()
