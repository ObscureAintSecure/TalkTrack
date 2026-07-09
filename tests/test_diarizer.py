# tests/test_diarizer.py
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf

from app.transcription.transcriber import TranscriptResult, TranscriptSegment


class TestSimpleDiarizerSampleRates(unittest.TestCase):
    """Mic and system tracks can have different sample rates; energy windows
    must be computed with each track's own rate."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_wav(self, name, data, rate):
        path = self.dir / name
        sf.write(str(path), data, rate)
        return str(path)

    def test_mismatched_rates_use_per_track_indices(self):
        from app.transcription.diarizer import SimpleDiarizer

        # Mic: 16 kHz, 3s, fully silent.
        mic = np.zeros(16000 * 3, dtype=np.float32)
        mic_path = self._write_wav("mic.wav", mic, 16000)

        # System: 48 kHz, 3s, loud ONLY during t=[1.0, 2.0].
        system = np.zeros(48000 * 3, dtype=np.float32)
        system[48000:96000] = 0.5
        sys_path = self._write_wav("system.wav", system, 48000)

        result = TranscriptResult(
            segments=[TranscriptSegment(start=1.0, end=2.0, text="hello")]
        )
        result = SimpleDiarizer(mic_path, sys_path).diarize(result)

        # System is clearly the active channel in that window. Indexing the
        # 48 kHz track with the mic's 16 kHz rate reads t=[0.33, 0.67]
        # (silence) instead and mislabels this as "You".
        self.assertEqual(result.segments[0].speaker, "Remote")

    def test_matched_rates_still_label_mic_speech(self):
        from app.transcription.diarizer import SimpleDiarizer

        mic = np.zeros(16000 * 3, dtype=np.float32)
        mic[16000:32000] = 0.5
        mic_path = self._write_wav("mic.wav", mic, 16000)
        system = np.zeros(16000 * 3, dtype=np.float32)
        sys_path = self._write_wav("system.wav", system, 16000)

        result = TranscriptResult(
            segments=[TranscriptSegment(start=1.0, end=2.0, text="hello")]
        )
        result = SimpleDiarizer(mic_path, sys_path).diarize(result)
        self.assertEqual(result.segments[0].speaker, "You")


class TestPipelineCache(unittest.TestCase):
    def test_same_token_reuses_pipeline(self):
        mock_pyannote_audio = MagicMock()
        with patch.dict(sys.modules, {
            "pyannote": MagicMock(audio=mock_pyannote_audio),
            "pyannote.audio": mock_pyannote_audio,
        }):
            import app.transcription.diarizer as dz
            dz._PIPELINE_CACHE.clear()
            p1 = dz._get_pipeline("token-a")
            p2 = dz._get_pipeline("token-a")
        self.assertIs(p1, p2)
        self.assertEqual(
            mock_pyannote_audio.Pipeline.from_pretrained.call_count, 1
        )


class TestSimpleDiarizeWorkerExists(unittest.TestCase):
    def test_worker_importable_with_expected_signals(self):
        from app.transcription.diarizer import SimpleDiarizeWorker
        self.assertTrue(hasattr(SimpleDiarizeWorker, "finished"))
        self.assertTrue(hasattr(SimpleDiarizeWorker, "error"))


def _fake_torch(cuda_available):
    t = MagicMock()
    t.cuda.is_available.return_value = cuda_available
    t.device.side_effect = lambda d: f"device:{d}"
    return t


class TestPipelineDeviceSelection(unittest.TestCase):
    """The pyannote pipeline moves to CUDA when available; CPU otherwise."""

    def _get_pipeline(self, device, cuda_available):
        pa = MagicMock()  # mocked pyannote.audio module
        pipeline = MagicMock()
        pa.Pipeline.from_pretrained.return_value = pipeline
        torch_mod = _fake_torch(cuda_available)
        with patch.dict(sys.modules, {"pyannote.audio": pa, "torch": torch_mod}):
            import app.transcription.diarizer as dz
            dz._PIPELINE_CACHE.clear()
            dz._get_pipeline("tok", device)
        return pipeline, torch_mod

    def test_cuda_available_moves_pipeline_to_gpu(self):
        pipeline, torch_mod = self._get_pipeline("cuda", cuda_available=True)
        torch_mod.device.assert_called_with("cuda")
        pipeline.to.assert_called_once_with("device:cuda")

    def test_cuda_unavailable_falls_back_to_cpu(self):
        pipeline, _ = self._get_pipeline("cuda", cuda_available=False)
        pipeline.to.assert_not_called()

    def test_cpu_device_stays_on_cpu(self):
        pipeline, _ = self._get_pipeline("cpu", cuda_available=True)
        pipeline.to.assert_not_called()

    def test_pipeline_cached_per_token_and_device(self):
        pa = MagicMock()
        pa.Pipeline.from_pretrained.side_effect = lambda *a, **k: MagicMock()
        with patch.dict(sys.modules, {"pyannote.audio": pa, "torch": _fake_torch(True)}):
            import app.transcription.diarizer as dz
            dz._PIPELINE_CACHE.clear()
            cuda1 = dz._get_pipeline("tok", "cuda")
            cuda2 = dz._get_pipeline("tok", "cuda")
            cpu1 = dz._get_pipeline("tok", "cpu")
        self.assertIs(cuda1, cuda2)      # same (token, cuda) reused
        self.assertIsNot(cuda1, cpu1)    # different resolved device -> different pipeline
        self.assertEqual(pa.Pipeline.from_pretrained.call_count, 2)


class TestResolveDevice(unittest.TestCase):
    def test_cuda_available(self):
        with patch.dict(sys.modules, {"torch": _fake_torch(True)}):
            import app.transcription.diarizer as dz
            self.assertEqual(dz._resolve_device("cuda"), "cuda")

    def test_cuda_unavailable(self):
        with patch.dict(sys.modules, {"torch": _fake_torch(False)}):
            import app.transcription.diarizer as dz
            self.assertEqual(dz._resolve_device("cuda"), "cpu")

    def test_cpu_passthrough(self):
        import app.transcription.diarizer as dz
        self.assertEqual(dz._resolve_device("cpu"), "cpu")


if __name__ == "__main__":
    unittest.main()
