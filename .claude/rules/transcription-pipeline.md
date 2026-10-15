# Transcription Pipeline: worker lifecycle, session binding, queueing, model caches

Invariants from issues #19–#21, #27–#28. Violating the first two reproduces cross-recording data corruption or crash-on-exit.

## Session binding — never read `_current_session` in completion handlers

Every pipeline worker (`TranscriptionWorker`, `DiarizationWorker`, `SimpleDiarizeWorker`) carries a `.session` attribute bound at creation. Completion/error handlers read the worker's session, not `self._current_session` — the user may have selected a different recording while the worker ran. Results whose session is no longer displayed are persisted via `_write_transcript_for_session` (own directory, own speaker names) without touching the UI, and auto-summarize is skipped for them (the summarize path reads notes/instruction from the *displayed* panels).

## Serial job queue

- `_start_transcription(audio_path, session=None)` queues `(audio_path, session)` in `_pending_transcriptions` when busy; never silently drops.
- `_transcription_busy()` covers ALL THREE workers (transcription, pyannote diarization, simple diarization) — one job (transcribe → diarize → display/save) runs at a time.
- Every terminal path (display, transcription error, cancel, diarization error) must call `_process_pending_transcriptions()` or the queue stalls.

## Shutdown

- `closeEvent` sets `self._closing = True` BEFORE `recorder.stop_recording()` — the synchronous `recording_finished` signal would otherwise spawn a fresh worker mid-exit. `_start_transcription` early-returns when closing.
- `_shutdown_workers()` handles all QThread workers (plus chat + search workers via `active_worker()` accessors): cooperative cancel where supported, `wait(5000)`, `terminate()` last resort. New background workers must be added to its list.

## Diarization error paths show the transcript

Diarization (full or simple) failing must still render/persist the successful transcript (`worker.transcript_result`). A silent drop here was the original #14 bug.

## GPU diarization falls back to CPU on OOM (#74)

`_get_pipeline(hf_token, device)` returns **`(pipeline, device_actually_used)`** — callers must
not re-derive the device with `_resolve_device`, or a CUDA request that fell back reports as
running on the GPU.

Two OOM points, both handled:

- **Moving to CUDA**: a failed `.to(cuda)` puts the pipeline back on CPU and caches it under the
  `(token, "cpu")` key. A half-moved pipeline must never be handed out under the CUDA key.
- **Inference**: only `_is_oom(exc)` is retried, on CPU, once. Everything else re-raises — a
  shape bug masked by a silent CPU rerun is worse than the crash. The retry calls
  `_release_cuda_pipeline`, which evicts the CUDA entry and `empty_cache()`s; keeping it would
  re-try and re-fail on every later recording while still holding the VRAM that caused it.

Why this exists: `transcriber._MODEL_CACHE` and `diarizer._PIPELINE_CACHE` are both resident by
design, so a CUDA run pins the Whisper model and the pyannote pipeline in VRAM at once. `large-v3`
alone is ~10 GB.

## Speaker embeddings: one network pass per chunk (#133)

`_get_pipeline` swaps the pipeline's `get_embeddings` for `chunk_embeddings.get_embeddings`.
pyannote runs the WeSpeaker ResNet once per (chunk, local speaker): three passes over the same
10 s of audio, although only the statistics pooling depends on the speaker. The per-chunk version
passes `(batch, speakers, frames)` weights, which the model pools in one pass. That step was 96%
of diarization time, and the change made it ~3x faster on a CPU.

- **The output must stay pyannote's.** Overlap-free mask selection, NaN handling, batch size and
  the progress hook mirror `SpeakerDiarization.get_embeddings`. Inactive speakers are still
  pooled with zero weights rather than skipped, since clustering sees their (NaN) rows.
  `test_chunk_embeddings` restates pyannote's loop and compares; re-check it against
  pyannote's source when upgrading pyannote.audio.
- Only pyannote's own WeSpeaker wrapper pools per speaker. `install` leaves other embedding
  backends (SpeechBrain, NeMo, ONNX) on pyannote's loop, and training keeps pyannote's path.

## Model caches — resident by design

- `transcriber._MODEL_CACHE` — WhisperModel keyed `(model_size, device, compute_type)`.
- `diarizer._PIPELINE_CACHE` — pyannote Pipeline keyed `(HF token, resolved device)`.
- `openvino_whisper._PIPELINE_CACHE` — OpenVINO WhisperPipeline keyed `(model_size, "GPU")`.
- `provider.get_sentence_transformer()` — shared embed model cache.
Loading costs seconds-to-tens-of-seconds per recording; models staying in RAM/VRAM between recordings is intentional. Don't "fix" it.

## SimpleDiarizer

