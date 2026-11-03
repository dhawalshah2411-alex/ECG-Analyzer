"""Tests for app/signal_processing/signal_quality.py on made-up 12-second windows.

Both "detectors" are given the true beat positions unless a test says
otherwise, so each test checks one rule at a time.
"""

import numpy as np

from app.signal_processing.signal_quality import JOLT_NOTE, TIPS_NOTE, assess

FS = 500.0
SECONDS = 12.0


def window(gap_s=0.8, seed=0):
    """A plain ECG-like trace: a narrow R wave every gap_s seconds, on 8000 counts."""
    t = np.arange(int(SECONDS * FS)) / FS
    beats = np.arange(0.4, SECONDS, gap_s)
    x = np.full(len(t), 8000.0)
    for b in beats:
        x += 3000.0 * np.exp(-0.5 * ((t - b) / 0.010) ** 2)
    x += 20.0 * np.random.default_rng(seed).standard_normal(len(t))
    return x, (beats * FS).astype(int)


def test_a_clean_window_is_good():
    x, beats = window()
    q = assess(x, FS, beats, beats, 75.0)
    assert q.state == "good"
    assert TIPS_NOTE not in q.reason and JOLT_NOTE not in q.reason


def test_cut_r_tips_stay_good_with_a_note():
    """The tips' height is lost, not the heart rate."""
    x, beats = window()
    x = np.minimum(x, 10000.0)                     # cut the top third off every R wave
    q = assess(x, FS, beats, beats, 75.0)
    assert q.state == "good"
    assert TIPS_NOTE in q.reason


def test_a_brief_jolt_to_the_limit_is_noted_not_poor():
    x, beats = window()
    start = int(5 * FS)
    x[start:start + int(0.3 * FS)] = x.max()       # 0.3 s stuck: 3% of the window
    q = assess(x, FS, beats, beats, 75.0)
    assert q.state != "poor"
    assert JOLT_NOTE in q.reason


def test_a_long_time_at_the_limit_is_poor():
    x, beats = window()
    start = int(5 * FS)
    x[start:start + int(1.5 * FS)] = x.max()       # 1.5 s stuck: 15% of the window
    q = assess(x, FS, beats, beats, 75.0)
    assert q.state == "poor"
    assert "stuck" in q.reason


def test_a_flat_signal_is_poor():
    q = assess(np.full(int(SECONDS * FS), 8000.0), FS, [], [], None)
    assert q.state == "poor"


def test_detectors_that_disagree_make_it_poor():
    x, beats = window()
    q = assess(x, FS, beats, beats[::2], 75.0)     # the second finds only half the beats
    assert q.state == "poor"
    assert q.bsqi is not None and q.bsqi < 0.667
    