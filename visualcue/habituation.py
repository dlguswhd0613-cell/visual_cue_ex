"""Headless habituation using the current firmware's lick-gated trial engine."""
import argparse
import csv
import queue
import sys
import threading
import time
from pathlib import Path

from .recording import SessionLog
from .schedule import generate_schedule, load_schedule


# The firmware requires cue handshakes before reward. Nothing is displayed.
# Subtract this second from firmware ITIs so lick -> next water retains the
# requested interval, apart from the usual firmware/USB scheduling tolerance.
HANDSHAKE_MS = 1000


def make_schedule(args):
    session = dict(trials=args.rewards, seed=args.seed, initial_iti_s=args.initial_iti_s,
                   iti_min_s=args.iti_min_s, iti_max_s=args.iti_max_s, iti_distribution="uniform")
    if args.schedule is None:
        return generate_schedule(session)
    with args.schedule.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames == ["Reward", "ITI_Duration_S"]:
            try:
                rows = [{"Trial": int(row["Reward"]), "ITI_Duration_S": int(row["ITI_Duration_S"]),
                         "Rewarded": 1} for row in reader]
            except (ValueError, TypeError) as error:
                raise ValueError("Habituation schedule fields must be integers") from error
        else:
            return load_schedule(args.schedule, session), None
    if len(rows) != args.rewards:
        raise ValueError("Schedule row count must match --rewards")
    for trial, row in enumerate(rows, 1):
        if row["Trial"] != trial:
            raise ValueError("Schedule Reward numbers must be consecutive, starting at 1")
        if trial == 1 and row["ITI_Duration_S"] != args.initial_iti_s:
            raise ValueError("First schedule ITI must match --initial-iti-s")
        if trial > 1 and not args.iti_min_s <= row["ITI_Duration_S"] <= args.iti_max_s:
            raise ValueError("Schedule ITI outside --iti-min-s/--iti-max-s")
    return rows, None


