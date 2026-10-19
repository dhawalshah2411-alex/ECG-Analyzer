"""Main application window: the ECG dashboard."""

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QMainWindow, QPushButton, QVBoxLayout, QWidget)

from app.ui import theme
from app.ui.widgets import MetricCard, QualityCard
from app.visualization.ecg_plot import ECGPlot

WINDOW_SECONDS = 4.0     # width of the ECG view
TREND_SECONDS = 60       # width of the heart-rate trend


class MainWindow(QMainWindow):
    """Dashboard: header, ECG and trend on the left, metrics on the right."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ECG Analyzer")
        self.resize(1280, 760)
        self.setMinimumSize(1000, 620)

        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        root.addLayout(self._build_body(), 1)
        root.addWidget(self._build_controls())

    # --- header -------------------------------------------------------

    def _build_header(self):
        bar = QFrame()
        bar.setObjectName("panel")

        heart = QLabel("♥")
        heart.setStyleSheet(f"color: {theme.ACCENT}; font-size: 18px;")
        title = QLabel("ECG Analyzer")
        title.setStyleSheet("font-size: 15px; font-weight: 600;")

        self._status_dot = QLabel()
        self._status_dot.setFixedSize(10, 10)
        self._source_label = QLabel()
        self._source_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 13px;")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(8)
        layout.addWidget(heart)
        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(self._status_dot)
        layout.addWidget(self._source_label)

        self.set_source("No source", active=False)
        return bar

    def set_source(self, text, active):
        """Update the header's source description and status dot."""
        colour = "#3B6D11" if active else theme.TEXT_MUTED
        self._status_dot.setStyleSheet(f"background: {colour}; border-radius: 5px;")
        self._source_label.setText(text)

    # --- body ---------------------------------------------------------

    def _build_body(self):
        self.ecg_plot = ECGPlot(window_seconds=WINDOW_SECONDS, mv_range=(-1.5, 1.5))
        self.trend_plot, self.trend_curve = self._build_trend_plot()

        left = QVBoxLayout()
        left.setSpacing(10)
        left.addWidget(self.ecg_plot, 1)
        left.addWidget(self.trend_plot)

        self.hr_card = MetricCard("Heart rate", "bpm", value_size=34)
        self.rr_card = MetricCard("RR interval", "ms")
        self.sdnn_card = MetricCard("Variability (SDNN)", "ms")
        self.quality_card = QualityCard()

        right = QVBoxLayout()
        right.setSpacing(10)
        for widget in (self.hr_card, self.rr_card, self.sdnn_card, self.quality_card):
            right.addWidget(widget)
        right.addStretch()

        right_column = QWidget()
        right_column.setLayout(right)
        right_column.setFixedWidth(220)

        body = QHBoxLayout()
        body.setContentsMargins(18, 14, 18, 14)
        body.setSpacing(14)
        body.addLayout(left, 1)
        body.addWidget(right_column)
        return body

    def _build_trend_plot(self):
        plot = pg.PlotWidget()
        plot.setBackground(theme.CARD_BG)
        plot.setFixedHeight(120)
        plot.setMenuEnabled(False)
        plot.setMouseEnabled(x=False, y=False)
        plot.hideButtons()
        plot.setXRange(-TREND_SECONDS, 0, padding=0)
        plot.setYRange(40, 140, padding=0)
        plot.setLabel("left", "BPM")
        plot.setLabel("bottom", "Time", units="s")
        plot.showGrid(x=False, y=True, alpha=0.15)
        curve = plot.plot(pen=pg.mkPen(theme.ACCENT, width=2))
        return plot, curve

    # --- control bar --------------------------------------------------

    def _build_controls(self):
        bar = QFrame()
        bar.setObjectName("panel")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(8)

        view_label = QLabel("View")
        view_label.setObjectName("cardLabel")
        layout.addWidget(view_label)

        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        for mode in ("raw", "filtered", "overlay"):
            button = QPushButton(mode.capitalize())
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked, m=mode: self.ecg_plot.set_mode(m))
            self._view_group.addButton(button)
            layout.addWidget(button)
            if mode == self.ecg_plot.mode:
                button.setChecked(True)

        layout.addStretch()
        self._filter_label = QLabel("Filter 0.5–40 Hz · notch 50 Hz")
        self._filter_label.setObjectName("muted")
        layout.addWidget(self._filter_label)
        return bar