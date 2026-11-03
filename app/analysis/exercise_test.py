"""Exercise test: rest, rounds of exercise and rest, then recovery - all measured.

The recording runs without a break through a fixed timetable of phases:

    rest before -> exercise 1 -> rest 1 -> ... -> exercise N -> recovery

Every phase is analysed, exercise included. Movement adds noise, so the
recording is judged in 5-second blocks (the same check as the Report
page) and only clean blocks are measured, leaving out 2 s on either side
of each noisy block as well; every phase says how much of it was usable.

No Qt, so it can be tested on synthetic recordings with a known answer:

    py -m pytest tests/test_exercise_test.py -v
"""

from dataclasses import dataclass, field

import numpy as np
from scipy import signal as sig

from app.analysis.intervals import BeatIntervals, measure
from app.analysis.r_peaks import pan_tompkins_detect, simple_detect
from app.analysis.recovery import (BEFORE_STOP_S, MIN_STOP_BEATS, POINT_HALF_S, STOP_WINDOW_S,
                                   Recovery, beat_rates, recovery_from_beats)
from app.analysis.report import BLOCK_S, _clean_blocks
from app.signal_processing.filters import preprocess

EDGE_S = 10.0             # heart rate "at the start / end" of a phase: its first / last 10 s
CURVE_HALF_S = 2.5        # heart-rate curve: once a second, the median of beats within 2.5 s
PEAK_AFTER_S = 5.0        # the peak can come just after a round ends: look 5 s past it
AFTER_S = 5.0             # heart rate at the end of the rest after a round: its last 5 s
                          # (the last round is followed by the recovery instead, and
                          # uses the recovery's own window: see analyse_exercise)
DEFAULT_REST_DROP_S = 60  # with no rests between rounds, compare drops over 60 s
FAST_WINDOW_S = 60.0      # "fast" average beat: the last 60 s of the final round...
AFTER_STOP_S = 30.0       # ...or, if too noisy, the first 30 s after it
FAST_CORRELATION = 0.80   # walking sway makes every beat a little less alike: on a
                          # synthetic walk their similarity to the average was about
                          # 0.87, under the 0.90 used at rest. The median of many
                          # beats still cancels the sway.
MIN_HRV_S = 60.0          # variability needs at least 60 s of clean resting signal
NORMAL_GAP = 0.20         # a gap >20% off its neighbours is not "normal-to-normal"
MIN_RECOVERY_S = 15.0     # a recovery shorter than this (stopped early) is not measured
CHECK_HIGHPASS_HZ = 5.0   # the check detector looks only above 5 Hz (see analyse_exercise)
EDGE_TRIM_S = 2.0         # beats this close to a noisy block are left out too (see analyse_exercise)
SHAPE_WINDOW_S = (0.10, 0.12)  # a beat's shape: its QRS, 100 ms before R to 120 ms after
UNUSUAL_BELOW = 0.6       # similarity to the usual resting beat under this = unusual shape
SIDE_S = 0.25             # ...unless the signal beside that window, out to 250 ms either side,
NOISY_SIDES = 0.6         # has a slope over 60% of the usual QRS's steepest: that is noise
QRS_HALF_S = 0.06         # the usual QRS's steepest slope is looked for within 60 ms of R


@dataclass
class Phase:
    kind: str             # "baseline", "exercise", "rest" or "recovery"
    label: str            # "Rest before", "Exercise 1", "Rest 1", "Recovery"
    round: int            # 0 for baseline and recovery
    start_s: float
    end_s: float

    @property
    def duration_s(self):
        return self.end_s - self.start_s


def build_phases(rest_before_s, rounds, exercise_s, rest_between_s, recovery_s):
    """The timetable of a test, in seconds from the start of the recording."""
    phases, t = [Phase("baseline", "Rest before", 0, 0.0, float(rest_before_s))], float(rest_before_s)
    for n in range(1, rounds + 1):
        phases.append(Phase("exercise", f"Exercise {n}", n, t, t + exercise_s))
        t += exercise_s
        if n < rounds and rest_between_s > 0:
            phases.append(Phase("rest", f"Rest {n}", n, t, t + rest_between_s))
            t += rest_between_s
    phases.append(Phase("recovery", "Recovery", 0, t, t + recovery_s))
    return phases


