# tests/test_chunk_embeddings.py
"""Per-chunk speaker embeddings must equal pyannote's per-speaker loop.

The suite cannot load torch (c10.dll, see .claude/rules/ways-of-working.md),
so pyannote is not imported. `_pyannote_loop` restates
SpeakerDiarization.get_embeddings from pyannote.audio 4.0, and a numpy
embedding model stands in for WeSpeaker: it pools per-frame features with the
given weights, per speaker when the weights carry a speaker axis, as the real
StatsPool does. A stand-in torch module maps vstack/from_numpy to numpy.
"""
import math
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from app.transcription import chunk_embeddings as ce

FAKE_TORCH = types.SimpleNamespace(vstack=np.vstack, from_numpy=lambda a: a)
SAMPLES = 160
FRAMES = 16


class FakeEmbedding:
    sample_rate = 16000
    dimension = 3

    def __init__(self, min_num_samples=40):
        # 40 of 160 samples -> pyannote needs more than 4 clean frames of 16.
        self.min_num_samples = min_num_samples * self.sample_rate // SAMPLES
        self.calls = []

    def __call__(self, waveforms, masks=None):
        self.calls.append(masks.shape)
        batch = waveforms.shape[0]
        feats = waveforms[:, 0, :].reshape(batch, FRAMES, -1).mean(-1)   # (B, F)

        def pool(w):
            with np.errstate(invalid="ignore", divide="ignore"):
                total = w.sum(-1)
                mean = (feats * w).sum(-1) / total
                square = (feats ** 2 * w).sum(-1) / total
            return np.stack([mean, square, total], -1)

        if masks.ndim == 2:
            return pool(masks)
        return np.stack([pool(masks[:, s]) for s in range(masks.shape[1])], 1)


class FakeSegmentations:
    """SlidingWindowFeature: .data, .sliding_window.duration, iterates (chunk, data[i])."""

    def __init__(self, data):
        self.data = data
        self.sliding_window = types.SimpleNamespace(duration=SAMPLES / FakeEmbedding.sample_rate)

    def __iter__(self):
        for i in range(len(self.data)):
            yield i, self.data[i]


class FakePipeline:
    def __init__(self, batch_size=4, training=False):
        self.embedding_batch_size = batch_size
        self.training = training
        self._embedding = FakeEmbedding()
        self._audio = MagicMock()
        self._audio.crop.side_effect = lambda file, chunk, mode: (file[chunk][None], 16000)

    def get_embeddings(self, *args, **kwargs):
        return "pyannote's own get_embeddings"


def _pyannote_loop(pipe, file, segs, exclude_overlap):
    """SpeakerDiarization.get_embeddings (pyannote.audio 4.0.7), training cache omitted."""
    duration = segs.sliding_window.duration
    num_chunks, num_frames, num_speakers = segs.data.shape
    if exclude_overlap:
        num_samples = duration * pipe._embedding.sample_rate
        min_num_frames = math.ceil(num_frames * pipe._embedding.min_num_samples / num_samples)
        clean_frames = 1.0 * (np.sum(segs.data, axis=2, keepdims=True) < 2)
        clean = segs.data * clean_frames
    else:
        min_num_frames = -1
        clean = segs.data
    pairs = []
    for c, (chunk, masks) in enumerate(segs):
        waveform, _ = pipe._audio.crop(file, chunk, mode="pad")
        masks = np.nan_to_num(masks, nan=0.0).astype(np.float32)
        clean_masks = np.nan_to_num(clean[c], nan=0.0).astype(np.float32)
        for mask, clean_mask in zip(masks.T, clean_masks.T):
            used = clean_mask if np.sum(clean_mask) > min_num_frames else mask
            pairs.append((waveform[None], used[None]))
    out = []
    for i in range(0, len(pairs), pipe.embedding_batch_size):
        batch = pairs[i:i + pipe.embedding_batch_size]
        out.append(pipe._embedding(np.vstack([w for w, _ in batch]),
                                   masks=np.vstack([m for _, m in batch])))
    return np.vstack(out).reshape(num_chunks, num_speakers, -1)


def _meeting(num_chunks=7, seed=0):
    """Audio plus a segmentation with overlap, silence, a short turn and NaN frames."""
    rng = np.random.default_rng(seed)
    file = rng.standard_normal((num_chunks, SAMPLES)).astype(np.float32)
    data = np.zeros((num_chunks, FRAMES, 3), dtype=np.float32)
    data[:, :10, 0] = 1                      # speaker 0 talks...
    data[:, 8:, 1] = 1                       # ...overlapping speaker 1 for 2 frames
    data[2, :, 1] = 0                        # speaker 1 silent in chunk 2
    data[3, 6:9, 2] = 1                      # speaker 2: 3 frames, all overlapped
    data[4, 13:, 2] = 1                      # speaker 2: 3 clean frames (too few)
    data[5, 0:2, :] = np.nan                 # partial stitching
    return file, FakeSegmentations(data)


def _run(pipe, file, segs, exclude_overlap, hook=None):
    with patch.dict(sys.modules, {"torch": FAKE_TORCH}):
        return ce.get_embeddings(pipe, file, segs, exclude_overlap=exclude_overlap, hook=hook)


