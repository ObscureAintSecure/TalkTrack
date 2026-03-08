# Per-App Audio Capture + System Status Panel

**Date:** 2026-03-08
**Status:** Approved

## Problem

TalkTrack currently captures all system audio via WASAPI loopback. Users want to record only specific apps (e.g., Microsoft Teams) without picking up Spotify, YouTube, notification sounds, etc. Additionally, there is no visibility into whether all dependencies are properly configured.

## Goals

1. Replace system-wide WASAPI loopback with per-process audio capture
2. Let users select which apps to record via a multi-select UI
3. Support live add/remove of apps during recording
4. Add a startup status panel showing dependency health
5. Maintain backward compatibility (legacy full-loopback mode)

## Non-Goals

- Per-app microphone filtering (mic capture stays as-is)
- Linux/macOS support (Windows-only feature)
- Windows 10 per-app capture (Win10 gets legacy mode only)

---

## Feature 1: Per-App Audio Capture

### Core Mechanism

Windows 11 (Build 22000+) provides `ActivateAudioInterfaceAsync` with `AUDIOCLIENT_ACTIVATION_PARAMS` supporting `PROCESS_LOOPBACK_PARAMS`:

- Accepts a **Process ID (PID)** to capture audio from
- `PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE` captures only that process and its children (handles multi-process apps like Chrome/Teams)
- Returns an `IAudioCaptureClient` for that specific process

### New Components

#### `ProcessAudioCapture` class (`app/recording/process_audio_capture.py`)

Replaces `AudioStream` for system audio when in per-app mode:

- Accepts a list of PIDs to capture
- Creates one capture stream per PID via `ActivateAudioInterfaceAsync` (COM interop via `comtypes`)
- Each stream runs on its own thread with audio callback
- Real-time mixer sums per-process streams with gain normalization (divide by active stream count)
- Produces a single mixed output identical to what `DualAudioCapture` expects

#### `AudioSessionMonitor` class (`app/utils/audio_session_monitor.py`)

Uses `pycaw` to enumerate active audio sessions:

- `get_active_audio_apps()` returns list of `{pid, name, icon_path, is_active}`
- Polls every ~3 seconds for new/removed audio sessions
- Provides process icons extracted from EXE files
- Runs on a QTimer for non-blocking UI updates

### App Enumeration

Using `pycaw` (`AudioUtilities.GetAllSessions()`):

- Each audio session exposes `.Process` with `.name()` and `.pid`
- Filter to sessions actively producing sound
- Returns live list: `Teams (PID 12345)`, `Chrome (PID 6789)`, etc.

### Pipeline Architecture

```
Microphone ──> AudioStream (unchanged) ──> mic_audio.wav
                                                          \
                                                           > combined_audio.wav > Whisper > Transcript
                                                          /
App 1 (PID) ──> ProcessCaptureStream ──┐
App 2 (PID) ──> ProcessCaptureStream ──┤──> Real-time Mixer ──> system_audio.wav
App N (PID) ──> ProcessCaptureStream ──┘
```

- Output files unchanged: `mic_audio.wav`, `system_audio.wav`, `combined_audio.wav`
- Downstream transcription and diarization code requires no changes
- Optional per-app WAVs saved for debugging (e.g., `teams_audio.wav`)

### Live Add/Remove During Recording

- When user checks a new app mid-recording: new `ProcessCaptureStream` spawned, added to mixer
- When unchecked: stream stopped and removed from mixer
- Apps that stop producing audio: grayed out in list, removed from mixer, other streams continue
- Mixer handles variable stream count gracefully

### UI Changes to `SourceSelector`

Replace the "System Audio" dropdown with a multi-select app picker:

```
+---------------------------------------------+
|  Audio Sources                               |
+---------------------------------------------+
|  Microphone:      [v Default Mic ...]        |
|                                              |
|  App Audio:                                  |
|  +-------------------------------------+    |
|  | [x] Microsoft Teams      PID 12345  |    |
|  | [ ] Google Chrome         PID 6789  |    |
|  | [ ] Spotify               PID 4321  |    |
|  +-------------------------------------+    |
|  ( ) Capture selected apps only              |
|  ( ) Capture all system audio (legacy)       |
|  [Refresh]           Auto-refresh: [x]       |
+---------------------------------------------+
```

- Auto-refreshes every ~3 seconds (polls for new/removed audio sessions)
- During recording, new apps appear and can be checked/unchecked live
- Apps that stop producing audio get grayed out but stay in list
- Radio toggle for legacy full-loopback fallback
- Process icons from EXE for visual scanning

