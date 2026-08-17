"""Tests for DependencyChecker."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestWhisperCacheDir(unittest.TestCase):
    """The HF cache path must use each model's real publishing org, not a
    hardcoded Systran — large-v3-turbo lives under mobiuslabsgmbh."""

    def _cache_dir(self, model_size):
        from app.utils.dependency_checker import whisper_cache_dir
        return whisper_cache_dir(model_size)

    def test_systran_model(self):
        self.assertEqual(
            self._cache_dir("large-v3").name,
            "models--Systran--faster-whisper-large-v3",
        )

    def test_turbo_model_uses_its_own_org(self):
        self.assertEqual(
            self._cache_dir("large-v3-turbo").name,
            "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo",
        )

    def test_unknown_model_falls_back_to_systran_layout(self):
        self.assertEqual(
            self._cache_dir("not-a-model").name,
            "models--Systran--faster-whisper-not-a-model",
        )

    def test_falls_back_when_faster_whisper_unimportable(self):
        import sys
        with patch.dict(sys.modules, {"faster_whisper.utils": None}):
            self.assertEqual(
                self._cache_dir("large-v3").name,
                "models--Systran--faster-whisper-large-v3",
            )


class TestCheckWhisperModel(unittest.TestCase):
    """check_whisper_model finds a cached non-Systran model."""

    def _check(self, model_size, cached_dirname):
        from app.utils.dependency_checker import DependencyChecker
        config = MagicMock()
        config.get.return_value = model_size
        with tempfile.TemporaryDirectory() as tmp:
            hub = Path(tmp) / ".cache" / "huggingface" / "hub"
            (hub / cached_dirname).mkdir(parents=True)
            with patch("app.utils.dependency_checker.Path.home", return_value=Path(tmp)):
                return DependencyChecker(config).check_whisper_model()

    def test_cached_turbo_model_passes(self):
        result = self._check(
            "large-v3-turbo", "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"
        )
        self.assertTrue(result["passed"])

    def test_uncached_model_fails(self):
        result = self._check("large-v3-turbo", "models--Systran--faster-whisper-base")
        self.assertFalse(result["passed"])


class TestPackageMetadataCheck(unittest.TestCase):
    """Detects packages that import fine but have gutted dist-info metadata
    (the interrupted-uv-sync failure mode)."""

    def _checker(self):
        from app.utils.dependency_checker import DependencyChecker
        return DependencyChecker()

    def test_all_metadata_present_passes(self):
        # numpy is installed with intact metadata in the test environment.
        result = self._checker().check_package_metadata(packages=("numpy",))
        self.assertTrue(result["passed"])

    def test_importable_without_metadata_reports_damaged(self):
        # stdlib json imports but has no dist metadata — same signature as a
        # package whose dist-info was gutted.
        result = self._checker().check_package_metadata(packages=("json",))
        self.assertFalse(result["passed"])
        self.assertEqual(result["level"], "critical")
        self.assertIn("json", result["message"])
        self.assertIn("reinstall", result["action"].lower())

    def test_not_installed_reports_missing(self):
        result = self._checker().check_package_metadata(
            packages=("definitely-not-a-real-package-xyz",)
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["level"], "warn")

    def test_metadata_version_none_reports_damaged(self):
        # importlib.metadata.version can return None (dist-info folder exists
        # but METADATA file is gone) — must count as damaged, not passed.
        with patch("importlib.metadata.version", return_value=None):
            result = self._checker().check_package_metadata(packages=("numpy",))
        self.assertFalse(result["passed"])
        self.assertEqual(result["level"], "critical")

    def test_included_in_run_all_checks(self):
        from app.utils.dependency_checker import DependencyChecker
        with patch.object(DependencyChecker, "check_package_metadata",
                          return_value={"name": "Package Metadata",
                                        "passed": True, "level": "critical",
                                        "message": "", "action": None}) as m:
            # Other checks hit real APIs; just verify ours is called.
            try:
                DependencyChecker().run_all_checks()
            except Exception:
                pass
            m.assert_called_once()


class TestDependencyChecker(unittest.TestCase):

    @patch("app.utils.dependency_checker.get_input_devices", return_value=[{"name": "Mic"}])
    def test_mic_check_passes_with_devices(self, mock_devs):
        from app.utils.dependency_checker import DependencyChecker
        checker = DependencyChecker()
        result = checker.check_microphone()
        self.assertTrue(result["passed"])

    @patch("app.utils.dependency_checker.get_input_devices", return_value=[])
    def test_mic_check_fails_with_no_devices(self, mock_devs):
        from app.utils.dependency_checker import DependencyChecker
        checker = DependencyChecker()
        result = checker.check_microphone()
        self.assertFalse(result["passed"])

    @patch("app.utils.dependency_checker.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_ffmpeg_check_passes_when_installed(self, mock_which):
        from app.utils.dependency_checker import DependencyChecker
        checker = DependencyChecker()
        result = checker.check_ffmpeg()
        self.assertTrue(result["passed"])

    @patch("app.utils.dependency_checker.shutil.which", return_value=None)
    def test_ffmpeg_check_fails_when_missing(self, mock_which):
        from app.utils.dependency_checker import DependencyChecker
        checker = DependencyChecker()
        result = checker.check_ffmpeg()
        self.assertFalse(result["passed"])
        self.assertEqual(result["level"], "warn")


    @patch("app.utils.dependency_checker.subprocess.run")
    def test_gpu_check_passes_with_cuda_torch(self, mock_run):
        """When torch.cuda.is_available() returns True, GPU check passes."""
        from app.utils.dependency_checker import DependencyChecker
        with patch.dict("sys.modules", {
            "torch": MagicMock(
                cuda=MagicMock(
                    is_available=MagicMock(return_value=True),
                    get_device_name=MagicMock(return_value="RTX 4070 Ti"),
                ),
                version=MagicMock(cuda="12.6"),
            ),
        }):
            info = DependencyChecker.detect_gpu_cuda()
            self.assertTrue(info["has_nvidia_gpu"])
            self.assertTrue(info["torch_has_cuda"])
            self.assertEqual(info["gpu_name"], "RTX 4070 Ti")

    @patch("app.utils.dependency_checker.subprocess.run")
    def test_gpu_check_warns_nvidia_no_cuda(self, mock_run):
        """NVIDIA GPU present but PyTorch is CPU-only."""
        mock_run.return_value = MagicMock(returncode=0, stdout="NVIDIA GeForce RTX 4070 Ti\n")
        from app.utils.dependency_checker import DependencyChecker
        with patch.dict("sys.modules", {
            "torch": MagicMock(
                cuda=MagicMock(is_available=MagicMock(return_value=False)),
            ),
        }):
            info = DependencyChecker.detect_gpu_cuda()
            self.assertTrue(info["has_nvidia_gpu"])
            self.assertFalse(info["torch_has_cuda"])

        # The check should warn when device is set to cuda
        config = MagicMock()
        config.get.return_value = "cuda"
        checker = DependencyChecker(config)
        with patch.object(DependencyChecker, "detect_gpu_cuda", return_value=info):
            result = checker.check_gpu_cuda()
            self.assertFalse(result["passed"])
            self.assertIn("pip install", result["action"])

    @patch("app.utils.dependency_checker.subprocess.run", side_effect=FileNotFoundError)
    def test_gpu_check_no_nvidia(self, mock_run):
        """No NVIDIA GPU detected at all."""
        from app.utils.dependency_checker import DependencyChecker
        with patch.dict("sys.modules", {}):
            # Force ImportError on torch
            import sys
            saved = sys.modules.get("torch")
            sys.modules["torch"] = None  # causes ImportError
            try:
                info = DependencyChecker.detect_gpu_cuda()
                self.assertFalse(info["has_nvidia_gpu"])
                self.assertFalse(info["torch_has_cuda"])
            finally:
                if saved is not None:
                    sys.modules["torch"] = saved
                else:
                    sys.modules.pop("torch", None)


if __name__ == "__main__":
    unittest.main()
