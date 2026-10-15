"""Voice profiles: recognise named speakers across recordings (#128).

pyannote returns one centroid embedding per diarized speaker. When the user
names a speaker, that centroid becomes a contribution to the profile with that
name. On later recordings every new centroid is compared with the profiles, and
confident matches pre-fill the speaker names.

Only names the user typed train profiles. A name that was auto-filled from a
match and left untouched never does, so a wrong match cannot reinforce itself.

Everything here is plain numpy + JSON (no Qt, no torch) so it stays testable.
"""

import json
import logging
import os
from pathlib import Path

import numpy as np

from app.utils.atomic_io import atomic_write_json
from app.utils.config import CONFIG_DIR

logger = logging.getLogger(__name__)

# Identifies the vector space the centroids live in. Vectors from a different
# model are never compared or averaged together.
EMBEDDING_MODEL_ID = "pyannote/speaker-diarization-community-1"

# Minimum cosine similarity between a speaker centroid and a profile to
# auto-fill the name. First calibrated at 0.6 on one 5-person Teams call
# (pt-BR) split in halves: same person 0.88 and 0.92, different people
# 0.12-0.44. Real use across four meetings on three days then showed:
#   same person, other meeting: 0.849, 0.857, 0.908, 0.924, 0.927, 0.950
#   different person:           up to 0.605, 0.627, 0.631 (one auto-filled
#                               a name that was not in the meeting)
# 0.75 sits in the middle of that gap. A missed match only leaves a name to
# type; a wrong one puts the wrong person in the minutes.
MATCH_THRESHOLD = 0.75

PROFILES_PATH = CONFIG_DIR / "voice_profiles.json"
EMBEDDINGS_FILE = "speaker_embeddings.json"   # per recording: label -> centroid
MATCHES_FILE = "voice_matches.json"           # per recording: label -> auto-filled name

_STORE_VERSION = 1


