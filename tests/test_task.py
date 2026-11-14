import csv
import tempfile
import unittest
from pathlib import Path

from visualcue.config import configuration_command, load_config, photometry_command, validate_config
from visualcue.recording import SessionLog
from visualcue.runner import Experiment, parse_event
from visualcue.schedule import generate_schedule, load_schedule, save_schedule


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_requested_timeline_and_all_rewarded_schedule(self):
        config = self.config
        session = config["session"]
        self.assertEqual(configuration_command(config), "CONFIG 100 1000 2000 6000 4000 30 90")
        self.assertEqual(session["cue_duration_ms"], 2000)
        self.assertEqual(session["reward_at_ms"] - session["cue_delay_ms"]
                         - session["cue_duration_ms"], 3000)
        rows, seed = generate_schedule(session, 123)
        self.assertEqual(seed, 123)
        self.assertEqual(len(rows), 100)
        self.assertEqual(rows[0], {"Trial": 1, "ITI_Duration_S": 90, "Rewarded": 1})
        self.assertTrue(all(row["Rewarded"] == 1 for row in rows))
        self.assertTrue(all(10 <= row["ITI_Duration_S"] <= 20 for row in rows[1:]))
        self.assertEqual(session["iti_distribution"], "exponential")

    def test_truncated_exponential_distribution(self):
        import math
        from collections import Counter
        session = dict(self.config["session"], trials=20001)
        rows, _ = generate_schedule(session, 123)
        counts = Counter(row["ITI_Duration_S"] for row in rows[1:])
        self.assertEqual(set(counts), set(range(10, 21)))
        weights = {k: math.exp(-(k - 10) / 3) for k in range(10, 21)}
        total = sum(weights.values())
        for k, weight in weights.items():
            self.assertAlmostEqual(counts[k] / 20000, weight / total, delta=.01)
        self.assertGreater(counts[10], counts[15])
        self.assertGreater(counts[15], counts[20])

    def test_legacy_uniform_and_fixed_schedules(self):
        import random
        session = dict(self.config["session"], iti_min_s=10, iti_max_s=20)
        session.pop("iti_distribution")
        session.pop("iti_exponential_scale_s")
        rows, _ = generate_schedule(session, 123)
        rng = random.Random(123)
        self.assertEqual([r["ITI_Duration_S"] for r in rows[1:]],
                         [rng.randint(10, 20) for _ in rows[1:]])
        session.update(iti_distribution="exponential", iti_min_s=1, iti_max_s=1)
        rows, _ = generate_schedule(session, 123)
        self.assertTrue(all(r["ITI_Duration_S"] == 1 for r in rows[1:]))

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
                             ("task", "unknown"), ("task", 1), ("task", None),
                             ("cue_duration_ms", True), ("valve_open_ms", -1),
                             ("iti_distribution", "unknown"), ("iti_exponential_scale_s", 0),
                             ("iti_exponential_scale_s", True), ("iti_exponential_scale_s", float("nan"))):
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

    def test_photometry_defaults_and_legacy_configs(self):
        self.assertEqual(photometry_command(self.config), "TRIGGERS 100 100 20")
        self.config["photometry"]["enabled"] = False
        validate_config(self.config)
        self.assertIsNone(photometry_command(self.config))
        del self.config["photometry"]
        validate_config(self.config)
        self.assertIsNone(photometry_command(self.config))

    def test_invalid_photometry_timing_rejected_before_hardware(self):
        for field, value in (("enabled", 1), ("cue_lead_ms", 1001),
                             ("reward_lead_ms", 3001), ("cue_lead_ms", -1),
                             ("pulse_ms", 0), ("pulse_ms", 1001), ("pulse_ms", True)):
            with self.subTest(field=field, value=value):
                config = load_config()
                config["photometry"][field] = value
                with self.assertRaises(ValueError):
                    validate_config(config)

    def test_shared_trigger_requires_low_gap(self):
        self.config["session"].update(cue_duration_ms=10, reward_at_ms=2000)
        self.config["photometry"].update(cue_lead_ms=0, reward_lead_ms=990, pulse_ms=10)
        with self.assertRaises(ValueError):
            validate_config(self.config)
        self.config["photometry"]["pulse_ms"] = 9
        validate_config(self.config)

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
