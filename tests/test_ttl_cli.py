"""Standalone TTL CLI checks; no real serial ports are opened."""
import unittest
from unittest.mock import patch
from test_ttl import TTLTester, main


class Board:
    def __init__(self, supported=True):
        self.commands, self.lines = [], []
        self.closed = False
        self.supported = supported

    def write_line(self, command):
        self.commands.append(command)
        replies = {"HELLO": ["READY,1"], "PING": ["PONG,1"], "STOP": ["SESSION_ABORTED,1"],
                   "TTL_CAPS": ["TTL_CAPS,1" if self.supported else "ERROR,1"]}
        response = replies.get(command, [])
        if command.startswith("TTL_PULSE "):
            response = ["TTL_ON,1", "TTL_OFF,1"]
        self.lines.extend(f"100,{event}" for event in response)

    def read_lines(self):
        lines, self.lines = self.lines, []
        return lines

    def close(self):
        self.closed = True


class TTLTests(unittest.TestCase):
    def test_pulse_handles_both_edges_arriving_together(self):
        board = Board()
        tester = TTLTester(board)
        tester.prepare()
        tester.pulse(20)
        tester.stop()
        self.assertEqual(board.commands, ["HELLO", "TTL_CAPS", "TTL_PULSE 20", "STOP"])

    def test_old_firmware_rejected_before_pulse(self):
        board = Board(supported=False)
        with self.assertRaisesRegex(RuntimeError, "TTL_CAPS/TTL_PULSE"):
            TTLTester(board).prepare()
        self.assertFalse(any(command.startswith("TTL_PULSE") for command in board.commands))

    def test_invalid_width_not_sent(self):
        board = Board()
        for width in (0, 1001, -1, True):
            with self.assertRaises(ValueError):
                TTLTester(board).pulse(width)
        self.assertEqual(board.commands, [])

    def test_heartbeat_and_response_timeout(self):
        now = [0.0]
        board = Board()
        tester = TTLTester(board, clock=lambda: now[0])
        now[0] = .3
        tester.poll()
        self.assertEqual(board.commands, ["PING"])
        board.write_line = lambda command: None
        now[0] = 2.31
        with self.assertRaises(TimeoutError):
            tester.poll()

    def test_cli_only_sends_ttl_commands_and_cleans_up(self):
        board = Board()
        with patch("test_ttl.SerialBoard", return_value=board), patch("test_ttl.time.sleep"), \
                patch.object(TTLTester, "wait_until"):
            self.assertEqual(main(["--port", "FAKE", "--count", "2"]), 0)
        self.assertEqual(board.commands.count("TTL_PULSE 20"), 2)
        self.assertTrue(set(board.commands) <= {"HELLO", "TTL_CAPS", "TTL_PULSE 20", "STOP", "PING"})
        self.assertEqual(board.commands[-1], "STOP")
        self.assertTrue(board.closed)

    def test_interrupt_stops_and_closes(self):
        board = Board()
        with patch("test_ttl.SerialBoard", return_value=board), patch("test_ttl.time.sleep"), \
                patch.object(TTLTester, "wait_until"), \
                patch.object(TTLTester, "pulse", side_effect=KeyboardInterrupt):
            self.assertEqual(main(["--port", "FAKE"]), 1)
        self.assertEqual(board.commands[-1], "STOP")
        self.assertTrue(board.closed)
