"""Exercise-test analysis, checked on a synthetic test with a known answer.

The fake test follows the default timetable: 2 min rest, 3 rounds of
4 min exercise with 1 min rest between, then 5 min recovery. The heart
rate follows known curves (rising in each round, a little higher each
time, falling in each rest), with breathing-linked variability at rest.
Exercise adds walking-like noise, and round 2 has a 20-second burst of
heavy noise that must be detected and left out.

Because the true beat times are known, so are the true answers, and the
measurements from the noisy ECG must come out close to them.

Run with:  py -m pytest tests/test_exercise_test.py -v
"""

import numpy as np
import pytest

from app.analysis.exercise_test import (AFTER_S, EDGE_S, _median, _variability,
                                        analyse_exercise, build_phases)
from app.analysis.recovery import BEFORE_STOP_S, MIN_STOP_BEATS, beat_rates

FS = 500.0
PHASES = build_phases(rest_before_s=120, rounds=3, exercise_s=240,
                      rest_between_s=60, recovery_s=300)
END = PHASES[-1].end_s
RESTING, BREATH_S, BREATH_RR_S = 72.0, 4.0, 0.04    # 72 bpm, breathing every 4 s
ROUND_TARGET = (120.0, 125.0, 130.0)                # each round a little harder
REST_TARGET, RISE_TAU, FALL_TAU, RECOVERY_TAU = 95.0, 30.0, 25.0, 45.0
HEAVY_NOISE = (480.0, 500.0)                        # inside exercise 2


def heart_rate_curve():
    """True heart rate once every 10 ms, phase by phase."""
    t = np.arange(0.0, END, 0.01)
    hr = np.empty_like(t)
    level = RESTING
    for p in PHASES:
        inside = (t >= p.start_s) & (t < p.end_s)
        dt = t[inside] - p.start_s
        if p.kind == "baseline":
            target, tau = RESTING, 1.0
        elif p.kind == "exercise":
            target, tau = ROUND_TARGET[p.round - 1], RISE_TAU
        elif p.kind == "rest":
            target, tau = REST_TARGET, FALL_TAU
        else:
            target, tau = RESTING, RECOVERY_TAU
        hr[inside] = target + (level - target) * np.exp(-dt / tau)
        level = hr[inside][-1]
    return t, hr


def true_beats():
    t_grid, hr = heart_rate_curve()
    beats, t = [], 0.5
    while t < END - 0.5:
        beats.append(t)
        gap = 60.0 / np.interp(t, t_grid, hr)
        if t < PHASES[0].end_s:                      # breathing-linked variability at rest
            gap += BREATH_RR_S * np.sin(2 * np.pi * t / BREATH_S)
        t += gap
    return np.array(beats)


def synthetic_ecg(beats, seed=1):
    """P, Q, R, S and T at each beat (mV), plus noise; heavier during exercise."""
    n = int(END * FS)
    t = np.arange(n) / FS
    x = np.zeros(n)
    for i, b in enumerate(beats):
        gap = beats[i + 1] - b if i + 1 < len(beats) else 0.8
        stretch = np.sqrt(gap)                       # T comes closer at high rates
        for centre_s, width_s, height in ((-0.16, 0.025, 0.15), (-0.025, 0.008, -0.10),
                                          (0.0, 0.010, 1.00), (0.025, 0.010, -0.25),
                                          (0.30 * stretch, 0.045, 0.30)):
            lo = max(int((b + centre_s - 4 * width_s) * FS), 0)
            hi = min(int((b + centre_s + 4 * width_s) * FS), n)
            x[lo:hi] += height * np.exp(-0.5 * ((t[lo:hi] - b - centre_s) / width_s) ** 2)
    rng = np.random.default_rng(seed)
    x += 0.01 * rng.standard_normal(n) + 0.02 * np.sin(2 * np.pi * 50 * t)
    for p in PHASES:
        if p.kind != "exercise":
            continue
        inside = (t >= p.start_s) & (t < p.end_s)
        sway = 0.15 * np.sin(2 * np.pi * 1.8 * t[inside])          # steps, ~1.8 a second
        x[inside] += sway + 0.06 * rng.standard_normal(inside.sum())
        spikes = rng.choice(np.flatnonzero(inside), 15, replace=False)
        x[spikes] += rng.choice([-1.0, 1.0], 15)
    heavy = (t >= HEAVY_NOISE[0]) & (t < HEAVY_NOISE[1])
    x[heavy] += 0.6 * rng.standard_normal(heavy.sum())
    return 3000.0 * x + 8000.0                       # like the Arduino's counts


@pytest.fixture(scope="module")
def result():
    beats = true_beats()
    return beats, analyse_exercise(synthetic_ecg(beats), FS, PHASES, age=49)


def truth_rates(beats):
    return beat_rates(beats)


def truth_at_stop(t, bpm, stop_s):
    """The true heart rate when a round ends: its last 5 s, as the app measures it."""
    return _median(t, bpm, stop_s - BEFORE_STOP_S, stop_s, MIN_STOP_BEATS)


