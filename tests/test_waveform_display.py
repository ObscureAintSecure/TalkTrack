# tests/test_waveform_display.py
import unittest
import numpy as np


class TestWaveformBuffer(unittest.TestCase):
    def test_ring_buffer_append(self):
        from app.ui.waveform_display import WaveformRingBuffer
        buf = WaveformRingBuffer(max_samples=100)
        chunk = np.ones(50, dtype=np.float32) * 0.5
        buf.append(chunk)
        data = buf.get_data()
        self.assertEqual(len(data), 50)
        self.assertAlmostEqual(data[-1], 0.5)

    def test_ring_buffer_wraps(self):
        from app.ui.waveform_display import WaveformRingBuffer
        buf = WaveformRingBuffer(max_samples=100)
        chunk = np.arange(150, dtype=np.float32)
        buf.append(chunk)
        data = buf.get_data()
        self.assertEqual(len(data), 100)
        self.assertAlmostEqual(data[-1], 149.0)
        self.assertAlmostEqual(data[0], 50.0)

    def test_ring_buffer_multiple_appends(self):
        from app.ui.waveform_display import WaveformRingBuffer
        buf = WaveformRingBuffer(max_samples=100)
        for i in range(5):
            chunk = np.full(30, float(i), dtype=np.float32)
            buf.append(chunk)
        data = buf.get_data()
        self.assertEqual(len(data), 100)
        self.assertAlmostEqual(data[-1], 4.0)

    def test_ring_buffer_clear(self):
        from app.ui.waveform_display import WaveformRingBuffer
        buf = WaveformRingBuffer(max_samples=100)
        buf.append(np.ones(50, dtype=np.float32))
        buf.clear()
        data = buf.get_data()
        self.assertEqual(len(data), 0)

    def test_downsample_for_display(self):
        from app.ui.waveform_display import downsample_for_display
        data = np.random.randn(1000).astype(np.float32)
        result = downsample_for_display(data, target_points=100)
        self.assertEqual(len(result), 100)


if __name__ == "__main__":
    unittest.main()
