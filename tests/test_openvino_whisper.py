"""Tests for the Intel GPU (OpenVINO GenAI) Whisper backend.

openvino, openvino_genai, huggingface_hub and faster_whisper.vad are all
stubbed: CI has no Intel GPU, and anything reaching torch must stay mocked
(see ways-of-working.md).
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from app.transcription import openvino_whisper as ovw

SR = ovw.SAMPLE_RATE


def _chunk(start, end, text):
    return SimpleNamespace(start_ts=start, end_ts=end, text=text)


class _FakePipeline:
    """WhisperPipeline stand-in: one canned result per generate() call."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = []  # (audio length in seconds, language passed)

    def get_generation_config(self):
        return SimpleNamespace(language=None, task=None, return_timestamps=False)

    def generate(self, audio, config):
        self.calls.append((len(audio) / SR, config.language))
        assert config.task == "transcribe"
        assert config.return_timestamps is True
        chunks, language = self._results.pop(0)
        return SimpleNamespace(chunks=chunks, language=language)


def _vad_module(regions_s):
    """faster_whisper.vad stub returning speech regions given in seconds."""
    vad = MagicMock()
    vad.get_speech_timestamps.return_value = [
        {"start": int(s * SR), "end": int(e * SR)} for s, e in regions_s
    ]
    return vad


class TestModelRepo(unittest.TestCase):
    def test_every_settings_model_size_has_an_openvino_build(self):
        for size in ("tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"):
            self.assertEqual(ovw.model_repo(size), f"OpenVINO/whisper-{size}-int8-ov")

    def test_unknown_model_size_raises(self):
        with self.assertRaises(ValueError):
            ovw.model_repo("large-v2-distil")

    def test_cache_dir_follows_the_huggingface_layout(self):
        self.assertEqual(
            ovw.model_cache_dir("small").name, "models--OpenVINO--whisper-small-int8-ov"
        )


class TestPlanBatches(unittest.TestCase):
    def test_regions_grouped_up_to_the_limit(self):
        regions = [(0, 40), (50, 90), (100, 140), (150, 160)]
        self.assertEqual(
            ovw.plan_batches(regions, max_samples=100),
            [[(0, 40), (50, 90)], [(100, 140), (150, 160)]],
        )

    def test_region_longer_than_the_limit_is_kept_whole(self):
        self.assertEqual(
            ovw.plan_batches([(0, 10), (20, 500), (510, 520)], max_samples=100),
            [[(0, 10)], [(20, 500)], [(510, 520)]],
        )

    def test_no_speech_means_no_batches(self):
        self.assertEqual(ovw.plan_batches([], max_samples=100), [])


class TestTimeMap(unittest.TestCase):
    def setUp(self):
        # Speech at 10-15 s and 30-40 s of the recording, concatenated to 15 s.
        self.tm = ovw.TimeMap([(10 * SR, 15 * SR), (30 * SR, 40 * SR)])

    def test_duration_is_the_concatenated_length(self):
        self.assertAlmostEqual(self.tm.duration, 15.0)

    def test_times_map_into_their_region(self):
        self.assertAlmostEqual(self.tm.to_original(2.0), 12.0)
        self.assertAlmostEqual(self.tm.to_original(7.0), 32.0)

    def test_boundary_start_belongs_to_the_next_region(self):
        self.assertAlmostEqual(self.tm.to_original(5.0), 30.0)

    def test_boundary_end_belongs_to_the_previous_region(self):
        self.assertAlmostEqual(self.tm.to_original(5.0, is_end=True), 15.0)

    def test_out_of_range_times_are_clamped(self):
        self.assertAlmostEqual(self.tm.to_original(-1.0), 10.0)
        self.assertAlmostEqual(self.tm.to_original(99.0, is_end=True), 40.0)


