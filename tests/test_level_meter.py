# tests/test_level_meter.py
import unittest
import numpy as np


class TestRMSCalculation(unittest.TestCase):
    def test_rms_of_silence(self):
        from app.ui.level_meter import compute_rms_db
        silence = np.zeros(1600, dtype=np.float32)
        db = compute_rms_db(silence)
        self.assertEqual(db, -60.0)  # Floor value

    def test_rms_of_full_scale(self):
        from app.ui.level_meter import compute_rms_db
        full = np.ones(1600, dtype=np.float32)
        db = compute_rms_db(full)
        self.assertAlmostEqual(db, 0.0, places=1)

    def test_rms_of_half_scale(self):
        from app.ui.level_meter import compute_rms_db
        half = np.full(1600, 0.5, dtype=np.float32)
        db = compute_rms_db(half)
        self.assertAlmostEqual(db, -6.0, delta=0.2)

    def test_rms_clamps_to_floor(self):
        from app.ui.level_meter import compute_rms_db
        tiny = np.full(1600, 0.0001, dtype=np.float32)
        db = compute_rms_db(tiny)
        self.assertEqual(db, -60.0)

    def test_db_to_fraction(self):
        from app.ui.level_meter import db_to_fraction
        self.assertAlmostEqual(db_to_fraction(0.0), 1.0)
        self.assertAlmostEqual(db_to_fraction(-60.0), 0.0)
        self.assertAlmostEqual(db_to_fraction(-30.0), 0.5, delta=0.01)


if __name__ == "__main__":
    unittest.main()
