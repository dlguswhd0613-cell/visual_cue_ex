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
    shape = "gabor"
    if isinstance(config, dict) and isinstance(config.get("stimulus"), dict):
        shape = config["stimulus"].get("type", "gabor")
    if shape == "square_grating":
        expected["stimulus"] = {"type", "visual_angle_deg", "viewing_distance_cm",
                                "screen_width_cm", "screen_width_px", "mean_gray", "contrast",
                                "spatial_frequency_cpd", "temporal_frequency_hz", "animation_rate_hz"}
    if (not isinstance(config, dict) or not set(expected) <= set(config)
            or set(config) - set(expected) - {"photometry"}):
        raise ValueError("Config requires serial, session, display, stimulus; optional photometry")
    if "photometry" in config:
        expected["photometry"] = {"enabled", "cue_lead_ms", "reward_lead_ms", "pulse_ms"}
    for section, keys in expected.items():
        optional = {"task", "cue_protocol", "iti_distribution", "iti_exponential_scale_s"} if section == "session" else set()
        if (not isinstance(config[section], dict) or not keys <= set(config[section])
                or set(config[section]) - keys - optional):
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
    protocol = session.get("cue_protocol", "all_rewarded")
    if protocol not in ("all_rewarded", "square_discrimination"):
        raise ValueError("session.cue_protocol must be all_rewarded or square_discrimination")
    if shape == "square_grating" and protocol != "square_discrimination":
        raise ValueError("square_grating requires session.cue_protocol=square_discrimination")
    if protocol == "square_discrimination":
        if shape != "square_grating" or session["trials"] % 2:
            raise ValueError("square_discrimination requires square stimuli and an even trial count (equal CS+/CS-)")
    if session.get("task", "operant") not in ("pavlovian", "operant"):
        raise ValueError("session.task must be pavlovian or operant")
    if session.get("iti_distribution", "uniform") not in ("uniform", "exponential"):
        raise ValueError("session.iti_distribution must be uniform or exponential")
    scale = session.get("iti_exponential_scale_s", 3.0)
    if (isinstance(scale, bool) or not isinstance(scale, (int, float))
            or not math.isfinite(scale) or scale <= 0):
        raise ValueError("session.iti_exponential_scale_s must be finite and >0")
    if session["reward_at_ms"] <= session["cue_delay_ms"] + session["cue_duration_ms"]:
        raise ValueError("reward_at_ms must be after cue_delay_ms + cue_duration_ms")
    if session["post_reward_ms"] < session["valve_open_ms"]:
        raise ValueError("post_reward_ms must be >= valve_open_ms")
    if "photometry" in config:
        p = config["photometry"]
        if type(p["enabled"]) is not bool:
            raise ValueError("photometry.enabled must be true or false")
        integer("photometry", "cue_lead_ms", 0, session["cue_delay_ms"])
        integer("photometry", "reward_lead_ms", 0,
                session["reward_at_ms"] - session["cue_delay_ms"] - session["cue_duration_ms"])
        integer("photometry", "pulse_ms", 1, 1000)
        cue_at = session["cue_delay_ms"] - p["cue_lead_ms"]
        reward_at = session["reward_at_ms"] - p["reward_lead_ms"]
        if p["pulse_ms"] >= reward_at - cue_at:
            raise ValueError("photometry pulses need a LOW gap between cue and reward on D7")
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
    stimulus = config["stimulus"]
    if shape == "square_grating":
        for key in ("visual_angle_deg", "viewing_distance_cm", "screen_width_cm",
                    "spatial_frequency_cpd", "temporal_frequency_hz"):
            value = stimulus[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"stimulus.{key} must be finite and >0")
        if stimulus["visual_angle_deg"] >= 180:
            raise ValueError("stimulus.visual_angle_deg must be <180")
        integer("stimulus", "screen_width_px", 64, 16384)
        integer("stimulus", "mean_gray", 1, 254)
        integer("stimulus", "animation_rate_hz", 10, 240)
        contrast = stimulus["contrast"]
        if isinstance(contrast, bool) or not isinstance(contrast, (int, float)) or not math.isfinite(contrast) or not 0 < contrast <= 1:
            raise ValueError("stimulus.contrast must be >0 and <=1")
        if stimulus["temporal_frequency_hz"] >= stimulus["animation_rate_hz"] / 2:
            raise ValueError("Temporal frequency must be below half the animation rate")
        degrees_per_pixel = math.degrees(stimulus["screen_width_cm"] / stimulus["screen_width_px"] / stimulus["viewing_distance_cm"])
        if stimulus["spatial_frequency_cpd"] * degrees_per_pixel >= .5:
            raise ValueError("Spatial frequency exceeds pixel sampling limit")
        from .stimulus import square_geometry
        if not 16 <= square_geometry(stimulus)["diagonal_px"] <= 4096:
            raise ValueError("Square diagonal must be 16..4096 pixels; check screen calibration")
        return
    integer("stimulus", "diameter_px", 16, 4096)
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


def photometry_command(config):
    p = config.get("photometry", {})
    if not p.get("enabled", False):
        return None
    return "TRIGGERS {} {} {}".format(p["cue_lead_ms"], p["reward_lead_ms"], p["pulse_ms"])
