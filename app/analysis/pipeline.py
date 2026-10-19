"""Analysis pipeline: raw samples in, everything the dashboard shows out.

Contains no GUI code. The same pipeline serves replay and live
acquisition, and can be tested without opening a window.

Pan-Tompkins produces every displayed number. A second, independent
detector runs alongside it purely to measure agreement (bSQI), which
becomes the signal-quality rating.
"""

from dataclasses import dataclass

import numpy as np

from app.analysis.heart_rate import HeartRateMonitor
from app.analysis.r_peaks import pan_tompkins_detect, simple_detect
from app.signal_processing.filters import MAINS_HZ, preprocess
from app.signal_processing.signal_quality import Quality, assess

MIN_SECONDS = 3.0        # below this, too little signal to analyse


@dataclass
class AnalysisResult:
    """One analysis pass. Beat positions are absolute sample numbers."""
    peak_samples: np.ndarray
    bpm: float | None
    rr_ms: float | None
    sdnn_ms: float | None
    trend_samples: np.ndarray
    trend_bpm: np.ndarray
    duration_s: float
    quality: Quality


class AnalysisPipeline:
    """Runs filtering, beat detection, rates and quality on a window."""

    def __init__(self, sample_rate, mains_hz=MAINS_HZ):
        self.fs = float(sample_rate)
        self.mains_hz = mains_hz
        self.hr = HeartRateMonitor(sample_rate)

    def process(self, raw, end_sample=None):
        """Analyse a window of raw samples.

        end_sample is the absolute number of the sample just after the
        last one in `raw` (the buffer's running total). It keeps beat
        positions correct as the window scrolls. Defaults to len(raw).
        """
        raw = np.asarray(raw, dtype=float)
        n = len(raw)
        if end_sample is None:
            end_sample = n
        offset = end_sample - n

        empty = np.array([], dtype=int)
        if n < MIN_SECONDS * self.fs:
            return AnalysisResult(empty, None, None, None, empty, np.array([]),
                                  n / self.fs, Quality("unknown", "", None))

        filtered = preprocess(raw, self.fs, mains=self.mains_hz)
        peaks = pan_tompkins_detect(filtered, self.fs)
        check = simple_detect(filtered, self.fs)     # second opinion, for bSQI

        bpm = self.hr.current_bpm(peaks)
        rr = self.hr.rr_intervals(peaks)
        sdnn = float(np.std(rr) * 1000.0) if len(rr) >= self.hr.window else None
        trend_idx, trend_bpm = self._trend(peaks)

        return AnalysisResult(
            peak_samples=peaks + offset,
            bpm=bpm,
            rr_ms=self.hr.current_rr(peaks),
            sdnn_ms=sdnn,
            trend_samples=trend_idx + offset,
            trend_bpm=trend_bpm,
            duration_s=n / self.fs,
            quality=assess(raw, self.fs, peaks, check, bpm),
        )

    def _trend(self, peaks):
        """Rolling-median heart rate at each beat, for the trend chart."""
        w = self.hr.window
        idx, bpm = [], []
        for i in range(w, len(peaks)):
            value = self.hr.current_bpm(peaks[i - w:i + 1])
            if value is not None:
                idx.append(peaks[i])
                bpm.append(value)
        return np.array(idx, dtype=int), np.array(bpm, dtype=float)