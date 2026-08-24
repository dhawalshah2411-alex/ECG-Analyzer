"""R-peak detection.

Two detectors are provided so their accuracy can be compared against
reference annotations:

- simple_detect: threshold and spacing constraints via scipy.find_peaks
- (Pan-Tompkins to follow)
"""

import numpy as np
from scipy import signal as sig

MIN_RR_SECONDS = 0.25    # 240 BPM ceiling — shorter gaps are not real beats
HEIGHT_FACTOR = 0.4      # threshold as a fraction of the signal's own scale


def simple_detect(x, fs, height_factor=HEIGHT_FACTOR,
                  min_rr=MIN_RR_SECONDS):
    """Detect R peaks by amplitude threshold and minimum spacing.

    Returns an array of sample indices.

    The threshold adapts to the signal's own amplitude rather than
    being a fixed millivolt value, so it does not depend on gain or
    electrode placement.
    """
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return np.array([], dtype=int)

    centred = x - np.median(x)
    scale = np.percentile(np.abs(centred), 98)
    if scale <= 0:
        return np.array([], dtype=int)

    peaks, _ = sig.find_peaks(
        centred,
        height=height_factor * scale,
        distance=max(1, int(min_rr * fs)),
    )
    return peaks


def rr_intervals(peaks, fs):
    """Return intervals between consecutive peaks, in seconds."""
    if len(peaks) < 2:
        return np.array([])
    return np.diff(peaks) / fs


def heart_rate(peaks, fs):
    """Mean heart rate in BPM from detected peaks."""
    rr = rr_intervals(peaks, fs)
    if len(rr) == 0:
        return 0.0
    return 60.0 / np.mean(rr)

    # --- Pan-Tompkins -----------------------------------------------------

QRS_BAND = (5.0, 15.0)      # Hz — where QRS energy concentrates
INTEGRATION_S = 0.150       # moving-window width, ~one QRS duration
REFRACTORY_S = 0.200        # minimum physiological gap between beats
SEARCHBACK_FACTOR = 1.66    # trigger searchback after this * mean RR


def _pt_transform(x, fs):
    """Band-pass, differentiate, square and integrate.

    Turns each QRS complex into a single smooth positive bump.
    """
    nyq = fs / 2.0
    low, high = QRS_BAND[0] / nyq, min(QRS_BAND[1] / nyq, 0.99)
    sos = sig.butter(2, [low, high], btype="bandpass", output="sos")
    band = sig.sosfiltfilt(sos, x)

    deriv = np.gradient(band) * fs
    squared = deriv ** 2

    width = max(1, int(INTEGRATION_S * fs))
    window = np.ones(width) / width
    integrated = np.convolve(squared, window, mode="same")
    return integrated


def pan_tompkins_detect(x, fs):
    """Detect R peaks using the Pan-Tompkins algorithm.

    Returns an array of sample indices, located on the original signal.

    Known limitation: the searchback scans the gap since the last
    accepted peak and recovers at most one beat from it. Consecutive
    missed beats within a single gap are not all recovered, which is
    the main source of remaining false negatives on records with
    varying beat amplitude (e.g. MIT-BIH 203).
    """
    x = np.asarray(x, dtype=float)
    if len(x) < int(fs):
        return np.array([], dtype=int)

    integrated = _pt_transform(x, fs)

    refractory = max(1, int(REFRACTORY_S * fs))
    candidates, _ = sig.find_peaks(integrated, distance=refractory)
    if len(candidates) == 0:
        return np.array([], dtype=int)

    # Robust initialisation over 5 s: percentiles rather than the raw
    # maximum, so a single artifact spike cannot set the level too high.
    init = integrated[:int(5 * fs)]
    if len(init) == 0:
        return np.array([], dtype=int)
    spki = float(np.percentile(init, 95))
    npki = float(np.percentile(init, 50))
    threshold = npki + 0.25 * (spki - npki)

    peaks = []
    rr_recent = []

    for c in candidates:
        value = integrated[c]

        if value > threshold:
            if peaks and (c - peaks[-1]) < refractory:
                continue
            peaks.append(int(c))
            spki = 0.125 * value + 0.875 * spki
            if len(peaks) > 1:
                rr_recent.append(peaks[-1] - peaks[-2])
                rr_recent = rr_recent[-8:]
        else:
            npki = 0.125 * value + 0.875 * npki

        threshold = npki + 0.25 * (spki - npki)

        # Searchback: scan the whole overdue gap at a halved threshold.
        if len(rr_recent) >= 2 and peaks:
            mean_rr = np.mean(rr_recent)
            if (c - peaks[-1]) > SEARCHBACK_FACTOR * mean_rr:
                window = candidates[
                    (candidates > peaks[-1] + refractory) & (candidates < c)
                ]
                if len(window):
                    best = window[np.argmax(integrated[window])]
                    if integrated[best] > threshold * 0.5:
                        peaks.append(int(best))
                        peaks.sort()
                        spki = 0.25 * integrated[best] + 0.75 * spki

    return _refine_to_signal_peak(x, np.array(sorted(set(peaks)), dtype=int), fs)
    
def _refine_to_signal_peak(x, peaks, fs, window_s=0.05):
    """Move each detection to the local maximum of the original signal.

    The integration stage introduces a small offset, so detections land
    near the QRS rather than exactly on the R peak.
    """
    if len(peaks) == 0:
        return peaks
    half = max(1, int(window_s * fs))
    refined = []
    for p in peaks:
        lo, hi = max(0, p - half), min(len(x), p + half + 1)
        refined.append(lo + int(np.argmax(x[lo:hi])))
    return np.array(sorted(set(refined)), dtype=int)
