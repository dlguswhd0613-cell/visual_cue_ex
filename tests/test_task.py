import csv
import tempfile
import unittest
from pathlib import Path

from visualcue.config import configuration_command, load_config, validate_config
from visualcue.recording import SessionLog
from visualcue.runner import Experiment, parse_event
from visualcue.schedule import generate_schedule, load_schedule, save_schedule


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_requested_timeline_and_all_rewarded_schedule(self):
        config = self.config
        session = config["session"]
        self.assertEqual(configuration_command(config), "CONFIG 100 1000 2000 9000 4000 30 90")
        rows, seed = generate_schedule(session, 123)
        self.assertEqual(seed, 123)
        self.assertEqual(len(rows), 100)
        self.assertEqual(rows[0], {"Trial": 1, "ITI_Duration_S": 90, "Rewarded": 1})
        self.assertTrue(all(row["Rewarded"] == 1 for row in rows))
        self.assertTrue(all(row["ITI_Duration_S"] == 33 for row in rows[1:]))
        self.assertEqual(session["reward_at_ms"] + session["post_reward_ms"] + 33000, 46000)

    def test_seed_reuses_random_itis_when_requested(self):
        session = self.config["session"]
        session.update(iti_min_s=16, iti_max_s=46)
        a, _ = generate_schedule(session, 10)
        b, _ = generate_schedule(session, 10)
        c, _ = generate_schedule(session, 11)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_schedule_roundtrip_and_reject_wrong_first_iti(self):
        session = self.config["session"]
        rows, _ = generate_schedule(session)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.csv"
            save_schedule(path, rows)
            self.assertEqual(load_schedule(path, session), rows)
            with self.assertRaises(FileExistsError):
                save_schedule(path, rows)
            bad = Path(directory) / "bad.csv"
            rows[0]["ITI_Duration_S"] = 33
            save_schedule(bad, rows)
            with self.assertRaises(ValueError):
                load_schedule(bad, session)

    def test_invalid_timing_and_unknown_key_rejected(self):
        for field, value in (("reward_at_ms", 3000), ("post_reward_ms", 29), ("trials", 201),
                             ("cue_duration_ms", True), ("valve_open_ms", -1)):
            with self.subTest(field=field):
                config = load_config()
                config["session"][field] = value
                with self.assertRaises(ValueError):
                    validate_config(config)
        self.config["stimulus"]["spatial_frequncy"] = 12
        with self.assertRaises(ValueError):
            validate_config(self.config)

    def test_protocol_rejects_old_firmware_and_malformed_events(self):
        self.assertEqual(parse_event("9000,REWARD_ON,1"), (9000, "REWARD_ON", 1))
        for line in ("# old sketch", "Ready. Python controls this Arduino.", "x,LICK,1", "4,LICK,1,extra"):
            with self.assertRaises(ValueError):
                parse_event(line)

    def test_recording_labels_simulation_and_preserves_unique_sessions(self):
        rows, seed = generate_schedule(self.config["session"], 7)
        with tempfile.TemporaryDirectory() as directory:
            first = SessionLog(directory, "mouse01", self.config, rows, seed, True)
            first.event("DISPLAY_ON", 1, at_ns=12345)
            first.event("LICK", 2, arduino_ms=9400, source="arduino")
            first.close()
            second = SessionLog(directory, "mouse01", self.config, rows, seed, True)
            second.close()
            self.assertNotEqual(first.path, second.path)
            self.assertTrue(first.path.name.startswith("SIMULATED_"))
            with (first.path / "events.csv").open(newline="") as file:
                events = list(csv.DictReader(file))
            self.assertEqual(events[0]["Host_Monotonic_NS"], "12345")
            self.assertEqual(events[1]["Arduino_ms"], "9400")
            with self.assertRaises(ValueError):
                SessionLog(directory, "../escape", self.config, rows, seed, True)

    def test_abort_stops_board_before_a_slow_display_or_disk(self):
        from types import SimpleNamespace
        operations = []
        app = Experiment.__new__(Experiment)
        app.board = SimpleNamespace(write_line=lambda line: operations.append(line))
        app.show_gray = lambda: operations.append("display flip")
        app.recording = SimpleNamespace(event=lambda *a: operations.append("disk write"),
                                        metadata={}, save_metadata=lambda: None)
        app.abort("operator")
        self.assertEqual(operations[0], "STOP")
        self.assertFalse(app.active)

    def test_error_batch_preserves_abort_and_pending_lick_records(self):
        from types import SimpleNamespace
        recorded = []
        app = Experiment.__new__(Experiment)
        app.board = SimpleNamespace(read_lines=lambda: ["20,ERROR,6", "20,SESSION_ABORTED,5", "21,LICK,2"])
        app.recording = SimpleNamespace(event=lambda *args: recorded.append(args[0]))
        with self.assertRaises(RuntimeError):
            app.read_events()
        self.assertEqual(recorded, ["ERROR", "SESSION_ABORTED", "LICK"])


if __name__ == "__main__":
    unittest.main()
