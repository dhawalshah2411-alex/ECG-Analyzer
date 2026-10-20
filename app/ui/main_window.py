"""Main application window: the ECG dashboard."""

import time
from collections import deque
from datetime import datetime

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QPushButton, QVBoxLayout,
                               QWidget)

from app.analysis.pipeline import AnalysisPipeline
from app.analysis.report import build_report
from app.database.session_store import SubjectRegistry, save_session
from app.signal_processing.filters import StreamingFilter
from app.ui import theme
from app.ui.recording_dialog import RecordingDialog
from app.ui.report_window import ReportWindow
from app.ui.widgets import MetricCard, QualityCard, RecordingCard, format_mmss
from app.visualization.ecg_plot import ECGPlot

WINDOW_SECONDS = 4.0          # width of the ECG view
TREND_SECONDS = 60            # width of the heart-rate trend
DRAW_INTERVAL_MS = 33         # redraw about 30 times a second
ANALYSIS_INTERVAL_MS = 500    # full analysis twice a second
MARKER_SEARCH_S = 0.05        # look this far either side of a beat for the trace's top
SETTLE_SECONDS = 15           # signal shown but not saved before recording;
                              # quality needs 10 s, so this leaves 5 s to act
RATE_TOLERANCE = 0.05         # refuse to record if samples arrive >5% off the expected rate
FILTER_NOTE = ("display: bandpass 0.5-40 Hz + notch 50 Hz, forward-only (monitor mode); "
               "analysis: same filters, zero-phase; saved signal is raw")


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
        self._display_filter = None   # live display filtering, chunk by chunk
        self._display = deque()       # filtered samples for the ECG view
        self._display_upto = 0        # absolute sample number filtered up to

        self._phase = "idle"          # "idle", "settling" or "recording"
        self._session = None
        self._settle_start = 0
        self._settle_clock = 0.0      # computer clock when settling began
        self._capture_clock = 0.0     # computer clock when recording began
        self._registry = SubjectRegistry()
        self._report_windows = []     # kept here so open reports aren't closed by Python

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
        self._display_filter = StreamingFilter(sample_rate)
        self._display = deque(maxlen=int(WINDOW_SECONDS * self._fs))
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
        self._display_filter.reset()
        self._display.clear()
        self._display_upto = self._buffer.total_added
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
        self._filter_new_samples(values, end)
        n = min(len(values), len(self._display), int(WINDOW_SECONDS * self._fs))
        if n >= 2:
            raw = values[-n:]
            times = (np.arange(n) - (n - 1)) / self._fs
            filtered = np.asarray(self._display)[-n:]
            self.ecg_plot.set_data(times, filtered, raw)

            shown = raw if self.ecg_plot.mode == "raw" else filtered
            self._draw_markers(shown, end, n)
            self._draw_trend(end)

        self._update_session()

    def _filter_new_samples(self, values, end):
        """Filter only the samples that arrived since the last frame.

        Filtering just the last 4 s with the zero-phase filter on every
        frame distorted the newest edge of the trace: when a beat was
        arriving, it could swing the wrong way by thousands of counts.
        """
        new = end - self._display_upto
        if new <= 0:
            return
        if new > len(values):
            # Fell further behind than the buffer holds: start afresh.
            new = len(values)
            self._display_filter.reset()
            self._display.clear()
        self._display.extend(self._display_filter.process(values[-new:]))
        self._display_upto = end

    def _draw_markers(self, shown, end, n):
        """Mark each detected beat, just above the highest point of the trace near it.

        The display filter delays the trace by a few milliseconds, so the
        trace's value at the exact beat sample can be partway up the R
        wave. Using the local top keeps every marker clear of the trace.
        """
        if self._result is None or len(self._result.peak_samples) == 0:
            self.ecg_plot.set_markers([], [])
            return
        first = end - n
        idx = self._result.peak_samples - first
        idx = idx[(idx >= 0) & (idx < n)]
        times = (idx - (n - 1)) / self._fs
        half = max(1, int(MARKER_SEARCH_S * self._fs))
        tops = [shown[max(0, i - half):i + half + 1].max() for i in idx]
        self.ecg_plot.set_markers(times, tops)

    def _draw_trend(self, end):
        if self._result is None or len(self._result.trend_samples) == 0:
            self.trend_curve.setData([], [])
            return
        t = (self._result.trend_samples - (end - 1)) / self._fs
        self.trend_curve.setData(t, self._result.trend_bpm)

    # --- slow loop: analysis ------------------------------------------

    def _analyse(self):
        """Run the analysis and update the cards.

        While the quality check says Poor, the numbers are hidden (shown
        as a dash): the beats behind them are probably noise. On the first
        real recordings, electrode artifacts made the heart-rate card show
        up to 191 bpm in large type while the quality card said Poor.
        """
        if self._buffer is None:
            return
        values, end = self._snapshot()
        self._result = self._pipeline.process(values, end_sample=end)

        quality = self._result.quality
        trusted = quality.state != "poor"
        self.hr_card.set_value(self._result.bpm if trusted else None)
        self.rr_card.set_value(self._result.rr_ms if trusted else None)
        full = self._buffer.is_full()
        self.sdnn_card.set_value(self._result.sdnn_ms if trusted and full else None)
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
        self._settle_clock = time.perf_counter()
        self._update_session()

    def _update_session(self):
        """Advance settling into recording; stop at the chosen duration."""
        if self._phase == "settling":
            settled = (self._buffer.total_added - self._settle_start) / self._fs
            remaining = SETTLE_SECONDS - settled
            if remaining > 0:
                self.recording_card.set_settling(remaining, self._session["subject_id"])
                return
            if not self._rate_is_correct():
                return
            self._begin_capture()

        if self._phase == "recording":
            elapsed = self._buffer.captured_count / self._fs
            total = self._session["duration_s"]
            self.recording_card.set_progress(min(elapsed, total), total,
                                             self._session["subject_id"])
            if elapsed >= total:
                self._finish_recording(early=False)

    def _rate_is_correct(self):
        """Check the samples that arrived while settling against the computer's clock.

        The app tells time by counting samples, so a device that sends
        faster or slower than it should makes every time, heart rate and
        recording length wrong, with nothing on screen to show it. This
        happened twice on the first day: an old sketch sent about 6,400
        samples a second, and so did a catch-up burst after a pause.
        """
        elapsed = time.perf_counter() - self._settle_clock
        received = self._buffer.total_added - self._settle_start
        measured = received / elapsed if elapsed > 0 else 0.0
        self._session["info"]["settling_rate_hz"] = round(measured, 1)
        if abs(measured - self._fs) <= RATE_TOLERANCE * self._fs:
            return True

        message = (f"Samples arrived at {measured:.0f} per second instead of "
                   f"{self._fs:.0f}, so every time and heart rate would be wrong. "
                   f"Nothing was recorded.\n\nRe-upload the firmware, then check "
                   f"the speed with:  py test_rate.py")
        self._end_session("Stopped: wrong sample rate — nothing recorded.")
        QMessageBox.warning(self, "Sample rate problem", message)
        return False

    def _begin_capture(self):
        self._session["started"] = datetime.now()
        self._capture_clock = time.perf_counter()
        self._buffer.start_capture()
        self._phase = "recording"
        self._rec_label.show()
        self._record_button.setText("■  Stop and save")

    def _finish_recording(self, early):
        session = self._session
        samples = self._buffer.stop_capture()
        elapsed = time.perf_counter() - self._capture_clock
        measured = len(samples) / elapsed if elapsed > 0 else 0.0
        samples = samples[:int(session["duration_s"] * self._fs)]

        if len(samples) < self._fs:
            self._end_session("Recording under 1 second — not saved.")
            return

        info = dict(session["info"], stopped_early=early,
                    measured_rate_hz=round(measured, 1))
        try:
            path = save_session(session["subject_id"], samples, self._fs,
                                self._units, session["started"], info)
        except (OSError, ValueError) as error:
            self._end_session(f"Couldn't save the recording: {error}")
            return

        saved = (f"Saved {path.name} · {format_mmss(len(samples) / self._fs)}"
                 f" · measured {measured:.0f} samples/s")
        self._end_session(saved + " · preparing the report…")
        details = " · ".join(str(info[k]) for k in ("gender", "age", "notes") if info.get(k))
        # A short delay lets the "preparing" message appear before the
        # analysis (about a second) keeps the window busy.
        QTimer.singleShot(50, lambda: self._open_report(
            samples, path.name, details, info.get("gender"), saved))

    def _open_report(self, samples, title, details, sex, saved_message):
        """Analyse the saved recording and show its Report window."""
        try:
            report = build_report(samples, self._fs)
        except Exception as error:     # never lose the session over a report
            self.recording_card.set_idle(f"{saved_message} · report failed: {error}")
            return
        window = ReportWindow(report, title, details, units=self._units, sex=sex)
        self._report_windows.append(window)
        window.show()
        window.raise_()
        window.activateWindow()
        self.recording_card.set_idle(saved_message)

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