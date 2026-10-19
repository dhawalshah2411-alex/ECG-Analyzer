"""Signal-quality assessment.

The central measure is bSQI: two different beat detectors are run on the
same signal and their agreement is measured. Where both find the same
beats, the signal is trustworthy; where they disagree, noise or electrode
movement is usually the cause (Li, Mark and Clifford, 2008).

Two simpler checks catch failures bSQI cannot: a flat signal (cable
unplugged or electrode off) and a clipped one (signal hitting the limits
of the converter).
"""

from dataclasses import dataclass

import numpy as np

MATCH_TOLERANCE_S = 0.15     # same tolerance as the accuracy scoring
GOOD_BSQI = 0.90
FAIR_BSQI = 0.80
WINDOW_S = 10.0              # judge quality on the most recent 10 s
MARGIN_S = 1.0               # ignore the newest 1 s, where beats are unconfirmed
CLIP_FRACTION = 0.01         # >1% of samples stuck at an extreme = clipping


@dataclass
class Quality:
    state: str          # "good", "fair", "poor" or "unknown"
    reason: str
    bsqi: float | None


def bsqi(peaks_a, peaks_b, fs, tolerance_s=MATCH_TOLERANCE_S):
    """Agreement between two sets of beats, from 0 (none) to 1 (all).

    Computed as an F1 score: twice the matched beats divided by the total
    beats found by both. Returns None if neither found any beats.
    """
    a = np.asarray(peaks_a)
    b = np.asarray(peaks_b)
    if len(a) == 0 and len(b) == 0:
        return None
    if len(a) == 0 or len(b) == 0:
        return 0.0

    tol = tolerance_s * fs
    used = set()
    matched = 0
    for p in a:
        i = int(np.argmin(np.abs(b - p)))
        if abs(b[i] - p) <= tol and i not in used:
            used.add(i)
            matched += 1
    return 2.0 * matched / (len(a) + len(b))


def assess(raw, fs, peaks_a, peaks_b, bpm):
    """Judge the quality of the most recent part of a signal window.

    raw: the analysis window. peaks_a, peaks_b: beat positions from two
    different detectors, as indices into raw. bpm: current heart rate,
    or None if implausible.
    """
    raw = np.asarray(raw, dtype=float)
    n = len(raw)
    if n < WINDOW_S * fs:
        return Quality("unknown", "", None)

    recent = raw[-int(WINDOW_S * fs):]
    if np.ptp(recent) == 0:
        return Quality("poor", "No signal — check the cable and electrodes.", None)

    at_extremes = np.mean((recent == recent.max()) | (recent == recent.min()))
    if at_extremes > CLIP_FRACTION:
        return Quality("poor", "Signal clipping — peaks are being cut off.", None)

    lo = n - int(WINDOW_S * fs)
    hi = n - int(MARGIN_S * fs)
    a = np.asarray(peaks_a)
    b = np.asarray(peaks_b)
    a = a[(a >= lo) & (a < hi)]
    b = b[(b >= lo) & (b < hi)]

    score = bsqi(a, b, fs)
    if score is None:
        return Quality("poor", "No heartbeats found — check electrode contact.", None)

    agree = f"Detectors agree on {score:.0%} of beats"
    if bpm is None:
        return Quality("poor", f"Heart rate implausible. {agree}.", score)
    if score >= GOOD_BSQI:
        return Quality("good", f"{agree}.", score)
    if score >= FAIR_BSQI:
        return Quality("fair", f"{agree} — some noise or movement.", score)
    return Quality("poor", f"{agree} — noise or electrode movement.", score)