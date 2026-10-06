"""Manual valve control for the updated visual-task Uno firmware.

Install: python -m pip install pyserial==3.5
Windows: python prime_valve.py --port COM5
Pi:      python prime_valve.py --port /dev/ttyACM0
Menu: 1=hold open, 2=repeat pulses, q=quit. Enter stops an active mode.
No screen or conditioning trials are used. Update the Uno sketch first.
"""

import argparse
import math
import queue
import sys
import threading
import time


class ValveController:
    def __init__(self, connection, clock=time.monotonic):
        self.connection = connection
        self.clock = clock
        self.buffer = bytearray()
        self.last_ping = clock()
        self.last_received = clock()
        self.active = False

    def send(self, command):
        data = (command + "\n").encode("ascii")
        if self.connection.write(data) != len(data):
            raise IOError("Incomplete command write")

    def receive(self):
        waiting = self.connection.in_waiting
        if waiting:
            self.buffer.extend(self.connection.read(min(waiting, 8192)))
        if len(self.buffer) > 16384:
            raise IOError("Arduino receive buffer overflow")
        events = []
        while b"\n" in self.buffer:
            raw, _, rest = self.buffer.partition(b"\n")
            self.buffer = bytearray(rest)
            line = raw.decode("ascii").strip()
            if not line:
                continue
            fields = line.split(",")
            if len(fields) != 3 or not fields[0].isdigit() or not fields[2].isdigit():
                raise RuntimeError("Unexpected reply. Upload the latest HEADFIXED_ARDUINO.ino first.")
            self.last_received = self.clock()
            events.append((int(fields[0]), fields[1], int(fields[2])))
        return events

    def heartbeat(self):
        if self.clock() - self.last_ping >= .25:
            self.send("PING")
            self.last_ping = self.clock()

    def exchange(self, command, expected, value, timeout=3):
        self.send(command)
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            self.heartbeat()
            for _, kind, received in self.receive():
                if kind == "ERROR":
                    raise RuntimeError(f"Arduino ERROR {received}. Upload the latest sketch with valve support.")
                if kind == "SESSION_ABORTED":
                    raise RuntimeError(f"Arduino stopped: reason {received}")
                if kind == expected and received == value:
                    return
            time.sleep(.005)
        raise TimeoutError(f"No {expected} reply from Arduino")

    def prepare(self):
        self.exchange("HELLO", "READY", 1)
        self.exchange("VALVE_CAPS", "VALVE_CAPS", 1)

    def start(self, mode, on_ms=300, off_ms=100):
        if self.active:
            raise RuntimeError("Stop the active mode before starting another")
        if mode not in ("hold", "pulse"):
            raise ValueError("mode must be hold or pulse")
        if any(type(v) is not int or not 10 <= v <= 60000 for v in (on_ms, off_ms)):
            raise ValueError("Pulse on/off times must be integers from 10 to 60000 ms")
        self.active = True  # teardown must STOP even if the start acknowledgment is lost
        command = "VALVE_HOLD" if mode == "hold" else f"VALVE_PULSE {on_ms} {off_ms}"
        self.exchange(command, "MANUAL_START", 1 if mode == "hold" else 2)

    def poll(self):
        self.heartbeat()
        events = self.receive()
        for _, kind, value in events:
            if kind in ("ERROR", "SESSION_ABORTED", "READY"):
                raise RuntimeError(f"Unexpected Arduino event {kind},{value}; valve control stopped")
        if self.clock() - self.last_received >= 2:
            raise TimeoutError("Arduino response timeout")
        return events

    def stop(self):
        # Send STOP before printing or waiting for input; repeat only on a later call.
        self.send("STOP")
        self.active = False
        deadline = self.clock() + 1
        while self.clock() < deadline:
            if any(kind == "SESSION_ABORTED" and value == 1 for _, kind, value in self.receive()):
                return
            time.sleep(.005)
        raise TimeoutError("STOP was sent but no closed-output acknowledgment arrived")


def read_keyboard(messages):
    """Keep heartbeat running while waiting for Enter, including on Windows."""
    try:
        for line in sys.stdin:
            messages.put(line.strip().lower())
    finally:
        messages.put(None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", "--com", required=True, help="COM5 on Windows, /dev/ttyACM0 on Pi")
    parser.add_argument("--on-ms", type=int, default=300, help="pulse open time (default 300 ms)")
    parser.add_argument("--off-ms", type=int, default=100, help="pulse closed time (default 100 ms)")
    parser.add_argument("--seconds", type=float, help="optional automatic stop time for each mode")
    args = parser.parse_args(argv)
    if not all(10 <= n <= 60000 for n in (args.on_ms, args.off_ms)):
        parser.error("--on-ms and --off-ms must be 10..60000")
    if args.seconds is not None and (not math.isfinite(args.seconds) or args.seconds <= 0):
        parser.error("--seconds must be a finite positive number")
    controller = connection = None
    result = 0
    try:
        import serial
        connection = serial.Serial(args.port, 115200, timeout=0, write_timeout=.25)
        controller = ValveController(connection)
        time.sleep(2.2)  # Uno reset after opening USB
        controller.prepare()
        messages = queue.Queue()
        threading.Thread(target=read_keyboard, args=(messages,), daemon=True).start()
        print("밸브 점검 준비 완료. 물이 실제 나오는지는 직접 확인하세요.", flush=True)
        while True:
            print(f"\n1: 계속 열기  2: {args.on_ms}ms 열기/{args.off_ms}ms 닫기 반복  q: 종료", flush=True)
            choice = messages.get()
            if choice is None or choice == "q":
                break
            if choice not in ("1", "2"):
                print("1, 2 또는 q를 입력하고 Enter를 누르세요.", flush=True)
                continue
            print("작동 시작. Enter를 누르면 닫힙니다. Ctrl+C는 닫고 종료합니다.", flush=True)
            started = time.monotonic()
            controller.start("hold" if choice == "1" else "pulse", args.on_ms, args.off_ms)
            leave = False
            while True:
                try:
                    line = messages.get_nowait()
                    leave = line is None or line == "q"
                    break  # Any entered line stops; no mode switches while open.
                except queue.Empty:
                    pass
                if args.seconds is not None and time.monotonic() - started >= args.seconds:
                    break
                events = controller.poll()
                for timestamp, kind, _ in events:
                    if kind in ("VALVE_ON", "VALVE_OFF"):
                        print(f"Arduino {timestamp}ms: {kind}", flush=True)
                time.sleep(.005)
            controller.stop()
            print("밸브 OFF 응답을 확인했습니다.", flush=True)
            if leave:
                break
    except KeyboardInterrupt:
        result = 130
    except Exception as error:
        # Close outputs before console I/O, which could block.
        if controller:
            try:
                controller.send("STOP")
            except Exception:
                pass
        print(f"오류: {error}", file=sys.stderr)
        result = 1
    finally:
        if controller:
            try:
                controller.stop()
            except Exception as error:
                print(f"종료 확인 실패: {error}. USB 통신이 끊기면 보드가 약 2초 뒤 출력을 닫습니다.", file=sys.stderr)
                if result == 0:
                    result = 1
        if connection:
            connection.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
