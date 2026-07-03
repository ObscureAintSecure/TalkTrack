"""Queued, thread-owned WAV writer for capture streams (#32).

Audio callbacks must never touch disk (PortAudio realtime constraint), so
each output track gets a ChunkWriter: callbacks `put()` chunks into a queue
and a daemon thread appends them to an open soundfile handle. This replaces
the old accumulate-in-RAM-until-stop design that made multi-hour recordings
risk MemoryError at the finish line.

Held start: nothing is written until `release(prepad_frames)` — the caller
(DualAudioCapture) computes the wall-clock alignment pad after the stream is
running, and the pad must land before the first queued chunk.
"""

import logging
import queue
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)


class ChunkWriter:
    """Writes float32 mono chunks to a 16-bit WAV as they arrive."""

    def __init__(self, path, sample_rate, flush_interval=5.0):
        self.path = Path(path)
        self.sample_rate = sample_rate
        self.error = None
        self._queue = queue.Queue()
        self._released = threading.Event()
        self._prepad_frames = 0
        self._discard = False
        self._stopping = False
        self._frames_written = 0
        self._flush_interval = flush_interval
        # PCM_16 matches the sf.write output the rest of the pipeline
        # (transcription, segment player, MP3 conversion) already consumes.
        self._file = sf.SoundFile(
            str(self.path), mode="w", samplerate=sample_rate,
            channels=1, subtype="PCM_16",
        )
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def frames_written(self):
        return self._frames_written

    def put(self, chunk):
        """Queue a chunk for writing. Non-blocking; safe from audio callbacks."""
        if self._stopping or self._discard or self.error is not None:
            return
        self._queue.put(chunk)

    def release(self, prepad_frames=0):
        """Start writing: `prepad_frames` of silence first, then queued chunks."""
        self._prepad_frames = int(prepad_frames)
        self._released.set()

    def stop(self):
        """Drain the queue, close the file. Returns total frames written.

        A writer that never wrote anything (or was never released) deletes
        its file so callers keep the "no data -> no file" contract.
        """
        self._stopping = True
        if not self._released.is_set():
            self._discard = True
            self._released.set()
        self._thread.join(timeout=10.0)
        try:
            self._file.close()
        except Exception:
            logger.exception("Error closing %s", self.path)
        if self._frames_written == 0:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                logger.exception("Could not remove empty track %s", self.path)
        return self._frames_written

    def abort(self):
        """Stop and delete the file regardless of frames written.

        Used when DualAudioCapture.start() fails partway — a discarded
        session must leave no track files (same contract as the old
        in-RAM design, which never saved anything before stop()).
        """
        self._stopping = True
        self._discard = True
        if not self._released.is_set():
            self._released.set()
        self._thread.join(timeout=10.0)
        try:
            self._file.close()
        except Exception:
            logger.exception("Error closing %s during abort", self.path)
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove aborted track %s", self.path)

    def _run(self):
        self._released.wait()
        if self._discard:
            return
        if self._prepad_frames > 0:
            self._write(np.zeros(self._prepad_frames, dtype=np.float32))
        last_flush = time.monotonic()
        while True:
            try:
                chunk = self._queue.get(timeout=0.1)
            except queue.Empty:
                if self._stopping:
                    break
                chunk = None
            if chunk is not None:
                self._write(chunk)
            now = time.monotonic()
            if now - last_flush >= self._flush_interval:
                self._flush()
                last_flush = now

    def _write(self, chunk):
        if self.error is not None:
            return
        try:
            arr = np.asarray(chunk, dtype=np.float32)
            if arr.ndim > 1:
                arr = arr.reshape(-1) if arr.shape[1] == 1 else arr.mean(axis=1)
            self._file.write(arr)
            self._frames_written += len(arr)
        except Exception as e:
            logger.exception("Write failed for %s — dropping further audio", self.path)
            self.error = str(e)

    def _flush(self):
        """Sync data + header so a crashed session leaves a readable WAV."""
        if self.error is not None:
            return
        try:
            self._file.flush()
        except Exception:
            logger.exception("Flush failed for %s", self.path)
