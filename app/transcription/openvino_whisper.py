"""Whisper on an Intel GPU through OpenVINO GenAI (#131).

faster-whisper (CTranslate2) runs on the CPU or an NVIDIA GPU only, so on
Intel laptops the integrated GPU sat idle while the CPU transcribed.
OpenVINO GenAI's ``WhisperPipeline`` runs the same Whisper models there:
on a Core Ultra 7 265U, large-v3-turbo transcribed a 7.4 min pt-BR meeting
in 54 s on the iGPU versus 7.7 min on the CPU, with the same text.

Two things faster-whisper did for us have to be done here:

- **VAD.** ``WhisperPipeline`` has none, and Whisper invents text over
  silence. faster-whisper's own Silero VAD picks the speech, and only speech
  is decoded.
- **Cancellation and progress.** ``generate()`` blocks, and its streamer is
  not available with timestamps on long audio. Speech is decoded in batches
  of up to ``MAX_BATCH_SECONDS``, so the worker can report progress and stop
  between batches.

No Qt here, and faster-whisper and OpenVINO are only imported inside
functions, so the module imports cleanly and is unit-testable with stubs.
"""
import math
import threading
from dataclasses import dataclass, field
from pathlib import Path

SAMPLE_RATE = 16000
OPENVINO_DEVICE = "GPU"
PIP_PACKAGE = "openvino-genai>=2026.1,<2027"

# int8 IR builds published by Intel, one per model size in Settings. They need
# OpenVINO 2026.1+, hence the floor in PIP_PACKAGE.
_MODEL_SIZES = ("tiny", "base", "small", "medium", "large-v3", "large-v3-turbo")

# Upper bound on speech per generate() call. Sets how often progress is
# reported and how long Cancel can take: about 7 s per batch for
# large-v3-turbo on a Core Ultra 7 265U iGPU. Meeting speech rarely pauses for
# the VAD's 2 s, so one region ran 264 s; the VAD splits such regions at a
# short pause to fit (as faster-whisper's batched mode does at 30 s). Total
# time was the same as with 120 s batches, and no phrases were dropped.
MAX_BATCH_SECONDS = 60

# Compiling a model for the GPU takes ~40 s; OpenVINO caches the compiled blob
# here so later loads take seconds.
COMPILE_CACHE_DIR = Path.home() / ".talktrack" / "openvino_cache"

# Loaded pipelines keyed by (model_size, device), resident between
# transcriptions like transcriber._MODEL_CACHE.
_PIPELINE_CACHE = {}
_PIPELINE_CACHE_LOCK = threading.Lock()
_GENERATE_LOCK = threading.Lock()


def model_repo(model_size):
    """HuggingFace repo of the OpenVINO build of a Whisper model size."""
    if model_size not in _MODEL_SIZES:
        raise ValueError(f"No OpenVINO build of Whisper model '{model_size}'")
    return f"OpenVINO/whisper-{model_size}-int8-ov"


def model_cache_dir(model_size):
    """HuggingFace cache directory the model is downloaded into."""
    repo = model_repo(model_size)
    return Path.home() / ".cache" / "huggingface" / "hub" / f"models--{repo.replace('/', '--')}"


def language_token(language):
    """'pt' -> '<|pt|>'; None or blank -> None (auto-detect)."""
    language = (language or "").strip()
    if not language:
        return None
    if language.startswith("<|"):
        return language
    return f"<|{language}|>"


def detect_intel_gpu():
    """Report whether OpenVINO is installed and sees a GPU.

    Returns {"installed": bool, "version": str, "gpu_name": str}; gpu_name is
    empty when no GPU is usable. Never raises.
    """
    try:
        import openvino as ov
    except Exception:
        return {"installed": False, "version": "", "gpu_name": ""}
    # __version__ carries a build suffix: "2026.4.1-22982-e213a14-releases/2026/4"
    version = str(getattr(ov, "__version__", "")).split("-")[0]
    info = {"installed": True, "version": version, "gpu_name": ""}
    try:
        core = ov.Core()
        gpus = [d for d in core.available_devices if d.startswith(OPENVINO_DEVICE)]
        if gpus:
            info["gpu_name"] = str(core.get_property(gpus[0], "FULL_DEVICE_NAME"))
    except Exception:
        pass
    return info


def _model_path(model_size, progress=None):
    from huggingface_hub import snapshot_download
    repo = model_repo(model_size)
    try:
        return snapshot_download(repo, local_files_only=True)
    except Exception:
        if progress:
            progress(f"Downloading {repo} (first use)...")
        return snapshot_download(repo)


