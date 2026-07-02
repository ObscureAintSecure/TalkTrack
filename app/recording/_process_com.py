"""Windows 11 process-loopback COM shim.

This module owns ctypes struct definitions, GUID constants, HRESULT name
mapping, and the thin wrappers that call into comtypes. It exists as a
separate file because mocking these is a high-effort/low-signal rabbit hole
- downstream code injects fakes for the activate/read functions when testing.
"""

import logging
import ctypes
from ctypes import (
    POINTER, byref, c_void_p, c_int32, c_uint32, c_uint64, c_wchar_p,
    c_ubyte,
)
from ctypes import wintypes

import comtypes
from comtypes import GUID, COMMETHOD, IUnknown

logger = logging.getLogger(__name__)


# --- HRESULT codes from Audioclient.h / winerror.h ---

_HRESULT_NAMES = {
    0x00000000: "S_OK",
    0x80004001: "E_NOTIMPL",
    0x80004002: "E_NOINTERFACE",
    0x80004003: "E_POINTER",
    0x80004004: "E_ABORT",
    0x80004005: "E_FAIL",
    0x80070005: "E_ACCESSDENIED",
    0x80070057: "E_INVALIDARG",
    0x80070490: "ERROR_NOT_FOUND_HRESULT",
    0x8007000E: "E_OUTOFMEMORY",
    0x80010106: "RPC_E_CHANGED_MODE",
    # AUDCLNT_ERR codes (AUDCLNT severity bits = 0x8889xxxx)
    0x88890001: "AUDCLNT_E_NOT_INITIALIZED",
    0x88890002: "AUDCLNT_E_ALREADY_INITIALIZED",
    0x88890003: "AUDCLNT_E_WRONG_ENDPOINT_TYPE",
    0x88890004: "AUDCLNT_E_DEVICE_INVALIDATED",
    0x88890005: "AUDCLNT_E_NOT_STOPPED",
    0x88890006: "AUDCLNT_E_BUFFER_TOO_LARGE",
    0x88890008: "AUDCLNT_E_OUT_OF_ORDER",
    0x88890009: "AUDCLNT_E_UNSUPPORTED_FORMAT",
    0x8889000A: "AUDCLNT_E_INVALID_SIZE",
    0x8889000B: "AUDCLNT_E_DEVICE_IN_USE",
    0x8889000C: "AUDCLNT_E_BUFFER_OPERATION_PENDING",
    0x88890017: "AUDCLNT_E_CPUUSAGE_EXCEEDED",
    0x88890021: "AUDCLNT_E_RESOURCES_INVALIDATED",
}


def hresult_name(hr):
    """Map an HRESULT to a symbolic name, falling back to hex for unknowns."""
    hr_u32 = hr & 0xFFFFFFFF
    if hr_u32 in _HRESULT_NAMES:
        return _HRESULT_NAMES[hr_u32]
    return f"0x{hr_u32:08X}"


# --- Constants from audioclient.h / audioclientactivationparams.h ---

# Virtual audio device path for per-process loopback. Per mmdeviceapi.h:
#   #define VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK L"VAD\\Process_Loopback"
# It is a device-interface-path string, NOT a GUID. ActivateAudioInterfaceAsync
# recognizes this literal. Passing a GUID string here returns an obscure
# MMDevAPI failure (0x8000000E) — been there, done that.
VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"

AUDIOCLIENT_ACTIVATION_TYPE_DEFAULT = 0
AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1

PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0
PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE = 1

AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_SHAREMODE_SHARED = 0

WAVE_FORMAT_PCM = 0x0001
WAVE_FORMAT_IEEE_FLOAT = 0x0003

AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY = 0x1
AUDCLNT_BUFFERFLAGS_SILENT = 0x2
AUDCLNT_BUFFERFLAGS_TIMESTAMP_ERROR = 0x4

AUDCLNT_S_BUFFER_EMPTY = 0x08890001

AUDCLNT_E_DEVICE_INVALIDATED = 0x88890004
E_ACCESSDENIED = 0x80070005

# CoInitializeEx flags.
COINIT_MULTITHREADED = 0x0
RPC_E_CHANGED_MODE = 0x80010106


# --- Struct definitions ---

class AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(ctypes.Structure):
    _fields_ = [
        ("TargetProcessId", wintypes.DWORD),
        ("ProcessLoopbackMode", wintypes.DWORD),
    ]


