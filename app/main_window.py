import json
import sys
import webbrowser
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTabWidget, QMenuBar, QStatusBar, QMessageBox, QLabel
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction

from app.utils.config import Config
from app.recording.recorder import Recorder, RecordingState
from app.transcription.transcriber import TranscriptionWorker, TranscriptResult
from app.transcription.diarizer import DiarizationWorker, SimpleDiarizer
from app.ui.recording_controls import RecordingControls
from app.ui.source_selector import SourceSelector
from app.ui.transcript_viewer import TranscriptViewer
from app.ui.notes_panel import NotesPanel
from app.ui.recordings_list import RecordingsList
from app.ui.settings_dialog import SettingsDialog
from app.ui.status_panel import SystemStatusDialog
from app.ui.recording_header import RecordingHeader
from app.ui.waveform_display import WaveformDisplay
from app.ui.about_dialog import AboutDialog, BMAC_URL
from app.ui.summary_panel import SummaryPanel
from app.ui.action_items_panel import ActionItemsPanel
from app.ui.chat_panel import ChatPanel
from app.ai.chat import build_chat_context


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = Config()
        self.recorder = Recorder(self.config)
        self._current_session = None
        self._transcription_worker = None
        self._diarization_worker = None

        self.setWindowTitle("TalkTrack - Call Recorder & Transcriber")
        self.setMinimumSize(1000, 700)
        self.resize(1260, 800)

        self._setup_menu()
        self._setup_ui()
        self._setup_statusbar()
        self._connect_signals()

        QTimer.singleShot(500, self._check_startup_status)

    def _setup_menu(self):
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        settings_action = QAction("&Settings...", self)
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()

        open_recordings_action = QAction("&Open Recordings Folder", self)
        open_recordings_action.triggered.connect(self._open_recordings_folder)
        file_menu.addAction(open_recordings_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        status_action = QAction("&System Status...", self)
        status_action.triggered.connect(self._show_system_status)
        help_menu.addAction(status_action)

        diarization_setup_action = QAction("&Diarization Setup...", self)
        diarization_setup_action.triggered.connect(self._show_diarization_setup)
        help_menu.addAction(diarization_setup_action)

        help_menu.addSeparator()

        log_action = QAction("Open &Log File", self)
        log_action.triggered.connect(self._open_log_file)
        help_menu.addAction(log_action)

        report_action = QAction("&Report a Bug...", self)
        report_action.triggered.connect(self._report_bug)
        help_menu.addAction(report_action)

        help_menu.addSeparator()

        support_action = QAction("Support TalkTrack", self)
        support_action.triggered.connect(lambda: webbrowser.open(BMAC_URL))
        help_menu.addAction(support_action)

        help_menu.addSeparator()

        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # Main splitter: left (controls) | right (tabs)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel: controls at top, sources collapsible, recordings below
        left_panel = QWidget()
        left_panel.setMaximumWidth(385)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)

        # Recording controls (buttons row + timer/meters row)
        self.recording_controls = RecordingControls()
        left_layout.addWidget(self.recording_controls)

        # Waveform display (hidden until recording starts)
        self.waveform = WaveformDisplay(
            seconds=5,
            sample_rate=self.config.get("audio", "sample_rate"),
        )
        left_layout.addWidget(self.waveform)

        # Audio sources (collapsible)
        self.source_selector = SourceSelector()
        left_layout.addWidget(self.source_selector, 1)

        # Recordings list
        recordings_dir = self.config.get("output", "directory")
        self.recordings_list = RecordingsList(recordings_dir)
        left_layout.addWidget(self.recordings_list, 1)

        splitter.addWidget(left_panel)

        # Right panel: tabs for transcript and notes
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)

        # Recording header (above tabs)
        self.recording_header = RecordingHeader()
        right_layout.addWidget(self.recording_header)

        self.tabs = QTabWidget()

        # Transcript tab
        self.transcript_viewer = TranscriptViewer()
        self.tabs.addTab(self.transcript_viewer, "Transcript")

        # Notes tab
        self.notes_panel = NotesPanel()
        self.tabs.addTab(self.notes_panel, "Notes")

        # Summary tab
        self.summary_panel = SummaryPanel()
        self.tabs.addTab(self.summary_panel, "Summary")

        # Action Items tab
        self.action_items_panel = ActionItemsPanel()
        self.tabs.addTab(self.action_items_panel, "Action Items")

        # Chat tab
        self.chat_panel = ChatPanel()
        self.tabs.addTab(self.chat_panel, "Chat")

        right_layout.addWidget(self.tabs)
        splitter.addWidget(right_panel)

        splitter.setSizes([275, 960])
        main_layout.addWidget(splitter)

    def _setup_statusbar(self):
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.status_label = QLabel("Ready")
        self.statusbar.addWidget(self.status_label)

    def _connect_signals(self):
        # Recording controls
        self.recording_controls.record_clicked.connect(self._start_recording)
        self.recording_controls.pause_clicked.connect(self._toggle_pause)
        self.recording_controls.stop_clicked.connect(self._stop_recording)

        # Recorder signals
        self.recorder.state_changed.connect(self._on_state_changed)
        self.recorder.time_updated.connect(self.recording_controls.update_time)
        self.recorder.recording_finished.connect(self._on_recording_finished)
        self.recorder.error_occurred.connect(self._on_error)
        self.recorder.mic_level.connect(self.recording_controls.update_mic_level)
        self.recorder.mic_level.connect(self.waveform.append_audio)
        self.recorder.system_level.connect(self.recording_controls.update_system_level)

        # Transcript
        self.transcript_viewer.transcribe_requested.connect(self._start_transcription)

        # Recordings list
        self.recordings_list.recording_selected.connect(self._on_recording_selected)
        self.recordings_list.search_result_selected.connect(self._on_search_result_selected)

        # Auto-stop when call ends
        self.source_selector.apps_went_inactive.connect(self._on_apps_went_inactive)

        # Recording header
        self.recording_header.name_changed.connect(self._on_recording_renamed)

        # Transcript editing
        self.transcript_viewer.transcript_changed.connect(self._save_transcript)
        self.transcript_viewer.speaker_names_changed.connect(self._save_speaker_names)

        # Summary / action items
        self.summary_panel.regenerate_requested.connect(self._regenerate_summary)
        self.action_items_panel.regenerate_requested.connect(self._regenerate_summary)

    def _start_recording(self):
        mic = self.source_selector.get_selected_mic()
        capture_mode = self.source_selector.get_capture_mode()
        app_pids = self.source_selector.get_selected_app_pids()
        loopback = self.source_selector.get_selected_loopback()

        # Validate: need at least one audio source
        if mic is None and loopback is None and not app_pids:
            QMessageBox.warning(
                self, "No Audio Source",
                "Please select at least one audio source "
                "(microphone, system audio, or app)."
            )
            return

        # Validate: per-app mode needs at least one app checked
        if capture_mode == "per_app" and not app_pids:
            QMessageBox.warning(
                self, "No Apps Selected",
                "Select at least one app to capture, "
                "or switch to 'Capture all system audio' mode."
            )
            return

        self.recorder.start_recording(
            mic_device=mic,
            loopback_device=loopback,
            capture_mode=capture_mode,
            app_pids=app_pids,
        )
        self.notes_panel.set_recording_start(datetime.now())
        self.chat_panel.clear_chat()
        self.status_label.setText("Recording...")

    def _toggle_pause(self):
        if self.recorder.state == RecordingState.RECORDING:
            self.recorder.pause_recording()
            self.status_label.setText("Paused")
        elif self.recorder.state == RecordingState.PAUSED:
            self.recorder.resume_recording()
            self.status_label.setText("Recording...")

    def _stop_recording(self):
        self.recorder.stop_recording()
        self.status_label.setText("Stopping...")

    def _on_apps_went_inactive(self):
        """Auto-stop recording when all selected apps leave their call."""
        if self.recorder.state in (RecordingState.RECORDING, RecordingState.PAUSED):
            if self.source_selector.is_per_app_mode():
                self.status_label.setText("Call ended — stopping recording...")
                self.recorder.stop_recording()

    def _on_state_changed(self, state):
        self.recording_controls.set_state(state)
        self.source_selector.set_enabled(state == RecordingState.IDLE)

        if state == RecordingState.RECORDING:
            if not self.waveform.isVisible():
                self.waveform.start()
            else:
                self.waveform._paint_timer.start()
        elif state == RecordingState.PAUSED:
            self.waveform._paint_timer.stop()
        elif state == RecordingState.IDLE:
            self.waveform.stop()
            self.recording_controls.reset_timer()
            self.recording_controls.reset_levels()

    def _on_recording_finished(self, session):
        self._current_session = session
        self.status_label.setText("Recording saved.")

        # Set up transcript viewer
        audio_files = session.get("audio_files", {})
        combined = audio_files.get("combined")
        system = audio_files.get("system")
        mic = audio_files.get("mic")

        audio_for_transcript = combined or system or mic
        self.transcript_viewer.set_audio_path(audio_for_transcript)

        # Save notes
        self.notes_panel.set_session_dir(session["directory"])
        self.notes_panel.save_notes()

        # Refresh recordings list
        self.recordings_list.refresh()

        # Switch to transcript tab
        self.tabs.setCurrentWidget(self.transcript_viewer)

        # Update recording header
        self.recording_header.set_recording(session)

        # Auto-start transcription if audio available
        if audio_for_transcript:
            self._start_transcription(audio_for_transcript)

    def _start_transcription(self, audio_path):
        if self._transcription_worker and self._transcription_worker.isRunning():
            return

        model_size = self.config.get("transcription", "model_size")
        language = self.config.get("transcription", "language")
        device = self.config.get("transcription", "device")

        self._transcription_worker = TranscriptionWorker(
            audio_path=audio_path,
            model_size=model_size,
            language=language,
            device=device,
        )
        self._transcription_worker.progress.connect(self._on_transcription_progress)
        self._transcription_worker.finished.connect(self._on_transcription_finished)
        self._transcription_worker.error.connect(self._on_transcription_error)
        self._transcription_worker.start()

        self.transcript_viewer.show_progress("Starting transcription...")
        self.status_label.setText("Transcribing...")

    def _on_transcription_progress(self, message):
        self.transcript_viewer.show_progress(message)
        self.status_label.setText(message)

    def _on_transcription_finished(self, result):
        diarization_enabled = self.config.get("diarization", "enabled")
        hf_token = self.config.get("diarization", "hf_token")

        if diarization_enabled and hf_token:
            # Run full diarization with pyannote
            self._start_diarization(result)
        elif self._current_session:
            # Try simple channel-based diarization
            audio_files = self._current_session.get("audio_files", {})
            mic_path = audio_files.get("mic")
            sys_path = audio_files.get("system")

            if mic_path and sys_path:
                try:
                    diarizer = SimpleDiarizer(mic_path, sys_path)
                    result = diarizer.diarize(result)
                except Exception as e:
                    print(f"Simple diarization failed: {e}")

            self._display_final_transcript(result)
        else:
            self._display_final_transcript(result)

    def _start_diarization(self, transcript_result):
        if self._diarization_worker and self._diarization_worker.isRunning():
            return

        audio_files = self._current_session.get("audio_files", {}) if self._current_session else {}
        audio_path = audio_files.get("combined") or audio_files.get("system") or audio_files.get("mic")

        if not audio_path:
            self._display_final_transcript(transcript_result)
            return

        hf_token = self.config.get("diarization", "hf_token")
        min_speakers = self.config.get("diarization", "min_speakers")
        max_speakers = self.config.get("diarization", "max_speakers")

        self._diarization_worker = DiarizationWorker(
            audio_path=audio_path,
            transcript_result=transcript_result,
            hf_token=hf_token,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
        )
        self._diarization_worker.progress.connect(self._on_transcription_progress)
        self._diarization_worker.finished.connect(self._display_final_transcript)
        self._diarization_worker.error.connect(self._on_diarization_error)
        self._diarization_worker.start()

        self.transcript_viewer.show_progress("Running speaker diarization...")

    def _on_diarization_error(self, error_msg):
        self.status_label.setText("Diarization failed - showing transcript without speakers")
        # Still show the transcript without speaker labels
        if self._transcription_worker:
            # Display whatever we have
            self.transcript_viewer.hide_progress()
        QMessageBox.warning(self, "Diarization Error", error_msg)

    def _display_final_transcript(self, result):
        self.transcript_viewer.hide_progress()

        # Load speaker names if available
        speaker_names = {}
        if self._current_session:
            names_path = Path(self._current_session["directory"]) / "speaker_names.json"
            if names_path.exists():
                try:
                    with open(names_path, "r", encoding="utf-8") as f:
                        speaker_names = json.load(f)
                except (json.JSONDecodeError, OSError):
                    pass

        self.transcript_viewer.display_transcript(result, speaker_names=speaker_names)
        self.status_label.setText("Transcription complete.")

        # Update recording header with speaker count
        if self._current_session:
            self.recording_header.set_recording(
                self._current_session,
                speaker_count=self.transcript_viewer.get_speaker_count()
            )

        # Save transcript
        self._save_transcript()

        # Auto-summarize if AI provider configured
        self._transcript = result
        self._maybe_auto_summarize()

        # Update chat panel context
        self._update_chat_context()

    def _on_transcription_error(self, error_msg):
        self.transcript_viewer.hide_progress()
        self.status_label.setText("Transcription failed.")
        QMessageBox.warning(self, "Transcription Error", error_msg)

    def _on_recording_selected(self, metadata):
        """Load a past recording for viewing/transcription."""
        self._current_session = metadata

        audio_files = metadata.get("audio_files", {})
        audio_path = audio_files.get("combined") or audio_files.get("system") or audio_files.get("mic")
        self.transcript_viewer.set_audio_path(audio_path)

        # Load speaker names
        speaker_names = {}
        names_path = Path(metadata["directory"]) / "speaker_names.json"
        if names_path.exists():
            try:
                with open(names_path, "r", encoding="utf-8") as f:
                    speaker_names = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        # Load existing transcript if available
        transcript_path = Path(metadata["directory"]) / "transcript.json"
        if transcript_path.exists():
            try:
                with open(transcript_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                from app.transcription.transcriber import TranscriptSegment
                result = TranscriptResult(
                    segments=[TranscriptSegment.from_dict(s) for s in data["segments"]],
                    language=data.get("language", ""),
                    duration=data.get("duration", 0),
                )
                self.transcript_viewer.display_transcript(result, speaker_names=speaker_names)
                self._transcript = result
            except Exception as e:
                print(f"[MainWindow] Failed to load transcript: {e}")

        # Update recording header
        self.recording_header.set_recording(
            metadata,
            speaker_count=self.transcript_viewer.get_speaker_count()
        )

        # Load notes
        self.notes_panel.set_session_dir(metadata["directory"])

        # Load saved summary and action items
        session_dir = Path(metadata["directory"])
        summary_path = session_dir / "summary.md"
        if summary_path.exists():
            try:
                with open(summary_path, "r", encoding="utf-8") as f:
                    self.summary_panel.set_summary(f.read())
            except OSError:
                pass

        actions_path = session_dir / "action_items.json"
        if actions_path.exists():
            try:
                with open(actions_path, "r", encoding="utf-8") as f:
                    self.action_items_panel.set_items(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass

        # Update chat panel context for loaded recording
        self.chat_panel.set_session_dir(metadata["directory"])
        try:
            from app.ai.provider_factory import create_provider
            ai_config = self.config.data.get("ai", {})
            provider = create_provider(ai_config)
            self.chat_panel.set_provider(provider)
        except Exception:
            self.chat_panel.set_provider(None)

        if hasattr(self, '_transcript') and self._transcript is not None:
            self._update_chat_context()

        # Switch to transcript tab
        self.tabs.setCurrentWidget(self.transcript_viewer)

    def _on_search_result_selected(self, recording_id, timestamp):
        """Load a recording from a search result."""
        recordings_dir = Path(self.config.get("output", "directory"))
        rec_dir = recordings_dir / recording_id
        meta_path = rec_dir / "metadata.json"
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                self._on_recording_selected(metadata)
            except (json.JSONDecodeError, OSError) as e:
                print(f"[MainWindow] Failed to load search result: {e}")

    def _save_transcript(self):
        """Save current transcript to session directory."""
        if not self._current_session or not self.transcript_viewer._transcript:
            return
        result = self.transcript_viewer._transcript
        names = self.transcript_viewer._speaker_names

        transcript_path = Path(self._current_session["directory"]) / "transcript.json"
        with open(transcript_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(speaker_names=names), f, indent=2, ensure_ascii=False)

        txt_path = Path(self._current_session["directory"]) / "transcript.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(result.to_text(speaker_names=names))

        self.recordings_list.refresh()

    def _save_speaker_names(self, names):
        """Save speaker names to session directory."""
        if not self._current_session:
            return
        names_path = Path(self._current_session["directory"]) / "speaker_names.json"
        with open(names_path, "w", encoding="utf-8") as f:
            json.dump(names, f, indent=2, ensure_ascii=False)

        # Also re-save transcript with updated names
        self._save_transcript()

    def _on_recording_renamed(self, new_name):
        """Handle recording rename from RecordingHeader."""
        if not self._current_session:
            return
        self._current_session["name"] = new_name

        # Update metadata.json
        meta_path = Path(self._current_session["directory"]) / "metadata.json"
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                metadata["name"] = new_name
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, OSError) as e:
                print(f"Failed to save recording name: {e}")

        self.recordings_list.refresh()

    def _on_error(self, error_msg):
        self.status_label.setText(f"Error: {error_msg}")
        QMessageBox.critical(self, "Error", error_msg)

    def _open_settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec():
            # Update recordings list with potentially new directory
            self.recordings_list.recordings_dir = Path(self.config.get("output", "directory"))
            self.recordings_list.refresh()

    def _open_recordings_folder(self):
        import os
        recordings_dir = self.config.get("output", "directory")
        os.makedirs(recordings_dir, exist_ok=True)
        os.startfile(recordings_dir)

    def _show_system_status(self):
        dialog = SystemStatusDialog(self.config, self)
        dialog.exec()

    def _show_diarization_setup(self):
        from app.ui.diarization_setup import DiarizationSetupWizard
        wizard = DiarizationSetupWizard(self.config, self)
        wizard.exec()

    def _check_startup_status(self):
        # Show diarization setup wizard first if no HF token configured
        hf_token = self.config.get("diarization", "hf_token")
        if not hf_token:
            self._show_diarization_setup()

        if SystemStatusDialog.should_show_on_startup(self.config):
            QTimer.singleShot(300, self._show_system_status)

    def _open_log_file(self):
        import os
        from main import get_log_file
        log_path = get_log_file()
        if log_path.exists():
            os.startfile(str(log_path))
        else:
            QMessageBox.information(self, "Log File", "No log file found yet.")

    def _report_bug(self):
        from main import build_bug_report_url
        webbrowser.open(build_bug_report_url())

    def _show_about(self):
        dialog = AboutDialog(self)
        dialog.exec()

    def _update_chat_context(self):
        if self._transcript:
            speaker_names = getattr(self, '_speaker_names', {})
            if not speaker_names:
                speaker_names = self.transcript_viewer._speaker_names
            context = build_chat_context(self._transcript.segments, speaker_names)
            self.chat_panel.set_context(context)

        if self._current_session:
            self.chat_panel.set_session_dir(self._current_session["directory"])

        # Set provider
        try:
            from app.ai.provider_factory import create_provider
            ai_config = self.config.data.get("ai", {})
            provider = create_provider(ai_config)
            self.chat_panel.set_provider(provider)
        except Exception:
            self.chat_panel.set_provider(None)

    def _maybe_auto_summarize(self):
        if not self.config.get("ai", "auto_summarize"):
            return
        if self.config.get("ai", "provider") == "none":
            return
        if not getattr(self, '_transcript', None):
            return
        self._run_summarize()

    def _regenerate_summary(self):
        if not getattr(self, '_transcript', None):
            return
        self._run_summarize()

    def _run_summarize(self):
        from app.ai.summarizer import build_summary_prompt, build_action_items_prompt, parse_action_items
        from app.ai.provider_factory import create_provider
        from PyQt6.QtCore import QThread, pyqtSignal

        ai_config = self.config.data.get("ai", {})
        try:
            provider = create_provider(ai_config)
        except Exception:
            return
        if provider is None:
            return

        self.summary_panel.set_loading()
        self.action_items_panel.set_loading()

        class SummarizeWorker(QThread):
            summary_ready = pyqtSignal(str)
            actions_ready = pyqtSignal(list)
            error = pyqtSignal(str)

            def __init__(self, provider, segments, speaker_names):
                super().__init__()
                self._provider = provider
                self._segments = segments
                self._names = speaker_names

            def run(self):
                try:
                    summary_prompt = build_summary_prompt(self._segments, self._names)
                    summary = self._provider.complete(summary_prompt)
                    self.summary_ready.emit(summary)

                    actions_prompt = build_action_items_prompt(self._segments, self._names)
                    actions_response = self._provider.complete(actions_prompt)
                    actions = parse_action_items(actions_response)
                    self.actions_ready.emit(actions)
                except Exception as e:
                    self.error.emit(str(e))

        speaker_names = self.transcript_viewer._speaker_names
        self._summarize_worker = SummarizeWorker(provider, self._transcript.segments, speaker_names)
        self._summarize_worker.summary_ready.connect(self._on_summary_ready)
        self._summarize_worker.actions_ready.connect(self._on_actions_ready)
        self._summarize_worker.error.connect(lambda e: self.status_label.setText(f"AI error: {e}"))
        self._summarize_worker.start()

    def _on_summary_ready(self, summary):
        self.summary_panel.set_summary(summary)
        if self._current_session:
            path = Path(self._current_session["directory"]) / "summary.md"
            with open(path, "w", encoding="utf-8") as f:
                f.write(summary)

    def _on_actions_ready(self, items):
        self.action_items_panel.set_items(items)
        if self._current_session:
            path = Path(self._current_session["directory"]) / "action_items.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(items, f, indent=2)

    def closeEvent(self, event):
        if self.recorder.state != RecordingState.IDLE:
            reply = QMessageBox.question(
                self,
                "Recording in Progress",
                "A recording is in progress. Stop and save before exiting?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.recorder.stop_recording()
                event.accept()
            elif reply == QMessageBox.StandardButton.No:
                event.accept()
            else:
                event.ignore()
                return

        self.config.save()
        event.accept()
