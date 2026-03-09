"""Dependency checker for TalkTrack system status panel."""
import shutil
import subprocess
from pathlib import Path

from app.utils.audio_devices import get_input_devices, get_wasapi_output_devices
from app.utils.platform_info import is_windows_11, get_windows_build


class DependencyChecker:
    """Checks system dependencies and reports their status."""

    def __init__(self, config=None):
        self.config = config

    def run_all_checks(self):
        """Run all dependency checks and return list of results."""
        return [
            self.check_microphone(),
            self.check_wasapi(),
            self.check_gpu_cuda(),
            self.check_ffmpeg(),
            self.check_whisper_model(),
            self.check_hf_token(),
            self.check_pyannote_models(),
            self.check_windows_version(),
        ]

    def check_microphone(self):
        """Check if any microphone input devices are available."""
        try:
            devices = get_input_devices()
            if devices:
                return {
                    "name": "Microphone",
                    "passed": True,
                    "level": "critical",
                    "message": f"Found {len(devices)} input device(s): {devices[0]['name']}",
                    "action": None,
                }
            else:
                return {
                    "name": "Microphone",
                    "passed": False,
                    "level": "critical",
                    "message": "No microphone input devices found.",
                    "action": "Connect a microphone or headset and restart TalkTrack.",
                }
        except Exception as e:
            return {
                "name": "Microphone",
                "passed": False,
                "level": "critical",
                "message": f"Error checking microphone: {e}",
                "action": "Ensure audio drivers are installed.",
            }

    def check_wasapi(self):
        """Check if WASAPI output devices are available for loopback capture."""
        try:
            devices = get_wasapi_output_devices()
            if devices:
                return {
                    "name": "WASAPI Loopback",
                    "passed": True,
                    "level": "critical",
                    "message": f"Found {len(devices)} WASAPI output device(s).",
                    "action": None,
                }
            else:
                return {
                    "name": "WASAPI Loopback",
                    "passed": False,
                    "level": "critical",
                    "message": "No WASAPI output devices found.",
                    "action": "WASAPI is required for system audio capture on Windows.",
                }
        except Exception as e:
            return {
                "name": "WASAPI Loopback",
                "passed": False,
                "level": "critical",
                "message": f"Error checking WASAPI: {e}",
                "action": "Ensure Windows audio services are running.",
            }

    @staticmethod
    def detect_gpu_cuda():
        """Detect NVIDIA GPU presence and CUDA PyTorch status.

        Returns dict with keys:
            has_nvidia_gpu (bool): True if NVIDIA GPU detected
            gpu_name (str): GPU name or empty string
            torch_has_cuda (bool): True if PyTorch has CUDA support
            cuda_version (str): CUDA version string or empty
        """
        result = {
            "has_nvidia_gpu": False,
            "gpu_name": "",
            "torch_has_cuda": False,
            "cuda_version": "",
        }
        # Check for NVIDIA GPU via torch first (most reliable if available)
        try:
            import torch
            result["torch_has_cuda"] = torch.cuda.is_available()
            if result["torch_has_cuda"]:
                result["has_nvidia_gpu"] = True
                result["gpu_name"] = torch.cuda.get_device_name(0)
                result["cuda_version"] = torch.version.cuda or ""
                return result
            # torch installed but no CUDA — check if GPU exists via subprocess
        except ImportError:
            pass

        # Fallback: detect NVIDIA GPU via nvidia-smi
        try:
            output = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            if output.returncode == 0 and output.stdout.strip():
                result["has_nvidia_gpu"] = True
                result["gpu_name"] = output.stdout.strip().split("\n")[0]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return result

    def check_gpu_cuda(self):
        """Check GPU availability and CUDA PyTorch setup."""
        info = self.detect_gpu_cuda()

        # Check what device the user has configured
        configured_device = "cpu"
        if self.config:
            try:
                configured_device = self.config.get("transcription", "device")
            except (KeyError, TypeError):
                pass

        if info["torch_has_cuda"]:
            return {
                "name": "GPU Acceleration",
                "passed": True,
                "level": "info",
                "message": f"NVIDIA {info['gpu_name']} detected with CUDA {info['cuda_version']}.",
                "action": None,
            }
        elif info["has_nvidia_gpu"]:
            action = (
                f"NVIDIA {info['gpu_name']} detected but PyTorch is CPU-only. "
                "To enable GPU acceleration, run:\n"
                "pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126"
            )
            if configured_device == "cuda":
                action += "\nTranscription will fall back to CPU until this is resolved."
            return {
                "name": "GPU Acceleration",
                "passed": False,
                "level": "warn",
                "message": f"NVIDIA {info['gpu_name']} found but CUDA PyTorch not installed.",
                "action": action,
            }
        else:
            return {
                "name": "GPU Acceleration",
                "passed": True if configured_device == "cpu" else False,
                "level": "info",
                "message": "No NVIDIA GPU detected. Using CPU for transcription.",
                "action": None if configured_device == "cpu" else "Set Compute Device to CPU in Settings.",
            }

    def check_whisper_model(self):
        """Check if the configured Whisper model is cached locally."""
        model_size = "base"
        if self.config:
            try:
                model_size = self.config.get("transcription", "model_size")
            except (KeyError, TypeError):
                pass

        cache_dir = Path.home() / ".cache" / "huggingface" / "hub" / f"models--Systran--faster-whisper-{model_size}"
        if cache_dir.exists():
            return {
                "name": "Whisper Model",
                "passed": True,
                "level": "critical",
                "message": f"Model 'faster-whisper-{model_size}' is cached.",
                "action": None,
            }
        else:
            return {
                "name": "Whisper Model",
                "passed": False,
                "level": "critical",
                "message": f"Model 'faster-whisper-{model_size}' not found in cache.",
                "action": "The model will be downloaded automatically on first transcription.",
            }

    def check_hf_token(self):
        """Check if a HuggingFace token is configured for diarization."""
        hf_token = ""
        if self.config:
            try:
                hf_token = self.config.get("diarization", "hf_token")
            except (KeyError, TypeError):
                pass

        if hf_token:
            return {
                "name": "HuggingFace Token",
                "passed": True,
                "level": "warn",
                "message": "HuggingFace token is configured.",
                "action": None,
            }
        else:
            return {
                "name": "HuggingFace Token",
                "passed": False,
                "level": "warn",
                "message": "No HuggingFace token configured.",
                "action": "Set a token in Settings to enable speaker diarization.",
            }

    def check_pyannote_models(self):
        """Check if pyannote speaker diarization models are cached."""
        cache_dir = Path.home() / ".cache" / "huggingface" / "hub" / "models--pyannote--speaker-diarization-community-1"
        if cache_dir.exists():
            return {
                "name": "Pyannote Models",
                "passed": True,
                "level": "warn",
                "message": "Speaker diarization model is cached.",
                "action": None,
            }
        else:
            return {
                "name": "Pyannote Models",
                "passed": False,
                "level": "warn",
                "message": "Speaker diarization model not found in cache.",
                "action": "Models will be downloaded when diarization is first used (requires HF token).",
            }

    def check_ffmpeg(self):
        """Check if ffmpeg is installed and available on PATH."""
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            return {
                "name": "FFmpeg",
                "passed": True,
                "level": "warn",
                "message": f"FFmpeg found at {ffmpeg_path}.",
                "action": None,
            }
        else:
            return {
                "name": "FFmpeg",
                "passed": False,
                "level": "warn",
                "message": "FFmpeg not found on PATH.",
                "action": "Install FFmpeg for audio format conversion support.",
            }

    def check_windows_version(self):
        """Check Windows version for compatibility."""
        if is_windows_11():
            build = get_windows_build()
            return {
                "name": "Windows Version",
                "passed": True,
                "level": "info",
                "message": f"Windows 11 (Build {build}) - per-process audio capture supported.",
                "action": None,
            }
        else:
            build = get_windows_build()
            if build > 0:
                return {
                    "name": "Windows Version",
                    "passed": False,
                    "level": "info",
                    "message": f"Windows Build {build} - per-process audio capture requires Windows 11.",
                    "action": "System-wide loopback capture will be used instead.",
                }
            else:
                return {
                    "name": "Windows Version",
                    "passed": False,
                    "level": "info",
                    "message": "Not running on Windows.",
                    "action": "TalkTrack is designed for Windows. Some features may not work.",
                }
