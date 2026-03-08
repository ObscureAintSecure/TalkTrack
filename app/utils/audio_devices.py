import sounddevice as sd


def get_input_devices():
    """Return list of audio input (microphone) devices."""
    devices = sd.query_devices()
    inputs = []
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
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


def get_wasapi_output_devices():
    """Return WASAPI output devices that can be used for loopback recording."""
    devices = sd.query_devices()
    outputs = []
    for i, dev in enumerate(devices):
        hostapi = sd.query_hostapis(dev["hostapi"])
        if hostapi["name"] == "Windows WASAPI" and dev["max_output_channels"] > 0:
            outputs.append({
                "index": i,
                "name": dev["name"],
                "channels": dev["max_output_channels"],
                "sample_rate": dev["default_samplerate"],
                "hostapi": "WASAPI",
                "is_loopback_capable": True,
            })
    return outputs


def get_default_mic():
    """Return the default microphone device index."""
    try:
        return sd.default.device[0]
    except Exception:
        inputs = get_input_devices()
        return inputs[0]["index"] if inputs else None


def get_default_output():
    """Return the default output device index (for loopback)."""
    try:
        return sd.default.device[1]
    except Exception:
        outputs = get_wasapi_output_devices()
        return outputs[0]["index"] if outputs else None
