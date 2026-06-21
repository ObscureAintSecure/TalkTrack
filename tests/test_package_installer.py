"""Tests for the ad-hoc AI provider package installer."""

import sys
import unittest
from unittest.mock import patch

from app.utils import package_installer
from app.utils.package_installer import _install_command, get_package_info


class InstallCommandTest(unittest.TestCase):
    """`_install_command` must always target the current interpreter, never global."""

    def test_uses_pip_when_pip_available(self):
        with patch.object(package_installer.importlib.util, "find_spec", return_value=object()):
            cmd = _install_command("anthropic>=0.40.0")
        self.assertEqual(cmd, [sys.executable, "-m", "pip", "install", "anthropic>=0.40.0"])

    def test_falls_back_to_uv_when_pip_missing(self):
        # uv venvs ship without pip — install_package must not silently fail.
        with patch.object(package_installer.importlib.util, "find_spec", return_value=None), \
             patch.object(package_installer.shutil, "which", return_value="C:\\bin\\uv.exe"):
            cmd = _install_command("openai>=1.50.0")
        self.assertEqual(
            cmd,
            ["C:\\bin\\uv.exe", "pip", "install", "--python", sys.executable, "openai>=1.50.0"],
        )

    def test_returns_none_when_no_installer(self):
        with patch.object(package_installer.importlib.util, "find_spec", return_value=None), \
             patch.object(package_installer.shutil, "which", return_value=None):
            self.assertIsNone(_install_command("mistralai>=1.0.0"))

    def test_command_targets_current_interpreter_not_global(self):
        # Whichever installer is chosen, the package goes to sys.executable.
        with patch.object(package_installer.importlib.util, "find_spec", return_value=None), \
             patch.object(package_installer.shutil, "which", return_value="uv"):
            cmd = _install_command("anthropic")
        self.assertIn(sys.executable, cmd)


class InstallPackageTest(unittest.TestCase):
    def test_no_installer_reports_failure(self):
        with patch.object(package_installer.importlib.util, "find_spec", return_value=None), \
             patch.object(package_installer.shutil, "which", return_value=None):
            ok, output = package_installer.install_package("anthropic")
        self.assertFalse(ok)
        self.assertIn("uv", output)

    def test_success_returns_stdout(self):
        class _Result:
            returncode = 0
            stdout = "installed!"
            stderr = ""

        with patch.object(package_installer.importlib.util, "find_spec", return_value=object()), \
             patch.object(package_installer.subprocess, "run", return_value=_Result()) as run:
            ok, output = package_installer.install_package("anthropic>=0.40.0")
        self.assertTrue(ok)
        self.assertEqual(output, "installed!")
        # Confirm we invoked the current interpreter's pip.
        called_cmd = run.call_args[0][0]
        self.assertEqual(called_cmd[0], sys.executable)


class ProviderInfoTest(unittest.TestCase):
    def test_known_provider_returns_package(self):
        info = get_package_info("claude")
        self.assertIsNotNone(info)
        self.assertEqual(info[0], "anthropic>=0.40.0")

    def test_unknown_provider_returns_none(self):
        self.assertIsNone(get_package_info("nonexistent"))


if __name__ == "__main__":
    unittest.main()
