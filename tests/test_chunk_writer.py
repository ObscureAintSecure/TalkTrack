"""Tests for ChunkWriter — queued, thread-owned WAV writer for capture streams."""

import time
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from app.recording.chunk_writer import ChunkWriter


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestChunkWriter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "track.wav"

    def tearDown(self):
        self._tmp.cleanup()

    def _make(self, **kwargs):
        return ChunkWriter(self.path, sample_rate=16000, **kwargs)

    def test_held_until_release_then_writes_queued_chunks(self):
        w = self._make()
        w.put(np.full(160, 0.5, dtype=np.float32))
        w.put(np.full(160, -0.5, dtype=np.float32))
        # Held: nothing hits the file yet.
        time.sleep(0.1)
        self.assertEqual(w.frames_written, 0)
        w.release(prepad_frames=0)
        self.assertTrue(_wait_for(lambda: w.frames_written == 320))
        w.stop()
        data, sr = sf.read(str(self.path), dtype="float32")
        self.assertEqual(sr, 16000)
        self.assertEqual(len(data), 320)
        self.assertAlmostEqual(float(data[:160].max()), 0.5, places=6)

    def test_release_prepad_writes_leading_silence(self):
        w = self._make()
        w.put(np.full(100, 0.25, dtype=np.float32))
        w.release(prepad_frames=400)
        w.stop()
        data, _ = sf.read(str(self.path), dtype="float32")
        self.assertEqual(len(data), 500)
        self.assertEqual(float(np.abs(data[:400]).max()), 0.0)
        self.assertAlmostEqual(float(data[400]), 0.25, places=6)

    def test_stop_drains_pending_queue(self):
        w = self._make()
        w.release(prepad_frames=0)
        for _ in range(50):
            w.put(np.ones(160, dtype=np.float32))
        frames = w.stop()
        self.assertEqual(frames, 50 * 160)
        data, _ = sf.read(str(self.path), dtype="float32")
        self.assertEqual(len(data), 50 * 160)

    def test_zero_frames_deletes_file_and_returns_zero(self):
        w = self._make()
        w.release(prepad_frames=0)
        frames = w.stop()
        self.assertEqual(frames, 0)
        self.assertFalse(self.path.exists())

    def test_stop_before_release_discards_and_deletes(self):
        # Mic start failed — writer was never released. Must not leave a file.
        w = self._make()
        w.put(np.ones(160, dtype=np.float32))
        frames = w.stop()
        self.assertEqual(frames, 0)
        self.assertFalse(self.path.exists())

    def test_write_error_sets_error_and_drops_chunks(self):
        w = self._make()
        w.release(prepad_frames=0)
        w.put(np.ones(160, dtype=np.float32))
        self.assertTrue(_wait_for(lambda: w.frames_written == 160))
        with patch.object(w._file, "write", side_effect=OSError("disk full")):
            w.put(np.ones(160, dtype=np.float32))
            self.assertTrue(_wait_for(lambda: w.error is not None))
        # Subsequent puts are dropped without raising.
        w.put(np.ones(160, dtype=np.float32))
        frames = w.stop()   # must not raise
        self.assertEqual(frames, 160)

    def test_flush_keeps_file_readable_before_close(self):
        # Crash-recovery guarantee: after a flush, a copy of the in-progress
        # file must parse as a valid WAV with the frames so far.
        w = self._make(flush_interval=0.05)
        w.release(prepad_frames=0)
        w.put(np.full(16000, 0.5, dtype=np.float32))
        self.assertTrue(_wait_for(lambda: w.frames_written == 16000))
        time.sleep(0.2)   # let at least one flush pass
        snapshot = self.path.with_name("snapshot.wav")
        snapshot.write_bytes(self.path.read_bytes())
        data, sr = sf.read(str(snapshot), dtype="float32")
        self.assertEqual(sr, 16000)
        self.assertEqual(len(data), 16000)
        w.stop()

    def test_put_after_stop_is_noop(self):
        w = self._make()
        w.release(prepad_frames=0)
        w.put(np.ones(16, dtype=np.float32))
        w.stop()
        w.put(np.ones(16, dtype=np.float32))   # must not raise
        data, _ = sf.read(str(self.path), dtype="float32")
        self.assertEqual(len(data), 16)

    def test_abort_deletes_file_even_with_frames_written(self):
        # Failed DualAudioCapture.start() discards everything — matches the
        # old in-RAM behavior where nothing was ever saved.
        w = self._make()
        w.release(prepad_frames=0)
        w.put(np.ones(160, dtype=np.float32))
        self.assertTrue(_wait_for(lambda: w.frames_written == 160))
        w.abort()
        self.assertFalse(self.path.exists())

    def test_multichannel_chunks_downmixed_to_mono(self):
        # Streams hand over device-shaped chunks; mic device chunks are
        # (frames, 1) — writer flattens to mono.
        w = self._make()
        w.release(prepad_frames=0)
        w.put(np.full((160, 1), 0.5, dtype=np.float32))
        frames = w.stop()
        self.assertEqual(frames, 160)
        data, _ = sf.read(str(self.path), dtype="float32")
        self.assertEqual(data.ndim, 1)


if __name__ == "__main__":
    unittest.main()
