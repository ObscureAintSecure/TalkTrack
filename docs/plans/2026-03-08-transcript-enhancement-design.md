# Transcript Enhancement Suite — Design Document

**Date:** 2026-03-08
**Status:** Approved

## Overview

Four interrelated features that transform the transcript viewer from a read-only display into an interactive editing and review tool.

1. **Speaker Name Assignment** — Map SPEAKER_00/01/etc. to real names
2. **Inline Transcript Editing** — Fix misheard words, acronyms, etc.
3. **Audio Clip Playback** — Play the audio for any segment to verify accuracy
4. **Recording Info Header + Rename** — Show which recording is loaded, give it a friendly name

## Feature 1: Speaker Name Assignment

### Behavior

- Collapsible "Speakers" panel above the transcript body
- One row per detected speaker: color swatch, original ID, editable name field
- Editing a name instantly re-renders transcript and auto-saves
- Empty name fields show the original speaker ID (no pressure to name everyone)
- Clicking a speaker label in the transcript body focuses its name field
- Panel only visible when transcript has speaker labels

### Storage

`speaker_names.json` in the session directory, separate from transcript.json:

```json
{"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"}
```

Names are an overlay — original speaker IDs preserved in transcript.json.

### Export Integration

- TXT/SRT exports use friendly names when available, fall back to original IDs
- JSON export includes both `speaker` (original) and `speaker_name` (friendly) fields

## Feature 2: Inline Transcript Editing

### Behavior

- Double-click a segment's text to enter edit mode (inline QLineEdit)
- Press Enter to confirm, Escape to cancel
- Right-click context menu: "Revert to Original" restores original text
- Subtle visual indicator on edited segments (e.g., small pencil icon or italic styling)

### Storage

Edit-in-place with undo field. When a segment is edited, `original_text` is saved:

```json
{
  "start": 83.0,
  "end": 105.0,
  "text": "The Q4 results look promising",
  "original_text": "The quarterly results look promising",
  "speaker": "SPEAKER_00"
}
```

`original_text` only exists on segments that have been edited. Reverting removes the field.

## Feature 3: Audio Clip Playback

### Behavior

- Small play button at the start of each segment row
- Click play: loads audio from start to end timestamps, plays via sounddevice
- Button changes to stop icon while playing
- Clicking another play or the stop button stops current clip
- Uses sounddevice (already installed) + soundfile (already installed)

### Implementation

Lightweight `SegmentPlayer` helper class:

```python
class SegmentPlayer:
    """Plays audio clips for transcript segments using sounddevice."""

    def play_segment(self, audio_path, start_sec, end_sec): ...
    def stop(self): ...
    def is_playing(self) -> bool: ...
```

- Loads full audio file once (cached), extracts segment by sample range
- Plays via `sounddevice.play(data, samplerate)`
- Emits signal when playback finishes (for button state reset)

## Feature 4: Recording Info Header + Rename

### Behavior

Header bar at the top of the right panel (above tabs):

```
Sprint Planning Meeting                    [Rename]
2024-03-08 14:30  |  Duration: 45m 12s  |  3 speakers
```

- Shows recording name (defaults to timestamp-based folder name if no custom name)
- Date, duration, speaker count
- "Rename" button enables inline editing of the name
- Hidden when no recording is loaded

### Storage

New `name` field in the existing `metadata.json`:

```json
{
  "name": "Sprint Planning Meeting",
  "started_at": "2024-03-08T14:30:00",
  ...
}
```

### Recordings List Integration

- Left-panel recordings list shows friendly name when set
- Falls back to date/time display if no name

## Widget Architecture

Replace the current `QTextEdit` in `TranscriptViewer` with individual segment widgets:

```
TranscriptViewer (QWidget)
  +-- RecordingHeader (QWidget) -- name, date, duration, rename
  +-- SpeakerNamePanel (QWidget, collapsible) -- speaker-to-name mapping
  +-- QScrollArea
       +-- QWidget (container)
            +-- SegmentWidget[0] -- [play] [timestamp] [speaker] [text]
            +-- SegmentWidget[1] -- [play] [timestamp] [speaker] [text]
            +-- ...
```

### SegmentWidget

A horizontal row widget containing:

- **Play button** (QPushButton, small square, ">" or "stop" icon)
- **Timestamp label** (QLabel, monospace, gray) — "[00:01:23 > 00:01:45]"
- **Speaker label** (QLabel, colored, bold, clickable via mousePressEvent)
- **Text display** (QLabel normally, QLineEdit when editing via double-click)
- **Edit indicator** (small icon, only visible if `original_text` exists)

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `app/ui/transcript_viewer.py` | Rewrite | Replace QTextEdit with scroll area layout, integrate sub-components |
| `app/ui/segment_widget.py` | New | Individual transcript segment row widget |
| `app/ui/speaker_name_panel.py` | New | Collapsible speaker name editing panel |
| `app/ui/recording_header.py` | New | Recording info display + rename |
| `app/audio/segment_player.py` | New | Audio clip playback via sounddevice |
| `app/transcription/transcriber.py` | Modify | Add `original_text` to TranscriptSegment, update exports to use speaker names |
| `app/main_window.py` | Modify | Load/save speaker_names.json, pass metadata to viewer, handle rename |
| `app/ui/recordings_list.py` | Modify | Show friendly name in list when available |
| Tests | New | Tests for name mapping, export with names, edit with undo, segment player |

## Out of Scope (YAGNI)

- Cross-session speaker recognition / voice fingerprinting
- Voice sample auto-matching
- Drag-and-drop speaker reassignment per segment
- Waveform visualization
- Batch find-and-replace in transcript
- Merge/split segments
