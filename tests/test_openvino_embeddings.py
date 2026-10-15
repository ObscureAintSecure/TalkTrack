# tests/test_openvino_embeddings.py
"""Speaker embeddings on the Intel GPU (#135), and their CPU fallback.

Neither torch nor OpenVINO can be loaded here (see test_chunk_embeddings),
so both are stubbed: a numpy stand-in for torch, a recording fake for
openvino, and a fake WeSpeaker model whose trunk and pooling are numpy.
"""
import sys
import tempfile
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from app.transcription import chunk_embeddings as ce
from app.transcription import openvino_embeddings as ove

FRAMES, MEL = 6, 4


class FakeTensor(np.ndarray):
    """numpy array with the two torch tensor methods the module calls."""

    def numpy(self):
        return np.asarray(self)

    def detach(self):
        return self

    def cpu(self):
        return self

    def contiguous(self):
        return self


def _tensor(a):
    return np.asarray(a, dtype=np.float32).view(FakeTensor)


FAKE_TORCH = types.SimpleNamespace(
    inference_mode=nullcontext, zeros=lambda *s: _tensor(np.zeros(s)),
    from_numpy=_tensor, vstack=lambda xs: _tensor(np.vstack(xs)),
)


class FakeResnet:
    def state_dict(self):
        return {"conv.weight": _tensor(np.arange(6).reshape(2, 3)), "bn.bias": _tensor([1.0])}

    @staticmethod
    def forward_frames(fbank):
        return _tensor(np.asarray(fbank) * 2)

    @staticmethod
    def forward_embedding(frames, weights=None):
        pooled = np.einsum("bsf,bfm->bsm", np.asarray(weights), np.asarray(frames))
        return None, _tensor(pooled)


class FakeModel:
    resnet = FakeResnet()

    @staticmethod
    def compute_fbank(waveforms):
        w = np.asarray(waveforms)[:, 0, :]
        return _tensor(w.reshape(w.shape[0], FRAMES, MEL))


def _pipeline(batch_size=4):
    p = types.SimpleNamespace(embedding_batch_size=batch_size, training=False)
    p._embedding = types.SimpleNamespace(model_=FakeModel(), sample_rate=FRAMES * MEL)
    p._segmentation = types.SimpleNamespace(
        model=types.SimpleNamespace(specifications=types.SimpleNamespace(duration=1.0)))
    return p


def _fake_openvino(compiled):
    ov = MagicMock()
    ov.Core.return_value.compile_model.return_value = compiled
    return ov


class TestGpuTrunk(unittest.TestCase):
    def _trunk(self, batch_size=4):
        compiled = MagicMock(side_effect=lambda x: [np.asarray(x) * 2])
        return ove.GpuTrunk(compiled, batch_size, FRAMES, MEL), compiled

    def test_short_batch_is_padded_to_compiled_shape(self):
        trunk, compiled = self._trunk()
        fbank = np.ones((3, FRAMES, MEL), dtype=np.float32)
        out = trunk.frames(fbank)
        self.assertEqual(compiled.call_args.args[0].shape, (4, FRAMES, MEL))
        self.assertEqual(out.shape, (3, FRAMES, MEL))
        np.testing.assert_array_equal(out, fbank * 2)

    def test_wrong_shape_raises_instead_of_guessing(self):
        trunk, _ = self._trunk()
        with self.assertRaises(ValueError):
            trunk.frames(np.ones((2, FRAMES + 1, MEL), dtype=np.float32))
        with self.assertRaises(ValueError):
            trunk.frames(np.ones((5, FRAMES, MEL), dtype=np.float32))

    def test_embed_matches_the_cpu_model(self):
        trunk, _ = self._trunk()
        rng = np.random.default_rng(0)
        waveforms = _tensor(rng.standard_normal((3, 1, FRAMES * MEL)))
        weights = _tensor(rng.random((3, 2, FRAMES)))
        model = FakeModel()
        with patch.dict(sys.modules, {"torch": FAKE_TORCH}):
            got = trunk.embed(model, waveforms, weights)
        expected = model.resnet.forward_embedding(
            model.resnet.forward_frames(model.compute_fbank(waveforms)), weights=weights)[1]
        np.testing.assert_allclose(got, expected, rtol=1e-6)