class Habituation:
    def __init__(self, board, recording, rows, valve_ms, clock=None):
        self.board = board
        self.recording = recording
        self.rows = rows
        self.valve_ms = valve_ms
        self.clock = clock or time.monotonic
        self.last_received = self.clock()
        self.last_ping = -float("inf")
        self.started = False
        self.done = False
        self.cue_trial = None
        self.cue_off_at = None
        self.current_trial = None
        self.completed_rewards = 0

    def send(self, command):
        self.board.write_line(command)
        if command != "PING":
            self.recording.event("COMMAND", command)

    def read_events(self):
        result = []
        failure = None
        for line in self.board.read_lines():
            parts = line.split(",")
            if len(parts) != 3 or not parts[0].isdigit() or not parts[2].isdigit():
                self.recording.event("INVALID_SERIAL_LINE", line)
                failure = RuntimeError("Unexpected serial protocol. Use the current visual-task Uno sketch.")
                continue
            timestamp, kind, value = int(parts[0]), parts[1], int(parts[2])
            self.last_received = self.clock()
            if kind != "PONG":
                self.recording.event(kind, value, timestamp, "arduino")
            if kind == "ERROR":
                failure = RuntimeError(f"Arduino ERROR {value}. Current visual-task firmware with LICK_END_CAPS is required.")
            result.append((kind, value))
        if failure:
            raise failure
        return result

    def ping(self):
        if self.clock() - self.last_ping >= .5:
            self.send("PING")
            self.last_ping = self.clock()

    def exchange(self, command, expected, value, timeout=3):
        self.send(command)
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            self.ping()
            replies = self.read_events()
            if any(kind == "SESSION_ABORTED" for kind, _ in replies):
                raise RuntimeError("Arduino aborted during preparation")
            if (expected, value) in replies:
                return
            time.sleep(.005)
        raise TimeoutError(f"No {expected},{value} for {command!r}; check the firmware and serial port")

    def prepare(self):
        self.exchange("HELLO", "READY", 1)
        self.exchange("LICK_END_CAPS", "LICK_END_CAPS", 1)
        initial = self.rows[0]["ITI_Duration_S"] - 1
        self.exchange(f"CONFIG {len(self.rows)} 0 1 {HANDSHAKE_MS} {self.valve_ms} {self.valve_ms} {initial}",
                      "CONFIG_OK", len(self.rows))
        # CONFIG defaults to lick-gated Operant and disables D7 triggers.
        for row in self.rows:
            self.exchange(f"TRIAL {row['Trial']} {row['ITI_Duration_S'] - 1} 1", "TRIAL_OK", row["Trial"])
        self.recording.metadata["status"] = "ready"
        self.recording.save_metadata()
        print(f"Ready: {len(self.rows)} rewards, valve {self.valve_ms} ms. Type start (or 2) + Enter.", flush=True)
        print("stop / 4 = abort, q / quit = quit, Ctrl+C = stop. One session per run.", flush=True)

    def start(self):
        if self.started or self.done:
            return
        self.started = True
        self.recording.metadata["status"] = "running"
        self.recording.save_metadata()
        self.send("START")

    def poll(self):
        self.ping()
        for kind, value in self.read_events():
            if kind == "CUE_REQUEST":
                if not self.started or self.cue_trial is not None or value != self.current_trial:
                    raise RuntimeError("Unexpected internal cue request")
                self.send(f"CUE_ON {value}")
                self.cue_trial = value
                self.cue_off_at = self.clock() + .001
            elif kind == "TRIAL_START":
                self.current_trial = value
            elif kind == "REWARD_ON":
                self.recording.metadata["delivered_rewards"] = value
                self.recording.save_metadata()
                print(f"REWARD_ON: {value}/{len(self.rows)}", flush=True)
            elif kind == "TRIAL_END":
                self.completed_rewards = value
                self.recording.metadata["completed_rewards"] = value
                self.recording.save_metadata()
                print(f"REWARD_CONSUMED: {value}/{len(self.rows)} (post-reward lick detected)", flush=True)
            elif kind == "ITI_START":
                seconds = self.rows[value - 1]["ITI_Duration_S"]
                print(f"ITI_START: next reward {value}, target water in {seconds} s", flush=True)
            elif kind == "SESSION_END":
                self.done = True
                self.recording.metadata.update(status="completed", completed_rewards=value, end_reason="reward_count")
                self.recording.save_metadata()
                print(f"SESSION_END: {value} rewards completed", flush=True)
            elif kind == "SESSION_ABORTED":
                raise RuntimeError(f"Arduino aborted: reason {value}")
            elif kind == "READY" and self.started:
                raise RuntimeError("Arduino reset during habituation")
            elif kind in ("SESSION_START", "REWARD_OFF", "WAIT_LICK", "LICK"):
                print(f"{kind}: {value}", flush=True)
        if self.cue_off_at is not None and self.clock() >= self.cue_off_at:
            self.send(f"CUE_OFF {self.cue_trial}")
            self.cue_trial = self.cue_off_at = None
        if self.clock() - self.last_received > 2:
            raise TimeoutError("Arduino response timeout")

    def stop(self, reason):
        self.send("STOP")
        self.recording.event("HOST_ABORT", reason)
        self.done = True
        self.recording.metadata.update(status="aborted", abort_reason=reason,
                                       completed_rewards=self.completed_rewards)
        self.recording.save_metadata()


def read_terminal(stream, commands):
    while True:
        line = stream.readline()
        commands.put(line.strip().lower() if line else "quit")
        if not line:
            return


