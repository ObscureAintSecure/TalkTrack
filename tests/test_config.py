# tests/test_config.py
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.utils import config as config_module
from app.utils.config import Config, DEFAULT_CONFIG


class ConfigTestCase(unittest.TestCase):
    """Base: point CONFIG_DIR/CONFIG_FILE at a temp dir for each test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self._tmp.name)
        self._patchers = [
            patch.object(config_module, "CONFIG_DIR", tmp_path),
            patch.object(config_module, "CONFIG_FILE", tmp_path / "settings.json"),
        ]
        for p in self._patchers:
            p.start()
        self.config_file = tmp_path / "settings.json"
        self.output_dir = tmp_path / "recordings"

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        self._tmp.cleanup()

    def _write_settings(self, data):
        self.config_file.write_text(json.dumps(data), encoding="utf-8")


class TestCorruptionHandling(ConfigTestCase):
    def test_corrupt_json_falls_back_to_defaults(self):
        self.config_file.write_text('{"audio": {tru', encoding="utf-8")
        cfg = Config()
        self.assertEqual(cfg.get("audio", "sample_rate"),
                         DEFAULT_CONFIG["audio"]["sample_rate"])

    def test_corrupt_json_is_backed_up(self):
        self.config_file.write_text("not json at all", encoding="utf-8")
        Config()
        backups = list(self.config_file.parent.glob("settings.json.bak*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "not json at all")

    def test_empty_file_falls_back_to_defaults(self):
        self.config_file.write_text("", encoding="utf-8")
        cfg = Config()
        self.assertEqual(cfg.get("general", "min_recording_length"),
                         DEFAULT_CONFIG["general"]["min_recording_length"])


class TestAtomicSave(ConfigTestCase):
    def test_save_load_round_trip(self):
        cfg = Config()
        cfg.set("output", "directory", str(self.output_dir))
        cfg.set("transcription", "model_size", "small")
        cfg2 = Config()
        self.assertEqual(cfg2.get("transcription", "model_size"), "small")

    def test_save_leaves_no_temp_file(self):
        cfg = Config()
        cfg.set("output", "directory", str(self.output_dir))
        cfg.save()
        leftovers = [p for p in self.config_file.parent.iterdir()
                     if p.name.startswith("settings") and p.suffix == ".tmp"]
        self.assertEqual(leftovers, [])


class TestDefaultConfigIsolation(ConfigTestCase):
    def test_set_does_not_mutate_default_config(self):
        # Saved file is missing the "ui" section entirely.
        self._write_settings({"output": {"directory": str(self.output_dir)}})
        pristine = copy.deepcopy(DEFAULT_CONFIG)
        cfg = Config()
        cfg.set("ui", "theme", "light")
        self.assertEqual(DEFAULT_CONFIG, pristine)

    def test_partial_config_filled_with_defaults(self):
        self._write_settings({
            "output": {"directory": str(self.output_dir)},
            "transcription": {"model_size": "large-v3"},
        })
        cfg = Config()
        self.assertEqual(cfg.get("transcription", "model_size"), "large-v3")
        # Unspecified keys in the same section keep defaults.
        self.assertEqual(cfg.get("transcription", "device"),
                         DEFAULT_CONFIG["transcription"]["device"])
        # Missing sections fully present.
        self.assertEqual(cfg.get("ui", "theme"), DEFAULT_CONFIG["ui"]["theme"])


class TestOutputDirFallback(ConfigTestCase):
    def test_invalid_output_dir_does_not_crash_load(self):
        self._write_settings({"output": {"directory": "Z:\\no\\such\\drive\\path"}})
        try:
            Config()
        except OSError:
            self.fail("Config() raised OSError for an invalid output directory")


if __name__ == "__main__":
    unittest.main()
