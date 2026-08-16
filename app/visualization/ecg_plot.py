"""ECG waveform display with a clinical-standard grid.

Renders at conventional ECG paper proportions: minor gridlines every
0.04 s / 0.1 mV, major gridlines every 0.2 s / 0.5 mV.
"""

import numpy as np
import pyqtgraph as pg
from PySide6.QtGui import QColor

MINOR_TIME = 0.04   # seconds
MAJOR_TIME = 0.20
MINOR_MV = 0.1      # millivolts
MAJOR_MV = 0.5

PAPER = QColor(255, 251, 250)
MINOR_LINE = QColor(252, 234, 230)
MAJOR_LINE = QColor(242, 190, 180)
TRACE = QColor(15, 15, 15)


class ECGPlot(pg.PlotWidget):
    """A PyQtGraph plot styled as clinical ECG paper."""

    def __init__(self, window_seconds=5.0, mv_range=(-1.5, 1.5),
                 show_minor_grid=True, parent=None):
        super().__init__(parent)
        self.window_seconds = window_seconds
        self.mv_range = mv_range
        self.show_minor_grid = show_minor_grid

        self.setBackground(PAPER)
        self.setAntialiasing(False)
        self.setMenuEnabled(False)
        self.setMouseEnabled(x=False, y=False)
        self.hideButtons()

        self.setXRange(-window_seconds, 0.0, padding=0)
        self.setYRange(mv_range[0], mv_range[1], padding=0)
        self.setLabel("bottom", "Time", units="s")
        self.setLabel("left", "Amplitude", units="mV")
        self.showGrid(x=False, y=False)

        self._draw_grid()
        self.curve = self.plot(pen=pg.mkPen(TRACE, width=1.4))

    def _draw_grid(self):
        """Draw the ECG paper grid behind the trace."""
        y0, y1 = self.mv_range

        minor_pen = pg.mkPen(MINOR_LINE, width=1)
        minor_pen.setCosmetic(True)
        major_pen = pg.mkPen(MAJOR_LINE, width=1)
        major_pen.setCosmetic(True)

        steps = [(MAJOR_TIME, MAJOR_MV, major_pen)]
        if self.show_minor_grid:
            steps.insert(0, (MINOR_TIME, MINOR_MV, minor_pen))

        for t_step, mv_step, pen in steps:
            x = -self.window_seconds
            while x <= 1e-9:
                line = pg.InfiniteLine(pos=x, angle=90, pen=pen)
                line.setZValue(-10)
                self.addItem(line)
                x += t_step

            y = np.ceil(y0 / mv_step) * mv_step
            while y <= y1 + 1e-9:
                line = pg.InfiniteLine(pos=y, angle=0, pen=pen)
                line.setZValue(-10)
                self.addItem(line)
                y += mv_step

    def set_data(self, times, values):
        """Update the displayed waveform."""
        self.curve.setData(times, values)