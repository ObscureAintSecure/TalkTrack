"""Audio source selection widget with per-app capture support."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel,
    QPushButton, QListWidget, QListWidgetItem,
    QRadioButton, QButtonGroup, QCheckBox, QToolButton, QFrame
)
from PyQt6.QtCore import pyqtSignal, QTimer, Qt

from app.utils.audio_devices import (
    get_input_devices, get_system_audio_devices,
    get_default_mic, get_default_output
)
from app.utils.platform_info import is_windows_11


class CollapsibleSection(QWidget):
    """A section with a clickable header that toggles content visibility."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header button
        self._toggle_btn = QToolButton()
        self._toggle_btn.setObjectName("collapsibleToggle")
        self._toggle_btn.setText(f"\u25b8  {title}")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(False)
        self._toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._toggle_btn.toggled.connect(self._on_toggled)
        self._toggle_btn.setStyleSheet(
            "QToolButton { border: none; color: #89b4fa; font-weight: bold; "
            "text-align: left; padding: 4px 0; }"
            "QToolButton:hover { color: #b4befe; }"
        )
        layout.addWidget(self._toggle_btn)

        # Content area
        self._content = QWidget()
        self._content.setVisible(False)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(self._content, 1)

        self._title = title

    def content_layout(self):
        return self._content_layout

    def _on_toggled(self, checked):
        self._content.setVisible(checked)
        arrow = "\u25be" if checked else "\u25b8"
        self._toggle_btn.setText(f"{arrow}  {self._title}")

    def set_expanded(self, expanded):
        self._toggle_btn.setChecked(expanded)


class SourceSelector(QWidget):
    """Widget for selecting audio input sources.

    On Windows 11, shows a per-app audio picker alongside the legacy
    system audio dropdown. On Windows 10, shows only the legacy dropdown.
    """

    devices_changed = pyqtSignal()
    # Emitted when all checked apps go inactive during recording
    apps_went_inactive = pyqtSignal()

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self._config = config
        self._mic_devices = []
        self._loopback_devices = []
        self._win11 = is_windows_11()
        self._auto_refresh_timer = None
        self._had_active_apps = False
        self._setup_ui()
        self.refresh_devices()
        self._restore_capture_mode()

        if self._win11:
            self._start_auto_refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Collapsible audio sources section
        self._section = CollapsibleSection("Audio Sources")
        content = self._section.content_layout()

        # Microphone selector
        mic_row = QHBoxLayout()
        mic_label = QLabel("Microphone:")
        mic_label.setFixedWidth(80)
        mic_row.addWidget(mic_label)

        self.mic_combo = QComboBox()
        mic_row.addWidget(self.mic_combo, 1)
        content.addLayout(mic_row)

        # System audio section
        if self._win11:
            self._setup_per_app_ui(content)
        else:
            self._setup_legacy_ui(content)

        # Bottom row: auto-refresh + refresh devices
        bottom_row = QHBoxLayout()
        if self._win11:
            self.auto_refresh_check = QCheckBox("Auto-refresh")
            self.auto_refresh_check.setChecked(True)
            self.auto_refresh_check.toggled.connect(self._on_auto_refresh_toggled)
            bottom_row.addWidget(self.auto_refresh_check)

        bottom_row.addStretch()
        self.refresh_btn = QPushButton("Refresh Devices")
        self.refresh_btn.clicked.connect(self.refresh_devices)
        bottom_row.addWidget(self.refresh_btn)
        content.addLayout(bottom_row)

        layout.addWidget(self._section, 1)

        # Start expanded by default
        self._section.set_expanded(True)

    def _setup_legacy_ui(self, parent_layout):
        """Original system audio dropdown (Win10 or fallback)."""
        sys_row = QHBoxLayout()
        sys_label = QLabel("System Audio:")
        sys_label.setFixedWidth(80)
        sys_row.addWidget(sys_label)

        self.loopback_combo = QComboBox()
        sys_row.addWidget(self.loopback_combo, 1)
        parent_layout.addLayout(sys_row)

        self.app_list = None
        self.mode_group = None

    def _setup_per_app_ui(self, parent_layout):
        """Per-app audio picker (Win11)."""
        self.mode_group = QButtonGroup(self)
        self.radio_per_app = QRadioButton("Capture selected apps")
        self.radio_per_app.setObjectName("captureMode")
        self.radio_legacy = QRadioButton("Capture all system audio")
        self.radio_legacy.setObjectName("captureMode")
        self.mode_group.addButton(self.radio_per_app, 0)
        self.mode_group.addButton(self.radio_legacy, 1)
        self.radio_per_app.setChecked(True)
        self.mode_group.idToggled.connect(self._on_mode_changed)

        parent_layout.addWidget(self.radio_per_app)

        # App list (checkable)
        self.app_list = QListWidget()
        self.app_list.setObjectName("appAudioList")
        self.app_list.setMinimumHeight(100)
        parent_layout.addWidget(self.app_list, 1)

        parent_layout.addWidget(self.radio_legacy)

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

    def _on_auto_refresh_toggled(self, checked):
        if checked:
            self._start_auto_refresh()
        else:
            self._stop_auto_refresh()

    def _start_auto_refresh(self):
        if self._auto_refresh_timer is None:
            self._auto_refresh_timer = QTimer(self)
            self._auto_refresh_timer.timeout.connect(self._refresh_app_list)
        self._auto_refresh_timer.start(3000)

    def _stop_auto_refresh(self):
        if self._auto_refresh_timer:
            self._auto_refresh_timer.stop()

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
        self._had_active_apps = any_checked_active

    def refresh_devices(self):
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

        if default_mic_idx > 0:
            self.mic_combo.setCurrentIndex(default_mic_idx)

        # System audio dropdown - always populated
        self.loopback_combo.clear()
        self._loopback_devices = get_system_audio_devices(hidden_devices=hidden)
        self.loopback_combo.addItem("(None - don't record system audio)", None)
        default_output = get_default_output()
        default_lb_idx = 0

        for i, dev in enumerate(self._loopback_devices):
            label = f"{dev['name']} (WASAPI Loopback)"
            self.loopback_combo.addItem(label, dev["index"])
            if dev["index"] == default_output:
                default_lb_idx = i + 1

        if default_lb_idx > 0:
            self.loopback_combo.setCurrentIndex(default_lb_idx)
        elif self._loopback_devices:
            # Default device didn't match — pick the first one
            self.loopback_combo.setCurrentIndex(1)

        # Refresh app list too
        if self._win11 and self.app_list is not None:
            self._refresh_app_list()

        self.devices_changed.emit()

    def get_selected_mic(self):
        return self.mic_combo.currentData()

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

    def save_capture_settings(self):
        """Save current capture mode and selected app names to config."""
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

    def set_enabled(self, enabled):
        self.mic_combo.setEnabled(enabled)
        self.loopback_combo.setEnabled(enabled)
        self.refresh_btn.setEnabled(enabled)
        if self.app_list is not None:
            self.app_list.setEnabled(enabled)
        if self.mode_group:
            self.radio_per_app.setEnabled(enabled)
            self.radio_legacy.setEnabled(enabled)