class AUDIOCLIENT_ACTIVATION_PARAMS(ctypes.Structure):
    """Passed as a PROPVARIANT(VT_BLOB) to ActivateAudioInterfaceAsync."""
    _fields_ = [
        ("ActivationType", wintypes.DWORD),
        ("ProcessLoopbackParams", AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS),
    ]


class WAVEFORMATEX(ctypes.Structure):
    """WAVEFORMATEX as defined in mmreg.h."""
    _pack_ = 1
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


class _BLOB(ctypes.Structure):
    _fields_ = [("cbSize", c_uint32), ("pBlobData", c_void_p)]


class _PROPVARIANT(ctypes.Structure):
    """PROPVARIANT for VT_BLOB carry — 24 bytes on 64-bit Windows.

    Header: vt(2) + wReserved1(2) + wReserved2(2) + wReserved3(2) = 8 bytes.
    Union:  16 bytes on 64-bit (largest variant member — accommodates DECIMAL).
    The BLOB layout (cbSize DWORD + pointer) on 64-bit is 4 + 4 pad + 8 = 16 bytes,
    which fills the union exactly. Do NOT add extra padding — Windows reads this
    by-value, and an oversized struct shifts the activation function's arg list.
    """
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("wReserved1", ctypes.c_ushort),
        ("wReserved2", ctypes.c_ushort),
        ("wReserved3", ctypes.c_ushort),
        ("blob", _BLOB),
    ]


def make_format_ieee_float(sample_rate=48000, channels=2, bits=32):
    """Build a WAVEFORMATEX for IEEE_FLOAT PCM."""
    fmt = WAVEFORMATEX()
    fmt.wFormatTag = WAVE_FORMAT_IEEE_FLOAT
    fmt.nChannels = channels
    fmt.nSamplesPerSec = sample_rate
    fmt.wBitsPerSample = bits
    fmt.nBlockAlign = (channels * bits) // 8
    fmt.nAvgBytesPerSec = sample_rate * fmt.nBlockAlign
    fmt.cbSize = 0
    return fmt


# --- COM GUIDs ---

IID_IActivateAudioInterfaceCompletionHandler = GUID(
    "{41D949AB-9862-444A-80F6-C261334DA5EB}"
)
IID_IActivateAudioInterfaceAsyncOperation = GUID(
    "{72A22D78-CDE4-431D-B8CC-843A71199B6D}"
)
IID_IAudioClient = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")
IID_IAudioCaptureClient = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
# Marker interface — apartment-neutral / thread-agile. Required by
# ActivateAudioInterfaceAsync on the completion handler (the C++ samples get
# this for free via WRL::RuntimeClass; Python COMObject doesn't).
IID_IAgileObject = GUID("{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}")


# --- COM interfaces ---

# REFERENCE_TIME is LONGLONG (signed 64-bit, 100 ns units).
REFERENCE_TIME = ctypes.c_longlong


class IActivateAudioInterfaceAsyncOperation(IUnknown):
    _iid_ = IID_IActivateAudioInterfaceAsyncOperation
    _methods_ = [
        COMMETHOD(
            [], comtypes.HRESULT, "GetActivateResult",
            (["out"], POINTER(comtypes.HRESULT), "activateResult"),
            (["out"], POINTER(POINTER(IUnknown)), "activatedInterface"),
        ),
    ]


class IActivateAudioInterfaceCompletionHandler(IUnknown):
    _iid_ = IID_IActivateAudioInterfaceCompletionHandler
    _methods_ = [
        COMMETHOD(
            [], comtypes.HRESULT, "ActivateCompleted",
            (["in"], POINTER(IActivateAudioInterfaceAsyncOperation),
             "activateOperation"),
        ),
    ]


class IAgileObject(IUnknown):
    """Marker interface — apartment-neutral object. No methods beyond IUnknown.

    Required on the ActivateAudioInterfaceAsync completion handler so Windows
    can safely invoke it from whichever apartment the async machinery chooses.
    """
    _iid_ = IID_IAgileObject
    _methods_ = []


