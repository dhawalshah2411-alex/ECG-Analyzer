"""Fixed-size rolling buffer for ECG samples, with optional capture.

Holds the most recent N seconds of data. Older samples are discarded
automatically, so memory use stays constant however long acquisition
runs. During a recording, every new sample is also kept in a separate
capture list, which is handed over when the recording stops.
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
        self._capture = None          # a list while recording, else None

    def add(self, value):
        """Add one sample. Oldest is dropped once the window is full."""
        self._samples.append(value)
        self.total_added += 1
        capture = self._capture       # read once: it may change mid-call
        if capture is not None:
            capture.append(value)

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

    # --- recording capture ---------------------------------------------

    def start_capture(self):
        """Begin keeping every new sample, beyond the rolling window."""
        self._capture = []

    def stop_capture(self):
        """Stop keeping samples and return everything captured."""
        captured, self._capture = self._capture, None
        return np.array(captured if captured is not None else [], dtype=float)

    @property
    def is_capturing(self):
        return self._capture is not None

    @property
    def captured_count(self):
        """Number of samples captured so far in the current recording."""
        capture = self._capture
        return len(capture) if capture is not None else 0