"""ECG waveform display with a clinical-standard grid.

Gridlines follow ECG paper proportions horizontally: minor every 0.04 s,
major every 0.2 s.

Vertically, calibrated signals (mV) use the fixed clinical scale of
0.1 / 0.5 mV per square. Uncalibrated signals (raw ADC counts) have no
standard scale: their size depends on the person, the electrode
positions and the amplifier. So in counts the view fits itself to the
size of a typical beat, and then holds still:

- the size is measured once every 1.5 s, and the median of the last
  8 measurements (12 s) is used, so one tall spike from touching an
  electrode cannot change the scale; the spike just runs off the edge
  for a moment;
- the view grows only if typical beats have been cut off for 3 s, and
  shrinks only if they have used under 35% of it for 15 s.

The first version grew at once for any spike and shrank 3 s later, so
the axis jumped during real recordings. The caption always states the
current scale.

Supports raw, filtered and overlay views, markers on detected beats,
and a caption stating the scale.
"""

import time
from collections import deque

import numpy as np
import pyqtgraph as pg
from PySide6.QtGui import QColor

MINOR_TIME = 0.04       # seconds
MAJOR_TIME = 0.20
MINOR_MV = 0.1          # millivolts
MAJOR_MV = 0.5
MINOR_COUNTS = 100      # ADC counts, uncalibrated (starting scale)
MAJOR_COUNTS = 500

# Fitting the view to uncalibrated signals
COUNT_STEPS = (100, 200, 250, 500, 1000, 2000)  # allowed counts per small square
TARGET_ROWS = 50        # at most this many small squares from bottom to top
MIN_COUNT_SPAN = 2000   # never zoom in further than this (avoids magnifying noise)
CHUNK_S = 1.5           # measure the trace's top and bottom once per 1.5 s
                        # (each chunk holds a beat at any rate above 40 bpm)
HISTORY_CHUNKS = 8      # typical size = median of the last 8 chunks (12 s)
STARTUP_CHUNKS = 3      # until 3 chunks are measured, fit at every chunk
HEADROOM = 0.25         # space above and below a typical beat, as a fraction of its height
GROW_AFTER = 2          # grow only if typical beats are cut off for 2 chunks in a row (3 s)
SHRINK_BELOW = 0.35     # shrink only if typical beats use under 35% of the view...
SHRINK_AFTER = 10       # ...for 10 chunks in a row (15 s)

PAPER = QColor(255, 251, 250)
MINOR_LINE = QColor(252, 234, 230)
MAJOR_LINE = QColor(242, 190, 180)
TRACE = QColor(15, 15, 15)
RAW_TRACE = QColor(150, 165, 190)
MARKER = QColor(163, 45, 45)
CAPTION = QColor(114, 36, 62)

MODES = ("raw", "filtered", "overlay")
CAPTION_MV = "Small square = 0.04 s × 0.1 mV"
CAPTION_COUNTS = "Uncalibrated · small square = 0.04 s × {step} counts"
CAPTION_CENTRED = " · grey trace: raw, centred"


