# TalkTrack UX & AI Improvements Design

**Date:** 2026-03-08
**Status:** Approved
**Approach:** Phase 1 (UX) first, then Phase 2 (AI) — Approach A

## Overview

Two-phase improvement plan for TalkTrack:
- **Phase 1:** UX refinements — audio level meters, live waveform, transcript editing upgrades
- **Phase 2:** AI superpowers — meeting summaries, action items, searchable history, chat with transcript, configurable AI backend (local vs cloud)
- **Bonus:** Buy Me a Coffee donation link (GitHub + in-app)

---

## Phase 1: UX Refinement

### 1A. Audio Level Meters

Real-time VU meters for mic and system audio in the left panel.

- Two horizontal bar meters stacked below the source selector ("Mic" and "System/App")
- Color gradient: green -> yellow -> red as level increases
- Updates ~20 times/sec from audio callback (receives raw numpy chunks)
- Peak hold indicator (briefly holds max level, then decays)
- When not recording: idle state (gray)
- New `LevelMeter` QWidget receives RMS values via signal from `DualAudioCapture`

**Files:** New `app/ui/level_meter.py`, minor changes to `DualAudioCapture`, wire into `main_window.py`.

### 1B. Live Waveform During Recording

Scrolling waveform visualization showing audio being captured in real-time.

- Horizontal waveform strip (~80px tall) between level meters and recording controls
- Shows last ~5 seconds of combined audio as a rolling waveform
- Ring buffer of recent samples, painted with QPainter
- Updates at ~15fps (repaint timer, not every audio callback)
- Pauses when recording paused, resumes when resumed
- Hidden when not recording

**Files:** New `app/ui/waveform_display.py`, fed from same audio callback as level meters.

### 1C. Transcript Editing Upgrades

Proper undo/redo and find/replace for transcript text.

**Undo/redo:**
- Edit history stack per segment, max 20 levels deep
- Ctrl+Z undoes last edit, Ctrl+Shift+Z redoes
- Existing `original_text` becomes the first entry in history

**Find/replace:**
- Collapsible toolbar at top of transcript viewer (Ctrl+F to open)
- Searches across all segments, highlights matches, next/prev navigation
- Replace operates on currently highlighted segment
- Optional regex support

**Files:** Edit history logic in `SegmentWidget`, new `TranscriptSearchBar` widget in `transcript_viewer.py`.

---

## Phase 2: AI Superpowers

### 2A. AI Backend Abstraction

Provider system allowing users to choose between local models and cloud APIs.

**Interface:**
- `AIProvider` base class: `complete(prompt, context) -> str` and `embed(texts) -> list[list[float]]`
- Cloud providers: Claude API (`anthropic` SDK), OpenAI API. User enters API key.
- Local provider: `llama-cpp-python` for completions, `sentence-transformers` for embeddings. User selects model file.
- `AIProviderFactory` returns configured provider based on settings.

**Settings:**
- New "AI Assistant" tab in Settings dialog
- Provider dropdown, API key input, model selection, test connection button

**Execution:**
- All AI features call provider abstraction, never a specific API directly
- Provider runs in QThread workers (same pattern as transcription)

**Files:** New `app/ai/` package: `provider.py`, `claude_provider.py`, `openai_provider.py`, `local_provider.py`, `provider_factory.py`. New settings tab.

### 2B. Meeting Summaries & Action Items

Auto-generate summary and extract action items after transcription.

**Trigger:** Automatically after transcription + diarization (disableable in settings).

**Output:**
- Summary: key points, decisions, outcomes -> `summary.md` in session directory
- Action items: task, assignee (speaker), deadline if mentioned -> `action_items.json`

**UI:**
- Two new sub-tabs under Transcript tab: "Summary" and "Action Items"
- Summary: rendered markdown, copy button, regenerate button
- Action Items: checklist with speaker, task text, checkbox for manual tracking
- Both editable after generation, persisted to disk
- "Regenerate" re-runs AI with current transcript

**Files:** New `app/ai/summarizer.py`, new `SummaryPanel` and `ActionItemsPanel` widgets.

### 2C. Searchable History

Search bar in left panel searching across all past recordings.

**UI:** Search box above recordings list in left panel.