def test_every_round_rise_and_drop_match_the_truth(result):
    beats, report = result
    t, bpm = truth_rates(beats)
    assert len(report.rounds) == 3
    for r, p in zip(report.rounds, [p for p in PHASES if p.kind == "exercise"]):
        start = _median(t, bpm, p.start_s, p.start_s + EDGE_S)
        end = _median(t, bpm, p.end_s - EDGE_S, p.end_s)
        at_stop = truth_at_stop(t, bpm, p.end_s)
        if p.round < 3:                              # followed by a rest: its last 5 s
            after = _median(t, bpm, p.end_s + 60 - AFTER_S, p.end_s + 60)
        else:                                        # followed by the recovery: its window
            after = _median(t, bpm, p.end_s + 57.5, p.end_s + 62.5, 2)
        assert abs(r.hr_start - start) < 3.0
        assert abs(r.hr_end - end) < 3.0
        assert abs(r.hr_at_stop - at_stop) < 3.0
        assert not r.stop_fallback
        assert abs(r.drop - (at_stop - after)) < 3.0


def test_last_round_and_recovery_agree(result):
    """Both are on the same screen, so the stop and the fall 60 s later must match."""
    _beats, report = result
    last, recovery = report.rounds[-1], report.recovery
    assert last.hr_at_stop == pytest.approx(recovery.stop_bpm)
    assert last.drop == pytest.approx(recovery.drop_at[60])


def test_noisy_end_of_round_uses_the_beats_just_after():
    """If the last seconds of a round are too noisy, the next few seconds are used, and flagged."""
    beats = true_beats()
    raw = synthetic_ecg(beats)
    end_1 = [p for p in PHASES if p.kind == "exercise"][0].end_s
    rng = np.random.default_rng(7)
    noisy = slice(int((end_1 - 5.0) * FS), int(end_1 * FS))
    raw[noisy] += 3000.0 * 0.6 * rng.standard_normal(noisy.stop - noisy.start)
    report = analyse_exercise(raw, FS, PHASES, age=49)
    first = report.rounds[0]
    assert first.stop_fallback
    assert first.hr_at_stop is not None
    assert not any(r.stop_fallback for r in report.rounds[1:])


def test_later_rounds_end_higher(result):
    _beats, report = result
    ends = [r.hr_end for r in report.rounds]
    assert ends[0] < ends[1] < ends[2]


def test_heavy_noise_is_found_and_left_out(result):
    _beats, report = result
    by_label = {s.phase.label: s for s in report.stats}
    assert by_label["Rest before"].usable > 0.95
    assert by_label["Recovery"].usable > 0.95
    assert 0.6 < by_label["Exercise 2"].usable < 0.95


def test_peak_and_intensity(result):
    beats, report = result
    assert abs(report.peak_bpm - ROUND_TARGET[-1]) < 4.0
    assert report.predicted_max_bpm == pytest.approx(208 - 0.7 * 49)
    assert report.peak_percent == pytest.approx(100 * report.peak_bpm / report.predicted_max_bpm)


def test_resting_variability_matches_the_true_beats(result):
    beats, report = result
    rest = beats[beats < PHASES[0].end_s]
    sdnn, rmssd = _variability(rest)
    assert abs(report.sdnn_ms - sdnn) < 3.0
    assert abs(report.rmssd_ms - rmssd) < 5.0


def test_final_recovery_is_measured(result):
    beats, report = result
    t, bpm = truth_rates(beats)
    stop = PHASES[-1].start_s
    at_stop = truth_at_stop(t, bpm, stop)
    at_60 = _median(t, bpm, stop + 57.5, stop + 62.5, 2)
    assert abs(report.recovery.drop_at[60] - (at_stop - at_60)) < 3.0


def test_qt_shortens_when_the_heart_is_fast(result):
    _beats, report = result
    assert report.rest_beat.qt_ms is not None and report.fast_beat.qt_ms is not None
    assert report.fast_beat.qt_ms < report.rest_beat.qt_ms - 20


def test_stopped_early_keeps_what_was_reached():
    beats = true_beats()
    raw = synthetic_ecg(beats)[:int(540 * FS)]          # stopped during exercise 2
    report = analyse_exercise(raw, FS, PHASES, age=49)
    assert [p.label for p in report.phases] == ["Rest before", "Exercise 1", "Rest 1", "Exercise 2"]
    assert report.recovery is None
    assert report.notes and "Stopped early" in report.notes[0]


def test_unusual_beats_are_counted_while_still():
    """Beats turned upside down (a very different shape) are found at rest, not during exercise."""
    beats = true_beats()
    raw = synthetic_ecg(beats)
    chosen = {"Rest before": beats[(beats > 30) & (beats < 100)][::20][:3],
              "Exercise 1": beats[(beats > 200) & (beats < 300)][::40][:3],
              "Recovery": beats[(beats > 1000) & (beats < 1200)][::30][:2]}
    for times in chosen.values():
        for b in times:
            lo, hi = int((b - 0.1) * FS), int((b + 0.4) * FS)
            raw[lo:hi] = 2 * 8000.0 - raw[lo:hi]         # flip the beat about the baseline
    report = analyse_exercise(raw, FS, PHASES, age=49)
    by_label = {s.phase.label: s.unusual for s in report.stats}
    assert by_label["Rest before"] == 3
    assert by_label["Exercise 1"] is None                # not judged while moving
    assert by_label["Recovery"] == 2
    assert by_label["Rest 1"] == 0