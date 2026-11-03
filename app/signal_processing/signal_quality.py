"""Signal-quality assessment: can the heart rate on screen be trusted?

The central measure is bSQI: two different beat detectors are run on the
same signal and their agreement is measured. Where both find the same
beats, the signal is trustworthy; where they disagree, noise or electrode
movement is usually the cause (Li, Mark and Clifford, 2008).

bSQI follows the paper's definition exactly: beats both detectors found,
divided by all the beats either detector found (each counted once), over
a 10 s window, with beats matched within 150 ms.

Two simpler checks catch failures bSQI cannot:

- a flat signal (cable unplugged or electrode off);
- a signal stuck at the top or bottom of its range for more than 10% of
  the last 10 s. A stretch stuck for 50 ms or more means the amplifier
  saturated there and any beat inside is lost. One brief stretch, when a
  step jolts the trace, loses a beat or two, which the heart-rate median
  ignores; a lot of it means an electrode is lifting.

The rating is about the heart rate, so two things that don't change it
are reported as notes, not as a worse rating:

- R-wave tips cut off at the top of the range. The amplifier's output
  can't go higher, so the tip's height is lost, but the peak's timing
  survives: a test that cut the top 20% off every R wave of a real
  5-minute recording (S002, 23 Oct) left heart rate unchanged, moved
  RMSSD by 0.1 ms and lost no beats.
- brief saturation, as above.

The first version capped every recording with cut tips at "fair", and
called any 50 ms at the limit "poor" for the next 10 s. Replaying the
live check over two real exercise tests (S005, S006) showed what that
cost: the heart rate was hidden in 15-18% of the exercise, yet where it
could be compared with the finished analysis it was within about 1 bpm.
A recording where an electrode really did come off (S002, 23 Oct:
stuck for up to 100% of the window) is still rated poor.
"""

from dataclasses import dataclass

import numpy as np

MATCH_TOLERANCE_S = 0.15     # beats within 150 ms count as the same beat (ANSI/AAMI EC57)
GOOD_BSQI = 9 / 11           # 0.818. Same verdicts as the earlier F1 version's 0.90:
FAIR_BSQI = 2 / 3            # 0.667. (bSQI = F1 / (2 - F1), and 0.80 becomes 2/3)
WINDOW_S = 10.0              # judge quality on the most recent 10 s (as Li et al.)
MARGIN_S = 1.0               # ignore the newest 1 s, where beats are unconfirmed
LIMIT_BAND = 0.002           # "at the limit": within 0.2% of the range from top or bottom
                             # (a saturated amplifier jitters a few counts below its limit)
STUCK_S = 0.050              # at the limit this long = saturated, not just an R tip
MAX_STUCK = 0.10             # saturated for more than 10% of the window (1 s) = poor
TIPS_CUT_BEATS = 3           # flat tips on this many beats in 10 s = the R waves are being cut
                             # (without clipping, only the single tallest beat reaches the top)

TIPS_NOTE = "R-wave tips are cut off: heart rate is unaffected, wave heights are not reliable."
JOLT_NOTE = "The trace briefly hit its limit (a movement); beats there are skipped."


@dataclass
class Quality:
    state: str          # "good", "fair", "poor" or "unknown"
    reason: str
    bsqi: float | None


def bsqi(peaks_a, peaks_b, fs, tolerance_s=MATCH_TOLERANCE_S):
    """Agreement between two sets of beats, from 0 (none) to 1 (all).

    Li, Mark and Clifford (2008): beats both detectors found, divided by
    all the beats either detector found, each beat counted once.
    Returns None if neither found any beats.
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
    return matched / (len(a) + len(b) - matched)


def limit_runs(x):
    """Lengths, in samples, of every stretch the signal spends at its top or bottom.

    "At" means within LIMIT_BAND of the signal's own highest or lowest
    value. Top and bottom are counted separately.
    """
    x = np.asarray(x, dtype=float)
    top, bottom = x.max(), x.min()
    band = LIMIT_BAND * (top - bottom)
    runs = []
    for at in (x >= top - band, x <= bottom + band):
        edges = np.diff(np.concatenate(([0], at.astype(int), [0])))
        starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
        runs.extend((ends - starts).tolist())
    return runs


def assess(raw, fs, peaks_a, peaks_b, bpm):
    """Judge whether the heart rate from the most recent 10 s can be trusted.

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

    runs = np.array(limit_runs(recent))
    stuck = runs[runs >= STUCK_S * fs].sum() / len(recent)
    if stuck > MAX_STUCK:
        return Quality("poor", f"Signal stuck at its limit for {stuck:.0%} of the last 10 s — "
                               "an electrode may be lifting.", None)
    notes = []
    if stuck > 0:
        notes.append(JOLT_NOTE)
    if (runs >= 2).sum() >= TIPS_CUT_BEATS:
        notes.append(TIPS_NOTE)
    extra = "".join(" " + note for note in notes)

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
        return Quality("good", f"{agree}.{extra}", score)
    if score >= FAIR_BSQI:
        return Quality("fair", f"{agree} — some noise or movement.{extra}", score)
    return Quality("poor", f"{agree} — noise or electrode movement.", score)