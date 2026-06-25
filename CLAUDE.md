# TalkTrack - CLAUDE.md

## Project Rules

Topic-specific rules are in `.claude/rules/`. `ways-of-working.md` is always loaded; the others are loaded on demand by topic.

@./.claude/rules/ways-of-working.md

- [audio-pipeline.md](.claude/rules/audio-pipeline.md) — AudioStream callback order, mute/gain scoping, MainWindow→capture access pattern.
- [per-app-audio-capture.md](.claude/rules/per-app-audio-capture.md) — Windows 11 process-loopback COM invariants (IAgileObject, device path, ctypes arg passing, generator caching gotcha).
- [ui-patterns.md](.claude/rules/ui-patterns.md) — CollapsibleSection, left-panel conventions, DAW meter fill direction, peak-sample bar semantics, Qt QSS gotchas, Catppuccin palette.

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
  start.bat                            # Launcher (uv-first, .venv isolation, falls back to pip)
  start_debug.bat                      # Debug launcher with console output
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
      grok_provider.py                 # Grok (xAI) via OpenAI-compatible API
      gemini_provider.py               # Google Gemini API implementation
      mistral_provider.py              # Mistral AI API implementation
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
  resources/
    style.qss                          # Dark theme stylesheet (Catppuccin Mocha)
    talktrack.ico                      # App icon (multi-size: 16-256px)
    build_ico.py                       # Rebuild .ico from source PNGs
    generate_icon.py                   # Old programmatic icon generator (deprecated)
    favicon.ico                        # Favicon for web use
    TT_icon_*.png                      # Icon source files (32, 64, 128, 256, 512px)
    TT_logo_*.png                      # Logo files (655x200, 1300x400)
  docs/plans/                         # Design docs and implementation plans
  recordings/                         # Output directory
```

## Current Features

- Record / Pause / Resume / Stop controls with live timer
- **Per-app audio capture (Win11):** select specific apps (Teams, Chrome, etc.) to record
- **Legacy system audio capture:** WASAPI loopback for all system audio (Win10 or fallback)
- Dual audio capture: microphone (your voice) + system/app audio
- **Dual microphone support:** optionally use 2 mics simultaneously (e.g., desk mic + headset), mixed into one track
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
- **AI meeting summaries:** auto-generated after transcription (configurable provider), manual generate/regenerate
- **AI action items:** extracted tasks with assignees and deadlines, manual generate/regenerate
- **Notes in AI context:** user call notes included in AI summary and action item prompts
- **Per-provider AI settings:** API keys and models stored separately per provider with status indicator
- **Searchable history:** text and semantic search across all past recordings
- **Chat with transcript:** ask AI questions about the current recording
- **AI provider choice:** Claude, OpenAI, Grok, Gemini, Mistral, or local models via Settings > AI Assistant
- **Hidden devices filter:** hide unwanted audio devices (e.g., Voicemeeter) from dropdowns
- **Capture settings persistence:** remembers capture mode (per-app vs legacy) and selected apps
- **Min duration filter:** skip auto-transcription for short recordings (configurable in Settings)
- **Multi-select bulk delete:** select multiple recordings and delete at once (Ctrl/Shift+click)
- **Custom app icon:** Start Menu shortcut (offered on first run) targets the venv interpreter and carries the icon + AppUserModelID for a correct taskbar icon
- **About dialog:** version info and Buy Me a Coffee donation link
- **Silence auto-stop:** monitors system/app audio (not mic) for sustained silence, auto-stops recording after configurable duration (Settings > General)
- **Continue from here:** checkbox next to Play All — click any segment to start continuous playback from that point
- **Smart scroll during playback:** auto-scroll to playing segment is suppressed if user has manually scrolled away

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
- Six implementations: Claude, OpenAI, Grok (xAI), Gemini (Google), Mistral, Local (llama-cpp-python)
- Factory pattern via `create_provider(config)` — returns configured provider or None
- AI SDK packages installed on-demand when user selects a provider (not bundled in requirements.txt)
- Ad-hoc installer prompts user before installing, shows progress in settings dialog
- All providers run in QThread workers to avoid UI blocking
- Per-provider settings: API keys and models stored in `provider_settings` dict, keyed by provider name
- API key status indicator in settings shows "API key configured (first4...last4)" or "No API key set"
- Settings tab for provider selection, API keys, and model configuration
- Auto-summarize after transcription (disableable in settings), with manual generate/regenerate buttons
- User call notes included in summary and action item AI prompts via `build_summary_prompt(segments, speaker_names, notes="")`
- Chat history persisted per recording as `chat_history.json`
- Search index uses text matching (no AI needed) or semantic embeddings

### Configuration
- Stored at ~/.talktrack/settings.json
- Audio settings: sample_rate, channels, capture_mode ("legacy" or "per_app"), selected_apps, hidden_devices, mic_count (1 or 2)
- Audio device selection is per-session (not persisted), but capture mode and selected apps are persisted
- Transcription settings: model size (tiny/base/small/medium/large-v3), language, compute device, min_duration
- AI settings: provider (none/claude/openai/grok/gemini/mistral/local), provider_settings (per-provider api_key/model), auto_summarize
- General settings: min_recording_length, auto_record, silence_auto_stop, silence_duration

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
- **WASAPI device index mismatch:** `sd.default.device[1]` returns DirectSound/MME index that doesn't match WASAPI device indices. `get_default_output()` matches by device name instead of index.
- **Microsoft Store Python AppUserModelID / taskbar icon:** Store-packaged Python's `pythonw` is an execution alias that overrides `SetCurrentProcessExplicitAppUserModelID` and can't be a shortcut target, so the taskbar shows the generic Python icon. Workaround: the app offers (on first run, or Help > Add to Start Menu via `app/utils/start_menu.py`) a Start Menu shortcut that targets the **venv** `pythonw` (`.venv\Scripts\pythonw.exe`, a real binary) and carries `talktrack.ico` + the `TalkTrack.TalkTrack.1` AppUserModelID. main.py sets the matching per-window AppUserModelID, so Windows resolves the shortcut's icon onto the taskbar. No PyInstaller/exe build needed.

## Known Limitations

- **Windows only:** Uses WASAPI and Windows COM APIs
- **Per-app capture requires Windows 11 Build 22000+**
