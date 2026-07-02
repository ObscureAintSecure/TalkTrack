"""Meeting summary and action item extraction."""

import json
from app.transcription.transcriber import TranscriptSegment


_TRUNCATION_MARKER = "\n[... transcript truncated to fit the model's context ...]\n"


def truncate_transcript(text, max_chars):
    """Cap transcript text, keeping the head and tail.

    Endings matter (action items and decisions cluster late in meetings), so
    a head-only cut like the chat panel's would drop exactly the part the
    action-item prompt needs. 60/40 head/tail split.
    """
    if max_chars is None or len(text) <= max_chars:
        return text
    budget = max_chars - len(_TRUNCATION_MARKER)
    head = int(budget * 0.6)
    tail = budget - head
    return text[:head] + _TRUNCATION_MARKER + text[-tail:]


def _format_transcript(segments, speaker_names, max_chars=None):
    lines = []
    for seg in segments:
        name = speaker_names.get(seg.speaker, seg.speaker) if seg.speaker else "Unknown"
        timestamp = f"[{seg.start:.1f}s]"
        lines.append(f"{timestamp} {name}: {seg.text}")
    return truncate_transcript("\n".join(lines), max_chars)


def _format_notes(notes):
    if not notes or not notes.strip():
        return ""
    return f"\n\nUSER NOTES (taken during the meeting):\n{notes.strip()}"


def _format_instruction(instruction):
    if not instruction or not instruction.strip():
        return ""
    return f"\n\nADDITIONAL INSTRUCTIONS FROM USER:\n{instruction.strip()}"


def build_summary_prompt(segments, speaker_names, notes="", instruction="",
                         max_transcript_chars=None):
    transcript_text = _format_transcript(segments, speaker_names,
                                         max_chars=max_transcript_chars)
    notes_text = _format_notes(notes)
    instruction_text = _format_instruction(instruction)
    return (
        "Below is a transcript of a meeting. Please provide a concise summary "
        "covering: key discussion points, decisions made, and outcomes.\n\n"
        "If user notes are included, incorporate any relevant context from them "
        "into the summary.\n\n"
        "If additional instructions are provided, follow them when generating "
        "the summary.\n\n"
        "Format as markdown with bullet points.\n\n"
        f"TRANSCRIPT:\n{transcript_text}{notes_text}{instruction_text}"
    )


def build_action_items_prompt(segments, speaker_names, notes="", instruction="",
                              max_transcript_chars=None):
    transcript_text = _format_transcript(segments, speaker_names,
                                         max_chars=max_transcript_chars)
    notes_text = _format_notes(notes)
    instruction_text = _format_instruction(instruction)
    return (
        "Below is a transcript of a meeting. Extract all action items — tasks, "
        "follow-ups, or commitments made by participants.\n\n"
        "If user notes are included, also extract any action items from them.\n\n"
        "If additional instructions are provided, follow them when extracting "
        "action items.\n\n"
        "Return a JSON array where each item has:\n"
        '- "task": description of the action item\n'
        '- "assignee": who is responsible (speaker name)\n'
        '- "deadline": mentioned deadline or empty string\n\n'
        "Return ONLY the JSON array, no other text.\n\n"
        f"TRANSCRIPT:\n{transcript_text}{notes_text}{instruction_text}"
    )


def parse_action_items(response):
    text = response.strip()
    # Models wrap the array in fences or prose; extract the outermost [...].
    start = text.find("[")
    end = text.rfind("]") + 1
    if start >= 0 and end > start:
        text = text[start:end]
    try:
        items = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(items, list):
        return []
    cleaned = []
    for item in items:
        if not isinstance(item, dict) or not item.get("task"):
            continue
        cleaned.append({
            "task": str(item.get("task", "")),
            "assignee": str(item.get("assignee") or ""),
            "deadline": str(item.get("deadline") or ""),
        })
    return cleaned
