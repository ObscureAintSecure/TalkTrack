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


def build_summary_prompt(segments, speaker_names):
    transcript_text = _format_transcript(segments, speaker_names)
    return (
        "Below is a transcript of a meeting. Please provide a concise summary "
        "covering: key discussion points, decisions made, and outcomes.\n\n"
        "Format as markdown with bullet points.\n\n"
        f"TRANSCRIPT:\n{transcript_text}"
    )


def build_action_items_prompt(segments, speaker_names):
    transcript_text = _format_transcript(segments, speaker_names)
    return (
        "Below is a transcript of a meeting. Extract all action items — tasks, "
        "follow-ups, or commitments made by participants.\n\n"
        "Return a JSON array where each item has:\n"
        '- "task": description of the action item\n'
        '- "assignee": who is responsible (speaker name)\n'
        '- "deadline": mentioned deadline or empty string\n\n'
        "Return ONLY the JSON array, no other text.\n\n"
        f"TRANSCRIPT:\n{transcript_text}"
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
