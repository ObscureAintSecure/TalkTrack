# tests/test_transcript_preview.py
"""The transcript is shown while its speakers are still being identified.

Diarization runs about as long as the recording on a CPU, and the transcript
used to wait for it. MainWindow is never constructed: methods run against a
stub self, and DiarizationWorker is patched with autospec so a constructor
signature change fails here instead of being absorbed by a mock.
"""
import unittest
from unittest.mock import MagicMock, call, patch

from app.transcription.transcriber import TranscriptResult, TranscriptSegment


def _transcript(*texts):
    return TranscriptResult(segments=[
        TranscriptSegment(start=float(i), end=i + 0.9, text=t) for i, t in enumerate(texts)
    ])


def _session(directory="D:/rec/recording_1"):
    return {"directory": directory, "audio_files": {"combined": f"{directory}/combined_audio.wav"}}


class TestStartDiarizationShowsPreview(unittest.TestCase):
    def _stub(self):
        stub = MagicMock()
        stub._diarization_worker = None
        stub.config.get.return_value = None
        return stub

    def test_preview_follows_worker_start(self):
        from app.main_window import MainWindow
        stub, result, session = self._stub(), _transcript("olá"), _session()
        with patch("app.main_window.DiarizationWorker", autospec=True) as worker_cls:
            for signal in ("progress", "finished", "error"):   # pyqtSignal: no autospec
                setattr(worker_cls.return_value, signal, MagicMock())
            MainWindow._start_diarization(stub, result, session)
        worker_cls.return_value.start.assert_called_once()
        stub._show_transcript_preview.assert_called_once_with(result, session)
        stub._display_final_transcript.assert_not_called()

    def test_no_audio_displays_final_without_preview(self):
        from app.main_window import MainWindow
        stub, result = self._stub(), _transcript("olá")
        with patch("app.main_window.DiarizationWorker", autospec=True) as worker_cls:
            MainWindow._start_diarization(stub, result, {"directory": "x", "audio_files": {}})
        worker_cls.assert_not_called()
        stub._show_transcript_preview.assert_not_called()
        stub._display_final_transcript.assert_called_once()


class TestShowTranscriptPreview(unittest.TestCase):
    def test_displayed_session_is_rendered_and_saved(self):
        from app.main_window import MainWindow
        stub, result, session = MagicMock(), _transcript("olá"), _session()
        stub._is_current_session.return_value = True
        MainWindow._show_transcript_preview(stub, result, session)
        stub.transcript_viewer.display_transcript.assert_called_once_with(result)
        stub._save_transcript.assert_called_once()
        stub._write_transcript_for_session.assert_not_called()

    def test_preview_leaves_progress_summary_and_queue_alone(self):
        from app.main_window import MainWindow
        stub = MagicMock()
        stub._is_current_session.return_value = True
        MainWindow._show_transcript_preview(stub, _transcript("olá"), _session())
        stub.transcript_viewer.hide_progress.assert_not_called()
        stub._maybe_auto_summarize.assert_not_called()
        stub._process_pending_transcriptions.assert_not_called()

    def test_other_session_is_saved_to_its_own_directory(self):
        from app.main_window import MainWindow
        stub, result, session = MagicMock(), _transcript("olá"), _session()
        stub._is_current_session.return_value = False
        MainWindow._show_transcript_preview(stub, result, session)
        stub._write_transcript_for_session.assert_called_once_with(result, session)
        stub.transcript_viewer.display_transcript.assert_not_called()


