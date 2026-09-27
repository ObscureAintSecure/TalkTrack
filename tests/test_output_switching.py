import unittest
import threading
import time
from unittest.mock import Mock
import numpy as np
from app.recording.output_switching import TimelineSink, SwitchingLoopbackStream


class Sink:
    def __init__(self): self.parts = []
    def put(self, data): self.parts.append(np.asarray(data))
    def put_silence(self, frames): self.parts.append(np.zeros(frames))


class TestTimeline(unittest.TestCase):
    def test_no_packets_leave_system_track_empty(self):
        now = [0.0]
        out = Sink()
        sink = TimelineSink(out, 100, clock=lambda: now[0])
        now[0] = 1.0
        sink.pause()
        now[0] = 2.0
        sink.resume()
        now[0] = 3.0
        sink.finish()
        self.assertEqual(out.parts, [])

    def test_buffered_packets_use_capture_time_not_callback_arrival(self):
        now = [0.0]
        out = Sink()
        sink = TimelineSink(out, 100, clock=lambda: now[0])
        now[0] = 1.0
        sink.put(np.ones(100), captured_at=0.0)
        # Two buffered packets arrive late, almost together. Both are real audio.
        now[0] = 3.0
        sink.put(np.full(100, 2), captured_at=1.0)
        now[0] = 3.01
        sink.put(np.full(100, 3), captured_at=2.0)
        data = np.concatenate(out.parts)
        self.assertEqual(len(data), 300)
        np.testing.assert_array_equal(data[:100], 1)
        np.testing.assert_array_equal(data[100:200], 2)
        np.testing.assert_array_equal(data[200:], 3)

    def test_overlapping_packet_does_not_accumulate_forward_drift(self):
        now = [0.0]
        out = Sink()
        sink = TimelineSink(out, 100, clock=lambda: now[0])
        now[0] = 1.0
        sink.put(np.ones(100))
        now[0] = 1.1
        sink.put(np.full(100, 2))
        data = np.concatenate(out.parts)
        self.assertEqual(len(data), 110)
        np.testing.assert_array_equal(data[:100], 1)
        np.testing.assert_array_equal(data[100:], 2)

    def test_capture_timestamp_gap_and_pause_keep_original_positions(self):
        now = [10.0]
        out = Sink()
        sink = TimelineSink(out, 100, clock=lambda: now[0])
        now[0] = 11.0
        sink.put(np.ones(100), captured_at=10.0)
        sink.pause()
        now[0] = 21.0
        sink.resume()
        now[0] = 24.0
        sink.put(np.full(100, 2), captured_at=23.0)
        sink.finish()
        data = np.concatenate(out.parts)
        self.assertEqual(len(data), 400)
        np.testing.assert_array_equal(data[100:300], 0)
        np.testing.assert_array_equal(data[300:], 2)

    def test_stale_stream_cannot_write_after_switch(self):
        out = Sink()
        now = [0.0]
        sink = TimelineSink(out, 100, clock=lambda: now[0])
        old = sink.next_generation()
        new = sink.next_generation()
        now[0] = 0.1
        sink.put(np.ones(10), generation=old)
        sink.put(np.full(10, 2), generation=new)
        self.assertEqual(len(out.parts), 1)
        np.testing.assert_array_equal(out.parts[0], 2)

    def test_gap_is_silence_at_original_position(self):
        now = [0.0]
        out = Sink()
        sink = TimelineSink(out, 100, clock=lambda: now[0])
        now[0] = 1
        sink.put(np.ones(100))
        now[0] = 4
        sink.put(np.full(100, 2))
        sink.finish()
        data = np.concatenate(out.parts)
        np.testing.assert_array_equal(data[:100], 1)
        np.testing.assert_array_equal(data[100:300], 0)
        np.testing.assert_array_equal(data[300:], 2)
        self.assertEqual(len(data), 400)

    def test_pause_is_excluded_and_tail_preserved(self):
        now = [0.0]
        out = Sink()
        sink = TimelineSink(out, 100, clock=lambda: now[0])
        now[0] = 1
        sink.put(np.ones(100))
        sink.pause()
        now[0] = 11
        sink.put(np.ones(100))
        sink.resume()
        now[0] = 12
        sink.finish()
        self.assertEqual(sum(map(len, out.parts)), 200)
        np.testing.assert_array_equal(out.parts[-1], 0)

    def test_late_callbacks_after_finish_are_ignored(self):
        now = [0.0]
        out = Sink()
        sink = TimelineSink(out, 100, clock=lambda: now[0])
        sink.put(np.ones(100), captured_at=0.0)
        now[0] = 1
        sink.finish()
        sink.put(np.ones(100))
        self.assertEqual(sum(map(len, out.parts)), 100)


