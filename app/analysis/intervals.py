"""Wave boundaries and intervals, measured on an averaged heartbeat.

A single beat is noisy. The median of many beats, lined up on their R
peaks, is not, so the P, QRS and T boundaries are found on that one
"average beat". Many ECG machines report their intervals the same way.

Results are times in milliseconds. Times do not depend on the
amplifier's gain, so they are meaningful even while amplitudes are
uncalibrated. Amplitudes are reported in the signal's own units.

These are estimates, not clinical measurements: one lead, filtered
0.5-40 Hz, boundaries found with simple slope and tangent rules. The
rules still have to be checked against cardiologists' annotations
(PhysioNet QT Database) before any accuracy can be claimed.

No Qt in this module, so it can be tested without opening a window.
To measure a saved recording from PowerShell:

    py -m app.analysis.intervals recordings/S001/S001_20261020_193742
"""

from dataclasses import dataclass, field

import numpy as np

BEFORE_S = 0.40          # the average beat starts this long before R...
AFTER_S = 0.60           # ...and ends this long after it
RR_TOLERANCE = 0.20      # leave out beats whose gap before or after is >20% off the
                         # typical gap: early beats, missed beats, artifacts
MIN_CORRELATION = 0.90   # leave out beats shaped unlike the first-pass average
MIN_BEATS = 20           # fewer usable beats than this: don't measure at all

SMOOTH_S = 0.008         # smooth the slope over 8 ms before using it
QRS_SLOPE_FRACTION = 0.10   # QRS starts/ends where the slope drops below 10% of
QUIET_S = 0.010             # its steepest value and stays there for 10 ms
QRS_SEARCH_S = 0.12         # look this far either side of R for the QRS edges
QS_SEARCH_S = 0.06          # Q and S troughs: lowest points within 60 ms of R
P_SLOPE_FRACTION = 0.10     # same idea for P, relative to the P wave's own slope
P_SEARCH_S = (0.30, 0.03)   # P is looked for 300-30 ms before QRS onset
P_SLOPE_SPAN_S = 0.06       # P's steepest slope: within 60 ms of the P peak
T_SEARCH_S = (0.04, 0.55)   # T is looked for from 40 ms after QRS end...
T_RR_FRACTION = 0.65        # ...to 550 ms after R, or 65% of the beat gap if sooner
T_TANGENT_S = 0.20          # steepest T downslope within 200 ms after its peak
MIN_T_FRACTION = 0.03       # a T wave under 3% of R's height is too flat to end reliably


@dataclass
class BeatIntervals:
    """Intervals of the average beat. None means 'could not be measured'."""
    n_beats: int
    rr_ms: float | None = None
    heart_rate_bpm: float | None = None
    p_duration_ms: float | None = None
    pr_interval_ms: float | None = None
    pr_segment_ms: float | None = None
    qrs_ms: float | None = None
    qt_ms: float | None = None
    qtc_bazett_ms: float | None = None
    qtc_fridericia_ms: float | None = None
    amplitudes: dict = field(default_factory=dict)   # P, R, T heights above baseline
    points: dict = field(default_factory=dict)       # boundary positions, in template samples
    template: np.ndarray | None = None               # the average beat itself
    r_index: int = 0                                 # where R sits in the template
    fs: float = 0.0


def average_beat(x, peaks, fs):
    """Median of the beats around each R peak, leaving out unusual ones.

    x: filtered signal. peaks: R-peak sample positions.
    Returns (template, r_index, beats_used, median_rr_samples), or
    (None, ...) if too few usable beats.
    """
    x = np.asarray(x, dtype=float)
    peaks = np.asarray(peaks, dtype=int)
    before, after = int(BEFORE_S * fs), int(AFTER_S * fs)
    if len(peaks) < 3:
        return None, before, 0, None

    rr = np.diff(peaks)
    typical = np.median(rr)
    regular = np.abs(rr - typical) <= RR_TOLERANCE * typical
    # A beat is kept only if the gaps on both sides of it are regular.
    keep = np.zeros(len(peaks), dtype=bool)
    keep[1:-1] = regular[:-1] & regular[1:]
    keep &= (peaks - before >= 0) & (peaks + after < len(x))

    beats = np.array([x[p - before:p + after] for p in peaks[keep]])
    if len(beats) < MIN_BEATS:
        return None, before, len(beats), typical

    first = np.median(beats, axis=0)
    similar = np.array([np.corrcoef(b, first)[0, 1] for b in beats]) >= MIN_CORRELATION
    beats = beats[similar]
    if len(beats) < MIN_BEATS:
        return None, before, len(beats), typical
    return np.median(beats, axis=0), before, len(beats), typical


