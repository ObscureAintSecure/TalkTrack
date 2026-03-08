"""Audio source selection widget with per-app capture support."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel,
    QPushButton, QGroupBox, QListWidget, QListWidgetItem,
    QRadioButton, QButtonGroup, QCheckBox
)
from PyQt6.QtCore import pyqtSignal, QTimer, Qt

from app.utils.audio_devices import (
    get_input_devices, get_wasapi_output_devices,
    get_default_mic, get_default_output
)
from app.utils.platform_info import is_windows_11


class SourceSelector(QWidget):
    """Widget for selecting audio input sources.

    On Windows 11, shows a per-app audio picker alongside the legacy
    system audio dropdown. On Windows 10, shows only the legacy dropdown.
    """

    devices_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mic_devices = []
        self._loopback_devices = []
        self._win11 = is_windows_11()
        self._auto_refresh_timer = None
        self._setup_ui()
        self.refresh_devices()

        if self._win11:
            self._start_auto_refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("Audio Sources")
        group_layout = QVBoxLayout(group)

        # --- Microphone selector (unchanged) ---
        mic_row = QHBoxLayout()
        mic_label = QLabel("Microphone:")
        mic_label.setFixedWidth(120)
        mic_row.addWidget(mic_label)

        self.mic_combo = QComboBox()
        self.mic_combo.setMinimumWidth(250)
        mic_row.addWidget(self.mic_combo, 1)
        group_layout.addLayout(mic_row)

        # --- System audio section ---
        if self._win11:
            self._setup_per_app_ui(group_layout)
        else:
            self._setup_legacy_ui(group_layout)

        # Refresh button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.refresh_btn = QPushButton("Refresh Devices")
        self.refresh_btn.clicked.connect(self.refresh_devices)
        btn_row.addWidget(self.refresh_btn)
        group_layout.addLayout(btn_row)

        layout.addWidget(group)

    def _setup_legacy_ui(self, parent_layout):
        """Original system audio dropdown (Win10 or fallback)."""
        sys_row = QHBoxLayout()
        sys_label = QLabel("System Audio:")
        sys_label.setFixedWidth(120)
        sys_row.addWidget(sys_label)

        self.loopback_combo = QComboBox()
        self.loopback_combo.setMinimumWidth(250)
        sys_row.addWidget(self.loopback_combo, 1)
        parent_layout.addLayout(sys_row)

        # Not used in legacy mode
        self.app_list = None
        self.mode_group = None

    def _setup_per_app_ui(self, parent_layout):
        """Per-app audio picker (Win11)."""
        self.mode_group = QButtonGroup(self)
        self.radio_per_app = QRadioButton("Capture selected apps only")
        self.radio_per_app.setObjectName("captureMode")
        self.radio_legacy = QRadioButton("Capture all system audio (legacy)")
        self.radio_legacy.setObjectName("captureMode")
        self.mode_group.addButton(self.radio_per_app, 0)
        self.mode_group.addButton(self.radio_legacy, 1)
        self.radio_per_app.setChecked(True)
        self.mode_group.idToggled.connect(self._on_mode_changed)

        parent_layout.addWidget(self.radio_per_app)

        # App list (checkable)
        app_label = QLabel("App Audio:")
        app_label.setObjectName("sectionHeader")
        parent_layout.addWidget(app_label)

        self.app_list = QListWidget()
        self.app_list.setObjectName("appAudioList")
        self.app_list.setMinimumHeight(100)
        self.app_list.setMaximumHeight(180)
        parent_layout.addWidget(self.app_list)

        parent_layout.addWidget(self.radio_legacy)

        # Also keep the legacy combo hidden for fallback
        self.loopback_combo = QComboBox()
        self.loopback_combo.setMinimumWidth(250)
        self.loopback_combo.setVisible(False)
        parent_layout.addWidget(self.loopback_combo)

        # Auto-refresh checkbox
        refresh_row = QHBoxLayout()
        self.auto_refresh_check = QCheckBox("Auto-refresh")
        self.auto_refresh_check.setChecked(True)
        self.auto_refresh_check.toggled.connect(self._on_auto_refresh_toggled)
        refresh_row.addStretch()
        refresh_row.addWidget(self.auto_refresh_check)
        parent_layout.addLayout(refresh_row)

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

        self.app_list.clear()

        for app in apps:
            # Show app name with status indicator
            if app.get("active", False):
                label = f"{app['name']}  ({len(app['pids'])} process{'es' if len(app['pids']) > 1 else ''})"
            else:
                label = f"{app['name']}  (not in call)"
            item = QListWidgetItem(label)
            # Store list of PIDs for this app
            item.setData(Qt.ItemDataRole.UserRole, app["pids"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if app["name"] in checked_names:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            self.app_list.addItem(item)

        if self.app_list.count() == 0:
            item = QListWidgetItem("No audio apps detected")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.app_list.addItem(item)

    def refresh_devices(self):
        self.mic_combo.clear()

        # Microphone devices
        self._mic_devices = get_input_devices()
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

        # System audio (legacy dropdown - always populated)
        self.loopback_combo.clear()
        self._loopback_devices = get_wasapi_output_devices()
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

        # Refresh app list too
        if self._win11 and self.app_list is not None:
            self._refresh_app_list()

        self.devices_changed.emit()

    def get_selected_mic(self):
        return self.mic_combo.currentData()

    def get_selected_loopback(self):
        """Return loopback device index (legacy mode only)."""
        if self.is_per_app_mode():
            return None
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

    def set_enabled(self, enabled):
        self.mic_combo.setEnabled(enabled)
        self.loopback_combo.setEnabled(enabled)
        self.refresh_btn.setEnabled(enabled)
        if self.app_list is not None:
            self.app_list.setEnabled(enabled)
        if self.mode_group:
            self.radio_per_app.setEnabled(enabled)
            self.radio_legacy.setEnabled(enabled)
