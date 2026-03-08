"""Tests for SegmentPlayer audio clip playback."""
import unittest
from unittest.mock import patch, MagicMock
import numpy as np


class TestSegmentPlayer(unittest.TestCase):

    @patch("app.audio.segment_player.sf")
    @patch("app.audio.segment_player.sd")
    def test_play_segment_extracts_correct_samples(self, mock_sd, mock_sf):
        """Playing from 1.0s to 2.0s at 16000Hz should extract samples 16000-32000."""
        from app.audio.segment_player import SegmentPlayer

        audio_data = np.zeros(80000, dtype=np.float32)
        mock_sf.read.return_value = (audio_data, 16000)

        player = SegmentPlayer()
        player.play_segment("test.wav", 1.0, 2.0)

        mock_sd.play.assert_called_once()
        played_data = mock_sd.play.call_args[0][0]
        self.assertEqual(len(played_data), 16000)
        self.assertEqual(mock_sd.play.call_args[1]["samplerate"], 16000)

    @patch("app.audio.segment_player.sf")
    @patch("app.audio.segment_player.sd")
    def test_stop_calls_sounddevice_stop(self, mock_sd, mock_sf):
        from app.audio.segment_player import SegmentPlayer

        player = SegmentPlayer()
        player.stop()
        mock_sd.stop.assert_called_once()

    @patch("app.audio.segment_player.sf")
    @patch("app.audio.segment_player.sd")
    def test_play_segment_caches_audio_file(self, mock_sd, mock_sf):
        """Loading the same file twice should only call sf.read once."""
        from app.audio.segment_player import SegmentPlayer

        audio_data = np.zeros(80000, dtype=np.float32)
        mock_sf.read.return_value = (audio_data, 16000)

        player = SegmentPlayer()
        player.play_segment("test.wav", 0.0, 1.0)
        player.play_segment("test.wav", 1.0, 2.0)

        self.assertEqual(mock_sf.read.call_count, 1)

    @patch("app.audio.segment_player.sf")
    @patch("app.audio.segment_player.sd")
    def test_play_segment_stops_previous_before_playing(self, mock_sd, mock_sf):
        from app.audio.segment_player import SegmentPlayer

        audio_data = np.zeros(80000, dtype=np.float32)
        mock_sf.read.return_value = (audio_data, 16000)

        player = SegmentPlayer()
        player.play_segment("test.wav", 0.0, 1.0)
        player.play_segment("test.wav", 1.0, 2.0)

        # stop() called before each play
        self.assertEqual(mock_sd.stop.call_count, 2)

    @patch("app.audio.segment_player.sf")
    @patch("app.audio.segment_player.sd")
    def test_play_clamps_to_audio_length(self, mock_sd, mock_sf):
        """End time beyond audio length should clamp to end of file."""
        from app.audio.segment_player import SegmentPlayer

        audio_data = np.zeros(16000, dtype=np.float32)  # 1 second
        mock_sf.read.return_value = (audio_data, 16000)

        player = SegmentPlayer()
        player.play_segment("test.wav", 0.5, 5.0)

        played_data = mock_sd.play.call_args[0][0]
        self.assertEqual(len(played_data), 8000)  # only 0.5s available


if __name__ == "__main__":
    unittest.main()
