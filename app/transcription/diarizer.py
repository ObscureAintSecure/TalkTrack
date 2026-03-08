from dataclasses import dataclass
from PyQt6.QtCore import QThread, pyqtSignal

from app.transcription.transcriber import TranscriptResult, TranscriptSegment


@dataclass
class SpeakerSegment:
    start: float
    end: float
    speaker: str


class DiarizationWorker(QThread):
    """Runs speaker diarization in a background thread using pyannote.audio."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(TranscriptResult)
    error = pyqtSignal(str)

    def __init__(self, audio_path, transcript_result, hf_token="",
                 min_speakers=None, max_speakers=None):
        super().__init__()
        self.audio_path = audio_path
        self.transcript_result = transcript_result
        self.hf_token = hf_token
        self.min_speakers = min_speakers
        self.max_speakers = max_speakers

    def run(self):
        try:
            self.progress.emit("Loading speaker diarization model...")

            from pyannote.audio import Pipeline

            if not self.hf_token:
                self.error.emit(
                    "HuggingFace token required for pyannote.audio. "
                    "Get one at https://huggingface.co/settings/tokens and "
                    "accept the model terms at "
                    "https://huggingface.co/pyannote/speaker-diarization-community-1"
                )
                return

            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-community-1",
                token=self.hf_token,
            )

            self.progress.emit("Loading audio for diarization...")

            # Pre-load audio via soundfile to avoid torchcodec dependency.
            # pyannote 4.0 accepts {"waveform": tensor, "sample_rate": int}.
            import soundfile as sf
            import torch

            audio_data, sample_rate = sf.read(self.audio_path, dtype="float32")
            if audio_data.ndim == 1:
                waveform = torch.from_numpy(audio_data).unsqueeze(0)
            else:
                waveform = torch.from_numpy(audio_data.T)
            audio_input = {"waveform": waveform, "sample_rate": sample_rate}

            self.progress.emit("Running speaker diarization...")

            diarization_params = {}
            if self.min_speakers is not None:
                diarization_params["min_speakers"] = self.min_speakers
            if self.max_speakers is not None:
                diarization_params["max_speakers"] = self.max_speakers

            result = pipeline(audio_input, **diarization_params)

            # pyannote 4.0 returns DiarizeOutput; extract the Annotation
            if hasattr(result, "speaker_diarization"):
                diarization = result.speaker_diarization
            else:
                diarization = result  # fallback for older versions

            # Extract speaker segments
            speaker_segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                speaker_segments.append(SpeakerSegment(
                    start=turn.start,
                    end=turn.end,
                    speaker=speaker,
                ))

            self.progress.emit("Mapping speakers to transcript...")

            # Assign speakers to transcript segments
            result = self._merge_diarization_with_transcript(
                self.transcript_result, speaker_segments
            )

            self.progress.emit("Speaker diarization complete.")
            self.finished.emit(result)

        except ImportError:
            self.error.emit(
                "pyannote.audio is not installed. "
                "Run: pip install pyannote.audio"
            )
        except Exception as e:
            self.error.emit(f"Diarization failed: {e}")

    def _merge_diarization_with_transcript(self, transcript, speaker_segments):
        """Assign speaker labels to transcript segments based on overlap."""
        for seg in transcript.segments:
            best_speaker = "Unknown"
            best_overlap = 0.0

            seg_start = seg.start
            seg_end = seg.end

            for spk_seg in speaker_segments:
                overlap_start = max(seg_start, spk_seg.start)
                overlap_end = min(seg_end, spk_seg.end)
                overlap = max(0, overlap_end - overlap_start)

                if overlap > best_overlap:
                    best_overlap = overlap
                    best_speaker = spk_seg.speaker

            seg.speaker = best_speaker

        return transcript


class SimpleDiarizer:
    """Simple diarization using mic vs system audio channel separation.

    Falls back to this when pyannote is not available.
    Uses the separate mic and system audio tracks to determine
    if the local user or a remote participant is speaking.
    """

    def __init__(self, mic_audio_path, system_audio_path):
        self.mic_audio_path = mic_audio_path
        self.system_audio_path = system_audio_path

    def diarize(self, transcript):
        """Assign 'You' or 'Remote' labels based on audio energy in each channel."""
        import numpy as np
        import soundfile as sf

        mic_data = None
        sys_data = None

        if self.mic_audio_path:
            mic_data, mic_sr = sf.read(self.mic_audio_path)
            if mic_data.ndim > 1:
                mic_data = mic_data.mean(axis=1)

        if self.system_audio_path:
            sys_data, sys_sr = sf.read(self.system_audio_path)
            if sys_data.ndim > 1:
                sys_data = sys_data.mean(axis=1)

        if mic_data is None and sys_data is None:
            return transcript

        sample_rate = mic_sr if mic_data is not None else sys_sr

        for seg in transcript.segments:
            start_sample = int(seg.start * sample_rate)
            end_sample = int(seg.end * sample_rate)

            mic_energy = 0.0
            sys_energy = 0.0

            if mic_data is not None and start_sample < len(mic_data):
                end_s = min(end_sample, len(mic_data))
                chunk = mic_data[start_sample:end_s]
                mic_energy = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) > 0 else 0.0

            if sys_data is not None and start_sample < len(sys_data):
                end_s = min(end_sample, len(sys_data))
                chunk = sys_data[start_sample:end_s]
                sys_energy = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) > 0 else 0.0

            if mic_energy > sys_energy * 1.5:
                seg.speaker = "You"
            elif sys_energy > mic_energy * 1.5:
                seg.speaker = "Remote"
            else:
                seg.speaker = "You" if mic_energy >= sys_energy else "Remote"

        return transcript
