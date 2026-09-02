"""Heart rate and RR interval calculation from detected R peaks.

Rate is reported as a rolling median over recent beats, which is
robust to the occasional missed or spurious detection: a missed beat
produces one doubled interval, which a median discards but a mean
would not.
"""

import numpy as np

DEFAULT_WINDOW = 8       # beats used for the rolling median
MIN_BPM = 30.0           # below this, report unavailable
MAX_BPM = 300.0          # above this, report unavailable


class HeartRateMonitor:
    """Tracks heart rate continuously from a stream of R-peak positions."""

    def __init__(self, sample_rate, window=DEFAULT_WINDOW,
                 min_bpm=MIN_BPM, max_bpm=MAX_BPM):
        self.sample_rate = sample_rate
        self.window = window
        self.min_bpm = min_bpm
        self.max_bpm = max_bpm

    def rr_intervals(self, peaks):
        """Intervals between consecutive peaks, in seconds."""
        peaks = np.asarray(peaks)
        if len(peaks) < 2:
            return np.array([])
        return np.diff(peaks) / self.sample_rate

    def current_rr(self, peaks):
        """Most recent RR interval in milliseconds, or None."""
        rr = self.rr_intervals(peaks)
        if len(rr) == 0:
            return None
        return float(rr[-1] * 1000.0)

    def current_bpm(self, peaks):
        """Rolling median heart rate in BPM, or None if unavailable.

        Returns None when there are too few beats, or when the result
        falls outside the plausible physiological range.
        """
        rr = self.rr_intervals(peaks)
        if len(rr) == 0:
            return None

        recent = rr[-self.window:]
        median_rr = float(np.median(recent))
        if median_rr <= 0:
            return None

        bpm = 60.0 / median_rr
        if bpm < self.min_bpm or bpm > self.max_bpm:
            return None
        return bpm

    def stats(self, peaks):
        """Summary statistics over all supplied peaks."""
        rr = self.rr_intervals(peaks)
        if len(rr) == 0:
            return {"beats": len(peaks), "bpm": None, "rr_ms": None,
                    "rr_std_ms": None}

        return {
            "beats": len(peaks),
            "bpm": self.current_bpm(peaks),
            "rr_ms": float(np.median(rr) * 1000.0),
            "rr_std_ms": float(np.std(rr) * 1000.0),
        }