import math
import os
import threading
from pathlib import Path
from dataclasses import dataclass, field, fields
from PyQt6.QtCore import QObject, pyqtSignal, QThread

# Loaded Whisper models keyed by (model_size, device, compute_type).
# Loading costs seconds-to-tens-of-seconds per recording; models stay
# resident between transcriptions by design.
_MODEL_CACHE = {}
_MODEL_CACHE_LOCK = threading.Lock()


def _get_model(model_size, device, compute_type):
    key = (model_size, device, compute_type)
    with _MODEL_CACHE_LOCK:
        if key not in _MODEL_CACHE:
            from faster_whisper import WhisperModel
            _MODEL_CACHE[key] = WhisperModel(
                model_size, device=device, compute_type=compute_type,
            )
        return _MODEL_CACHE[key]


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: str = ""
    confidence: float = 0.0
    original_text: str = ""

    @classmethod
    def from_dict(cls, d):
        """Create a TranscriptSegment from a dict, ignoring unknown keys."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_dict(self):
        d = {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "speaker": self.speaker,
            "confidence": self.confidence,
        }
        if self.original_text:
            d["original_text"] = self.original_text
        return d


@dataclass
class TranscriptResult:
    segments: list = field(default_factory=list)
    language: str = ""
    duration: float = 0.0

    def _display_speaker(self, seg, speaker_names=None):
        """Return the display name for a segment's speaker."""
        if not seg.speaker:
            return ""
        if speaker_names and seg.speaker in speaker_names and speaker_names[seg.speaker]:
            return speaker_names[seg.speaker]
        return seg.speaker

    def to_dict(self, speaker_names=None):
        segments = []
        for s in self.segments:
            d = s.to_dict()
            if speaker_names and s.speaker in speaker_names and speaker_names[s.speaker]:
                d["speaker_name"] = speaker_names[s.speaker]
            segments.append(d)
        return {
            "segments": segments,
            "language": self.language,
            "duration": self.duration,
        }

    def to_text(self, speaker_names=None):
        lines = []
        for seg in self.segments:
            display = self._display_speaker(seg, speaker_names)
            speaker = f"[{display}] " if display else ""
            timestamp = f"[{_format_time(seg.start)} -> {_format_time(seg.end)}]"
            lines.append(f"{timestamp} {speaker}{seg.text}")
        return "\n".join(lines)

    def to_plain_text(self, speaker_names=None):
        """Clipboard-friendly plain text: '{speaker}: {text}' per line, blank line between speaker changes, no timestamps."""
        if not self.segments:
            return ""
        lines = []
        prev_speaker = None
        for seg in self.segments:
            display = self._display_speaker(seg, speaker_names)
            if prev_speaker is not None and seg.speaker != prev_speaker:
                lines.append("")
            text = seg.text.strip()
            if display:
                lines.append(f"{display}: {text}")
            else:
                lines.append(text)
            prev_speaker = seg.speaker
        return "\n".join(lines)

    def to_srt(self, speaker_names=None):
        lines = []
        for i, seg in enumerate(self.segments, 1):
            start_ts = _format_srt_time(seg.start)
            end_ts = _format_srt_time(seg.end)
            display = self._display_speaker(seg, speaker_names)
            speaker = f"[{display}] " if display else ""
            lines.append(f"{i}")
            lines.append(f"{start_ts} --> {end_ts}")
            lines.append(f"{speaker}{seg.text}")
            lines.append("")
        return "\n".join(lines)


def _format_time(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _format_srt_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class TranscriptionWorker(QThread):
    """Runs transcription in a background thread."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(TranscriptResult)
    error = pyqtSignal(str)

    cancelled = pyqtSignal()

    def __init__(self, audio_path, model_size="base", language=None, device="cpu",
                 batch_size=8):
        super().__init__()
        self.audio_path = audio_path
        self.model_size = model_size
        self.language = language
        self.device = device
        # batch_size > 1 uses faster-whisper's BatchedInferencePipeline (VAD-chunked
        # parallel decode, typically several times faster). batch_size == 1 keeps the
        # classic sequential path (which retains condition_on_previous_text).
        self.batch_size = batch_size
        self._cancel_requested = False

    def cancel(self):
        """Request cancellation of the transcription."""
        self._cancel_requested = True

    def run(self):
        try:
            self.progress.emit("Loading transcription model...")

            device = self.device
            if device == "cuda":
                try:
                    import torch
                    if not torch.cuda.is_available():
                        self.progress.emit(
                            "CUDA selected but not available — falling back to CPU. "
                            "Install CUDA PyTorch for GPU acceleration: "
                            "pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126"
                        )
                        device = "cpu"
                except ImportError:
                    self.progress.emit("PyTorch not found — falling back to CPU.")
                    device = "cpu"

            compute_type = "float16" if device == "cuda" else "int8"
            model = _get_model(self.model_size, device, compute_type)

            if self._cancel_requested:
                self.cancelled.emit()
                return

            if self.batch_size and self.batch_size > 1:
                self.progress.emit(f"Transcribing audio (batched, batch size {self.batch_size})...")
                from faster_whisper import BatchedInferencePipeline
                pipeline = BatchedInferencePipeline(model=model)
                segments_gen, info = pipeline.transcribe(
                    self.audio_path,
                    language=self.language,
                    vad_filter=True,
                    batch_size=self.batch_size,
                )
            else:
                self.progress.emit("Transcribing audio...")
                segments_gen, info = model.transcribe(
                    self.audio_path,
                    language=self.language,
                    vad_filter=True,
                )

            result = TranscriptResult(
                language=info.language,
                duration=info.duration,
            )

            for segment in segments_gen:
                if self._cancel_requested:
                    self.cancelled.emit()
                    return
                ts = TranscriptSegment(
                    start=segment.start,
                    end=segment.end,
                    text=segment.text.strip(),
                    confidence=math.exp(segment.avg_logprob),
                )
                result.segments.append(ts)
                self.progress.emit(f"Transcribed: {_format_time(segment.end)}")

            self.progress.emit("Transcription complete.")
            self.finished.emit(result)

        except ImportError:
            self.error.emit(
                "faster-whisper is not installed. "
                "Run: pip install faster-whisper"
            )
        except Exception as e:
            self.error.emit(f"Transcription failed: {e}")
