# TalkTrack

Record, transcribe, and identify speakers from your calls — all locally on your machine.

TalkTrack is a Windows desktop app that captures audio from Teams, Zoom, and other call apps, then transcribes it with [Faster Whisper](https://github.com/SYSTRAN/faster-whisper) and identifies speakers with [pyannote.audio](https://github.com/pyannote/pyannote-audio). Everything runs offline — no cloud services, no data leaves your PC.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6)
![UI](https://img.shields.io/badge/UI-PyQt6-41CD52)
![License](https://img.shields.io/badge/License-MIT-green)

## Features

- **Record calls** with Record / Pause / Resume / Stop controls and a live timer
- **Per-app audio capture** (Windows 11) — pick specific apps like Teams or Chrome
- **System audio capture** (Windows 10+) — WASAPI loopback for all system audio
- **Dual-channel recording** — microphone + system/app audio captured separately
- **Local transcription** — Faster Whisper (OpenAI Whisper), no internet required
- **Speaker diarization** — two modes:
  - *Simple* (no setup): labels "You" vs "Remote" from mic vs system channels
  - *Full* (pyannote.audio): identifies individual speakers with a free HuggingFace token
- **Interactive transcript** — click any segment to replay its audio, edit text inline, assign speaker names
- **Export** to TXT, SRT (subtitles), or JSON
- **Call notes** with timestamp insertion
- **Recording browser** — browse and replay past recordings
- **Dark theme** UI (Catppuccin Mocha palette)
- **Guided setup wizard** for HuggingFace / pyannote configuration

## Quick Start

### Prerequisites

- Windows 10 or 11
- Python 3.10+
- A microphone

### Install

```bash
git clone https://github.com/ObscureAintSecure/TalkTrack.git
cd TalkTrack
pip install -r requirements.txt
```

### Run

Double-click **`start.bat`**, or:

```bash
python main.py
```

### Speaker Diarization (Optional)

For multi-speaker identification, TalkTrack uses pyannote.audio which requires a free HuggingFace account. On first launch, a setup wizard walks you through the steps:

1. Create a free account at [huggingface.co](https://huggingface.co/join)
2. Accept the model license at [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
3. Create an access token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
4. Paste the token into the wizard (or Settings > Transcription)

Without this setup, TalkTrack still works — it just labels speakers as "You" and "Remote" based on audio channels.

## Usage

1. Start your call in Teams, Zoom, or any app
2. In TalkTrack, select your microphone and the app to capture
3. Click **Record**
4. When done, click **Stop** — transcription starts automatically
5. Review the transcript, assign speaker names, edit text, export

**Windows 11:** Select specific apps (Teams, Chrome, etc.) in the app picker to capture only their audio.

**Windows 10:** Captures all system audio via WASAPI loopback.

## Settings

Access via the gear icon or **Edit > Settings**:

| Setting | Options | Default |
|---------|---------|---------|
| Whisper Model | tiny, base, small, medium, large-v3 | small |
| Sample Rate | 16000, 44100, 48000 Hz | 16000 |
| Output Format | WAV, MP3 | WAV |
| Capture Mode | Per-app (Win11) or Legacy | Auto-detected |

## Project Structure

```
TalkTrack/
  main.py                    # Entry point
  start.bat / start.ps1      # Launcher scripts
  requirements.txt           # Dependencies
  resources/style.qss        # Dark theme stylesheet
  app/
    main_window.py           # Main window + orchestration
    audio/
      segment_player.py      # Audio clip playback
    recording/
      audio_capture.py       # WASAPI capture (legacy + per-app)
      process_audio_capture.py  # Win11 per-process capture
      recorder.py            # Recording state machine
    transcription/
      transcriber.py         # Faster Whisper integration
      diarizer.py            # Speaker diarization (pyannote)
    ui/                      # All UI components
    utils/                   # Config, device enumeration, helpers
  tests/                     # Unit tests
  recordings/                # Output directory
```

## Running Tests

```bash
python -m pytest tests/ -v
```

## Tech Stack

| Component | Library |
|-----------|---------|
| GUI | PyQt6 |
| Audio Capture | sounddevice, WASAPI, comtypes |
| Transcription | faster-whisper |
| Speaker Diarization | pyannote.audio 4.0 |
| Deep Learning | PyTorch |
| Audio Processing | scipy, pydub, soundfile, numpy |
| Windows Integration | pywin32, pycaw, comtypes |

## Known Limitations

- **Windows only** — uses WASAPI and Windows COM APIs
- **Per-app capture requires Windows 11** Build 22000+
- Per-process COM capture is in active development — the pipeline structure is in place, with packet reading being completed through real-device testing
