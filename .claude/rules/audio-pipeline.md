# Audio Pipeline: capture invariants and mute/gain semantics

## AudioStream callback processing order

`AudioStream._audio_callback` in `app/recording/audio_capture.py` processes each chunk in this exact order. Do not reorder — the tests encode this sequence:

1. `chunk = indata.copy()` (detach from device buffer)
2. If `_gain != 1.0`: multiply + `np.clip(chunk, -1.0, 1.0, out=chunk)` (pre-clip so downstream can't wrap)
3. If `_muted`: `chunk.fill(0.0)` (mute overrides gain — tested in `test_mute_beats_gain`)
4. `_sink.put(chunk)` — the ChunkWriter streams it to disk (#32; the older `_all_chunks` RAM
   accumulator and the `_buffer` queue before it are both gone — do not reintroduce either)
5. Call `_level_callback(chunk)` with the post-processed chunk

Callbacks must never touch disk directly — `ChunkWriter.put` is a non-blocking queue put;
a daemon thread per track does the actual `soundfile` writes (`app/recording/chunk_writer.py`).

The level meter and waveform see the processed signal (what's actually being recorded), which is the intended UX.

## Mute and gain scoping

- Both live on `DualAudioCapture`: `_muted` + `set_muted(bool)` and `mic_gain` + `set_gain(float)`.
- Both propagate to `mic_stream` AND `mic_stream_2` (dual-mic-aware).
- Neither touches `system_stream` — system/app audio is **never** muted or gained. The "cough button" and "boost my mic" use cases are mic-only by design.
- `set_gain` always propagates; `start()` re-applies both after each mic stream is created.

## Stop/start conventions (DualAudioCapture)

- Audio is **streamed to disk during capture** (#32): `DualAudioCapture` owns one `ChunkWriter`
  per track (`_writers`, keys `mic`/`mic2`/`system`) and passes each as the stream's `sink`.
  Streams never own writers. `stop()` closes writers, then assembles dual-mic `mic_audio.wav`
  and `combined_audio.wav` block-wise via `mix_wav_files` (two-pass peak normalize: dual-mic
  `if_clipping`, combined `always` to 0.95; lone track = verbatim copy).
- `stop()` guards every stop/close/mix step individually (mic unplug or disk-full must not lose
  the other tracks) — keep new steps guarded the same way. A `ChunkWriter` that wrote 0 frames
  deletes its file, preserving "no data → no results entry".
- Wall-clock alignment happens at **start**, not stop: `_system_start_ts` is stamped first,
  then each mic writer is `release()`d with `_alignment_prepad_frames(ts)` of leading silence
  (per-app activation alone can cost ~1s). Deltas >30s are clock anomalies and skipped.
  Writers hold queued chunks until released, so no pad/data race.
- Mic-start failure triggers `_stop_streams_quietly()` — stops streams AND `abort()`s writers
  (deletes files); never leave the system capture running or track files behind when `start()`
  raises.
- In-progress recordings write final filenames; that's safe because `metadata.json` only
  appears at stop, and it feeds the recovered-recordings salvage (writers flush ~5s so crashed
  WAVs stay header-valid).

## WASAPI loopback and WAV-flush facts (verified on real hardware)

- WASAPI loopback delivers **no packets when nothing renders** — an empty/missing
  `system_audio.wav` with silence on the endpoint is correct behavior, not a capture bug.
  Real-hardware smoke tests must render a tone (`sd.play(sine, 48000)`) to exercise the
  loopback→writer path.
- `soundfile.SoundFile.flush()` does update the WAV header frame count (libsndfile
  `sf_write_sync`) — a mid-recording copy of the file parses as valid WAV. ChunkWriter's
  crash-readability guarantee depends on this; `test_flush_keeps_file_readable_before_close`
  encodes it.

## MainWindow → capture access pattern

- `MainWindow` reaches into `self.recorder._capture` directly for `set_muted`, `set_gain`, etc. This is the established pattern — do **not** add a `Recorder.set_muted`/`set_gain` passthrough. Recorder stays focused on state machine + session lifecycle.
- Debounced config writes (gain slider): 500ms single-shot `QTimer` on `MainWindow`, flushed on `closeEvent`. `_pending_gain` tracks value between drag and flush.
