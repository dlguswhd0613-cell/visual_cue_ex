"""Hardware-free serial peer for the Pi display demo.

This is a model for exercising the host program, not an emulator or a test of
the Arduino firmware. It never opens a serial port or drives physical outputs.
Durations use real monotonic time unless a caller supplies a clock for tests.
"""

from __future__ import annotations

from collections import deque
import time
from typing import Callable

SESSION_LIMIT_MS = 3_600_000


class SimulatedBoard:
    """Implement the same line transport interface as the USB serial peer."""

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 simulate_licks: bool = True) -> None:
        self._clock = clock
        self._origin = clock()
        self._lines: deque[str] = deque()
        self._config: tuple[int, ...] | None = None
        self._trials: dict[int, tuple[int, bool]] = {}
        self._state = "idle"
        self._deadline: int | None = None
        self._trial = 0
        self._trial_started = 0
        self._blink = 0
        self._lick_count = 0
        self._last_ping = 0
        self._simulate_licks = simulate_licks
        self._auto_lick_at: int | None = None
        self._reward_lick = False
        self._last_lick_at = -50
        self._session_deadline: int | None = None
        self._session_timed_out = False
        self._completed_trials = 0
        self._triggers: tuple[int, int, int] | None = None
        self._trigger_edges: dict[str, int] = {}
        self.cue_trigger_on = False
        self.reward_trigger_on = False
        self._trigger_low_since = self._now()
        self.valve_on = False
        self.closed = False
        self._emit("READY", 1)

    def _now(self) -> int:
        return round((self._clock() - self._origin) * 1000)

    def _emit(self, event: str, value: int | str, at: int | None = None) -> None:
        self._lines.append(f"{self._now() if at is None else at},{event},{value}")

    def write_line(self, line: str) -> None:
        if self.closed:
            raise RuntimeError("Simulated board is closed")
        self._tick()
        parts = line.strip().split()
        if not parts:
            return
        command = parts[0]
        if len(line.strip()) > 95:
            self._error(5)
            return
        if command in ("HELLO", "LICK_END_CAPS", "SESSION_LIMIT_CAPS", "PING", "STOP", "START") and len(parts) == 1:
            if command in ("HELLO", "LICK_END_CAPS", "SESSION_LIMIT_CAPS"):
                if self._state != "idle":
                    self._error(3)
                else:
                    self._emit("READY" if command == "HELLO" else command,
                               SESSION_LIMIT_MS // 1000 if command == "SESSION_LIMIT_CAPS" else 1)
            elif command == "PING":
                self._last_ping = self._now()
                self._emit("PONG", 1)
            elif command == "STOP":
                self._stop()
            else:
                self._start()
            return
        try:
            if any(not token.isascii() or not token.isdigit() for token in parts[1:]):
                raise ValueError
            values = tuple(int(token) for token in parts[1:])
            if any(value > 4294967295 for value in values):
                raise ValueError
        except ValueError:
            self._error(1)
            return
        if command == "CONFIG":
            self._configure(values)
        elif command == "TRIGGERS":
            self._configure_triggers(values)
        elif command == "TRIAL":
            self._load_trial(values)
        elif command in ("CUE_ON", "CUE_OFF") and len(values) == 1:
            self._cue_ack(command, values[0])
        else:
            self._error(1)

    def _error(self, code: int) -> None:
        self._emit("ERROR", code)
        if self._state != "idle":
            self._stop(5)

    def _configure(self, values: tuple[int, ...]) -> None:
        bounds = ((1, 200), (0, 60000), (1, 60000), (1, 60000),
                  (1, 60000), (1, 1000), (0, 65535))
        if self._state != "idle":
            self._error(3)
        elif len(values) != len(bounds):
            self._error(1)
        elif any(
            not low <= value <= high
            for value, (low, high) in zip(values, bounds)
        ) or values[3] <= values[1] + values[2] or values[4] < values[5]:
            self._error(2)
        else:
            self._config = values
            self._triggers = None
            self._trials.clear()
            self._emit("CONFIG_OK", values[0])

    def _configure_triggers(self, values: tuple[int, ...]) -> None:
        if self._state != "idle":
            self._error(3)
        elif len(values) != 3:
            self._error(1)
        elif self._config is None:
            self._error(4)
        elif (values[0] > self._config[1]
              or values[1] > self._config[3] - self._config[1] - self._config[2]
              or not 1 <= values[2] <= 1000
              or values[2] >= (self._config[3] - values[1]) - (self._config[1] - values[0])):
            self._error(2)
        else:
            self._triggers = values
            self._emit("TRIGGERS_OK", 2)

    @property
    def trigger_on(self) -> bool:
        """Shared D7 logic level for both cue and reward markers."""
        return self.cue_trigger_on or self.reward_trigger_on

    def _schedule_trigger(self, kind: str, at: int) -> None:
        assert self._triggers is not None
        self._trigger_edges[f"{kind}_TRIGGER_ON"] = at
        self._trigger_edges[f"{kind}_TRIGGER_OFF"] = at + self._triggers[2]

    def _clear_triggers(self, at: int | None = None) -> None:
        self._trigger_edges.clear()
        self.cue_trigger_on = self.reward_trigger_on = False
        self._trigger_low_since = self._now() if at is None else at

    def _load_trial(self, values: tuple[int, ...]) -> None:
        if self._state != "idle":
            self._error(3)
        elif len(values) != 3:
            self._error(1)
        elif self._config is None:
            self._error(4)
        else:
            index, iti_s, reward = values
            if index != len(self._trials) + 1 or index > self._config[0]:
                self._error(4)
                return
            if not (0 <= iti_s <= 65535 and reward in (0, 1)):
                self._error(2)
                return
            self._trials[index] = (iti_s, bool(reward))
            self._emit("TRIAL_OK", index)

    def _start(self) -> None:
        if self._state != "idle":
            self._error(3)
            return
        if self._config is None or len(self._trials) != self._config[0]:
            self._error(4)
            return
        self._trial = 1
        self._completed_trials = 0
        self._session_timed_out = False
        self._session_deadline = self._now() + SESSION_LIMIT_MS
        self._blink = 0
        self._lick_count = 0
        self._last_lick_at = self._now() - 50
        self._reward_lick = False
        self._auto_lick_at = None
        self._state = "marker_off"
        self._deadline = self._now() + 500
        self._last_ping = self._now()
        self._emit("SESSION_START", self._config[0])

    def _cue_ack(self, command: str, index: int) -> None:
        if self._state == "idle" and self._session_timed_out:
            return
        expected = "cue_requested" if command == "CUE_ON" else "cue_on"
        if self._state != expected or index != self._trial:
            self._error(6)
            return
        self._emit(command, index)
        if command == "CUE_ON":
            self._state = "cue_on"
            assert self._config is not None
            self._deadline = self._now() + self._config[2] + 1000
        else:
            assert self._config is not None
            self._state = "delay"
            # Reward is anchored to TRIAL_START, while receiving this display-
            # OFF acknowledgement remains a prerequisite for opening the valve.
            self._deadline = self._trial_started + self._config[3]
            if self._triggers is not None and self._trials[self._trial][1]:
                self._schedule_trigger("REWARD", max(self._now(), self._deadline - self._triggers[1]))

    def _start_iti(self, at: int) -> None:
        assert self._config is not None
        iti_s = self._config[6] if self._trial == 1 else self._trials[self._trial][0]
        self._state = "iti"
        self._deadline = at + iti_s * 1000
        self._emit("ITI_START", self._trial, at)
        self._emit("ITI_DURATION_S", iti_s, at)

    def _finish_trial(self, at: int) -> None:
        assert self._config is not None
        self._clear_triggers(at)
        self._auto_lick_at = None
        self._completed_trials += 1
        self._emit("TRIAL_END", self._trial, at)
        if self._trial == self._config[0]:
            self._session_deadline = None
            self._state = "idle"
            self._deadline = None
            self._emit("SESSION_END", self._trial, at)
        else:
            self._trial += 1
            self._start_iti(at)

    def inject_lick(self) -> None:
        """Inject a rising sensor edge in simulation; never sends a hardware command."""
        if self.closed:
            raise RuntimeError("Simulated board is closed")
        self._tick()
        self._record_lick(self._now())

    def _record_lick(self, at: int) -> None:
        if at - self._last_lick_at < 50:
            return
        self._last_lick_at = at
        self._lick_count += 1
        self._emit("LICK", self._lick_count, at)
        if self._state in ("valve", "wait_lick"):
            self._reward_lick = True
            if self._state == "wait_lick":
                self._finish_trial(at)

    def _tick(self) -> None:
        if self.closed:
            return
        now = self._now()
        limit_due = self._session_deadline is not None and now >= self._session_deadline
        if not limit_due and self._state != "idle" and now - self._last_ping >= 2000:
            self._stop(2)
            return
        if not limit_due and self._state in ("cue_requested", "cue_on"):
            assert self._config is not None
            if now >= self._trial_started + self._config[3]:
                self._stop(7)
                return
        while True:
            pending = [when for when in (self._deadline, self._auto_lick_at, self._session_deadline)
                       if when is not None]
            pending.extend(self._trigger_edges.values())
            if not pending or min(pending) > now:
                break
            at = min(pending)
            if at == self._session_deadline:
                self.valve_on = False
                self._clear_triggers(at)
                self._session_deadline = None
                self._session_timed_out = True
                self._state = "idle"
                self._deadline = self._auto_lick_at = None
                self._config = None
                self._trials.clear()
                self._reward_lick = False
                self._emit("SESSION_TIME_LIMIT", self._completed_trials, at)
                self._emit("SESSION_END", self._completed_trials, at)
                return
            edges = [name for name, when in self._trigger_edges.items() if when == at]
            if edges:
                for name in edges:
                    del self._trigger_edges[name]
                    if name.endswith("_ON"):
                        if self.trigger_on or at - self._trigger_low_since < 1:
                            self._stop(8)
                            return
                    else:
                        self._trigger_low_since = at
                    if name.startswith("CUE_"):
                        self.cue_trigger_on = name.endswith("_ON")
                    else:
                        self.reward_trigger_on = name.endswith("_ON")
                    self._emit(name, self._trial, at)
                continue
            if self._auto_lick_at == at:
                self._auto_lick_at = None
                self._record_lick(at)
                continue
            assert self._config is not None
            if self._state == "marker_on":
                self._emit("LED_OFF", self._blink, at)
                if self._blink == 3:
                    self._start_iti(at)
                else:
                    self._state = "marker_off"
                    self._deadline = at + 500
            elif self._state == "marker_off":
                self._blink += 1
                self._emit("LED_ON", self._blink, at)
                self._state = "marker_on"
                self._deadline = at + 500
            elif self._state == "iti":
                self._reward_lick = False
                self._trial_started = at
                self._emit("TRIAL_START", self._trial, at)
                self._state = "cue_lead"
                self._deadline = at + self._config[1]
                if self._triggers is not None:
                    self._schedule_trigger("CUE", self._deadline - self._triggers[0])
            elif self._state == "cue_lead":
                self._emit("CUE_REQUEST", self._trial, at)
                self._state = "cue_requested"
                self._deadline = at + 100
            elif self._state == "cue_requested":
                self._stop(3)
            elif self._state == "cue_on":
                self._stop(4)
            elif self._state == "delay":
                if self._trials[self._trial][1]:
                    self._reward_lick = False
                    self.valve_on = True
                    self._emit("REWARD_ON", self._trial, at)
                    self._state = "valve"
                    self._deadline = at + self._config[5]
                else:
                    self._emit("NO_REWARD", self._trial, at)
                    self._state = "post_reward"
                    self._deadline = self._trial_started + self._config[3] + self._config[4]
            elif self._state == "valve":
                self.valve_on = False
                self._emit("REWARD_OFF", self._trial, at)
                if self._reward_lick:
                    self._finish_trial(at)
                else:
                    self._state = "wait_lick"
                    self._deadline = None
                    self._emit("WAIT_LICK", self._trial, at)
                    if self._simulate_licks:
                        self._auto_lick_at = at + 100
            elif self._state == "post_reward":
                self._finish_trial(at)
            else:
                raise RuntimeError(f"Unknown simulator state: {self._state}")

    def _stop(self, reason: int = 1) -> None:
        self.valve_on = False
        self._session_deadline = None
        self._reward_lick = False
        self._clear_triggers()
        self._triggers = None
        self._state = "idle"
        self._deadline = None
        self._auto_lick_at = None
        self._config = None
        self._trials.clear()
        self._emit("SESSION_ABORTED", reason)

    def read_lines(self) -> list[str]:
        self._tick()
        lines = list(self._lines)
        self._lines.clear()
        return lines

    def close(self) -> None:
        """Cancel every future transition, including any synthetic lick."""
        if not self.closed:
            self._stop()
            self.closed = True
