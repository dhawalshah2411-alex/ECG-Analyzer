"""Digital filters for ECG signal conditioning.

All filters use zero-phase forward-backward application, so peak
positions are preserved exactly. This matters because RR intervals
and therefore heart rate depend on peak timing.
"""

import numpy as np
from scipy import signal as sig

HIGHPASS_HZ = 0.5      # removes baseline wander
LOWPASS_HZ = 40.0      # removes high-frequency noise
MAINS_HZ = 50.0        # India, Europe, most of Asia (60.0 in the Americas)
NOTCH_Q = 30.0         # notch sharpness
ORDER = 2


def _min_length(order):
    """Minimum samples filtfilt can process for a given order."""
    return 3 * (2 * order + 1)


def bandpass(x, fs, low=HIGHPASS_HZ, high=LOWPASS_HZ, order=ORDER):
    """Band-pass filter, zero phase.

    Removes baseline wander below `low` and noise above `high`.
    Returns the input unchanged if it is too short to filter.
    """
    x = np.asarray(x, dtype=float)
    if len(x) < _min_length(order):
        return x

    nyquist = fs / 2.0
    high = min(high, nyquist * 0.95)
    if low >= high:
        raise ValueError(f"low ({low} Hz) must be below high ({high} Hz)")

    sos = sig.butter(order, [low / nyquist, high / nyquist],
                     btype="bandpass", output="sos")
    return sig.sosfiltfilt(sos, x)


def notch(x, fs, freq=MAINS_HZ, q=NOTCH_Q):
    """Notch filter, zero phase.

    Removes a narrow band around `freq` — mains interference.
    Returns the input unchanged if `freq` is above the Nyquist limit
    or the signal is too short.
    """
    x = np.asarray(x, dtype=float)
    if len(x) < _min_length(2) or freq >= fs / 2.0:
        return x

    b, a = sig.iirnotch(freq, q, fs)
    return sig.filtfilt(b, a, x)


def preprocess(x, fs, mains=MAINS_HZ):
    """Standard ECG conditioning: band-pass then notch."""
    return notch(bandpass(x, fs), fs, freq=mains)