class IAudioClient(IUnknown):
    """Subset of IAudioClient. Methods MUST be declared in vtable order, from
    the first method after IUnknown's QueryInterface/AddRef/Release triad.
    We declare all 12 to keep slot offsets correct; only a few are called."""
    _iid_ = IID_IAudioClient
    _methods_ = [
        COMMETHOD(
            [], comtypes.HRESULT, "Initialize",
            (["in"], c_uint32, "ShareMode"),
            (["in"], c_uint32, "StreamFlags"),
            (["in"], REFERENCE_TIME, "hnsBufferDuration"),
            (["in"], REFERENCE_TIME, "hnsPeriodicity"),
            (["in"], POINTER(WAVEFORMATEX), "pFormat"),
            (["in"], POINTER(GUID), "AudioSessionGuid"),
        ),
        COMMETHOD(
            [], comtypes.HRESULT, "GetBufferSize",
            (["out"], POINTER(c_uint32), "pNumBufferFrames"),
        ),
        COMMETHOD(
            [], comtypes.HRESULT, "GetStreamLatency",
            (["out"], POINTER(REFERENCE_TIME), "phnsLatency"),
        ),
        COMMETHOD(
            [], comtypes.HRESULT, "GetCurrentPadding",
            (["out"], POINTER(c_uint32), "pNumPaddingFrames"),
        ),
        COMMETHOD(
            [], comtypes.HRESULT, "IsFormatSupported",
            (["in"], c_uint32, "ShareMode"),
            (["in"], POINTER(WAVEFORMATEX), "pFormat"),
            (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppClosestMatch"),
        ),
        COMMETHOD(
            [], comtypes.HRESULT, "GetMixFormat",
            (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppDeviceFormat"),
        ),
        COMMETHOD(
            [], comtypes.HRESULT, "GetDevicePeriod",
            (["out"], POINTER(REFERENCE_TIME), "phnsDefaultDevicePeriod"),
            (["out"], POINTER(REFERENCE_TIME), "phnsMinimumDevicePeriod"),
        ),
        COMMETHOD([], comtypes.HRESULT, "Start"),
        COMMETHOD([], comtypes.HRESULT, "Stop"),
        COMMETHOD([], comtypes.HRESULT, "Reset"),
        COMMETHOD(
            [], comtypes.HRESULT, "SetEventHandle",
            (["in"], wintypes.HANDLE, "eventHandle"),
        ),
        COMMETHOD(
            [], comtypes.HRESULT, "GetService",
            (["in"], POINTER(GUID), "riid"),
            (["out"], POINTER(c_void_p), "ppv"),
        ),
    ]


class IAudioCaptureClient(IUnknown):
    _iid_ = IID_IAudioCaptureClient
    _methods_ = [
        COMMETHOD(
            [], comtypes.HRESULT, "GetBuffer",
            (["out"], POINTER(POINTER(c_ubyte)), "ppData"),
            (["out"], POINTER(c_uint32), "pNumFramesToRead"),
            (["out"], POINTER(c_uint32), "pdwFlags"),
            (["out"], POINTER(c_uint64), "pu64DevicePosition"),
            (["out"], POINTER(c_uint64), "pu64QPCPosition"),
        ),
        COMMETHOD(
            [], comtypes.HRESULT, "ReleaseBuffer",
            (["in"], c_uint32, "NumFramesRead"),
        ),
        COMMETHOD(
            [], comtypes.HRESULT, "GetNextPacketSize",
            (["out"], POINTER(c_uint32), "pNumFramesInNextPacket"),
        ),
    ]


class _CompletionHandler(comtypes.COMObject):
    """Python COM object that signals a Win32 event when activation completes.

    Implements BOTH IActivateAudioInterfaceCompletionHandler (the callback
    surface) AND IAgileObject (the apartment-neutrality marker). Without
    IAgileObject, ActivateAudioInterfaceAsync fails synchronously with
    E_ILLEGAL_METHOD_CALL (0x8000000E) because it can't safely marshal the
    callback across apartments.

    comtypes COMObject method signatures do NOT include the `this` pointer —
    the library handles that internally.
    """
    _com_interfaces_ = [
        IActivateAudioInterfaceCompletionHandler,
        IAgileObject,
    ]

    def __init__(self, event_handle):
        super().__init__()
        self._event = event_handle

    def ActivateCompleted(self, activate_operation):
        ctypes.windll.kernel32.SetEvent(self._event)
        return 0   # S_OK


# --- Activated-context wrapper ---

class _ActivatedContext:
    """Bundles the activated IAudioClient + IAudioCaptureClient + format info.

    ProcessCaptureStream stores the pieces it needs via getattr, so this
    duck-types cleanly against the lightweight objects test fakes produce.
    """
    def __init__(self, audio_client, capture_client, native_rate,
                 native_channels, native_format, native_frame_bytes):
        self.audio_client = audio_client
        self.capture_client = capture_client
        self.native_rate = native_rate
        self.native_channels = native_channels
        self.native_format = native_format
        self.native_frame_bytes = native_frame_bytes


def _format_info_from_waveformatex(fmt):
    """Inspect a WAVEFORMATEX and produce the (rate, channels, format_tag, frame_bytes) tuple."""
    rate = int(fmt.nSamplesPerSec)
    channels = int(fmt.nChannels)
    bits = int(fmt.wBitsPerSample)
    tag = int(fmt.wFormatTag)
    block_align = int(fmt.nBlockAlign) or (channels * bits // 8)

    # Determine our internal format_tag string.
    # WAVE_FORMAT_EXTENSIBLE (0xFFFE) carries the real tag in a sub-format GUID
    # but for process-loopback the default Windows path returns float32, so we
    # treat anything reporting 32-bit float as "float32" and fall back to the
    # wave-format-tag otherwise.
    if tag == WAVE_FORMAT_IEEE_FLOAT or (tag == 0xFFFE and bits == 32):
        format_tag = "float32"
    elif tag == WAVE_FORMAT_PCM and bits == 16:
        format_tag = "s16"
    elif tag == WAVE_FORMAT_PCM and bits in (24, 32):
        format_tag = "s24"
    else:
        format_tag = "float32"   # best effort; resample_poly will still work
    return rate, channels, format_tag, block_align


def _query_apartment_type():
    """Return a short string describing the thread's COM apartment, for logging."""
    try:
        apt_type = ctypes.c_int(0)
        apt_qualifier = ctypes.c_int(0)
        CoGetApartmentType = ctypes.windll.ole32.CoGetApartmentType
        CoGetApartmentType.restype = ctypes.c_long
        CoGetApartmentType.argtypes = [POINTER(ctypes.c_int), POINTER(ctypes.c_int)]
        hr = CoGetApartmentType(byref(apt_type), byref(apt_qualifier))
        if hr != 0:
            return f"<CoGetApartmentType hr=0x{hr & 0xFFFFFFFF:08X}>"
        # APTTYPE enum from objidlbase.h:
        # CURRENT = -1, STA = 0, MTA = 1, NA = 2, MAINSTA = 3
        names = {-1: "CURRENT", 0: "STA", 1: "MTA", 2: "NA", 3: "MAIN_STA"}
        return f"{names.get(apt_type.value, apt_type.value)} (qual={apt_qualifier.value})"
    except Exception as e:
        return f"<query failed: {e}>"


def activate_process_loopback(pid, timeout_ms=5000):
    """Synchronously activate an IAudioClient + IAudioCaptureClient for one PID.

    Returns (_ActivatedContext, hresult: int).
    On success, hresult == 0 and the context holds the live COM pointers.
    On any failure, returns (None, hresult). The caller translates the hresult
    via hresult_name().
    """
    import threading

    # MTA init. CoInitializeEx returns S_OK on first call, S_FALSE if already
    # initialized in the same mode, or RPC_E_CHANGED_MODE if the thread is STA.
    hr_init = ctypes.windll.ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
    hr_init_u32 = hr_init & 0xFFFFFFFF
    logger.debug("[PID %s] thread=%s CoInitializeEx(MTA) -> %s (0x%08X) apt=%s",
                 pid, threading.current_thread().name,
                 hresult_name(hr_init_u32), hr_init_u32,
                 _query_apartment_type())
    if hr_init_u32 == RPC_E_CHANGED_MODE:
        return None, RPC_E_CHANGED_MODE

    # Build AUDIOCLIENT_ACTIVATION_PARAMS.
    params = AUDIOCLIENT_ACTIVATION_PARAMS()
    params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
    params.ProcessLoopbackParams.TargetProcessId = pid
    params.ProcessLoopbackParams.ProcessLoopbackMode = (
        PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE
    )

    # Wrap as PROPVARIANT(VT_BLOB). Keep `params` in scope — pBlobData is a
    # raw pointer into its buffer and the activation is async. Holding it on
    # this function's local stack frame is sufficient because we block on
    # WaitForSingleObject before returning.
    pv = _PROPVARIANT()
    pv.vt = 0x41   # VT_BLOB
    pv.blob.cbSize = ctypes.sizeof(params)
    params_addr = ctypes.addressof(params)
    pv.blob.pBlobData = ctypes.cast(params_addr, c_void_p)

    # Manual-reset event for the handler to signal.
    event_handle = ctypes.windll.kernel32.CreateEventW(None, True, False, None)
    if not event_handle:
        logger.warning("[PID %s] CreateEventW failed", pid)
        return None, 0x80004005

    handler_obj = _CompletionHandler(event_handle)

    # QueryInterface to get a genuine COM pointer for the handler. This is
    # passed as a raw c_void_p below, bypassing ctypes' interface-aware
    # coercion path entirely.
    try:
        handler_ptr = handler_obj.QueryInterface(
            IActivateAudioInterfaceCompletionHandler,
        )
    except comtypes.COMError as ce:
        ctypes.windll.kernel32.CloseHandle(event_handle)
        logger.warning("[PID %s] QueryInterface on handler failed: 0x%08X",
                       pid, ce.hresult & 0xFFFFFFFF)
        return None, ce.hresult & 0xFFFFFFFF

    try:
        # Call via WinDLL with c_void_p throughout — no interface-aware
        # coercion, we pass raw pointers. Previous approach with
        # POINTER(Interface) argtypes was silently producing an invalid
        # handler pointer, which is why the API kept returning
        # E_ILLEGAL_METHOD_CALL (0x8000000E) synchronously.
        mmdev = ctypes.WinDLL("Mmdevapi.dll")
        ActivateAudioInterfaceAsync = mmdev.ActivateAudioInterfaceAsync
        ActivateAudioInterfaceAsync.restype = ctypes.c_long
        ActivateAudioInterfaceAsync.argtypes = [
            c_wchar_p, c_void_p, c_void_p, c_void_p, c_void_p,
        ]
        operation_ptr = c_void_p(0)

        pv_addr = ctypes.cast(ctypes.pointer(pv), c_void_p).value
        iid_addr = ctypes.cast(ctypes.pointer(IID_IAudioClient), c_void_p).value
        handler_raw = ctypes.cast(handler_ptr, c_void_p).value

        logger.debug(
            "[PID %s] ActivateAudioInterfaceAsync args: device=%r, "
            "params_addr=0x%X size=%d, pv_addr=0x%X, iid_addr=0x%X, handler=0x%X",
            pid, VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
            params_addr, ctypes.sizeof(params),
            pv_addr, iid_addr, handler_raw,
        )

        hr = ActivateAudioInterfaceAsync(
            VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
            iid_addr,
            pv_addr,
            handler_raw,
            ctypes.cast(ctypes.pointer(operation_ptr), c_void_p),
        )
        hr_u32 = hr & 0xFFFFFFFF
        if hr != 0:
            logger.warning("[PID %s] ActivateAudioInterfaceAsync -> %s (0x%08X)",
                           pid, hresult_name(hr_u32), hr_u32)
            return None, hr_u32
        logger.debug("[PID %s] ActivateAudioInterfaceAsync -> S_OK", pid)

        # operation_ptr now holds the async-operation pointer as a raw
        # address. Wrap it as a proper interface pointer for GetActivateResult.
        operation = ctypes.cast(
            operation_ptr, POINTER(IActivateAudioInterfaceAsyncOperation),
        )

        # Wait for the completion handler to SetEvent.
        wait_result = ctypes.windll.kernel32.WaitForSingleObject(
            event_handle, timeout_ms,
        )
        if wait_result != 0:
            logger.warning("[PID %s] WaitForSingleObject -> 0x%08X",
                           pid, wait_result)
            return None, 0x80004005

        activate_hr, activated = operation.GetActivateResult()
        activate_hr_u32 = activate_hr & 0xFFFFFFFF if activate_hr else 0
        if activate_hr != 0 or not activated:
            logger.warning("[PID %s] GetActivateResult -> %s (0x%08X), activated=%r",
                           pid, hresult_name(activate_hr_u32),
                           activate_hr_u32, bool(activated))
            return None, activate_hr_u32 if activate_hr else 0x80004003

        try:
            audio_client = activated.QueryInterface(IAudioClient)
        except comtypes.COMError as ce:
            logger.warning("[PID %s] QueryInterface(IAudioClient) failed: 0x%08X",
                           pid, ce.hresult & 0xFFFFFFFF)
            return None, ce.hresult & 0xFFFFFFFF

        requested_format = make_format_ieee_float(48000, 2, 32)
        try:
            audio_client.Initialize(
                AUDCLNT_SHAREMODE_SHARED,
                AUDCLNT_STREAMFLAGS_LOOPBACK,
                2_000_000,
                0,
                byref(requested_format),
                None,
            )
        except comtypes.COMError as ce:
            logger.warning("[PID %s] Initialize failed: 0x%08X",
                           pid, ce.hresult & 0xFFFFFFFF)
            return None, ce.hresult & 0xFFFFFFFF

        # The engine delivers buffers in the format we Initialize()d with, NOT
        # the endpoint mix format. GetMixFormat() can differ (44.1 kHz, >2ch,
        # 24-bit) and interpreting the requested-format buffers with it
        # pitch-shifts the audio or over-reads the buffer.
        native_rate, native_channels, native_format, native_frame_bytes = (
            _format_info_from_waveformatex(requested_format)
        )
        logger.debug("[PID %s] negotiated format: %d Hz x %d ch (%s), frame_bytes=%d",
                     pid, native_rate, native_channels, native_format,
                     native_frame_bytes)

        try:
            capture_client_void = audio_client.GetService(byref(IID_IAudioCaptureClient))
        except comtypes.COMError as ce:
            logger.warning("[PID %s] GetService(IAudioCaptureClient) failed: 0x%08X",
                           pid, ce.hresult & 0xFFFFFFFF)
            return None, ce.hresult & 0xFFFFFFFF

        capture_client = ctypes.cast(
            capture_client_void, POINTER(IAudioCaptureClient),
        )

        try:
            audio_client.Start()
        except comtypes.COMError as ce:
            logger.warning("[PID %s] Start failed: 0x%08X",
                           pid, ce.hresult & 0xFFFFFFFF)
            return None, ce.hresult & 0xFFFFFFFF

        logger.info(
            "[PID %s] per-app activation complete (%d Hz x %d ch, %s)",
            pid, native_rate, native_channels, native_format,
        )
        context = _ActivatedContext(
            audio_client=audio_client,
            capture_client=capture_client,
            native_rate=native_rate,
            native_channels=native_channels,
            native_format=native_format,
            native_frame_bytes=native_frame_bytes,
        )
        return context, 0
    finally:
        ctypes.windll.kernel32.CloseHandle(event_handle)


def read_next_packet(capture_client, native_frame_bytes):
    """Drain the next available packet from an IAudioCaptureClient.

    Returns (data_bytes, frames, flags, hr).
    - On no packet ready: returns (None, 0, 0, 0).
    - On AUDCLNT_E_DEVICE_INVALIDATED: returns (None, 0, 0, 0x88890004).
    - On success: returns (bytes, frames, flags, 0).

    native_frame_bytes is the byte size of one frame (channels * bytes_per_sample)
    at the negotiated format. It comes from the format info captured at activation.
    """
    try:
        num_frames = capture_client.GetNextPacketSize()
    except comtypes.COMError as ce:
        hr = ce.hresult & 0xFFFFFFFF
        if hr == AUDCLNT_E_DEVICE_INVALIDATED:
            return None, 0, 0, hr
        raise

    if not num_frames:
        return None, 0, 0, 0

    try:
        data_ptr, frames, flags, _dev_pos, _qpc_pos = capture_client.GetBuffer()
    except comtypes.COMError as ce:
        hr = ce.hresult & 0xFFFFFFFF
        if hr == AUDCLNT_E_DEVICE_INVALIDATED:
            return None, 0, 0, hr
        raise

    byte_count = int(frames) * int(native_frame_bytes)
    if flags & AUDCLNT_BUFFERFLAGS_SILENT:
        raw = b"\x00" * byte_count
    else:
        raw = ctypes.string_at(data_ptr, byte_count)
    capture_client.ReleaseBuffer(frames)
    return raw, int(frames), int(flags), 0