def main(argv=None):
    parser = argparse.ArgumentParser(description="Water habituation: reward -> lick -> ITI -> next reward; current Uno firmware")
    parser.add_argument("--port", "--com", default="/dev/ttyACM0")
    parser.add_argument("--mouse-id", "--mice", default="mouse01")
    parser.add_argument("--schedule", type=Path, help="Optional reference habituation CSV (Reward,ITI_Duration_S)")
    parser.add_argument("--outdir", type=Path, default=Path("data/habituation"))
    parser.add_argument("--rewards", type=int, default=80)
    parser.add_argument("--valve-ms", type=int, default=30)
    parser.add_argument("--initial-iti-s", type=int, default=90)
    parser.add_argument("--iti-min-s", type=int, default=10)
    parser.add_argument("--iti-max-s", type=int, default=20)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--simulate", action="store_true", help="Synthetic board and licks; no USB or physical outputs")
    parser.add_argument("--autostart", action="store_true", help="Start immediately, including on real hardware")
    args = parser.parse_args(argv)
    if not 1 <= args.rewards <= 200 or not 1 <= args.valve_ms <= 1000:
        parser.error("--rewards must be 1..200 and --valve-ms 1..1000")
    if not 1 <= args.initial_iti_s <= 65535 or not 1 <= args.iti_min_s <= args.iti_max_s <= 65535:
        parser.error("ITI durations must be 1..65535 s with min <= max")
    # Validate all schedule data before opening USB.
    try:
        rows, seed = make_schedule(args)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    recording = board = app = None
    result = 0
    try:
        config = dict(session=dict(task="habituation", trials=args.rewards, valve_open_ms=args.valve_ms,
                     initial_iti_s=args.initial_iti_s, iti_min_s=args.iti_min_s, iti_max_s=args.iti_max_s),
                      serial=dict(port=args.port, baud=115200))
        recording = SessionLog(args.outdir, args.mouse_id, config, rows, seed, args.simulate)
        recording.metadata.update(task="habituation", delivered_rewards=0, completed_rewards=0,
            trial_end_rule="post_reward_lick_and_valve_closed", source_schedule=str(args.schedule) if args.schedule else None,
            internal_handshake=dict(cue_delay_ms=0, cue_duration_ms=1, reward_at_ms=HANDSHAKE_MS,
                                    firmware_iti_seconds_subtracted=1, display_used=False,
                                    D7_triggers=False, D9_note="Internal CUE_ON/OFF acknowledgments also pulse D9"))
        recording.save_metadata()
        if args.simulate:
            from .simulated_board import SimulatedBoard
            board = SimulatedBoard()
            print("SIMULATION: synthetic rewards and licks, no hardware connected", flush=True)
        else:
            from .transport import SerialBoard
            board = SerialBoard(args.port)
            time.sleep(2.2)
        print(f"Session records: {recording.path}", flush=True)
        app = Habituation(board, recording, rows, args.valve_ms)
        app.prepare()
        commands = queue.SimpleQueue()
        if args.autostart:
            app.start()
        if not args.autostart or sys.stdin.isatty():
            threading.Thread(target=read_terminal, args=(sys.stdin, commands), daemon=True).start()
        while not app.done:
            while not commands.empty() and not app.done:
                command = commands.get_nowait()
                if command in ("start", "2"):
                    app.start()
                elif command in ("stop", "4", "q", "quit"):
                    if app.started:
                        app.stop("operator terminal command")
                        result = 1
                    else:
                        app.done = True
                        recording.metadata["status"] = "cancelled"
                        recording.save_metadata()
                elif command:
                    print("Type start / 2 to begin, stop / 4 to abort, q to quit", flush=True)
            if not app.done:
                app.poll()
                time.sleep(.002)
    except (Exception, KeyboardInterrupt) as error:
        result = 1
        if board:
            try:
                board.write_line("STOP")
            except Exception:
                pass
        print(f"Stopped: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        if recording:
            recording.event("HOST_ERROR", f"{type(error).__name__}: {error}")
            recording.metadata.update(status="aborted" if isinstance(error, KeyboardInterrupt) else "failed",
                                       error=str(error))
            recording.save_metadata()
    finally:
        if board:
            try:
                if recording is None or recording.metadata["status"] != "completed":
                    board.write_line("STOP")
                    deadline = time.monotonic() + .5
                    while time.monotonic() < deadline:
                        replies = app.read_events() if app else []
                        if ("SESSION_ABORTED", 1) in replies:
                            break
                        time.sleep(.005)
            except Exception as error:
                print(f"STOP cleanup: {error}", file=sys.stderr, flush=True)
            finally:
                try:
                    board.close()
                except Exception as error:
                    print(f"Serial close: {error}", file=sys.stderr, flush=True)
        if recording:
            recording.close()
    return result
