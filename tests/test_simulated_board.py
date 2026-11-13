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

    def start(self, count=1, rewarded=True, reward_at=9000, triggers=False):
        self.send(f"CONFIG {count} 1000 2000 {reward_at} 4000 30 0")
        if triggers:
            self.send("TRIGGERS 100 100 20")
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

    def test_photometry_pulses_precede_events_and_repeat_on_next_trial(self):
        self.start(count=2, triggers=True)
        self.finish_cue()
        self.advance(5900)
        self.assertTrue(self.board.reward_trigger_on)
        self.assertTrue(self.board.trigger_on)
        self.assertFalse(self.board.valve_on)
        self.advance(20)
        self.assertFalse(self.board.reward_trigger_on)
        self.assertFalse(self.board.trigger_on)
        self.advance(80)
        self.assertTrue(self.board.valve_on)
        self.assertEqual(self.matching("CUE_TRIGGER_ON"), [(3900, "CUE_TRIGGER_ON", 1)])
        self.assertEqual(self.matching("CUE_TRIGGER_OFF"), [(3920, "CUE_TRIGGER_OFF", 1)])
        self.assertEqual(self.matching("REWARD_TRIGGER_ON"), [(11900, "REWARD_TRIGGER_ON", 1)])
        self.assertEqual(self.matching("REWARD_TRIGGER_OFF"), [(11920, "REWARD_TRIGGER_OFF", 1)])
        self.advance(34030)
        self.assertEqual(self.matching("CUE_TRIGGER_ON")[-1], (46030, "CUE_TRIGGER_ON", 2))

    def test_stop_clears_active_trigger_and_cancels_future_reward_trigger(self):
        self.start(triggers=True)
        self.advance(900)
        self.assertTrue(self.board.cue_trigger_on)
        self.assertTrue(self.board.trigger_on)
        self.send("STOP")
        self.assertFalse(self.board.cue_trigger_on)
        self.assertFalse(self.board.reward_trigger_on)
        self.assertFalse(self.board.trigger_on)
        self.advance(20000)
        self.assertFalse(self.matching("REWARD_TRIGGER_ON"))
        self.assertFalse(self.matching("REWARD_ON"))

    def test_long_pulse_is_cleared_at_trial_end(self):
        self.send("CONFIG 2 1000 2000 6000 30 30 0")
        self.send("TRIGGERS 100 100 1000")
        self.send("TRIAL 1 0 1")
        self.send("TRIAL 2 0 1")
        self.send("START")
        self.advance(3000)
        self.finish_cue()
        self.advance(3000)
        self.assertTrue(self.board.reward_trigger_on)
        self.assertTrue(self.board.trigger_on)
        self.board.inject_lick()  # Lick during the valve pulse must not truncate it.
        self.advance(30)
        self.assertFalse(self.board.reward_trigger_on)
        self.assertFalse(self.board.trigger_on)
        self.assertEqual(len(self.matching("TRIAL_START")), 2)

    def test_no_reward_trigger_for_omitted_reward(self):
        self.start(rewarded=False, triggers=True)
        self.finish_cue()
        self.advance(10000)
        self.assertTrue(self.matching("CUE_TRIGGER_ON"))
        self.assertFalse(self.matching("REWARD_TRIGGER_ON"))

    def test_trigger_config_requires_valid_session_and_resets_with_config(self):
        self.send("TRIGGERS 100 100 20")
        self.assertEqual(self.matching("ERROR")[-1][2], 4)
        self.send("CONFIG 1 1000 2000 9000 4000 30 0")
        for args in ("1001 100 20", "100 6001 20", "100 100 0", "100 100 1001"):
            self.send("TRIGGERS " + args)
            self.assertEqual(self.matching("ERROR")[-1][2], 2)
        self.send("TRIGGERS 100 100 20")
        self.assertEqual(self.matching("TRIGGERS_OK")[-1][2], 2)
        self.start()  # New CONFIG clears the earlier trigger settings.
        self.finish_cue()
        self.advance(10000)
        self.assertFalse(self.matching("CUE_TRIGGER_ON"))
        self.assertFalse(self.matching("REWARD_TRIGGER_ON"))

    def test_shared_trigger_rejects_overlap_and_zero_low_gap(self):
        self.send("CONFIG 1 1000 10 2000 4000 30 0")
        for width in (20, 10):
            self.send(f"TRIGGERS 0 990 {width}")
            self.assertEqual(self.matching("ERROR")[-1][2], 2)
        self.send("TRIGGERS 0 990 9")
        self.assertEqual(self.matching("TRIGGERS_OK")[-1][2], 2)

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
        self.assertEqual(self.matching("TRIAL_END"), [(12130, "TRIAL_END", 1)])
        self.assertEqual(self.matching("SESSION_END"), [(12130, "SESSION_END", 1)])

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

    def test_iti_starts_at_post_reward_lick(self):
        self.start(count=2)
        self.finish_cue()
        self.advance(39130)
        self.assertEqual(self.matching("TRIAL_END"), [(12130, "TRIAL_END", 1)])
        self.assertEqual(self.matching("ITI_START")[-1], (12130, "ITI_START", 2))
        self.assertEqual(self.matching("TRIAL_START")[-1], (45130, "TRIAL_START", 2))

    def test_no_lick_waits_then_starts_iti_at_lick(self):
        self.board = SimulatedBoard(clock=self.clock, simulate_licks=False)
        self.start(count=2)
        self.board.inject_lick()  # Pre-reward lick is ignored for trial completion.
        self.finish_cue()
        self.advance(43000)
        self.assertFalse(self.matching("TRIAL_END"))
        self.assertEqual(len(self.matching("TRIAL_START")), 1)
        self.assertFalse(self.board.valve_on)
        self.board.inject_lick()
        self.drain()
        self.assertEqual(self.matching("TRIAL_END"), [(49000, "TRIAL_END", 1)])
        self.assertEqual(self.matching("ITI_START")[-1], (49000, "ITI_START", 2))
        self.advance(32999)
        self.assertEqual(len(self.matching("TRIAL_START")), 1)
        self.advance(1)
        self.assertEqual(self.matching("TRIAL_START")[-1], (82000, "TRIAL_START", 2))
        self.advance(1000)
        self.send("CUE_ON 2")
        self.advance(2000)
        self.send("CUE_OFF 2")
        self.advance(10000)
        self.assertFalse(self.matching("SESSION_END"))
        self.board.inject_lick()
        self.drain()
        self.assertEqual(self.matching("SESSION_END"), [(95000, "SESSION_END", 2)])

    def test_lick_during_valve_waits_until_full_pulse_finishes(self):
        self.board = SimulatedBoard(clock=self.clock, simulate_licks=False)
        self.start()
        self.finish_cue()
        self.advance(6005)
        self.board.inject_lick()
        self.drain()
        self.assertTrue(self.board.valve_on)
        self.assertFalse(self.matching("TRIAL_END"))
        self.advance(24)
        self.assertTrue(self.board.valve_on)
        self.advance(1)
        self.assertFalse(self.board.valve_on)
        self.assertEqual(self.matching("SESSION_END"), [(12030, "SESSION_END", 1)])

    def test_wait_for_lick_stops_on_watchdog_or_operator(self):
        for watchdog in (False, True):
            with self.subTest(watchdog=watchdog):
                self.setUp()
                self.board = SimulatedBoard(clock=self.clock, simulate_licks=False)
                self.start()
                self.finish_cue()
                self.advance(10000)
                self.assertTrue(self.matching("WAIT_LICK"))
                if watchdog:
                    self.clock.ms += 2000
                    self.drain()
                else:
                    self.send("STOP")
                self.assertEqual(self.matching("SESSION_ABORTED")[-1][2], 2 if watchdog else 1)
                self.assertFalse(self.board.valve_on)
                self.assertFalse(self.board.trigger_on)
                self.assertFalse(self.matching("TRIAL_END"))

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

    def test_one_hour_includes_initial_iti_and_ends_without_trials(self):
        self.send("SESSION_LIMIT_CAPS")
        self.assertEqual(self.matching("SESSION_LIMIT_CAPS")[-1][2], 3600)
        self.send("CONFIG 100 1000 2000 6000 4000 30 4000")
        for index in range(1, 101):
            self.send(f"TRIAL {index} 10 1")
        self.send("START")
        self.advance(3_599_999)
        self.assertFalse(self.matching("SESSION_END"))
        self.advance(1)
        self.assertEqual(self.matching("SESSION_END"), [(3_600_000, "SESSION_END", 0)])
        self.assertEqual(self.matching("SESSION_TIME_LIMIT"), [(3_600_000, "SESSION_TIME_LIMIT", 0)])
        self.assertFalse(self.matching("TRIAL_START"))
        self.assertFalse(self.board.valve_on)

    def test_one_hour_stops_waiting_and_counts_completed_trials_only(self):
        self.board = SimulatedBoard(clock=self.clock, simulate_licks=False)
        self.start(count=2)
        self.finish_cue()
        self.advance(6030)
        self.board.inject_lick()
        self.drain()
        self.advance(33000)
        self.advance(1000)
        self.send("CUE_ON 2")
        self.advance(2000)
        self.send("CUE_OFF 2")
        self.advance(3_600_000 - self.clock.ms)
        self.assertEqual(self.matching("SESSION_END"), [(3_600_000, "SESSION_END", 1)])
        self.assertEqual(len(self.matching("TRIAL_END")), 1)
        self.assertFalse(self.board.valve_on)
        self.assertFalse(self.board.trigger_on)
        self.send("CUE_OFF 2")  # In-flight ACK after timeout must not cause ERROR.
        self.assertFalse(self.matching("ERROR"))

    def test_limit_during_valve_pulse_closes_it_immediately(self):
        self.board = SimulatedBoard(clock=self.clock, simulate_licks=False)
        self.start()
        self.finish_cue()
        self.advance(6000)
        self.assertTrue(self.board.valve_on)
        self.board._session_deadline = self.clock.ms + 10
        self.advance(9)
        self.assertTrue(self.board.valve_on)
        self.advance(1)
        self.assertFalse(self.board.valve_on)
        self.assertEqual(self.matching("SESSION_END"), [(12010, "SESSION_END", 0)])
        self.assertFalse(self.matching("TRIAL_END"))

    def test_earlier_trial_completion_cancels_time_limit(self):
        self.start()
        self.finish_cue()
        self.advance(6130)
        self.advance(3_600_000 - self.clock.ms)
        self.assertEqual(self.matching("SESSION_END"), [(12130, "SESSION_END", 1)])
        self.assertFalse(self.matching("SESSION_TIME_LIMIT"))


if __name__ == "__main__":
    unittest.main()
