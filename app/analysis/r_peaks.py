"""R-peak detection.

Two detectors are provided so their accuracy can be compared against
reference annotations:

- simple_detect: threshold and spacing constraints via scipy.find_peaks
- (Pan-Tompkins to follow)
"""

import numpy as np
from scipy import signal as sig

MIN_RR_SECONDS = 0.25    # 240 BPM ceiling — shorter gaps are not real beats
HEIGHT_FACTOR = 0.4      # threshold as a fraction of the signal's own scale


def simple_detect(x, fs, height_factor=HEIGHT_FACTOR,
                  min_rr=MIN_RR_SECONDS):
    """Detect R peaks by amplitude threshold and minimum spacing.

    Returns an array of sample indices.

    The threshold adapts to the signal's own amplitude rather than
    being a fixed millivolt value, so it does not depend on gain or
    electrode placement.
    """
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return np.array([], dtype=int)

    centred = x - np.median(x)
    scale = np.percentile(np.abs(centred), 98)
    if scale <= 0:
        return np.array([], dtype=int)

    peaks, _ = sig.find_peaks(
        centred,
        height=height_factor * scale,
        distance=max(1, int(min_rr * fs)),
    )
    return peaks


def rr_intervals(peaks, fs):
    """Return intervals between consecutive peaks, in seconds."""
    if len(peaks) < 2:
        return np.array([])
    return np.diff(peaks) / fs


def heart_rate(peaks, fs):
    """Mean heart rate in BPM from detected peaks."""
    rr = rr_intervals(peaks, fs)
    if len(rr) == 0:
        return 0.0
    return 60.0 / np.mean(rr)