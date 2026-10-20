"""ECG waveform display with a clinical-standard grid.

Gridlines follow ECG paper proportions horizontally: minor every 0.04 s,
major every 0.2 s. Vertically, calibrated signals (mV) use 0.1 / 0.5 mV;
uncalibrated signals (raw ADC counts) use 100 / 500 counts and say so.

Supports raw, filtered and overlay views, markers on detected beats,
and a caption stating the scale.
"""

import numpy as np
import pyqtgraph as pg
from PySide6.QtGui import QColor

MINOR_TIME = 0.04       # seconds
MAJOR_TIME = 0.20
MINOR_MV = 0.1          # millivolts
MAJOR_MV = 0.5
MINOR_COUNTS = 100      # ADC counts, uncalibrated
MAJOR_COUNTS = 500

PAPER = QColor(255, 251, 250)
MINOR_LINE = QColor(252, 234, 230)
MAJOR_LINE = QColor(242, 190, 180)
TRACE = QColor(15, 15, 15)
RAW_TRACE = QColor(150, 165, 190)
MARKER = QColor(163, 45, 45)
CAPTION = QColor(114, 36, 62)

MODES = ("raw", "filtered", "overlay")
CAPTION_MV = "Small square = 0.04 s × 0.1 mV"
CAPTION_COUNTS = "Uncalibrated · small square = 0.04 s × 100 counts"


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
            self._y_range = self.mv_range
            minor, major = MINOR_MV, MAJOR_MV
            self.setLabel("left", "Amplitude", units="mV")
            self.caption.setText(CAPTION_MV)
        else:
            self._y_range = self.count_range
            minor, major = MINOR_COUNTS, MAJOR_COUNTS
            self.setLabel("left", "Amplitude (ADC counts)")
            self.caption.setText(CAPTION_COUNTS)

        self.setYRange(self._y_range[0], self._y_range[1], padding=0)
        self.caption.setPos(-self.window_seconds, self._y_range[1])
        self._draw_grid(minor, major)

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

    # --- view mode ------------------------------------------------------

    def set_mode(self, mode):
        """Set the view mode: 'raw', 'filtered' or 'overlay'."""
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        self._mode = mode
        self.raw_curve.setVisible(mode == "overlay")

    @property
    def mode(self):
        return self._mode

    # --- data -----------------------------------------------------------

    def set_data(self, times, filtered, raw=None):
        """Update the displayed waveform(s)."""
        if self._mode == "raw" and raw is not None:
            self.curve.setData(times, raw)
        else:
            self.curve.setData(times, filtered)

        if self._mode == "overlay" and raw is not None:
            self.raw_curve.setData(times, raw)

    def set_markers(self, times, peak_values):
        """Place a marker above each detected beat."""
        times = np.asarray(times, dtype=float)
        peak_values = np.asarray(peak_values, dtype=float)
        offset = 0.06 * (self._y_range[1] - self._y_range[0])
        self.markers.setData(times, peak_values + offset)

    def set_caption(self, text):
        """Override the scale caption."""
        self.caption.setText(text)