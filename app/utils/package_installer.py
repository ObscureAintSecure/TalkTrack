"""Ad-hoc package installer for optional AI provider dependencies."""

import importlib
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


def install_package(pip_package: str) -> tuple[bool, str]:
    """Install a package via pip. Returns (success, output)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pip_package],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return True, result.stdout
        return False, result.stderr
    except subprocess.TimeoutExpired:
        return False, "Installation timed out."
    except Exception as e:
        return False, str(e)