class TestSameAsPyannote(unittest.TestCase):
    def _assert_same(self, exclude_overlap, batch_size, num_chunks=7):
        file, segs = _meeting(num_chunks)
        expected = _pyannote_loop(FakePipeline(batch_size), file, segs, exclude_overlap)
        got = _run(FakePipeline(batch_size), file, segs, exclude_overlap)
        self.assertEqual(got.shape, expected.shape)
        np.testing.assert_allclose(got, expected, rtol=1e-6, equal_nan=True)

    def test_exclude_overlap(self):
        self._assert_same(exclude_overlap=True, batch_size=4)

    def test_without_exclude_overlap(self):
        self._assert_same(exclude_overlap=False, batch_size=4)

    def test_batch_size_not_dividing_chunks(self):
        for batch_size in (1, 2, 3, 7, 32):
            with self.subTest(batch_size=batch_size):
                self._assert_same(exclude_overlap=True, batch_size=batch_size)

    def test_inactive_speakers_are_pooled_with_zero_weights_as_in_pyannote(self):
        # Not skipped or zero-filled: clustering sees the model's own output
        # for them (NaN from the real StatsPool), whatever filler would differ.
        file, segs = _meeting()
        got = _run(FakePipeline(), file, segs, exclude_overlap=True)
        self.assertTrue(np.isnan(got[2, 1, 0]))
        self.assertEqual(got[2, 1, 2], 0.0)   # total weight


class TestOnePassPerChunk(unittest.TestCase):
    def test_model_runs_once_per_batch_of_chunks(self):
        file, segs = _meeting(num_chunks=10)
        pipe = FakePipeline(batch_size=4)
        _run(pipe, file, segs, exclude_overlap=True)
        self.assertEqual(pipe._embedding.calls, [(4, 3, FRAMES), (4, 3, FRAMES), (2, 3, FRAMES)])

    def test_pyannote_loop_needs_three_times_the_rows(self):
        file, segs = _meeting(num_chunks=10)
        pipe = FakePipeline(batch_size=4)
        _pyannote_loop(pipe, file, segs, exclude_overlap=True)
        self.assertEqual(sum(shape[0] for shape in pipe._embedding.calls), 30)

    def test_hook_reports_every_batch(self):
        file, segs = _meeting(num_chunks=10)
        hook = MagicMock()
        _run(FakePipeline(batch_size=4), file, segs, exclude_overlap=True, hook=hook)
        progress = [(c.args[0], c.kwargs["completed"], c.kwargs["total"]) for c in hook.call_args_list]
        self.assertEqual(progress, [("embeddings", n, 3) for n in range(4)])


class TestSpeakerWeights(unittest.TestCase):
    def test_clean_frames_used_when_enough(self):
        full = np.array([[1, 1], [1, 1], [1, 0]], dtype=np.float32)
        clean = np.array([[1, 0], [1, 0], [1, 0]], dtype=np.float32)
        w = ce.speaker_weights(full, clean, min_num_frames=2)
        np.testing.assert_array_equal(w[0], [1, 1, 1])      # 3 clean > 2: clean
        np.testing.assert_array_equal(w[1], [1, 1, 0])      # 0 clean: full mask

    def test_nan_counts_as_inactive(self):
        full = np.array([[np.nan], [1]], dtype=np.float32)
        w = ce.speaker_weights(full, full, min_num_frames=-1)
        np.testing.assert_array_equal(w, [[0, 1]])
        self.assertEqual(w.dtype, np.float32)


class TestInstall(unittest.TestCase):
    def _wespeaker_pipeline(self):
        pipe = FakePipeline()
        pipe._embedding.model_ = types.SimpleNamespace(
            compute_fbank=lambda w: w,
            resnet=types.SimpleNamespace(forward_frames=lambda f: f,
                                         forward_embedding=lambda f, weights=None: f),
        )
        return pipe

    def test_installs_on_wespeaker_pipeline(self):
        pipe = self._wespeaker_pipeline()
        self.assertTrue(ce.install(pipe))
        self.assertEqual(pipe.get_embeddings.__func__, ce.get_embeddings)

    def test_other_embedding_models_keep_pyannote_loop(self):
        pipe = FakePipeline()
        pipe._embedding.model_ = types.SimpleNamespace(encode_batch=lambda w: w)  # SpeechBrain-like
        self.assertFalse(ce.install(pipe))
        self.assertEqual(pipe.get_embeddings(), "pyannote's own get_embeddings")

    def test_training_uses_pyannote_path(self):
        pipe = self._wespeaker_pipeline()
        pipe.training = True
        ce.install(pipe)
        file, segs = _meeting()
        self.assertEqual(pipe.get_embeddings(file, segs), "pyannote's own get_embeddings")


class TestDiarizerInstallsIt(unittest.TestCase):
    def test_new_pipeline_gets_per_chunk_embeddings(self):
        pa = MagicMock()
        with patch.dict(sys.modules, {"pyannote": MagicMock(audio=pa), "pyannote.audio": pa}):
            import app.transcription.diarizer as dz
            dz._PIPELINE_CACHE.clear()
            with patch("app.transcription.chunk_embeddings.install", autospec=True) as install:
                pipeline, _ = dz._get_pipeline("tok", "cpu")
                dz._get_pipeline("tok", "cpu")
            dz._PIPELINE_CACHE.clear()
        install.assert_called_once_with(pipeline)


if __name__ == "__main__":
    unittest.main()
