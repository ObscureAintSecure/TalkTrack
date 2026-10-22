"""Tests for meeting-end detection from microphone usage (no Qt, no registry)."""
import unittest
from unittest.mock import patch

from app.recording.meeting_end import (
    MeetingEndWatcher, meeting_app_name, meeting_apps_using_mic, read_mic_usage,
)

TEAMS = ("MSTeams_8wekyb3d8bbwe", True)
CHROME = ("C:#Program Files#Google#Chrome#Application#chrome.exe", False)
PYTHON = ("C:#Python312#pythonw.exe", False)


class TestMeetingAppName(unittest.TestCase):

    def test_packaged_teams(self):
        self.assertEqual(meeting_app_name(*TEAMS), "Microsoft Teams")

    def test_desktop_apps_by_executable_ignoring_case(self):
        self.assertEqual(meeting_app_name(*CHROME), "Google Chrome")
        self.assertEqual(meeting_app_name("C:#Users#x#AppData#Roaming#Zoom#bin#Zoom.exe", False), "Zoom")

    def test_other_apps_are_not_meeting_apps(self):
        # TalkTrack itself holds the microphone while recording.
        self.assertIsNone(meeting_app_name(*PYTHON))
        self.assertIsNone(meeting_app_name("windows.immersivecontrolpanel_cw5n1h2txyewy", True))
        self.assertIsNone(meeting_app_name("NonPackagedTeams", True))


class TestMeetingAppsUsingMic(unittest.TestCase):

    def test_in_use_means_started_and_not_stopped(self):
        entries = [
            (*TEAMS, 134000, 0),          # using it now
            (*CHROME, 133000, 133500),    # used earlier, released
            (*PYTHON, 135000, 0),         # in use, but not a meeting app
        ]
        self.assertEqual(meeting_apps_using_mic(entries), {"Microsoft Teams"})

    def test_never_used(self):
        self.assertEqual(meeting_apps_using_mic([(*TEAMS, 0, 0)]), set())


class TestReadMicUsage(unittest.TestCase):

    def test_off_windows_returns_nothing(self):
        with patch.dict("sys.modules", {"winreg": None}):
            self.assertEqual(read_mic_usage(), [])

    def test_unreadable_store_returns_nothing(self):
        import types
        fake = types.SimpleNamespace(HKEY_CURRENT_USER=1)

        def fail(*_a):
            raise OSError("no key")
        fake.OpenKey = fail
        with patch.dict("sys.modules", {"winreg": fake}):
            self.assertEqual(read_mic_usage(), [])


class TestMeetingEndWatcher(unittest.TestCase):

    def test_fires_after_the_grace_period(self):
        w = MeetingEndWatcher(grace_seconds=20)
        self.assertIsNone(w.update({"Microsoft Teams"}, 0))
        self.assertIsNone(w.update(set(), 100))
        self.assertIsNone(w.update(set(), 119))
        self.assertEqual(w.update(set(), 120), ["Microsoft Teams"])

    def test_fires_once_then_disarms(self):
        w = MeetingEndWatcher(grace_seconds=20)
        w.update({"Microsoft Teams"}, 0)
        w.update(set(), 10)
        self.assertEqual(w.update(set(), 30), ["Microsoft Teams"])
        self.assertFalse(w.armed)
        self.assertIsNone(w.update(set(), 1000))

    def test_rearms_when_an_app_takes_the_mic_again(self):
        w = MeetingEndWatcher(grace_seconds=20)
        w.update({"Microsoft Teams"}, 0)
        w.update(set(), 10)
        w.update(set(), 30)                       # asked, user kept recording
        w.update({"Microsoft Teams"}, 40)         # joined another call
        w.update(set(), 50)
        self.assertEqual(w.update(set(), 70), ["Microsoft Teams"])

    def test_a_short_release_is_not_an_ending(self):
        w = MeetingEndWatcher(grace_seconds=20)
        w.update({"Microsoft Teams"}, 0)
        w.update(set(), 10)                       # device switch
        w.update({"Microsoft Teams"}, 15)
        w.update(set(), 25)
        self.assertIsNone(w.update(set(), 40))
        self.assertEqual(w.update(set(), 45), ["Microsoft Teams"])

    def test_never_fires_without_a_meeting_app_on_the_mic(self):
        # Recording a call that isn't in a known app, or nothing at all.
        w = MeetingEndWatcher(grace_seconds=20)
        for t in range(0, 600, 2):
            self.assertIsNone(w.update(set(), t))

    def test_waits_for_every_app_that_was_in_the_call(self):
        w = MeetingEndWatcher(grace_seconds=20)
        w.update({"Microsoft Teams", "Google Chrome"}, 0)
        w.update({"Google Chrome"}, 10)
        self.assertIsNone(w.update({"Google Chrome"}, 100))
        w.update(set(), 110)
        self.assertEqual(w.update(set(), 130), ["Google Chrome", "Microsoft Teams"])