def clean_embedding(vector):
    """Return a 1-D float64 array, or None for empty/zero/non-finite vectors.

    pyannote pads the centroid matrix with zero rows for speakers it could not
    compute a centroid for; those must never match anything.
    """
    try:
        arr = np.asarray(vector, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if arr.ndim != 1 or arr.size == 0 or not np.all(np.isfinite(arr)):
        return None
    if np.linalg.norm(arr) == 0:
        return None
    return arr


def _unit(arr):
    return arr / np.linalg.norm(arr)


def speaker_embeddings_by_label(output, diarization):
    """Map each diarization label to its centroid from a pyannote DiarizeOutput.

    `output.speaker_embeddings[i]` belongs to `diarization.labels()[i]`.
    Returns {} when the output carries no embeddings (older pyannote).
    """
    vectors = getattr(output, "speaker_embeddings", None)
    if vectors is None:
        return {}
    result = {}
    for i, label in enumerate(diarization.labels()):
        if i >= len(vectors):
            break
        vec = clean_embedding(vectors[i])
        if vec is not None:
            result[label] = vec
    return result


def match_speakers(embeddings, profiles, threshold=MATCH_THRESHOLD, exclude_names=()):
    """Assign profile names to speakers, one-to-one, best similarity first.

    Args:
        embeddings: {label: vector} for the speakers to identify.
        profiles: {name: unit vector}, e.g. VoiceProfileStore.profiles().
        exclude_names: names already used in this recording; never reassigned.

    Returns:
        {label: (name, cosine_similarity)} for matches at or above threshold.
    """
    excluded = set(exclude_names)
    candidates = []
    for label, vector in embeddings.items():
        vec = clean_embedding(vector)
        if vec is None:
            continue
        vec = _unit(vec)
        for name, profile in profiles.items():
            if name in excluded or len(profile) != len(vec):
                continue
            score = float(vec @ profile)
            if score >= threshold:
                candidates.append((score, label, name))

    matches = {}
    used_names = set()
    for score, label, name in sorted(candidates, key=lambda c: c[0], reverse=True):
        if label in matches or name in used_names:
            continue
        matches[label] = (name, score)
        used_names.add(name)
    return matches


def trained_names(names, matches):
    """The names the user actually gave: drop blanks and untouched auto-fills.

    Args:
        names: {label: name} as in speaker_names.json.
        matches: {label: {"name": ..., "score": ...}} as in voice_matches.json.
    """
    trained = {}
    for label, name in names.items():
        name = (name or "").strip()
        if not name:
            continue
        auto = matches.get(label)
        if auto and auto.get("name") == name:
            continue
        trained[label] = name
    return trained


# --- per-recording files -----------------------------------------------------

def save_recording_embeddings(directory, embeddings, model_id=EMBEDDING_MODEL_ID):
    atomic_write_json(Path(directory) / EMBEDDINGS_FILE, {
        "model": model_id,
        "speakers": {
            label: [round(float(x), 6) for x in vec]
            for label, vec in embeddings.items()
        },
    })


def load_recording_embeddings(directory, model_id=EMBEDDING_MODEL_ID):
    """{label: vector} for a recording, or {} if missing, corrupt or another model."""
    data = _read_json(Path(directory) / EMBEDDINGS_FILE)
    if not isinstance(data, dict) or data.get("model") != model_id:
        return {}
    result = {}
    for label, vector in (data.get("speakers") or {}).items():
        vec = clean_embedding(vector)
        if vec is not None:
            result[label] = vec
    return result


def save_voice_matches(directory, matches):
    """Persist auto-filled names: {label: (name, score)}."""
    atomic_write_json(Path(directory) / MATCHES_FILE, {
        label: {"name": name, "score": round(float(score), 3)}
        for label, (name, score) in matches.items()
    }, indent=2, ensure_ascii=False)


def load_voice_matches(directory):
    data = _read_json(Path(directory) / MATCHES_FILE)
    if not isinstance(data, dict):
        return {}
    return {
        label: entry for label, entry in data.items()
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        logger.warning("Ignoring unreadable %s", path, exc_info=True)
        return None


# --- recording-level operations used by MainWindow ---------------------------

def apply_to_recording(directory, embeddings, speaker_names, store,
                       threshold=MATCH_THRESHOLD):
    """Store a freshly diarized recording's centroids and auto-fill known voices.

    Only speakers without a name get one. Names the user typed on a previous
    run (re-transcription of a named recording) are kept and train the store.
    Untouched auto-fills from a previous run are dropped and matched afresh:
    they were never the user's, and must not start training now.

    Returns:
        (the recording's new speaker names, {label: (name, score)})
    """
    directory = Path(directory)
    previous = load_voice_matches(directory)
    save_recording_embeddings(directory, embeddings)

    names = {
        label: name for label, name in speaker_names.items()
        if (name or "").strip()
        and not (label in previous and previous[label].get("name") == name)
    }
    unnamed = {label: vec for label, vec in embeddings.items() if label not in names}
    matches = match_speakers(unnamed, store.profiles(), threshold,
                             exclude_names=set(names.values()))
    save_voice_matches(directory, matches)

    filled = dict(names)
    for label, (name, _score) in matches.items():
        filled[label] = name

    store.set_recording(directory.name, {
        label: (name, embeddings[label])
        for label, name in trained_names(filled, load_voice_matches(directory)).items()
        if label in embeddings
    })
    return filled, matches


def train_from_names(directory, speaker_names, store):
    """Update the store after the user edits a recording's speaker names."""
    directory = Path(directory)
    embeddings = load_recording_embeddings(directory)
    if not embeddings:
        return False
    matches = load_voice_matches(directory)
    return store.set_recording(directory.name, {
        label: (name, embeddings[label])
        for label, name in trained_names(speaker_names, matches).items()
        if label in embeddings
    })


# --- profile store -------------------------------------------------------------

class VoiceProfileStore:
    """Named voice profiles in one JSON file.

    Stores contributions, not averages: one entry per (recording, speaker) the
    user named. A profile is the mean of its contributions' unit vectors. Keeping
    the raw contributions makes every update idempotent (the speaker panel
    reports every keystroke), lets a rename move a voice to another name, and
    lets a profile be deleted cleanly.

    The file is re-read on every call so that edits from another store
    instance (the Settings dialog) are never overwritten with stale data.
    """

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else PROFILES_PATH

    def _load(self):
        data = _read_json(self.path)
        if data is None:
            if self.path.exists():
                self._backup_corrupt_file()
            return []
        contributions = data.get("contributions") if isinstance(data, dict) else None
        if not isinstance(contributions, list):
            self._backup_corrupt_file()
            return []
        return [c for c in contributions if self._valid(c)]

    @staticmethod
    def _valid(c):
        return (
            isinstance(c, dict)
            and isinstance(c.get("recording"), str)
            and isinstance(c.get("speaker"), str)
            and isinstance(c.get("name"), str)
            and isinstance(c.get("model"), str)
            and clean_embedding(c.get("embedding")) is not None
        )

    def _backup_corrupt_file(self):
        try:
            os.replace(self.path, self.path.with_name(self.path.name + ".bak"))
        except OSError:
            pass

    def _save(self, contributions):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, {
            "version": _STORE_VERSION,
            "contributions": contributions,
        }, ensure_ascii=False)

    def set_recording(self, recording_id, named_speakers, model_id=EMBEDDING_MODEL_ID):
        """Replace a recording's contributions with {label: (name, vector)}.

        Returns True if anything changed (and was saved).
        """
        contributions = self._load()
        kept = [c for c in contributions if c["recording"] != recording_id]
        new = []
        for label, (name, vector) in sorted(named_speakers.items()):
            vec = clean_embedding(vector)
            name = (name or "").strip()
            if vec is None or not name:
                continue
            new.append({
                "recording": recording_id,
                "speaker": label,
                "name": name,
                "model": model_id,
                "embedding": [round(float(x), 6) for x in vec],
            })
        old = [c for c in contributions if c["recording"] == recording_id]
        if self._key(old) == self._key(new):
            return False
        self._save(kept + new)
        return True

    @staticmethod
    def _key(contributions):
        return sorted((c["speaker"], c["name"], c["model"]) for c in contributions)

    def profiles(self, model_id=EMBEDDING_MODEL_ID):
        """{name: unit mean vector} over contributions from `model_id`."""
        grouped = {}
        for c in self._load():
            if c["model"] != model_id:
                continue
            grouped.setdefault(c["name"], []).append(_unit(clean_embedding(c["embedding"])))
        profiles = {}
        for name, vectors in grouped.items():
            if len({len(v) for v in vectors}) != 1:
                continue
            mean = np.mean(vectors, axis=0)
            if np.linalg.norm(mean) > 0:
                profiles[name] = _unit(mean)
        return profiles

    def summary(self):
        """[(name, number of recordings)] sorted by name, case-insensitively."""
        recordings = {}
        for c in self._load():
            recordings.setdefault(c["name"], set()).add(c["recording"])
        return sorted(((n, len(r)) for n, r in recordings.items()), key=lambda x: x[0].casefold())

    def delete_profile(self, name):
        contributions = self._load()
        kept = [c for c in contributions if c["name"] != name]
        if len(kept) != len(contributions):
            self._save(kept)

    def clear(self):
        self._save([])