def _slope(y, fs):
    """Slope (change per second), lightly smoothed."""
    d = np.gradient(y) * fs
    w = max(1, int(SMOOTH_S * fs))
    return np.convolve(d, np.ones(w) / w, mode="same")


def _edge(active, start, step, stop, quiet):
    """Walk from `start` in direction `step` until `active` has been False
    for `quiet` samples in a row; return the first quiet sample, or None."""
    run = 0
    i = start
    while (step < 0 and i >= stop) or (step > 0 and i <= stop):
        run = run + 1 if not active[i] else 0
        if run >= quiet:
            return i - step * (quiet - 1)
        i += step
    return None


def _trough(y, lo, hi):
    """Lowest point between lo and hi, if it is a real dip inside the range
    (not just the edge of the range); otherwise None."""
    i = lo + int(np.argmin(y[lo:hi + 1]))
    return i if lo < i < hi else None


def delineate(template, r, fs, rr_samples):
    """Find P, QRS and T boundaries on the average beat and turn them into intervals."""
    y = np.asarray(template, dtype=float)
    n = len(y)
    d = _slope(y, fs)
    ad = np.abs(d)
    ms = 1000.0 / fs
    quiet = max(1, int(QUIET_S * fs))
    points = {"r": r}

    # --- QRS: where the steep slopes around R begin and end. The search
    # starts from the Q and S troughs, not from R, because the slope is
    # briefly flat at the bottom of each trough.
    span = int(QRS_SEARCH_S * fs)
    lo, hi = max(1, r - span), min(n - 2, r + span)
    steepest = ad[lo:hi].max()
    active = ad >= QRS_SLOPE_FRACTION * steepest
    qs = int(QS_SEARCH_S * fs)
    q = _trough(y, r - qs, r)
    s = _trough(y, r, r + qs)
    # No distinct Q or S trough: start from the steepest part of R instead.
    if q is None:
        q = r - qs + int(np.argmax(d[r - qs:r + 1]))
    if s is None:
        s = r + int(np.argmin(d[r:r + qs + 1]))
    qrs_on = _edge(active, q, -1, lo, quiet)
    qrs_off = _edge(active, s, +1, hi, quiet)
    if qrs_on is None or qrs_off is None:
        return points, {}
    points.update(qrs_on=qrs_on, qrs_off=qrs_off)

    # Isoelectric level: the PR segment just before QRS onset.
    base = float(np.median(y[max(0, qrs_on - int(0.012 * fs)):qrs_on + 1]))
    amps = {"R": float(y[r] - base)}

    # --- P: the hump before QRS onset
    p_lo = max(1, qrs_on - int(P_SEARCH_S[0] * fs))
    p_hi = qrs_on - int(P_SEARCH_S[1] * fs)
    if p_hi - p_lo > quiet * 3:
        p_peak = p_lo + int(np.argmax(y[p_lo:p_hi]))
        p_height = y[p_peak] - base
        if p_height > 0.02 * amps["R"]:
            # Walk outwards from the steepest point on each side of the
            # peak, not from the peak itself: a flat-topped P would look
            # 'quiet' straight away.
            near = int(P_SLOPE_SPAN_S * fs)
            left = max(0, p_peak - near)
            rise = left + int(np.argmax(d[left:p_peak + 1]))
            fall = p_peak + int(np.argmin(d[p_peak:min(qrs_on, p_peak + near)]))
            p_steep = max(d[rise], -d[fall])
            p_active = ad >= P_SLOPE_FRACTION * p_steep
            p_on = _edge(p_active, rise, -1, max(1, p_lo - int(0.05 * fs)), quiet)
            p_off = _edge(p_active, fall, +1, qrs_on, quiet)
            points["p_peak"] = p_peak
            amps["P"] = float(p_height)
            if p_on is not None:
                points["p_on"] = p_on
            if p_off is not None:
                points["p_off"] = p_off

    # --- T: the biggest hump after QRS, measured against a straight line
    # drawn across the search window (so a sloping ST segment is not
    # mistaken for T); its end is found by the tangent method.
    t_lo = qrs_off + int(T_SEARCH_S[0] * fs)
    t_hi = min(n - 2, r + int(min(T_SEARCH_S[1], T_RR_FRACTION * rr_samples / fs) * fs))
    if t_hi - t_lo > quiet * 3:
        edge = max(1, int(0.02 * fs))
        start_level = float(np.median(y[t_lo:t_lo + edge]))
        end_level = float(np.median(y[t_hi - edge:t_hi]))
        line = np.linspace(start_level, end_level, t_hi - t_lo)
        t_peak = t_lo + int(np.argmax(np.abs(y[t_lo:t_hi] - line)))
        hump = y[t_peak] - line[t_peak - t_lo]
        polarity = np.sign(hump) or 1.0
        points["t_peak"] = t_peak
        amps["T"] = float(y[t_peak] - base)
        if abs(hump) < MIN_T_FRACTION * amps["R"]:
            k_hi = t_peak          # T too flat: its end can't be placed reliably
        else:
            k_hi = min(n - 2, t_peak + int(T_TANGENT_S * fs))
        # Steepest slope back towards the baseline after the peak.
        towards = -polarity * d[t_peak:k_hi]
        if len(towards) and towards.max() > 0:
            k = t_peak + int(np.argmax(towards))
            # Where the tangent at k reaches the level the signal settles
            # at after T (the TP segment, before the next P wave).
            t_off = k + (end_level - y[k]) / (d[k] / fs)
            if t_peak < t_off < n:
                points["t_off"] = int(round(t_off))

    def gap(a, b):
        return (points[b] - points[a]) * ms if a in points and b in points else None

    values = {
        "p_duration_ms": gap("p_on", "p_off"),
        "pr_interval_ms": gap("p_on", "qrs_on"),
        "pr_segment_ms": gap("p_off", "qrs_on"),
        "qrs_ms": gap("qrs_on", "qrs_off"),
        "qt_ms": gap("qrs_on", "t_off"),
        "amplitudes": amps,
    }
    return points, values