def phases_to_dicts(phases):
    return [dict(kind=p.kind, label=p.label, round=p.round,
                 start_s=round(p.start_s, 3), end_s=round(p.end_s, 3)) for p in phases]


def phases_from_dicts(items):
    return [Phase(d["kind"], d["label"], int(d["round"]), float(d["start_s"]),
                  float(d["end_s"])) for d in items]


@dataclass
class PhaseStats:
    phase: Phase
    usable: float                 # share of the phase with clean signal (0-1)
    beats: int                    # clean beats counted
    hr_start: float | None
    hr_end: float | None
    hr_mean: float | None
    hr_low: float | None          # lowest and highest of the heart-rate curve
    hr_high: float | None
    unusual: int | None           # beats shaped unlike the usual one; None during exercise


@dataclass
class RoundStats:
    round: int
    hr_start: float | None        # first 10 s of the round
    hr_end: float | None          # last 10 s of the round
    rise: float | None            # end - start
    peak: float | None            # highest point of the curve in the round
    hr_at_stop: float | None      # when the round ended: the same rule as the recovery
                                  # (the last 5 s before the end; see _stop_rate)
    stop_fallback: bool           # True: too few clean beats there, so the beats from
                                  # 3 s before to 5 s after were used (reads a little low)
    hr_after: float | None        # last 5 s of the rest that followed; for the last
                                  # round, the recovery's heart rate at the same time
    drop: float | None            # hr_at_stop - hr_after
    rest_s: float                 # how long that rest was


@dataclass
class ExerciseReport:
    duration_s: float
    fs: float
    phases: list
    stats: list                   # PhaseStats, one per phase
    rounds: list                  # RoundStats, one per exercise round
    usable: float                 # share of the whole test with clean signal
    clean_blocks: np.ndarray
    beat_t: np.ndarray            # every clean, believable beat: time (s)...
    beat_bpm: np.ndarray          # ...and heart rate (bpm)
    curve_t: np.ndarray           # heart-rate curve, one point a second
    curve_bpm: np.ndarray
    resting_bpm: float | None
    sdnn_ms: float | None
    rmssd_ms: float | None
    hrv_seconds: float            # clean resting signal the variability came from
    peak_bpm: float | None
    peak_t: float | None
    predicted_max_bpm: float | None
    peak_percent: float | None
    recovery: Recovery | None
    rest_beat: BeatIntervals
    fast_beat: BeatIntervals
    fast_source: str              # where the "fast" average beat came from
    unusual_t: np.ndarray = field(default_factory=lambda: np.array([]))  # their times (s)
    filtered: np.ndarray = field(default=None, repr=False)   # for the whole-ECG view
    notes: list = field(default_factory=list)


def _median(times, values, start, end, minimum=3):
    chosen = values[(times >= start) & (times <= end)]
    return float(np.median(chosen)) if len(chosen) >= minimum else None


def _stop_rate(times, bpm, stop_s):
    """Heart rate when a round ended, by the same rule as the recovery (recovery.py).

    The beats in the last 5 s before the end, if at least 3 are clean.
    Otherwise the beats from 3 s before to 5 s after, which read a little
    low because the heart is already slowing. The earlier version always
    used that second window: on the synthetic exercise test (six noise
    patterns) it read 0.6 bpm low at the end of every round, against
    0.03 bpm with this rule, and the last round disagreed with the
    recovery shown on the same screen.

    Returns (heart rate or None, whether the second window was used).
    """
    value = _median(times, bpm, stop_s - BEFORE_STOP_S, stop_s, MIN_STOP_BEATS)
    if value is not None:
        return value, False
    value = _median(times, bpm, stop_s - STOP_WINDOW_S[0], stop_s + STOP_WINDOW_S[1], 2)
    return value, value is not None


def _curve(times, bpm, end_s):
    """One point a second: the median heart rate of the beats within 2.5 s."""
    grid = np.arange(0.0, np.floor(end_s) + 1.0)
    lo = np.searchsorted(times, grid - CURVE_HALF_S)
    hi = np.searchsorted(times, grid + CURVE_HALF_S, side="right")
    curve = np.array([np.median(bpm[a:b]) if b - a >= 2 else np.nan
                      for a, b in zip(lo, hi)])
    return grid, curve


