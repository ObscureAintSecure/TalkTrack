# tests/test_live_transcriber.py
"""Transcribing while recording (#139): track reading, incremental batching, worker.

OpenVINO is never loaded: openvino_whisper's speech_regions and decode_batch
are patched where live_transcriber looks them up. The track tests use real
WAV files written the way ChunkWriter writes them.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf

from app.transcription import live_transcriber as lt
from app.transcription.openvino_whisper import BatchResult

SR = lt.SAMPLE_RATE


def secs(x):
    return int(x * SR)


class TestTrackFollower(unittest.TestCase):
    def test_reads_only_what_was_flushed_since_last_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mic_audio.wav"
            writer = sf.SoundFile(str(path), mode="w", samplerate=SR, channels=1, subtype="PCM_16")
            follower = lt.TrackFollower(path)
            writer.write(np.full(1600, 0.25, dtype=np.float32))
            writer.flush()
            self.assertEqual(follower.available(), 1600)
            first = follower.read(1000)
            self.assertEqual(len(first), 1000)
            self.assertEqual(follower.available(), 600)
            writer.write(np.full(400, -0.5, dtype=np.float32))
            writer.flush()
            rest = follower.read(follower.available())
            writer.close()
        np.testing.assert_allclose(rest[-400:], -0.5, atol=1e-4)
        self.assertEqual(len(rest), 1000)

    def test_missing_file_has_nothing_available(self):
        self.assertEqual(lt.TrackFollower(Path("Z:/nope/track.wav")).available(), 0)


class FakeFollower:
    def __init__(self, data):
        self.data = np.asarray(data, dtype=np.float32)
        self.position = 0

    def available(self):
        return len(self.data) - self.position

    def read(self, frames):
        out = self.data[self.position:self.position + frames]
        self.position += len(out)
        return out


class TestLiveMixer(unittest.TestCase):
    def test_mixes_only_as_far_as_every_track_has_data(self):
        mic, system = FakeFollower([0.2] * 10), FakeFollower([0.4] * 6)
        mixed = lt.LiveMixer([mic], system).read()
        np.testing.assert_allclose(mixed, [0.3] * 6)
        self.assertEqual(mic.position, 6)   # the rest waits for the system track

    def test_two_microphones_are_summed_then_mixed_with_system(self):
        mixed = lt.LiveMixer([FakeFollower([0.2] * 4), FakeFollower([0.2] * 4)],
                             FakeFollower([0.0] * 4)).read()
        np.testing.assert_allclose(mixed, [0.2] * 4)

    def test_single_track_is_passed_through(self):
        np.testing.assert_allclose(lt.LiveMixer([FakeFollower([0.7] * 3)]).read(), [0.7] * 3)
        np.testing.assert_allclose(lt.LiveMixer([], FakeFollower([0.1] * 2)).read(), [0.1] * 2)

    def test_a_track_without_data_holds_everything_back(self):
        self.assertEqual(len(lt.LiveMixer([FakeFollower([0.2] * 5)], FakeFollower([])).read()), 0)


class SessionHarness:
    """LiveSession with VAD and decoding faked: regions are given, text names the batch."""

    def __init__(self, regions, normalize=False, language="pt"):
        self.regions = regions        # absolute (start, end) in seconds
        self.decoded = []             # (batch regions absolute s, audio peak, token)
        self.session = lt.LiveSession(MagicMock(), language, normalize=normalize,
                                      settle_seconds=3, min_batch_seconds=20,
                                      max_batch_seconds=60)
        self._patches = [
            patch.object(lt.ovw, "speech_regions", side_effect=self._speech_regions),
            patch.object(lt.ovw, "decode_batch", side_effect=self._decode_batch),
        ]

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()

    def _offset(self):
        return self.session.state.done_until / SR

    def _speech_regions(self, audio, max_speech_seconds):
        offset, length = self._offset(), len(audio) / SR
        out = []
        for s, e in self.regions:
            s, e = s - offset, e - offset
            if e <= 0 or s >= length:
                continue
            out.append((secs(max(s, 0)), secs(min(e, length))))
        return out

    def _decode_batch(self, pipeline, audio, batch, token):
        offset = self._offset()
        absolute = [(round(s / SR + offset, 2), round(e / SR + offset, 2)) for s, e in batch]
        self.decoded.append((absolute, float(np.abs(audio).max()) if len(audio) else 0.0, token))
        start, end = batch[0][0] / SR, batch[-1][1] / SR
        return BatchResult(segments=[(start, end, f"batch {len(self.decoded)}")], language="pt")

    def feed_seconds(self, seconds, level=0.1):
        self.session.feed(np.full(secs(seconds), level, dtype=np.float32))


class TestLiveSessionStep(unittest.TestCase):
    def test_too_little_audio_waits(self):
        with SessionHarness([(0, 10)]) as h:
            h.feed_seconds(15)
            self.assertEqual(h.session.step(), [])
        self.assertEqual(h.decoded, [])

    def test_speech_near_the_write_head_waits_to_settle(self):
        # 25 s of speech ends at 40 s; at 42 s it is within the 3 s settle window.
        with SessionHarness([(15, 40)]) as h:
            h.feed_seconds(42)
            self.assertEqual(h.session.step(), [])
            h.feed_seconds(2)
            new = h.session.step()
        self.assertEqual(len(new), 1)
        self.assertEqual(h.decoded[0][0], [(15.0, 40.0)])
        self.assertEqual(new[0][:2], (15.0, 40.0))         # in recording time, after the dropped silence
        self.assertEqual(h.session.state.done_until, secs(40))

    def test_short_last_batch_waits_for_more_speech(self):
        with SessionHarness([(0, 55), (57, 67)]) as h:
            h.feed_seconds(80)
            h.session.step()
        self.assertEqual([(d[0], d[2]) for d in h.decoded], [([(0.0, 55.0)], "<|pt|>")])
        self.assertEqual(h.session.state.done_until, secs(55))

    def test_long_silence_is_skipped_without_decoding(self):
        with SessionHarness([]) as h:
            h.feed_seconds(120)
            h.session.step()
        self.assertEqual(h.decoded, [])
        self.assertEqual(h.session.state.done_until, secs(117))
        self.assertEqual(len(h.session._audio), secs(3))

    def test_segments_accumulate_across_steps_in_recording_time(self):
        with SessionHarness([(0, 30), (40, 70)]) as h:
            h.feed_seconds(35)
            h.session.step()
            h.feed_seconds(40)
            h.session.step()
        times = [s[:2] for s in h.session.state.segments]
        self.assertEqual(times, [(0.0, 30.0), (40.0, 70.0)])

    def test_level_is_normalized_to_the_running_peak_when_asked(self):
        with SessionHarness([(0, 30)], normalize=True) as h:
            h.feed_seconds(35, level=0.2)
            h.session.step()
        self.assertAlmostEqual(h.decoded[0][1], lt.TARGET_PEAK, places=5)

    def test_level_untouched_for_a_lone_track(self):
        with SessionHarness([(0, 30)], normalize=False) as h:
            h.feed_seconds(35, level=0.2)
            h.session.step()
        self.assertAlmostEqual(h.decoded[0][1], 0.2, places=5)

    def test_detected_language_is_pinned(self):
        with SessionHarness([(0, 40), (45, 85)], language=None) as h:   # two batches
            h.feed_seconds(90)
            h.session.step()
        self.assertEqual([d[2] for d in h.decoded], [None, "<|pt|>"])
        self.assertEqual(h.session.state.language, "pt")

    def test_stop_request_keeps_the_rest_for_later(self):
        with SessionHarness([(0, 40), (45, 85)]) as h:   # two batches
            h.feed_seconds(90)
            calls = iter([False, True])
            h.session.step(should_stop=lambda: next(calls))
        self.assertEqual(len(h.decoded), 1)
        self.assertEqual(h.session.state.done_until, secs(45))


class TestLiveSessionFinish(unittest.TestCase):
    def test_everything_left_is_transcribed_as_is(self):
        with SessionHarness([(0, 30), (40, 50), (52, 54)], normalize=True) as h:
            h.feed_seconds(45, level=0.5)
            h.session.step()                       # 0-30 live
            tail = np.full(secs(25), 0.1, dtype=np.float32)   # 30 s .. 55 s, from the final file
            h.session.finish(tail)
        self.assertEqual([d[0] for d in h.decoded], [[(0.0, 30.0)], [(40.0, 50.0), (52.0, 54.0)]])
        self.assertAlmostEqual(h.decoded[1][1], 0.1, places=5)   # final file: no rescaling
        self.assertEqual([s[:2] for s in h.session.state.segments], [(0.0, 30.0), (40.0, 54.0)])
        self.assertEqual(h.session.state.done_until, secs(55))

    def test_empty_tail(self):
        with SessionHarness([]) as h:
            self.assertEqual(h.session.finish(np.zeros(0, dtype=np.float32)), [])


class TestLiveWorker(unittest.TestCase):
    def _worker(self):
        return lt.LiveTranscriptionWorker(["mic.wav"], "system.wav", "large-v3-turbo", "pt")

    def test_finish_refused_once_failed_or_cancelled(self):
        worker = self._worker()
        worker.failed = "DEVICE_LOST"
        self.assertFalse(worker.finish("combined.wav"))
        other = self._worker()
        other.cancel()
        self.assertFalse(other.finish("combined.wav"))

    def test_finish_accepted_stops_reading(self):
        worker = self._worker()
        self.assertTrue(worker.finish("combined.wav"))
        self.assertFalse(worker._reading)

    def test_failure_before_finish_just_marks_it_failed(self):
        worker = self._worker()
        fallback = MagicMock()
        worker.fallback.connect(fallback)
        with patch.object(lt.ovw, "get_pipeline", side_effect=RuntimeError("no GPU")):
            with self.assertLogs(lt.logger, "WARNING"):
                self.assertIsNone(worker._follow_recording())
        self.assertEqual(worker.failed, "no GPU")
        self.assertFalse(worker.usable)
        fallback.assert_not_called()

    def test_failure_after_finish_was_accepted_asks_for_fallback(self):
        worker = self._worker()
        self.assertTrue(worker.finish("combined.wav"))
        emitted = []
        worker.fallback.connect(emitted.append)
        with patch.object(lt.ovw, "get_pipeline", side_effect=RuntimeError("DEVICE_LOST")):
            with self.assertLogs(lt.logger, "WARNING"):
                worker._follow_recording()
        self.assertEqual(emitted, ["DEVICE_LOST"])

    def test_cancelled_run_emits_cancelled(self):
        worker = self._worker()
        cancelled = MagicMock()
        worker.cancelled.connect(cancelled)
        worker.cancel()
        with patch.object(worker, "_follow_recording", return_value=MagicMock()):
            worker.run()
        cancelled.assert_called_once()

    def test_finish_emits_transcript_in_recording_time(self):
        worker = self._worker()
        worker.finish("combined.wav")
        session = lt.LiveSession(MagicMock(), "pt")
        session.state.segments = [(1.0, 2.0, "olá")]
        session.state.done_until = secs(2)
        results = []
        worker.finished.connect(results.append)
        audio = np.zeros(secs(5), dtype=np.float32)
        with patch("faster_whisper.decode_audio", return_value=audio, create=True), \
                patch.object(session, "finish") as finish:
            worker._finish(session)
        finish.assert_called_once()
        self.assertEqual(len(finish.call_args.args[0]), secs(3))   # only the unread tail
        result = results[0]
        self.assertEqual([(s.start, s.end, s.text) for s in result.segments], [(1.0, 2.0, "olá")])
        self.assertEqual(result.language, "pt")
        self.assertAlmostEqual(result.duration, 5.0)

    def test_finish_failure_asks_for_fallback(self):
        worker = self._worker()
        worker.finish("combined.wav")
        emitted = []
        worker.fallback.connect(emitted.append)
        with patch("faster_whisper.decode_audio", side_effect=OSError("gone"), create=True):
            with self.assertLogs(lt.logger, "WARNING"):
                worker._finish(lt.LiveSession(MagicMock(), "pt"))
        self.assertEqual(emitted, ["gone"])


if __name__ == "__main__":
    unittest.main()
