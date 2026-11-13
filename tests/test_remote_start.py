"""Exercise hardware CLI selection using a simulated serial peer, never a USB port."""
import contextlib
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from visualcue.runner import main
from visualcue.simulated_board import SimulatedBoard


class RemoteStartTests(unittest.TestCase):
    def test_hardware_autostart_and_terminal_interrupt_close_outputs(self):
        board = SimulatedBoard()
        commands = []
        original_write = board.write_line
        original_read = board.read_lines
        started_reads = 0

        def write(command):
            commands.append(command)
            original_write(command)

        def read():
            nonlocal started_reads
            if "START" in commands and "STOP" not in commands:
                started_reads += 1
                if started_reads == 2:
                    raise KeyboardInterrupt
            return original_read()

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"SDL_VIDEODRIVER": "dummy"}), \
                patch("visualcue.transport.SerialBoard", return_value=board) as serial, \
                patch.object(board, "write_line", side_effect=write), \
                patch.object(board, "read_lines", side_effect=read), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = main(["--port", "FAKE", "--autostart", "--outdir", directory])
        serial.assert_called_once_with("FAKE", 115200)
        self.assertEqual(result, 1)  # Ctrl+C is an interrupted, not completed session.
        self.assertEqual(commands.count("START"), 1)
        self.assertIn("STOP", commands)
        self.assertIn("SESSION_START:", output.getvalue())

    def test_demo_still_requires_simulation(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(["--demo", "--autostart"])
        self.assertEqual(error.exception.code, 2)

    def test_fixed_duration_firmware_rejected_before_start(self):
        board = SimulatedBoard()
        original_write = board.write_line
        commands = []

        def write(command):
            commands.append(command)
            if command == "LICK_END_CAPS":
                board._emit("ERROR", 1)
            else:
                original_write(command)

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"SDL_VIDEODRIVER": "dummy"}), \
                patch("visualcue.simulated_board.SimulatedBoard", return_value=board), \
                patch.object(board, "write_line", side_effect=write), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = main(["--simulate", "--autostart", "--outdir", directory])
        self.assertEqual(result, 1)
        self.assertIn("LICK_END_CAPS", commands)
        self.assertNotIn("START", commands)
        self.assertIn("STOP", commands)
        self.assertIn("command='LICK_END_CAPS'", output.getvalue())
        self.assertIn("Post-reward lick trial endings", output.getvalue())
        self.assertIn("one-hour session limit runs in Python", output.getvalue())

    def test_host_time_limit_completes_with_previous_firmware_and_exits(self):
        board = SimulatedBoard()
        original_write = board.write_line
        commands = []

        def write(command):
            commands.append(command)
            original_write(command)

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"SDL_VIDEODRIVER": "dummy"}), \
                patch("visualcue.simulated_board.SimulatedBoard", return_value=board), \
                patch("visualcue.runner.SESSION_LIMIT_S", .02), \
                patch.object(board, "write_line", side_effect=write), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = main(["--simulate", "--autostart", "--exit-when-done", "--outdir", directory])
            session = next(Path(directory).iterdir())
            metadata = json.loads((session / "metadata.json").read_text())
            with (session / "events.csv").open(newline="") as file:
                events = list(csv.DictReader(file))
        self.assertEqual(result, 0, output.getvalue())
        self.assertNotIn("SESSION_LIMIT_CAPS", commands)
        self.assertEqual(commands.count("START"), 1)
        self.assertEqual(commands.count("STOP"), 1)
        self.assertEqual(metadata["status"], "completed")
        self.assertEqual(metadata["end_reason"], "time_limit")
        self.assertEqual(metadata["session_limit_controller"], "python")
        self.assertEqual(metadata["completed_trials"], 0)
        self.assertIn(("SESSION_ABORTED", "arduino"), [(e["Event"], e["Source"]) for e in events])
        self.assertIn(("SESSION_END", "host"), [(e["Event"], e["Source"]) for e in events])
        self.assertFalse(any(e["Event"] == "TRIAL_END" for e in events))
        self.assertFalse(board.valve_on or board.trigger_on)
        self.assertIn("SESSION_TIME_LIMIT:", output.getvalue())
