"""Prune WAV originals left beside MP3s by pre-#60 recordings.

Recordings made before the MP3 conversion started replacing its input kept
both formats — a full set of WAVs sitting next to the MP3s carrying the same
audio. This plans and applies the cleanup for an existing library. (issue #77)

Planning and deleting are separate on purpose: `plan_recording` only reads, so
a caller can show the user exactly what would go before anything is removed.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from app.utils.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

# A WAV is only pruned when its MP3 is within this many seconds of it. A
# conversion interrupted partway leaves a short MP3; that WAV has to survive.
DURATION_TOLERANCE_S = 0.5

TRACK_STEMS = (("mic", "mic_audio"),
               ("system", "system_audio"),
               ("combined", "combined_audio"))


@dataclass
class RecordingPlan:
    directory: Path
    prunable: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    metadata: dict = None

    @property
    def reclaimed_bytes(self):
        return sum(p["bytes"] for p in self.prunable)


def _duration(path):
    import soundfile as sf
    return float(sf.info(str(path)).duration)


def plan_recording(directory):
    """Work out which WAVs in one recording directory are safe to delete.

    Read-only. Returns a RecordingPlan; an empty `prunable` means nothing in
    this recording qualified, with the reasons in `skipped`.
    """
    directory = Path(directory)
    plan = RecordingPlan(directory=directory)

    meta_path = directory / "metadata.json"
    try:
        plan.metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Without metadata there is nothing to repoint, so the recording would
        # be left pointing at files that no longer exist.
        plan.skipped.append({"path": str(directory), "reason": "no readable metadata"})
        return plan

    for key, stem in TRACK_STEMS:
        wav = directory / f"{stem}.wav"
        mp3 = directory / f"{stem}.mp3"
        if not wav.exists() or not mp3.exists():
            continue

        try:
            if os.path.getsize(mp3) <= 0:
                raise ValueError("empty file")
            mp3_duration = _duration(mp3)
        except Exception as exc:
            plan.skipped.append({"path": str(mp3), "reason": f"MP3 unreadable ({exc})"})
            continue

        try:
            wav_duration = _duration(wav)
        except Exception as exc:
            plan.skipped.append({"path": str(wav), "reason": f"WAV unreadable ({exc})"})
            continue

        if abs(wav_duration - mp3_duration) > DURATION_TOLERANCE_S:
            plan.skipped.append({
                "path": str(mp3),
                "reason": (f"duration mismatch "
                           f"(WAV {wav_duration:.1f}s vs MP3 {mp3_duration:.1f}s)"),
            })
            continue

        plan.prunable.append({
            "key": key,
            "wav": str(wav),
            "mp3": str(mp3),
            "bytes": os.path.getsize(wav),
        })

    return plan


def plan_library(recordings_dir):
    """Plan every recording directory under `recordings_dir`."""
    recordings_dir = Path(recordings_dir)
    plans = []
    for entry in sorted(recordings_dir.iterdir()):
        if entry.is_dir():
            plans.append(plan_recording(entry))
    return plans


def apply_plan(plan):
    """Repoint metadata at the MP3s, then delete the planned WAVs.

    Metadata is written first: a crash between the two steps leaves a
    recording that still resolves (to the MP3), whereas deleting first would
    leave metadata pointing at a file that is gone.
    """
    if not plan.prunable:
        return 0

    audio_files = dict(plan.metadata.get("audio_files") or {})
    for item in plan.prunable:
        audio_files[item["key"]] = item["mp3"]
        audio_files.pop(item["key"] + "_mp3", None)

    metadata = dict(plan.metadata)
    metadata["audio_files"] = audio_files
    atomic_write_json(plan.directory / "metadata.json", metadata, indent=2)
    plan.metadata = metadata

    reclaimed = 0
    for item in plan.prunable:
        try:
            size = os.path.getsize(item["wav"])
            os.remove(item["wav"])
            reclaimed += size
        except OSError:
            logger.warning("Could not delete %s", item["wav"])
    return reclaimed