class TestTranscribe(unittest.TestCase):
    def _run(self, regions_s, results, language=None, max_batch_seconds=120,
             audio_seconds=60):
        audio = np.zeros(audio_seconds * SR, dtype=np.float32)
        pipeline = _FakePipeline(results)
        vad = _vad_module(regions_s)
        with patch.dict(sys.modules, {"faster_whisper": MagicMock(vad=vad),
                                      "faster_whisper.vad": vad}):
            batches = list(ovw.transcribe(
                pipeline, audio, language=language, max_batch_seconds=max_batch_seconds,
            ))
        return batches, pipeline

    def test_segment_times_are_mapped_back_to_the_recording(self):
        batches, pipeline = self._run(
            [(10, 15), (30, 40)],
            [([_chunk(0.5, 4.0, " Oi."), _chunk(5.0, 9.0, " Tudo bem?")], "pt")],
        )
        self.assertEqual(pipeline.calls[0][0], 15.0)  # only speech is decoded
        self.assertEqual(
            batches[0].segments, [(10.5, 14.0, "Oi."), (30.0, 34.0, "Tudo bem?")]
        )

    def test_long_speech_is_split_by_the_vad_at_the_batch_limit(self):
        vad = _vad_module([(0, 10)])
        audio = np.zeros(20 * SR, dtype=np.float32)
        with patch.dict(sys.modules, {"faster_whisper": MagicMock(vad=vad),
                                      "faster_whisper.vad": vad}):
            list(ovw.transcribe(_FakePipeline([([], "pt")]), audio, max_batch_seconds=45))
        vad.VadOptions.assert_called_once_with(max_speech_duration_s=45)

    def test_one_generate_call_per_batch(self):
        batches, pipeline = self._run(
            [(0, 10), (20, 30)],
            [([_chunk(0, 2, "a")], "pt"), ([_chunk(0, 2, "b")], "pt")],
            max_batch_seconds=15,
        )
        self.assertEqual(len(pipeline.calls), 2)
        self.assertEqual([b.segments[0][:2] for b in batches], [(0.0, 2.0), (20.0, 22.0)])

    def test_empty_text_chunks_are_dropped(self):
        batches, _ = self._run([(0, 10)], [([_chunk(0, 1, "  "), _chunk(1, 2, "ok")], "pt")])
        self.assertEqual(batches[0].segments, [(1.0, 2.0, "ok")])

    def test_open_ended_chunk_ends_at_the_end_of_its_batch(self):
        batches, _ = self._run([(0, 10)], [([_chunk(8.0, -1.0, "fim")], "pt")])
        self.assertEqual(batches[0].segments, [(8.0, 10.0, "fim")])

    def test_given_language_is_passed_to_every_batch(self):
        _, pipeline = self._run(
            [(0, 10), (20, 30)], [([], "pt"), ([], "pt")],
            language="pt", max_batch_seconds=15,
        )
        self.assertEqual([c[1] for c in pipeline.calls], ["<|pt|>", "<|pt|>"])

    def test_auto_detected_language_is_kept_for_later_batches(self):
        # faster-whisper detects once per recording; batches must not flip language.
        batches, pipeline = self._run(
            [(0, 10), (20, 30)], [([], "pt"), ([], "es")], max_batch_seconds=15,
        )
        self.assertEqual([c[1] for c in pipeline.calls], [None, "<|pt|>"])
        self.assertEqual(batches[0].language, "pt")

    def test_no_speech_means_no_generate_call(self):
        batches, pipeline = self._run([], [])
        self.assertEqual(batches, [])
        self.assertEqual(pipeline.calls, [])


class TestDecodeBatch(unittest.TestCase):
    """The live worker (#139) and the queue's job can share one pipeline."""

    def test_generate_runs_under_the_shared_lock(self):
        pipeline = _FakePipeline([([_chunk(0, 1, "oi")], "pt")])
        held = []
        original = pipeline.generate
        pipeline.generate = lambda audio, config: (held.append(ovw._GENERATE_LOCK.locked()),
                                                   original(audio, config))[1]
        audio = np.zeros(5 * SR, dtype=np.float32)
        result = ovw.decode_batch(pipeline, audio, [(SR, 3 * SR)], "<|pt|>")
        self.assertEqual(held, [True])
        self.assertFalse(ovw._GENERATE_LOCK.locked())
        self.assertEqual(result.segments, [(1.0, 2.0, "oi")])
        self.assertEqual(pipeline.calls, [(2.0, "<|pt|>")])


class TestLanguageToken(unittest.TestCase):
    def test_plain_code_is_wrapped(self):
        self.assertEqual(ovw.language_token("pt"), "<|pt|>")

    def test_token_is_kept(self):
        self.assertEqual(ovw.language_token("<|en|>"), "<|en|>")

    def test_empty_means_auto_detect(self):
        self.assertIsNone(ovw.language_token(None))
        self.assertIsNone(ovw.language_token("  "))


def _openvino_module(devices, name="Intel(R) Graphics", version="2026.4.1"):
    ov = MagicMock(__version__=version)
    core = ov.Core.return_value
    core.available_devices = devices
    core.get_property.return_value = name
    return ov


class TestDetectIntelGpu(unittest.TestCase):
    def test_gpu_found(self):
        with patch.dict(sys.modules, {"openvino": _openvino_module(["CPU", "GPU", "NPU"])}):
            info = ovw.detect_intel_gpu()
        self.assertEqual(
            info, {"installed": True, "version": "2026.4.1", "gpu_name": "Intel(R) Graphics"}
        )

    def test_version_build_suffix_is_dropped(self):
        ov = _openvino_module(["GPU"], version="2026.4.1-22982-e213a147257-releases/2026/4")
        with patch.dict(sys.modules, {"openvino": ov}):
            self.assertEqual(ovw.detect_intel_gpu()["version"], "2026.4.1")

    def test_installed_without_gpu(self):
        with patch.dict(sys.modules, {"openvino": _openvino_module(["CPU"])}):
            info = ovw.detect_intel_gpu()
        self.assertTrue(info["installed"])
        self.assertEqual(info["gpu_name"], "")

    def test_not_installed(self):
        with patch.dict(sys.modules, {"openvino": None}):
            info = ovw.detect_intel_gpu()
        self.assertFalse(info["installed"])

    def test_device_query_failure_reports_no_gpu(self):
        ov = _openvino_module(["GPU"])
        ov.Core.side_effect = RuntimeError("plugin load failed")
        with patch.dict(sys.modules, {"openvino": ov}):
            info = ovw.detect_intel_gpu()
        self.assertTrue(info["installed"])
        self.assertEqual(info["gpu_name"], "")


