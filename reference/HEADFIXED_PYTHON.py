r"""
Pavlovian task serial logger.

Reads event lines from one or more Arduino boards (HEADFIXED_ARDUINO.ino) over
serial and writes them to per-mouse CSV files. Also lets the operator send
session commands to a specific Arduino, since opening a COM port here means
the Arduino IDE Serial Monitor can no longer use it at the same time.

Trial order / ITI durations are no longer decided by the Arduino on the fly.
Run generate_schedule.py once per day to create a fixed schedule CSV, then
point every mouse's run at that same file with --schedule so they all use
the identical sequence that day.

Once running, type a digit at the "> " prompt to control the Arduino:
    "1" -> start CS+/CS- conditioning session (schedule required)
    "2" -> start habituation session (schedule required)
    "4" -> abort whatever is currently running

Manual valve priming ("3" on the Arduino's serial protocol) is NOT handled
here anymore - use prime_valve.py instead, one rig at a time
(python prime_valve.py --com COM3). That keeps priming independent of the
logging/session script, so priming one rig never touches another rig's run.

Sending "1" or "2" first reads --schedule's CSV and transmits the whole
sequence to the Arduino (marker 'C' or 'H' + the schedule, see
HEADFIXED_ARDUINO.ino's serial protocol notes), then sends the start digit.
Both mode 1 and mode 2 begin on the Arduino with 3 LED/TTL blinks, then a
fixed 90 s start ITI, then the first trial/reward. Later ITIs follow the
loaded schedule.

Arduino line format: "millis,Event,Value"
Main CSV columns     : PC_Timestamp, Arduino_ms, Event, Value

A second CSV is also opened when "1"/"2" is sent, recording the sequence as
it actually executes (useful to confirm it matches the schedule, and to see
how far a session got if it was aborted):
  "1" (conditioning) -> columns Trial, CS_Type, ITI_Duration_S
  "2" (habituation)  -> columns Reward, ITI_Duration_S

Two ways to run this for multiple rigs:
  1) Multi-rig in one process: fill in ARDUINOS below and run with no arguments.
     All rigs share one console; stopping the script stops all of them together.
     Control each rig by typing '<mouse_id> <digit>' at the prompt.
  2) One rig per process (recommended when mice finish training at different
     times and you don't want to disturb the other rigs): pass --mice/--com
     and open one PyCharm run configuration (or terminal) per rig, e.g.
       python HEADFIXED_PYTHON.py --mice npy3 --com COM3 --schedule "D:\Schedules\...csv"
       python HEADFIXED_PYTHON.py --mice npy4 --com COM4 --schedule "D:\Schedules\...csv"
     Each process is fully independent - restart or close one without
     touching the others.

Install dependency once:  pip install pyserial
"""

import argparse
import csv
import threading
import time
from datetime import datetime
from pathlib import Path

import serial

# ---- Edit this to choose where CSV files are saved. ----
# Leave as None to save to a "data" folder next to this script.
# Otherwise set an absolute path, e.g. r"D:\PavlovianData"
SAVE_DIR = "D:\\AM\\Data"

# ---- Path to the schedule CSV made by generate_schedule.py. ----
#  "1" (conditioning) -> columns Trial, CS_Type, ITI_Duration_S
#  "2" (habituation)  -> columns Reward, ITI_Duration_S
# Required to send "1" or "2". Can be overridden with --schedule.
SCHEDULE_PATH = "D:\\AM\\Data\\Schedule\\20261001_142839_habituation_schedule.csv"

# 1 = conditioning session, 2 = habituation session, 4 = stop.
# Manual valve priming ("3") is handled by prime_valve.py, not here.
VALID_COMMANDS = ("1", "2", "4")

# ---- Used only when the script is run with no --com argument (multi-rig mode). ----
ARDUINOS = [
    {"mouse_id": "261001_HJ1", "port": "COM3", "baud": 115200},
    #{"mouse_id": "NPY193_3", "port": "COM8", "baud": 115200},
]

ARDUINO_RESET_WAIT_S = 2.0  # opening a serial port resets most Arduino boards
SCHEDULE_SETTLE_S = 0.1     # brief pause after sending a schedule, before the start digit

# ---- Must match HEADFIXED_ARDUINO.ino's TOTAL_TRIALS / TOTAL_REWARDS. Used only for the progress summary. ----
TOTAL_TRIALS_CONDITIONING = 100
TOTAL_REWARDS_HABITUATION = 80

