"""Beat detection scored against cardiologists' annotations (MIT-BIH).

The four records in data/sample are scored the standard way: a detected
beat counts as correct if it lies within 150 ms of an annotated beat.

    sensitivity (Se): share of real beats that were found
    positive predictivity (PPV): share of detections that were real beats

The thresholds are the scores measured when this test was written, so
any later change to the detector that makes it worse will fail here.

Run with:  py -m pytest tests/test_detector.py -v
"""

import numpy as np
import pytest
import wfdb

from app.acquisition.record_loader import RecordLoader
from app.analysis.r_peaks import pan_tompkins_detect
from app.signal_processing.filters import preprocess

RECORDS = ("100", "105", "108", "203")
TOLERANCE_S = 0.150
BEAT_SYMBOLS = set("NLRBAaJSVrFejnE/fQ?")   # annotation symbols that mark a beat
MIN_SE, MIN_PPV = 98.5, 97.9                # percent, all four records together


def score(record):
    """(matched, annotated, detected) beats for one record."""
    path = f"data/sample/{record}"
    signal, fs = RecordLoader(path, channel_name="MLII").load()
    ann = wfdb.rdann(path, "atr")
    truth = np.array([s for s, sym in zip(ann.sample, ann.symbol) if sym in BEAT_SYMBOLS])
    found = pan_tompkins_detect(preprocess(signal, fs), fs)

    tolerance = int(TOLERANCE_S * fs)
    used = np.zeros(len(found), dtype=bool)
    matched = 0
    for beat in truth:
        i = np.searchsorted(found, beat)
        nearest = [j for j in (i - 1, i) if 0 <= j < len(found) and not used[j]
                   and abs(found[j] - beat) <= tolerance]
        if nearest:
            used[min(nearest, key=lambda j: abs(found[j] - beat))] = True
            matched += 1
    return matched, len(truth), len(found)


@pytest.fixture(scope="module")
def scores():
    return {record: score(record) for record in RECORDS}


def test_overall_accuracy(scores):
    matched = sum(m for m, _, _ in scores.values())
    annotated = sum(a for _, a, _ in scores.values())
    detected = sum(d for _, _, d in scores.values())
    se, ppv = 100 * matched / annotated, 100 * matched / detected
    print(f"\nAll four records: Se {se:.2f}%  PPV {ppv:.2f}%")
    assert se >= MIN_SE and ppv >= MIN_PPV


def test_clean_record_is_perfect(scores):
    """Record 100 is clean and regular: every beat found, nothing extra."""
    matched, annotated, detected = scores["100"]
    assert matched == annotated == detected