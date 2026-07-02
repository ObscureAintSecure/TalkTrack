# tests/test_atomic_io.py
import json
import tempfile
import unittest
from pathlib import Path


class TestAtomicWrite(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_text_creates_file(self):
        from app.utils.atomic_io import atomic_write_text
        path = self.dir / "out.txt"
        atomic_write_text(path, "hello")
        self.assertEqual(path.read_text(encoding="utf-8"), "hello")

    def test_write_text_replaces_existing(self):
        from app.utils.atomic_io import atomic_write_text
        path = self.dir / "out.txt"
        path.write_text("old", encoding="utf-8")
        atomic_write_text(path, "new")
        self.assertEqual(path.read_text(encoding="utf-8"), "new")

    def test_no_tmp_file_left_behind(self):
        from app.utils.atomic_io import atomic_write_text
        atomic_write_text(self.dir / "out.txt", "x")
        leftovers = [p.name for p in self.dir.iterdir() if p.suffix == ".tmp"]
        self.assertEqual(leftovers, [])

    def test_write_json_round_trips(self):
        from app.utils.atomic_io import atomic_write_json
        path = self.dir / "out.json"
        data = {"segments": [{"text": "héllo", "start": 1.5}]}
        atomic_write_json(path, data, indent=2, ensure_ascii=False)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), data)


if __name__ == "__main__":
    unittest.main()
