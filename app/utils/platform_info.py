"""Platform detection utilities for TalkTrack."""
import platform


def is_windows():
    """Check if running on Windows."""
    return platform.system() == "Windows"


def is_windows_11():
    """Check if running on Windows 11 (Build 22000+).

    Windows 11 introduced per-process audio loopback capture via
    ActivateAudioInterfaceAsync with AUDIOCLIENT_ACTIVATION_PARAMS.
    """
    if not is_windows():
        return False
    try:
        build = int(platform.version().split(".")[-1])
        return build >= 22000
    except (ValueError, IndexError):
        return False


def get_windows_build():
    """Return the Windows build number, or 0 if not on Windows."""
    if not is_windows():
        return 0
    try:
        return int(platform.version().split(".")[-1])
    except (ValueError, IndexError):
        return 0
