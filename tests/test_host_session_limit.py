"""Host deadline and existing STOP protocol, without new Arduino commands."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from visualcue.runner import Experiment


class HostSessionLimitTests(unittest.TestCase):
    def setUp(self):
        self.operations = []
        self.app = Experiment.__new__(Experiment)
        self.app.active = self.app.started = True
        self.app.done = False
        self.app.session_started_at = 100.0
        self.app.time_limit_stop_at = None
        self.app.completed_trials = 41
        self.app.cue_on_ns = 123
        self.app.board = SimpleNamespace(write_line=lambda line: self.operations.append(line))
        self.app.show_gray = Mock(side_effect=lambda: self.operations.append("display flip"))
        self.app.recording = SimpleNamespace(
            event=Mock(side_effect=lambda *args: self.operations.append("disk write")),
            metadata={"status": "running"}, save_metadata=Mock())
        self.clock = patch("visualcue.runner.time.monotonic", return_value=3700.0).start()
        self.output = patch("builtins.print").start()
        self.addCleanup(patch.stopall)

    def test_exact_hour_stops_outputs_before_display_and_waits_for_ack(self):
        self.clock.return_value = 3699.999
        self.app.check_session_limit()
        self.assertEqual(self.operations, [])
        self.clock.return_value = 3700.0
        self.app.check_session_limit()
        self.assertEqual(self.operations[0], "STOP")
        self.assertFalse(self.app.active)
        self.assertFalse(self.app.done)
        self.assertIsNone(self.app.cue_on_ns)
        self.app.recording.event.assert_any_call("SESSION_TIME_LIMIT", 3600)
        self.assertEqual(self.app.recording.metadata["status"], "stopping")
        # A cue request already in USB transit must not produce a cue ACK.
        self.app.handle_event("CUE_REQUEST", 42)
        self.assertNotIn("CUE_ON 42", self.operations)
        self.app.handle_event("SESSION_ABORTED", 1)
        self.assertTrue(self.app.done)
        self.assertEqual(self.app.recording.metadata,
                         {"status": "completed", "end_reason": "time_limit", "completed_trials": 41})
        self.app.recording.event.assert_any_call("SESSION_END", 41)
        self.assertTrue(all(call.kwargs.get("flush") for call in self.output.call_args_list))

    def test_completed_trial_in_transit_is_counted_before_stop_ack(self):
        self.app.check_session_limit()
        self.app.handle_event("TRIAL_END", 42)
        self.app.handle_event("SESSION_ABORTED", 1)
        self.assertEqual(self.app.recording.metadata["completed_trials"], 42)
        self.assertEqual(self.operations.count("STOP"), 1)

    def test_missing_ack_is_failure_instead_of_false_completion(self):
        self.app.check_session_limit()
        self.clock.return_value += 2.0
        with self.assertRaisesRegex(TimeoutError, "STOP acknowledgment"):
            self.app.check_session_limit()
        self.assertFalse(self.app.done)
        self.assertNotEqual(self.app.recording.metadata["status"], "completed")

    def test_other_abort_reason_is_not_reported_as_completion(self):
        self.app.check_session_limit()
        with self.assertRaisesRegex(RuntimeError, "before acknowledging"):
            self.app.handle_event("SESSION_ABORTED", 2)
        self.assertFalse(self.app.done)

    def test_normal_completion_before_hour_does_not_send_stop(self):
        self.app.handle_event("SESSION_END", 100)
        self.app.check_session_limit()
        self.assertNotIn("STOP", self.operations)
        self.assertEqual(self.app.recording.metadata,
                         {"status": "completed", "end_reason": "trial_count", "completed_trials": 100})

    def test_normal_end_in_transit_still_requires_stop_ack(self):
        self.app.check_session_limit()
        self.app.handle_event("TRIAL_END", 100)
        self.app.handle_event("SESSION_END", 100)
        self.assertFalse(self.app.done)
        self.app.handle_event("SESSION_ABORTED", 1)
        self.assertEqual(self.app.recording.metadata["completed_trials"], 100)
        self.assertTrue(self.app.done)

    def test_no_timer_before_start_and_operator_abort_stays_aborted(self):
        self.app.session_started_at = None
        self.app.check_session_limit()
        self.assertEqual(self.operations, [])
        self.app.handle_event("SESSION_ABORTED", 1)
        self.assertEqual(self.app.recording.metadata["status"], "aborted")


if __name__ == "__main__":
    unittest.main()
