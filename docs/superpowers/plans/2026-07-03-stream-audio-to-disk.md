# Stream recording audio to disk incrementally (#32)

## Problem

All three stream classes (`AudioStream`, `LoopbackStream`, `ProcessAudioCapture`) hold the
full recording in `_all_chunks` (~700 MB/hr across mic+mic2+system at 16 kHz mono float32),
and `np.concatenate` at stop transiently doubles it. Multi-hour recordings risk MemoryError
at the finish line — after the audio was successfully captured.

## Design

### _ChunkWriter (new: `app/recording/chunk_writer.py`)

One instance per output track. Owns a `queue.Queue`, a daemon writer thread, and a
`soundfile.SoundFile` opened for write (WAV, float32, mono, target sample rate).

- `put(chunk)` — non-blocking, called from audio callbacks / mixer thread. Audio callbacks
  must never touch disk (PortAudio realtime constraint); the queue decouples them.
- **Held start**: the writer thread does not write until `release(prepad_frames)` is called.
  Queued chunks accumulate (sub-second worth) while `DualAudioCapture.start()` computes the
  alignment pad; `release` writes `prepad_frames` of silence first, then drains. This replaces
  `_apply_start_alignment` (array front-pad at stop) with an equivalent front-pad at start —
  no race with early callbacks, no file rewrite.
- **Periodic flush** (~5 s): keeps the WAV header/frame count crash-readable so a crashed
  session leaves salvageable audio for the recovered-recordings path. Verified by test.
- Errors (disk full, etc.) are caught in the writer thread, stored on `.error`, and the writer
  drops subsequent chunks. `stop()` drains the queue, closes the file, returns frames written.
  A zero-frame file is deleted (preserves "no data → no file → results[key] = None").

### Stream classes

`_all_chunks` is removed everywhere. Each stream takes an optional `sink` (a `_ChunkWriter`);
the callback `put`s the post-processed chunk. Callback order in `AudioStream` is unchanged
except step 4: copy → gain+clip → mute → **sink.put** → level callback.

- `get_audio_data()` / `save_to_file()` are removed from all three classes (only internal
  callers + tests used them).
- `ProcessAudioCapture`: mixer loop `put`s mixed chunks to its sink. `enable_buffer` flag is
  replaced by sink presence (None = level-only, the old `enable_buffer=False`). `stop()` no
  longer returns `mixed_audio`.

### DualAudioCapture

- `start(output_dir)`: system stream first (unchanged), its writer released with prepad 0.
  Mic writer(s) created held; after mic stream starts and `_mic_start_ts` is stamped,
  released with `prepad = (mic_ts - system_ts) * sample_rate` (30 s anomaly guard kept;
  no system stream → prepad 0). System always starts first, so only mic tracks ever pad.
- Single mic → writes `mic_audio.wav` directly. Dual mic → `mic1_raw.wav` + `mic2_raw.wav`
  temps, block-wise mixed into `mic_audio.wav` at stop (pad shorter with zeros, sum,
  peak-normalize to 0.95 only when peak > 1.0 — matches current behavior), temps deleted.
- `stop()`: stop streams → stop writers → dual-mic mix → combined mix. Combined is block-wise
  two-pass over `mic_audio.wav` + `system_audio.wav`: pass 1 computes peak of
  `0.5*mic + 0.5*sys`, pass 2 writes scaled to 0.95 peak (matches current normalization).
  Every step individually guarded, results dict shape unchanged.
- In-progress files use final names: `metadata.json` is only written at stop, so the
  recordings list never sees a live session, and a crash leaves playable WAVs for the
  recovered-recordings salvage.

### Unchanged

Level meters, waveform, silence detection (all callback-driven), pause/resume semantics
(paused chunks are simply never put), recorder state machine, min-length discard
(deletes the dir — streamed files included), MP3 conversion.

## Memory profile

Steady state per track: queue depth × chunk size (few hundred KB worst case) instead of the
full recording. No concatenate at stop.

## Validation

- Full suite green; new unit tests for _ChunkWriter (held start, prepad, flush-crash
  readability, error capture, zero-frame delete) and block-wise mixing (equivalence with the
  old array math on synthetic signals).
- Short real-hardware capture (5 s) → three valid WAVs, mic front-pad present.
- **Deferred to user**: multi-hour real recording on real hardware (issue text).

## Test migration

`test_dual_audio_capture.py` gain/mute/callback-order assertions on `_all_chunks[n]` move to
a fake sink recording `put` calls. `test_process_audio_capture.py` buffer/save tests become
sink tests.
