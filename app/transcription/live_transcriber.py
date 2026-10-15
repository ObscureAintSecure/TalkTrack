"""Transcribe a recording while it is being recorded, on the Intel GPU (#139).

Opt-in (``transcription.live``) and only with the ``intel_gpu`` device, which
transcribes several times faster than real time. Without it, a 31-minute
meeting waited 4 minutes after Stop for its transcript; with it, only the
speech since the last finished batch is left.

Nothing here touches audio capture. The worker reads the track files that
``ChunkWriter`` already streams to disk (their WAV headers are refreshed every
few seconds), mixes them the way ``DualAudioCapture.stop`` builds
combined_audio.wav, and transcribes speech once it has settled:

- Only speech regions that ended at least ``SETTLE_SECONDS`` before the end of
  what has been read are taken, so a sentence is never cut at the write head.
- Batches wait until they hold ``MIN_BATCH_SECONDS`` of speech, to give
  Whisper context; at Stop the rest goes regardless.
- The mix is read only as far as every track has data: the final mix aligns
  tracks by sample index, and a track that is behind may still catch up.

At Stop, the worker reads what is left from the final combined file (WAV or
MP3) and emits the same signals as TranscriptionWorker, so MainWindow treats
it as that recording's transcription job. Any failure before that marks the
worker failed, and MainWindow runs the normal transcription instead.
"""
import logging
import threading
from dataclasses import dataclass, field

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from app.transcription import openvino_whisper as ovw
from app.transcription.transcriber import TranscriptResult, TranscriptSegment, _format_time

logger = logging.getLogger(__name__)

SAMPLE_RATE = ovw.SAMPLE_RATE
POLL_SECONDS = 10.0
SETTLE_SECONDS = 3.0          # longer than the VAD's 2 s minimum silence
MIN_BATCH_SECONDS = 30.0
TARGET_PEAK = 0.95            # as combined_audio.wav is normalized


class TrackFollower:
    """Reads the frames appended to a WAV that another handle is still writing."""

    def __init__(self, path):
        self.path = path
        self.position = 0

    def available(self):
        """Frames the header reports beyond what was read; 0 if unreadable now."""
        import soundfile as sf
        try:
            with sf.SoundFile(str(self.path)) as f:
                return max(f.frames - self.position, 0)
        except Exception:
            return 0

    def read(self, frames):
        import soundfile as sf
        with sf.SoundFile(str(self.path)) as f:
            f.seek(self.position)
            data = f.read(frames, dtype="float32", always_2d=True)
        data = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
        self.position += len(data)
        return data


class LiveMixer:
    """Mixes growing mic and system tracks as DualAudioCapture.stop does."""

    def __init__(self, mic_followers, system_follower=None):
        self.mic = list(mic_followers)
        self.system = system_follower

    def read(self):
        """Mixed samples newly available on every track (possibly none)."""
        tracks = self.mic + ([self.system] if self.system else [])
        if not tracks:
            return np.zeros(0, dtype=np.float32)
        frames = min(t.available() for t in tracks)
        if frames <= 0:
            return np.zeros(0, dtype=np.float32)
        mic = None
        for follower in self.mic:
            data = follower.read(frames)
            mic = data if mic is None else mic + data
        system = self.system.read(frames) if self.system else None
        if mic is not None and system is not None:
            return (0.5 * mic + 0.5 * system).astype(np.float32)
        return (mic if mic is not None else system).astype(np.float32)


@dataclass
class LiveState:
    """What has been transcribed so far. Times are seconds into the recording."""
    segments: list = field(default_factory=list)   # [(start, end, text)]
    language: str = ""
    done_until: int = 0                            # samples transcribed (or skipped as silence)


