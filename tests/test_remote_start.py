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
from visualcue.config import load_config
from visualcue.simulated_board import SimulatedBoard


class RemoteStartTests(unittest.TestCase):
    def test_task_cli_overrides_config_and_records_selected_behavior(self):
        for selection, task in (("1", "pavlovian"), ("pavlovian", "pavlovian"),
                                ("2", "operant"), ("operant", "operant")):
            with self.subTest(selection=selection), tempfile.TemporaryDirectory() as directory:
                config = load_config()
                config["session"].update(task="operant" if task == "pavlovian" else "pavlovian",
                                         trials=1, cue_delay_ms=20, cue_duration_ms=20,
                                         reward_at_ms=100, post_reward_ms=100, valve_open_ms=10,
                                         initial_iti_s=0, iti_min_s=0, iti_max_s=0)
                del config["photometry"]
                path = Path(directory) / "config.json"
                path.write_text(json.dumps(config))
                board = SimulatedBoard()
                original_write = board.write_line
                commands = []

                def write(command):
                    commands.append(command)
                    # The previous lick-end sketch has no TASK command. Operant
                    # must remain compatible without requiring another upload.
                    if task == "operant" and command.startswith("TASK "):
                        board._emit("ERROR", 1)
                    else:
                        original_write(command)

                output = io.StringIO()
                with patch.dict(os.environ, {"SDL_VIDEODRIVER": "dummy"}), \
                        patch("visualcue.simulated_board.SimulatedBoard", return_value=board), \
                        patch.object(board, "write_line", side_effect=write), \
                        contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    result = main(["--simulate", "--config", str(path), "--task", selection,
                                   "--autostart", "--exit-when-done", "--outdir", str(Path(directory) / "data")])
                self.assertEqual(result, 0, output.getvalue())
                session = next((Path(directory) / "data").iterdir())
                metadata = json.loads((session / "metadata.json").read_text())
                with (session / "events.csv").open(newline="") as file:
                    events = list(csv.DictReader(file))
                number = 1 if task == "pavlovian" else 2
                self.assertEqual(metadata["task"], task)
                self.assertEqual(metadata["task_number"], number)
                self.assertEqual(metadata["config"]["session"]["task"], task)
                self.assertEqual(metadata["status"], "completed")
                self.assertEqual(metadata["completed_trials"], 1)
                self.assertIn(f"Task {number}: {task.capitalize()} task", output.getvalue())
                if task == "pavlovian":
                    self.assertIn("TASK 1", commands)
                    self.assertLess(commands.index("TASK 1"), commands.index("TRIAL 1 0 1"))
                    self.assertEqual(metadata["trial_end_rule"], "reward_at_plus_post_reward")
                    self.assertFalse(any(e["Event"] == "WAIT_LICK" for e in events))
                else:
                    self.assertIn("LICK_END_CAPS", commands)
                    self.assertEqual(metadata["trial_end_rule"], "post_reward_lick_and_valve_closed")
                    self.assertTrue(any(e["Event"] == "WAIT_LICK" for e in events))

    def test_pavlovian_rejected_before_start_on_unsupported_firmware(self):
        board = SimulatedBoard()
        original_write = board.write_line
        commands = []

        def write(command):
            commands.append(command)
            if command == "TASK 1":
                board._emit("ERROR", 1)
            else:
                original_write(command)

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"SDL_VIDEODRIVER": "dummy"}), \
                patch("visualcue.simulated_board.SimulatedBoard", return_value=board), \
                patch.object(board, "write_line", side_effect=write), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = main(["--simulate", "--task", "1", "--autostart", "--outdir", directory])
        self.assertEqual(result, 1)
        self.assertNotIn("START", commands)
        self.assertIn("STOP", commands)
        self.assertIn("task-selectable Uno sketch", output.getvalue())

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

    def test_session_keeps_running_after_three_hours_until_operator_interrupt(self):
        board = SimulatedBoard()
        original_write = board.write_line
        commands = []
        started_reads = 0
        original_read = board.read_lines

        def write(command):
            commands.append(command)
            original_write(command)
            if command == "START":
                clock.return_value += 3 * 3600

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
                patch("visualcue.simulated_board.SimulatedBoard", return_value=board), \
                patch("visualcue.runner.time.monotonic", return_value=100.0) as clock, \
                patch.object(board, "write_line", side_effect=write), \
                patch.object(board, "read_lines", side_effect=read), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = main(["--simulate", "--autostart", "--exit-when-done", "--outdir", directory])
            session = next(Path(directory).iterdir())
            metadata = json.loads((session / "metadata.json").read_text())
            with (session / "events.csv").open(newline="") as file:
                events = list(csv.DictReader(file))
        self.assertEqual(result, 1)  # Operator interruption, not a time limit.
        self.assertEqual(started_reads, 2)
        self.assertNotIn("SESSION_LIMIT_CAPS", commands)
        self.assertEqual(commands.count("START"), 1)
        self.assertIn("STOP", commands)  # Cleanup after Ctrl+C still works.
        self.assertNotIn("session_limit_s", metadata)
        self.assertNotIn("end_reason", metadata)
        self.assertIn(("SESSION_ABORTED", "arduino"), [(e["Event"], e["Source"]) for e in events])
        self.assertFalse(any(e["Event"] == "SESSION_TIME_LIMIT" for e in events))
        self.assertFalse(any(e["Event"] == "TRIAL_END" for e in events))
        self.assertFalse(board.valve_on or board.trigger_on)
        self.assertIn("SESSION_START:", output.getvalue())
