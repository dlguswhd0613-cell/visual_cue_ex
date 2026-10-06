"""Pi display, session supervision and event recording."""

import argparse
import copy
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from .config import DEFAULT_CONFIG, configuration_command, load_config, validate_config
from .recording import SessionLog
from .schedule import generate_schedule, load_schedule
from .stimulus import make_gabor


def parse_event(line):
    parts = line.split(",")
    if len(parts) != 3:
        raise ValueError(f"Unexpected Arduino protocol line: {line!r}; upload the visual-task firmware")
    timestamp, event, value = parts
    if not timestamp.isdigit() or not event or not value.lstrip("-").isdigit():
        raise ValueError(f"Invalid Arduino event: {line!r}")
    return int(timestamp), event, int(value)


class Experiment:
    def __init__(self, config, board, recording, rows, windowed=False):
        import pygame
        self.pg = pygame
        self.config = config
        self.board = board
        self.recording = recording
        self.rows = rows
        self.started = False
        self.active = False
        self.done = False
        self.cue_on_ns = None
        self.cue_trial = None
        self.last_received = time.monotonic()
        self.last_ping = 0.0
        self.gray = config["display"]["background_gray"]
        pygame.display.init()
        display = config["display"]
        sizes = pygame.display.get_desktop_sizes()
        index = display["screen_index"]
        if index >= len(sizes):
            raise ValueError(f"Display {index} not found; available: {len(sizes)}")
        fullscreen = display["fullscreen"] and not windowed
        size = sizes[index] if fullscreen else (display["window_width"], display["window_height"])
        if config["stimulus"]["diameter_px"] > min(size):
            raise ValueError(f"Gabor diameter exceeds display size {size}; reduce diameter_px")
        flags = pygame.FULLSCREEN if fullscreen else 0
        # SCALED requests SDL vsync. Native resolution preserves physical pixel size.
        # The dummy driver used by CI has no hardware renderer or vsync.
        self.vsync_requested = pygame.display.get_driver() != "dummy"
        if self.vsync_requested:
            flags |= pygame.SCALED
        self.screen = pygame.display.set_mode(size, flags, display=index, vsync=int(self.vsync_requested))
        pygame.display.set_caption("Visual cue experiment")
        pygame.mouse.set_visible(False)
        self.show_gray()
        pixels = make_gabor(**config["stimulus"], background_gray=self.gray)
        self.texture = pygame.surfarray.make_surface(pixels.swapaxes(0, 1)).convert()
        self.target = self.texture.get_rect(center=self.screen.get_rect().center)
        self.recording.metadata["display"] = {"resolution": list(self.screen.get_size()),
            "driver": pygame.display.get_driver(), "vsync_requested": self.vsync_requested,
            "timing_note": "DISPLAY_ON/OFF timestamps are software flip returns, not measured photons"}
        self.recording.save_metadata()

    def show_gray(self):
        self.screen.fill((self.gray,) * 3)
        self.pg.display.flip()
        return time.monotonic_ns()

    def send(self, command):
        self.board.write_line(command)
        if command != "PING":
            self.recording.event("COMMAND", command)

    def ping(self):
        if time.monotonic() - self.last_ping >= .5:
            self.send("PING")
            self.last_ping = time.monotonic()

    def read_events(self):
        result = []
        failure = None
        for line in self.board.read_lines():
            if not line:
                continue
            try:
                timestamp, event, value = parse_event(line)
            except ValueError as error:
                self.recording.event("INVALID_SERIAL_LINE", line)
                failure = error
                continue
            self.last_received = time.monotonic()
            if event != "PONG":
                self.recording.event(event, value, timestamp, "arduino")
            if event == "ERROR":
                failure = RuntimeError(f"Arduino ERROR {value}; see firmware protocol comments")
            result.append((timestamp, event, value))
        if failure:
            raise failure
        return result

    def exchange(self, command, expected, value, timeout=3):
        self.send(command)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for event in self.pg.event.get():
                if event.type == self.pg.QUIT or (event.type == self.pg.KEYDOWN and event.key in (self.pg.K_ESCAPE, self.pg.K_q)):
                    raise KeyboardInterrupt
            self.ping()
            for _, kind, actual in self.read_events():
                if kind == "SESSION_ABORTED":
                    raise RuntimeError(f"Arduino aborted during configuration: {actual}")
                if kind == expected and actual == value:
                    return
            time.sleep(.005)
        raise TimeoutError(f"No {expected},{value} acknowledgment for {command!r}")

    def prepare(self, simulated=False):
        # The Uno resets on serial open; keep the display gray during boot.
        if not simulated:
            deadline = time.monotonic() + 2.2
            while time.monotonic() < deadline:
                for event in self.pg.event.get():
                    if event.type == self.pg.QUIT or (event.type == self.pg.KEYDOWN and event.key in (self.pg.K_ESCAPE, self.pg.K_q)):
                        raise KeyboardInterrupt
                time.sleep(.01)
        self.exchange("HELLO", "READY", 1)
        self.exchange(configuration_command(self.config), "CONFIG_OK", len(self.rows))
        for row in self.rows:
            self.exchange(f"TRIAL {row['Trial']} {row['ITI_Duration_S']} {row['Rewarded']}", "TRIAL_OK", row["Trial"])
        self.recording.metadata["status"] = "ready"
        self.recording.save_metadata()
        print("Ready. SPACE=start, ESC=abort to gray, Q=quit. One session per run.", flush=True)

    def start(self):
        if self.started:
            return
        self.started = self.active = True
        self.recording.metadata["status"] = "running"
        self.recording.save_metadata()
        self.send("START")

    def abort(self, reason):
        # Stop physical outputs before any possibly blocking display or disk operation.
        self.board.write_line("STOP")
        self.show_gray()
        self.cue_on_ns = None
        self.recording.event("COMMAND", "STOP")
        self.recording.event("HOST_ABORT", reason)
        self.active = False
        self.started = self.done = True
        self.recording.metadata["status"] = "aborted"
        self.recording.metadata["abort_reason"] = reason
        self.recording.save_metadata()

    def handle_event(self, kind, value):
        if kind == "CUE_REQUEST":
            if not self.active or self.cue_on_ns is not None:
                raise RuntimeError("Unexpected cue request")
            self.screen.fill((self.gray,) * 3)
            self.screen.blit(self.texture, self.target)
            self.pg.display.flip()
            self.cue_on_ns = time.monotonic_ns()
            self.cue_trial = value
            self.send(f"CUE_ON {value}")
            self.recording.event("DISPLAY_ON", value, at_ns=self.cue_on_ns)
        elif kind in ("SESSION_END", "SESSION_ABORTED"):
            self.show_gray()
            self.cue_on_ns = None
            self.active = False
            self.done = True
            self.recording.metadata["status"] = "completed" if kind == "SESSION_END" else "aborted"
            self.recording.save_metadata()
            print(f"{kind}: {value}. Gray screen remains until Q.", flush=True)
        elif kind == "READY" and self.started:
            raise RuntimeError("Arduino reset during session")
        elif kind in ("TRIAL_START", "TRIAL_END", "REWARD_ON"):
            print(f"{kind}: {value}", flush=True)

    def update_cue(self):
        if self.cue_on_ns is None:
            return
        duration_ms = self.config["session"]["cue_duration_ms"]
        if time.monotonic_ns() - self.cue_on_ns < duration_ms * 1_000_000:
            return
        off_ns = self.show_gray()
        elapsed_ms = (off_ns - self.cue_on_ns) / 1_000_000
        self.recording.event("DISPLAY_OFF", self.cue_trial, at_ns=off_ns)
        self.recording.event("CUE_ELAPSED_MS", f"{elapsed_ms:.3f}")
        self.cue_on_ns = None
        if elapsed_ms - duration_ms > self.config["display"]["max_cue_overrun_ms"]:
            self.abort(f"Cue display overrun: {elapsed_ms:.3f} ms")
            return
        self.send(f"CUE_OFF {self.cue_trial}")

    def run(self, autostart=False, exit_when_done=False):
        if autostart:
            self.start()
        timer = self.pg.time.Clock()
        while True:
            for event in self.pg.event.get():
                if event.type == self.pg.QUIT or (event.type == self.pg.KEYDOWN and event.key == self.pg.K_q):
                    if self.active:
                        self.abort("window closed")
                    return
                if event.type == self.pg.KEYDOWN:
                    if event.key == self.pg.K_SPACE:
                        self.start()
                    elif event.key == self.pg.K_ESCAPE:
                        self.abort("operator pressed ESC")
                if event.type == self.pg.WINDOWFOCUSLOST and self.active:
                    self.abort("stimulus window lost focus")
            self.ping()
            for _, kind, value in self.read_events():
                self.handle_event(kind, value)
            self.update_cue()
            if time.monotonic() - self.last_received > 2.0:
                raise TimeoutError("Arduino response timeout; stopping session")
            if self.done and exit_when_done:
                return
            timer.tick(240)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Raspberry Pi visual cue task + Arduino CSV recording")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--port", "--com", dest="port", help="Uno USB serial port, e.g. /dev/ttyACM0 or COM3")
    parser.add_argument("--mouse-id", "--mice", dest="mouse_id", default="mouse01")
    parser.add_argument("--outdir", type=Path, default=Path("data"))
    parser.add_argument("--schedule", type=Path)
    parser.add_argument("--simulate", action="store_true", help="Use simulated Arduino; no hardware commands")
    parser.add_argument("--demo", action="store_true", help="Simulation only: 3 trials, initial delay 0, ITI 1 s")
    parser.add_argument("--autostart", action="store_true", help="Simulation only: start without SPACE")
    parser.add_argument("--exit-when-done", action="store_true")
    parser.add_argument("--windowed", action="store_true")
    args = parser.parse_args(argv)
    if (args.demo or args.autostart) and not args.simulate:
        parser.error("--demo and --autostart require --simulate")
    if args.demo and args.schedule:
        parser.error("--demo creates its own schedule; omit --schedule")
    board = recording = app = None
    exit_code = 0
    try:
        config = copy.deepcopy(load_config(args.config))
        if args.port:
            config["serial"]["port"] = args.port
        if args.demo:
            config["session"].update(trials=3, initial_iti_s=0, iti_min_s=1, iti_max_s=1)
        validate_config(config)
        if args.schedule:
            rows, seed = load_schedule(args.schedule, config["session"]), None
        else:
            rows, seed = generate_schedule(config["session"])
        recording = SessionLog(args.outdir, args.mouse_id, config, rows, seed, args.simulate)
        if args.simulate:
            from .simulated_board import SimulatedBoard
            board = SimulatedBoard()
            print("SIMULATION: no Arduino connected; synthetic lick events.", flush=True)
        else:
            from .transport import SerialBoard
            board = SerialBoard(config["serial"]["port"], config["serial"]["baud"])
        app = Experiment(config, board, recording, rows, args.windowed)
        print(f"Session records: {recording.path}", flush=True)
        app.prepare(simulated=args.simulate)
        app.run(args.autostart, args.exit_when_done)
        if not app.started:
            recording.metadata["status"] = "cancelled"
            recording.save_metadata()
        if recording.metadata["status"] == "aborted":
            exit_code = 1
    except (Exception, KeyboardInterrupt) as error:
        exit_code = 1
        if board:
            try:
                board.write_line("STOP")
            except Exception:
                pass
        print(f"Stopped: {type(error).__name__}: {error}", file=sys.stderr)
        if recording:
            recording.event("HOST_ERROR", f"{type(error).__name__}: {error}")
            recording.metadata["status"] = "failed"
            recording.metadata["error"] = str(error)
            recording.save_metadata()
    finally:
        needs_stop = board is not None and (recording is None or recording.metadata["status"] != "completed")
        if needs_stop:
            try:
                board.write_line("STOP")
            except Exception:
                pass
        if app:
            try:
                app.show_gray()
            except Exception:
                pass
        if board:
            try:
                # Confirm safe stop before closing USB. Firmware watchdog also handles crashes.
                deadline = time.monotonic() + (.5 if needs_stop else .02)
                acknowledged = False
                while time.monotonic() < deadline:
                    lines = board.read_lines()
                    for line in lines:
                        try:
                            timestamp, event, value = parse_event(line)
                            if recording and event != "PONG":
                                recording.event(event, value, timestamp, "arduino")
                            acknowledged |= event == "SESSION_ABORTED"
                        except ValueError:
                            if recording:
                                recording.event("INVALID_SERIAL_LINE", line)
                    if acknowledged:
                        break
                    time.sleep(.01)
            except Exception:
                pass
            finally:
                board.close()
        if recording:
            recording.close()
        if "pygame" in sys.modules:
            sys.modules["pygame"].quit()
    return exit_code