def get_pipeline(model_size, progress=None):
    """Return the cached WhisperPipeline for a model size, building it once."""
    key = (model_size, OPENVINO_DEVICE)
    with _PIPELINE_CACHE_LOCK:
        if key not in _PIPELINE_CACHE:
            import openvino_genai
            model_path = _model_path(model_size, progress)
            COMPILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            if progress:
                progress("Preparing the model for the Intel GPU...")
            _PIPELINE_CACHE[key] = openvino_genai.WhisperPipeline(
                str(model_path), OPENVINO_DEVICE, CACHE_DIR=str(COMPILE_CACHE_DIR),
            )
        return _PIPELINE_CACHE[key]


def release_pipeline(model_size):
    """Drop a pipeline that failed, so the next transcription rebuilds it."""
    with _PIPELINE_CACHE_LOCK:
        _PIPELINE_CACHE.pop((model_size, OPENVINO_DEVICE), None)


def speech_regions(audio, max_speech_seconds=MAX_BATCH_SECONDS):
    """[(start_sample, end_sample)] of speech from faster-whisper's Silero VAD.

    Its sequential-mode defaults, except that speech running longer than
    max_speech_seconds is split at the last short pause before the limit.
    """
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    options = VadOptions(max_speech_duration_s=max_speech_seconds)
    return [(ts["start"], ts["end"]) for ts in get_speech_timestamps(audio, options)]


def plan_batches(regions, max_samples):
    """Group consecutive speech regions into batches of at most max_samples.

    A region longer than the limit becomes a batch of its own rather than
    being cut, since a cut could land mid-word.
    """
    batches, current, size = [], [], 0
    for start, end in regions:
        length = end - start
        if current and size + length > max_samples:
            batches.append(current)
            current, size = [], 0
        current.append((start, end))
        size += length
    if current:
        batches.append(current)
    return batches


class TimeMap:
    """Maps times in a batch's concatenated speech back to the recording."""

    def __init__(self, regions):
        self._spans = []  # (start in batch, start in recording, length), seconds
        offset = 0
        for start, end in regions:
            self._spans.append((offset / SAMPLE_RATE, start / SAMPLE_RATE, (end - start) / SAMPLE_RATE))
            offset += end - start
        self.duration = offset / SAMPLE_RATE

    def to_original(self, t, is_end=False):
        """Recording time of batch time t.

        A time exactly on a boundary between two regions is the start of the
        next region, or for an end time, the end of the previous one.
        """
        t = min(max(t, 0.0), self.duration)
        span = self._spans[0]
        for candidate in self._spans[1:]:
            if t > candidate[0] or (not is_end and t == candidate[0]):
                span = candidate
            else:
                break
        batch_start, original_start, length = span
        return original_start + min(t - batch_start, length)


@dataclass
class BatchResult:
    segments: list = field(default_factory=list)  # [(start, end, text)], recording time
    language: str = ""


def decode_batch(pipeline, audio, batch, token):
    """Transcribe one batch of speech regions of `audio`; times are in `audio`'s timeline.

    ``token`` is the language token, or None to detect. Returns a BatchResult
    whose ``language`` is what the model reported (detected or pinned).
    """
    import numpy as np

    time_map = TimeMap(batch)
    speech = np.concatenate([audio[start:end] for start, end in batch])

    # One generate() at a time per pipeline: a recording being transcribed live
    # (#139) and the queue's job can share it.
    with _GENERATE_LOCK:
        config = pipeline.get_generation_config()
        config.task = "transcribe"
        config.return_timestamps = True
        config.language = token
        result = pipeline.generate(speech, config)

    detected = (getattr(result, "language", "") or "").strip("<|>")
    segments = []
    for chunk in result.chunks:
        text = chunk.text.strip()
        if not text:
            continue
        start, end = float(chunk.start_ts), float(chunk.end_ts)
        if not math.isfinite(end) or end < start:
            end = time_map.duration  # final chunk with no closing timestamp
        segments.append(
            (time_map.to_original(start), time_map.to_original(end, is_end=True), text)
        )
    return BatchResult(segments=segments, language=detected)


def transcribe(pipeline, audio, language=None, max_batch_seconds=MAX_BATCH_SECONDS):
    """Transcribe the speech in `audio` (16 kHz float32), yielding one BatchResult per batch.

    With no language given, the first batch detects it and later batches reuse
    it, as faster-whisper detects once per recording.
    """
    token = language_token(language)
    regions = speech_regions(audio, max_speech_seconds=max_batch_seconds)
    for batch in plan_batches(regions, int(max_batch_seconds * SAMPLE_RATE)):
        result = decode_batch(pipeline, audio, batch, token)
        if token is None and result.language:
            token = language_token(result.language)
        yield result
