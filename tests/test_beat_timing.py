"""Tests for the early-beat and long-gap rule in app/analysis/report.py.

Each test is a made-up series of gaps between beats (ms) with a known
answer, so no ECG is needed.
"""

import numpy as np

from app.analysis.report import _beat_timing


def timing(gaps, clean=None):
    gaps = np.array(gaps, dtype=float)
    clean = np.ones(len(gaps), dtype=bool) if clean is None else np.array(clean)
    early, long_gaps, normal = _beat_timing(gaps, clean)
    return early.tolist(), long_gaps.tolist(), normal


def test_breathing_is_not_flagged():
    """Gaps swinging 25% either way with each breath, but gradually: nothing to flag.

    The first version flagged both ends of every breath like this.
    """
    gaps = 800 + 200 * np.sin(2 * np.pi * np.arange(80) / 8)
    early, long_gaps, normal = timing(gaps)
    assert early == [] and long_gaps == []
    assert normal.all()                       # so all of it counts in the variability


def test_an_early_beat_and_its_pause():
    gaps = [800] * 10 + [500, 1100] + [800] * 10
    early, long_gaps, normal = timing(gaps)
    assert early == [10]
    assert long_gaps == []                    # the pause after it is not a long gap
    assert not normal[10] and not normal[11]  # neither counts in the variability


def test_a_long_pause():
    gaps = [800] * 10 + [1600] + [800] * 10
    early, long_gaps, _ = timing(gaps)
    assert long_gaps == [10]
    assert early == []                        # the normal gap after it is not early


def test_every_beat_in_a_run_of_alternating_early_beats():
    gaps = [800] * 10 + [500, 1100] * 3 + [800] * 10
    early, _, _ = timing(gaps)
    assert early == [10, 12, 14]


def test_no_clean_gap_before_means_no_judgement():
    gaps = [800] * 10 + [500, 1100] + [800] * 10
    clean = [True] * 9 + [False] + [True] * 12   # the gap before the early one is noisy
    early, _, _ = timing(gaps, clean)
    assert early == []
    