class TestGetTrunk(unittest.TestCase):
    def setUp(self):
        ove.release_trunks()
        self.tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.tmp.name)
        patcher = patch.object(ove, "COMPILE_CACHE_DIR", self.cache_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(ove.release_trunks)

    def _get(self, ov, pipeline=None):
        with patch.dict(sys.modules, {"torch": FAKE_TORCH, "openvino": ov}):
            with patch.object(ove, "_convert", autospec=True) as convert:
                convert.side_effect = lambda resnet, b, f, m, path: path.write_text("ir")
                trunk = ove.get_trunk(pipeline or _pipeline(), progress=self.progress)
        return trunk, convert

    def progress(self, message):
        self.messages.append(message)

    messages = []

    def test_first_use_converts_then_compiles_for_the_gpu(self):
        self.messages = []
        ov = _fake_openvino(compiled=MagicMock())
        trunk, convert = self._get(ov)
        convert.assert_called_once()
        _, batch, frames, mel, path = convert.call_args.args
        self.assertEqual((batch, frames, mel), (4, FRAMES, MEL))
        self.assertEqual(path.parent, self.cache_dir)
        self.assertTrue(any("first use" in m for m in self.messages))
        core = ov.Core.return_value
        core.read_model.return_value.reshape.assert_called_once_with([4, FRAMES, MEL])
        device, config = core.compile_model.call_args.args[1:]
        self.assertEqual(device, "GPU")
        self.assertEqual(config, {"CACHE_DIR": str(self.cache_dir)})
        self.assertIsInstance(trunk, ove.GpuTrunk)

    def test_saved_model_is_reused_without_converting(self):
        self.messages = []
        with patch.dict(sys.modules, {"torch": FAKE_TORCH}):
            key = ove.weights_key(FakeResnet())
        (self.cache_dir / f"wespeaker-trunk-{key}.xml").write_text("ir")
        _, convert = self._get(_fake_openvino(MagicMock()))
        convert.assert_not_called()
        self.assertEqual(self.messages, [])

    def test_compiled_trunk_is_cached_until_released(self):
        ov = _fake_openvino(MagicMock())
        first, _ = self._get(ov)
        second, _ = self._get(ov)
        self.assertIs(first, second)
        ove.release_trunks()
        third, _ = self._get(ov)
        self.assertIsNot(first, third)

    def test_weights_key_tracks_the_weights(self):
        with patch.dict(sys.modules, {"torch": FAKE_TORCH}):
            a = ove.weights_key(FakeResnet())
            other = FakeResnet()
            other.state_dict = lambda: {"conv.weight": _tensor(np.zeros((2, 3))),
                                        "bn.bias": _tensor([1.0])}
            b = ove.weights_key(other)
        self.assertEqual(len(a), 16)
        self.assertNotEqual(a, b)

    def test_missing_openvino_raises(self):
        with patch.dict(sys.modules, {"torch": FAKE_TORCH, "openvino": None}):
            with self.assertRaises(ImportError):
                ove.get_trunk(_pipeline())


class TestChunkEmbeddingsAccelerator(unittest.TestCase):
    def _pipe(self):
        pipe = types.SimpleNamespace(_chunk_accelerator=None)
        pipe._embedding = MagicMock(return_value="cpu result")
        pipe._embedding.model_ = "model"
        return pipe

    def test_accelerator_does_the_pass(self):
        pipe = self._pipe()
        accelerator = MagicMock()
        accelerator.embed.return_value = "gpu result"
        ce.set_accelerator(pipe, accelerator)
        self.assertEqual(ce._embed(pipe, "w", "m"), "gpu result")
        accelerator.embed.assert_called_once_with("model", "w", "m")
        pipe._embedding.assert_not_called()

    def test_failure_falls_back_to_the_cpu_for_the_rest_of_the_run(self):
        pipe = self._pipe()
        accelerator = types.SimpleNamespace(error=None, embed=MagicMock(side_effect=RuntimeError("DEVICE_LOST")))
        ce.set_accelerator(pipe, accelerator)
        with self.assertLogs("app.transcription.chunk_embeddings", "WARNING"):
            self.assertEqual(ce._embed(pipe, "w", "m"), "cpu result")
        self.assertEqual(ce._embed(pipe, "w", "m"), "cpu result")
        accelerator.embed.assert_called_once()
        self.assertIsInstance(accelerator.error, RuntimeError)
        self.assertIsNone(pipe._chunk_accelerator)

    def test_cleared_accelerator_uses_the_model(self):
        pipe = self._pipe()
        ce.set_accelerator(pipe, MagicMock())
        ce.set_accelerator(pipe, None)
        self.assertEqual(ce._embed(pipe, "w", "m"), "cpu result")
        pipe._embedding.assert_called_once_with("w", masks="m")


class TestDiarizationWorkerIntelGpu(unittest.TestCase):
    def _stub(self):
        stub = MagicMock()
        stub.progress.emit = MagicMock()
        return stub

    def test_trunk_built_for_supported_pipeline(self):
        from app.transcription.diarizer import DiarizationWorker
        stub = self._stub()
        with patch("app.transcription.chunk_embeddings.supports", return_value=True), \
                patch("app.transcription.openvino_embeddings.get_trunk") as get_trunk:
            trunk = DiarizationWorker._intel_gpu_trunk(stub, "pipeline")
        self.assertIs(trunk, get_trunk.return_value)
        get_trunk.assert_called_once_with("pipeline", progress=stub.progress.emit)

    def test_unavailable_gpu_keeps_the_cpu_and_says_so(self):
        from app.transcription.diarizer import DiarizationWorker
        stub = self._stub()
        with patch("app.transcription.chunk_embeddings.supports", return_value=True), \
                patch("app.transcription.openvino_embeddings.get_trunk",
                      side_effect=RuntimeError("no GPU")):
            with self.assertLogs("app.transcription.diarizer", "WARNING"):
                trunk = DiarizationWorker._intel_gpu_trunk(stub, "pipeline")
        self.assertIsNone(trunk)
        self.assertIn("no GPU", stub.progress.emit.call_args.args[0])

    def test_unsupported_embedding_model_stays_on_cpu(self):
        from app.transcription.diarizer import DiarizationWorker
        with patch("app.transcription.chunk_embeddings.supports", return_value=False), \
                patch("app.transcription.openvino_embeddings.get_trunk") as get_trunk:
            self.assertIsNone(DiarizationWorker._intel_gpu_trunk(self._stub(), "pipeline"))
        get_trunk.assert_not_called()


class TestDiarizationWorkerRun(unittest.TestCase):
    """run() sets the accelerator per run: the CPU pipeline is shared by both settings."""

    def _run(self, device, trunk):
        from app.transcription import diarizer as dz
        from app.transcription.transcriber import TranscriptResult
        stub = MagicMock()
        stub.hf_token, stub.device = "tok", device
        stub.min_speakers = stub.max_speakers = None
        stub.audio_path = "a.wav"
        stub.transcript_result = TranscriptResult()
        stub._intel_gpu_trunk.return_value = trunk
        pipeline = MagicMock()
        sf_mod = MagicMock()
        sf_mod.read.return_value = (np.zeros(16000, dtype=np.float32), 16000)
        torch_mod = MagicMock()
        with patch.dict(sys.modules, {"soundfile": sf_mod, "torch": torch_mod}), \
                patch.object(dz, "_get_pipeline", return_value=(pipeline, "cpu")), \
                patch("app.transcription.chunk_embeddings.set_accelerator") as set_acc, \
                patch("app.transcription.openvino_embeddings.release_trunks") as release:
            dz.DiarizationWorker.run(stub)
        return stub, pipeline, set_acc, release

    def test_intel_gpu_setting_attaches_the_trunk(self):
        trunk = types.SimpleNamespace(error=None)
        stub, pipeline, set_acc, release = self._run("intel_gpu", trunk)
        set_acc.assert_called_once_with(pipeline, trunk)
        release.assert_not_called()
        stub.error.emit.assert_not_called()

    def test_cpu_setting_clears_it(self):
        stub, pipeline, set_acc, _ = self._run("cpu", trunk="unused")
        stub._intel_gpu_trunk.assert_not_called()
        set_acc.assert_called_once_with(pipeline, None)

    def test_mid_run_gpu_failure_is_reported_and_evicted(self):
        trunk = types.SimpleNamespace(error=RuntimeError("DEVICE_LOST"))
        stub, _, _, release = self._run("intel_gpu", trunk)
        release.assert_called_once()
        messages = [c.args[0] for c in stub.progress.emit.call_args_list]
        self.assertTrue(any("finished on the CPU" in m for m in messages))
        stub.finished.emit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
