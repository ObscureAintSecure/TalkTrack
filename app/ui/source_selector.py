"""Audio source selection widget with per-app capture support."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel,
    QPushButton, QListWidget, QListWidgetItem,
    QRadioButton, QButtonGroup, QCheckBox, QFrame
)
from PyQt6.QtCore import pyqtSignal, QTimer, Qt

from app.utils.audio_devices import (
    get_input_devices, get_system_audio_devices,
    get_default_mic
)
from app.utils.platform_info import is_windows_11
from app.ui.collapsible_section import CollapsibleSection


# Apps that set AUDCLNT_STREAMFLAGS_EXCLUDE_FROM_PROCESS_LOOPBACK_CAPTURE
# on their call audio stream, making per-app loopback return silence
# during calls. Process-loopback captures non-call audio from these apps
# (chat chimes, notifications) but not the actual conversation.
# See docs/per-app-audio-capture.md for background.
CONFERENCING_APPS = {
    "Microsoft Teams",
    "Zoom",
    "Webex",
    "GoToMeeting",
    "Google Meet",
    "Discord",
}


def format_per_app_suffix(names):
    """Build the collapsed-title suffix for per-app capture mode.

    [] -> "(No apps selected)"
    [A] -> "(A)"
    [A, B] -> "(A, B)"
    [A, B, ...] -> "(A, B +N more)" where N = len - 2.
    """
    if not names:
        return "(No apps selected)"
    if len(names) <= 2:
        return f"({', '.join(names)})"
    return f"({names[0]}, {names[1]} +{len(names) - 2} more)"


def format_legacy_suffix(combo_text):
    """Build the collapsed-title suffix for legacy loopback mode.

    Strips the trailing " (WASAPI Loopback)" marker from the combo label.
    """
    wasapi_suffix = " (WASAPI Loopback)"
    text = combo_text
    if text.endswith(wasapi_suffix):
        text = text[: -len(wasapi_suffix)]
    return f"({text})"


class SourceSelector(QWidget):
    """Widget for selecting audio input sources.

    On Windows 11, shows a per-app audio picker alongside the legacy
    system audio dropdown. On Windows 10, shows only the legacy dropdown.
    """

    devices_changed = pyqtSignal()
    # Emitted when the user picks a different mic in the dropdown.
    # Payload is the new device index (or None for "don't record mic").
    # Not emitted during refresh_devices — signals are blocked there.
    mic_changed = pyqtSignal(object)
    output_changed = pyqtSignal(object)
    # Emitted when all checked apps go inactive during recording
    apps_went_inactive = pyqtSignal()
    # Emitted when a checked app becomes active (for auto-record)
    apps_became_active = pyqtSignal()

    _BASE_TITLE = "Audio Sources"

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self._config = config
        self._mic_devices = []
        self._loopback_devices = []
        self._win11 = is_windows_11()
        self._auto_refresh_timer = None
        self._had_active_apps = False
        self._capture_active = False
        self._setup_ui()
        self.loopback_combo.currentIndexChanged.connect(self._output_selected)
        self.refresh_devices()
        self._restore_capture_mode()
        self._update_section_title()

        if self._win11:
            self._start_auto_refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Collapsible audio sources section
        self._section = CollapsibleSection(self._BASE_TITLE)
        content = self._section.content_layout()

        # Microphone selector
        mic_row = QHBoxLayout()
        mic_label = QLabel("Microphone:")
        mic_label.setFixedWidth(95)
        mic_row.addWidget(mic_label)

        self.mic_combo = QComboBox()
        self.mic_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.mic_combo.currentIndexChanged.connect(self._save_mic_selection)
        mic_row.addWidget(self.mic_combo, 1)
        content.addLayout(mic_row)

        # Second microphone selector (hidden by default)
        self._mic2_row_widget = QWidget()
        mic2_row = QHBoxLayout(self._mic2_row_widget)
        mic2_row.setContentsMargins(0, 0, 0, 0)
        mic2_label = QLabel("Microphone 2:")
        mic2_label.setFixedWidth(95)
        mic2_row.addWidget(mic2_label)

        self.mic2_combo = QComboBox()
        self.mic2_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.mic2_combo.currentIndexChanged.connect(self._save_mic_selection)
        mic2_row.addWidget(self.mic2_combo, 1)
        content.addWidget(self._mic2_row_widget)

        mic_count = self._config.get("audio", "mic_count") if self._config else 1
        self._mic2_row_widget.setVisible(mic_count >= 2)

        # System audio section
        if self._win11:
            self._setup_per_app_ui(content)
        else:
            self._setup_legacy_ui(content)

        # Warning label for per-app capture failures
        self._capture_warning = QLabel("")
        self._capture_warning.setObjectName("captureWarning")
        self._capture_warning.setStyleSheet(
            "color: #f9e2af; font-size: 11px; padding: 2px 4px;"
        )
        self._capture_warning.setVisible(False)
        content.addWidget(self._capture_warning)

        layout.addWidget(self._section)

        # Refresh devices when the section is expanded (picks up any mic or
        # output device the user plugged in while the section was closed).
        self._section.toggled.connect(self._on_section_toggled)

        # Keep the collapsed title suffix in sync with selection state.
        self.loopback_combo.currentIndexChanged.connect(self._update_section_title)
        if self.app_list is not None:
            self.app_list.itemChanged.connect(self._update_section_title)

        # Start expanded by default
        self._section.set_expanded(True)

    def _setup_legacy_ui(self, parent_layout):
        """Original system audio dropdown (Win10 or fallback)."""
        sys_row = QHBoxLayout()
        sys_label = QLabel("System Audio:")
        sys_label.setFixedWidth(95)
        sys_row.addWidget(sys_label)

        self.loopback_combo = QComboBox()
        sys_row.addWidget(self.loopback_combo, 1)
        parent_layout.addLayout(sys_row)

        self.app_list = None
        self.mode_group = None

    def _setup_per_app_ui(self, parent_layout):
        """Per-app audio picker (Win11)."""
        self.mode_group = QButtonGroup(self)
        self.radio_per_app = QRadioButton("Selected apps")
        self.radio_per_app.setObjectName("captureMode")
        self.radio_per_app.setToolTip("Capture audio only from the apps checked below.")
        self.radio_legacy = QRadioButton("All system audio")
        self.radio_legacy.setObjectName("captureMode")
        self.radio_legacy.setToolTip("Capture all system audio output (WASAPI loopback).")
        self.mode_group.addButton(self.radio_per_app, 0)
        self.mode_group.addButton(self.radio_legacy, 1)
        self.radio_per_app.setChecked(True)
        self.mode_group.idToggled.connect(self._on_mode_changed)

        # Radios on a single row so they don't push the app list down
        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)
        mode_row.addWidget(self.radio_per_app, 1)
        mode_row.addWidget(self.radio_legacy, 1)
        parent_layout.addLayout(mode_row)

        # App list (checkable). Scrollbar shows automatically when the list
        # has more items than its visible area can fit.
        self.app_list = QListWidget()
        self.app_list.setObjectName("appAudioList")
        self.app_list.setMinimumHeight(120)
        self.app_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.app_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        parent_layout.addWidget(self.app_list, 1)

        # Warning shown when a conferencing app is checked in per-app mode.
        # Those apps set AUDCLNT_STREAMFLAGS_EXCLUDE_FROM_PROCESS_LOOPBACK_
        # CAPTURE on their call stream, so per-app loopback gets silence.
        # Legacy mode (device-level WASAPI tap) bypasses the opt-out.
        self.conferencing_warning = QLabel(
            "⚠ Teams / Zoom / WebEx block per-app recording. "
            "Switch to \"All system audio\" to capture calls."
        )
        self.conferencing_warning.setObjectName("conferencingWarning")
        self.conferencing_warning.setWordWrap(True)
        self.conferencing_warning.setStyleSheet(
            "QLabel#conferencingWarning {"
            " color: #f9e2af;"
            " background-color: #313244;"
            " border: 1px solid #f9e2af;"
            " border-radius: 4px;"
            " padding: 6px;"
            " font-size: 9pt;"
            "}"
        )
        self.conferencing_warning.setVisible(False)
        parent_layout.addWidget(self.conferencing_warning)

        # Hidden legacy combo for fallback
        self.loopback_combo = QComboBox()
        self.loopback_combo.setVisible(False)
        parent_layout.addWidget(self.loopback_combo)

    def _on_mode_changed(self, button_id, checked):
        if not checked:
            return
        if self.app_list is not None:
            is_per_app = button_id == 0
            self.app_list.setVisible(is_per_app)
            self.loopback_combo.setVisible(not is_per_app)
        self._update_section_title()

    def _on_section_toggled(self, expanded):
        if expanded:
            self.refresh_devices()
        self._update_section_title()

    def _selected_sources_text(self):
        """Build the ' (...)' suffix shown when the section is collapsed."""
        if self._win11 and self.is_per_app_mode():
            names = []
            if self.app_list is not None:
                for i in range(self.app_list.count()):
                    item = self.app_list.item(i)
                    if item.checkState() == Qt.CheckState.Checked:
                        names.append(item.text().split("  (")[0])
            return format_per_app_suffix(names)

        # Legacy loopback mode (Win10 or Win11 with "All system audio" radio)
        if self.loopback_combo.currentData() is None:
            return "(No system audio)"
        return format_legacy_suffix(self.loopback_combo.currentText())

    def _update_section_title(self):
        if self._section.is_expanded():
            self._section.set_title(self._BASE_TITLE)
        else:
            self._section.set_title(f"{self._BASE_TITLE} {self._selected_sources_text()}")
        self._update_conferencing_warning()

    def _update_conferencing_warning(self):
        """Show the opt-out warning only when a conferencing app is checked
        in per-app mode. Legacy (device-level loopback) works fine, so
        hide the warning there.
        """
        if not self._win11 or self.app_list is None:
            return
        if not hasattr(self, "conferencing_warning"):
            return
        show = False
        if self.get_capture_mode() == "per_app":
            for i in range(self.app_list.count()):
                item = self.app_list.item(i)
                if item.checkState() != Qt.CheckState.Checked:
                    continue
                # Strip the trailing "  (N processes)" / "  (not in call)"
                # suffix added at list-render time so the match keys on name only.
                label = item.text().split("  ")[0]
                if label in CONFERENCING_APPS:
                    show = True
                    break
        self.conferencing_warning.setVisible(show)

    def _start_auto_refresh(self):
        if self._auto_refresh_timer is None:
            self._auto_refresh_timer = QTimer(self)
            self._auto_refresh_timer.timeout.connect(self._refresh_app_list)
        self._auto_refresh_timer.start(3000)

    def _stop_auto_refresh(self):
        if self._auto_refresh_timer:
            self._auto_refresh_timer.stop()

    def set_recording_active(self, active):
        """Switch to faster polling (1s) during recording for quicker call-end detection."""
        if self._auto_refresh_timer and self._auto_refresh_timer.isActive():
            self._auto_refresh_timer.start(1000 if active else 3000)

    def _refresh_app_list(self):
        """Update the app list with currently active audio apps."""
        if self.app_list is None:
            return

        try:
            from app.utils.audio_session_monitor import get_active_audio_apps
            apps = get_active_audio_apps()
        except Exception as e:
            print(f"[SourceSelector] Error refreshing app list: {e}")
            return

        # Filter out hidden apps
        hidden = []
        if self._config:
            try:
                hidden = self._config.get("audio", "hidden_devices") or []
            except (KeyError, TypeError):
                pass
        if hidden:
            hidden_lower = [h.lower() for h in hidden]
            apps = [a for a in apps if not any(
                h in a["name"].lower() for h in hidden_lower
            )]

        # Remember which app names were checked (stable across PID changes)
        checked_names = set()
        for i in range(self.app_list.count()):
            item = self.app_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                checked_names.add(item.text().split("  (")[0])

        # On first load (empty list), seed from saved config
        if not checked_names and self._config:
            try:
                saved_apps = self._config.get("audio", "selected_apps")
                if saved_apps:
                    checked_names = set(saved_apps)
            except (KeyError, TypeError):
                pass

        self.app_list.clear()

        # Track whether any checked apps are still active
        any_checked_active = False

        for app in apps:
            if app.get("active", False):
                label = f"{app['name']}  ({len(app['pids'])} process{'es' if len(app['pids']) > 1 else ''})"
            else:
                label = f"{app['name']}  (not in call)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, app["pids"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if app["name"] in checked_names:
                item.setCheckState(Qt.CheckState.Checked)
                if app.get("active", False):
                    any_checked_active = True
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            self.app_list.addItem(item)

        if self.app_list.count() == 0:
            item = QListWidgetItem("No audio apps detected")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.app_list.addItem(item)

        # Detect transition: checked apps were active, now all inactive
        if checked_names and self._had_active_apps and not any_checked_active:
            self.apps_went_inactive.emit()
        # Detect transition: no checked apps were active, now at least one is
        if checked_names and not self._had_active_apps and any_checked_active:
            self.apps_became_active.emit()
        self._had_active_apps = any_checked_active
        self._update_section_title()

    def has_active_checked_apps(self):
        """Whether any checked app is currently reported as active.

        Reflects the most recent poll of get_active_audio_apps(). Used by
        the auto-record threshold to confirm sustained activity before
        starting a recording.
        """
        return bool(self._had_active_apps)

    def refresh_devices(self):
        if self._capture_active:
            return  # Re-enumeration must not change microphone selection mid-call.
        self.loopback_combo.blockSignals(True)
        # Block signals while rebuilding combos so clear/addItem don't
        # trigger _save_mic_selection with stale values
        self.mic_combo.blockSignals(True)
        self.mic2_combo.blockSignals(True)

        self.mic_combo.clear()

        # Get hidden device patterns from config
        hidden = []
        if self._config:
            try:
                hidden = self._config.get("audio", "hidden_devices") or []
            except (KeyError, TypeError):
                pass

        # Microphone devices
        self._mic_devices = get_input_devices(hidden_devices=hidden)
        self.mic_combo.addItem("(None - don't record microphone)", None)
        default_mic = get_default_mic()
        default_mic_idx = 0

        for i, dev in enumerate(self._mic_devices):
            label = f"{dev['name']} ({dev['hostapi']})"
            self.mic_combo.addItem(label, dev["index"])
            if dev["index"] == default_mic:
                default_mic_idx = i + 1

        # Restore saved mic or fall back to system default
        last_mic = ""
        if self._config:
            try:
                last_mic = self._config.get("audio", "last_mic") or ""
            except (KeyError, TypeError):
                pass

        if last_mic:
            idx = self.mic_combo.findText(last_mic)
            if idx >= 0:
                self.mic_combo.setCurrentIndex(idx)
            elif default_mic_idx > 0:
                self.mic_combo.setCurrentIndex(default_mic_idx)
        elif default_mic_idx > 0:
            self.mic_combo.setCurrentIndex(default_mic_idx)

        # Second microphone (same device list)
        self.mic2_combo.clear()
        self.mic2_combo.addItem("(None - don't record second mic)", None)
        for i, dev in enumerate(self._mic_devices):
            label = f"{dev['name']} ({dev['hostapi']})"
            self.mic2_combo.addItem(label, dev["index"])

        # Restore saved mic 2
        last_mic2 = ""
        if self._config:
            try:
                last_mic2 = self._config.get("audio", "last_mic2") or ""
            except (KeyError, TypeError):
                pass
        if last_mic2:
            idx = self.mic2_combo.findText(last_mic2)
            if idx >= 0:
                self.mic2_combo.setCurrentIndex(idx)

        self.mic_combo.blockSignals(False)
        self.mic2_combo.blockSignals(False)

        # System audio dropdown - always populated
        self.loopback_combo.clear()
        self._loopback_devices = get_system_audio_devices(hidden_devices=hidden)
        self.loopback_combo.addItem("(None - don't record system audio)", None)
        self.loopback_combo.addItem("Follow Windows default output", -1)
        for dev in self._loopback_devices:
            label = f"{dev['name']} (WASAPI Loopback)"
            self.loopback_combo.addItem(label, dev["index"])

        saved = self._config.data.get('audio', {}).get('last_system_output') if self._config else None
        if saved is None:
            self.loopback_combo.setCurrentIndex(1)
        elif saved == '__disabled__':
            self.loopback_combo.setCurrentIndex(0)
        else:
            idx = self.loopback_combo.findText(saved + ' (WASAPI Loopback)')
            if idx < 0:
                self.loopback_combo.addItem(saved + ' (unavailable)', saved)
                idx = self.loopback_combo.count() - 1
            self.loopback_combo.setCurrentIndex(idx)
        self.loopback_combo.blockSignals(False)

        # Refresh app list too
        if self._win11 and self.app_list is not None:
            self._refresh_app_list()

        self.devices_changed.emit()

    def get_selected_mic(self):
        return self.mic_combo.currentData()

    def get_selected_mic2(self):
        """Return second mic device index, or None if not enabled/selected."""
        if not self._mic2_row_widget.isVisible():
            return None
        return self.mic2_combo.currentData()

    def update_mic_count(self, count):
        """Show or hide the second microphone dropdown."""
        self._mic2_row_widget.setVisible(count >= 2)

    def _output_selected(self):
        value = self.loopback_combo.currentData()
        if value == -1:
            name = None
        elif value is None:
            name = '__disabled__'
        elif isinstance(value, str):
            name = value
        else:
            name = self.loopback_combo.currentText().removesuffix(' (WASAPI Loopback)')
        if self._config:
            self._config.set('audio', 'last_system_output', name)
        self.output_changed.emit(name)

    def get_selected_loopback(self):
        """Return loopback device index for system audio capture."""
        return self.loopback_combo.currentData()

    def get_selected_app_pids(self):
        """Return list of checked app PIDs (per-app mode only).

        Each app entry may have multiple PIDs (e.g., Zoom runs several
        processes). All PIDs for checked apps are returned.
        """
        if self.app_list is None:
            return []
        pids = []
        for i in range(self.app_list.count()):
            item = self.app_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                pid_data = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(pid_data, list):
                    pids.extend(pid_data)
                elif pid_data is not None:
                    pids.append(pid_data)
        return pids

    def get_capture_mode(self):
        """Return 'per_app' or 'legacy'."""
        if self.is_per_app_mode():
            return "per_app"
        return "legacy"

    def is_per_app_mode(self):
        """Check if per-app capture mode is selected."""
        if self.mode_group and self.radio_per_app.isChecked():
            return True
        return False

    def _restore_capture_mode(self):
        """Restore capture mode and selected apps from config."""
        if not self._config:
            return
        try:
            mode = self._config.get("audio", "capture_mode")
        except (KeyError, TypeError):
            return

        if self._win11 and self.mode_group:
            if mode == "legacy":
                self.radio_legacy.setChecked(True)
                # Explicitly set visibility in case signal didn't fire
                if self.app_list is not None:
                    self.app_list.setVisible(False)
                    self.loopback_combo.setVisible(True)
            else:
                self.radio_per_app.setChecked(True)

    def _save_mic_selection(self):
        """Persist mic choices immediately when the user changes a dropdown."""
        if self._config:
            mic1_text = self.mic_combo.currentText() if self.mic_combo.currentData() is not None else ""
            self._config.set("audio", "last_mic", mic1_text)
            mic2_text = self.mic2_combo.currentText() if self.mic2_combo.currentData() is not None else ""
            self._config.set("audio", "last_mic2", mic2_text)
        self.mic_changed.emit(self.mic_combo.currentData())

    def save_capture_settings(self):
        """Save current capture mode, selected app names, and mic choices to config."""
        if not self._config:
            return
        self._config.set("audio", "capture_mode", self.get_capture_mode())

        # Save checked app names (not PIDs, since those change)
        selected_names = []
        if self.app_list is not None:
            for i in range(self.app_list.count()):
                item = self.app_list.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    selected_names.append(item.text().split("  (")[0])
        self._config.set("audio", "selected_apps", selected_names)

        # Save mic selections by name (device indices change across sessions)
        mic1_text = self.mic_combo.currentText() if self.mic_combo.currentData() is not None else ""
        self._config.set("audio", "last_mic", mic1_text)
        mic2_text = self.mic2_combo.currentText() if self.mic2_combo.currentData() is not None else ""
        self._config.set("audio", "last_mic2", mic2_text)

    def set_enabled(self, enabled):
        self._capture_active = not enabled
        self.mic_combo.setEnabled(enabled)
        self.mic2_combo.setEnabled(enabled)
        self.loopback_combo.setEnabled(enabled)
        if self.app_list is not None:
            self.app_list.setEnabled(enabled)
        if self.mode_group:
            self.radio_per_app.setEnabled(enabled)
            self.radio_legacy.setEnabled(enabled)

    def mark_capture_failures(self, failures):
        """Show/hide the ⚠ indicator when per-app activation fails for some PIDs.

        Args:
            failures: {pid: hresult_name_str} mapping. Empty dict clears the indicator.
        """
        if not failures:
            self._capture_warning.setVisible(False)
            self._capture_warning.setText("")
            self._capture_warning.setToolTip("")
            return

        # Resolve PID -> display name via the current app list entries.
        pid_to_name = {}
        if self.app_list is not None:
            for i in range(self.app_list.count()):
                item = self.app_list.item(i)
                pid_data = item.data(Qt.ItemDataRole.UserRole)
                name = item.text()
                if isinstance(pid_data, list):
                    for pid in pid_data:
                        pid_to_name[pid] = name
                elif pid_data is not None:
                    pid_to_name[pid_data] = name

        lines = []
        names_shown = set()
        for pid, err in failures.items():
            name = pid_to_name.get(pid, f"PID {pid}")
            if name in names_shown:
                continue
            names_shown.add(name)
            lines.append(f"{name}: {err}")

        self._capture_warning.setText(
            f"\u26a0 {len(names_shown)} app(s) could not be captured"
        )
        self._capture_warning.setToolTip("\n".join(lines))
        self._capture_warning.setVisible(True)