class TestGetPipeline(unittest.TestCase):
    def setUp(self):
        ovw._PIPELINE_CACHE.clear()
        self.addCleanup(ovw._PIPELINE_CACHE.clear)
        self.genai = MagicMock()
        self.hub = MagicMock()
        self.hub.snapshot_download.return_value = "C:/hf/whisper-small"
        self.mods = {"openvino_genai": self.genai, "huggingface_hub": self.hub}

    def test_pipeline_built_on_the_gpu_with_a_compile_cache_and_reused(self):
        with patch.dict(sys.modules, self.mods), \
                patch.object(ovw, "COMPILE_CACHE_DIR", Path("C:/tt/ov_cache")), \
                patch.object(Path, "mkdir"):
            p1 = ovw.get_pipeline("small")
            p2 = ovw.get_pipeline("small")
        self.assertIs(p1, p2)
        self.genai.WhisperPipeline.assert_called_once_with(
            "C:/hf/whisper-small", "GPU", CACHE_DIR=str(Path("C:/tt/ov_cache")),
        )

    def test_cached_model_is_used_without_network(self):
        with patch.dict(sys.modules, self.mods), patch.object(Path, "mkdir"):
            ovw.get_pipeline("small")
        self.hub.snapshot_download.assert_called_once_with(
            "OpenVINO/whisper-small-int8-ov", local_files_only=True
        )

    def test_missing_model_is_downloaded_with_a_progress_message(self):
        self.hub.snapshot_download.side_effect = [OSError("not cached"), "C:/hf/new"]
        messages = []
        with patch.dict(sys.modules, self.mods), patch.object(Path, "mkdir"):
            ovw.get_pipeline("small", progress=messages.append)
        self.assertEqual(self.hub.snapshot_download.call_args.args, ("OpenVINO/whisper-small-int8-ov",))
        self.assertTrue(any("Downloading" in m for m in messages))

    def test_release_evicts_the_pipeline(self):
        with patch.dict(sys.modules, self.mods), patch.object(Path, "mkdir"):
            ovw.get_pipeline("small")
            ovw.release_pipeline("small")
            ovw.get_pipeline("small")
        self.assertEqual(self.genai.WhisperPipeline.call_count, 2)



class TestPackageDeclarations(unittest.TestCase):
    """The pip spec lives in three places; Settings installs the installer's."""

    def test_settings_installer_uses_the_backend_spec(self):
        from app.utils.package_installer import get_package_info
        self.assertEqual(get_package_info("openvino")[0], ovw.PIP_PACKAGE)

    def test_pyproject_extra_uses_the_backend_spec(self):
        import tomllib
        root = Path(__file__).resolve().parent.parent
        with open(root / "pyproject.toml", "rb") as f:
            extras = tomllib.load(f)["project"]["optional-dependencies"]
        self.assertEqual(extras["openvino"], [ovw.PIP_PACKAGE])



class TestSettingsInstallPrompt(unittest.TestCase):
    """Config.set() writes to disk at once, so the OpenVINO prompt comes first."""

    def _save(self, device, installed):
        from app.ui.settings_dialog import SettingsDialog
        stub = MagicMock()
        stub.device_combo.currentData.return_value = device
        stub._install_provider_package.return_value = installed
        stub.min_speakers_spin.value.return_value = 0
        stub.max_speakers_spin.value.return_value = 0
        SettingsDialog._save_and_close(stub)
        return stub

    def test_declined_install_leaves_the_settings_untouched(self):
        stub = self._save("intel_gpu", installed=False)
        stub._install_provider_package.assert_called_once_with(
            "openvino", status_label=stub.gpu_status_label,
            purpose="to transcribe on the Intel GPU",
        )
        stub.config.set.assert_not_called()
        stub.accept.assert_not_called()

    def test_other_devices_never_prompt_for_openvino(self):
        stub = self._save("cpu", installed=True)
        self.assertNotIn("openvino", [c.args[0] for c in stub._install_provider_package.call_args_list])
        stub.config.set.assert_any_call("transcription", "device", "cpu")


if __name__ == "__main__":
    unittest.main()