- Runs off-thread via `SimpleDiarizeWorker` (reads both full WAVs — froze the UI inline).
- Indexes each track with its OWN sample rate (`mic_sr` / `sys_sr`) — mic and system tracks can legitimately differ; a single shared rate made You/Remote labels random (#28).

## Segment metadata

- `TranscriptSegment.confidence` = `exp(segment.avg_logprob)` — populated since #29.
- `word_timestamps` is deliberately NOT requested (unused output, real alignment cost). If a feature needs word timing, re-enable it and actually consume `segment.words`.

## Whisper model cache paths are not all under Systran (#73)

`faster-whisper` publishes models under different orgs — `large-v3` is `Systran/...`,
`large-v3-turbo` is `mobiuslabsgmbh/...`. Resolve the repo id from `faster_whisper.utils._MODELS`
via `dependency_checker.whisper_cache_dir`, never interpolate an org into the path. Getting this
wrong made System Status report a downloaded model as missing, at `critical` level, which
auto-opens the status dialog on startup.

## batch_size defaults to 1 and should stay there (#46)

`transcription.batch_size > 1` uses `BatchedInferencePipeline`; 1 is the classic sequential path.
Do not raise the default. `Config.load` deep-merges `DEFAULT_CONFIG` into an existing
settings.json, so a higher default silently switches every installed copy to batched decode on
next launch and trades away cross-chunk `condition_on_previous_text`. The default compute device
is also `cpu`, where there is least parallel-decode headroom to win back. The worker and the
config declare the default separately, so both are pinned by tests.

## Intel GPU via OpenVINO (#131)

`transcription.device = "intel_gpu"` routes `TranscriptionWorker` to `_run_openvino`, backed by
`app/transcription/openvino_whisper.py` (no Qt; OpenVINO and faster-whisper imported inside
functions). faster-whisper (CTranslate2) has no Intel GPU support, so this is a second backend,
not a device flag.

- **Any OpenVINO failure falls back to the CPU**, at load or mid-run, and evicts the pipeline
  (`release_pipeline`). Unlike the diarizer's OOM-only retry, failures here are environmental
  (missing package, no GPU, driver hang `ZE_RESULT_ERROR_DEVICE_LOST`), and the transcript
  matters more than surfacing them. Unreadable audio raises instead: the CPU would fail too.
- **VAD is ours to do.** `WhisperPipeline` has none, and Whisper invents text over silence
  (20 s of silence came back as "E aí"). `speech_regions` uses faster-whisper's Silero VAD;
  only speech is decoded and `TimeMap` maps times back to the recording.
- **Batches of ≤ `MAX_BATCH_SECONDS` (60) of speech.** `generate()` blocks and its streamer is
  unavailable with timestamps on long audio, so batches are the only progress and cancel
  points. Meeting speech rarely pauses for the VAD's 2 s (one region ran 264 s, which made
  Cancel wait ~30 s), so the VAD also gets `max_speech_duration_s = MAX_BATCH_SECONDS` and
  splits long speech at a short pause. Same total time as 120 s batches.
- **Language is detected once**, on the first batch, then pinned for the rest, as faster-whisper
  does. A batch must not flip a pt-BR meeting to Spanish halfway.
- Models are Intel's `OpenVINO/whisper-<size>-int8-ov` builds in the HF cache
  (`model_cache_dir`; System Status checks that path when Intel GPU is selected). The first
  load compiles for the GPU (~40 s); the compiled blob is cached in `~/.talktrack/openvino_cache`.
- OpenVINO returns no per-segment log-probability, so these segments keep `confidence = 0.0`.
- pyannote stays a torch pipeline on the CPU (`diarizer._resolve_device` maps `intel_gpu` to
  `cpu`); only its embedding network moves to the GPU, see below.
- **No NPU option.** On a Core Ultra 7 265U NPU, large-v3-turbo hangs the device
  (`ZE_RESULT_ERROR_DEVICE_LOST`, 2/2 runs); only small ran. Revisit with newer drivers.
- The pip spec lives in `openvino_whisper.PIP_PACKAGE`, `package_installer.PROVIDER_PACKAGES`
  and the `openvino` extra; `test_openvino_whisper.TestPackageDeclarations` keeps them equal.

## Speaker embeddings on the Intel GPU (#135)

With `intel_gpu` selected, `DiarizationWorker` compiles pyannote's WeSpeaker ResNet34 trunk for the
GPU (`openvino_embeddings.get_trunk`) and hands it to `chunk_embeddings.set_accelerator`. On a
5-minute excerpt: 267 s (pyannote as is) → 63–100 s (#133, CPU) → 18.5 s, DER 0.0002, centroids
at cosine ≥ 0.99999.

- **Only the trunk moves.** fbank before it and the per-speaker pooling after it stay in torch
  on the CPU: they are cheap, and pooling is where each local speaker's weights apply.
- **Set the accelerator on every run, including to None.** The `cpu` and `intel_gpu` settings
  share the `(token, "cpu")` pipeline in `_PIPELINE_CACHE`; a stale accelerator would keep
  using the GPU after the user switched back.
- **Failures fall back, as transcription does.** At build time (`_intel_gpu_trunk` returns None)
  the run stays on the CPU. Mid-run, `chunk_embeddings._embed` keeps the error on
  `accelerator.error` and finishes on the CPU; the worker then calls `release_trunks()` and says so.
- **The model is converted locally**, since pyannote's weights are gated and cannot ship. First use
  traces the trunk (~60 s) to `openvino_cache/wespeaker-trunk-<weights hash>.xml`. The hash covers
  the weights, so a pyannote model update converts again rather than reusing a stale IR.
- The trunk is compiled with a static shape (embedding batch size × one chunk's fbank frames);
  short batches are zero-padded. A different shape raises and falls back rather than reshaping.
- NPU ran the trunk too (1.1 s vs 1.7 s per batch) but compiles in 30 s instead of 5, and is
  where large-v3-turbo hung. The GPU was as fast end to end, so it is the only target.
