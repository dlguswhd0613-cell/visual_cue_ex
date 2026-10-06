import unittest
from prime_valve import ValveController


class Connection:
    """Protocol fixture for host tests; actual GPIO logic is tested in C++."""
    def __init__(self, supported=True):
        self.data = bytearray()
        self.commands = []
        self.supported = supported

    @property
    def in_waiting(self):
        return len(self.data)

    def read(self, size):
        part = bytes(self.data[:size])
        del self.data[:size]
        return part

    def write(self, data):
        command = data.decode().strip()
        self.commands.append(command)
        response = {"HELLO": "READY,1", "VALVE_CAPS": "VALVE_CAPS,1" if self.supported else "ERROR,1",
                    "VALVE_HOLD": "MANUAL_START,1", "PING": "PONG,1", "STOP": "SESSION_ABORTED,1"}.get(command)
        if command.startswith("VALVE_PULSE "):
            response = "MANUAL_START,2"
        if response:
            self.data.extend(f"100,{response}\n".encode())
        return len(data)


class ValveTests(unittest.TestCase):
    def test_start_is_explicit_and_stop_allows_next_mode(self):
        serial = Connection()
        controller = ValveController(serial)
        controller.prepare()
        self.assertEqual(serial.commands, ["HELLO", "VALVE_CAPS"])
        controller.start("hold")
        self.assertTrue(controller.active)
        with self.assertRaises(RuntimeError):
            controller.start("pulse")
        controller.stop()
        controller.start("pulse", 30, 100)
        controller.stop()
        self.assertEqual(serial.commands[-3:], ["STOP", "VALVE_PULSE 30 100", "STOP"])

    def test_old_firmware_rejected_before_open(self):
        serial = Connection(supported=False)
        controller = ValveController(serial)
        with self.assertRaisesRegex(RuntimeError, "latest sketch"):
            controller.prepare()
        self.assertNotIn("VALVE_HOLD", serial.commands)

    def test_invalid_pulse_duration_never_sent(self):
        for value in (0, -1, 9, 60001, True):
            serial = Connection()
            with self.assertRaises(ValueError):
                ValveController(serial).start("pulse", value, 100)
            self.assertEqual(serial.commands, [])

    def test_keepalive_and_loss_detection(self):
        now = [0.0]
        serial = Connection()
        controller = ValveController(serial, clock=lambda: now[0])
        controller.prepare()
        controller.start("hold")
        now[0] = .3
        controller.poll()
        self.assertEqual(serial.commands[-1], "PING")
        # Stop responding: a successful host write is not proof of board health.
        serial.write = lambda data: len(data)
        now[0] = 2.31
        with self.assertRaises(TimeoutError):
            controller.poll()

    def test_board_abort_is_not_reported_as_normal_operation(self):
        serial = Connection()
        controller = ValveController(serial)
        controller.start("hold")
        serial.data.extend(b"200,VALVE_OFF,0\n200,SESSION_ABORTED,2\n")
        with self.assertRaisesRegex(RuntimeError, "SESSION_ABORTED"):
            controller.poll()


if __name__ == "__main__":
    unittest.main()
