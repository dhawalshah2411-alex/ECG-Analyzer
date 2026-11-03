"""Everything the Report page shows about one finished recording.

Runs the same detector the live screen uses, finds which parts of the
recording are clean, and measures only those: heart rate, the gaps
between beats, beats that arrive unusually early or late, variability,
and the intervals of the average beat. No Qt, so it can be tested
from PowerShell:

    py -m app.analysis.report recordings/S001/S001_20261020_193742
"""

from dataclasses import dataclass, field

import numpy as np

from app.analysis.intervals import BeatIntervals, measure
from app.analysis.r_peaks import pan_tompkins_detect, simple_detect
from app.signal_processing.filters import preprocess
from app.signal_processing.signal_quality import GOOD_BSQI, LIMIT_BAND, STUCK_S, bsqi

BLOCK_S = 5.0            # judge cleanliness in 5-second blocks
EDGE_PERCENTILE = 0.01   # the signal's top and bottom: the 0.01% most extreme samples are
                         # ignored, so one corrupted sample can't set them
NOISE_FACTOR = 3.0       # a block noisier than 3x the typical block = artifact
SWING_FACTOR = 1.5       # a swing 1.5x taller than a typical R wave = artifact
MIN_GAP_FRACTION = 0.5   # two "beats" closer than half the typical gap = artifact
EARLY = 0.80             # a gap 20% shorter than the one before AND the usual = an early beat
LONG = 1.20              # a gap 20% longer than the one before AND the usual = a long gap
USUAL_GAPS = 10          # "the usual gap": the median of the 10 clean gaps around it


@dataclass
class Report:
    duration_s: float
    fs: float
    beats_total: int
    clean_fraction: float            # share of the recording judged clean
    clean_blocks: np.ndarray         # one True/False per BLOCK_S block
    beat_times_s: np.ndarray         # every detected beat
    rr_times_s: np.ndarray           # time of each gap (at its second beat)
    rr_ms: np.ndarray                # every gap between beats
    rr_clean: np.ndarray             # True where both beats are in clean blocks
    heart_rate_bpm: float | None     # average over clean gaps
    heart_rate_range: tuple | None   # lowest and highest 10-beat average
    early_times_s: np.ndarray        # beats that came early (clean parts only)
    long_times_s: np.ndarray         # unusually long gaps not explained by an early beat
    sdnn_ms: float | None
    rmssd_ms: float | None
    intervals: BeatIntervals
    filtered: np.ndarray = field(default=None, repr=False)   # for the whole-ECG view


def _rail_runs(x, fs):
    """Boolean mask of samples where the signal is stuck at its top or bottom.

    Stuck means within LIMIT_BAND of the signal's own top or bottom for
    STUCK_S (50 ms) or longer: the amplifier is saturated, because an
    electrode is lifting or the baseline drifted out of range. A saturated
    amplifier jitters a few counts below its limit (16,370-16,383 in a
    real recording), hence the band rather than an exact value.

    R-wave tips that touch the limit for a few milliseconds are not
    marked: the beat's timing survives clipping (see signal_quality.py).
    """
    run = max(2, int(STUCK_S * fs))
    top = np.percentile(x, 100 - EDGE_PERCENTILE)
    bottom = np.percentile(x, EDGE_PERCENTILE)
    band = LIMIT_BAND * (top - bottom)
    mask = np.zeros(len(x), dtype=bool)
    for at in (x >= top - band, x <= bottom + band):
        edges = np.diff(np.concatenate(([0], at.astype(int), [0])))
        for start, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
            if end - start >= run:
                mask[start:end] = True
    return mask


