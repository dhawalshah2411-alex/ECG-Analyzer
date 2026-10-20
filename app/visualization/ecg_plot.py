"""ECG waveform display with a clinical-standard grid.

Gridlines follow ECG paper proportions horizontally: minor every 0.04 s,
major every 0.2 s.

Vertically, calibrated signals (mV) use the fixed clinical scale of
0.1 / 0.5 mV per square. Uncalibrated signals (raw ADC counts) have no
standard scale: their size depends on the person, the electrode
positions and the amplifier. So in counts the view fits itself to the
trace — it grows at once when the signal gets bigger, and shrinks only
after the signal has stayed small for a few seconds, so it does not
jump on every beat. The caption always states the current scale.

Supports raw, filtered and overlay views, markers on detected beats,
and a caption stating the scale.
"""

import time

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
FIT_MARGIN = 0.10       # headroom above and below the trace, as a fraction of its span
SHRINK_BELOW = 0.7      # shrink only if the trace needs less than 70% of the view...
SHRINK_AFTER_S = 3.0    # ...for at least this long

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
        self._small_since = None      # when the trace first became small enough to shrink for

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
            self._small_since = None
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

    def _fit_to(self, traces, now=None):
        """Grow or shrink the counts view so the traces fit.

        Grows immediately if any part of the trace would be cut off.
        Shrinks only after the trace has needed less than 70% of the view
        for SHRINK_AFTER_S seconds, so a single tall artifact does not
        leave the view zoomed out for good, and normal beats do not make
        it jump. `now` exists for testing; normally the clock is used.
        """
        data = [np.asarray(t, dtype=float) for t in traces if t is not None and len(t)]
        if not data:
            return
        data = np.concatenate(data)
        lo, hi = float(np.min(data)), float(np.max(data))
        span = max(hi - lo, MIN_COUNT_SPAN)
        middle = (lo + hi) / 2.0
        want_lo = middle - span * (0.5 + FIT_MARGIN)
        want_hi = middle + span * (0.5 + FIT_MARGIN)

        cur_lo, cur_hi = self._y_range
        if want_lo < cur_lo or want_hi > cur_hi:
            self._small_since = None
            self._set_count_range(want_lo, want_hi)
            return

        if (want_hi - want_lo) < SHRINK_BELOW * (cur_hi - cur_lo):
            now = time.monotonic() if now is None else now
            if self._small_since is None:
                self._small_since = now
            elif now - self._small_since >= SHRINK_AFTER_S:
                self._small_since = None
                self._set_count_range(want_lo, want_hi)
        else:
            self._small_since = None

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
            self._fit_to([main, extra])

    def set_markers(self, times, peak_values):
        """Place a marker above each detected beat."""
        times = np.asarray(times, dtype=float)
        peak_values = np.asarray(peak_values, dtype=float)
        offset = 0.06 * (self._y_range[1] - self._y_range[0])
        self.markers.setData(times, peak_values + offset)

    def set_caption(self, text):
        """Override the scale caption."""
        self.caption.setText(text)