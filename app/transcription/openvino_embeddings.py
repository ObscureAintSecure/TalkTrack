"""pyannote's speaker-embedding network on an Intel GPU through OpenVINO (#135).

Even with one pass per chunk (#133), the WeSpeaker ResNet34 is most of
diarization time on a CPU. On a Core Ultra 7 265U its trunk ran 6.6x faster on
the iGPU, and a 5-minute meeting excerpt diarized in 18.5 s instead of 267 s
(pyannote as is), with a DER of 0.0002 against the original and speaker
centroids at cosine >= 0.99999, so voice profiles (#128) stay comparable.

Only the convolutional trunk runs on the GPU. The fbank features before it
and the per-speaker statistics pooling after it stay in torch on the CPU:
they are cheap, and the pooling is where each local speaker gets its weights.

pyannote's weights are gated on Hugging Face, so no prebuilt model can ship.
The trunk is converted from the loaded torch model on first use (about a
minute of tracing) and saved under ``COMPILE_CACHE_DIR``, keyed by a hash of
the weights. OpenVINO caches the compiled GPU blob there too.

No Qt, and OpenVINO and torch are imported inside functions, so the module
imports cleanly and is unit-testable with stubs.
"""
import hashlib
import threading

from app.transcription.openvino_whisper import COMPILE_CACHE_DIR, OPENVINO_DEVICE

# Compiled trunks keyed by (weights hash, batch size, fbank frames, mel bins),
# resident between recordings like the Whisper pipelines.
_TRUNK_CACHE = {}
_TRUNK_CACHE_LOCK = threading.Lock()


def weights_key(module):
    """Short hash of a torch module's weights: names, shapes and values."""
    digest = hashlib.sha1()
    for name, tensor in sorted(module.state_dict().items()):
        array = tensor.detach().cpu().contiguous().numpy()
        digest.update(f"{name}:{array.dtype}:{array.shape};".encode())
        digest.update(array.tobytes())
    return digest.hexdigest()[:16]


def ir_path(key):
    return COMPILE_CACHE_DIR / f"wespeaker-trunk-{key}.xml"


def chunk_fbank_shape(pipeline):
    """(frames, mel bins) of the fbank for one segmentation chunk."""
    import torch
    model = pipeline._embedding.model_
    duration = pipeline._segmentation.model.specifications.duration
    num_samples = int(round(duration * pipeline._embedding.sample_rate))
    with torch.inference_mode():
        fbank = model.compute_fbank(torch.zeros(1, 1, num_samples))
    return tuple(fbank.shape[1:])


def _convert(resnet, batch_size, frames, mel_bins, path):
    """Trace the ResNet trunk (fbank -> frame features) and save it as OpenVINO IR."""
    import openvino as ov
    import torch

    class Trunk(torch.nn.Module):
        def __init__(self, resnet):
            super().__init__()
            self.resnet = resnet

        def forward(self, fbank):
            # forward_frames unsqueezes its input in place; tracing needs a copy.
            return self.resnet.forward_frames(fbank.clone())

    example = torch.zeros(batch_size, frames, mel_bins)
    model = ov.convert_model(Trunk(resnet).eval(), example_input=example,
                             input=[ov.PartialShape([-1, frames, mel_bins])])
    path.parent.mkdir(parents=True, exist_ok=True)
    ov.save_model(model, str(path), compress_to_fp16=False)


class GpuTrunk:
    """Compiled trunk with a fixed input shape; shorter batches are zero-padded."""

    def __init__(self, compiled, batch_size, frames, mel_bins):
        self.compiled = compiled
        self.batch_size = batch_size
        self.shape = (frames, mel_bins)
        self.error = None   # set by chunk_embeddings when a batch fails

    def frames(self, fbank):
        """(n, frames, mel) float32 fbank -> trunk output for those n rows."""
        import numpy as np
        n = fbank.shape[0]
        if fbank.shape[1:] != self.shape or n > self.batch_size:
            raise ValueError(f"fbank batch {fbank.shape} does not fit the compiled trunk "
                             f"({self.batch_size}, {self.shape[0]}, {self.shape[1]})")
        if n < self.batch_size:
            pad = np.zeros((self.batch_size - n,) + self.shape, dtype=np.float32)
            fbank = np.concatenate([fbank, pad])
        return self.compiled(fbank)[0][:n]

    def embed(self, model, waveforms, weights):
        """What ``PyannoteAudioPretrainedSpeakerEmbedding(waveforms, masks=weights)`` returns."""
        import torch
        with torch.inference_mode():
            fbank = model.compute_fbank(waveforms).numpy().astype("float32", copy=False)
            frames = torch.from_numpy(self.frames(fbank))
            return model.resnet.forward_embedding(frames, weights=weights)[1].numpy()


def get_trunk(pipeline, progress=None):
    """The pipeline's embedding trunk compiled for the Intel GPU, built once.

    Raises if OpenVINO is missing, no GPU is found, or conversion fails; the
    caller keeps the CPU then.
    """
    model = pipeline._embedding.model_
    batch_size = pipeline.embedding_batch_size
    frames, mel_bins = chunk_fbank_shape(pipeline)
    key = weights_key(model.resnet)
    cache_key = (key, batch_size, frames, mel_bins)
    with _TRUNK_CACHE_LOCK:
        if cache_key not in _TRUNK_CACHE:
            import openvino as ov
            path = ir_path(key)
            if not path.exists():
                if progress:
                    progress("Preparing the speaker model for the Intel GPU (first use, about a minute)...")
                _convert(model.resnet, batch_size, frames, mel_bins, path)
            core = ov.Core()
            ir = core.read_model(str(path))
            ir.reshape([batch_size, frames, mel_bins])
            compiled = core.compile_model(ir, OPENVINO_DEVICE,
                                          {"CACHE_DIR": str(COMPILE_CACHE_DIR)})
            _TRUNK_CACHE[cache_key] = GpuTrunk(compiled, batch_size, frames, mel_bins)
        return _TRUNK_CACHE[cache_key]


def release_trunks():
    """Drop compiled trunks after a failure, so the next recording rebuilds them."""
    with _TRUNK_CACHE_LOCK:
        _TRUNK_CACHE.clear()
