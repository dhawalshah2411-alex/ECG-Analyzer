"""Tests for the unusual-shape check in app/analysis/exercise_test.py.

They reuse the synthetic exercise test from test_exercise_test.py and
change three beats at rest in known ways.
"""

import numpy as np

from app.analysis.exercise_test import analyse_exercise
from tests.test_exercise_test import FS, PHASES, synthetic_ecg, true_beats

BASELINE = 8000.0          # the synthetic signal's zero, in counts
MV = 3000.0                # counts per millivolt in the synthetic signal


def unusual_at_rest(raw):
    report = analyse_exercise(raw, FS, PHASES, age=49)
    return {s.phase.label: s.unusual for s in report.stats}["Rest before"]


def chosen_beats(beats):
    return beats[(beats > 30) & (beats < 100)][::20][:3]


def flip(raw, b):
    """Turn one beat upside down: a very different QRS."""
    lo, hi = int((b - 0.1) * FS), int((b + 0.4) * FS)
    raw[lo:hi] = 2 * BASELINE - raw[lo:hi]


def spike(raw, centre_s, width_s=0.010, height_mv=1.0):
    t = np.arange(len(raw)) / FS
    lo, hi = int((centre_s - 4 * width_s) * FS), int((centre_s + 4 * width_s) * FS)
    raw[lo:hi] += height_mv * MV * np.exp(-0.5 * ((t[lo:hi] - centre_s) / width_s) ** 2)


def test_a_different_qrs_is_found():
    beats = true_beats()
    raw = synthetic_ecg(beats)
    for b in chosen_beats(beats):
        flip(raw, b)
    assert unusual_at_rest(raw) == 3


def test_a_normal_beat_next_to_an_early_one_is_not_unusual():
    """The first version saw the early beat inside its window and flagged its neighbour."""
    beats = true_beats()
    early = chosen_beats(beats) + 0.30
    raw = synthetic_ecg(np.sort(np.concatenate([beats, early])))
    assert unusual_at_rest(raw) == 0


def test_a_different_qrs_in_noise_is_not_counted():
    """Spikes as steep as a QRS beside it mean noise, so the beat proves nothing."""
    beats = true_beats()
    raw = synthetic_ecg(beats)
    for b in chosen_beats(beats):
        flip(raw, b)
        spike(raw, b - 0.18)
        spike(raw, b + 0.18)
    assert unusual_at_rest(raw) == 0
    