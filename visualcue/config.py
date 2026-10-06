"""Load and validate user configuration before touching hardware."""

import json
import math
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "experiment.json"


def load_config(path=DEFAULT_CONFIG):
    with Path(path).open(encoding="utf-8") as file:
        config = json.load(file)
    validate_config(config)
    return config


def validate_config(config):
    expected = {
        "serial": {"port", "baud"},
        "session": {"trials", "cue_delay_ms", "cue_duration_ms", "reward_at_ms", "post_reward_ms", "valve_open_ms",
                    "initial_iti_s", "iti_min_s", "iti_max_s", "seed"},
        "display": {"fullscreen", "screen_index", "window_width", "window_height",
                    "background_gray", "max_cue_overrun_ms"},
        "stimulus": {"diameter_px", "cycles_per_patch", "orientation_deg", "contrast",
                     "sigma_fraction", "phase_deg"},
    }
    if not isinstance(config, dict) or set(config) != set(expected):
        raise ValueError("Config requires exactly serial, session, display, stimulus sections")
    for section, keys in expected.items():
        if not isinstance(config[section], dict) or set(config[section]) != keys:
            raise ValueError(f"Unexpected or missing keys in {section}; expected {sorted(keys)}")

    def integer(section, name, low, high):
        value = config[section][name]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{section}.{name} must be an integer in [{low}, {high}]")

    for name, low, high in (("trials", 1, 200), ("cue_delay_ms", 0, 60000),
                            ("cue_duration_ms", 1, 60000),
                            ("reward_at_ms", 1, 60000), ("post_reward_ms", 1, 60000), ("valve_open_ms", 1, 1000),
                            ("initial_iti_s", 0, 65535), ("iti_min_s", 0, 65535),
                            ("iti_max_s", 0, 65535)):
        integer("session", name, low, high)
    session = config["session"]
    if session["reward_at_ms"] <= session["cue_delay_ms"] + session["cue_duration_ms"]:
        raise ValueError("reward_at_ms must be after cue_delay_ms + cue_duration_ms")
    if session["post_reward_ms"] < session["valve_open_ms"]:
        raise ValueError("post_reward_ms must be >= valve_open_ms")
    if session["iti_max_s"] < session["iti_min_s"]:
        raise ValueError("iti_max_s must be >= iti_min_s")
    if session["seed"] is not None and type(session["seed"]) is not int:
        raise ValueError("session.seed must be an integer or null")
    if not isinstance(config["serial"]["port"], str) or not config["serial"]["port"]:
        raise ValueError("serial.port must be a nonempty string")
    if config["serial"]["baud"] != 115200:
        raise ValueError("Firmware requires baud 115200")
    if type(config["display"]["fullscreen"]) is not bool:
        raise ValueError("display.fullscreen must be true or false")
    for name, low, high in (("screen_index", 0, 31), ("window_width", 64, 8192),
                            ("window_height", 64, 8192), ("background_gray", 0, 255),
                            ("max_cue_overrun_ms", 1, 500)):
        integer("display", name, low, high)
    integer("stimulus", "diameter_px", 16, 4096)
    stimulus = config["stimulus"]
    for key in ("cycles_per_patch", "orientation_deg", "contrast", "sigma_fraction", "phase_deg"):
        value = stimulus[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"stimulus.{key} must be finite")
    if not 0 < stimulus["cycles_per_patch"] <= stimulus["diameter_px"] / 2:
        raise ValueError("cycles_per_patch must be >0 and <= diameter_px / 2")
    if not 0 <= stimulus["contrast"] <= 1 or not 0 < stimulus["sigma_fraction"] <= .5:
        raise ValueError("contrast must be 0..1; sigma_fraction must be >0 and <=0.5")


def configuration_command(config):
    s = config["session"]
    return "CONFIG {} {} {} {} {} {} {}".format(s["trials"], s["cue_delay_ms"],
        s["cue_duration_ms"], s["reward_at_ms"], s["post_reward_ms"], s["valve_open_ms"], s["initial_iti_s"])
