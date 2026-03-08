"""Monitor active audio sessions and known audio apps.

Enumerates which Windows apps are currently producing audio (via pycaw)
and also detects well-known audio apps that are running but may not have
active audio sessions yet (e.g., Teams before joining a call).

Returns grouped entries: one per app name with all associated PIDs.
"""
import psutil
from pycaw.pycaw import AudioUtilities


FRIENDLY_NAMES = {
    "msedge": "Microsoft Edge",
    "msedgewebview2": "Microsoft Edge",
    "chrome": "Google Chrome",
    "firefox": "Firefox",
    "Teams": "Microsoft Teams",
    "ms-teams": "Microsoft Teams",
    "Spotify": "Spotify",
    "Discord": "Discord",
    "Zoom": "Zoom",
    "slack": "Slack",
}

# Process names (without .exe) that are well-known audio/call apps.
# These will be detected from running processes even without active
# audio sessions, so users can pre-select them before a call starts.
KNOWN_AUDIO_APPS = {
    "ms-teams",
    "Teams",
    "Zoom",
    "Discord",
    "slack",
    "Spotify",
}


def _friendly_name(process_name):
    """Convert process name to a user-friendly display name."""
    name = process_name
    if name.lower().endswith(".exe"):
        name = name[:-4]
    return FRIENDLY_NAMES.get(name, name)


def _base_name(process_name):
    """Strip .exe suffix for matching."""
    if process_name.lower().endswith(".exe"):
        return process_name[:-4]
    return process_name


def get_active_audio_apps():
    """Return list of apps available for per-app audio capture.

    Combines two sources:
      1. Apps with active Windows audio sessions (pycaw) — currently using audio
      2. Well-known audio/call apps that are running — even if not yet in a call

    Each entry: {"pids": [int, ...], "name": str, "process_name": str, "active": bool}

    Deduplicates by display name, grouping all PIDs for the same app.
    The "active" flag is True if the app has at least one pycaw audio session.
    """
    # Map: display_name -> {"pids": set, "process_name": str, "active": bool}
    app_map = {}

    # --- Source 1: pycaw audio sessions ---
    active_pids = set()
    try:
        sessions = AudioUtilities.GetAllSessions()
    except Exception:
        sessions = []

    for session in sessions:
        if session.Process is None:
            continue

        pid = session.Process.pid
        if pid == 0:
            continue

        process_name = session.Process.name()
        display_name = _friendly_name(process_name)
        active_pids.add(pid)

        if display_name not in app_map:
            app_map[display_name] = {
                "pids": set(),
                "process_name": process_name,
                "active": True,
            }
        app_map[display_name]["pids"].add(pid)
        app_map[display_name]["active"] = True

    # --- Source 2: running processes for known audio apps ---
    try:
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                proc_name = proc.info["name"]
                base = _base_name(proc_name)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

            if base not in KNOWN_AUDIO_APPS:
                continue

            pid = proc.info["pid"]
            if pid == 0:
                continue

            display_name = _friendly_name(proc_name)

            if display_name not in app_map:
                app_map[display_name] = {
                    "pids": set(),
                    "process_name": proc_name,
                    "active": False,
                }
            app_map[display_name]["pids"].add(pid)
    except Exception:
        pass

    # Build sorted result list
    apps = []
    for display_name, info in app_map.items():
        apps.append({
            "pids": sorted(info["pids"]),
            "name": display_name,
            "process_name": info["process_name"],
            "active": info["active"],
        })

    apps.sort(key=lambda a: a["name"].lower())
    return apps
