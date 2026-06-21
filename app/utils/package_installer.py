"""Ad-hoc package installer for optional AI provider dependencies."""

import importlib
import importlib.util
import shutil
import subprocess
import sys

# Map provider type to (import_name, pip_package, display_name)
PROVIDER_PACKAGES = {
    "claude": ("anthropic", "anthropic>=0.40.0", "Anthropic SDK"),
    "openai": ("openai", "openai>=1.50.0", "OpenAI SDK"),
    "grok": ("openai", "openai>=1.50.0", "OpenAI SDK (used by Grok)"),
    "gemini": ("google.generativeai", "google-generativeai>=0.8.0", "Google Generative AI SDK"),
    "mistral": ("mistralai", "mistralai>=1.0.0", "Mistral AI SDK"),
    "local": ("llama_cpp", "llama-cpp-python>=0.3.0", "llama.cpp Python bindings"),
}


def is_package_installed(provider_type: str) -> bool:
    """Check if the required package for a provider is installed."""
    info = PROVIDER_PACKAGES.get(provider_type)
    if info is None:
        return True
    import_name = info[0]
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        return False


def get_package_info(provider_type: str) -> tuple[str, str] | None:
    """Return (pip_package, display_name) for a provider, or None if unknown."""
    info = PROVIDER_PACKAGES.get(provider_type)
    if info is None:
        return None
    return info[1], info[2]


def _install_command(pip_package: str) -> list[str] | None:
    """Build the install command for the *current* interpreter.

    Always targets ``sys.executable`` so optional SDKs land in the active
    environment (the project's .venv), never the global Python install.

    Prefers pip when it's importable — e.g. a venv created by ``python -m venv``.
    uv-created virtualenvs ship WITHOUT pip, so when pip is missing fall back to
    ``uv pip install --python <sys.executable>``, which installs into this same
    interpreter. Returns ``None`` if neither installer is available.
    """
    if importlib.util.find_spec("pip") is not None:
        return [sys.executable, "-m", "pip", "install", pip_package]
    uv = shutil.which("uv")
    if uv:
        return [uv, "pip", "install", "--python", sys.executable, pip_package]
    return None


def install_package(pip_package: str) -> tuple[bool, str]:
    """Install a package into the current environment. Returns (success, output)."""
    cmd = _install_command(pip_package)
    if cmd is None:
        return False, (
            "Neither pip nor uv is available to install packages. "
            "Install uv (https://docs.astral.sh/uv/) and relaunch, or recreate "
            "the environment with pip available."
        )
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return True, result.stdout
        return False, result.stderr
    except subprocess.TimeoutExpired:
        return False, "Installation timed out."
    except Exception as e:
        return False, str(e)
