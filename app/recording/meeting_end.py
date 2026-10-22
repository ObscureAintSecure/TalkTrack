"""Notice when a meeting app lets go of the microphone during a recording.

A conferencing app holds the microphone for the whole call, muted or not, and
releases it when you leave. Windows records that for its privacy indicator
under CapabilityAccessManager\\ConsentStore\\microphone: per app,
``LastUsedTimeStop`` is 0 while the app is using the microphone. That makes it
a better "the meeting ended" signal than silence (quiet screen-shares look the
same; WASAPI loopback stops delivering packets, #104) or audio sessions, which
Teams keeps open after a call (#105).

Reading the registry is cheap and needs no COM, so MainWindow polls it.
No Qt here.
"""

import logging
import os

logger = logging.getLogger(__name__)

CONSENT_STORE = (r"Software\Microsoft\Windows\CurrentVersion"
                 r"\CapabilityAccessManager\ConsentStore\microphone")

# Store (MSIX) apps, keyed by package family name prefix.
PACKAGED_MEETING_APPS = {
    "MSTeams_": "Microsoft Teams",
    "MicrosoftTeams_": "Microsoft Teams",
    "Microsoft.SkypeApp_": "Skype",
    "Zoom.Zoom_": "Zoom",
}

# Desktop apps, keyed by executable name. Browsers count: Meet, Teams on the
# web and Zoom's web client hold the microphone the same way.
DESKTOP_MEETING_APPS = {
    "ms-teams.exe": "Microsoft Teams",
    "teams.exe": "Microsoft Teams",
    "zoom.exe": "Zoom",
    "cpthost.exe": "Zoom",
    "webex.exe": "Webex",
    "ciscocollabhost.exe": "Webex",
    "slack.exe": "Slack",
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "firefox.exe": "Firefox",
    "brave.exe": "Brave",
}

# How long every meeting app must stay off the microphone before we ask.
# Teams briefly drops and retakes the microphone when the device changes.
DEFAULT_GRACE_SECONDS = 20


def meeting_app_name(key_name, packaged):
    """Friendly name of the meeting app behind a ConsentStore key, or None."""
    if packaged:
        for prefix, name in PACKAGED_MEETING_APPS.items():
            if key_name.startswith(prefix):
                return name
        return None
    exe = os.path.basename(key_name.replace("#", "\\")).lower()
    return DESKTOP_MEETING_APPS.get(exe)


def meeting_apps_using_mic(entries):
    """Names of the meeting apps using the microphone now.

    entries: iterable of (key name, packaged, LastUsedTimeStart, LastUsedTimeStop).
    """
    apps = set()
    for key_name, packaged, start, stop in entries:
        if start and not stop:
            name = meeting_app_name(key_name, packaged)
            if name:
                apps.add(name)
    return apps


def read_mic_usage():
    """The ConsentStore entries as (key name, packaged, start, stop) tuples.

    Returns [] off Windows or when the store can't be read: no data must
    mean no prompt, never a wrong one.
    """
    try:
        import winreg
    except ImportError:
        return []
    entries = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CONSENT_STORE) as store:
            entries.extend(_subkey_times(winreg, store, packaged=True))
            try:
                with winreg.OpenKey(store, "NonPackaged") as desktop:
                    entries.extend(_subkey_times(winreg, desktop, packaged=False))
            except OSError:
                pass
    except OSError:
        logger.debug("Microphone usage store unreadable", exc_info=True)
    return entries


def _subkey_times(winreg, key, packaged):
    i = 0
    while True:
        try:
            name = winreg.EnumKey(key, i)
        except OSError:
            return
        i += 1
        if packaged and name == "NonPackaged":
            continue
        try:
            with winreg.OpenKey(key, name) as sub:
                start = _qword(winreg, sub, "LastUsedTimeStart")
                stop = _qword(winreg, sub, "LastUsedTimeStop")
        except OSError:
            continue
        yield name, packaged, start, stop


def _qword(winreg, key, value_name):
    try:
        value, _type = winreg.QueryValueEx(key, value_name)
        return int(value)
    except (OSError, TypeError, ValueError):
        return 0


class MeetingEndWatcher:
    """Decides when to ask "did the meeting end?" during one recording.

    Arms when a meeting app is seen on the microphone, so a recording started
    before joining works, and an app that was never in a call can't end one.
    Fires once when every armed app has been off the microphone for
    ``grace_seconds``, then disarms: answering "keep recording" is not asked
    again until an app takes the microphone and lets it go again.
    """

    def __init__(self, grace_seconds=DEFAULT_GRACE_SECONDS):
        self.grace_seconds = grace_seconds
        self._armed = set()         # apps seen using the mic since the last prompt
        self._released_at = None    # when the last armed app let go

    @property
    def armed(self):
        return bool(self._armed)

    def update(self, apps_using_mic, now):
        """Feed the current apps; returns the apps that ended the meeting, or None."""
        if apps_using_mic:
            self._armed |= set(apps_using_mic)
            self._released_at = None
            return None
        if not self._armed:
            return None
        if self._released_at is None:
            self._released_at = now
            return None
        if now - self._released_at < self.grace_seconds:
            return None
        ended = sorted(self._armed)
        self._armed = set()
        self._released_at = None
        return ended
