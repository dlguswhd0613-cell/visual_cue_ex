"""Reproducible, all-rewarded visual trial schedules."""

import csv
import math
import random
import secrets
from pathlib import Path

HEADERS = ["Trial", "ITI_Duration_S", "Rewarded"]


def generate_schedule(session, seed=None):
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
    return rows, seed


def save_schedule(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def load_schedule(path, session):
    with Path(path).open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != HEADERS:
            raise ValueError(f"Schedule headers must be {HEADERS}")
        try:
            rows = [{k: int(row[k]) for k in HEADERS} for row in reader]
        except (TypeError, ValueError, KeyError) as error:
            raise ValueError("Schedule must contain integer fields") from error
    if len(rows) != session["trials"]:
        raise ValueError("Schedule row count must match session.trials")
    for i, row in enumerate(rows, start=1):
        if row["Trial"] != i or row["Rewarded"] != 1:
            raise ValueError("This task requires consecutive trial numbers and every trial rewarded (1)")
        iti = row["ITI_Duration_S"]
        if i == 1 and iti != session["initial_iti_s"]:
            raise ValueError("First schedule ITI must equal initial_iti_s")
        if i > 1 and not session["iti_min_s"] <= iti <= session["iti_max_s"]:
            raise ValueError(f"Trial {i} ITI lies outside configured range")
    return rows
