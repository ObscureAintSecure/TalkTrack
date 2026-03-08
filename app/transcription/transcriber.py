import os
from pathlib import Path
from dataclasses import dataclass, field
from PyQt6.QtCore import QObject, pyqtSignal, QThread


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: str = ""
    confidence: float = 0.0
    original_text: str = ""

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

    def __init__(self, audio_path, model_size="base", language=None, device="cpu"):
        super().__init__()
        self.audio_path = audio_path
        self.model_size = model_size
        self.language = language
        self.device = device

    def run(self):
        try:
            self.progress.emit("Loading transcription model...")
            from faster_whisper import WhisperModel

            compute_type = "float16" if self.device == "cuda" else "int8"
            model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=compute_type,
            )

            self.progress.emit("Transcribing audio...")
            segments_gen, info = model.transcribe(
                self.audio_path,
                language=self.language,
                word_timestamps=True,
                vad_filter=True,
            )

            result = TranscriptResult(
                language=info.language,
                duration=info.duration,
            )

            for segment in segments_gen:
                ts = TranscriptSegment(
                    start=segment.start,
                    end=segment.end,
                    text=segment.text.strip(),
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