STATUS_REPORT_INTERVAL_S = 60  # how often to print the all-rig progress summary


class ArduinoLogger(threading.Thread):
    def __init__(self, mouse_id, port, baud, output_dir, schedule_path=None):
        super().__init__(daemon=True)
        self.mouse_id = mouse_id
        self.port = port
        self.baud = baud
        self.output_dir = output_dir
        self.schedule_path = schedule_path
        self.ser = None
        self.csv_file = None
        self.csv_writer = None
        self.executed_file = None
        self.executed_writer = None
        self.active_mode = None  # "1" (conditioning) or "2" (habituation)
        self.session_active = False
        self.pending_iti_duration = None
        self.running = True

        # Progress tracking for the periodic status summary (see status_line()).
        self.status = "IDLE"  # IDLE, RUNNING, DONE, ABORTED
        self.progress_current = None
        self.progress_total = None

    def connect(self):
        """Open the serial port and wait out the Arduino's reset, synchronously.

        Must be called (and finish) for one board before the next board's
        connect() starts - opening a port toggles DTR and resets the Arduino,
        and resetting multiple boards at nearly the same instant (e.g. several
        threads opening ports back-to-back) can glitch a shared USB hub/
        controller so some boards never come back up. This is why main()
        calls connect() in a plain sequential for-loop over ARDUINOS rather
        than from each board's thread - it works the same way regardless of
        how many boards are configured (2, 6, or more). Returns True on
        success.
        """
        print(f"Mice: {self.mouse_id}  Com: {self.port}")
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=1)
        except serial.SerialException as exc:
            print(f"[Mice: {self.mouse_id} Com: {self.port}] could not open port: {exc}")
            return False

        time.sleep(ARDUINO_RESET_WAIT_S)
        self._open_csv()
        return True

    def run(self):
        if not (self.ser and self.ser.is_open):
            return

        while self.running:
            try:
                raw = self.ser.readline().decode("utf-8", errors="replace").strip()
            except serial.SerialException:
                break
            if not raw:
                continue

            if raw.startswith("#") or raw.startswith("Timestamp_ms"):
                print(f"[{self.mouse_id}] {raw}")
                continue

            parts = raw.split(",")
            if len(parts) != 3:
                print(f"[{self.mouse_id}] unparsed line: {raw}")
                continue

            arduino_ms, event, value = parts
            pc_time = datetime.now().isoformat(timespec="milliseconds")
            self.csv_writer.writerow([pc_time, arduino_ms, event, value])
            self.csv_file.flush()
            print(f"[{self.mouse_id}] {pc_time} {event} {value}")

            if event == "ITI_DURATION_S":
                self.pending_iti_duration = value
            elif event in ("CS_PLUS_ON", "CS_MINUS_ON") and self.active_mode == "1" and self.executed_writer:
                cs_type = "CS+" if event == "CS_PLUS_ON" else "CS-"
                self.executed_writer.writerow([value, cs_type, self.pending_iti_duration])
                self.executed_file.flush()
                self.pending_iti_duration = None
            elif event == "REWARD_ON" and self.active_mode == "2" and self.executed_writer:
                self.executed_writer.writerow([value, self.pending_iti_duration])
                self.executed_file.flush()
                self.pending_iti_duration = None
            elif event == "ITI_START" and self.status == "RUNNING":
                try:
                    self.progress_current = int(value)
                except ValueError:
                    pass
            elif event in ("SESSION_END", "SESSION_ABORTED"):
                self.session_active = False
                self.status = "DONE" if event == "SESSION_END" else "ABORTED"
                if event == "SESSION_END":
                    self.progress_current = self.progress_total

        self._close()

    def _open_csv(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.output_dir / f"{stamp}_{self.mouse_id}_{self.port}.csv"
        self.csv_file = open(path, "w", newline="", encoding="utf-8")
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(["PC_Timestamp", "Arduino_ms", "Event", "Value"])
        print(f"[{self.mouse_id}] logging to {path}")

    def _open_executed_csv(self, mode):
        if self.executed_file:
            self.executed_file.close()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if mode == "1":
            suffix, headers = "conditioning_executed", ["Trial", "CS_Type", "ITI_Duration_S"]
        else:
            suffix, headers = "habituation_executed", ["Reward", "ITI_Duration_S"]
        path = self.output_dir / f"{stamp}_{self.mouse_id}_{self.port}_{suffix}.csv"
        self.executed_file = open(path, "w", newline="", encoding="utf-8")
        self.executed_writer = csv.writer(self.executed_file)
        self.executed_writer.writerow(headers)
        print(f"[{self.mouse_id}] executed sequence -> {path}")

    def _read_schedule_rows(self):
        if not self.schedule_path:
            print(f"[{self.mouse_id}] ERROR: no --schedule given, cannot start a session.")
            return None
        path = Path(self.schedule_path)
        if not path.exists():
            print(f"[{self.mouse_id}] ERROR: schedule file not found: {path}")
            return None
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header
            return [row for row in reader if row]  # drop any blank lines

    def _build_schedule_payload(self, mode, rows):
        expected_cols = 3 if mode == "1" else 2
        tokens = []
        for i, row in enumerate(rows, start=1):
            if len(row) != expected_cols:
                print(f"[{self.mouse_id}] ERROR: schedule row {i} has {len(row)} column(s), "
                      f"expected {expected_cols}. Wrong schedule file for this mode?")
                return None
            try:
                if mode == "1":
                    _, cs_type, iti = row
                    cs_type = cs_type.strip()
                    if cs_type not in ("CS+", "CS-"):
                        print(f"[{self.mouse_id}] ERROR: schedule row {i} has CS_Type '{cs_type}', "
                              f"expected exactly 'CS+' or 'CS-'.")
                        return None
                    tokens.append(f"{'+' if cs_type == 'CS+' else '-'}{int(iti)}")
                else:
                    _, iti = row
                    tokens.append(str(int(iti)))
            except ValueError:
                print(f"[{self.mouse_id}] ERROR: schedule row {i} has a non-numeric ITI value: {row}")
                return None
        return tokens

    def _send_schedule(self, mode):
        rows = self._read_schedule_rows()
        if not rows:
            return False

        tokens = self._build_schedule_payload(mode, rows)
        if tokens is None:
            return False

        marker = "C" if mode == "1" else "H"
        payload = ",".join(tokens) + "\n"
        self.ser.write(marker.encode("utf-8"))
        self.ser.write(payload.encode("utf-8"))
        print(f"[{self.mouse_id}] sent schedule ({len(tokens)} entries) from {self.schedule_path}")
        time.sleep(SCHEDULE_SETTLE_S)
        return True

    def send_command(self, cmd):
        if not (self.ser and self.ser.is_open):
            return

        if cmd in ("1", "2"):
            if self.session_active:
                print(f"[{self.mouse_id}] Ignored '{cmd}': a session is already running on this rig.")
                return
            if not self._send_schedule(cmd):
                print(f"[{self.mouse_id}] Schedule not sent - '{cmd}' aborted, nothing started.")
                return
            self.active_mode = cmd
            self.session_active = True
            self.pending_iti_duration = None
            self._open_executed_csv(cmd)
            self.status = "RUNNING"
            self.progress_current = 0
            self.progress_total = TOTAL_TRIALS_CONDITIONING if cmd == "1" else TOTAL_REWARDS_HABITUATION

        self.ser.write(cmd.encode("utf-8"))

    def status_line(self):
        mode_name = {"1": "conditioning", "2": "habituation"}.get(self.active_mode, "-")
        if self.status == "IDLE":
            return f"{self.mouse_id} ({self.port}): idle"
        progress = f"{self.progress_current}/{self.progress_total}" if self.progress_total else "-"
        return f"{self.mouse_id} ({self.port}): {self.status} [{mode_name}] {progress}"

    def stop(self):
        self.running = False

    def _close(self):
        if self.csv_file:
            self.csv_file.close()
        if self.executed_file:
            self.executed_file.close()
        if self.ser and self.ser.is_open:
            self.ser.close()


def sequential_command_mode(loggers):
    """Walk through every configured rig one at a time and ask for a command,
    instead of typing '<mouse_id> <digit>' into a console that's also full of
    live sensor events from every other rig.
    """
    print("Sequential mode - one rig at a time. Enter 1/2/4, or leave blank to skip a rig.")
    for mouse_id, logger in loggers.items():
        while True:
            cmd = input(f"  [{mouse_id} ({logger.port})] > ").strip()
            if cmd == "":
                print(f"  [{mouse_id}] skipped.")
                break
            if cmd not in VALID_COMMANDS:
                print("  Command must be 1, 2, or 4 (or blank to skip).")
                continue
            logger.send_command(cmd)
            break
    print("Sequential mode done.")


def report_status_periodically(loggers, stop_event):
    while not stop_event.wait(STATUS_REPORT_INTERVAL_S):
        print(f"\n=== Status {datetime.now().strftime('%H:%M:%S')} ===")
        for logger in loggers.values():
            print(f"  {logger.status_line()}")
        print()


def parse_args():
    parser = argparse.ArgumentParser(description="Log one Arduino rig's events to CSV.")
    parser.add_argument("--mice", default="npy3", help="Mouse/rig ID, e.g. npy3 (used in the CSV filename).")
    parser.add_argument("--com", help="COM port, e.g. COM3. If given, ignores the ARDUINOS list and runs just this one rig.")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument(
        "--schedule",
        default=SCHEDULE_PATH,
        help="Path to the schedule CSV from generate_schedule.py. Required before sending 1 or 2. "
             "Defaults to the SCHEDULE_PATH variable above.",
    )
    parser.add_argument(
        "--outdir",
        default=SAVE_DIR if SAVE_DIR else str(Path(__file__).parent / "data"),
        help="Folder to save CSV files in. Defaults to the SAVE_DIR variable above.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    output_dir = Path(args.outdir)

    arduino_configs = (
        [{"mouse_id": args.mice, "port": args.com, "baud": args.baud}]
        if args.com
        else ARDUINOS
    )

    mouse_ids = [cfg["mouse_id"] for cfg in arduino_configs]
    duplicates = {m for m in mouse_ids if mouse_ids.count(m) > 1}
    if duplicates:
        print(f"WARNING: duplicate mouse_id(s) in ARDUINOS: {duplicates}. "
              f"Only the last rig with each duplicated id will be controllable.")

    loggers = {}
    for cfg in arduino_configs:
        logger = ArduinoLogger(cfg["mouse_id"], cfg["port"], cfg["baud"], output_dir, schedule_path=args.schedule)
        # connect() (port open + reset wait) runs synchronously here, one board
        # at a time, before the next board's port is even opened. This loop
        # doesn't care how many entries ARDUINOS has - each one is connected
        # in turn, so the reset-collision protection scales to any number of
        # rigs. See the docstring on connect() for why simultaneous opens are unsafe.
        if logger.connect():
            logger.start()
            loggers[cfg["mouse_id"]] = logger
        else:
            print(f"[{cfg['mouse_id']}] skipped - connection failed.")

    status_stop_event = threading.Event()
    status_thread = threading.Thread(
        target=report_status_periodically, args=(loggers, status_stop_event), daemon=True
    )
    status_thread.start()

    print("Commands: 1=conditioning, 2=habituation, 4=stop. (priming: run prime_valve.py separately)")
    if args.schedule:
        print(f"Schedule file: {args.schedule}")
    else:
        print("WARNING: no --schedule set - sending '1' or '2' will be refused.")
    if len(loggers) == 1:
        print("Single Arduino configured: type the digit directly, e.g. '4'.")
    else:
        print("Multiple Arduinos configured: type '<mouse_id> <digit>', e.g. 'npy3 4'.")
        print("Or type 'all' to go through every rig one at a time instead.")
    print("Type 'quit' to exit.")

    try:
        while True:
            line = input("> ").strip()
            if not line:
                continue
            if line.lower() == "quit":
                break
            if line.lower() == "all" and len(loggers) > 1:
                sequential_command_mode(loggers)
                continue

            tokens = line.split()
            if len(tokens) == 1 and len(loggers) == 1:
                mouse_id, cmd = next(iter(loggers)), tokens[0]
            elif len(tokens) == 2:
                mouse_id, cmd = tokens
            else:
                print("Format: '<mouse_id> <digit>' (or just '<digit>' with one Arduino configured).")
                continue

            if mouse_id not in loggers:
                print(f"Unknown mouse_id '{mouse_id}'. Configured: {list(loggers.keys())}")
                continue
            if cmd not in VALID_COMMANDS:
                print("Command must be 1, 2, or 4.")
                continue

            loggers[mouse_id].send_command(cmd)
    except KeyboardInterrupt:
        pass
    finally:
        status_stop_event.set()
        for logger in loggers.values():
            logger.stop()
        for logger in loggers.values():
            logger.join(timeout=2)


if __name__ == "__main__":
    main()
