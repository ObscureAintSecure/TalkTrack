"""Step-by-step diarization setup wizard for HuggingFace + pyannote."""
import webbrowser

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QFrame
)
from PyQt6.QtCore import Qt


HF_JOIN_URL = "https://huggingface.co/join"
HF_MODEL_URL = "https://huggingface.co/pyannote/speaker-diarization-community-1"
HF_TOKENS_URL = "https://huggingface.co/settings/tokens"


class _StepWidget(QFrame):
    """A single numbered setup step with description and optional action button."""

    def __init__(self, number, title, description, button_text=None,
                 button_url=None, parent=None):
        super().__init__(parent)
        self.setObjectName("wizardStep")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # Number circle
        num_label = QLabel(str(number))
        num_label.setObjectName("wizardStepNumber")
        num_label.setFixedSize(32, 32)
        num_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(num_label)

        # Text column
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("wizardStepTitle")
        text_layout.addWidget(title_label)

        desc_label = QLabel(description)
        desc_label.setObjectName("wizardStepDesc")
        desc_label.setWordWrap(True)
        text_layout.addWidget(desc_label)

        layout.addLayout(text_layout, 1)

        # Action button
        if button_text and button_url:
            action_btn = QPushButton(button_text)
            action_btn.setObjectName("wizardActionBtn")
            action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            action_btn.clicked.connect(lambda: webbrowser.open(button_url))
            layout.addWidget(action_btn)


class DiarizationSetupWizard(QDialog):
    """Guided setup wizard for HuggingFace speaker diarization."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Speaker Diarization Setup")
        self.setMinimumSize(550, 520)
        self.setMaximumSize(650, 650)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header
        header = QLabel("Speaker Diarization Setup")
        header.setObjectName("wizardHeader")
        layout.addWidget(header)

        intro = QLabel(
            "Speaker diarization identifies who is speaking in your recordings. "
            "It requires a free HuggingFace account. Follow these steps:"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #a6adc8; margin-bottom: 8px;")
        layout.addWidget(intro)

        # Step 1: Create account
        layout.addWidget(_StepWidget(
            number=1,
            title="Create a HuggingFace account",
            description="Sign up for a free account at huggingface.co. "
                        "Skip this step if you already have one.",
            button_text="Open HuggingFace",
            button_url=HF_JOIN_URL,
        ))

        # Step 2: Accept model license
        layout.addWidget(_StepWidget(
            number=2,
            title="Accept the model license",
            description="The pyannote speaker diarization model requires you to "
                        "accept its license terms. Click the link, scroll down, "
                        "and click \"Agree and access repository\".",
            button_text="Accept License",
            button_url=HF_MODEL_URL,
        ))

        # Step 3: Create token
        layout.addWidget(_StepWidget(
            number=3,
            title="Create an access token",
            description="Go to your HuggingFace token settings and create a new "
                        "token. Select \"Read\" access — that's all TalkTrack needs.",
            button_text="Open Token Settings",
            button_url=HF_TOKENS_URL,
        ))

        # Step 4: Paste token
        step4_frame = QFrame()
        step4_frame.setObjectName("wizardStep")
        step4_layout = QHBoxLayout(step4_frame)
        step4_layout.setContentsMargins(12, 10, 12, 10)
        step4_layout.setSpacing(12)

        num4 = QLabel("4")
        num4.setObjectName("wizardStepNumber")
        num4.setFixedSize(32, 32)
        num4.setAlignment(Qt.AlignmentFlag.AlignCenter)
        step4_layout.addWidget(num4)

        token_col = QVBoxLayout()
        token_col.setSpacing(4)

        token_title = QLabel("Paste your token below")
        token_title.setObjectName("wizardStepTitle")
        token_col.addWidget(token_title)

        self.token_edit = QLineEdit()
        self.token_edit.setPlaceholderText("hf_xxxxxxxxxxxxxxxxxxxx")
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)

        # Pre-fill if token already exists
        existing_token = self.config.get("diarization", "hf_token") or ""
        if existing_token:
            self.token_edit.setText(existing_token)

        token_col.addWidget(self.token_edit)
        step4_layout.addLayout(token_col, 1)

        layout.addWidget(step4_frame)

        # Enable checkbox
        self.enable_check = QCheckBox("Enable speaker diarization")
        self.enable_check.setChecked(True)
        self.enable_check.setStyleSheet("margin-top: 4px; margin-left: 4px;")
        layout.addWidget(self.enable_check)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        skip_btn = QPushButton("Skip")
        skip_btn.clicked.connect(self.reject)
        skip_btn.setMinimumWidth(80)
        btn_layout.addWidget(skip_btn)

        save_btn = QPushButton("Save && Enable")
        save_btn.setObjectName("wizardSaveBtn")
        save_btn.clicked.connect(self._save_and_close)
        save_btn.setMinimumWidth(120)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    def _save_and_close(self):
        token = self.token_edit.text().strip()
        if token:
            self.config.set("diarization", "hf_token", token)
        self.config.set("diarization", "enabled", self.enable_check.isChecked())
        self.config.save()
        self.accept()
