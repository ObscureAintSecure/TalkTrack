import json
import os
from pathlib import Path


DEFAULT_CONFIG = {
    "audio": {
        "sample_rate": 16000,
        "channels": 1,
        "mic_device": None,
        "loopback_device": None,
        "last_mic": "",
        "last_mic2": "",
        "capture_mode": "legacy",
        "selected_apps": [],
        "hidden_devices": [],
        "mic_count": 1,
        "mic_mute_on_start": False,
        "mic_gain": 1.0,
    },
    "output": {
        "directory": str(Path(__file__).parent.parent.parent / "recordings"),
        "format": "wav",
        "filename_template": "recording_{timestamp}",
    },
    "transcription": {
        "model_size": "base",
        "language": None,
        "device": "cpu",
        "min_duration": 10,
    },
    "diarization": {
        "enabled": True,
        "hf_token": "",
        "min_speakers": None,
        "max_speakers": None,
    },
    "ai": {
        "provider": "none",
        "api_key": "",
        "model": "",
        "local_model_path": "",
        "embed_model": "all-MiniLM-L6-v2",
        "auto_summarize": True,
        "provider_settings": {},
    },
    "general": {
        "min_recording_length": 5,
        "auto_record": False,
        "auto_record_threshold": 5,
        "auto_transcribe": True,
        "silence_auto_stop": True,
        "silence_duration": 120,
        "minimize_to_tray": False,
        "show_tray_hint": True,
        "start_menu_offer_done": False,
    },
    "ui": {
        "theme": "dark",
        "speakers_collapsed": False,
    },
}

CONFIG_DIR = Path.home() / ".talktrack"
CONFIG_FILE = CONFIG_DIR / "settings.json"


class Config:
    def __init__(self):
        self._data = {}
        self.load()

    def load(self):
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
            self._data = self._deep_merge(DEFAULT_CONFIG, saved)
        else:
            self._data = json.loads(json.dumps(DEFAULT_CONFIG))
        os.makedirs(self._data["output"]["directory"], exist_ok=True)

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(self._data, f, indent=2)

    def get(self, *keys):
        value = self._data
        for key in keys:
            value = value[key]
        return value

    def set(self, *keys_and_value):
        keys = keys_and_value[:-1]
        value = keys_and_value[-1]
        d = self._data
        for key in keys[:-1]:
            d = d[key]
        d[keys[-1]] = value
        self.save()

    @property
    def data(self):
        return self._data

    def _deep_merge(self, base, override):
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result
