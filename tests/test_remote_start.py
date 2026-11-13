"""Exercise hardware CLI selection using a simulated serial peer, never a USB port."""
import contextlib
import io
import os
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

    def test_firmware_without_session_limit_rejected_before_start(self):
        board = SimulatedBoard()
        original_write = board.write_line
        commands = []

        def write(command):
            commands.append(command)
            if command == "SESSION_LIMIT_CAPS":
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
        self.assertIn("SESSION_LIMIT_CAPS", commands)
        self.assertNotIn("START", commands)
        self.assertIn("STOP", commands)
