# Audio Pipeline: capture invariants and mute/gain semantics

## AudioStream callback processing order

`AudioStream._audio_callback` in `app/recording/audio_capture.py` processes each chunk in this exact order. Do not reorder — the tests encode this sequence:

1. `chunk = indata.copy()` (detach from device buffer)
2. If `_gain != 1.0`: multiply + `np.clip(chunk, -1.0, 1.0, out=chunk)` (pre-clip so downstream can't wrap)
3. If `_muted`: `chunk.fill(0.0)` (mute overrides gain — tested in `test_mute_beats_gain`)
4. Append to `_all_chunks` (the old `_buffer` queue was dead code doubling mic RAM — removed in #26; do not reintroduce)
5. Call `_level_callback(chunk)` with the post-processed chunk

The level meter and waveform see the processed signal (what's actually being recorded), which is the intended UX.

## Mute and gain scoping

- Both live on `DualAudioCapture`: `_muted` + `set_muted(bool)` and `mic_gain` + `set_gain(float)`.
- Both propagate to `mic_stream` AND `mic_stream_2` (dual-mic-aware).
- Neither touches `system_stream` — system/app audio is **never** muted or gained. The "cough button" and "boost my mic" use cases are mic-only by design.
- `set_gain` always propagates; `start()` re-applies both after each mic stream is created.

## Stop/start conventions (DualAudioCapture)

- `stop()` guards every stop/save step individually (mic unplug or disk-full must not lose the other tracks) — keep new steps guarded the same way. System audio is saved from the aligned array via `sf.write`, not `save_to_file`.
- Streams stamp `_mic_start_ts`/`_system_start_ts` (monotonic) at start; `_apply_start_alignment` front-pads the later-starting track so t=0 matches wall-clock across mic/system/combined (per-app activation alone can cost ~1s). Deltas >30s are treated as clock anomalies and skipped.
- Mic-start failure triggers `_stop_streams_quietly()` — never leave the system capture running when `start()` raises.
- All three stream classes hold audio in `_all_chunks` (RAM) until stop **by design**; disk streaming is tracked as #32 — don't partially convert one stream class.

## MainWindow → capture access pattern

- `MainWindow` reaches into `self.recorder._capture` directly for `set_muted`, `set_gain`, etc. This is the established pattern — do **not** add a `Recorder.set_muted`/`set_gain` passthrough. Recorder stays focused on state machine + session lifecycle.
- Debounced config writes (gain slider): 500ms single-shot `QTimer` on `MainWindow`, flushed on `closeEvent`. `_pending_gain` tracks value between drag and flush.
