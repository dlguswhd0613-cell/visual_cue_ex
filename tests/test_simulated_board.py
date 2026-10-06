"""Host-demo behavior checks; these do not certify real Arduino timing."""

import unittest

from visualcue.simulated_board import SimulatedBoard


class FakeClock:
    def __init__(self):
        self.ms = 0

    def __call__(self):
        return self.ms / 1000


class SimulatedBoardTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.board = SimulatedBoard(clock=self.clock)
        self.events = []
        self.drain()

    def drain(self):
        for line in self.board.read_lines():
            timestamp, event, value = line.split(",")
            self.events.append((int(timestamp), event, int(value)))

    def send(self, command):
        self.board.write_line(command)
        self.drain()

    def advance(self, milliseconds):
        """Model a responsive host, polling and keeping the link alive."""
        target = self.clock.ms + milliseconds
        while self.clock.ms < target:
            self.clock.ms = min(target, self.clock.ms + 50)
            self.send("PING")

    def matching(self, name):
        return [event for event in self.events if event[1] == name]

    def start(self, count=1, rewarded=True, reward_at=9000):
        self.send(f"CONFIG {count} 1000 2000 {reward_at} 4000 30 0")
        for index in range(1, count + 1):
            self.send(f"TRIAL {index} 33 {int(rewarded)}")
        self.send("START")
        self.advance(3000)
        self.assertEqual(self.matching("TRIAL_START"), [(3000, "TRIAL_START", 1)])

    def finish_cue(self):
        self.advance(1000)
        self.assertEqual(self.matching("CUE_REQUEST"), [(4000, "CUE_REQUEST", 1)])
        self.send("CUE_ON 1")
        self.advance(2000)
        self.send("CUE_OFF 1")

    def test_marker_is_three_pulses_before_first_trial(self):
        self.start()
        self.assertEqual(self.matching("LED_ON"), [
            (500, "LED_ON", 1), (1500, "LED_ON", 2), (2500, "LED_ON", 3),
        ])
        self.assertEqual(self.matching("LED_OFF"), [
            (1000, "LED_OFF", 1), (2000, "LED_OFF", 2), (3000, "LED_OFF", 3),
        ])

    def test_reward_is_at_trial_second_nine_despite_small_display_latency(self):
        self.start()
        self.advance(1010)  # Host confirms the first display flip 10 ms late.
        self.send("CUE_ON 1")
        self.advance(2025)  # The second flip has another modest display delay.
        self.send("CUE_OFF 1")
        self.advance(5964)
        self.assertFalse(self.matching("REWARD_ON"))
        self.advance(1)
        self.assertEqual(self.matching("REWARD_ON"), [(12000, "REWARD_ON", 1)])
        self.assertTrue(self.board.valve_on)
        self.advance(30)
        self.assertFalse(self.board.valve_on)
        self.assertEqual(self.matching("REWARD_OFF"), [(12030, "REWARD_OFF", 1)])
        self.assertFalse(self.matching("SESSION_END"))
        self.advance(100)
        self.assertEqual(self.matching("LICK"), [(12130, "LICK", 1)])
        self.assertFalse(self.matching("SESSION_END"))
        self.advance(3870)
        self.assertEqual(self.matching("TRIAL_END"), [(16000, "TRIAL_END", 1)])
        self.assertEqual(self.matching("SESSION_END"), [(16000, "SESSION_END", 1)])

    def test_missing_display_off_aborts_without_reward(self):
        self.start()
        self.advance(1000)
        self.send("CUE_ON 1")
        self.advance(3000)
        self.assertEqual(self.matching("SESSION_ABORTED"), [(7000, "SESSION_ABORTED", 4)])
        self.advance(9000)
        self.assertFalse(self.matching("REWARD_ON"))

    def test_absolute_reward_deadline_rejects_still_visible_cue(self):
        self.start(reward_at=3010)
        self.advance(1050)  # A valid 50 ms onset latency reaches the tight reward margin.
        self.send("CUE_ON 1")
        self.advance(1960)
        self.assertEqual(self.matching("SESSION_ABORTED"), [(6010, "SESSION_ABORTED", 7)])
        self.assertFalse(self.matching("REWARD_ON"))

    def test_cue_on_ack_101_ms_late_aborts_without_reward(self):
        self.start()
        self.advance(1101)
        self.send("CUE_ON 1")
        self.assertEqual(self.matching("SESSION_ABORTED"), [(4100, "SESSION_ABORTED", 3)])
        self.advance(10000)
        self.assertFalse(self.matching("REWARD_ON"))

    def test_stop_during_valve_pulse_cancels_future_lick_and_trial(self):
        self.start(count=2)
        self.finish_cue()
        self.advance(6000)
        self.assertTrue(self.board.valve_on)
        self.send("STOP")
        self.assertFalse(self.board.valve_on)
        self.advance(1000)
        self.assertFalse(self.matching("LICK"))
        self.assertEqual(len(self.matching("TRIAL_START")), 1)
        self.send("START")
        self.assertEqual(self.matching("ERROR")[-1][2], 4)

    def test_wrong_trial_ack_aborts_instead_of_opening_reward(self):
        self.start()
        self.advance(1000)
        self.send("CUE_ON 2")
        self.assertEqual(self.matching("ERROR")[-1][2], 6)
        self.assertEqual(self.matching("SESSION_ABORTED")[-1][2], 5)
        self.advance(10000)
        self.assertFalse(self.matching("REWARD_ON"))

    def test_missing_host_heartbeat_aborts(self):
        self.start()
        self.clock.ms += 2000
        self.drain()
        self.assertEqual(self.matching("SESSION_ABORTED"), [(5000, "SESSION_ABORTED", 2)])
        self.assertFalse(self.board.valve_on)

    def test_33_second_interval_starts_after_13_second_trial(self):
        self.start(count=2)
        self.finish_cue()
        self.advance(43000)
        self.assertEqual(self.matching("TRIAL_END"), [(16000, "TRIAL_END", 1)])
        self.assertEqual(self.matching("TRIAL_START")[-1], (49000, "TRIAL_START", 2))
        self.assertEqual(self.matching("TRIAL_START")[1][0]
                         - self.matching("TRIAL_START")[0][0], 46000)

    def test_absent_lick_does_not_delay_trial_or_session_end(self):
        self.board = SimulatedBoard(clock=self.clock, simulate_licks=False)
        self.start(count=2)
        self.finish_cue()
        self.advance(43000)
        self.assertFalse(self.matching("LICK"))
        self.assertEqual(self.matching("TRIAL_START")[-1], (49000, "TRIAL_START", 2))
        self.advance(1000)
        self.send("CUE_ON 2")
        self.advance(2000)
        self.send("CUE_OFF 2")
        self.advance(10000)
        self.assertEqual(self.matching("SESSION_END"), [(62000, "SESSION_END", 2)])

    def test_nonreward_trial_still_keeps_full_observation_period(self):
        self.start(rewarded=False)
        self.finish_cue()
        self.advance(6000)
        self.assertEqual(self.matching("NO_REWARD"), [(12000, "NO_REWARD", 1)])
        self.assertFalse(self.matching("SESSION_END"))
        self.advance(4000)
        self.assertEqual(self.matching("SESSION_END"), [(16000, "SESSION_END", 1)])
        self.assertFalse(self.matching("REWARD_ON"))
        self.assertFalse(self.matching("WAIT_LICK"))

    def test_reward_pulse_cannot_outlast_the_observation_period(self):
        self.send("CONFIG 1 1000 2000 9000 20 30 0")
        self.assertEqual(self.matching("ERROR")[-1][2], 2)
        self.assertFalse(self.matching("CONFIG_OK"))

    def test_incomplete_or_out_of_order_schedule_cannot_start(self):
        self.send("CONFIG 2 1000 2000 9000 4000 30 0")
        self.send("TRIAL 2 33 1")
        self.assertEqual(self.matching("ERROR")[-1][2], 4)
        self.send("TRIAL 1 33 1")
        self.send("START")
        self.assertEqual(self.matching("ERROR")[-1][2], 4)
        self.assertFalse(self.matching("SESSION_START"))

    def test_close_is_idempotent_and_stops_time_progress(self):
        self.start()
        self.board.close()
        self.board.close()
        self.drain()
        before = list(self.events)
        self.clock.ms += 100000
        self.drain()
        self.assertEqual(self.events, before)
        self.assertFalse(self.board.valve_on)
        with self.assertRaises(RuntimeError):
            self.board.write_line("START")


if __name__ == "__main__":
    unittest.main()