class TestCarryOverEdits(unittest.TestCase):
    def _edited_copy(self, result, index, text):
        shown = TranscriptResult(segments=[
            TranscriptSegment.from_dict(s.to_dict()) for s in result.segments
        ])
        seg = shown.segments[index]
        seg.original_text, seg.text = seg.text, text
        return shown

    def test_edit_on_reloaded_preview_reaches_final(self):
        from app.main_window import MainWindow
        result = _transcript("um", "dois", "três")
        result.segments[1].speaker = "SPEAKER_00"
        shown = self._edited_copy(result, 1, "DOIS")
        MainWindow._carry_over_edits(shown, result)
        self.assertEqual(result.segments[1].text, "DOIS")
        self.assertEqual(result.segments[1].original_text, "dois")
        self.assertEqual(result.segments[1].speaker, "SPEAKER_00")
        self.assertEqual([s.text for s in result.segments], ["um", "DOIS", "três"])

    def test_same_object_is_left_alone(self):
        from app.main_window import MainWindow
        result = _transcript("um")
        MainWindow._carry_over_edits(result, result)
        self.assertEqual(result.segments[0].text, "um")

    def test_different_transcript_is_ignored(self):
        from app.main_window import MainWindow
        result = _transcript("um", "dois")
        shown = self._edited_copy(result, 0, "UM")
        shown.segments[1].end = 9.0
        MainWindow._carry_over_edits(shown, result)
        self.assertEqual(result.segments[0].text, "um")

    def test_different_length_is_ignored(self):
        from app.main_window import MainWindow
        result = _transcript("um", "dois")
        shown = self._edited_copy(_transcript("um"), 0, "UM")
        MainWindow._carry_over_edits(shown, result)
        self.assertEqual(result.segments[0].text, "um")

    def test_nothing_shown(self):
        from app.main_window import MainWindow
        result = _transcript("um")
        MainWindow._carry_over_edits(None, result)
        self.assertEqual(result.segments[0].text, "um")


class TestFinishDiarizedTranscript(unittest.TestCase):
    def _stub(self, current):
        stub = MagicMock()
        stub._is_current_session.return_value = current
        return stub

    def test_edits_carried_over_before_display(self):
        from app.main_window import MainWindow
        stub, result, session = self._stub(True), _transcript("olá"), _session()
        MainWindow._finish_diarized_transcript(stub, result, session)
        shown = stub.transcript_viewer._transcript
        self.assertEqual(stub.mock_calls[-2:], [
            call._carry_over_edits(shown, result),
            call._display_final_transcript(result, session),
        ])

    def test_other_session_skips_the_viewer(self):
        from app.main_window import MainWindow
        stub, result, session = self._stub(False), _transcript("olá"), _session()
        MainWindow._finish_diarized_transcript(stub, result, session)
        stub._carry_over_edits.assert_not_called()
        stub._display_final_transcript.assert_called_once_with(result, session)

    def test_diarization_finished_goes_through_it(self):
        from app.main_window import MainWindow
        stub, result, session = self._stub(True), _transcript("olá"), _session()
        stub._diarization_worker.session = session
        MainWindow._on_diarization_finished(stub, result)
        stub._finish_diarized_transcript.assert_called_once_with(result, session)

    def test_diarization_error_goes_through_it(self):
        from app.main_window import MainWindow
        stub, result, session = self._stub(True), _transcript("olá"), _session()
        stub._diarization_worker.session = session
        stub._diarization_worker.transcript_result = result
        stub._is_hidden_to_tray.return_value = True
        MainWindow._on_diarization_error(stub, "boom")
        stub._finish_diarized_transcript.assert_called_once_with(result, session)


class TestReopenWhileDiarizing(unittest.TestCase):
    def _select(self, worker_session, running=True):
        from app.main_window import MainWindow
        stub = MagicMock()
        stub._diarization_worker.isRunning.return_value = running
        stub._diarization_worker.session = worker_session
        stub._is_current_session.side_effect = lambda s: s.get("directory") == "D:/rec/a"
        with patch("app.main_window.Path") as path:
            path.return_value.__truediv__.return_value.exists.return_value = False
            MainWindow._on_recording_selected(stub, {"directory": "D:/rec/a", "audio_files": {}})
        return stub

    def test_progress_shown_for_the_recording_being_diarized(self):
        stub = self._select({"directory": "D:/rec/a"})
        stub.transcript_viewer.show_progress.assert_called_once()

    def test_no_progress_for_another_recording(self):
        stub = self._select({"directory": "D:/rec/b"})
        stub.transcript_viewer.show_progress.assert_not_called()

    def test_no_progress_when_diarization_is_done(self):
        stub = self._select({"directory": "D:/rec/a"}, running=False)
        stub.transcript_viewer.show_progress.assert_not_called()


if __name__ == "__main__":
    unittest.main()
