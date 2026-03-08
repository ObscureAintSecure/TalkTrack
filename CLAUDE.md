# TalkTrack - CLAUDE.md

## Project Overview

TalkTrack is a Windows desktop application that records, transcribes, and diarizes audio from calls (Teams, Zoom, etc.). It is a modern clone of Evaer for Teams with AI-powered transcription and speaker identification.

## Tech Stack

- **GUI:** PyQt6
- **Audio Capture:** sounddevice + WASAPI, comtypes (Win11 per-process capture)
- **Audio Session Enumeration:** pycaw (Windows Core Audio API)
- **Transcription:** faster-whisper (local OpenAI Whisper, no internet needed)
- **Speaker Diarization:** pyannote.audio (requires free HuggingFace token)
- **Deep Learning:** torch, torchaudio
- **Audio Processing:** scipy, pydub, soundfile, numpy
- **Windows Integration:** pywin32, comtypes

## Project Structure

```
TalkTrack/
  main.py                              # Entry point, QApplication setup
  requirements.txt                     # Dependencies
  app/
    main_window.py                     # Main window + orchestration
    recording/
      audio_capture.py                 # AudioStream, DualAudioCapture (legacy + per-app modes)
      process_audio_capture.py         # ProcessCaptureStream, ProcessAudioCapture (Win11 per-PID)
      recorder.py                      # State machine, session management
    transcription/
      transcriber.py                   # Whisper worker + dataclasses
      diarizer.py                      # Speaker diarization (pyannote)
    ui/
      source_selector.py              # Mic dropdown + per-app picker (Win11) or legacy loopback (Win10)
      recording_controls.py           # Record/Pause/Stop buttons + timer
      settings_dialog.py              # Settings dialog with tabs
      status_panel.py                 # System status dialog (dependency health checks)
      transcript_viewer.py            # Display + export transcripts
      notes_panel.py                  # Call notes with timestamps
      recordings_list.py              # Past recordings browser
    utils/
      audio_devices.py                # Device enumeration (sounddevice)
      audio_session_monitor.py        # Per-app audio session enumeration (pycaw)
      config.py                       # JSON config management
      dependency_checker.py           # System health checks for status panel
      platform_info.py                # Windows version detection
  tests/
    test_platform_info.py             # Windows version detection tests
    test_audio_session_monitor.py     # Audio session enumeration tests
    test_process_audio_capture.py     # Mixer and capture stream tests
    test_dual_audio_capture.py        # Per-app mode integration tests
    test_dependency_checker.py        # Dependency checker tests
  docs/plans/                         # Design docs and implementation plans
  recordings/                         # Output directory
```

## Current Features

- Record / Pause / Resume / Stop controls with live timer
- **Per-app audio capture (Win11):** select specific apps (Teams, Chrome, etc.) to record
- **Legacy system audio capture:** WASAPI loopback for all system audio (Win10 or fallback)
- Dual audio capture: microphone (your voice) + system/app audio
- Auto-transcribes after recording stops using Faster-Whisper
- Speaker diarization with two modes:
  - Simple mode (no setup): labels "You" vs "Remote" based on mic vs system channels
  - Full diarization (pyannote.audio): identifies individual speakers
- **System Status Panel:** startup dependency health check (Help > System Status)
- Color-coded transcript with speaker labels and timestamps
- Export transcript to TXT, SRT (subtitles), or JSON
- Call notes with timestamp insertion
- Browse and replay past recordings
- Settings for model size, sample rate, output format (WAV/MP3)
- Dark theme UI (Catppuccin Mocha palette)

## Architecture Notes

### Audio Capture (Two Modes)

**Per-App Mode (Win11 only):**
- `ProcessCaptureStream`: Captures audio from a single process by PID using Win11 `ActivateAudioInterfaceAsync` COM API
- `ProcessAudioCapture`: Manages multiple ProcessCaptureStreams, mixes output in real-time
- Supports live add/remove of apps during recording
- Uses `PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE` to capture process + children

**Legacy Mode (Win10/fallback):**
- `AudioStream`: Single-device capture wrapper around sounddevice
- WASAPI loopback captures all system audio

**Common:**
- `DualAudioCapture`: Orchestrates mic + system audio, accepts either mode via `capture_mode` param
- Output files per recording: mic_audio.wav, system_audio.wav, combined_audio.wav

### Audio Session Monitoring
- `audio_session_monitor.py` uses pycaw to enumerate active audio sessions
- Returns process names/PIDs of apps producing audio
- Auto-refreshes every 3 seconds in the UI

### Recording Pipeline
- State machine: IDLE -> RECORDING -> PAUSED <-> RECORDING -> STOPPING -> IDLE
- Each recording gets timestamped directory with audio files + metadata.json
- Metadata includes capture_mode and app_pids
- Transcription/diarization runs in separate QThread workers

### System Status Panel
- `DependencyChecker` runs health checks: mic, WASAPI, Whisper model, HF token, pyannote, FFmpeg, Windows version
- `SystemStatusDialog` shows results with actionable fix suggestions
- Auto-shows on startup if critical checks fail
- Accessible via Help > System Status

### Configuration
- Stored at ~/.talktrack/settings.json
- Audio settings: sample_rate, channels, capture_mode ("legacy" or "per_app")
- Audio device selection is per-session (not persisted)
- Transcription settings: model size (tiny/base/small/medium/large-v3), language, compute device

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
3. Enter your token in Settings > Transcription > HuggingFace Token

### Usage During a Teams Call
Start a Teams meeting normally, then click Record in TalkTrack.
- **Windows 11:** Select "Microsoft Teams" in the app picker to capture only Teams audio
- **Windows 10:** Captures all system audio via WASAPI loopback

## Running Tests

```bash
python -m pytest tests/ -v
```

## Coding Conventions

- Python with PyQt6 for all UI
- QThread workers for background processing (transcription, diarization)
- Signals/slots for inter-component communication
- Config stored as JSON, loaded via config.py utility
- Dark theme by default (Catppuccin Mocha palette)
- All audio processing uses numpy arrays at 16000 Hz sample rate (speech-optimized)
- Tests use unittest with mock for hardware-dependent code

## Bash Command Style

When running shell commands:
- Avoid complex chained commands with `&&`, `||`, or pipes when possible
- Run simple, single-purpose commands sequentially instead

## Known Limitations

- **Per-process COM capture is scaffolded:** The `ProcessCaptureStream._read_audio_packets()` method is a pipeline placeholder. The COM initialization structure is in place but the actual `IAudioCaptureClient.GetBuffer()` packet reading needs to be completed with real audio testing on Windows 11.
- **Windows only:** Uses WASAPI and Windows COM APIs
- **Per-app capture requires Windows 11 Build 22000+**
