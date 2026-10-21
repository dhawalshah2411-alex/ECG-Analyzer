"""Recovery measurement, checked on a synthetic recording with a known answer.

The test builds a fake but realistic ECG: 2 minutes of rest, 2 minutes
of exercise buried in heavy movement noise, then 4 minutes of recovery
where the heart rate falls along a known curve. Because the true beat
times are known, the true answers are known too, and the app's
measurements from the noisy ECG must come out close to them.

Run with:  py -m pytest tests/test_recovery.py -v
"""

import numpy as np
import pytest

from app.analysis.recovery import measure_recovery, recovery_from_beats

FS = 500.0
REST, EXERCISE, RECOVERY = 120.0, 120.0, 240.0
RESTING_BPM, PEAK_BPM, TAU_S = 72.0, 150.0, 45.0


def heart_rate(t):
    """The true heart rate (bpm) at time t seconds into the recording."""
    start, stop = REST, REST + EXERCISE
    if t < start:
        return RESTING_BPM
    if t < stop:
        return RESTING_BPM + (PEAK_BPM - RESTING_BPM) * (t - start) / EXERCISE
    return RESTING_BPM + (PEAK_BPM - RESTING_BPM) * np.exp(-(t - stop) / TAU_S)


def true_beats():
    """Beat times that follow heart_rate(t) exactly."""
    beats, t = [], 0.5
    while t < REST + EXERCISE + RECOVERY:
        beats.append(t)
        t += 60.0 / heart_rate(t)
    return np.array(beats)


def synthetic_ecg(beats, seed=1):
    """A single-lead ECG (mV): P, Q, R, S and T waves at each beat, plus noise."""
    n = int((REST + EXERCISE + RECOVERY) * FS)
    t = np.arange(n) / FS
    x = np.zeros(n)
    for i, b in enumerate(beats):
        gap = beats[i + 1] - b if i + 1 < len(beats) else 0.8
        stretch = np.sqrt(gap)                      # waves come closer at high rates
        for centre_s, width_s, height in ((-0.16, 0.025, 0.15), (-0.025, 0.008, -0.10),
                                          (0.0, 0.010, 1.00), (0.025, 0.010, -0.25),
                                          (0.30 * stretch, 0.045, 0.30)):
            lo = int((b + centre_s - 4 * width_s) * FS)
            hi = int((b + centre_s + 4 * width_s) * FS)
            lo, hi = max(lo, 0), min(hi, n)
            x[lo:hi] += height * np.exp(-0.5 * ((t[lo:hi] - b - centre_s) / width_s) ** 2)
    rng = np.random.default_rng(seed)
    x += 0.01 * rng.standard_normal(n)                       # electronic noise
    x += 0.02 * np.sin(2 * np.pi * 50 * t)                   # mains hum
    exercise = (t >= REST) & (t < REST + EXERCISE)
    wander = np.cumsum(rng.standard_normal(n)) * 0.03        # movement: big slow wander,
    x[exercise] += (wander - wander[exercise].mean())[exercise]
    x[exercise] += 0.5 * rng.standard_normal(exercise.sum())   # muscle noise half as tall as R,
    spikes = rng.choice(np.flatnonzero(exercise), 300, replace=False)
    x[spikes] += rng.choice([-2.0, 2.0], 300)                # and cable-tug spikes twice as tall
    return x


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_noisy_ecg_matches_the_true_beats(seed):
    """Measuring the noisy ECG gives (almost) the same answers as the true beats.

    Five different random noise patterns, so one lucky pattern can't pass it.
    """
    beats = true_beats()
    truth = recovery_from_beats(beats, REST, REST + EXERCISE)
    measured = measure_recovery(synthetic_ecg(beats, seed), FS, REST, REST + EXERCISE)

    assert abs(measured.resting_bpm - truth.resting_bpm) < 1.0
    assert abs(measured.stop_bpm - truth.stop_bpm) < 3.0
    for point in (10, 60, 120):
        assert abs(measured.hr_at[point] - truth.hr_at[point]) < 3.0
        assert abs(measured.drop_at[point] - truth.drop_at[point]) < 3.0
    assert abs(measured.t30_s - truth.t30_s) < 0.05 * truth.t30_s
    assert abs(measured.back_to_rest_s - truth.back_to_rest_s) <= 3.0


def test_true_beats_give_the_textbook_answers():
    """With perfect beats, the numbers match the curve they were made from."""
    stop = REST + EXERCISE
    r = recovery_from_beats(true_beats(), REST, stop)

    assert abs(r.resting_bpm - RESTING_BPM) < 1.0
    # Heart rate 60 s after the stop, straight from the formula.
    expected_60 = heart_rate(stop + 60)
    assert abs(r.hr_at[60] - expected_60) < 1.5
    # Back within 10% of resting: solve 72 + 78 * exp(-t / 45) = 1.1 * 72.
    expected_back = -TAU_S * np.log(0.1 * RESTING_BPM / (PEAK_BPM - RESTING_BPM))
    assert abs(r.back_to_rest_s - expected_back) <= 3.0