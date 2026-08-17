"""Delete WAV originals left beside MP3s by recordings made before #60.

Dry run by default. Nothing is deleted without --apply.

    python scripts/prune_redundant_wavs.py                  # show what would go
    python scripts/prune_redundant_wavs.py --apply          # actually delete

A WAV is only removed when its MP3 opens and matches it in duration, and the
recording's metadata.json is repointed at the MP3 before anything is deleted.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.utils.wav_prune import apply_plan, plan_library  # noqa: E402


def _gb(n):
    return f"{n / 1e9:.2f} GB"


def _default_recordings_dir():
    try:
        from app.utils.config import Config
        return Path(Config().get("output", "directory"))
    except Exception:
        return Path(__file__).resolve().parent.parent / "recordings"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recordings-dir", type=Path, default=None,
                        help="defaults to the configured output directory")
    parser.add_argument("--apply", action="store_true",
                        help="delete the WAVs (without this, only reports)")
    args = parser.parse_args(argv)

    recordings_dir = args.recordings_dir or _default_recordings_dir()
    if not recordings_dir.is_dir():
        print(f"No recordings directory at {recordings_dir}")
        return 1

    print(f"Scanning {recordings_dir}\n")
    plans = plan_library(recordings_dir)

    total = 0
    affected = 0
    for plan in plans:
        if plan.prunable:
            affected += 1
            total += plan.reclaimed_bytes
            tracks = ", ".join(p["key"] for p in plan.prunable)
            print(f"  {plan.directory.name}: {tracks} ({_gb(plan.reclaimed_bytes)})")
        for skip in plan.skipped:
            print(f"  {plan.directory.name}: SKIP {skip['reason']}")

    if not affected:
        print("Nothing to prune.")
        return 0

    print(f"\n{affected} of {len(plans)} recordings, {_gb(total)} reclaimable")

    if not args.apply:
        print("Dry run. Re-run with --apply to delete.")
        return 0

    reclaimed = sum(apply_plan(plan) for plan in plans)
    print(f"Deleted {_gb(reclaimed)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
