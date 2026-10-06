r"""
Generates a fixed CS+/CS- (conditioning) or ITI (habituation) schedule ahead
of time, so every mouse run on a given day uses the exact same sequence
instead of each Arduino picking its own random order.

Run this once per day, pick the mode, and it writes a schedule CSV. Then
point HEADFIXED_PYTHON.py at that same file with --schedule for every mouse
run that day.

Mode 1 and mode 2 start with 3 LED/TTL blinks followed by a fixed
START_FIXED_ITI_SECONDS delay before the first trial/reward. The first row's
ITI is written as that fixed value; rows 2..end are the scheduled ITIs used
between trials/rewards.

Usage:
    python generate_schedule.py --mode 1 --outdir "D:\Schedules"   (conditioning: 100 trials)
    python generate_schedule.py --mode 2 --outdir "D:\Schedules"   (habituation: 80 rewards)
    python generate_schedule.py                                   (no --mode: asks 1 or 2 interactively)

Each run creates exactly one schedule file - conditioning OR habituation,
never both.
"""

import argparse
import csv
import random
from datetime import datetime
from pathlib import Path

# ---- Must match HEADFIXED_ARDUINO.ino's constants. ----
TRIALS_PER_TYPE = 50
TOTAL_TRIALS = TRIALS_PER_TYPE * 2
COND_ITI_MIN_S = 16
COND_ITI_MAX_S = 46
START_FIXED_ITI_SECONDS = 90

TOTAL_REWARDS = 80
HAB_ITI_MIN_S = 10
HAB_ITI_MAX_S = 20

# ---- Edit this to choose where the schedule CSV is saved. ----
# Leave as None to save to a "schedules" folder next to this script.
SAVE_DIR = "D:\\AM\\Data\\Schedule"


def generate_conditioning_schedule():
    types = ["CS+"] * TRIALS_PER_TYPE + ["CS-"] * TRIALS_PER_TYPE
    random.shuffle(types)
    rows = []
    for trial, cs_type in enumerate(types, start=1):
        iti = START_FIXED_ITI_SECONDS if trial == 1 else random.randint(COND_ITI_MIN_S, COND_ITI_MAX_S)
        rows.append([trial, cs_type, iti])
    return ["Trial", "CS_Type", "ITI_Duration_S"], rows


def generate_habituation_schedule():
    rows = []
    for reward in range(1, TOTAL_REWARDS + 1):
        iti = START_FIXED_ITI_SECONDS if reward == 1 else random.randint(HAB_ITI_MIN_S, HAB_ITI_MAX_S)
        rows.append([reward, iti])
    return ["Reward", "ITI_Duration_S"], rows


def prompt_for_mode():
    while True:
        choice = input("Generate schedule for: 1=conditioning, 2=habituation > ").strip()
        if choice in ("1", "2"):
            return choice
        print("Please enter 1 or 2.")


def main():
    parser = argparse.ArgumentParser(description="Generate a fixed daily schedule for conditioning or habituation.")
    parser.add_argument("--mode", choices=["1", "2"], help="1=conditioning, 2=habituation. Omit to be asked interactively.")
    parser.add_argument(
        "--outdir",
        default=SAVE_DIR if SAVE_DIR else str(Path(__file__).parent / "schedules"),
        help="Folder to save the schedule CSV in. Defaults to the SAVE_DIR variable above.",
    )
    args = parser.parse_args()

    mode = args.mode if args.mode else prompt_for_mode()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if mode == "1":
        headers, rows = generate_conditioning_schedule()
        path = outdir / f"{stamp}_conditioning_schedule.csv"
    else:
        headers, rows = generate_habituation_schedule()
        path = outdir / f"{stamp}_habituation_schedule.csv"

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    print(f"Schedule written to {path}")
    print(f'Use it with HEADFIXED_PYTHON.py: --schedule "{path}"')


if __name__ == "__main__":
    main()
