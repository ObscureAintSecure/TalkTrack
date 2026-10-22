"""Name suggestions for the Speakers panel: the names already given elsewhere.

Typing a speaker's name from scratch in every recording ends with one person
under several spellings ("Fabio", "Fábio Feti", "fabio ferreira"), which splits
search, summaries and anything keyed by name. The panel offers the names
already used in other recordings instead.

No Qt here, so the ranking and matching stay testable.
"""

import json
import logging
import unicodedata
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

NAMES_FILE = "speaker_names.json"
MAX_SUGGESTIONS = 10


def fold(text):
    """Lowercase, accent-free, single-spaced: "  Fábio  Feti" -> "fabio feti"."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(plain.casefold().split())


def known_speaker_names(recordings_dir, extra_names=()):
    """Every speaker name used in the recordings, most used first.

    Spellings that differ only in case, accents or spacing count as one name,
    shown with the spelling used most (the latest recording breaks ties).
    ``extra_names`` (e.g. voice profile names) are added once each.
    """
    usage = Counter()      # folded -> recordings using it
    spellings = {}         # folded -> Counter(spelling -> recordings)
    last_seen = {}         # (folded, spelling) -> recording order
    root = Path(recordings_dir) if recordings_dir else None
    files = sorted(root.glob(f"*/{NAMES_FILE}")) if root and root.is_dir() else []
    for order, path in enumerate(files):
        for name in set(_read_names(path)):
            key = fold(name)
            usage[key] += 1
            spellings.setdefault(key, Counter())[name] += 1
            last_seen[(key, name)] = order
    for name in extra_names:
        name = " ".join((name or "").split())
        key = fold(name)
        if key and key not in spellings:
            usage[key] += 1
            spellings[key] = Counter({name: 1})
            last_seen[(key, name)] = -1

    def best_spelling(key):
        return max(spellings[key], key=lambda s: (spellings[key][s], last_seen[(key, s)]))

    ranked = sorted(usage, key=lambda k: (-usage[k], k))
    return [best_spelling(k) for k in ranked]


def _read_names(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        logger.debug("Skipping unreadable %s", path, exc_info=True)
        return []
    if not isinstance(data, dict):
        return []
    names = []
    for value in data.values():
        if isinstance(value, str):
            value = " ".join(value.split())
            if value:
                names.append(value)
    return names


def matching_names(names, typed, exclude=(), limit=MAX_SUGGESTIONS):
    """The known names that fit what was typed, best first.

    Matches ignore case and accents. Names where a word starts with the typed
    text come before names that only contain it; within each group the
    original (most used first) order is kept. Names in ``exclude`` (used by
    another speaker of this recording) and the exact text typed are left out.
    """
    query = fold(typed)
    if not query:
        return []
    excluded = {fold(n) for n in exclude}
    word_start, inside = [], []
    for name in names:
        key = fold(name)
        if key in excluded or key == query:
            continue
        if key.startswith(query) or f" {query}" in f" {key}":
            word_start.append(name)
        elif query in key:
            inside.append(name)
    return (word_start + inside)[:limit]
