"""Atomic file writes — temp file + os.replace so a crash mid-write can't
leave a truncated file behind."""

import json
import os


def atomic_write_text(path, text, encoding="utf-8"):
    path = str(path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding=encoding) as f:
        f.write(text)
    os.replace(tmp, path)


def atomic_write_json(path, obj, **dump_kwargs):
    atomic_write_text(path, json.dumps(obj, **dump_kwargs))