**Two modes** (toggled by button):
- Text search: substring/keyword match across all `transcript.json` files. Fast, no AI needed.
- Semantic search: embeds query via provider's `embed()`, compares against pre-computed segment embeddings.

**Results:** Appear in-place replacing recordings list. Each shows: recording name, timestamp, matching snippet, relevance score. Click -> loads recording, scrolls to segment.

**Embedding index:**
- Built on first use or on demand
- Stored as `~/.talktrack/search_index.json`
- Incrementally updated when new recordings transcribed
- Falls back to text-only if no AI provider configured

**Files:** New `app/ai/search_index.py`, new `SearchBar` widget, modifications to `recordings_list.py`.

### 2D. Chat With Transcript

Persistent chat panel for asking questions about the current recording.

**UI:** New "Chat" tab alongside Transcript and Notes in right panel. Standard chat UI: message history, text input, send button.

**Context:** Sends current transcript with speaker names. For long transcripts: chunks + embedding retrieval for relevant segments (RAG-lite).

**Example queries:**
- "Summarize what Alice said about the budget"
- "When did we discuss the deadline?"
- "What were the main disagreements?"

**Persistence:** Chat history per recording in `chat_history.json`.

**Fallback:** Shows setup prompt if no AI provider configured.

**Files:** New `app/ai/chat.py`, new `ChatPanel` widget.

---

## Bonus: Buy Me a Coffee

### External Setup
1. Create account at buymeacoffee.com
2. Configure page (name, profile pic, default price)
3. Get URL: `https://buymeacoffee.com/<username>`

### GitHub Integration
- `.github/FUNDING.yml` with Buy Me a Coffee username -> renders Sponsor button on repo
- Badge + link in README.md

### In-App Integration
- **Help > About TalkTrack** dialog: app name, version, description, donation button (opens in browser)
- **Help > Support TalkTrack** menu item: opens donation link directly in browser

**Files:** New `app/ui/about_dialog.py`, changes to `main_window.py` Help menu, new `.github/FUNDING.yml`, README update.

---

## Architecture Summary

### New Files
```
app/
  ai/
    __init__.py
    provider.py            # AIProvider base class
    claude_provider.py     # Claude API implementation
    openai_provider.py     # OpenAI API implementation
    local_provider.py      # llama-cpp-python + sentence-transformers
    provider_factory.py    # Factory for configured provider
    summarizer.py          # Summary + action item generation
    search_index.py        # Embedding index + retrieval
    chat.py                # Chat context assembly + provider calls
  ui/
    level_meter.py         # VU meter widget
    waveform_display.py    # Rolling waveform widget
    about_dialog.py        # About TalkTrack dialog
.github/
  FUNDING.yml              # GitHub Sponsors/BMAC config
```

### Modified Files
```
app/main_window.py         # Wire new widgets, Help menu items
app/ui/settings_dialog.py  # New AI Assistant tab
app/ui/transcript_viewer.py # Search bar, summary/action/chat tabs
app/ui/segment_widget.py   # Undo/redo history
app/ui/recordings_list.py  # Search integration
app/recording/audio_capture.py # Level signals
requirements.txt           # New deps (anthropic, llama-cpp-python, etc.)
README.md                  # BMAC badge
```

### New Dependencies
- `anthropic` — Claude API SDK
- `openai` — OpenAI API SDK
- `llama-cpp-python` — Local LLM inference (optional)
- `sentence-transformers` — Local embeddings (already a transitive dep of pyannote)

### Data Files Per Recording
```
recording_YYYYMMDD_HHMMSS/
  ... (existing files) ...
  summary.md               # AI-generated summary
  action_items.json         # Extracted action items
  chat_history.json         # Chat conversation history
```

### Global Data
```
~/.talktrack/
  settings.json            # Existing + AI provider config
  search_index.json        # Embedding index across all recordings
```

---

## Build Sequence

1. **Phase 1A:** Audio level meters
2. **Phase 1B:** Live waveform display
3. **Phase 1C:** Transcript editing (undo/redo + find/replace)
4. **Bonus:** Buy Me a Coffee (GitHub + in-app)
5. **Phase 2A:** AI backend abstraction + settings tab
6. **Phase 2B:** Meeting summaries + action items
7. **Phase 2C:** Searchable history
8. **Phase 2D:** Chat with transcript
