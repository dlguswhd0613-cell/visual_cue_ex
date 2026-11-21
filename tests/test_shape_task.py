"""Balanced shape discrimination, shared drifting carrier and reward routing."""
import contextlib
import csv
import io
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from visualcue.config import load_config, validate_config
from visualcue.runner import Experiment, main
from visualcue.schedule import generate_schedule, load_schedule, save_schedule
from visualcue.stimulus import SquareGrating, square_geometry


class ShapeTaskTests(unittest.TestCase):
    def test_default_balanced_session_and_seeded_shuffle(self):
        config = load_config()
        rows, seed = generate_schedule(config["session"], 123)
        self.assertEqual(len(rows), 100)
        self.assertEqual(sum(r["Cue"] == "CS+" for r in rows), 50)
        self.assertEqual(sum(r["Cue"] == "CS-" for r in rows), 50)
        self.assertTrue(all(r["Rewarded"] == (r["Cue"] == "CS+") for r in rows))
        self.assertEqual(rows, generate_schedule(config["session"], seed)[0])
        self.assertNotEqual(rows, generate_schedule(config["session"], 124)[0])
        self.assertEqual(rows[0]["ITI_Duration_S"], 90)
        self.assertTrue(all(10 <= r["ITI_Duration_S"] <= 20 for r in rows[1:]))

    def test_schedule_roundtrip_and_reject_mismatched_labels_or_unbalanced_counts(self):
        session = load_config()["session"]
        with tempfile.TemporaryDirectory() as directory:
            rows, _ = generate_schedule(session, 1)
            path = Path(directory) / "valid.csv"
            save_schedule(path, rows)
            self.assertEqual(load_schedule(path, session), rows)
            rows[0]["Cue"] = "CS-" if rows[0]["Rewarded"] else "CS+"
            path = Path(directory) / "mismatched.csv"
            save_schedule(path, rows)
            with self.assertRaisesRegex(ValueError, "must be rewarded"):
                load_schedule(path, session)
            for row in rows:
                row.update(Rewarded=1, Cue="CS+")
            path = Path(directory) / "unbalanced.csv"
            save_schedule(path, rows)
            with self.assertRaisesRegex(ValueError, "equal CS"):
                load_schedule(path, session)
            for row in rows:
                del row["Cue"]
            path = Path(directory) / "old.csv"
            save_schedule(path, rows)
            with self.assertRaisesRegex(ValueError, "generate a new schedule"):
                load_schedule(path, session)

    def test_invalid_count_and_calibration_rejected(self):
        for section, key, value in (("session", "trials", 99),
                ("stimulus", "viewing_distance_cm", 0), ("stimulus", "visual_angle_deg", 180),
                ("stimulus", "screen_width_cm", float("nan")), ("stimulus", "contrast", True),
                ("stimulus", "temporal_frequency_hz", 30)):
            with self.subTest(key=key):
                config = load_config()
                config[section][key] = value
                with self.assertRaises(ValueError):
                    validate_config(config)

    def test_angle_equal_area_and_identical_carrier_in_both_shapes(self):
        settings = load_config()["stimulus"]
        geometry = square_geometry(settings)
        self.assertAlmostEqual(geometry["diagonal_cm"], 2 * 15 * math.tan(math.radians(10)))
        self.assertAlmostEqual(math.degrees(2 * math.atan(geometry["diagonal_cm"] / 30)), 20)
        self.assertAlmostEqual(geometry["side_px"] * math.sqrt(2), geometry["diagonal_px"])
        renderer = SquareGrating(settings, 0)
        a, b = renderer.coverage[1], renderer.coverage[0]
        self.assertAlmostEqual(a.sum() / b.sum(), 1, delta=.005)
        shared = (a == 1) & (b == 1)
        for elapsed in (0, .1, .5):
            plus, minus = renderer.frame(1, elapsed), renderer.frame(0, elapsed)
            np.testing.assert_array_equal(plus[shared], minus[shared])
            self.assertTrue(np.all(plus[a == 0] == 0))
            self.assertTrue(np.all(minus[b == 0] == 0))
        square_width = np.count_nonzero(np.any(b > 0, axis=0))
        diamond_width = np.count_nonzero(np.any(a > 0, axis=0))
        self.assertAlmostEqual(diamond_width / square_width, math.sqrt(2), delta=.02)

    def test_grating_moves_down_and_repeats_at_requested_frequency(self):
        s = load_config()["stimulus"]
        renderer = SquareGrating(s, 0)
        first = renderer.frame(1, 0)
        after = renderer.frame(1, .05)
        np.testing.assert_array_equal(first, renderer.frame(1, 1 / s["temporal_frequency_hz"]))
        self.assertFalse(np.array_equal(first, after))
        x = first.shape[1] // 2
        y_before = np.argmax(first[:, x, 0])
        y_after = np.argmax(after[:, x, 0])
        self.assertGreater(y_after, y_before)

    def test_both_task_modes_route_cues_rewards_ttls_and_end_unrewarded_trials(self):
        for task in ("operant", "pavlovian"):
            with self.subTest(task=task), tempfile.TemporaryDirectory() as directory:
                config = load_config()
                config["session"].update(task=task, trials=4, seed=123, initial_iti_s=0,
                    iti_min_s=0, iti_max_s=0, cue_delay_ms=100, cue_duration_ms=100,
                    reward_at_ms=500, post_reward_ms=100, valve_open_ms=10)
                config["photometry"].update(cue_lead_ms=50, reward_lead_ms=50)
                path = Path(directory) / "config.json"
                path.write_text(json.dumps(config))
                output = io.StringIO()
                seen = {}
                frames = []
                original = Experiment.handle_event
                original_frame = SquareGrating.frame

                def capture_frame(renderer, rewarded, elapsed):
                    frames.append(elapsed)
                    return original_frame(renderer, rewarded, elapsed)

                def capture_display(app, kind, value):
                    original(app, kind, value)
                    if kind == "CUE_REQUEST":
                        actual = app.pg.surfarray.array3d(app.screen)[app.target.left:app.target.right,
                                                                    app.target.top:app.target.bottom]
                        expected = original_frame(app.grating, app.rows[value-1]["Rewarded"], 0)
                        np.testing.assert_array_equal(actual, expected.swapaxes(0, 1))
                        seen[value] = app.rows[value-1]["Cue"]

                with patch.dict(os.environ, {"SDL_VIDEODRIVER": "dummy"}), \
                        patch.object(Experiment, "handle_event", capture_display), \
                        patch.object(SquareGrating, "frame", capture_frame), \
                        contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    code = main(["--simulate", "--config", str(path), "--autostart",
                                 "--exit-when-done", "--outdir", str(Path(directory) / "data")])
                self.assertEqual(code, 0, output.getvalue())
                record = next((Path(directory) / "data").iterdir())
                with (record / "events.csv").open() as file:
                    events = list(csv.DictReader(file))
                def trials(event):
                    return {int(e["Value"]) for e in events if e["Event"] == event}
                plus = {i for i, cue in seen.items() if cue == "CS+"}
                minus = {i for i, cue in seen.items() if cue == "CS-"}
                self.assertEqual(len(plus), 2)
                self.assertEqual(len(minus), 2)
                for event in ("CS_PLUS_ON", "REWARD_ON", "REWARD_TRIGGER_ON"):
                    self.assertEqual(trials(event), plus)
                for event in ("CS_MINUS_ON", "NO_REWARD"):
                    self.assertEqual(trials(event), minus)
                for event in ("CUE_TRIGGER_ON", "TRIAL_END", "DISPLAY_ON", "DISPLAY_OFF"):
                    self.assertEqual(trials(event), {1, 2, 3, 4})
                self.assertFalse(trials("WAIT_LICK") & minus)
                self.assertTrue(any(t > 0 for t in frames))
                self.assertEqual(trials("SESSION_END"), {4})
                self.assertFalse(trials("SESSION_ABORTED"))
