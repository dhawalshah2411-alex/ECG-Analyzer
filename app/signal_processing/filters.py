"""Digital filters for ECG signal conditioning.

Two kinds, for two jobs:

- bandpass / notch / preprocess: zero-phase (forward then backward).
  Peak positions are preserved exactly, which matters because RR
  intervals and heart rate depend on peak timing. Used for all
  analysis. Because each point needs samples from both sides, the
  newest edge of a live signal comes out distorted.

- StreamingFilter: forward only, one chunk at a time, for the live
  display. No edge distortion, at the cost of a few milliseconds of
  delay and slight reshaping of slow waves — the same trade-off bedside
  monitors make in their "monitor mode".
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


class StreamingFilter:
    """Band-pass and notch for a live display, applied chunk by chunk.

    Remembers its internal state between calls, so a signal fed in
    pieces comes out exactly as if it had been filtered in one go —
    and every new piece can be shown at once, without waiting for
    future samples.

    For display only. Analysis must keep using preprocess(), whose
    zero-phase filtering preserves peak timing.
    """

    def __init__(self, fs, mains=MAINS_HZ, low=HIGHPASS_HZ, high=LOWPASS_HZ,
                 order=ORDER):
        nyquist = fs / 2.0
        high = min(high, nyquist * 0.95)
        sos = sig.butter(order, [low / nyquist, high / nyquist],
                         btype="bandpass", output="sos")
        if mains < nyquist:
            b, a = sig.iirnotch(mains, NOTCH_Q, fs)
            sos = np.vstack([sos, sig.tf2sos(b, a)])
        self._sos = sos
        self._unit_state = sig.sosfilt_zi(sos)
        self._state = None

    def reset(self):
        """Forget the past, e.g. when a new session starts."""
        self._state = None

    def process(self, chunk):
        """Filter the next chunk of samples and return it."""
        chunk = np.asarray(chunk, dtype=float)
        if len(chunk) == 0:
            return chunk
        if self._state is None:
            # Start as if the first value had always been there, so the
            # large constant offset of raw ADC counts (about 8,000)
            # doesn't produce a big swing on the first frames.
            self._state = self._unit_state * chunk[0]
        out, self._state = sig.sosfilt(self._sos, chunk, zi=self._state)
        return out