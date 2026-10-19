"""Saving recording sessions to disk.

Each session is stored three ways:
  - WFDB (.dat + .hea): the PhysioNet research format. Replays through
    the same loader as MIT-BIH, and is the format a published dataset uses.
  - CSV: the same samples, readable in any spreadsheet.
  - JSON: session details — subject ID, timing, settings.

Names and other identifying details live only in a separate private
registry and are never written into session files.
"""

import csv
import json
from pathlib import Path

import numpy as np
import wfdb

RECORDINGS_DIR = Path("recordings")
REGISTRY_FILE = "subjects_private.csv"
REGISTRY_FIELDS = ["subject_id", "name", "age", "gender",
                   "profession", "city", "registered"]


def _normalise(name):
    """Lower-case and collapse spaces, so 'A  b' matches 'a b'."""
    return " ".join(name.split()).lower()


class SubjectRegistry:
    """Private list linking subject IDs to identifying details."""

    def __init__(self, root=RECORDINGS_DIR):
        self.root = Path(root)
        self.path = self.root / REGISTRY_FILE

    def _rows(self):
        if not self.path.exists():
            return []
        with self.path.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def find_or_create(self, name, age, gender, profession, city, registered=""):
        """Return this person's subject ID, creating a new one if needed.

        Known limitation: two different people with exactly the same
        name would be given the same ID.
        """
        key = _normalise(name)
        rows = self._rows()
        for row in rows:
            if _normalise(row["name"]) == key:
                return row["subject_id"]

        subject_id = f"S{len(rows) + 1:03d}"
        self.root.mkdir(parents=True, exist_ok=True)
        is_new_file = not self.path.exists()
        with self.path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=REGISTRY_FIELDS)
            if is_new_file:
                writer.writeheader()
            writer.writerow({
                "subject_id": subject_id, "name": name.strip(), "age": age,
                "gender": gender, "profession": profession, "city": city,
                "registered": registered,
            })
        return subject_id


def save_session(subject_id, samples, sample_rate, units, started, info,
                 root=RECORDINGS_DIR):
    """Write one recording session in WFDB, CSV and JSON.

    started: datetime when recording began.
    info: shareable details only (age, gender, source, notes, ...).
    Returns the session path without extension.
    """
    samples = np.asarray(samples, dtype=float)
    name = f"{subject_id}_{started.strftime('%Y%m%d_%H%M%S')}"
    folder = Path(root) / subject_id
    folder.mkdir(parents=True, exist_ok=True)

    wfdb.wrsamp(name, fs=sample_rate, units=[units], sig_name=["ECG"],
                p_signal=samples.reshape(-1, 1), fmt=["16"],
                write_dir=str(folder), comments=[f"subject {subject_id}"])

    times = np.arange(len(samples)) / sample_rate
    np.savetxt(folder / f"{name}.csv", np.column_stack([times, samples]),
               delimiter=",", header="time_s,value", comments="",
               fmt=["%.4f", "%.6f"])

    meta = {
        "session": name,
        "subject_id": subject_id,
        "started": started.isoformat(timespec="seconds"),
        "sample_rate_hz": float(sample_rate),
        "samples": int(len(samples)),
        "duration_s": round(len(samples) / sample_rate, 2),
        "units": units,
        **info,
    }
    with (folder / f"{name}.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return folder / name