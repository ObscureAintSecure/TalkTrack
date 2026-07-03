"""Per-recording embedding cache (#33).

semantic_search used to re-embed every past recording's segments on every
search. Each recording dir now carries an embeddings.npz mapping
sha1(segment text) -> vector for one embedding model; only new or edited
segments are embedded, and entries for deleted/edited text are pruned on
the next search. A different embed model (or a corrupt file) invalidates
the whole cache for that recording.
"""

import hashlib
import logging
import os
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

CACHE_FILENAME = "embeddings.npz"


def text_hash(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def load_cache(rec_dir, model_id):
    """Return {text_hash: vector} for model_id; {} on miss/mismatch/corruption."""
    path = Path(rec_dir) / CACHE_FILENAME
    if not path.exists():
        return {}
    try:
        with np.load(str(path), allow_pickle=False) as z:
            if str(z["model"]) != model_id:
                return {}
            hashes = [str(h) for h in z["hashes"]]
            vectors = z["vectors"]
            return {h: vectors[i] for i, h in enumerate(hashes)}
    except Exception:
        logger.warning("Unreadable embedding cache %s — rebuilding", path)
        return {}


def save_cache(rec_dir, model_id, mapping):
    """Atomically write {text_hash: vector} for model_id."""
    path = Path(rec_dir) / CACHE_FILENAME
    tmp = str(path) + ".tmp"
    hashes = list(mapping)
    vectors = (np.stack([np.asarray(mapping[h], dtype=np.float32)
                         for h in hashes])
               if hashes else np.zeros((0, 0), dtype=np.float32))
    with open(tmp, "wb") as f:
        np.savez(f, model=np.array(model_id),
                 hashes=np.array(hashes), vectors=vectors)
    os.replace(tmp, str(path))


def get_corpus_vectors(rec_dir, texts, provider):
    """Vectors for texts (aligned by index), embedding only cache misses.

    Falls back to plain provider.embed() when the provider has no
    embed_model_id or no recording dir is given (nothing safe to key on).
    """
    model_id = getattr(provider, "embed_model_id", None)
    if model_id is None or rec_dir is None:
        return np.array(provider.embed(texts))

    cached = load_cache(rec_dir, model_id)
    hashes = [text_hash(t) for t in texts]
    missing = {}   # hash -> text; dict dedupes repeated segments
    for h, t in zip(hashes, texts):
        if h not in cached:
            missing[h] = t
    if missing:
        new_vectors = provider.embed(list(missing.values()))
        for h, v in zip(missing, new_vectors):
            cached[h] = np.asarray(v, dtype=np.float32)

    current = {h: cached[h] for h in hashes}
    if missing or len(current) != len(cached):
        try:
            save_cache(rec_dir, model_id, current)
        except Exception:
            logger.exception("Could not write embedding cache in %s", rec_dir)

    return np.stack([current[h] for h in hashes])
