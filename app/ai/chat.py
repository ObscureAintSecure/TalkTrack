"""Chat with transcript functionality."""

from app.transcription.transcriber import TranscriptSegment

MAX_CONTEXT_CHARS = 12000


def build_chat_context(segments, speaker_names):
    lines = []
    total = 0
    header = (
        "You are a helpful assistant. The user is asking about a meeting transcript. "
        "Answer based on the transcript content below.\n\n"
        "TRANSCRIPT:\n"
    )
    total += len(header)

    for seg in segments:
        name = speaker_names.get(seg.speaker, seg.speaker) if seg.speaker else "Unknown"
        line = f"[{seg.start:.1f}s] {name}: {seg.text}"
        if total + len(line) + 1 > MAX_CONTEXT_CHARS:
            lines.append("... (transcript truncated)")
            break
        lines.append(line)
        total += len(line) + 1

    return header + "\n".join(lines)


def format_chat_prompt(question, history=None):
    parts = []
    if history:
        for msg in history[-6:]:
            role = "User" if msg["role"] == "user" else "Assistant"
            parts.append(f"{role}: {msg['content']}")
    parts.append(f"User: {question}")
    return "\n\n".join(parts)
