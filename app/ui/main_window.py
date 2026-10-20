"""Main application window: the ECG dashboard."""

from datetime import datetime

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QMainWindow, QPushButton, QVBoxLayout, QWidget)

from app.analysis.pipeline import AnalysisPipeline
from app.database.session_store import SubjectRegistry, save_session
from app.signal_processing.filters import preprocess
from app.ui import theme
from app.ui.recording_dialog import RecordingDialog
from app.ui.widgets import MetricCard, QualityCard, RecordingCard, format_mmss
from app.visualization.ecg_plot import ECGPlot

WINDOW_SECONDS = 4.0          # width of the ECG view
TREND_SECONDS = 60            # width of the heart-rate trend
DRAW_INTERVAL_MS = 33         # redraw about 30 times a second
ANALYSIS_INTERVAL_MS = 500    # full analysis twice a second
SETTLE_SECONDS = 15           # signal shown but not saved before recording;
                              # quality needs 10 s, so this leaves 5 s to act
FILTER_NOTE = "bandpass 0.5-40 Hz, notch 50 Hz (display only; saved signal is raw)"


class MainWindow(QMainWindow):
    """Dashboard with a session flow: idle, settling, recording."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ECG Analyzer")
        self.resize(1280, 800)
        self.setMinimumSize(1000, 660)

        self._source = None
        self._buffer = None
        self._fs = None
        self._units = "mV"
        self._description = ""
        self._pipeline = None
        self._result = None

        self._phase = "idle"          # "idle", "settling" or "recording"
        self._session = None
        self._settle_start = 0
        self._registry = SubjectRegistry()

        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        root.addLayout(self._build_body(), 1)
        root.addWidget(self._build_controls())

        self._draw_timer = QTimer(self)
        self._draw_timer.timeout.connect(self._redraw)
        self._analysis_timer = QTimer(self)
        self._analysis_timer.timeout.connect(self._analyse)

    # --- header -------------------------------------------------------

    def _build_header(self):
        bar = QFrame()
        bar.setObjectName("panel")

        heart = QLabel("♥")
        heart.setStyleSheet(f"color: {theme.ACCENT}; font-size: 18px;")
        title = QLabel("ECG Analyzer")
        title.setStyleSheet("font-size: 15px; font-weight: 600;")

        self._rec_label = QLabel("● REC")
        self._rec_label.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: 13px; font-weight: 600;")
        self._rec_label.hide()

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
        layout.addWidget(self._rec_label)
        layout.addSpacing(12)
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
        self.sdnn_card = MetricCard("Variability (SDNN)", "ms · 60 s")
        self.quality_card = QualityCard()
        self.recording_card = RecordingCard()

        right = QVBoxLayout()
        right.setSpacing(10)
        for widget in (self.hr_card, self.rr_card, self.sdnn_card,
                       self.quality_card, self.recording_card):
            right.addWidget(widget)
        right.addStretch()

        right_column = QWidget()
        right_column.setLayout(right)
        right_column.setFixedWidth(240)

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
        layout.addSpacing(16)

        self._record_button = QPushButton("●  New recording")
        self._record_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._record_button.setStyleSheet(
            f"QPushButton {{ background: {theme.ACCENT}; color: white; border: none;"
            f" border-radius: 6px; padding: 7px 18px; font-size: 13px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: #8A2424; }}"
            f"QPushButton:disabled {{ background: {theme.BORDER}; color: {theme.TEXT_MUTED}; }}"
        )
        self._record_button.clicked.connect(self._on_record_button)
        self._record_button.setEnabled(False)
        layout.addWidget(self._record_button)
        return bar

    # --- data source --------------------------------------------------

    def attach_source(self, source, buffer, sample_rate, description, units="mV"):
        """Connect a data source. Nothing streams until a session starts."""
        self._source = source
        self._buffer = buffer
        self._fs = float(sample_rate)
        self._units = units
        self._description = description
        self._pipeline = AnalysisPipeline(sample_rate)
        self.ecg_plot.set_units(units)

        self.set_source(f"{description} · ready", active=False)
        self._record_button.setEnabled(True)
        QTimer.singleShot(300, self.new_recording)

    def _start_streaming(self):
        self.set_source(self._description, active=True)
        self._source.start()
        self._draw_timer.start(DRAW_INTERVAL_MS)
        self._analysis_timer.start(ANALYSIS_INTERVAL_MS)

    def _stop_streaming(self):
        self._draw_timer.stop()
        self._analysis_timer.stop()
        self._source.stop()
        self.set_source(f"{self._description} · stopped", active=False)

    def _reset_display(self):
        """Clear everything from the previous session."""
        self._buffer.clear()
        self._result = None
        for card in (self.hr_card, self.rr_card, self.sdnn_card):
            card.set_value(None)
        self.quality_card.set_state("unknown")
        empty = np.array([])
        self.ecg_plot.set_data(empty, empty, empty)
        self.ecg_plot.set_markers(empty, empty)
        self.trend_curve.setData([], [])

    def _snapshot(self):
        """Buffer contents, plus the absolute number of the next sample.

        The background thread may add a sample between the two reads,
        which shifts beat positions by a sample or two (a few ms) —
        invisible on screen, and cheaper than locking the buffer.
        """
        values = self._buffer.get_values()
        end = self._buffer.total_added
        return values, end

    # --- fast loop: drawing -------------------------------------------

    def _redraw(self):
        if self._buffer is None:
            return
        values, end = self._snapshot()
        n = min(len(values), int(WINDOW_SECONDS * self._fs))
        if n >= 2:
            raw = values[-n:]
            times = (np.arange(n) - (n - 1)) / self._fs
            filtered = preprocess(raw, self._fs)
            self.ecg_plot.set_data(times, filtered, raw)

            shown = raw if self.ecg_plot.mode == "raw" else filtered
            self._draw_markers(shown, end, n)
            self._draw_trend(end)

        self._update_session()

    def _draw_markers(self, shown, end, n):
        if self._result is None or len(self._result.peak_samples) == 0:
            self.ecg_plot.set_markers([], [])
            return
        first = end - n
        idx = self._result.peak_samples - first
        idx = idx[(idx >= 0) & (idx < n)]
        times = (idx - (n - 1)) / self._fs
        self.ecg_plot.set_markers(times, shown[idx])

    def _draw_trend(self, end):
        if self._result is None or len(self._result.trend_samples) == 0:
            self.trend_curve.setData([], [])
            return
        t = (self._result.trend_samples - (end - 1)) / self._fs
        self.trend_curve.setData(t, self._result.trend_bpm)

    # --- slow loop: analysis ------------------------------------------

    def _analyse(self):
        if self._buffer is None:
            return
        values, end = self._snapshot()
        self._result = self._pipeline.process(values, end_sample=end)

        self.hr_card.set_value(self._result.bpm)
        self.rr_card.set_value(self._result.rr_ms)
        sdnn = self._result.sdnn_ms if self._buffer.is_full() else None
        self.sdnn_card.set_value(sdnn)

        quality = self._result.quality
        self.quality_card.set_state(quality.state, quality.reason)

    # --- session flow -------------------------------------------------

    def _on_record_button(self):
        if self._phase == "idle":
            self.new_recording()
        elif self._phase == "settling":
            self._end_session("Cancelled before recording started.")
        else:
            self._finish_recording(early=True)

    def new_recording(self):
        """Ask for subject details, then start a session."""
        if self._source is None or self._phase != "idle":
            return
        dialog = RecordingDialog(self)
        if not dialog.exec():
            self.recording_card.set_idle()
            return

        v = dialog.values()
        subject_id = self._registry.find_or_create(
            v["name"], v["age"], v["gender"], v["profession"], v["city"],
            registered=datetime.now().date().isoformat())

        self._session = {
            "subject_id": subject_id,
            "duration_s": v["duration_s"],
            "started": None,
            "info": {
                "age": v["age"],
                "gender": v["gender"],
                "notes": v["notes"],
                "requested_duration_s": v["duration_s"],
                "source": self._description,
                "settle_seconds": SETTLE_SECONDS,
                "display_filter": FILTER_NOTE,
            },
        }

        self._reset_display()
        self._phase = "settling"
        self._settle_start = self._buffer.total_added
        self._record_button.setText("■  Cancel")
        self._start_streaming()
        self._update_session()

    def _update_session(self):
        """Advance settling into recording; stop at the chosen duration."""
        if self._phase == "settling":
            settled = (self._buffer.total_added - self._settle_start) / self._fs
            remaining = SETTLE_SECONDS - settled
            if remaining > 0:
                self.recording_card.set_settling(remaining, self._session["subject_id"])
                return
            self._begin_capture()

        if self._phase == "recording":
            elapsed = self._buffer.captured_count / self._fs
            total = self._session["duration_s"]
            self.recording_card.set_progress(min(elapsed, total), total,
                                             self._session["subject_id"])
            if elapsed >= total:
                self._finish_recording(early=False)

    def _begin_capture(self):
        self._session["started"] = datetime.now()
        self._buffer.start_capture()
        self._phase = "recording"
        self._rec_label.show()
        self._record_button.setText("■  Stop and save")

    def _finish_recording(self, early):
        session = self._session
        samples = self._buffer.stop_capture()
        samples = samples[:int(session["duration_s"] * self._fs)]

        if len(samples) < self._fs:
            self._end_session("Recording under 1 second — not saved.")
            return

        info = dict(session["info"], stopped_early=early)
        try:
            path = save_session(session["subject_id"], samples, self._fs,
                                self._units, session["started"], info)
            message = f"Saved {path.name} · {format_mmss(len(samples) / self._fs)}"
        except (OSError, ValueError) as error:
            message = f"Couldn't save the recording: {error}"
        self._end_session(message)

    def _end_session(self, message):
        """Return to idle: stop streaming, keep the last trace on screen."""
        if self._buffer.is_capturing:
            self._buffer.stop_capture()
        self._stop_streaming()
        self._phase = "idle"
        self._session = None
        self._rec_label.hide()
        self._record_button.setText("●  New recording")
        self.recording_card.set_idle(message)

    # --- shutdown -----------------------------------------------------

    def closeEvent(self, event):
        """Save any recording in progress, then stop everything."""
        if self._phase == "recording":
            self._finish_recording(early=True)
        elif self._phase == "settling":
            self._end_session("")
        self._draw_timer.stop()
        self._analysis_timer.stop()
        if self._source is not None:
            self._source.stop()
        super().closeEvent(event)