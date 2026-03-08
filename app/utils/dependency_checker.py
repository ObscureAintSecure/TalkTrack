"""Dependency checker for TalkTrack system status panel."""
import shutil
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
        cache_dir = Path.home() / ".cache" / "huggingface" / "hub" / "models--pyannote--speaker-diarization-3.1"
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
