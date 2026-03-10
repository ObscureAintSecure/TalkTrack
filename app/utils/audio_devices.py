import sounddevice as sd


def _is_hidden(name, hidden_devices):
    """Check if a device name matches any hidden device pattern (case-insensitive)."""
    if not hidden_devices:
        return False
    name_lower = name.lower()
    for pattern in hidden_devices:
        if pattern.lower() in name_lower:
            return True
    return False


def get_input_devices(hidden_devices=None):
    """Return list of audio input (microphone) devices."""
    devices = sd.query_devices()
    inputs = []
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            if _is_hidden(dev["name"], hidden_devices):
                continue
            inputs.append({
                "index": i,
                "name": dev["name"],
                "channels": dev["max_input_channels"],
                "sample_rate": dev["default_samplerate"],
                "hostapi": sd.query_hostapis(dev["hostapi"])["name"],
            })
    return inputs


def get_loopback_devices():
    """Return list of WASAPI loopback devices for system audio capture."""
    devices = sd.query_devices()
    loopbacks = []
    for i, dev in enumerate(devices):
        hostapi = sd.query_hostapis(dev["hostapi"])
        if hostapi["name"] == "Windows WASAPI" and dev["max_input_channels"] > 0:
            if "loopback" in dev["name"].lower() or dev["max_output_channels"] > 0:
                loopbacks.append({
                    "index": i,
                    "name": dev["name"],
                    "channels": dev["max_input_channels"],
                    "sample_rate": dev["default_samplerate"],
                    "hostapi": "WASAPI",
                })
    return loopbacks


def get_system_audio_devices(hidden_devices=None):
    """Return WASAPI output devices for system audio loopback capture.

    These are speakers/headphone output devices. PyAudioWPatch automatically
    finds the corresponding loopback input device by name matching.
    """
    devices = sd.query_devices()
    outputs = []
    for i, dev in enumerate(devices):
        hostapi = sd.query_hostapis(dev["hostapi"])
        if hostapi["name"] == "Windows WASAPI" and dev["max_output_channels"] > 0:
            if _is_hidden(dev["name"], hidden_devices):
                continue
            outputs.append({
                "index": i,
                "name": dev["name"],
                "channels": dev["max_output_channels"],
                "sample_rate": dev["default_samplerate"],
                "hostapi": "WASAPI",
            })
    return outputs


# Keep old name as alias
get_wasapi_output_devices = get_system_audio_devices


def get_default_mic():
    """Return the default microphone device index."""
    try:
        return sd.default.device[0]
    except Exception:
        inputs = get_input_devices()
        return inputs[0]["index"] if inputs else None


def get_default_output():
    """Return the default output device index (for loopback).

    sd.default.device[1] returns a DirectSound/MME index which doesn't match
    WASAPI device indices. We match by name instead to find the corresponding
    WASAPI output device.
    """
    try:
        default_idx = sd.default.device[1]
        if default_idx is not None and default_idx >= 0:
            default_info = sd.query_devices(default_idx)
            default_name = default_info["name"]
            # Find the matching WASAPI output device by name
            for dev in get_system_audio_devices():
                if dev["name"] == default_name:
                    return dev["index"]
    except Exception:
        pass
    outputs = get_system_audio_devices()
    return outputs[0]["index"] if outputs else None
