# tests/test_live_transcription_window.py
"""MainWindow's side of transcribing while recording (#139).

MainWindow is never constructed: methods run against a stub self, and
LiveTranscriptionWorker/TranscriptionWorker are patched with autospec (their
pyqtSignal attributes are added by hand, as autospec cannot see them).
"""
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from app.recording.recorder import RecordingState


def _config(overrides=None):
    values = {
        ("transcription", "live"): True,
        ("transcription", "device"): "intel_gpu",
        ("transcription", "model_size"): "large-v3-turbo",
        ("transcription", "language"): "pt",
        ("transcription", "batch_size"): 1,
        ("general", "auto_transcribe"): True,
    }
    values.update(overrides or {})
    config = MagicMock()
    config.get.side_effect = lambda *keys: values.get(keys)
    return config


def _recording_stub(config=None, writers=("mic", "system")):
    stub = MagicMock()
    stub.config = config or _config()
    stub._live_workers = {}
    stub.recorder.state = RecordingState.RECORDING
    stub.recorder._current_session = {"directory": "D:/rec/recording_1"}
    stub.recorder._capture._writers = {
        key: types.SimpleNamespace(path=Path(f"D:/rec/recording_1/{key}.wav")) for key in writers
    }
    return stub


def _with_signals(mock_cls):
    for name in ("progress", "finished", "error", "cancelled", "fallback"):
        setattr(mock_cls.return_value, name, MagicMock())
    return mock_cls


class TestStartLiveTranscription(unittest.TestCase):
    def _start(self, stub):
        from app.main_window import MainWindow
        with patch("app.main_window.LiveTranscriptionWorker", autospec=True) as cls:
            MainWindow._start_live_transcription(stub)
        return cls

    def test_started_with_the_capture_track_files(self):
        stub = _recording_stub(writers=("mic", "mic2", "system"))
        cls = self._start(stub)
        args, kwargs = cls.call_args
        self.assertEqual(args[0], [Path("D:/rec/recording_1/mic.wav"), Path("D:/rec/recording_1/mic2.wav")])
        self.assertEqual(args[1], Path("D:/rec/recording_1/system.wav"))
        self.assertEqual(kwargs, {"model_size": "large-v3-turbo", "language": "pt"})
        worker = cls.return_value
        worker.start.assert_called_once()
        self.assertIs(stub._live_workers["D:/rec/recording_1"], worker)
        self.assertEqual(worker.session, stub.recorder._current_session)

    def test_mic_only_recording(self):
        cls = self._start(_recording_stub(writers=("mic",)))
        self.assertIsNone(cls.call_args.args[1])

    def test_not_started_unless_enabled_on_the_intel_gpu_with_auto_transcribe(self):
        for override in ({("transcription", "live"): False},
                         {("transcription", "device"): "cpu"},
                         {("general", "auto_transcribe"): False}):
            with self.subTest(override=override):
                stub = _recording_stub(_config(override))
                self._start(stub).assert_not_called()
                self.assertEqual(stub._live_workers, {})

    def test_not_started_when_recording_did_not_start(self):
        stub = _recording_stub()
        stub.recorder.state = RecordingState.IDLE
        self._start(stub).assert_not_called()

    def test_no_tracks_no_worker(self):
        self._start(_recording_stub(writers=())).assert_not_called()


class TestStopAndDiscard(unittest.TestCase):
    def test_stopping_state_stops_reading_before_files_are_mixed(self):
        from app.main_window import MainWindow
        stub = MagicMock()
        live = MagicMock()
        stub._live_workers = {"D:/rec/a": live}
        MainWindow._on_state_changed(stub, RecordingState.STOPPING)
        live.stop_reading.assert_called_once()

    def test_discarded_recording_cancels_its_worker(self):
        from app.main_window import MainWindow
        stub = MagicMock()
        live, other = MagicMock(), MagicMock()
        stub._live_workers = {"D:/rec/a": live, "D:/rec/b": other}
        stub.recorder._current_session = {"directory": "D:/rec/a"}
        MainWindow._on_recording_discarded(stub, 3.0)
        live.cancel.assert_called_once()
        other.cancel.assert_not_called()
        self.assertEqual(list(stub._live_workers), ["D:/rec/b"])


