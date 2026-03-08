"""Monitor active audio sessions using pycaw.

Enumerates which Windows apps are currently producing audio,
returning their process names and PIDs for the per-app capture UI.
"""
from pycaw.pycaw import AudioUtilities


FRIENDLY_NAMES = {
    "msedge": "Microsoft Edge",
    "chrome": "Google Chrome",
    "firefox": "Firefox",
    "Teams": "Microsoft Teams",
    "ms-teams": "Microsoft Teams",
    "Spotify": "Spotify",
    "Discord": "Discord",
    "Zoom": "Zoom",
    "slack": "Slack",
}


def _friendly_name(process_name):
    """Convert process name to a user-friendly display name."""
    name = process_name
    if name.lower().endswith(".exe"):
        name = name[:-4]
    return FRIENDLY_NAMES.get(name, name)


def get_active_audio_apps():
    """Return list of apps currently registered in Windows audio sessions.

    Each entry: {"pid": int, "name": str, "process_name": str}
    Deduplicates by PID.
    """
    apps = []
    seen_pids = set()

    try:
        sessions = AudioUtilities.GetAllSessions()
    except Exception:
        return []

    for session in sessions:
        if session.Process is None:
            continue

        pid = session.Process.pid
        if pid in seen_pids or pid == 0:
            continue
        seen_pids.add(pid)

        process_name = session.Process.name()
        display_name = _friendly_name(process_name)

        apps.append({
            "pid": pid,
            "name": display_name,
            "process_name": process_name,
        })

    apps.sort(key=lambda a: a["name"].lower())
    return apps
