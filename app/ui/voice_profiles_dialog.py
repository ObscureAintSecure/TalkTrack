"""Lists saved voice profiles and lets the user delete them (#128)."""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QMessageBox, QAbstractItemView
)
from PyQt6.QtCore import Qt

from app.transcription.voice_profiles import VoiceProfileStore


def _profile_label(name, recordings):
    plural = "recording" if recordings == 1 else "recordings"
    return f"{name}  ({recordings} {plural})"


class VoiceProfilesDialog(QDialog):
    def __init__(self, store=None, parent=None):
        super().__init__(parent)
        self._store = store if store is not None else VoiceProfileStore()
        self.setWindowTitle("Voice Profiles")
        self.setMinimumSize(380, 320)
        self._setup_ui()
        self._refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel(
            "A profile is learned from every recording where you named that "
            "speaker. Profiles stay on this computer. Deleting one does not "
            "touch your recordings or their speaker names."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self._list)

        self._empty_label = QLabel(
            "No voice profiles yet. Name the speakers of a diarized recording "
            "to create them."
        )
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet("color: #a6adc8;")
        layout.addWidget(self._empty_label)

        buttons = QHBoxLayout()
        self._delete_btn = QPushButton("Delete Selected")
        self._delete_btn.clicked.connect(self._delete_selected)
        buttons.addWidget(self._delete_btn)
        self._delete_all_btn = QPushButton("Delete All")
        self._delete_all_btn.clicked.connect(self._delete_all)
        buttons.addWidget(self._delete_all_btn)
        buttons.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def _refresh(self):
        self._list.clear()
        summary = self._store.summary()
        for name, recordings in summary:
            item = QListWidgetItem(_profile_label(name, recordings))
            item.setData(Qt.ItemDataRole.UserRole, name)
            self._list.addItem(item)
        self._list.setVisible(bool(summary))
        self._empty_label.setVisible(not summary)
        self._delete_all_btn.setEnabled(bool(summary))
        self._update_buttons()

    def _update_buttons(self):
        self._delete_btn.setEnabled(bool(self._list.selectedItems()))

    def _delete_selected(self):
        names = [i.data(Qt.ItemDataRole.UserRole) for i in self._list.selectedItems()]
        if not names:
            return
        for name in names:
            self._store.delete_profile(name)
        self._refresh()

    def _delete_all(self):
        reply = QMessageBox.question(
            self, "Delete All Voice Profiles",
            "Delete every saved voice profile? TalkTrack will stop recognizing "
            "speakers until you name them again.",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._store.clear()
            self._refresh()