### OS Compatibility

```
On startup:
  +-- Check Windows build number
  +-- Build >= 22000 (Win11) --> enable per-app capture mode
  +-- Build < 22000 (Win10) --> hide per-app UI, show only legacy loopback
```

- Win10: UI looks exactly as it does today, no confusing disabled controls
- Win11 + COM failure: fall back to legacy with warning toast

### Error Handling

| Scenario | Behavior |
|----------|----------|
| Selected app exits mid-recording | Stream closes gracefully. App grayed out. Other streams continue. |
| No apps producing audio | Empty state: "No apps are currently playing audio." Legacy mode available. |
| COM initialization fails | Fall back to legacy loopback with warning toast. |
| Multi-process apps (Chrome/Teams) | `INCLUDE_TARGET_PROCESS_TREE` captures process + children. |
| User selects 0 apps and clicks Record | Validation: "Select at least one app or switch to legacy mode." |
| Audio format mismatch between apps | Each stream normalizes to 16kHz mono before mixer. |

### New Dependencies

- `pycaw` -- audio session enumeration (which apps produce sound)
- `comtypes` -- Win11 `ActivateAudioInterfaceAsync` COM calls (pycaw already depends on this)

### Unchanged Components

- Transcription pipeline (Whisper)
- Speaker diarization (pyannote)
- Export formats (TXT, SRT, JSON)
- Recording state machine (IDLE/RECORDING/PAUSED/STOPPING)
- Settings/config system (except adding "capture mode" preference)
- Microphone capture

---

## Feature 2: Startup System Status Panel

### Purpose

Show users at a glance whether all dependencies are configured and ready, with actionable steps to fix anything missing.

### Behavior

- Shows automatically on first launch, or if anything critical (mic, WASAPI) is missing
- Accessible anytime via **Help > System Status**
- Non-blocking: app fully opens behind the dialog
- Actionable: download buttons for models, links to settings for token

### Status Checks

| Check | Type | Status | Action if Missing |
|-------|------|--------|-------------------|
| Microphone detected | Critical | Pass/Fail | "No microphone found -- check your audio devices" |
| System audio (WASAPI) | Critical | Pass/Fail | "No WASAPI loopback device detected" |
| Whisper model downloaded | Critical | Pass/Fail | "Click to download [model size] model" with progress bar |
| HuggingFace token set | Optional | Pass/Warn | "Set in Settings > Transcription" |
| Pyannote models downloaded | Optional | Pass/Fail | "Click to download now" (only if HF token is set) |
| FFmpeg installed | Optional | Pass/Warn | "MP3 export disabled -- install FFmpeg for MP3 support" |
| Windows version | Info | Pass/Warn | "Windows 11 required for per-app capture. Using all system audio." |
| Per-app capture (pycaw) | Info | Pass/Fail | Only checked on Win11 |

### Status Icons

- Pass: Green checkmark
- Warn: Yellow warning (optional feature unavailable)
- Fail: Red X (core functionality missing)

### Implementation

New file: `app/ui/status_panel.py`

- `SystemStatusDialog(QDialog)` with styled check list
- `DependencyChecker` utility class that runs each check and returns results
- Download buttons trigger background `QThread` workers with progress bars
- Integrates with existing dark theme via `style.qss`

---

## Summary of All Changes

### New Files
- `app/recording/process_audio_capture.py` -- Per-process capture via Win11 API
- `app/utils/audio_session_monitor.py` -- Active audio app enumeration via pycaw
- `app/ui/status_panel.py` -- Startup system status dialog
- `app/utils/dependency_checker.py` -- Health check logic

### Modified Files
- `app/ui/source_selector.py` -- Replace loopback dropdown with app picker + legacy toggle
- `app/recording/audio_capture.py` -- `DualAudioCapture` accepts `ProcessAudioCapture` as alternative to `AudioStream`
- `app/main_window.py` -- Wire up status panel, app picker, capture mode toggle
- `app/utils/config.py` -- Add `capture_mode` setting (per-app vs legacy)
- `requirements.txt` -- Add `pycaw`, `comtypes`
- `resources/style.qss` -- Styles for status panel, app picker checklist

### Unchanged Files
- `app/transcription/transcriber.py`
- `app/transcription/diarizer.py`
- `app/ui/transcript_viewer.py`
- `app/ui/notes_panel.py`
- `app/ui/recordings_list.py`
- `app/ui/recording_controls.py`
- `app/recording/recorder.py` (minimal change: pass capture mode)
