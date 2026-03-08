import json
import os
from pathlib import Path


DEFAULT_CONFIG = {
    "audio": {
        "sample_rate": 16000,
        "channels": 1,
        "mic_device": None,
        "loopback_device": None,
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
    },
    "diarization": {
        "enabled": True,
        "hf_token": "",
        "min_speakers": None,
        "max_speakers": None,
    },
    "ui": {
        "theme": "dark",
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
