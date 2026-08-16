"""Loader for PhysioNet WFDB-format ECG records.

Provides recorded signals to the same processing pipeline as live
acquisition, so algorithms can be developed and validated against
annotated reference data.
"""

import numpy as np
import wfdb


class RecordLoader:
    """Reads a single channel from a WFDB record."""

    def __init__(self, path, channel_name="MLII"):
        self.path = path
        self.channel_name = channel_name
        self.signal = None
        self.sample_rate = None
        self.units = None
        self.annotations = None

    def load(self):
        """Read the record. Returns (signal, sample_rate)."""
        record = wfdb.rdrecord(self.path)

        if self.channel_name not in record.sig_name:
            raise ValueError(
                f"Channel {self.channel_name!r} not in record. "
                f"Available: {record.sig_name}"
            )

        index = record.sig_name.index(self.channel_name)
        self.signal = record.p_signal[:, index].astype(float)
        self.sample_rate = float(record.fs)
        self.units = record.units[index]
        return self.signal, self.sample_rate

    def load_annotations(self, extension="atr"):
        """Read reference beat annotations as sample indices."""
        ann = wfdb.rdann(self.path, extension)
        self.annotations = np.array(ann.sample)
        return self.annotations

    @property
    def duration_seconds(self):
        if self.signal is None:
            return 0.0
        return len(self.signal) / self.sample_rate