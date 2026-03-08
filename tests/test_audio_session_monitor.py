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


if __name__ == "__main__":
    unittest.main()