def _clean_blocks(raw, filtered, peaks, check, fs, gap_rule=True, widen=True):
    """Mark each block clean or not: no rail-sticking, normal noise, detectors agree.

    gap_rule: also reject a block with two "beats" closer than half the
    typical gap. widen: also reject the blocks either side of a rejected one.
    Both suit a still, resting recording; the exercise test turns them off
    (see app/analysis/exercise_test.py).
    """
    block = int(BLOCK_S * fs)
    n_blocks = max(1, len(raw) // block)
    rails = _rail_runs(raw, fs)
    noise = np.array([np.std(np.diff(filtered[b * block:(b + 1) * block]))
                      for b in range(n_blocks)])
    typical_noise = np.median(noise)
    typical_r = np.median(np.abs(filtered[peaks])) if len(peaks) else 0.0
    typical_gap = np.median(np.diff(peaks)) if len(peaks) > 1 else 0.0
    clean = np.ones(n_blocks, dtype=bool)
    for b in range(n_blocks):
        lo, hi = b * block, (b + 1) * block
        a = peaks[(peaks >= lo) & (peaks < hi)]
        c = check[(check >= lo) & (check < hi)]
        agreement = bsqi(a, c, fs)
        too_close = (gap_rule and len(a) > 1
                     and np.diff(a).min() < MIN_GAP_FRACTION * typical_gap)
        too_tall = np.abs(filtered[lo:hi]).max() > SWING_FACTOR * typical_r
        if (rails[lo:hi].any() or noise[b] > NOISE_FACTOR * typical_noise
                or too_close or too_tall
                or agreement is None or agreement < GOOD_BSQI):
            clean[b] = False
    if not widen:
        return clean
    # A block next to an artifact is often disturbed too.
    widened = clean.copy()
    widened[1:] &= clean[:-1]
    widened[:-1] &= clean[1:]
    return widened


def _beat_timing(rr, rr_clean):
    """Sort the clean gaps into: ending in an early beat, unusually long, or normal.

    A beat is early if its gap is at least 20% shorter than BOTH the gap
    just before it and the usual gap (the median of the 10 clean gaps
    around it). A gap is long if it is at least 20% longer than both.

    Needing both is what tells an early beat or a pause from breathing.
    Breathing speeds the heart up and slows it down gradually, a few
    percent a beat, so each gap stays close to the one before it even
    when it drifts more than 20% from the usual. The first version
    compared with the usual gap only, and called ordinary breathing in a
    healthy young adult (S005, 24 Oct: gaps of 714, 770 and 828 ms) three
    long gaps. Those gaps were also left out of the variability, which
    made it read too low: breathing is part of what SDNN and RMSSD measure.

    The gap before may be the pause after an early beat, so in a run of
    alternating early beats every one is found. A gap whose previous gap
    isn't clean can't be judged this way, so it is counted as normal. The
    pause after an early beat is not counted as normal either way.

    Checked on the four MIT-BIH records here against the cardiologists'
    marks: it found 58 of the 66 premature beats in clean parts (the first
    version: 60) with half the flags on beats that weren't premature (10,
    against 20, nearly all in record 203, whose rhythm is irregular
    throughout), and none of the 8 false flags the first version put on
    our own six resting recordings.

    Returns (indices of early-beat gaps, indices of long gaps, normal mask).
    """
    rr = np.asarray(rr, dtype=float)
    normal = np.asarray(rr_clean, dtype=bool).copy()
    idx = np.flatnonzero(rr_clean)
    good = rr[idx]
    half = USUAL_GAPS // 2
    early, long_gaps = [], []
    for j, i in enumerate(idx):
        if not normal[i]:
            continue                                  # the pause after an early beat
        if i == 0 or not rr_clean[i - 1]:
            continue                                  # nothing clean to compare with
        usual = np.median(good[max(0, j - half):j + half + 1])
        before = rr[i - 1]
        if rr[i] < EARLY * before and rr[i] < EARLY * usual:
            early.append(i)
            normal[i] = False
            if i + 1 < len(rr):
                normal[i + 1] = False                 # the pause after an early beat
        elif rr[i] > LONG * before and rr[i] > LONG * usual:
            long_gaps.append(i)
            normal[i] = False
    return np.array(early, dtype=int), np.array(long_gaps, dtype=int), normal


def build_report(raw, fs):
    """Analyse a whole recording (raw samples) and return a Report."""
    raw = np.asarray(raw, dtype=float)
    filtered = preprocess(raw, fs)
    peaks = pan_tompkins_detect(filtered, fs)
    check = simple_detect(filtered, fs)
    clean_blocks = _clean_blocks(raw, filtered, peaks, check, fs)

    block = int(BLOCK_S * fs)
    beat_clean = clean_blocks[np.minimum(peaks // block, len(clean_blocks) - 1)]
    beat_times = peaks / fs
    rr = np.diff(peaks) / fs * 1000.0
    rr_clean = beat_clean[1:] & beat_clean[:-1]
    good = rr[rr_clean]

    heart_rate = hr_range = sdnn = rmssd = None
    early, long_gaps = [], []
    normal = rr_clean.copy()           # gaps between two normally-timed beats
    if len(good) >= 10:
        heart_rate = 60000.0 / good.mean()
        rolling = np.convolve(good, np.ones(10) / 10, mode="valid")
        hr_range = (60000.0 / rolling.max(), 60000.0 / rolling.min())
        early_i, long_i, normal = _beat_timing(rr, rr_clean)
        early = beat_times[early_i + 1]
        long_gaps = beat_times[long_i + 1]
        # Variability uses only gaps between normally-timed beats ("NN").
        nn = rr[normal]
        if len(nn) >= 10:
            sdnn = float(np.std(nn, ddof=1))
            both = normal[1:] & normal[:-1]
            steps = np.diff(rr)[both]
            rmssd = float(np.sqrt(np.mean(steps ** 2))) if len(steps) else None

    # The average beat uses clean beats only.
    intervals = measure(filtered, peaks[beat_clean], fs)

    return Report(
        duration_s=len(raw) / fs,
        fs=fs,
        beats_total=len(peaks),
        clean_fraction=float(clean_blocks.mean()),
        clean_blocks=clean_blocks,
        beat_times_s=beat_times,
        rr_times_s=beat_times[1:],
        rr_ms=rr,
        rr_clean=rr_clean,
        heart_rate_bpm=heart_rate,
        heart_rate_range=hr_range,
        early_times_s=np.array(early),
        long_times_s=np.array(long_gaps),
        sdnn_ms=sdnn,
        rmssd_ms=rmssd,
        intervals=intervals,
        filtered=filtered,
    )


def _print(path, sex=None):
    """Load a WFDB recording and print its report with reference ranges."""
    from app.acquisition.record_loader import RecordLoader
    from app.analysis.references import reference

    channel = "ECG" if "recordings" in path.replace("\\", "/") else "MLII"
    loader = RecordLoader(path, channel_name=channel)
    signal, fs = loader.load()
    r = build_report(signal, fs)
    iv = r.intervals

    def row(label, value, ref_name=None, unit="ms"):
        text = "could not measure" if value is None else f"{value:.0f} {unit}"
        ref = reference(ref_name, sex) if ref_name else None
        print(f"  {label:<22}{text:<20}{ref.text if ref else ''}")

    print(f"{path}  ({r.duration_s:.0f} s)")
    print(f"  {'Clean part':<22}{r.clean_fraction:.0%} of the recording")
    print(f"  {'Beats found':<22}{r.beats_total}   (average beat built from {iv.n_beats})")
    row("Heart rate", r.heart_rate_bpm, "heart_rate", "bpm")
    if r.heart_rate_range:
        low, high = r.heart_rate_range
        print(f"  {'  lowest - highest':<22}{low:.0f} - {high:.0f} bpm (10-beat averages)")
    for label, times in (("Early beats", r.early_times_s), ("Long gaps", r.long_times_s)):
        where = f"  at {', '.join(f'{t:.0f} s' for t in times[:8])}" if len(times) else ""
        more = " ..." if len(times) > 8 else ""
        print(f"  {label:<22}{len(times)}{where}{more}")
    row("SDNN", r.sdnn_ms)
    row("RMSSD", r.rmssd_ms)
    row("P duration", iv.p_duration_ms, "p_duration")
    row("PR interval", iv.pr_interval_ms, "pr_interval")
    row("PR segment", iv.pr_segment_ms)
    row("QRS duration", iv.qrs_ms, "qrs")
    row("QT interval", iv.qt_ms)
    row("QTc (Bazett)", iv.qtc_bazett_ms, "qtc")
    row("QTc (Fridericia)", iv.qtc_fridericia_ms, "qtc")


if __name__ == "__main__":
    import sys
    _print(sys.argv[1] if len(sys.argv) > 1 else "data/sample/100",
           sys.argv[2] if len(sys.argv) > 2 else None)