def _usable(clean_blocks, start, end):
    """Share of [start, end) covered by clean blocks."""
    t = np.arange(start, end, 0.5)
    if not len(t):
        return 0.0
    idx = np.minimum((t // BLOCK_S).astype(int), len(clean_blocks) - 1)
    return float(clean_blocks[idx].mean())


def _variability(beat_times):
    """SDNN and RMSSD (ms) from beats in one stretch of clean rest."""
    gaps = np.diff(beat_times) * 1000.0
    if len(gaps) < 20:
        return None, None
    normal = np.ones(len(gaps), dtype=bool)
    for i in range(len(gaps)):
        near = np.median(gaps[max(0, i - 5):i + 6])
        normal[i] = abs(gaps[i] - near) <= NORMAL_GAP * near
    nn = gaps[normal]
    if len(nn) < 20:
        return None, None
    both = normal[1:] & normal[:-1]
    steps = np.diff(gaps)[both]
    return float(np.std(nn, ddof=1)), (float(np.sqrt(np.mean(steps ** 2))) if len(steps) else None)


def _unusual_beats(x, peaks, fs, phases, usual):
    """Times of beats whose QRS is shaped unlike the usual resting beat's.

    Each beat's QRS (100 ms before R to 120 ms after) is compared with
    the same stretch of the average resting beat; a similarity
    (correlation) under 0.6 marks it unusual. Only clean parts of the
    still phases are judged; exercise is not, as movement changes every
    beat.

    Only the QRS, because the rest of the beat changes for ordinary
    reasons: the T wave changes with heart rate and after exercise, and
    when the heart is fast the beats on either side come into a longer
    window. The first version used 250 ms before R to 350 ms after, and
    flagged 17 ordinary beats in one minute of rest after exercise (S006,
    26 Oct) and normal beats next to an early one (S001, 22 Oct).

    A beat is not judged either if the signal beside its QRS has a slope
    over 60% of the usual QRS's steepest: P and T waves are never that
    steep, so it is noise, and a noisy beat is no evidence of a
    different kind of heartbeat.

    On the four real exercise tests so far, against the first version:
    S001's repeating differently shaped beat was still found 15 times of
    16 (the 16th was detected off its centre, so its own QRS looked like
    noise beside it), with 1 false mark instead of 4; S006 went from 19
    marks to 1, S002 from 5 to 0, S005 from 2 to 0.
    """
    if usual.template is None:
        return np.array([])
    lo, hi = int(SHAPE_WINDOW_S[0] * fs), int(SHAPE_WINDOW_S[1] * fs)
    side, q = int(SIDE_S * fs), max(1, int(QRS_HALF_S * fs))
    r = usual.r_index
    if r - max(lo, q) < 0 or r + max(hi, q) > len(usual.template):
        return np.array([])
    reference = usual.template[r - lo:r + hi]
    steepest = np.abs(np.diff(usual.template[r - q:r + q + 1])).max()
    still = [p for p in phases if p.kind != "exercise"]
    found = []
    for peak in peaks:
        t = peak / fs
        if peak - side < 0 or peak + side > len(x) or not any(p.start_s <= t < p.end_s for p in still):
            continue
        if np.corrcoef(x[peak - lo:peak + hi], reference)[0, 1] >= UNUSUAL_BELOW:
            continue
        slopes = np.abs(np.diff(x[peak - side:peak + side]))
        beside = max(slopes[:side - lo].max(), slopes[side + hi:].max())
        if beside > NOISY_SIDES * steepest:
            continue
        found.append(t)
    return np.array(found)


def analyse_exercise(raw, fs, phases, age=None):
    """Measure a whole exercise test. phases: the timetable (list of Phase)."""
    raw = np.asarray(raw, dtype=float)
    duration = len(raw) / fs
    filtered = preprocess(raw, fs)
    peaks = pan_tompkins_detect(filtered, fs)
    # Clean blocks are where two detectors agree. The second one finds beats
    # by height alone, and walking sways the trace about twice a second,
    # lifting T waves over its threshold: on a synthetic walk it rejected
    # the start of every round although the main detector found every
    # beat. Above 5 Hz the sway and the T waves are gone and the QRS stays.
    # (On the resting recordings so far this changes nothing.)
    sos = sig.butter(2, CHECK_HIGHPASS_HZ, "highpass", fs=fs, output="sos")
    check = simple_detect(sig.sosfiltfilt(sos, filtered), fs)
    # Two of the resting-report rules are switched off here. "Two beats
    # too close together" rejected a block for a single extra detection,
    # and "reject the neighbours too" then took 15 s around it: on the
    # first real exercise test, two-thirds of a perfectly readable rest
    # were thrown away. Odd gaps are dropped beat by beat instead (beat_rates).
    clean_blocks = _clean_blocks(raw, filtered, peaks, check, fs,
                                 gap_rule=False, widen=False)
    block_of = np.minimum(peaks // int(BLOCK_S * fs), len(clean_blocks) - 1)
    # Noise spills over the edge of a noisy block: the first or last beats
    # of a clean block beside it are often false detections. In one real
    # test (S006, 26 Oct) such beats made a peak of 143 bpm where the ECG
    # shows 110-120. So beats within 2 s of a noisy block are left out too.
    keep = clean_blocks[block_of].copy()
    times = peaks / fs
    for b in np.flatnonzero(~clean_blocks):
        keep &= ~((times >= b * BLOCK_S - EDGE_TRIM_S) & (times < (b + 1) * BLOCK_S + EDGE_TRIM_S))
    clean_peaks = peaks[keep]
    clean_times = clean_peaks / fs

    # A test stopped early keeps only the phases (or parts) it reached.
    planned_end = phases[-1].end_s if phases else duration
    phases = [Phase(p.kind, p.label, p.round, p.start_s, min(p.end_s, duration))
              for p in phases if p.start_s < duration - 1.0]

    beat_t, beat_bpm = beat_rates(clean_times)
    curve_t, curve_bpm = _curve(beat_t, beat_bpm, duration)

    def curve_between(start, end):
        part = curve_bpm[(curve_t >= start) & (curve_t <= end)]
        part = part[np.isfinite(part)]
        return part

    stats = []
    for p in phases:
        inside = (beat_t >= p.start_s) & (beat_t < p.end_s)
        part = curve_between(p.start_s, p.end_s)
        stats.append(PhaseStats(
            phase=p,
            usable=_usable(clean_blocks, p.start_s, p.end_s),
            beats=int(inside.sum()),
            hr_start=_median(beat_t, beat_bpm, p.start_s, p.start_s + EDGE_S),
            hr_end=_median(beat_t, beat_bpm, p.end_s - EDGE_S, p.end_s),
            hr_mean=float(beat_bpm[inside].mean()) if inside.sum() >= 3 else None,
            hr_low=float(part.min()) if len(part) else None,
            hr_high=float(part.max()) if len(part) else None,
            unusual=None,             # filled in once the usual beat is known
        ))

    rests = [p for p in phases if p.kind == "rest"]
    rest_len = rests[0].duration_s if rests else DEFAULT_REST_DROP_S
    rounds = []
    for i, p in enumerate(phases):
        if p.kind != "exercise":
            continue
        start = _median(beat_t, beat_bpm, p.start_s, p.start_s + EDGE_S)
        end = _median(beat_t, beat_bpm, p.end_s - EDGE_S, p.end_s)
        part = curve_between(p.start_s, p.end_s)
        at_stop, fallback = _stop_rate(beat_t, beat_bpm, p.end_s)
        nxt = phases[i + 1] if i + 1 < len(phases) else None
        after = None
        if nxt is not None and nxt.kind == "recovery":
            # The same window as the recovery's "after 60 s" (2.5 s either side),
            # so the last round and the recovery show the same number. A rest
            # can't use it: the next round starts when the rest ends.
            if nxt.end_s >= p.end_s + rest_len + POINT_HALF_S:
                after = _median(beat_t, beat_bpm, p.end_s + rest_len - POINT_HALF_S,
                                p.end_s + rest_len + POINT_HALF_S, 2)
        elif nxt is not None and nxt.end_s >= p.end_s + rest_len - 1.0:
            after = _median(beat_t, beat_bpm, p.end_s + rest_len - AFTER_S, p.end_s + rest_len)
        rounds.append(RoundStats(
            round=p.round, hr_start=start, hr_end=end,
            rise=(end - start) if start is not None and end is not None else None,
            peak=float(part.max()) if len(part) else None,
            hr_at_stop=at_stop, stop_fallback=fallback, hr_after=after,
            drop=(at_stop - after) if at_stop is not None and after is not None else None,
            rest_s=rest_len))

    # Peak: highest point of the curve during exercise or just after a round.
    peak_bpm = peak_t = None
    for p in phases:
        if p.kind == "exercise":
            window = (curve_t >= p.start_s) & (curve_t <= p.end_s + PEAK_AFTER_S)
            window &= np.isfinite(curve_bpm)
            if window.any():
                j = np.flatnonzero(window)[np.argmax(curve_bpm[window])]
                if peak_bpm is None or curve_bpm[j] > peak_bpm:
                    peak_bpm, peak_t = float(curve_bpm[j]), float(curve_t[j])
    predicted = 208.0 - 0.7 * age if age else None
    percent = 100.0 * peak_bpm / predicted if predicted and peak_bpm else None

    baseline = next((p for p in phases if p.kind == "baseline"), None)
    exercises = [p for p in phases if p.kind == "exercise"]
    recovery_phase = next((p for p in phases if p.kind == "recovery"), None)

    resting = sdnn = rmssd = None
    hrv_seconds = 0.0
    rest_beat = BeatIntervals(n_beats=0)
    if baseline is not None:
        resting = _median(beat_t, beat_bpm, baseline.end_s - 60.0, baseline.end_s, 10)
        hrv_seconds = _usable(clean_blocks, baseline.start_s, baseline.end_s) * baseline.duration_s
        in_rest = (clean_times >= baseline.start_s) & (clean_times < baseline.end_s)
        if hrv_seconds >= MIN_HRV_S:
            sdnn, rmssd = _variability(clean_times[in_rest])
        rest_beat = measure(filtered, clean_peaks[in_rest], fs)

    unusual_t = _unusual_beats(filtered, clean_peaks, fs, phases, rest_beat)
    if rest_beat.template is not None:
        for st in stats:
            if st.phase.kind != "exercise":
                st.unusual = int(((unusual_t >= st.phase.start_s)
                                  & (unusual_t < st.phase.end_s)).sum())

    recovery = None
    if (recovery_phase is not None and exercises and baseline is not None
            and recovery_phase.duration_s >= MIN_RECOVERY_S):
        recovery = recovery_from_beats(clean_times, exercises[0].start_s, recovery_phase.start_s)

    fast_beat, fast_source = BeatIntervals(n_beats=0), "not measured"
    if exercises:
        last = exercises[-1]
        near_end = (clean_times >= last.end_s - FAST_WINDOW_S) & (clean_times < last.end_s)
        fast_beat = measure(filtered, clean_peaks[near_end], fs, FAST_CORRELATION)
        fast_source = f"last {FAST_WINDOW_S:.0f} s of exercise {last.round}"
        if fast_beat.template is None and recovery_phase is not None:
            just_after = ((clean_times >= recovery_phase.start_s)
                          & (clean_times < recovery_phase.start_s + AFTER_STOP_S))
            fast_beat = measure(filtered, clean_peaks[just_after], fs, FAST_CORRELATION)
            fast_source = f"first {AFTER_STOP_S:.0f} s after exercise {last.round}"

    notes = []
    if duration < planned_end - 1.0:
        notes.append(f"Stopped early: {duration:.0f} s of the planned {planned_end:.0f} s.")
    return ExerciseReport(
        duration_s=duration, fs=fs, phases=phases, stats=stats, rounds=rounds,
        usable=float(clean_blocks.mean()), clean_blocks=clean_blocks,
        beat_t=beat_t, beat_bpm=beat_bpm, curve_t=curve_t, curve_bpm=curve_bpm,
        resting_bpm=resting, sdnn_ms=sdnn, rmssd_ms=rmssd, hrv_seconds=hrv_seconds,
        peak_bpm=peak_bpm, peak_t=peak_t, predicted_max_bpm=predicted, peak_percent=percent,
        recovery=recovery, rest_beat=rest_beat, fast_beat=fast_beat,
        fast_source=fast_source, unusual_t=unusual_t, filtered=filtered, notes=notes)