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
            p1, _ = dz._get_pipeline("token-a")
            p2, _ = dz._get_pipeline("token-a")
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
            _, resolved = dz._get_pipeline("tok", device)
        return pipeline, torch_mod, resolved

    def test_cuda_available_moves_pipeline_to_gpu(self):
        pipeline, torch_mod, _ = self._get_pipeline("cuda", cuda_available=True)
        torch_mod.device.assert_called_with("cuda")
        pipeline.to.assert_called_once_with("device:cuda")

    def test_cuda_unavailable_falls_back_to_cpu(self):
        pipeline, _, _ = self._get_pipeline("cuda", cuda_available=False)
        pipeline.to.assert_not_called()

    def test_cpu_device_stays_on_cpu(self):
        pipeline, _, _ = self._get_pipeline("cpu", cuda_available=True)
        pipeline.to.assert_not_called()

    def test_pipeline_cached_per_token_and_device(self):
        pa = MagicMock()
        pa.Pipeline.from_pretrained.side_effect = lambda *a, **k: MagicMock()
        with patch.dict(sys.modules, {"pyannote.audio": pa, "torch": _fake_torch(True)}):
            import app.transcription.diarizer as dz
            dz._PIPELINE_CACHE.clear()
            cuda1, _ = dz._get_pipeline("tok", "cuda")
            cuda2, _ = dz._get_pipeline("tok", "cuda")
            cpu1, _ = dz._get_pipeline("tok", "cpu")
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


def _oom_error():
    return RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")


class TestCudaOomFallback(unittest.TestCase):
    """VRAM is shared with the resident Whisper model, so diarization can find
    the GPU full. Falling back to CPU keeps the speakers; raising loses them
    for a reason the user can do nothing about. (issue #74)"""

    def _modules(self, cuda_available=True):
        pa = MagicMock()
        torch_mod = _fake_torch(cuda_available)
        return {"pyannote.audio": pa, "torch": torch_mod}, pa, torch_mod

    def test_oom_moving_to_gpu_falls_back_to_cpu(self):
        mods, pa, _ = self._modules()
        pipeline = MagicMock()
        pipeline.to.side_effect = _oom_error()
        pa.Pipeline.from_pretrained.return_value = pipeline
        with patch.dict(sys.modules, mods):
            import app.transcription.diarizer as dz
            dz._PIPELINE_CACHE.clear()
            returned, device = dz._get_pipeline("tok", "cuda")
        self.assertEqual(device, "cpu")
        self.assertIs(returned, pipeline)

    def test_failed_gpu_move_is_not_cached_as_cuda(self):
        """A half-moved pipeline must never be handed out as the CUDA one."""
        mods, pa, _ = self._modules()
        pipeline = MagicMock()
        pipeline.to.side_effect = _oom_error()
        pa.Pipeline.from_pretrained.return_value = pipeline
        with patch.dict(sys.modules, mods):
            import app.transcription.diarizer as dz
            dz._PIPELINE_CACHE.clear()
            dz._get_pipeline("tok", "cuda")
            keys = list(dz._PIPELINE_CACHE)
        self.assertNotIn(("tok", "cuda"), keys)
        self.assertIn(("tok", "cpu"), keys)

    def test_successful_gpu_move_reports_cuda(self):
        mods, pa, _ = self._modules()
        pa.Pipeline.from_pretrained.return_value = MagicMock()
        with patch.dict(sys.modules, mods):
            import app.transcription.diarizer as dz
            dz._PIPELINE_CACHE.clear()
            _, device = dz._get_pipeline("tok", "cuda")
        self.assertEqual(device, "cuda")

    def test_is_oom_recognises_cuda_message(self):
        import app.transcription.diarizer as dz
        self.assertTrue(dz._is_oom(_oom_error()))
        self.assertFalse(dz._is_oom(RuntimeError("shape mismatch")))

    def test_release_cuda_pipeline_drops_entry_and_frees_vram(self):
        mods, _, torch_mod = self._modules()
        with patch.dict(sys.modules, mods):
            import app.transcription.diarizer as dz
            dz._PIPELINE_CACHE.clear()
            dz._PIPELINE_CACHE[("tok", "cuda")] = MagicMock()
            dz._PIPELINE_CACHE[("tok", "cpu")] = MagicMock()
            dz._release_cuda_pipeline("tok")
            keys = list(dz._PIPELINE_CACHE)
        self.assertNotIn(("tok", "cuda"), keys)
        self.assertIn(("tok", "cpu"), keys)   # CPU entry is still useful
        torch_mod.cuda.empty_cache.assert_called_once()


class TestWorkerOomRetry(unittest.TestCase):
    """An OOM during inference retries on CPU rather than losing the speakers."""

    def _stub_self(self):
        from app.transcription.transcriber import TranscriptResult, TranscriptSegment
        stub = MagicMock()
        stub.audio_path = "a.wav"
        stub.transcript_result = TranscriptResult(
            language="en", duration=1.0,
            segments=[TranscriptSegment(start=0.0, end=1.0, text="hi")],
        )
        stub.hf_token = "tok"
        stub.min_speakers = None
        stub.max_speakers = None
        stub.device = "cuda"
        return stub

    def _run(self, pipeline_side_effect):
        import numpy as np
        from app.transcription.diarizer import DiarizationWorker

        gpu_pipeline = MagicMock(side_effect=pipeline_side_effect)
        cpu_pipeline = MagicMock(return_value=MagicMock())
        sf_mod = MagicMock()
        sf_mod.read.return_value = (np.zeros(16000, dtype="float32"), 16000)
        torch_mod = _fake_torch(True)

        calls = []

        def fake_get_pipeline(token, device="cpu"):
            calls.append(device)
            if device == "cuda":
                return gpu_pipeline, "cuda"
            return cpu_pipeline, "cpu"

        stub = self._stub_self()
        with patch.dict(sys.modules, {"soundfile": sf_mod, "torch": torch_mod}):
            with patch("app.transcription.diarizer._get_pipeline",
                       side_effect=fake_get_pipeline):
                DiarizationWorker.run(stub)
        return stub, calls, gpu_pipeline, cpu_pipeline

    def test_inference_oom_retries_on_cpu(self):
        stub, calls, gpu, cpu = self._run(_oom_error())
        cpu.assert_called_once()
        stub.error.emit.assert_not_called()
        stub.finished.emit.assert_called_once()
        self.assertEqual(calls, ["cuda", "cpu"])

    def test_non_oom_inference_error_is_not_retried(self):
        """A real bug must surface, not be masked by a silent CPU rerun."""
        stub, calls, gpu, cpu = self._run(RuntimeError("shape mismatch"))
        cpu.assert_not_called()
        stub.error.emit.assert_called_once()
        stub.finished.emit.assert_not_called()
