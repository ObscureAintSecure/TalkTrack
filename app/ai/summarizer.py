"""Meeting summary and action item extraction."""

import json
from app.transcription.transcriber import TranscriptSegment


def _format_transcript(segments, speaker_names):
    lines = []
    for seg in segments:
        name = speaker_names.get(seg.speaker, seg.speaker) if seg.speaker else "Unknown"
        timestamp = f"[{seg.start:.1f}s]"
        lines.append(f"{timestamp} {name}: {seg.text}")
    return "\n".join(lines)


def _format_notes(notes):
    if not notes or not notes.strip():
        return ""
    return f"\n\nUSER NOTES (taken during the meeting):\n{notes.strip()}"


def build_summary_prompt(segments, speaker_names, notes=""):
    transcript_text = _format_transcript(segments, speaker_names)
    notes_text = _format_notes(notes)
    return (
        "Below is a transcript of a meeting. Please provide a concise summary "
        "covering: key discussion points, decisions made, and outcomes.\n\n"
        "If user notes are included, incorporate any relevant context from them "
        "into the summary.\n\n"
        "Format as markdown with bullet points.\n\n"
        f"TRANSCRIPT:\n{transcript_text}{notes_text}"
    )


def build_action_items_prompt(segments, speaker_names, notes=""):
    transcript_text = _format_transcript(segments, speaker_names)
    notes_text = _format_notes(notes)
    return (
        "Below is a transcript of a meeting. Extract all action items — tasks, "
        "follow-ups, or commitments made by participants.\n\n"
        "If user notes are included, also extract any action items from them.\n\n"
        "Return a JSON array where each item has:\n"
        '- "task": description of the action item\n'
        '- "assignee": who is responsible (speaker name)\n'
        '- "deadline": mentioned deadline or empty string\n\n'
        "Return ONLY the JSON array, no other text.\n\n"
        f"TRANSCRIPT:\n{transcript_text}{notes_text}"
    )


def parse_action_items(response):
    text = response.strip()
    if "```" in text:
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            text = text[start:end]
    try:
        items = json.loads(text)
        if isinstance(items, list):
            return items
    except (json.JSONDecodeError, ValueError):
        pass
    return []
