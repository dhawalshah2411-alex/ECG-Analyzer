"""Heart-rate recovery after exercise, measured beat by beat.

A recovery test is one continuous recording in three parts:

    rest  ->  exercise  ->  recovery
              ^start        ^stop  (both marked by button presses)

The exercise part is noisy (movement), so it is never measured. What is
measured, from the beats themselves:

- resting heart rate: the last 60 s of rest
- heart rate at the stop: the beats from 3 s before to 5 s after the
  "Exercise stopped" press (the closest clean estimate of the peak)
- heart rate 10 s, 60 s and 120 s after the stop, and the drop since
  the stop at each of those times
- T30: how fast the heart rate falls in the first 30 s, as a time
  constant in seconds (smaller = faster)
- how long until the heart rate is back within 10% of resting

No Qt, so it can be tested on synthetic recordings with a known answer.
"""

from dataclasses import dataclass, field

import numpy as np

from app.analysis.r_peaks import pan_tompkins_detect
from app.signal_processing.filters import preprocess

REST_S = 60.0             # resting rate from the last 60 s before exercise
STOP_WINDOW_S = (3.0, 5.0)  # beats from 3 s before to 5 s after the stop
POINT_HALF_S = 2.5        # heart rate "at 60 s" = beats from 57.5 to 62.5 s
CHECK_POINTS_S = (10, 60, 120)
T30_S = 30.0              # T30 uses the first 30 s after the stop
NEAR_REST = 0.10          # "back to rest" = within 10% of the resting rate
NEIGHBOURS = 5            # a beat gap is compared with 5 gaps on each side
MAX_JUMP = 0.25           # ...and dropped if it differs from them by >25%
RR_LIMITS_S = (0.27, 2.0)  # gaps outside 30-220 bpm are never real beats


@dataclass
class Recovery:
    resting_bpm: float | None
    stop_bpm: float | None
    hr_at: dict = field(default_factory=dict)      # seconds after stop -> bpm
    drop_at: dict = field(default_factory=dict)    # seconds after stop -> bpm fallen
    t30_s: float | None = None
    back_to_rest_s: float | None = None
    curve_t: np.ndarray = field(default_factory=lambda: np.array([]))   # s from stop
    curve_bpm: np.ndarray = field(default_factory=lambda: np.array([]))
    beat_t: np.ndarray = field(default_factory=lambda: np.array([]))    # s from stop
    beat_bpm: np.ndarray = field(default_factory=lambda: np.array([]))


def beat_rates(beat_times):
    """Heart rate at each beat (60 / gap), keeping only believable gaps.

    Returns (times, bpm) for the second beat of every accepted gap.
    A gap is rejected if it is outside 30-220 bpm, or if it differs by
    more than 25% from the median of its neighbours - which is what a
    missed beat, a doubled beat or a movement spike looks like.
    """
    t = np.asarray(beat_times, dtype=float)
    if len(t) < 3:
        return np.array([]), np.array([])
    gaps = np.diff(t)
    ok = (gaps >= RR_LIMITS_S[0]) & (gaps <= RR_LIMITS_S[1])
    keep = ok.copy()
    for i in np.flatnonzero(ok):
        lo, hi = max(0, i - NEIGHBOURS), min(len(gaps), i + NEIGHBOURS + 1)
        near = gaps[lo:hi][ok[lo:hi]]
        if len(near) >= 3 and abs(gaps[i] - np.median(near)) > MAX_JUMP * np.median(near):
            keep[i] = False
    return t[1:][keep], 60.0 / gaps[keep]


def _median_between(times, bpm, start, end, minimum=2):
    chosen = bpm[(times >= start) & (times <= end)]
    return float(np.median(chosen)) if len(chosen) >= minimum else None


def recovery_from_beats(beat_times, exercise_start_s, stop_s):
    """All recovery measurements from beat times (seconds into the recording)."""
    times, bpm = beat_rates(beat_times)
    resting = _median_between(times, bpm, exercise_start_s - REST_S, exercise_start_s, 10)
    stop = _median_between(times, bpm, stop_s - STOP_WINDOW_S[0], stop_s + STOP_WINDOW_S[1])

    after = times >= stop_s - STOP_WINDOW_S[0]
    rel_t, rel_bpm = times[after] - stop_s, bpm[after]

    # A smooth curve, one point per second: median of the beats within 2.5 s.
    end = rel_t.max() if len(rel_t) else 0.0
    grid = np.arange(0.0, np.floor(end) + 1.0)
    curve = np.array([_median_between(rel_t, rel_bpm, g - POINT_HALF_S, g + POINT_HALF_S)
                      or np.nan for g in grid])

    hr_at, drop_at = {}, {}
    for point in CHECK_POINTS_S:
        value = _median_between(rel_t, rel_bpm, point - POINT_HALF_S, point + POINT_HALF_S)
        hr_at[point] = value
        drop_at[point] = (stop - value) if (stop is not None and value is not None) else None

    # T30: the straight line that best fits log(heart rate) over the first
    # 30 s; T30 = -1 / its slope. An exponential fall with time constant
    # tau gives a straight line of slope -1/tau.
    t30 = None
    first = (grid <= T30_S) & np.isfinite(curve)
    if first.sum() >= 15:
        slope = np.polyfit(grid[first], np.log(curve[first]), 1)[0]
        if slope < 0:
            t30 = -1.0 / slope

    back = None
    if resting is not None:
        near = np.flatnonzero(np.isfinite(curve) & (curve <= (1 + NEAR_REST) * resting))
        if len(near):
            back = float(grid[near[0]])

    return Recovery(resting_bpm=resting, stop_bpm=stop, hr_at=hr_at, drop_at=drop_at,
                    t30_s=t30, back_to_rest_s=back, curve_t=grid, curve_bpm=curve,
                    beat_t=rel_t, beat_bpm=rel_bpm)


def measure_recovery(raw, fs, exercise_start_s, stop_s):
    """Detect beats in a whole recovery-test recording and measure recovery."""
    filtered = preprocess(np.asarray(raw, dtype=float), fs)
    peaks = pan_tompkins_detect(filtered, fs)
    beat_times = peaks / fs
    # Beats during the exercise itself are not trusted; drop them.
    keep = (beat_times < exercise_start_s) | (beat_times >= stop_s - STOP_WINDOW_S[0])
    return recovery_from_beats(beat_times[keep], exercise_start_s, stop_s)