class LiveSession:
    """Incremental transcription over a growing 16 kHz mix (no Qt, testable)."""

    def __init__(self, pipeline, language=None, normalize=True,
                 settle_seconds=SETTLE_SECONDS, min_batch_seconds=MIN_BATCH_SECONDS,
                 max_batch_seconds=ovw.MAX_BATCH_SECONDS):
        self.pipeline = pipeline
        # combined_audio.wav is peak-normalized only when it mixes two tracks;
        # a lone track is copied verbatim, so live audio follows suit.
        self.normalize = normalize
        self.token = ovw.language_token(language)
        self.settle = int(settle_seconds * SAMPLE_RATE)
        self.min_batch = int(min_batch_seconds * SAMPLE_RATE)
        self.max_batch_seconds = max_batch_seconds
        self.state = LiveState(language=language or "")
        self._audio = np.zeros(0, dtype=np.float32)   # samples from state.done_until on
        self._received = 0                             # total samples fed
        self._peak = 0.0

    def feed(self, samples):
        if len(samples):
            self._peak = max(self._peak, float(np.abs(samples).max()))
            self._audio = np.concatenate([self._audio, samples])
            self._received += len(samples)

    def step(self, should_stop=lambda: False):
        """Transcribe the speech that has settled. Returns the new segments."""
        if len(self._audio) < self.settle + self.min_batch:
            return []
        regions = ovw.speech_regions(self._audio, max_speech_seconds=self.max_batch_seconds)
        limit = len(self._audio) - self.settle
        # Drop the silence before the first speech, so a long quiet stretch is
        # not re-scanned by the VAD on every poll.
        leading = min(regions[0][0] if regions else limit, limit)
        if leading > 0:
            self._consume(leading)
            regions = [(s - leading, e - leading) for s, e in regions]
            limit -= leading
        ready = []
        for region in regions:
            if region[1] > limit:
                break
            ready.append(region)
        batches = ovw.plan_batches(ready, int(self.max_batch_seconds * SAMPLE_RATE))
        # Keep a short last batch for later: more speech gives it context.
        while batches and sum(e - s for s, e in batches[-1]) < self.min_batch:
            batches.pop()
        if not batches:
            return []
        scale = TARGET_PEAK / self._peak if self.normalize and self._peak > 0 else 1.0
        return self._decode(batches, batches[-1][-1][1], scale, should_stop)

    def finish(self, tail, should_stop=lambda: False):
        """Transcribe everything left, given the recording from state.done_until on.

        ``tail`` comes from the final combined file, which may have more audio
        than was read live (the last seconds, or a track that was behind). It
        is used as is, already normalized, as the normal transcription would.
        """
        self._audio = np.asarray(tail, dtype=np.float32)
        if not len(self._audio):
            return []
        regions = ovw.speech_regions(self._audio, max_speech_seconds=self.max_batch_seconds)
        batches = ovw.plan_batches(regions, int(self.max_batch_seconds * SAMPLE_RATE))
        return self._decode(batches, len(self._audio), 1.0, should_stop)

    def _decode(self, batches, consumed, scale, should_stop):
        offset = self.state.done_until / SAMPLE_RATE
        audio = self._audio * scale if scale != 1.0 else self._audio
        new = []
        for batch in batches:
            if should_stop():
                # Not consumed: the audio stays for the next step or finish.
                consumed = batch[0][0]
                break
            result = ovw.decode_batch(self.pipeline, audio, batch, self.token)
            if self.token is None and result.language:
                self.token = ovw.language_token(result.language)
                self.state.language = result.language
            new.extend((s + offset, e + offset, text) for s, e, text in result.segments)
        self.state.segments.extend(new)
        self._consume(consumed)
        return new

    def _consume(self, samples):
        self.state.done_until += samples
        self._audio = self._audio[samples:]


