# Per-App Audio Capture: Windows 11 COM invariants and hard-won gotchas

These are invariants for `app/recording/_process_com.py` and `app/recording/process_audio_capture.py`. Each one bit us during bring-up on Windows 11 Build 26200; violating them reproduces `E_ILLEGAL_METHOD_CALL` (`0x8000000E`) or silent silence.

## Completion handler must implement `IAgileObject`

`ActivateAudioInterfaceAsync` refuses handlers that aren't apartment-neutral and fails **synchronously** with `0x8000000E`. WRL's `RuntimeClass` marks C++ handlers `IAgileObject` automatically. `comtypes.COMObject` does NOT — you must list it:

```python
class _CompletionHandler(comtypes.COMObject):
    _com_interfaces_ = [
        IActivateAudioInterfaceCompletionHandler,
        IAgileObject,    # marker interface, no methods — apartment-neutrality
    ]
```

## Virtual device path is a literal string, NOT a GUID

Per `mmdeviceapi.h`: `#define VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK L"VAD\\Process_Loopback"`. Passing a braced GUID here returns `0x8000000E` synchronously. Our constant is `"VAD\\Process_Loopback"` (Python string with one backslash).

## ctypes arg passing: use `c_void_p` + manual `ctypes.cast`

`ActivateAudioInterfaceAsync.argtypes` is `[c_wchar_p, c_void_p, c_void_p, c_void_p, c_void_p]`. Raw pointer addresses are extracted via `ctypes.cast(ptr, c_void_p).value` and passed as integers. `POINTER(Interface)` argtypes combined with `comtypes.COMObject` instances produce silent coercion failures across comtypes versions — don't use them for C-style API calls.

## Never cache a COM-packet generator

`ProcessCaptureStream._drain_real_source` re-enters `read_next_packet` on every `read_available()` call. A generator that `return`s once is permanently dead — caching one made the stream go silent after the first empty tick. If a COM packet drain loop feels "idiomatic to make a generator", resist.

## Interpret buffers with the Initialize format, never GetMixFormat

The engine delivers buffers in the format passed to `Initialize` (we request 48000/2/float32) — NOT the endpoint mix format. Deriving `native_rate/channels/format/frame_bytes` from `GetMixFormat()` pitch-shifted audio ~8.8% on 44.1 kHz endpoints and over-read the buffer 3x on surround mixes (fixed in #22). `activate_process_loopback` now derives all four from the requested format; keep it that way.

## Silent-capture detection (conferencing opt-out warning)

`ProcessCaptureStream.received_audio` flips on the first non-silent sample (`read_available`); `ProcessAudioCapture.has_received_audio` aggregates; `DualAudioCapture.system_audio_received()` returns True for legacy/no-system configs. `MainWindow._check_silent_capture` warns once at 15s of recording with zero audio received (the Teams/Zoom opt-out symptom). Keep these in sync when touching packet handling.

## HRESULT `0x8000000E` = `E_ILLEGAL_METHOD_CALL`, not a device error

Generic-facility severity-only HRESULT meaning "precondition violated / object in wrong state". Three different PIDs returning the same `0x8000000E` synchronously means a handler or argument config bug — not PID-specific. Check IAgileObject, device path, handler QueryInterface, and PROPVARIANT layout in that order.

## `comtypes.COMObject` subclass methods don't take `this`

The vtable `this` pointer is handled by comtypes internally. Declare methods with only the IDL arg list:

```python
def ActivateCompleted(self, activate_operation):  # no `this` parameter
    ...
```

Adding `this` as a positional arg shifts the real args by one and silently breaks the callback.

## Capture pipeline structure (for orientation)

- `ProcessCaptureStream.activate()` is synchronous. It owns the COM objects for one PID (`_client`, `_capture_client`, `_native_frame_bytes`, resampler).
- `ProcessAudioCapture` owns the single 10 ms polling thread. PIDs are locked at `start()` — no live add/remove.
- Partial activation is tolerated: `start()` returns `{"total": N, "active": K, "failures": {pid: hresult_name}}` and `DualAudioCapture.start()` only raises when `active == 0`.
- `DualAudioCapture` dispatches: `capture_mode == "per_app" and app_pids` → `ProcessAudioCapture`; otherwise → `LoopbackStream` (legacy). The attribute is `self.system_stream` on both branches.
- System activates BEFORE mic in `DualAudioCapture.start()` so an all-PIDs-failed raise doesn't leave the mic orphaned.

## Conferencing apps opt out of process-loopback capture

Windows 11 audio clients can set `AUDCLNT_STREAMFLAGS_EXCLUDE_FROM_PROCESS_LOOPBACK_CAPTURE` on their `IAudioClient` to make per-process loopback return silence for that stream. Microsoft Teams, Zoom, WebEx, and similar call apps set this flag on their **call audio** stream (for privacy) but usually not on notification/chime streams. Observable symptom: per-app capture records chat chimes but silent call audio.

This is a Windows-level opt-out; there is no per-app code change that bypasses it. Fallbacks that work:

- **Device-level WASAPI loopback** (legacy mode in TalkTrack — `LoopbackStream`) taps the endpoint post-mix. The opt-out flag only blocks the per-process API path, so device loopback still captures everything the user hears.
- **Inverse process-loopback** (`PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE` on TalkTrack's own PID) — untested whether it respects the opt-out; docs are ambiguous. If ever pursued, confirm with a real Teams call first.

The `SourceSelector` maintains `CONFERENCING_APPS` (`app/ui/source_selector.py`) and shows a warning banner when any of those are checked in per-app mode. Keep that set in sync with the friendly names emitted by `audio_session_monitor._friendly_name`.

Diagnostic script: `scripts/find_call_audio_pid.py` — enumerates pycaw sessions with State + parent chain. Run during a call to identify which PID renders call audio; if the PID is captured but silent, the opt-out flag is likely the cause.

## Re-enabling per-step diagnostic logs

Routine logs live at DEBUG. One-line INFO per success. To see full activation trace (apartment, pointer values, each COM call):

```python
import logging
logging.getLogger("app.recording._process_com").setLevel(logging.DEBUG)
```
