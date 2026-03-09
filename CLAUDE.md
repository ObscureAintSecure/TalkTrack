# TalkTrack - CLAUDE.md

## Project Overview

TalkTrack is a Windows desktop application that records, transcribes, and diarizes audio from calls (Teams, Zoom, etc.). It is a modern clone of Evaer for Teams with AI-powered transcription and speaker identification.

## Tech Stack

- **GUI:** PyQt6
- **Audio Capture:** sounddevice + WASAPI, comtypes (Win11 per-process capture)
- **Audio Session Enumeration:** pycaw (Windows Core Audio API)
- **Transcription:** faster-whisper (local OpenAI Whisper, no internet needed)
- **Speaker Diarization:** pyannote.audio 4.0 (requires free HuggingFace token)
- **Deep Learning:** torch, torchaudio
- **Audio Processing:** scipy, pydub, soundfile, numpy
- **Process Detection:** psutil (for known audio app enumeration)
- **NLP/Embeddings:** transformers, sentence-transformers (pyannote dependencies)
- **Windows Integration:** pywin32, comtypes

## Project Structure

```
TalkTrack/
  main.py                              # Entry point, QApplication setup
  requirements.txt                     # Dependencies
  app/
    main_window.py                     # Main window + orchestration
    audio/
      __init__.py                      # Package init
      segment_player.py               # Audio clip playback for transcript segments
    recording/
      audio_capture.py                 # AudioStream, DualAudioCapture (legacy + per-app modes)
      process_audio_capture.py         # ProcessCaptureStream, ProcessAudioCapture (Win11 per-PID)
      recorder.py                      # State machine, session management
    transcription/
      transcriber.py                   # Whisper worker + dataclasses
      diarizer.py                      # Speaker diarization (pyannote)
    ai/
      __init__.py                      # Package init
      provider.py                      # AIProvider base class
      claude_provider.py               # Claude API implementation
      openai_provider.py               # OpenAI API implementation
      local_provider.py                # Local model (llama-cpp-python)
      provider_factory.py              # Factory for configured provider
      summarizer.py                    # Meeting summary + action items
      search_index.py                  # Transcript search + embeddings
      chat.py                          # Chat context builder
    ui/
      source_selector.py              # Mic dropdown + per-app picker (Win11) or legacy loopback (Win10)
      recording_controls.py           # Record/Pause/Stop buttons + timer
      recording_header.py             # Recording info display with rename
      segment_widget.py               # Interactive transcript segment row
      settings_dialog.py              # Settings dialog with tabs
      speaker_name_panel.py           # Collapsible speaker name mapping panel
      status_panel.py                 # System status dialog (dependency health checks)
      transcript_viewer.py            # Display + export transcripts (with interactive segments)
      notes_panel.py                  # Call notes with timestamps
      recordings_list.py              # Past recordings browser
      level_meter.py                   # Real-time audio level meters
      waveform_display.py             # Live waveform visualization
      transcript_search_bar.py        # Find/replace for transcripts
      search_bar.py                    # Recordings search bar
      summary_panel.py                 # AI meeting summary display
      action_items_panel.py            # AI action items display
      chat_panel.py                    # Chat with transcript panel
      about_dialog.py                  # About dialog with donation link
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
    test_transcriber.py               # TranscriptSegment/TranscriptResult tests
    test_segment_player.py            # Audio clip playback tests
    test_recording_header.py          # RecordingHeader helper tests
    test_speaker_name_panel.py        # SpeakerNamePanel helper tests
    test_segment_widget.py            # SegmentWidget helper tests
    test_level_meter.py                # Audio level meter tests
    test_waveform_display.py           # Waveform ring buffer tests
    test_edit_history.py               # Undo/redo history tests
    test_transcript_search_bar.py      # Find/replace logic tests
    test_ai_provider.py                # AI provider factory tests
    test_summarizer.py                 # Summary prompt builder tests
    test_search_index.py               # Transcript search tests
    test_chat.py                       # Chat context builder tests
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
- **Interactive transcript viewer:** per-segment audio playback, inline text editing, speaker name mapping
- **Speaker naming:** assign friendly names to diarized speakers, saved per recording
- **Recording header:** shows loaded recording info (name, date, duration, speakers) with rename
- Color-coded transcript with speaker labels and timestamps
- Export transcript to TXT, SRT (subtitles), or JSON with speaker names
- Call notes with timestamp insertion
- Browse and replay past recordings (with friendly names)
- Settings for model size, sample rate, output format (WAV/MP3)
- Dark theme UI (Catppuccin Mocha palette)
- **Audio level meters:** real-time VU meters for mic and system audio during recording
- **Live waveform:** scrolling waveform visualization during recording
- **Transcript find/replace:** Ctrl+F search across all segments with regex support
- **Transcript undo/redo:** per-segment edit history with context menu
- **AI meeting summaries:** auto-generated after transcription (configurable provider)
- **AI action items:** extracted tasks with assignees and deadlines
- **Searchable history:** text and semantic search across all past recordings
- **Chat with transcript:** ask AI questions about the current recording
- **AI provider choice:** Claude, OpenAI, or local models via Settings > AI Assistant
- **About dialog:** version info and Buy Me a Coffee donation link

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
- `audio_session_monitor.py` uses pycaw + psutil to enumerate audio apps
- Two sources: pycaw (apps with active audio sessions) + psutil (known audio apps like Teams/Zoom even when not in a call)
- Groups by display name (deduplicates multi-process apps like Zoom)
- Returns `{"pids": [int], "name": str, "process_name": str, "active": bool}`
- Auto-refreshes every 3 seconds in the UI

### Recording Pipeline
- State machine: IDLE -> RECORDING -> PAUSED <-> RECORDING -> STOPPING -> IDLE
- Each recording gets timestamped directory with audio files + metadata.json
- Metadata includes capture_mode and app_pids
- Transcription/diarization runs in separate QThread workers

### System Status Panel
- `DependencyChecker` runs health checks: mic, WASAPI, GPU/CUDA, Whisper model, HF token, pyannote, FFmpeg, Windows version
- GPU check detects NVIDIA GPU via torch or nvidia-smi, warns if CUDA PyTorch not installed
- `SystemStatusDialog` shows results with actionable fix suggestions
- Auto-shows on startup if critical checks fail
- Accessible via Help > System Status
- Settings dialog shows inline GPU status when CUDA is selected as compute device

### Transcript Enhancement Suite
- `SegmentWidget`: Interactive row per transcript segment — play button, timestamp, speaker label (clickable), editable text, edit indicator
- `SpeakerNamePanel`: Collapsible panel mapping speaker IDs (e.g., SPEAKER_00) to friendly names, with color swatches
- `RecordingHeader`: Shows loaded recording info with inline rename capability
- `SegmentPlayer`: Plays audio clips for individual segments using sounddevice, caches loaded audio
- Speaker names stored per recording in `speaker_names.json`, separate from `transcript.json`
- `TranscriptSegment.original_text` tracks pre-edit text for undo support
- Signal flow: SegmentWidget → TranscriptViewer → MainWindow (saves to disk)

### AI Provider System
- Pluggable provider abstraction: `AIProvider` base class with `complete()` and `embed()` methods
- Three implementations: Claude (Anthropic SDK), OpenAI, Local (llama-cpp-python + sentence-transformers)
- Factory pattern via `create_provider(config)` — returns configured provider or None
- All providers run in QThread workers to avoid UI blocking
- Settings tab for provider selection, API keys, and model configuration
- Auto-summarize after transcription (disableable in settings)
- Chat history persisted per recording as `chat_history.json`
- Search index uses text matching (no AI needed) or semantic embeddings

### Configuration
- Stored at ~/.talktrack/settings.json
- Audio settings: sample_rate, channels, capture_mode ("legacy" or "per_app")
- Audio device selection is per-session (not persisted)
- Transcription settings: model size (tiny/base/small/medium/large-v3), language, compute device
- AI settings: provider (none/claude/openai/local), api_key, model, auto_summarize

### Data Files Per Recording
- summary.md: AI-generated meeting summary
- action_items.json: Extracted action items with assignees
- chat_history.json: Chat conversation history

## Setup Instructions

### Basic Setup
```bash
pip install -r requirements.txt
python main.py
```

### For Full Speaker Diarization (Optional)
1. Get a free HuggingFace token at https://huggingface.co/settings/tokens
2. Accept the pyannote model terms at:
   - https://huggingface.co/pyannote/speaker-diarization-community-1
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

## Platform Workarounds

- **PyQt6 + PyTorch DLL conflict:** QApplication modifies Windows DLL search order, breaking torch's c10.dll loading in QThreads. Fixed by calling `os.add_dll_directory(torch/lib)` before QApplication init (in main.py).
- **torchcodec not available on Windows:** pyannote.audio 4.0 uses torchcodec for audio decoding, which requires FFmpeg DLLs. Workaround: pre-load audio via soundfile and pass as `{"waveform": tensor, "sample_rate": int}` dict to pyannote pipeline.
- **torchcodec warning suppression:** `warnings.filterwarnings("ignore", module=r"pyannote\.audio\.core\.io")` in main.py.
- **PyQt6 QListWidget truthiness:** Empty QListWidget evaluates as falsy in PyQt6. Always use `is None` / `is not None` checks, never `if widget:` / `if not widget:`.

## Known Limitations

- **Per-process COM capture is scaffolded:** The `ProcessCaptureStream._read_audio_packets()` method is a pipeline placeholder. The COM initialization structure is in place but the actual `IAudioCaptureClient.GetBuffer()` packet reading needs to be completed with real audio testing on Windows 11.
- **Windows only:** Uses WASAPI and Windows COM APIs
- **Per-app capture requires Windows 11 Build 22000+**