class LiveTranscriptionWorker(QThread):
    """Transcribes one recording while it records; finishes it after Stop.

    Lifecycle, all driven by MainWindow from the GUI thread:
    ``start()`` when recording starts; ``stop_reading()`` when Stop begins,
    before the track files are closed and mixed; ``finish(audio_path)`` when
    the recording's transcription job comes up, or ``cancel()``.

    Signals match TranscriptionWorker's, plus ``fallback`` when finishing
    fails and the recording should be transcribed the normal way.
    """

    progress = pyqtSignal(str)
    finished = pyqtSignal(TranscriptResult)
    error = pyqtSignal(str)
    cancelled = pyqtSignal()
    fallback = pyqtSignal(str)

    def __init__(self, mic_paths, system_path, model_size, language=None,
                 poll_seconds=POLL_SECONDS):
        super().__init__()
        self.mic_paths = list(mic_paths)
        self.system_path = system_path
        self.model_size = model_size
        self.language = language
        self.poll_seconds = poll_seconds
        self.failed = None            # why live transcription gave up, if it did
        self._wake = threading.Event()
        self._read_lock = threading.Lock()
        self._state_lock = threading.Lock()   # failed vs finish() requested
        self._reading = True
        self._final_audio_path = None
        self._cancelled = False

    @property
    def usable(self):
        """True while the worker can still deliver this recording's transcript."""
        return self.failed is None and not self._cancelled

    def stop_reading(self):
        """Stop touching the track files. Blocks until a read in progress ends."""
        with self._read_lock:
            self._reading = False
        self._wake.set()

    def finish(self, audio_path):
        """Transcribe what is left from the recording's final audio file.

        Returns False if the worker can no longer do it (it failed or was
        cancelled); the caller then transcribes the recording the normal way.
        """
        with self._state_lock:
            if not self.usable:
                return False
            self._final_audio_path = audio_path
        self.stop_reading()
        return True

    def cancel(self):
        self._cancelled = True
        self.stop_reading()

    def run(self):
        session = self._follow_recording()
        if session is None:
            return
        while self._final_audio_path is None and not self._cancelled:
            self._wake.wait(1.0)
            self._wake.clear()
        if self._cancelled:
            self.cancelled.emit()
            return
        self._finish(session)

    def _follow_recording(self):
        """Transcribe settled speech until Stop. Returns the session, or None if it failed."""
        try:
            pipeline = ovw.get_pipeline(self.model_size)
            mixer = LiveMixer(
                [TrackFollower(p) for p in self.mic_paths],
                TrackFollower(self.system_path) if self.system_path else None,
            )
            session = LiveSession(pipeline, self.language,
                                  normalize=bool(self.mic_paths and self.system_path))
            while True:
                self._wake.wait(self.poll_seconds)
                self._wake.clear()
                with self._read_lock:
                    if not self._reading:
                        break
                    samples = mixer.read()
                session.feed(samples)
                if session.step(should_stop=lambda: not self._reading):
                    logger.info("Live transcription: transcribed up to %s",
                                _format_time(session.state.done_until / SAMPLE_RATE))
            return session
        except Exception as e:
            logger.warning("Live transcription stopped; the recording will be "
                           "transcribed after Stop instead", exc_info=True)
            with self._state_lock:
                self.failed = str(e) or type(e).__name__
                finishing = self._final_audio_path is not None
            if finishing:
                # finish() was already accepted, so MainWindow is waiting on us.
                self.fallback.emit(self.failed)
            return None

    def _finish(self, session):
        try:
            from faster_whisper import decode_audio
            self.progress.emit("Transcribing the end of the recording (Intel GPU)...")
            audio = decode_audio(self._final_audio_path, sampling_rate=SAMPLE_RATE)
            session.finish(audio[session.state.done_until:],
                           should_stop=lambda: self._cancelled)
            if self._cancelled:
                self.cancelled.emit()
                return
            result = TranscriptResult(
                segments=[TranscriptSegment(start=s, end=e, text=t)
                          for s, e, t in session.state.segments],
                language=session.state.language or self.language or "",
                duration=len(audio) / SAMPLE_RATE,
            )
            self.progress.emit("Transcription complete.")
            self.finished.emit(result)
        except Exception as e:
            logger.warning("Live transcription could not finish; transcribing the "
                           "recording again", exc_info=True)
            self.failed = str(e) or type(e).__name__
            self.fallback.emit(self.failed)
