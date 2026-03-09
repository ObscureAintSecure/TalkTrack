"""Tests for DependencyChecker."""
import unittest
from unittest.mock import patch, MagicMock


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
