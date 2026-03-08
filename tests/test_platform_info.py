"""Tests for platform_info utility."""
import unittest
from unittest.mock import patch


class TestPlatformInfo(unittest.TestCase):

    @patch("platform.version", return_value="10.0.22621")
    def test_is_windows_11_with_win11_build(self, mock_ver):
        from app.utils.platform_info import is_windows_11
        self.assertTrue(is_windows_11())

    @patch("platform.version", return_value="10.0.19045")
    def test_is_windows_11_with_win10_build(self, mock_ver):
        from app.utils.platform_info import is_windows_11
        self.assertFalse(is_windows_11())

    @patch("platform.version", return_value="10.0.22000")
    def test_is_windows_11_with_exact_boundary(self, mock_ver):
        from app.utils.platform_info import is_windows_11
        self.assertTrue(is_windows_11())

    @patch("platform.system", return_value="Windows")
    def test_is_windows_true(self, mock_sys):
        from app.utils.platform_info import is_windows
        self.assertTrue(is_windows())

    @patch("platform.system", return_value="Linux")
    def test_is_windows_false(self, mock_sys):
        from app.utils.platform_info import is_windows
        self.assertFalse(is_windows())


if __name__ == "__main__":
    unittest.main()