class TestTranscriptionJobUsesLiveWorker(unittest.TestCase):
    def _stub(self):
        stub = MagicMock()
        stub._closing = False
        stub._transcription_busy.return_value = False
        stub._pending_transcriptions = []
        return stub

    def test_usable_live_worker_takes_the_job(self):
        from app.main_window import MainWindow
        stub, live, session = self._stub(), MagicMock(), {"directory": "D:/rec/a"}
        live.finish.return_value = True
        stub._take_live_worker.return_value = live
        MainWindow._start_transcription(stub, "D:/rec/a/combined_audio.wav", session)
        live.finish.assert_called_once_with("D:/rec/a/combined_audio.wav")
        self.assertIs(stub._transcription_worker, live)
        live.finished.connect.assert_called_once_with(stub._on_transcription_finished)
        live.fallback.connect.assert_called_once_with(stub._on_live_transcription_fallback)
        stub._start_transcription_worker.assert_not_called()

    def test_refused_finish_transcribes_normally(self):
        from app.main_window import MainWindow
        stub, live, session = self._stub(), MagicMock(), {"directory": "D:/rec/a"}
        live.finish.return_value = False
        stub._take_live_worker.return_value = live
        MainWindow._start_transcription(stub, "a.wav", session)
        stub._start_transcription_worker.assert_called_once_with("a.wav", session)

    def test_busy_queue_keeps_the_live_worker_for_later(self):
        from app.main_window import MainWindow
        stub, session = self._stub(), {"directory": "D:/rec/a"}
        stub._transcription_busy.return_value = True
        MainWindow._start_transcription(stub, "a.wav", session)
        stub._take_live_worker.assert_not_called()
        self.assertEqual(stub._pending_transcriptions, [("a.wav", session)])

    def test_normal_worker_still_starts_without_live(self):
        from app.main_window import MainWindow
        stub = self._stub()
        stub.config = _config()
        with patch("app.main_window.TranscriptionWorker", autospec=True) as cls:
            _with_signals(cls)
            MainWindow._start_transcription_worker(stub, "a.wav", {"directory": "x"})
        cls.assert_called_once_with(audio_path="a.wav", model_size="large-v3-turbo",
                                    language="pt", device="intel_gpu", batch_size=1)
        cls.return_value.start.assert_called_once()


class TestTakeLiveWorker(unittest.TestCase):
    def _take(self, live, session={"directory": "D:/rec/a"}):
        from app.main_window import MainWindow
        stub = MagicMock()
        stub._live_workers = {"D:/rec/a": live} if live is not None else {}
        return MainWindow._take_live_worker(stub, session), stub

    def test_usable_running_worker_is_handed_over(self):
        live = MagicMock(usable=True, failed=None)
        live.isRunning.return_value = True
        taken, stub = self._take(live)
        self.assertIs(taken, live)
        self.assertEqual(stub._live_workers, {})

    def test_failed_worker_is_cancelled_and_dropped(self):
        live = MagicMock(usable=False, failed="DEVICE_LOST")
        taken, stub = self._take(live)
        self.assertIsNone(taken)
        live.cancel.assert_called_once()
        self.assertEqual(stub._live_workers, {})

    def test_other_recordings_have_none(self):
        self.assertIsNone(self._take(None)[0])
        self.assertIsNone(self._take(MagicMock(), session=None)[0])


class TestFallbackAndShutdown(unittest.TestCase):
    def test_fallback_transcribes_the_same_recording_normally(self):
        from app.main_window import MainWindow
        stub = MagicMock()
        stub._closing = False
        live = stub._transcription_worker
        live.audio_path, live.session = "a.wav", {"directory": "D:/rec/a"}
        with self.assertLogs("app.main_window", "WARNING"):
            MainWindow._on_live_transcription_fallback(stub, "DEVICE_LOST")
        live.wait.assert_called_once()
        stub._start_transcription_worker.assert_called_once_with("a.wav", {"directory": "D:/rec/a"})

    def test_shutdown_cancels_and_waits_for_live_workers(self):
        from app.main_window import MainWindow
        stub = MagicMock()
        stub._transcription_worker = None
        stub._diarization_worker = stub._simple_diarize_worker = stub._summarize_worker = None
        stub.chat_panel.active_worker.return_value = None
        stub.recordings_list.active_search_worker.return_value = None
        live = MagicMock()
        live.isRunning.return_value = True
        live.wait.return_value = True
        stub._live_workers = {"D:/rec/a": live}
        MainWindow._shutdown_workers(stub)
        self.assertEqual(live.mock_calls[:1], [call.cancel()])
        live.wait.assert_called_once_with(5000)
        live.terminate.assert_not_called()
        self.assertEqual(stub._live_workers, {})


class TestRecordingNotTranscribed(unittest.TestCase):
    def _finish(self, duration, auto_transcribe=True):
        from app.main_window import MainWindow
        stub = MagicMock()
        stub.config = _config({("transcription", "min_duration"): 10,
                                 ("general", "auto_transcribe"): auto_transcribe})
        live = MagicMock()
        stub._live_workers = {"D:/rec/a": live}
        session = {"directory": "D:/rec/a", "duration": duration,
                   "audio_files": {"combined": "D:/rec/a/combined_audio.wav"}}
        MainWindow._on_recording_finished(stub, session)
        return stub, live

    def test_too_short_cancels_live_worker(self):
        stub, live = self._finish(duration=4)
        live.cancel.assert_called_once()
        stub._start_transcription.assert_not_called()

    def test_auto_transcribe_off_cancels_live_worker(self):
        _, live = self._finish(duration=60, auto_transcribe=False)
        live.cancel.assert_called_once()

    def test_transcribed_recording_keeps_it_for_the_job(self):
        stub, live = self._finish(duration=60)
        stub._start_transcription.assert_called_once()
        live.cancel.assert_not_called()
        self.assertIn("D:/rec/a", stub._live_workers)


if __name__ == "__main__":
    unittest.main()
