"""Tests for AudioSessionMonitor."""
import unittest
from unittest.mock import patch, MagicMock


class TestGetActiveAudioApps(unittest.TestCase):

    @patch("app.utils.audio_session_monitor.psutil")
    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_returns_empty_list_when_no_sessions_and_no_known_apps(self, mock_au, mock_psutil):
        mock_au.GetAllSessions.return_value = []
        mock_psutil.process_iter.return_value = []
        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        self.assertEqual(result, [])

    @patch("app.utils.audio_session_monitor.psutil")
    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_returns_apps_with_active_audio_sessions(self, mock_au, mock_psutil):
        mock_session = MagicMock()
        mock_session.Process = MagicMock()
        mock_session.Process.name.return_value = "Teams.exe"
        mock_session.Process.pid = 12345

        mock_au.GetAllSessions.return_value = [mock_session]
        mock_psutil.process_iter.return_value = []

        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Microsoft Teams")
        self.assertEqual(result[0]["pids"], [12345])
        self.assertTrue(result[0]["active"])

    @patch("app.utils.audio_session_monitor.psutil")
    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_skips_sessions_without_process(self, mock_au, mock_psutil):
        mock_session = MagicMock()
        mock_session.Process = None

        mock_au.GetAllSessions.return_value = [mock_session]
        mock_psutil.process_iter.return_value = []

        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        self.assertEqual(result, [])

    @patch("app.utils.audio_session_monitor.psutil")
    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_groups_multiple_pids_by_display_name(self, mock_au, mock_psutil):
        """Two Zoom processes with different PIDs should appear as one entry."""
        session1 = MagicMock()
        session1.Process = MagicMock()
        session1.Process.name.return_value = "Zoom.exe"
        session1.Process.pid = 100

        session2 = MagicMock()
        session2.Process = MagicMock()
        session2.Process.name.return_value = "Zoom.exe"
        session2.Process.pid = 200

        mock_au.GetAllSessions.return_value = [session1, session2]
        mock_psutil.process_iter.return_value = []

        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Zoom")
        self.assertEqual(result[0]["pids"], [100, 200])

    @patch("app.utils.audio_session_monitor.psutil")
    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_deduplicates_same_pid_same_app(self, mock_au, mock_psutil):
        """Same PID appearing in multiple sessions should only appear once."""
        session1 = MagicMock()
        session1.Process = MagicMock()
        session1.Process.name.return_value = "chrome.exe"
        session1.Process.pid = 100

        session2 = MagicMock()
        session2.Process = MagicMock()
        session2.Process.name.return_value = "chrome.exe"
        session2.Process.pid = 100

        mock_au.GetAllSessions.return_value = [session1, session2]
        mock_psutil.process_iter.return_value = []

        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pids"], [100])

    @patch("app.utils.audio_session_monitor.psutil")
    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_detects_known_apps_from_running_processes(self, mock_au, mock_psutil):
        """Teams should appear even without an active audio session."""
        mock_au.GetAllSessions.return_value = []

        mock_proc = MagicMock()
        mock_proc.info = {"pid": 5555, "name": "ms-teams.exe"}

        mock_psutil.process_iter.return_value = [mock_proc]

        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Microsoft Teams")
        self.assertEqual(result[0]["pids"], [5555])
        self.assertFalse(result[0]["active"])

    @patch("app.utils.audio_session_monitor.psutil")
    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_merges_pycaw_and_process_pids(self, mock_au, mock_psutil):
        """If Teams has a pycaw session AND a running process, merge PIDs."""
        mock_session = MagicMock()
        mock_session.Process = MagicMock()
        mock_session.Process.name.return_value = "ms-teams.exe"
        mock_session.Process.pid = 1000

        mock_au.GetAllSessions.return_value = [mock_session]

        mock_proc = MagicMock()
        mock_proc.info = {"pid": 2000, "name": "ms-teams.exe"}

        mock_psutil.process_iter.return_value = [mock_proc]

        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Microsoft Teams")
        self.assertIn(1000, result[0]["pids"])
        self.assertIn(2000, result[0]["pids"])
        self.assertTrue(result[0]["active"])  # active because pycaw found it

    @patch("app.utils.audio_session_monitor.psutil")
    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_webview2_child_of_teams_attributed_to_teams(self, mock_au, mock_psutil):
        """New Teams (Teams 2.x) audio comes from msedgewebview2 child processes
        parented by ms-teams.exe. They must appear under "Microsoft Teams",
        not "Microsoft Edge", or users selecting Teams capture nothing.
        """
        child_session = MagicMock()
        child_session.Process = MagicMock()
        child_session.Process.name.return_value = "msedgewebview2.exe"
        child_session.Process.pid = 4242

        mock_au.GetAllSessions.return_value = [child_session]

        # psutil.Process(4242).parent() returns ms-teams.exe process
        parent_proc = MagicMock()
        parent_proc.name.return_value = "ms-teams.exe"
        parent_proc.pid = 1000
        parent_proc.parent.return_value = None

        child_proc = MagicMock()
        child_proc.name.return_value = "msedgewebview2.exe"
        child_proc.pid = 4242
        child_proc.parent.return_value = parent_proc

        def process_factory(pid):
            return {4242: child_proc, 1000: parent_proc}[pid]

        mock_psutil.Process.side_effect = process_factory
        mock_psutil.NoSuchProcess = Exception
        mock_psutil.AccessDenied = Exception
        mock_psutil.process_iter.return_value = []

        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        names = [r["name"] for r in result]
        self.assertIn("Microsoft Teams", names)
        self.assertNotIn("Microsoft Edge", names)
        teams = next(r for r in result if r["name"] == "Microsoft Teams")
        self.assertIn(4242, teams["pids"])

    @patch("app.utils.audio_session_monitor.psutil")
    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_standalone_edge_webview_stays_as_edge(self, mock_au, mock_psutil):
        """msedgewebview2 without Teams parent stays attributed to Edge."""
        sess = MagicMock()
        sess.Process = MagicMock()
        sess.Process.name.return_value = "msedgewebview2.exe"
        sess.Process.pid = 7777

        mock_au.GetAllSessions.return_value = [sess]

        root = MagicMock()
        root.name.return_value = "explorer.exe"
        root.pid = 1
        root.parent.return_value = None

        proc = MagicMock()
        proc.name.return_value = "msedgewebview2.exe"
        proc.pid = 7777
        proc.parent.return_value = root

        mock_psutil.Process.side_effect = lambda pid: {7777: proc, 1: root}[pid]
        mock_psutil.NoSuchProcess = Exception
        mock_psutil.AccessDenied = Exception
        mock_psutil.process_iter.return_value = []

        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Microsoft Edge")

    @patch("app.utils.audio_session_monitor.psutil")
    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_strips_exe_extension_from_name(self, mock_au, mock_psutil):
        mock_session = MagicMock()
        mock_session.Process = MagicMock()
        mock_session.Process.name.return_value = "Spotify.exe"
        mock_session.Process.pid = 999

        mock_au.GetAllSessions.return_value = [mock_session]
        mock_psutil.process_iter.return_value = []

        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        self.assertEqual(result[0]["name"], "Spotify")


    # --- session State filtering (issue #6) ---

    @patch("app.utils.audio_session_monitor.psutil")
    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_active_session_state_one_is_listed_active(self, mock_au, mock_psutil):
        sess = MagicMock()
        sess.Process = MagicMock()
        sess.Process.name.return_value = "Spotify.exe"
        sess.Process.pid = 11
        sess.State = 1  # AudioSessionStateActive
        mock_au.GetAllSessions.return_value = [sess]
        mock_psutil.process_iter.return_value = []

        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["active"])

    @patch("app.utils.audio_session_monitor.psutil")
    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_inactive_session_state_zero_is_filtered(self, mock_au, mock_psutil):
        sess = MagicMock()
        sess.Process = MagicMock()
        sess.Process.name.return_value = "vlc.exe"  # not a known audio app
        sess.Process.pid = 22
        sess.State = 0  # AudioSessionStateInactive
        mock_au.GetAllSessions.return_value = [sess]
        mock_psutil.process_iter.return_value = []

        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        self.assertEqual(result, [])

    @patch("app.utils.audio_session_monitor.psutil")
    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_expired_session_state_two_is_filtered(self, mock_au, mock_psutil):
        sess = MagicMock()
        sess.Process = MagicMock()
        sess.Process.name.return_value = "vlc.exe"
        sess.Process.pid = 33
        sess.State = 2  # AudioSessionStateExpired
        mock_au.GetAllSessions.return_value = [sess]
        mock_psutil.process_iter.return_value = []

        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        self.assertEqual(result, [])

    @patch("app.utils.audio_session_monitor.psutil")
    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_known_app_with_inactive_session_shows_inactive_via_process(self, mock_au, mock_psutil):
        # Teams idle: only an Inactive session, but it's a known audio app, so
        # it should still appear (from the process scan) marked active=False.
        sess = MagicMock()
        sess.Process = MagicMock()
        sess.Process.name.return_value = "ms-teams.exe"
        sess.Process.pid = 44
        sess.State = 0
        mock_au.GetAllSessions.return_value = [sess]

        proc = MagicMock()
        proc.info = {"pid": 44, "name": "ms-teams.exe"}
        mock_psutil.process_iter.return_value = [proc]
        mock_psutil.NoSuchProcess = Exception
        mock_psutil.AccessDenied = Exception

        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Microsoft Teams")
        self.assertFalse(result[0]["active"])
        self.assertEqual(result[0]["pids"], [44])


if __name__ == "__main__":
    unittest.main()