def measure(x, peaks, fs):
    """Average the beats in a filtered signal and measure the result."""
    template, r, used, rr = average_beat(x, peaks, fs)
    result = BeatIntervals(n_beats=used, r_index=r, fs=fs)
    if template is None:
        return result

    result.template = template
    result.rr_ms = rr * 1000.0 / fs
    result.heart_rate_bpm = 60000.0 / result.rr_ms
    points, values = delineate(template, r, fs, rr)
    result.points = points
    for name, value in values.items():
        setattr(result, name, value)

    if result.qt_ms is not None:
        rr_s = result.rr_ms / 1000.0
        result.qtc_bazett_ms = result.qt_ms / np.sqrt(rr_s)
        result.qtc_fridericia_ms = result.qt_ms / np.cbrt(rr_s)
    return result


def _print_report(path):
    """Load a WFDB recording, measure it and print the results."""
    from app.acquisition.record_loader import RecordLoader
    from app.analysis.r_peaks import pan_tompkins_detect
    from app.signal_processing.filters import preprocess

    channel = "ECG" if "recordings" in path.replace("\\", "/") else "MLII"
    loader = RecordLoader(path, channel_name=channel)
    signal, fs = loader.load()
    filtered = preprocess(signal, fs)
    result = measure(filtered, pan_tompkins_detect(filtered, fs), fs)

    def show(label, value, unit="ms"):
        text = "could not measure" if value is None else f"{value:.0f} {unit}"
        print(f"  {label:<20}{text}")

    print(f"{path}  ({len(signal) / fs:.0f} s, units: {loader.units})")
    print(f"  {'Beats averaged':<20}{result.n_beats}")
    show("Heart rate", result.heart_rate_bpm, "bpm")
    show("RR interval", result.rr_ms)
    show("P duration", result.p_duration_ms)
    show("PR interval", result.pr_interval_ms)
    show("PR segment", result.pr_segment_ms)
    show("QRS duration", result.qrs_ms)
    show("QT interval", result.qt_ms)
    show("QTc (Bazett)", result.qtc_bazett_ms)
    show("QTc (Fridericia)", result.qtc_fridericia_ms)
    decimals = 2 if loader.units == "mV" else 0
    for wave, height in result.amplitudes.items():
        print(f"  {wave + ' height':<20}{height:.{decimals}f} {loader.units}")


if __name__ == "__main__":
    import sys
    _print_report(sys.argv[1] if len(sys.argv) > 1 else "data/sample/100")