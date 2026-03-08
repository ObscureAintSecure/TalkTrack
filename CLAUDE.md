# TalkTrack - CLAUDE.md

## Project Overview

TalkTrack is a Windows desktop application that records, transcribes, and diarizes audio from calls (Teams, Zoom, etc.). It is a modern clone of Evaer for Teams with AI-powered transcription and speaker identification.

## Tech Stack

- **GUI:** PyQt6
- **Audio Capture:** sounddevice + WASAPI (Windows Audio Session API)
- **Transcription:** faster-whisper (local OpenAI Whisper, no internet needed)
- **Speaker Diarization:** pyannote.audio (requires free HuggingFace token)
- **Deep Learning:** torch, torchaudio
- **Audio Processing:** scipy, pydub, soundfile, numpy
- **Windows Integration:** pywin32

## Project Structure

```
TalkTrack/
  main.py                         # Entry point, QApplication setup
  requirements.txt                # Dependencies
  app/
    main_window.py                # Main window + orchestration
    recording/
      audio_capture.py            # AudioStream, DualAudioCapture
      recorder.py                 # State machine, session management
    transcription/
      transcriber.py              # Whisper worker + dataclasses
      diarizer.py                 # Speaker diarization (pyannote)
    ui/
      source_selector.py          # Device selection dropdowns
      recording_controls.py       # Record/Pause/Stop buttons + timer
      settings_dialog.py          # Settings dialog with tabs
      transcript_viewer.py        # Display + export transcripts
      notes_panel.py              # Call notes with timestamps
      recordings_list.py          # Past recordings browser
    utils/
      audio_devices.py            # Device enumeration (sounddevice)
      config.py                   # JSON config management
  recordings/                     # Output directory
```

## Current Features

- Record / Pause / Resume / Stop controls with live timer
- Dual audio capture: microphone (your voice) + system audio (WASAPI loopback)
- Auto-transcribes after recording stops using Faster-Whisper
- Speaker diarization with two modes:
  - Simple mode (no setup): labels "You" vs "Remote" based on mic vs system channels
  - Full diarization (pyannote.audio): identifies individual speakers
- Color-coded transcript with speaker labels and timestamps
- Export transcript to TXT, SRT (subtitles), or JSON
- Call notes with timestamp insertion
- Browse and replay past recordings
- Settings for model size, sample rate, output format (WAV/MP3)
- Dark theme UI

## Architecture Notes

### Audio Capture
- `AudioStream`: Single-device capture wrapper around sounddevice
- `DualAudioCapture`: Orchestrates simultaneous mic + system audio recording
- WASAPI loopback captures all system audio (not per-app)
- Audio mixed at finalization (stop time), not real-time
- Output files per recording: mic_audio.wav, system_audio.wav, combined_audio.wav

### Recording Pipeline
- State machine: IDLE -> RECORDING -> PAUSED <-> RECORDING -> STOPPING -> IDLE
- Each recording gets timestamped directory with audio files + metadata.json
- Transcription/diarization runs in separate QThread workers

### Configuration
- Stored at ~/.talktrack/settings.json
- Audio device selection is per-session (not persisted)
- Transcription settings: model size (tiny/base/small/medium/large-v3), language, compute device

## Planned: Per-App Audio Capture (Approach 3)

**Goal:** Replace system-wide WASAPI loopback with per-process audio capture so users can select specific apps (e.g., only Teams) instead of capturing all system audio.

**Approach:** Use Windows 11's `ActivateAudioInterfaceAsync` with `AUDIOCLIENT_ACTIVATION_PARAMS` for process-based loopback capture. This API allows specifying a PID to capture only that process's audio output.

**Key decisions:**
- Multi-select dropdown showing currently running audio-producing apps
- Live refresh: app list updates in real-time, even during recording
- Microphone capture stays as-is (only system audio side gets per-app filtering)
- Requires Windows 11 Build 22000+
- Implemented via comtypes/ctypes COM interop from Python

## Setup Instructions

### Basic Setup
```bash
pip install -r requirements.txt
python main.py
```

### For Full Speaker Diarization (Optional)
1. Get a free HuggingFace token at https://huggingface.co/settings/tokens
2. Accept the pyannote model terms at:
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0
3. Install: `pip install pyannote.audio torch torchaudio`
4. Enter your token in Settings > Transcription > HuggingFace Token

### Usage During a Teams Call
Start a Teams meeting normally, then click Record in TalkTrack. It captures audio output from your computer - no Teams integration or special permissions needed.

## Coding Conventions

- Python with PyQt6 for all UI
- QThread workers for background processing (transcription, diarization)
- Signals/slots for inter-component communication
- Config stored as JSON, loaded via config.py utility
- Dark theme by default
- All audio processing uses numpy arrays at 16000 Hz sample rate (speech-optimized)

## Bash Command Style

When running shell commands:
- Avoid complex chained commands with `&&`, `||`, or pipes when possible
- Run simple, single-purpose commands sequentially instead
