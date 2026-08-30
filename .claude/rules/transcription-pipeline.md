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

## Model caches — resident by design

- `transcriber._MODEL_CACHE` — WhisperModel keyed `(model_size, device, compute_type)`.
- `diarizer._PIPELINE_CACHE` — pyannote Pipeline keyed `(HF token, resolved device)`.
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