class TestMainWindowWiring(unittest.TestCase):
    """MainWindow's meeting-end methods against a stub window (no widgets)."""

    def _window(self, enabled=True):
        from unittest.mock import MagicMock
        stub = MagicMock()
        stub.config.get.side_effect = lambda s, k: enabled if (s, k) == ("general", "meeting_end_prompt") else None
        stub._meeting_end_watcher = None
        stub._meeting_end_dialog = None
        return stub

    def test_recording_starts_one_watcher(self):
        from app.main_window import MainWindow
        from app.recording.recorder import RecordingState
        w = self._window()
        MainWindow._update_meeting_end_watch(w, RecordingState.RECORDING)
        first = w._meeting_end_watcher
        self.assertIsInstance(first, MeetingEndWatcher)
        w._meeting_end_timer.start.assert_called_once()
        MainWindow._update_meeting_end_watch(w, RecordingState.PAUSED)
        MainWindow._update_meeting_end_watch(w, RecordingState.RECORDING)
        self.assertIs(w._meeting_end_watcher, first)   # pause/resume keeps it armed

    def test_disabled_in_settings(self):
        from app.main_window import MainWindow
        from app.recording.recorder import RecordingState
        w = self._window(enabled=False)
        MainWindow._update_meeting_end_watch(w, RecordingState.RECORDING)
        self.assertIsNone(w._meeting_end_watcher)
        w._meeting_end_timer.start.assert_not_called()

    def test_stopping_tears_down_and_closes_the_prompt(self):
        from unittest.mock import MagicMock
        from app.main_window import MainWindow
        from app.recording.recorder import RecordingState
        w = self._window()
        w._meeting_end_watcher = MeetingEndWatcher()
        dialog = MagicMock()
        w._meeting_end_dialog = dialog
        MainWindow._update_meeting_end_watch(w, RecordingState.STOPPING)
        w._meeting_end_timer.stop.assert_called_once()
        self.assertIsNone(w._meeting_end_watcher)
        dialog.dismiss.assert_called_once()
        self.assertIsNone(w._meeting_end_dialog)

    def test_poll_prompts_when_the_watcher_fires(self):
        from app.main_window import MainWindow
        w = self._window()
        w._meeting_end_watcher = MeetingEndWatcher(grace_seconds=0)
        usage = [[("MSTeams_8wekyb3d8bbwe", True, 1, 0)], [("MSTeams_8wekyb3d8bbwe", True, 1, 2)],
                 [("MSTeams_8wekyb3d8bbwe", True, 1, 2)]]
        with patch("app.main_window.read_mic_usage", side_effect=usage):
            for _ in usage:
                MainWindow._poll_meeting_end(w)
        w._show_meeting_end_prompt.assert_called_once_with(["Microsoft Teams"])

    def test_stop_answer_stops_only_a_running_recording(self):
        from app.main_window import MainWindow
        from app.recording.recorder import RecordingState
        w = self._window()
        w.recorder.state = RecordingState.RECORDING
        MainWindow._on_meeting_end_stop(w)
        w._stop_recording.assert_called_once()
        w = self._window()
        w.recorder.state = RecordingState.IDLE
        MainWindow._on_meeting_end_stop(w)
        w._stop_recording.assert_not_called()


class TestFormatApps(unittest.TestCase):

    def test_lists(self):
        from app.ui.meeting_end_dialog import format_apps
        self.assertEqual(format_apps(["Zoom"]), "Zoom")
        self.assertEqual(format_apps(["A", "B"]), "A and B")
        self.assertEqual(format_apps(["A", "B", "C"]), "A, B and C")
        self.assertEqual(format_apps([]), "The meeting app")


if __name__ == "__main__":
    unittest.main()
