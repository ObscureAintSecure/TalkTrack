# Diarization Setup Wizard — Design

## Problem

New users have no guidance for setting up HuggingFace + pyannote speaker diarization. The existing system status panel shows terse messages, and the settings dialog has two small hyperlinks (one pointing to the wrong model). Users must figure out the multi-step process on their own.

## Solution

A single-page step-by-step wizard dialog (`DiarizationSetupWizard`) that walks users through the HuggingFace setup process with numbered steps, descriptions, action buttons, and a token input field.

## New File

- `app/ui/diarization_setup.py` — `DiarizationSetupWizard(QDialog)`

## Modified Files

- `app/main_window.py` — auto-show wizard on first launch, add Help menu item
- `app/ui/settings_dialog.py` — add "Setup Wizard..." button, fix wrong model link
- `app/utils/dependency_checker.py` — fix wrong model cache path

## Wizard Layout

Single scrollable dialog with all steps visible:

1. **Create a HuggingFace account** — link to huggingface.co/join
2. **Accept the model license** — link to pyannote/speaker-diarization-community-1
3. **Create an access token** — link to huggingface.co/settings/tokens, notes "Read" permission
4. **Paste your token** — QLineEdit with password echo mode
5. **Enable diarization** — checkbox, pre-checked when saving

Buttons: "Skip" (close without saving) and "Save & Enable" (save token + enable flag).

## Launch Points

1. **Auto on first launch** — when no HF token is configured (after system status check)
2. **Help menu** — "Diarization Setup..." always available
3. **Settings dialog** — "Setup Wizard..." button in diarization section

## Bug Fixes

- `settings_dialog.py`: model link `speaker-diarization-3.1` → `speaker-diarization-community-1`
- `dependency_checker.py`: cache path `speaker-diarization-3.1` → `speaker-diarization-community-1`

## YAGNI Exclusions

- No token verification API call
- No multi-page wizard with Next/Back
- No step completion tracking
