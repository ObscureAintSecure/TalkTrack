"""Speaker embeddings with one network pass per audio chunk, not per speaker (#133).

pyannote's ``SpeakerDiarization.get_embeddings`` runs the embedding network
once for every (chunk, local speaker) pair. community-1 has three local
speakers per 10 s chunk, so each chunk goes through the WeSpeaker ResNet three
times, although only the final statistics pooling depends on the speaker. The
model already pools several speakers from one pass when given
(batch, speakers, frames) weights, so this runs it once per chunk.

The output is the same as pyannote's loop. On a 5-minute meeting excerpt
(Core Ultra 7 265U, CPU) it gave a DER of 0.0 against the original and
identical speaker centroids, in 93 s instead of 267 s. Embeddings were 96% of
diarization time.

No torch import at module level: the test suite cannot load torch (see
tests/test_chunk_embeddings.py).
"""
import math
import types

import numpy as np


def supports(pipeline):
    """True when the pipeline's embedding model pools per-speaker weights in one pass.

    That is pyannote's own WeSpeaker ResNet wrapper. Other embedding backends
    (SpeechBrain, NeMo, ONNX) take one mask per waveform; those pipelines keep
    pyannote's loop.
    """
    model = getattr(getattr(pipeline, "_embedding", None), "model_", None)
    resnet = getattr(model, "resnet", None)
    return (
        callable(getattr(model, "compute_fbank", None))
        and callable(getattr(resnet, "forward_frames", None))
        and callable(getattr(resnet, "forward_embedding", None))
    )


def install(pipeline):
    """Make ``pipeline`` compute embeddings per chunk. Returns True if it did."""
    if not supports(pipeline):
        return False
    pipeline.get_embeddings = types.MethodType(get_embeddings, pipeline)
    return True


def speaker_weights(masks, clean_masks, min_num_frames):
    """(speakers, frames) pooling weights for one chunk, as pyannote picks them.

    Each speaker uses its overlap-free frames when there are more than
    ``min_num_frames`` of them, and all its frames otherwise. NaN (partial
    stitching) counts as inactive.
    """
    masks = np.nan_to_num(masks, nan=0.0).astype(np.float32)
    clean_masks = np.nan_to_num(clean_masks, nan=0.0).astype(np.float32)
    return np.stack([
        clean if np.sum(clean) > min_num_frames else full
        for full, clean in zip(masks.T, clean_masks.T)
    ])


def get_embeddings(self, file, binary_segmentations, exclude_overlap=False, hook=None):
    """Drop-in for ``SpeakerDiarization.get_embeddings``, bound to the pipeline.

    Returns the same (num_chunks, num_speakers, dimension) array.
    """
    if self.training:
        # Training reuses cached embeddings across trials; keep pyannote's path.
        return type(self).get_embeddings(
            self, file, binary_segmentations, exclude_overlap=exclude_overlap, hook=hook,
        )

    import torch

    data = binary_segmentations.data
    num_chunks, num_frames, num_speakers = data.shape
    if exclude_overlap:
        # Fewer samples than this make the model raise, so pyannote falls
        # back to the full mask below that many overlap-free frames.
        duration = binary_segmentations.sliding_window.duration
        num_samples = duration * self._embedding.sample_rate
        min_num_frames = math.ceil(num_frames * self._embedding.min_num_samples / num_samples)
        clean = data * (np.sum(data, axis=2, keepdims=True) < 2)
    else:
        min_num_frames = -1
        clean = data

    batch_size = self.embedding_batch_size
    batch_count = math.ceil(num_chunks / batch_size)
    embeddings = np.zeros((num_chunks, num_speakers, self._embedding.dimension), dtype=np.float32)
    if hook is not None:
        hook("embeddings", None, total=batch_count, completed=0)

    waveforms, weights, start, done = [], [], 0, 0
    for c, (chunk, masks) in enumerate(binary_segmentations):
        waveform, _ = self._audio.crop(file, chunk, mode="pad")
        waveforms.append(waveform[None])
        weights.append(speaker_weights(masks, clean[c], min_num_frames))
        if len(waveforms) == batch_size or c == num_chunks - 1:
            batch = self._embedding(
                torch.vstack(waveforms), masks=torch.from_numpy(np.stack(weights)),
            )
            embeddings[start:c + 1] = batch
            start, done = c + 1, done + 1
            waveforms, weights = [], []
            if hook is not None:
                hook("embeddings", batch, total=batch_count, completed=done)
    return embeddings
