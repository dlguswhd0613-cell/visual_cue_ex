"""Reproducible visual schedules, including balanced CS+/CS- discrimination."""

import csv
import math
import random
import secrets
from pathlib import Path

HEADERS = ["Trial", "ITI_Duration_S", "Rewarded"]
DISCRIMINATION_HEADERS = HEADERS + ["Cue"]


def generate_schedule(session, seed=None):
    discrimination = session.get("cue_protocol") == "square_discrimination"
    if discrimination and session["trials"] % 2:
        raise ValueError("Equal CS+/CS- counts require an even number of trials")
    if seed is None:
        seed = session["seed"]
    if seed is None:
        seed = secrets.randbits(32)
    rng = random.Random(seed)
    low, high = session["iti_min_s"], session["iti_max_s"]
    distribution = session.get("iti_distribution", "uniform")
    if distribution == "exponential":
        scale = session.get("iti_exponential_scale_s", 3.0)
        # Discrete truncated exponential: P(k) is proportional to
        # exp(-(k-low)/scale), for every integer low <= k <= high.
        # Sampling within the bounds avoids a pileup from clipping at high.
        intervals = range(low, high + 1)
        weights = [math.exp(-(k - low) / scale) for k in intervals]
    elif distribution != "uniform":
        raise ValueError("iti_distribution must be uniform or exponential")

    def next_iti():
        if low == high:
            return low
        if distribution == "exponential":
            return rng.choices(intervals, weights=weights, k=1)[0]
        return rng.randint(low, high)

    rows = [{"Trial": i, "ITI_Duration_S": session["initial_iti_s"] if i == 1 else
             next_iti(), "Rewarded": 1}
            for i in range(1, session["trials"] + 1)]
    if discrimination:
        rewarded = [1] * (len(rows) // 2) + [0] * (len(rows) // 2)
        rng.shuffle(rewarded)
        for row, reward in zip(rows, rewarded):
            row.update(Rewarded=reward, Cue="CS+" if reward else "CS-")
    return rows, seed


def save_schedule(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8") as file:
        headers = DISCRIMINATION_HEADERS if rows and "Cue" in rows[0] else HEADERS
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def load_schedule(path, session):
    discrimination = session.get("cue_protocol") == "square_discrimination"
    headers = DISCRIMINATION_HEADERS if discrimination else HEADERS
    with Path(path).open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != headers:
            raise ValueError(f"Schedule headers must be {headers}; generate a new schedule for the selected cue protocol")
        try:
            rows = []
            for row in reader:
                parsed = {k: int(row[k]) for k in HEADERS}
                if discrimination:
                    parsed["Cue"] = row["Cue"]
                rows.append(parsed)
        except (TypeError, ValueError, KeyError) as error:
            raise ValueError("Schedule must contain integer fields") from error
    if len(rows) != session["trials"]:
        raise ValueError("Schedule row count must match session.trials")
    for i, row in enumerate(rows, start=1):
        if row["Trial"] != i or row["Rewarded"] not in ((0, 1) if discrimination else (1,)):
            raise ValueError("Invalid trial number or reward flag for selected cue protocol")
        if discrimination and row["Cue"] != ("CS+" if row["Rewarded"] else "CS-"):
            raise ValueError(f"Trial {i}: CS+ must be rewarded and CS- must be unrewarded")
        iti = row["ITI_Duration_S"]
        if i == 1 and iti != session["initial_iti_s"]:
            raise ValueError("First schedule ITI must equal initial_iti_s")
        if i > 1 and not session["iti_min_s"] <= iti <= session["iti_max_s"]:
            raise ValueError(f"Trial {i} ITI lies outside configured range")
    if discrimination and (len(rows) % 2 or sum(r["Rewarded"] for r in rows) != len(rows) // 2):
        raise ValueError("Schedule requires equal CS+ and CS- counts")
    return rows
