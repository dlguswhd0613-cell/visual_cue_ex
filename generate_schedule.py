"""Generate a daily schedule to reuse across mice; no hardware connection."""

import argparse
from datetime import datetime
from pathlib import Path

from visualcue.config import DEFAULT_CONFIG, load_config
from visualcue.schedule import generate_schedule, save_schedule


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    rows, seed = generate_schedule(config["session"], args.seed)
    path = args.out or Path("schedules") / f"{datetime.now():%Y%m%d_%H%M%S_%f}_visual_seed{seed}.csv"
    save_schedule(path, rows)
    print(f"{path} ({len(rows)} trials; seed={seed})")


if __name__ == "__main__":
    main()
