"""Legacy output reconnection with a continuous, pause-aware audio timeline."""
import threading
import time
import numpy as np


def default_output_name():
    # Query Core Audio afresh: PortAudio's device/default list is a startup snapshot.
    import comtypes
    from pycaw.pycaw import AudioUtilities
    comtypes.CoInitialize()
    try:
        return AudioUtilities.GetSpeakers().FriendlyName
    finally:
        comtypes.CoUninitialize()


class TimelineSink:
    def __init__(self, sink, sample_rate, clock=time.monotonic):
        self.sink, self.rate, self.clock = sink, sample_rate, clock
        self.started = clock()
        self.paused_at = None
        self.paused_seconds = 0.0
        self.frames = 0
        self.has_audio = False
        self.closed = False
        self.generation = 0
        self.lock = threading.Lock()

    def _position(self):
        now = self.paused_at if self.paused_at is not None else self.clock()
        return max(0, round((now - self.started - self.paused_seconds) * self.rate))

    def _pad(self, position):
        gap = max(0, position - self.frames)
        if gap:
            self.sink.put_silence(gap)
            self.frames += gap

    def next_generation(self):
        with self.lock:
            self.generation += 1
            return self.generation

    def put(self, chunk, generation=None, captured_at=None):
        with self.lock:
            if self.closed or self.paused_at is not None or (generation is not None and generation != self.generation):
                return
            if captured_at is None:
                start = self._position() - len(chunk)
            else:
                # Native capture timestamps preserve buffered audio delivered late.
                start = round((captured_at - self.started - self.paused_seconds) * self.rate)
            if start < 0:
                chunk = chunk[-start:]
                start = 0
            # Correct both directions, with a small allowance for clock jitter.
            delta = start - self.frames
            if delta > self.rate * 0.05:
                self._pad(start)
            elif delta < -self.rate * 0.05:
                chunk = chunk[min(len(chunk), -delta):]
            if len(chunk):
                self.sink.put(chunk)
                self.frames += len(chunk)
                self.has_audio = True

    def pause(self):
        with self.lock:
            if self.paused_at is None:
                if self.has_audio:
                    self._pad(self._position())
                self.paused_at = self.clock()

    def resume(self):
        with self.lock:
            if self.paused_at is not None:
                self.paused_seconds += self.clock() - self.paused_at
                self.paused_at = None

    def finish(self):
        with self.lock:
            if not self.closed:
                if self.has_audio:
                    self._pad(self._position())
                self.closed = True


class SwitchingLoopbackStream:
    """One output at a time; reconnect off the GUI thread and keep the mic untouched.

    None follows Windows' default multimedia output. A name pins an endpoint.
    '__disabled__' intentionally captures silence until another source is selected.
    """
    def __init__(self, device_name=None, sample_rate=16000, level_callback=None,
                 sink=None, factory=None, resolver=default_output_name):
        self.requested = device_name
        self.rate = sample_rate
        self.level_callback = level_callback
        self.timeline = TimelineSink(sink, sample_rate)
        self.factory = factory
        self.resolver = resolver
        self.stream = None
        self.current = None
        self.paused = False
        self.status = 'Connecting system audio...'
        self.last_packet = time.monotonic()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.RLock()
        self._thread = None

    def set_device(self, name):
        with self._lock:
            self.requested = name
        self._wake.set()

    def _level(self, chunk):
        self.last_packet = time.monotonic()
        if self.level_callback:
            self.level_callback(chunk)

    def _close_stream(self):
        self.timeline.next_generation()
        with self._lock:
            old_stream = self.stream
            self.stream = None
            self.current = None
        if old_stream is not None:
            old_stream.stop()

    def _step(self):
        try:
            with self._lock:
                requested = self.requested
                stream, current = self.stream, self.current
            target = self.resolver() if requested is None else requested
            if target == '__disabled__':
                self._close_stream()
                self.status = 'System audio disabled; microphone continues'
                return
            if stream is None or target != current or not stream.is_active:
                self._close_stream()
                self.status = 'Reconnecting system audio...'
                factory = self.factory
                if factory is None:
                    from app.recording.audio_capture import LoopbackStream
                    factory = LoopbackStream
                generation = self.timeline.next_generation()
                timeline = self.timeline
                class StreamSink:
                    def put(self, chunk):
                        timeline.put(chunk, generation=generation)
                    def put_timed(self, chunk, captured_at):
                        timeline.put(chunk, generation=generation, captured_at=captured_at)
                candidate = factory(device_name=target, sample_rate=self.rate,
                                    level_callback=self._level, sink=StreamSink())
                try:
                    candidate.start()
                except Exception:
                    candidate.stop()
                    raise
                with self._lock:
                    stale = self._stop.is_set() or self.requested != requested
                    if not stale:
                        self.stream, self.current = candidate, target
                        if self.paused:
                            candidate.pause()
                if stale:
                    self.timeline.next_generation()
                    candidate.stop()
                    return
                self.last_packet = time.monotonic()
            with self._lock:
                paused = self.paused
            if not paused and time.monotonic() - self.last_packet > 10:
                self.status = 'No system audio arriving; check playback/output: ' + target
            else:
                self.status = ('Paused: ' if paused else 'System audio: ') + target
        except Exception as exc:
            self._close_stream()
            self.status = 'System audio unavailable; retrying (' + type(exc).__name__ + ')'

    def _run(self):
        try:
            while not self._stop.is_set():
                self._step()
                self._wake.wait(0.75)
                self._wake.clear()
        finally:
            self._close_stream()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self):
        self.timeline.pause()
        with self._lock:
            self.paused = True
            if self.stream:
                self.stream.pause()
        self._wake.set()

    def resume(self):
        self.timeline.resume()
        with self._lock:
            self.paused = False
            if self.stream:
                self.stream.resume()
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()
        # Freeze audio at the user's stop time; driver shutdown may take seconds.
        self.timeline.finish()
        if self._thread:
            self._thread.join(timeout=5)
        if self._thread is None or not self._thread.is_alive():
            self._close_stream()

    @property
    def is_active(self):
        return not self._stop.is_set() and self.stream is not None and self.stream.is_active
