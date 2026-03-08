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


if __name__ == "__main__":
    unittest.main()