class ECGPlot(pg.PlotWidget):
    """A PyQtGraph plot styled as clinical ECG paper."""

    def __init__(self, window_seconds=4.0, mv_range=(-1.5, 1.5),
                 count_range=(-2000, 2000), show_minor_grid=True,
                 mode="filtered", units="mV", parent=None):
        super().__init__(parent)
        self.window_seconds = window_seconds
        self.mv_range = mv_range
        self.count_range = count_range
        self.show_minor_grid = show_minor_grid
        self._mode = mode
        self._grid_items = []
        self._y_range = mv_range
        self._count_step = MINOR_COUNTS
        self._reset_fit()

        self.setBackground(PAPER)
        self.setAntialiasing(False)
        self.setMenuEnabled(False)
        self.setMouseEnabled(x=False, y=False)
        self.hideButtons()
        self.getPlotItem().layout.setContentsMargins(4, 12, 12, 4)
        self.setXRange(-window_seconds, 0.0, padding=0)
        self.setLabel("bottom", "Time", units="s")
        self.showGrid(x=False, y=False)

        self.raw_curve = self.plot(pen=pg.mkPen(RAW_TRACE, width=1.0))
        self.raw_curve.setZValue(1)
        self.curve = self.plot(pen=pg.mkPen(TRACE, width=1.4))
        self.curve.setZValue(2)

        self.markers = pg.ScatterPlotItem(symbol="t", size=10, pen=None,
                                          brush=pg.mkBrush(MARKER))
        self.markers.setZValue(3)
        self.addItem(self.markers)

        self.caption = pg.TextItem("", color=CAPTION, anchor=(0, 0))
        self.caption.setZValue(4)
        self.addItem(self.caption)

        self.set_units(units)
        self.set_mode(mode)

    # --- units and grid -------------------------------------------------

    def set_units(self, units):
        """Switch between calibrated ('mV') and uncalibrated (counts) display."""
        self.units = units
        if units == "mV":
            self.setLabel("left", "Amplitude", units="mV")
            self._apply_range(self.mv_range, MINOR_MV, MAJOR_MV)
        else:
            self.setLabel("left", "Amplitude (ADC counts)")
            self._count_step = MINOR_COUNTS
            self._reset_fit()
            self._apply_range(self.count_range, MINOR_COUNTS, MAJOR_COUNTS)

    @property
    def calibrated(self):
        return self.units == "mV"

    def _apply_range(self, y_range, minor, major):
        """Set the vertical range, redraw the grid and move the caption."""
        self._y_range = (float(y_range[0]), float(y_range[1]))
        self.setYRange(self._y_range[0], self._y_range[1], padding=0)
        self._draw_grid(minor, major)
        self._update_caption()

    def _update_caption(self):
        if self.calibrated:
            text = CAPTION_MV
        else:
            text = CAPTION_COUNTS.format(step=self._count_step)
            if self._mode == "overlay":
                text += CAPTION_CENTRED
        self.caption.setText(text)
        self.caption.setPos(-self.window_seconds, self._y_range[1])

    def _draw_grid(self, minor_step, major_step):
        """Draw the ECG paper grid behind the traces."""
        for item in self._grid_items:
            self.removeItem(item)
        self._grid_items = []

        y0, y1 = self._y_range
        minor_pen = pg.mkPen(MINOR_LINE, width=1)
        minor_pen.setCosmetic(True)
        major_pen = pg.mkPen(MAJOR_LINE, width=1)
        major_pen.setCosmetic(True)

        steps = [(MAJOR_TIME, major_step, major_pen)]
        if self.show_minor_grid:
            steps.insert(0, (MINOR_TIME, minor_step, minor_pen))

        for t_step, v_step, pen in steps:
            x = -self.window_seconds
            while x <= 1e-9:
                self._add_line(x, 90, pen)
                x += t_step

            y = np.ceil(y0 / v_step) * v_step
            while y <= y1 + 1e-9:
                self._add_line(y, 0, pen)
                y += v_step

    def _add_line(self, pos, angle, pen):
        line = pg.InfiniteLine(pos=pos, angle=angle, pen=pen)
        line.setZValue(-10)
        self.addItem(line)
        self._grid_items.append(line)

    # --- fitting uncalibrated signals -----------------------------------

    def _reset_fit(self):
        """Forget the measured beat size (new session, or a different view mode)."""
        self._tops = deque(maxlen=HISTORY_CHUNKS)
        self._bottoms = deque(maxlen=HISTORY_CHUNKS)
        self._chunk_started = None    # clock time the current chunk began
        self._cut_count = 0           # chunks in a row with typical beats cut off
        self._small_count = 0         # chunks in a row with typical beats too small

    def _fit_to(self, traces, times, now=None):
        """Keep the counts view fitted to a typical beat, changing it rarely.

        `now` exists for testing; normally the clock is used.
        """
        data = [np.asarray(t, dtype=float) for t in traces if t is not None and len(t)]
        if not data:
            self._reset_fit()
            return
        now = time.monotonic() if now is None else now

        if self._chunk_started is None:
            # Start of a session: fit at once so the first beats are on screen.
            self._chunk_started = now
            self._fit_beat(min(d.min() for d in data), max(d.max() for d in data))
            return
        if now - self._chunk_started < CHUNK_S:
            if not self._tops:
                # Before the first measurement, grow at once if anything is cut off.
                lo, hi = min(d.min() for d in data), max(d.max() for d in data)
                if lo < self._y_range[0] or hi > self._y_range[1]:
                    self._fit_beat(lo, hi)
            return
        self._chunk_started = now

        times = np.asarray(times, dtype=float)
        recent = times > times[-1] - CHUNK_S
        self._tops.append(max(d[recent].max() for d in data))
        self._bottoms.append(min(d[recent].min() for d in data))
        top, bottom = float(np.median(self._tops)), float(np.median(self._bottoms))

        cur_lo, cur_hi = self._y_range
        if len(self._tops) < STARTUP_CHUNKS:
            self._fit_beat(bottom, top)
        elif top > cur_hi or bottom < cur_lo:
            self._cut_count += 1
            self._small_count = 0
            if self._cut_count >= GROW_AFTER:
                self._fit_beat(bottom, top)
        elif top - bottom < SHRINK_BELOW * (cur_hi - cur_lo):
            self._small_count += 1
            self._cut_count = 0
            if self._small_count >= SHRINK_AFTER:
                self._fit_beat(bottom, top)
        else:
            self._cut_count = self._small_count = 0

    def _fit_beat(self, bottom, top):
        """Set the view around a beat from `bottom` to `top`, with headroom."""
        margin = HEADROOM * (top - bottom)
        lo, hi = bottom - margin, top + margin
        if hi - lo < MIN_COUNT_SPAN:
            middle = (lo + hi) / 2.0
            lo, hi = middle - MIN_COUNT_SPAN / 2.0, middle + MIN_COUNT_SPAN / 2.0
        self._cut_count = self._small_count = 0
        self._set_count_range(lo, hi)

    def _set_count_range(self, lo, hi):
        """Pick a grid step for this span, then snap the range to whole large squares."""
        span = hi - lo
        step = COUNT_STEPS[-1]
        for candidate in COUNT_STEPS:
            if span / candidate <= TARGET_ROWS:
                step = candidate
                break
        major = 5 * step
        lo = np.floor(lo / major) * major
        hi = np.ceil(hi / major) * major
        self._count_step = step
        self._apply_range((lo, hi), step, major)

    # --- view mode ------------------------------------------------------

    def set_mode(self, mode):
        """Set the view mode: 'raw', 'filtered' or 'overlay'."""
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        if mode != self._mode:
            self._reset_fit()         # raw and filtered sit at very different levels
        self._mode = mode
        self.raw_curve.setVisible(mode == "overlay")
        self._update_caption()

    @property
    def mode(self):
        return self._mode

    # --- data -----------------------------------------------------------

    def set_data(self, times, filtered, raw=None):
        """Update the displayed waveform(s).

        In counts, the overlay's grey raw trace is centred on zero, because
        raw ADC values sit around the middle of the converter's range
        (about 8,000) while the filtered trace sits around zero. Without
        centring, the two would be drawn far apart.
        """
        if self._mode == "raw" and raw is not None:
            main = raw
        else:
            main = filtered
        self.curve.setData(times, main)

        extra = None
        if self._mode == "overlay" and raw is not None:
            extra = np.asarray(raw, dtype=float)
            if not self.calibrated and len(extra):
                extra = extra - np.median(extra)
            self.raw_curve.setData(times, extra)

        if not self.calibrated:
            self._fit_to([main, extra], times)

    def set_markers(self, times, peak_values):
        """Place a marker above each detected beat."""
        times = np.asarray(times, dtype=float)
        peak_values = np.asarray(peak_values, dtype=float)
        offset = 0.06 * (self._y_range[1] - self._y_range[0])
        self.markers.setData(times, peak_values + offset)

    def set_caption(self, text):
        """Override the scale caption."""
        self.caption.setText(text)