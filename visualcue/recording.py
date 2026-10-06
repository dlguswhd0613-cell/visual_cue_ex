"""Unique session directories and flush-on-event records."""

import csv
import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

from .schedule import save_schedule


class SessionLog:
    def __init__(self, outdir, mouse_id, config, schedule, seed, simulated):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", mouse_id):
            raise ValueError("mouse-id must be 1..80 letters, digits, underscores or hyphens")
        name = f"{datetime.now():%Y%m%d_%H%M%S_%f}_{mouse_id}_{uuid.uuid4().hex[:6]}"
        self.path = Path(outdir) / ("SIMULATED_" + name if simulated else name)
        self.path.mkdir(parents=True, exist_ok=False)
        self.metadata = {"mouse_id": mouse_id, "simulated": simulated, "seed": seed,
                         "created_at": datetime.now().astimezone().isoformat(), "config": config,
                         "status": "preparing", "protocol_version": 1}
        self.save_metadata()
        save_schedule(self.path / "schedule.csv", schedule)
        self.file = (self.path / "events.csv").open("x", newline="", encoding="utf-8")
        self.writer = csv.writer(self.file)
        self.writer.writerow(["Host_Timestamp", "Host_Monotonic_NS", "Arduino_ms", "Event", "Value", "Source"])
        self.file.flush()

    def save_metadata(self):
        temporary = self.path / "metadata.json.tmp"
        temporary.write_text(json.dumps(self.metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path / "metadata.json")

    def event(self, event, value, arduino_ms="", source="host", at_ns=None):
        self.writer.writerow([datetime.now().astimezone().isoformat(timespec="milliseconds"),
                              at_ns if at_ns is not None else time.monotonic_ns(),
                              arduino_ms, event, value, source])
        self.file.flush()

    def close(self):
        self.file.close()
