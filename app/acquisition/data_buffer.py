"""Fixed-size rolling buffer for ECG samples.

Holds the most recent N seconds of data. Older samples are discarded
automatically, so memory use stays constant however long acquisition runs.
"""

from collections import deque

import numpy as np


class DataBuffer:
    """A rolling window of the most recent ECG samples."""

    def __init__(self, sample_rate=500, window_seconds=5.0):
        self.sample_rate = sample_rate
        self.window_seconds = window_seconds
        self.maxlen = int(sample_rate * window_seconds)
        self._samples = deque(maxlen=self.maxlen)
        self.total_added = 0

    def add(self, value):
        """Add one sample. Oldest is dropped once the window is full."""
        self._samples.append(value)
        self.total_added += 1

    def get_values(self):
        """Return the buffered samples as a NumPy array."""
        return np.array(self._samples, dtype=float)

    def get_time_axis(self, n=None):
        """Return timestamps in seconds, ending at 0.0 (now).

        Pass n to match an array you already took, avoiding a mismatch
        if the buffer grew in between.
        """
        if n is None:
            n = len(self._samples)
        return np.linspace(-n / self.sample_rate, 0.0, n)

    def is_full(self):
        """True once the window holds a complete span of data."""
        return len(self._samples) == self.maxlen

    def clear(self):
        """Discard all buffered samples."""
        self._samples.clear()

    def __len__(self):
        return len(self._samples)