class TestSwitching(unittest.TestCase):
    def make(self):
        self.device = ['speakers']
        self.streams = []
        def factory(**kwargs):
            stream = Mock()
            stream.is_active = True
            self.streams.append((kwargs['device_name'], stream))
            return stream
        return SwitchingLoopbackStream(None, 100, sink=Sink(), factory=factory,
                                       resolver=lambda: self.device[0])

    def test_default_changes_and_fixed_override(self):
        capture = self.make()
        capture._step()
        self.device[0] = 'headphones'
        capture._step()
        self.assertEqual([x[0] for x in self.streams], ['speakers', 'headphones'])
        self.streams[0][1].stop.assert_called_once()
        capture.set_device('fixed')
        capture._step()
        self.device[0] = 'other'
        capture._step()
        self.assertEqual([x[0] for x in self.streams], ['speakers', 'headphones', 'fixed'])
        capture.stop()

    def test_failed_reconnect_retries_and_reports_loss(self):
        capture = self.make()
        capture._step()
        capture.resolver = Mock(side_effect=RuntimeError('unplugged'))
        capture._step()
        self.assertIn('unavailable', capture.status.lower())
        capture.resolver = lambda: 'headphones'
        capture._step()
        self.assertEqual(self.streams[-1][0], 'headphones')
        capture.stop()

    def test_inactive_stream_reconnects_same_output(self):
        capture = self.make()
        capture._step()
        self.streams[-1][1].is_active = False
        capture._step()
        self.assertEqual([name for name, _ in self.streams], ['speakers', 'speakers'])
        self.streams[0][1].stop.assert_called_once()
        capture.stop()

    def test_pause_survives_device_switch(self):
        capture = self.make()
        capture._step()
        capture.pause()
        self.device[0] = 'headphones'
        capture._step()
        self.streams[-1][1].pause.assert_called()
        capture.resume()
        self.streams[-1][1].resume.assert_called_once()
        capture.stop()

    def test_ui_requests_do_not_wait_for_driver_start(self):
        entered = threading.Event()
        release = threading.Event()
        class SlowDevice:
            is_active = True
            def start(self):
                entered.set()
                release.wait(2)
            def stop(self): pass
            def pause(self): pass
            def resume(self): pass
        capture = SwitchingLoopbackStream('speakers', 100, sink=Sink(),
                                          factory=lambda **kwargs: SlowDevice())
        worker = threading.Thread(target=capture._step)
        worker.start()
        self.assertTrue(entered.wait(1))
        changed = threading.Event()
        def request():
            capture.set_device('headphones')
            capture.pause()
            capture.resume()
            changed.set()
        requester = threading.Thread(target=request)
        requester.start()
        try:
            self.assertTrue(changed.wait(0.2), 'UI request waited for driver startup')
        finally:
            release.set()
            worker.join(1)
            requester.join(1)
        self.assertFalse(worker.is_alive())
        self.assertIsNone(capture.stream)  # stale initial target was not published

    def test_stop_seals_timeline_during_driver_start(self):
        entered = threading.Event()
        release = threading.Event()
        class SlowDevice:
            is_active = True
            def start(self):
                entered.set()
                release.wait(2)
            def stop(self): pass
        capture = SwitchingLoopbackStream('speakers', 100, sink=Sink(),
                                          factory=lambda **kwargs: SlowDevice())
        worker = threading.Thread(target=capture._step)
        worker.start()
        self.assertTrue(entered.wait(1))
        stopper = threading.Thread(target=capture.stop)
        stopper.start()
        try:
            deadline = time.monotonic() + 0.2
            while not capture.timeline.closed and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertTrue(capture.timeline.closed)
        finally:
            release.set()
            worker.join(1)
            stopper.join(1)
        self.assertFalse(worker.is_alive())
        self.assertIsNone(capture.stream)
