import logging
import threading
from dataclasses import dataclass
from PyQt6.QtCore import QThread, pyqtSignal

from app.transcription.transcriber import TranscriptResult, TranscriptSegment

logger = logging.getLogger(__name__)

# Loaded pyannote pipelines keyed by (HF token, resolved device). from_pretrained
# costs many seconds; the pipeline stays resident between recordings by design.
# A CPU pipeline and a CUDA pipeline are distinct objects, hence the device in the key.
_PIPELINE_CACHE = {}
_PIPELINE_CACHE_LOCK = threading.Lock()


def _resolve_device(device):
    """Map a requested device to one torch can actually use, else 'cpu'.

    pyannote uses fp32, so there is no pre-Volta float16 concern here (unlike
    CTranslate2 in the transcriber). CUDA just needs to be available.
    """
    if device == "cuda":
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            pass
    return "cpu"


def _is_oom(exc):
    """True for a CUDA out-of-memory failure, which is retryable on the CPU.

    Matched by message as well as by type: allocation failures also surface
    from cuDNN/cuBLAS as a plain RuntimeError.
    """
    try:
        import torch
        if isinstance(exc, torch.cuda.OutOfMemoryError):
            return True
    except Exception:
        pass
    return "out of memory" in str(exc).lower()


def _release_cuda_pipeline(hf_token):
    """Evict the cached CUDA pipeline and hand its VRAM back.

    Called after an OOM. Keeping it cached would mean re-trying CUDA, failing
    and falling back on every subsequent recording, while still holding the
    memory that caused the problem.
    """
    with _PIPELINE_CACHE_LOCK:
        _PIPELINE_CACHE.pop((hf_token, "cuda"), None)
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass


def _get_pipeline(hf_token, device="cpu"):
    """Return (pipeline, device_actually_used).

    The caller gets the resolved device back rather than re-deriving it, so a
    CUDA request that fell back to the CPU cannot be reported as running on
    the GPU.
    """
    resolved = _resolve_device(device)
    with _PIPELINE_CACHE_LOCK:
        key = (hf_token, resolved)
        if key in _PIPELINE_CACHE:
            return _PIPELINE_CACHE[key], resolved

        from pyannote.audio import Pipeline
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-community-1",
            token=hf_token,
        )
        if resolved == "cuda":
            import torch
            try:
                pipeline.to(torch.device("cuda"))
            except Exception:
                # Out of VRAM, or any other refusal to move. The pipeline may
                # be half-moved, so put it back and cache it as the CPU one --
                # never hand a partially-moved pipeline out under the CUDA key.
                logger.warning(
                    "Could not move diarization pipeline to CUDA; using CPU",
                    exc_info=True,
                )
                try:
                    pipeline.to(torch.device("cpu"))
                except Exception:
                    pass
                resolved = "cpu"
                key = (hf_token, resolved)

        _PIPELINE_CACHE[key] = pipeline
        return pipeline, resolved


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
                 min_speakers=None, max_speakers=None, device="cpu"):
        super().__init__()
        self.audio_path = audio_path
        self.transcript_result = transcript_result
        self.hf_token = hf_token
        self.min_speakers = min_speakers
        self.max_speakers = max_speakers
        self.device = device

    def run(self):
        try:
            self.progress.emit("Loading speaker diarization model...")

            if not self.hf_token:
                self.error.emit(
                    "HuggingFace token required for pyannote.audio. "
                    "Get one at https://huggingface.co/settings/tokens and "
                    "accept the model terms at "
                    "https://huggingface.co/pyannote/speaker-diarization-community-1"
                )
                return

            pipeline, device_used = _get_pipeline(self.hf_token, self.device)
            if device_used == "cuda":
                self.progress.emit("Running speaker diarization on GPU...")

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

            try:
                result = pipeline(audio_input, **diarization_params)
            except Exception as exc:
                # Only OOM is retryable. Anything else is a real failure and
                # must surface rather than be masked by a silent CPU rerun.
                if device_used != "cuda" or not _is_oom(exc):
                    raise
                logger.warning("Diarization hit CUDA OOM; retrying on CPU")
                self.progress.emit(
                    "GPU out of memory - retrying speaker diarization on CPU..."
                )
                _release_cuda_pipeline(self.hf_token)
                pipeline, device_used = _get_pipeline(self.hf_token, "cpu")
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

        def _window_rms(data, rate, start_s, end_s):
            # Each track is indexed with its OWN sample rate — mic and system
            # can legitimately be recorded at different rates.
            start = int(start_s * rate)
            end = min(int(end_s * rate), len(data))
            if start >= len(data):
                return 0.0
            chunk = data[start:end]
            return float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) > 0 else 0.0

        for seg in transcript.segments:
            mic_energy = 0.0
            sys_energy = 0.0

            if mic_data is not None:
                mic_energy = _window_rms(mic_data, mic_sr, seg.start, seg.end)

            if sys_data is not None:
                sys_energy = _window_rms(sys_data, sys_sr, seg.start, seg.end)

            if mic_energy > sys_energy * 1.5:
                seg.speaker = "You"
            elif sys_energy > mic_energy * 1.5:
                seg.speaker = "Remote"
            else:
                seg.speaker = "You" if mic_energy >= sys_energy else "Remote"

        return transcript


class SimpleDiarizeWorker(QThread):
    """Runs SimpleDiarizer off the GUI thread.

    Reading both full WAVs plus per-segment RMS freezes the UI for seconds
    on long recordings when run inline.
    """

    finished = pyqtSignal(TranscriptResult)
    error = pyqtSignal(str)

    def __init__(self, mic_audio_path, system_audio_path, transcript_result):
        super().__init__()
        self.mic_audio_path = mic_audio_path
        self.system_audio_path = system_audio_path
        self.transcript_result = transcript_result

    def run(self):
        try:
            diarizer = SimpleDiarizer(self.mic_audio_path, self.system_audio_path)
            result = diarizer.diarize(self.transcript_result)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(f"Simple diarization failed: {e}")
