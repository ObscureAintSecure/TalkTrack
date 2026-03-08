from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QPushButton, QGroupBox
)
from PyQt6.QtCore import pyqtSignal

from app.utils.audio_devices import (
    get_input_devices, get_wasapi_output_devices,
    get_default_mic, get_default_output
)


class SourceSelector(QWidget):
    """Widget for selecting audio input sources."""

    devices_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mic_devices = []
        self._loopback_devices = []
        self._setup_ui()
        self.refresh_devices()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Audio Sources Group
        group = QGroupBox("Audio Sources")
        group_layout = QVBoxLayout(group)

        # Microphone selector
        mic_row = QHBoxLayout()
        mic_label = QLabel("Microphone:")
        mic_label.setFixedWidth(120)
        mic_row.addWidget(mic_label)

        self.mic_combo = QComboBox()
        self.mic_combo.setMinimumWidth(250)
        mic_row.addWidget(self.mic_combo, 1)
        group_layout.addLayout(mic_row)

        # System audio selector
        sys_row = QHBoxLayout()
        sys_label = QLabel("System Audio:")
        sys_label.setFixedWidth(120)
        sys_row.addWidget(sys_label)

        self.loopback_combo = QComboBox()
        self.loopback_combo.setMinimumWidth(250)
        sys_row.addWidget(self.loopback_combo, 1)
        group_layout.addLayout(sys_row)

        # Refresh button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.refresh_btn = QPushButton("Refresh Devices")
        self.refresh_btn.clicked.connect(self.refresh_devices)
        btn_row.addWidget(self.refresh_btn)
        group_layout.addLayout(btn_row)

        layout.addWidget(group)

    def refresh_devices(self):
        self.mic_combo.clear()
        self.loopback_combo.clear()

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

        # System audio (WASAPI output devices for loopback)
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

        self.devices_changed.emit()

    def get_selected_mic(self):
        return self.mic_combo.currentData()

    def get_selected_loopback(self):
        return self.loopback_combo.currentData()

    def set_enabled(self, enabled):
        self.mic_combo.setEnabled(enabled)
        self.loopback_combo.setEnabled(enabled)
        self.refresh_btn.setEnabled(enabled)
