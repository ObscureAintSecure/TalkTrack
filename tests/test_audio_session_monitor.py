"""Tests for AudioSessionMonitor."""
import unittest
from unittest.mock import patch, MagicMock


class TestGetActiveAudioApps(unittest.TestCase):

    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_returns_empty_list_when_no_sessions(self, mock_au):
        mock_au.GetAllSessions.return_value = []
        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        self.assertEqual(result, [])

    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_returns_apps_with_valid_processes(self, mock_au):
        mock_session = MagicMock()
        mock_session.Process = MagicMock()
        mock_session.Process.name.return_value = "Teams.exe"
        mock_session.Process.pid = 12345
        mock_session.ProcessId = 12345

        mock_au.GetAllSessions.return_value = [mock_session]

        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Microsoft Teams")
        self.assertEqual(result[0]["pid"], 12345)

    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_skips_sessions_without_process(self, mock_au):
        mock_session = MagicMock()
        mock_session.Process = None
        mock_session.ProcessId = 0

        mock_au.GetAllSessions.return_value = [mock_session]

        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        self.assertEqual(result, [])

    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_deduplicates_by_pid(self, mock_au):
        session1 = MagicMock()
        session1.Process = MagicMock()
        session1.Process.name.return_value = "chrome.exe"
        session1.Process.pid = 100
        session1.ProcessId = 100

        session2 = MagicMock()
        session2.Process = MagicMock()
        session2.Process.name.return_value = "chrome.exe"
        session2.Process.pid = 100
        session2.ProcessId = 100

        mock_au.GetAllSessions.return_value = [session1, session2]

        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        self.assertEqual(len(result), 1)

    @patch("app.utils.audio_session_monitor.AudioUtilities")
    def test_strips_exe_extension_from_name(self, mock_au):
        mock_session = MagicMock()
        mock_session.Process = MagicMock()
        mock_session.Process.name.return_value = "Spotify.exe"
        mock_session.Process.pid = 999
        mock_session.ProcessId = 999

        mock_au.GetAllSessions.return_value = [mock_session]

        from app.utils.audio_session_monitor import get_active_audio_apps
        result = get_active_audio_apps()
        self.assertEqual(result[0]["name"], "Spotify")


if __name__ == "__main__":
    unittest.main()
