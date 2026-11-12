"""Send standalone test pulses via the Uno D7, without running a task or valve.

Start pyPhotometry acquisition first. Upload the updated Uno sketch first.
Pi: python3 test_ttl.py --port /dev/ttyACM0
"""

import argparse
import math
import time

from visualcue.transport import SerialBoard


class TTLTester:
    def __init__(self, board, clock=time.monotonic, sleep=time.sleep):
        self.board = board
        self.clock = clock
        self.sleep = sleep
        self.last_ping = clock()
        self.last_received = clock()

    def poll(self, stopping=False):
        now = self.clock()
        if now - self.last_ping >= .25:
            self.board.write_line("PING")
            self.last_ping = now
        events = []
        for line in self.board.read_lines():
            parts = line.split(",")
            if len(parts) != 3 or not parts[0].isdigit() or not parts[2].isdigit():
                raise RuntimeError("Unexpected reply; upload the updated Uno sketch.")
            at, kind, value = int(parts[0]), parts[1], int(parts[2])
            self.last_received = self.clock()
            if kind == "ERROR":
                raise RuntimeError(f"Uno ERROR {value}; upload the sketch with TTL_CAPS/TTL_PULSE support.")
            if kind == "SESSION_ABORTED" and not (stopping and value == 1):
                raise RuntimeError(f"Uno stopped: reason {value}")
            if kind in ("TTL_ON", "TTL_OFF"):
                print(f"Uno {at}ms: {kind} (D7)", flush=True)
            events.append((kind, value))
        if self.clock() - self.last_received >= 2:
            raise TimeoutError("No response from Uno for 2 seconds")
        return events

    def exchange(self, command, expected, value, timeout=3):
        self.board.write_line(command)
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            events = self.poll(stopping=command == "STOP")
            if (expected, value) in events:
                return
            self.sleep(.005)
        raise TimeoutError(f"No {expected},{value}; upload the updated Uno sketch and check the port.")

    def prepare(self):
        self.exchange("HELLO", "READY", 1)
        self.exchange("TTL_CAPS", "TTL_CAPS", 1)

    def pulse(self, width_ms):
        if type(width_ms) is not int or not 1 <= width_ms <= 1000:
            raise ValueError("pulse width must be 1..1000 ms")
        # Waiting for OFF also handles ON and OFF arriving in one USB read.
        self.exchange(f"TTL_PULSE {width_ms}", "TTL_OFF", 1)

    def wait_until(self, deadline):
        while self.clock() < deadline:
            self.poll()
            self.sleep(min(.005, max(0, deadline - self.clock())))

    def stop(self):
        self.exchange("STOP", "SESSION_ABORTED", 1, timeout=1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="/dev/ttyACM0 on Pi, COM5 on Windows")
    parser.add_argument("--pulse-ms", type=int, default=20)
    parser.add_argument("--interval", type=float, default=10, help="seconds between pulse starts (default 10)")
    parser.add_argument("--count", type=int, default=5)
    args = parser.parse_args(argv)
    if not 1 <= args.pulse_ms <= 1000:
        parser.error("--pulse-ms must be 1..1000")
    if not math.isfinite(args.interval) or args.interval <= args.pulse_ms / 1000:
        parser.error("--interval must be finite and longer than the pulse")
    if args.count < 1:
        parser.error("--count must be >=1")
    board = tester = None
    result = 0
    try:
        board = SerialBoard(args.port)
        time.sleep(2.2)  # Uno resets on USB open; no task START is sent.
        tester = TTLTester(board)
        tester.prepare()  # Old firmware is rejected before sending a pulse.
        print("D7-only test. Start pyPhotometry acquisition; first pulse in 5 seconds.", flush=True)
        tester.wait_until(time.monotonic() + 5)
        for index in range(args.count):
            started = time.monotonic()
            print(f"Pulse {index + 1}/{args.count}, width {args.pulse_ms}ms", flush=True)
            tester.pulse(args.pulse_ms)
            if index + 1 < args.count:
                tester.wait_until(started + args.interval)
        print("Done. Keep pyPhotometry acquiring for at least 8 more seconds for the plot.", flush=True)
    except KeyboardInterrupt:
        print("Interrupted; stopping D7.", flush=True)
        result = 1
    except Exception as error:
        print(f"TTL test failed: {error}", flush=True)
        result = 1
    finally:
        if tester:
            try:
                tester.stop()
            except Exception as error:
                print(f"STOP not acknowledged: {error}. Uno pulse has a 1000ms maximum.", flush=True)
                result = 1
        if board:
            board.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
