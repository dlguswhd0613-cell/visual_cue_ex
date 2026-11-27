import contextlib
import csv
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from visualcue.habituation import Habituation, main, make_schedule
from visualcue.recording import SessionLog
from visualcue.simulated_board import SimulatedBoard


class Clock:
    def __init__(self):
        self.now = 0.

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class HabituationTests(unittest.TestCase):
    def test_manual_start_and_lick_gate_including_final_reward(self):
        clock = Clock()
        board = SimulatedBoard(clock, simulate_licks=False)
        rows = [{"Trial": 1, "ITI_Duration_S": 2, "Rewarded": 1},
                {"Trial": 2, "ITI_Duration_S": 3, "Rewarded": 1}]
        commands = []
        write = board.write_line

        def record(command):
            commands.append(command)
            write(command)

        def tick(app, seconds):
            for _ in range(round(seconds / .002)):
                clock.sleep(.002)
                app.poll()

        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()), \
                patch.object(board, "write_line", side_effect=record), \
                patch("visualcue.habituation.time.sleep", clock.sleep):
            log = SessionLog(Path(directory), "NPY195_2", {}, rows, None, True)
            try:
                app = Habituation(board, log, rows, 30, clock)
                app.prepare()
                tick(app, 3)
                self.assertNotIn("START", commands)
                self.assertFalse(board.valve_on)
                app.start()
                app.start()
                self.assertEqual(commands.count("START"), 1)
                tick(app, 4.5)
                board.inject_lick()  # During the first reward's pre-water interval.
                tick(app, .6)
                self.assertTrue(board._state == "wait_lick")
                tick(app, 10)
                self.assertEqual(app.completed_rewards, 0)
                self.assertFalse(board.valve_on)
                board.inject_lick()
                app.poll()
                self.assertEqual(app.completed_rewards, 1)
                tick(app, 2.9)
                self.assertFalse(board.valve_on)
                tick(app, .2)
                self.assertEqual(board._state, "wait_lick")
                self.assertFalse(app.done)
                tick(app, 10)
                self.assertFalse(app.done)
                board.inject_lick()
                app.poll()
                self.assertTrue(app.done)
                self.assertEqual(log.metadata["status"], "completed")
                self.assertEqual(log.metadata["completed_rewards"], 2)
                self.assertFalse(board.valve_on or board.trigger_on)
            finally:
                log.close()
            with (log.path / "events.csv").open() as stream:
                events = list(csv.DictReader(stream))
            rewards = [e for e in events if e["Event"] == "REWARD_ON"]
            self.assertEqual(len(rewards), 2)
            iti = [e for e in events if e["Event"] == "ITI_START"]
            for reward, start, duration in zip(rewards, iti, (2, 3)):
                self.assertAlmostEqual((int(reward["Arduino_ms"]) - int(start["Arduino_ms"])) / 1000,
                                       duration, delta=.02)
            self.assertFalse(any(e["Event"].endswith("TRIGGER_ON") for e in events))

    def test_stop_and_watchdog_while_waiting_for_lick(self):
        for watchdog in (False, True):
            with self.subTest(watchdog=watchdog), tempfile.TemporaryDirectory() as directory, \
                    contextlib.redirect_stdout(io.StringIO()):
                clock = Clock()
                board = SimulatedBoard(clock, simulate_licks=False)
                rows = [{"Trial": 1, "ITI_Duration_S": 1, "Rewarded": 1}]
                log = SessionLog(Path(directory), "test", {}, rows, None, True)
                try:
                    app = Habituation(board, log, rows, 30, clock)
                    with patch("visualcue.habituation.time.sleep", clock.sleep):
                        app.prepare()
                    app.start()
                    for _ in range(2200):
                        clock.sleep(.002)
                        app.poll()
                    self.assertEqual(board._state, "wait_lick")
                    if watchdog:
                        clock.sleep(3)
                        replies = board.read_lines()
                        self.assertTrue(any(",SESSION_ABORTED,2" in r for r in replies))
                    else:
                        app.stop("operator")
                        self.assertEqual(log.metadata["status"], "aborted")
                    self.assertFalse(board.valve_on or board.trigger_on)
                    self.assertEqual(app.completed_rewards, 0)
                finally:
                    log.close()

    def test_old_schedule_is_accepted_and_bad_input_rejected_before_usb(self):
        with tempfile.TemporaryDirectory() as directory:
            schedule = Path(directory) / "legacy.csv"
            schedule.write_text("Reward,ITI_Duration_S\n1,90\n2,12\n")
            args = Namespace(rewards=2, seed=1, initial_iti_s=90, iti_min_s=10, iti_max_s=20, schedule=schedule)
            rows, seed = make_schedule(args)
            self.assertEqual(rows[1], {"Trial": 2, "ITI_Duration_S": 12, "Rewarded": 1})
            schedule.write_text("Reward,ITI_Duration_S\n1,90\n3,12\n")
            with patch("visualcue.transport.SerialBoard") as serial, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(["--rewards", "2", "--schedule", str(schedule)])
            serial.assert_not_called()

    def test_cli_uses_current_protocol_and_records_one_complete_session(self):
        clock = Clock()
        board = SimulatedBoard(clock)
        with tempfile.TemporaryDirectory() as directory, \
                patch("visualcue.habituation.time.monotonic", clock), \
                patch("visualcue.habituation.time.sleep", clock.sleep), \
                patch("visualcue.simulated_board.SimulatedBoard", return_value=board), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = main(["--simulate", "--autostart", "--rewards", "2", "--initial-iti-s", "1",
                           "--iti-min-s", "1", "--iti-max-s", "1", "--outdir", directory])
            self.assertEqual(result, 0)
            session = next(Path(directory).iterdir())
            metadata = json.loads((session / "metadata.json").read_text())
            self.assertEqual(metadata["status"], "completed")
            self.assertEqual(metadata["completed_rewards"], 2)
            self.assertTrue(board.closed)
            self.assertTrue((session / "schedule.csv").is_file())

    def test_cli_no_start_on_quit_and_ctrl_c_closes_outputs(self):
        for interrupt in (False, True):
            clock = Clock()
            board = SimulatedBoard(clock)
            read = board.read_lines

            def reads():
                if interrupt and board._state == "wait_lick":
                    raise KeyboardInterrupt
                return read()

            with self.subTest(interrupt=interrupt), tempfile.TemporaryDirectory() as directory, \
                    patch("visualcue.habituation.time.monotonic", clock), \
                    patch("visualcue.habituation.time.sleep", clock.sleep), \
                    patch("visualcue.habituation.sys.stdin", io.StringIO("quit\n")), \
                    patch("visualcue.simulated_board.SimulatedBoard", return_value=board), \
                    patch.object(board, "read_lines", side_effect=reads), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                args = ["--simulate", "--rewards", "1", "--initial-iti-s", "1", "--outdir", directory]
                if interrupt:
                    args.append("--autostart")
                result = main(args)
                metadata = json.loads((next(Path(directory).iterdir()) / "metadata.json").read_text())
                self.assertEqual(result, int(interrupt))
                self.assertEqual(metadata["status"], "aborted" if interrupt else "cancelled")
                self.assertFalse(board.valve_on)
                self.assertTrue(board.closed)
