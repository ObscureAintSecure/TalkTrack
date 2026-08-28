# tests/test_system_monitor_start.py
"""Regression cover for MainWindow._start_system_monitor.

The Test Mic button crashed with `unexpected keyword argument 'enable_buffer'`
because ProcessAudioCapture dropped that parameter in #32 and this call site
was never updated (issue #79). Nothing exercised the call, so the suite stayed
green while the button was dead.

MainWindow is never constructed here — the method is called against a stub
self, which keeps the test free of Qt widgets while still exercising the real
call. ProcessAudioCapture is patched with autospec so a signature mismatch
fails loudly instead of being absorbed by a permissive mock.
"""
import unittest
from unittest.mock import MagicMock, patch


def _stub_self(mode="per_app", pids=(1234,)):
    stub = MagicMock()
    stub.source_selector.get_capture_mode.return_value = mode
    stub.source_selector.get_selected_app_pids.return_value = list(pids)
    stub.config.get.return_value = 16000
    stub.system_monitor = None
    return stub


class TestStartSystemMonitor(unittest.TestCase):
    def test_per_app_monitor_constructed_with_valid_arguments(self):
        from app.main_window import MainWindow
        stub = _stub_self()
        with patch("app.main_window.ProcessAudioCapture", autospec=True) as pac:
            pac.return_value.start.return_value = {
                "total": 1, "active": 1, "failures": {},
            }
            MainWindow._start_system_monitor(stub)

        pac.assert_called_once()
        kwargs = pac.call_args.kwargs
        self.assertEqual(kwargs["pids"], [1234])
        self.assertEqual(kwargs["sample_rate"], 16000)
        self.assertIs(stub.system_monitor, pac.return_value)

    def test_no_selected_pids_starts_nothing(self):
        from app.main_window import MainWindow
        stub = _stub_self(pids=())
        with patch("app.main_window.ProcessAudioCapture", autospec=True) as pac:
            MainWindow._start_system_monitor(stub)
        pac.assert_not_called()

    def test_failed_activation_leaves_no_monitor(self):
        from app.main_window import MainWindow
        stub = _stub_self()
        with patch("app.main_window.ProcessAudioCapture", autospec=True) as pac:
            pac.return_value.start.return_value = {
                "total": 2, "active": 0, "failures": {1234: "E_ILLEGAL_METHOD_CALL"},
            }
            MainWindow._start_system_monitor(stub)
        self.assertIsNone(stub.system_monitor)
        stub.status_label.setText.assert_called_once()


if __name__ == "__main__":
    unittest.main()
