"""Search index for transcript history."""

import json
import re
from pathlib import Path


def load_all_transcripts(recordings_dir):
    """Load all transcripts from the recordings directory.

    Returns a dict mapping recording directory name to list of segment dicts.
    """
    transcripts = {}
    if not recordings_dir.exists():
        return transcripts
    for entry in recordings_dir.iterdir():
        if not entry.is_dir():
            continue
        transcript_path = entry / "transcript.json"
        if not transcript_path.exists():
            continue
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            segments = data.get("segments", [])
            transcripts[entry.name] = segments
        except (json.JSONDecodeError, OSError):
            continue
    return transcripts


def text_search(query, transcripts):
    """Search transcripts for segments containing the query string.

    Case-insensitive keyword search across all transcript segments.
    Returns a list of result dicts with recording_id, text, start, speaker.
    """
    results = []
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    for rec_id, segments in transcripts.items():
        for seg in segments:
            text = seg.get("text", "")
            if pattern.search(text):
                results.append({
                    "recording_id": rec_id,
                    "text": text,
                    "start": seg.get("start", 0.0),
                    "speaker": seg.get("speaker", ""),
                })
    return results


def semantic_search(query, transcripts, provider, recordings_dir=None):
    """Search transcripts using semantic similarity via an AI provider.

    Computes cosine similarity between the query and all transcript
    segments. When recordings_dir is given, per-recording embedding caches
    (#33) are used so only new/changed segments are embedded. Returns top
    results above threshold.
    """
    per_recording = []   # (rec_dir or None, [texts])
    corpus_meta = []
    for rec_id, segments in transcripts.items():
        texts = []
        for seg in segments:
            text = seg.get("text", "").strip()
            if text:
                texts.append(text)
                corpus_meta.append({
                    "recording_id": rec_id,
                    "text": text,
                    "start": seg.get("start", 0.0),
                    "speaker": seg.get("speaker", ""),
                })
        if texts:
            rec_dir = Path(recordings_dir) / rec_id if recordings_dir else None
            per_recording.append((rec_dir, texts))
    if not corpus_meta:
        return []

    import numpy as np
    from app.ai.embedding_cache import get_corpus_vectors
    query_emb = np.array(provider.embed([query])[0])
    corpus_embs = np.vstack([
        get_corpus_vectors(rec_dir, texts, provider)
        for rec_dir, texts in per_recording
    ])

    query_norm = query_emb / (np.linalg.norm(query_emb) + 1e-10)
    corpus_norms = corpus_embs / (np.linalg.norm(corpus_embs, axis=1, keepdims=True) + 1e-10)
    similarities = corpus_norms @ query_norm

    top_indices = np.argsort(similarities)[::-1][:20]
    results = []
    for idx in top_indices:
        if similarities[idx] > 0.3:
            result = dict(corpus_meta[idx])
            result["score"] = float(similarities[idx])
            results.append(result)
    return results
