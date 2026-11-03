"""Exercise test report: every phase of the test, measured and compared.

Sections, top to bottom:
  1. heart rate through the whole test, phases shaded, unusable parts greyed
  2. phase by phase, and round by round
  3. recovery after the last round
  4. the heartbeat's shape at rest and when fast, beside typical adult values
  5. resting baseline (heart rate, variability) and how hard the exercise was
"View whole ECG" shows every second of the test as strips of ECG paper.

To preview it on a synthetic test with a known answer:

    py -m app.ui.exercise_window

To reopen a saved exercise test:

    py -m app.ui.exercise_window recordings/S001/S001_20261025_101500
"""

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from app.analysis.exercise_test import analyse_exercise
from app.analysis.recovery import CHECK_POINTS_S, NEAR_REST, STOP_WINDOW_S
from app.analysis.references import SOURCES as RANGE_SOURCES
from app.analysis.references import reference
from app.analysis.report import BLOCK_S
from app.ui import theme
from app.ui.ecg_viewer import ECGViewer, recording_folder
from app.ui.widgets import format_mmss

PHASE_BANDS = {
    "baseline": QColor(12, 68, 124, 24),
    "exercise": QColor(163, 45, 45, 30),
    "rest": QColor(39, 80, 10, 30),
    "recovery": QColor(12, 68, 124, 24),
}
UNCLEAN = QColor(138, 137, 132, 90)
BEAT_DOT = QColor(138, 137, 132)
CURVE = QColor(163, 45, 45)
REST_LINE = QColor(12, 68, 124)
REST_BEAT = QColor(12, 68, 124)
FAST_BEAT = QColor(163, 45, 45)
UNUSUAL = QColor(133, 79, 11)

NOTE = ("Not a diagnosis. Measurements use only the parts of the recording judged "
        "clean (grey bands are left out). Amplitudes are uncalibrated ADC counts; "
        "times and heart rates do not depend on calibration. Typical values for "
        "recovery depend on the exact protocol, so none are shown.")
SOURCES = (
    "Age-predicted maximum heart rate (208 − 0.7 × age): Tanaka H, Monahan KD, Seals DR. "
    "Age-predicted maximal heart rate revisited. J Am Coll Cardiol 2001;37(1):153-156.",
    "Heart-rate variability recording length: Task Force of the ESC and NASPE. Heart rate "
    "variability: standards of measurement. Circulation 1996;93(5):1043-1065.",
    "T30 index: Imai K, Sato H, Hori M, et al. J Am Coll Cardiol 1994;24:1529-35.",
    "Bazett over-corrects at fast heart rates; Fridericia much less: CredibleMeds/AZCERT, "
    "'The effect of heart rate on QT: rate correction of QT (QTc)', companion PDF 3.",
)


def _fmt(value, unit="bpm", sign=False):
    if value is None:
        return "—"
    return f"{value:+.0f} {unit}" if sign else f"{value:.0f} {unit}"


def _change(drop, unit=""):
    """A fall as a change: a 12 bpm fall shows as −12, a 3 bpm rise as +3."""
    if drop is None:
        return "—"
    text = f"{-drop:+.0f}".replace("-", "−")
    return f"{text} {unit}".strip()


def _pct(value):
    return "—" if value is None else f"{value:.0f}%"


def _plot(left_label):
    plot = pg.PlotWidget()
    plot.setBackground(theme.PANEL_BG)
    plot.setMenuEnabled(False)
    plot.setMouseEnabled(x=False, y=False)
    plot.hideButtons()
    plot.showGrid(x=True, y=True, alpha=0.12)
    plot.setLabel("left", left_label)
    return plot


def _section(title, widget, height=None):
    frame = QFrame()
    frame.setObjectName("panel")
    label = QLabel(title)
    label.setObjectName("cardLabel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(6)
    layout.addWidget(label)
    layout.addWidget(widget, 1)
    if height:
        frame.setMinimumHeight(height)
    return frame


def _table(headings, rows, first_width=120, plain_last=False):
    """A simple grid of labels: headings, then rows of text.

    Values are bold. plain_last: show the last column in grey instead
    (used for typical ranges, so they don't look like measurements).
    """
    box = QWidget()
    grid = QGridLayout(box)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(14)
    grid.setVerticalSpacing(6)
    for col, heading in enumerate(headings):
        label = QLabel(heading)
        label.setObjectName("cardLabel")
        grid.addWidget(label, 0, col)
    last = len(headings) - 1
    for r, row in enumerate(rows, start=1):
        for col, text in enumerate(row):
            label = QLabel(text)
            grey = col == 0 or (plain_last and col == last)
            label.setStyleSheet("font-size: 13px;" + (f" color: {theme.TEXT_SECONDARY};"
                                                      if grey else " font-weight: 600;"))
            grid.addWidget(label, r, col)
    grid.setColumnMinimumWidth(0, first_width)
    grid.setRowStretch(len(rows) + 1, 1)
    return box


def _muted(text, size=12):
    label = QLabel(text)
    label.setObjectName("muted")
    label.setStyleSheet(f"font-size: {size}px;")
    label.setWordWrap(True)
    return label


class ExerciseWindow(QWidget):
    """A separate window showing one exercise test."""

    def __init__(self, report, title, details="", sex=None, parent=None):
        super().__init__(parent)
        self.setObjectName("central")
        self.setWindowTitle(f"Exercise test · {title}")
        self.resize(1400, 900)
        self._r = report
        self._sex = sex
        self._title, self._details = title, details
        self._viewer = None

        content = QWidget()
        content.setObjectName("central")
        body = QVBoxLayout(content)
        body.setContentsMargins(18, 14, 18, 18)
        body.setSpacing(12)
        body.addWidget(_section("Heart rate through the whole test", self._whole_plot(), 330))

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(_section("Phase by phase", self._phase_table()), 3)
        row.addWidget(_section("Round by round", self._round_table()), 2)
        body.addLayout(row)

        body.addWidget(_section("Recovery after the last round", self._recovery_box(), 380))
        body.addWidget(_section("Heartbeat shape: at rest and when fast", self._beat_box(), 380))

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(_section("Resting baseline", self._baseline_box()), 1)
        row.addWidget(_section("How hard the exercise was", self._intensity_box()), 1)
        body.addLayout(row)

        notes = QVBoxLayout()
        for text in self._r.notes:
            notes.addWidget(_muted(text, 13))
        found = len(self._r.unusual_t)
        if found:
            notes.addWidget(_muted(
                f"{found} beat{'s' if found != 1 else ''} with a shape unlike the person's "
                f"usual beat {'were' if found != 1 else 'was'} found while still (▼ on the "
                "graph). Movement can cause this, and so can a different kind of heartbeat; "
                "this app cannot tell which. A doctor can, from a standard ECG.", 13))
        notes.addWidget(_muted(NOTE))
        sources = SOURCES + tuple(RANGE_SOURCES[k] for k in ("mayo_hr", "statpearls_ecg",
                                                            "aha_2009_qt"))
        notes.addWidget(_muted("Sources: " + "  ·  ".join(sources), 11))
        body.addLayout(notes)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._header(title, details))
        root.addWidget(scroll, 1)

    # --- header -------------------------------------------------------

    def _header(self, title, details):
        r = self._r
        bar = QFrame()
        bar.setObjectName("panel")
        name = QLabel("Exercise test")
        name.setStyleSheet("font-size: 17px; font-weight: 600;")
        rounds = [p for p in r.phases if p.kind == "exercise"]
        plan = f"{len(rounds)} round" + ("s" if len(rounds) != 1 else "")
        if rounds:
            plan += f" × {format_mmss(rounds[0].duration_s)}"
        sub = QLabel(" · ".join(x for x in (title, plan, f"total {format_mmss(r.duration_s)}",
                                             f"usable signal {r.usable:.0%}", details) if x))
        sub.setObjectName("muted")
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(name)
        text.addWidget(sub)

        parts = []
        if r.peak_bpm is not None:
            peak = f"Peak {r.peak_bpm:.0f} bpm"
            if r.peak_percent is not None:
                peak += f" ({r.peak_percent:.0f}% of age-predicted maximum)"
            parts.append(peak)
        if r.recovery is not None and r.recovery.drop_at.get(60) is not None:
            drop = r.recovery.drop_at[60]
            change = (f"fell {drop:.0f} bpm" if drop >= 0 else f"rose {-drop:.0f} bpm")
            change += " in the minute after"
            share = r.recovery.recovered_pct.get(60)
            if share is not None:
                change += f" ({share:.0f}% of the rise)"
            parts.append(change)
        summary = QLabel(" · ".join(parts) if parts else "Heart rate could not be measured")
        summary.setStyleSheet("font-size: 15px; font-weight: 600;")
        whole = QPushButton("View whole ECG")
        whole.clicked.connect(self._show_whole_ecg)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.addLayout(text)
        layout.addStretch()
        layout.addWidget(summary)
        layout.addSpacing(12)
        layout.addWidget(whole)
        return bar

    def _show_whole_ecg(self):
        """Every second of the test as strips of ECG paper, in its own window."""
        r = self._r
        self._viewer = ECGViewer(r.filtered, r.fs, self._title, self._details,
                                 marks=r.unusual_t, phases=r.phases,
                                 save_dir=recording_folder(self._title))
        self._viewer.show()
        self._viewer.raise_()

    # --- 1. whole test ------------------------------------------------

    def _whole_plot(self):
        r = self._r
        plot = _plot("Heart rate (bpm)")
        plot.setLabel("bottom", "Minutes into the test")
        minutes = 1 / 60.0
        ok = np.isfinite(r.curve_bpm)
        top = float(np.nanmax(r.curve_bpm)) if ok.any() else 120.0
        low = float(np.nanmin(r.curve_bpm)) if ok.any() else 60.0

        for p in r.phases:
            band = pg.LinearRegionItem((p.start_s * minutes, p.end_s * minutes), movable=False,
                                       brush=pg.mkBrush(PHASE_BANDS[p.kind]), pen=pg.mkPen(None))
            band.setZValue(-10)
            plot.addItem(band)
            label = pg.TextItem(p.label, color=theme.TEXT_SECONDARY, anchor=(0.5, 0))
            label.setPos((p.start_s + p.end_s) / 2 * minutes, top + 14)
            plot.addItem(label)

        blocks, i = r.clean_blocks, 0
        while i < len(blocks):
            if not blocks[i]:
                j = i
                while j < len(blocks) and not blocks[j]:
                    j += 1
                band = pg.LinearRegionItem((i * BLOCK_S * minutes, j * BLOCK_S * minutes),
                                           movable=False, brush=pg.mkBrush(UNCLEAN),
                                           pen=pg.mkPen(None))
                band.setZValue(-5)
                plot.addItem(band)
                i = j
            i += 1

        if len(r.beat_t):
            plot.plot(r.beat_t * minutes, r.beat_bpm, pen=None, symbol="o", symbolSize=3,
                      symbolPen=None, symbolBrush=pg.mkBrush(BEAT_DOT))
        # NaN where there were no clean beats, so gaps stay gaps instead of
        # being bridged by a straight line.
        plot.plot(r.curve_t * minutes, r.curve_bpm, pen=pg.mkPen(CURVE, width=2.2),
                  connect="finite")
        if len(r.unusual_t):
            plot.plot(r.unusual_t * minutes, np.full(len(r.unusual_t), top + 6), pen=None,
                      symbol="t", symbolSize=9, symbolPen=None,
                      symbolBrush=pg.mkBrush(UNUSUAL))
        if r.resting_bpm is not None:
            plot.addItem(pg.InfiniteLine(r.resting_bpm, angle=0,
                                         pen=pg.mkPen(REST_LINE, width=1.1,
                                                      style=Qt.PenStyle.DashLine)))
        if r.peak_bpm is not None:
            plot.plot([r.peak_t * minutes], [r.peak_bpm], pen=None, symbol="t1", symbolSize=12,
                      symbolBrush=pg.mkBrush(CURVE), symbolPen=None)
            label = pg.TextItem(f"peak {r.peak_bpm:.0f}", color=CURVE, anchor=(0.5, 1.6))
            label.setPos(r.peak_t * minutes, r.peak_bpm)
            plot.addItem(label)
        plot.setYRange(low - 10, top + 28, padding=0)
        plot.setXRange(0, r.duration_s * minutes, padding=0.01)
        return plot

    # --- 2. tables ----------------------------------------------------

    def _phase_table(self):
        rows = []
        for s in self._r.stats:
            p = s.phase
            span = (f"{_fmt(s.hr_low, '')}–{_fmt(s.hr_high, '')}".replace(" ", "")
                    if s.hr_low is not None else "—")
            rows.append((p.label, f"{format_mmss(p.start_s)}–{format_mmss(p.end_s)}",
                         f"{s.usable:.0%}", _fmt(s.hr_start, ""), _fmt(s.hr_end, ""),
                         _fmt(s.hr_mean, ""), span,
                         "—" if s.unusual is None else str(s.unusual)))
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_table(("Phase", "Time", "Usable", "Start", "End", "Average",
                                 "Low–high", "Unusual"), rows))
        layout.addWidget(_muted("Heart rates in bpm. Start / end: the first / last 10 s "
                                "of the phase. Low–high: of the 1-second heart-rate curve. "
                                "Unusual: beats shaped unlike the usual resting beat; not "
                                "judged during exercise, where movement changes every beat."))
        return box

    def _round_table(self):
        r = self._r
        rest = r.rounds[0].rest_s if r.rounds else 60
        rows = [(f"Round {x.round}", _fmt(x.hr_start, ""), _fmt(x.hr_end, ""),
                 _fmt(x.rise, "", sign=True), _fmt(x.peak, ""),
                 _change(x.drop) + (" *" if x.stop_fallback and x.drop is not None else ""))
                for x in r.rounds]
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_table(("", "Start", "End", "Rise", "Peak",
                                 f"In the {rest:.0f} s after"), rows, 70))
        text = (f"In the {rest:.0f} s after: the change from the end of the round (its "
                f"last 5 s) to {rest:.0f} s later (the end of the rest; for the last round, "
                f"the recovery's own {rest:.0f} s value, so the two match). Every round is "
                "compared over the same time; − means the heart rate fell. A round that "
                "ends higher than the one before, at the same effort, means the heart is "
                "working harder as the test goes on.")
        if any(x.stop_fallback for x in r.rounds):
            text += (" * The last 5 s of that round were too noisy, so its end was taken "
                     "from 3 s before to 5 s after it. The heart is already slowing then, "
                     "so this fall is likely a little smaller than the real one.")
        layout.addWidget(_muted(text))
        return box

    # --- 3. recovery and beat shape -----------------------------------

    def _recovery_box(self):
        rec = self._r.recovery
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        if rec is None:
            layout.addWidget(_muted("Not measured: the test did not reach the final "
                                    "recovery.", 13))
            return box

        plot = _plot("Heart rate (bpm)")
        plot.setLabel("bottom", "Seconds after the last round")
        if len(rec.beat_t):
            plot.plot(rec.beat_t, rec.beat_bpm, pen=None, symbol="o", symbolSize=4,
                      symbolPen=None, symbolBrush=pg.mkBrush(BEAT_DOT))
        ok = np.isfinite(rec.curve_bpm)
        plot.plot(rec.curve_t, rec.curve_bpm, pen=pg.mkPen(CURVE, width=2.5), connect="finite")
        top = float(np.nanmax(rec.curve_bpm)) if ok.any() else 100.0
        if rec.resting_bpm is not None:
            plot.addItem(pg.LinearRegionItem((rec.resting_bpm, (1 + NEAR_REST) * rec.resting_bpm),
                                             orientation="horizontal", movable=False,
                                             brush=pg.mkBrush(PHASE_BANDS["baseline"]),
                                             pen=pg.mkPen(None)))
            plot.addItem(pg.InfiniteLine(rec.resting_bpm, angle=0,
                                         pen=pg.mkPen(REST_LINE, width=1.2,
                                                      style=Qt.PenStyle.DashLine)))
        for point in CHECK_POINTS_S:
            if rec.drop_at.get(point) is not None:
                plot.addItem(pg.InfiniteLine(point, angle=90, pen=pg.mkPen(
                    theme.TEXT_MUTED, style=Qt.PenStyle.DotLine)))
                label = pg.TextItem(f"{point} s\n{_change(rec.drop_at[point])}", color=CURVE,
                                    anchor=(0, 0))
                label.setPos(point + 1, top + 4)
                plot.addItem(label)
        low = min(float(np.nanmin(rec.curve_bpm)) if ok.any() else 60.0,
                  rec.resting_bpm or 60.0)
        plot.setYRange(low - 8, top + 16, padding=0)
        plot.setXRange(-STOP_WINDOW_S[0], max(rec.curve_t[-1] if len(rec.curve_t) else 60, 60),
                       padding=0.01)

        rise = (rec.stop_bpm - rec.resting_bpm
                if rec.stop_bpm is not None and rec.resting_bpm is not None else None)
        rows = [("Resting", _fmt(rec.resting_bpm), "", ""),
                ("At the stop", _fmt(rec.stop_bpm), _change(-rise) if rise is not None else "",
                 "")]
        for point in CHECK_POINTS_S:
            rows.append((f"After {point} s", _fmt(rec.hr_at.get(point)),
                         _change(rec.drop_at.get(point)), _pct(rec.recovered_pct.get(point))))
        rows.append(("T30", "not measured" if rec.t30_s is None else f"{rec.t30_s:.0f} s", "", ""))
        if rec.back_to_rest_s is not None:
            back = f"after {rec.back_to_rest_s:.0f} s"
        else:
            back = "not measured" if rec.stop_bpm is None else "not reached"
        rows.append(("Back within 10%", back, "", ""))
        if rec.stop_source.startswith("last"):
            stop_note = f"At the stop: the beats in the {rec.stop_source}."
        elif rec.stop_source:
            stop_note = f"At the stop: the beats from {rec.stop_source}."
        else:
            stop_note = ("At the stop: not measured. There were too few clean beats around "
                         "the stop, so nothing measured from it is shown; an electrode may "
                         "have lost contact.")
        side = QVBoxLayout()
        side.addWidget(_table(("", "Heart rate", "Change", "Of the rise"), rows, 110))
        side.addWidget(_muted(
            f"{stop_note} Resting: the last 60 s of the rest before. Change: from the "
            "stop (for the stop itself, how far the heart rose above resting). Of the rise: "
            "how much of that rise has been recovered; after light exercise the heart can "
            "only fall about as far as it rose, so this compares fairly between people and "
            "tests (shown when it rose 5 bpm or more). T30: how fast the heart rate falls "
            "in the first 30 s, as a time constant (smaller = faster), shown only when "
            "those 30 s follow a steady fall clearly bigger than the beat-to-beat "
            "scatter; after light exercise they often don't. Back within 10%: counted "
            "once the heart rate, seen above that band first, stays inside it for 10 s."))
        layout.addWidget(plot, 3)
        layout.addLayout(side, 2)
        return box

    def _beat_box(self):
        r = self._r
        rest, fast = r.rest_beat, r.fast_beat
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)

        plot = _plot("Amplitude (ADC counts)")
        plot.setLabel("bottom", "Time from the R peak (ms)")
        plot.addLegend(offset=(-10, 10))
        for beat, colour, name in ((rest, REST_BEAT, "at rest"), (fast, FAST_BEAT, "fast")):
            if beat.template is None:
                continue
            ms = (np.arange(len(beat.template)) - beat.r_index) * 1000.0 / beat.fs
            # A fast beat's window reaches the beats on either side; show only its own.
            keep = (ms >= -0.45 * beat.rr_ms) & (ms <= min(600.0, 0.85 * beat.rr_ms))
            plot.plot(ms[keep], beat.template[keep], pen=pg.mkPen(colour, width=2.2), name=name)
            if "t_off" in beat.points:
                t_off = (beat.points["t_off"] - beat.r_index) * 1000.0 / beat.fs
                plot.addItem(pg.InfiniteLine(t_off, angle=90, pen=pg.mkPen(
                    colour, width=1, style=Qt.PenStyle.DashLine)))

        def ms(value):
            return _fmt(value, "ms")

        def typical(name):
            ref = reference(name, self._sex)
            return ref.text if ref else ""

        rows = [("Heart rate", _fmt(rest.heart_rate_bpm), _fmt(fast.heart_rate_bpm),
                 typical("heart_rate")),
                ("PR interval", ms(rest.pr_interval_ms), ms(fast.pr_interval_ms),
                 typical("pr_interval")),
                ("QRS", ms(rest.qrs_ms), ms(fast.qrs_ms), typical("qrs")),
                ("QT", ms(rest.qt_ms), ms(fast.qt_ms), ""),
                ("QTc Bazett", ms(rest.qtc_bazett_ms), ms(fast.qtc_bazett_ms), typical("qtc")),
                ("QTc Fridericia", ms(rest.qtc_fridericia_ms), ms(fast.qtc_fridericia_ms),
                 typical("qtc")),
                ("Beats averaged", str(rest.n_beats), str(fast.n_beats), "")]
        side = QVBoxLayout()
        side.addWidget(_table(("", "At rest", "Fast", "Typical adult, at rest"), rows, 105,
                              plain_last=True))
        side.addWidget(_muted(
            f"At rest: the rest before. Fast: {r.fast_source}. Dashed lines: end of T. "
            "Typical ranges are for adults at rest, for context only, not a diagnosis. "
            "The QT gets shorter as the heart speeds up. QTc corrects it for heart rate; "
            "Bazett's correction over-corrects at fast rates, Fridericia's much less. "
            "Fewer than 20 clean, alike beats: not measured."))
        layout.addWidget(plot, 3)
        layout.addLayout(side, 2)
        return box

    # --- 4. baseline and intensity ------------------------------------

    def _baseline_box(self):
        r = self._r
        rows = [("Resting heart rate", _fmt(r.resting_bpm)),
                ("SDNN", _fmt(r.sdnn_ms, "ms")),
                ("RMSSD", _fmt(r.rmssd_ms, "ms"))]
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_table(("", "Value"), rows, 150))
        layout.addWidget(_muted(
            f"Variability: how much the gap between beats changes from beat to beat "
            f"(SDNN: overall spread; RMSSD: beat-to-beat change), from "
            f"{r.hrv_seconds:.0f} s of clean rest. The standard short-term measurement "
            f"uses 5 minutes, so these shorter-window values are rougher."))
        return box

    def _intensity_box(self):
        r = self._r
        rows = [("Peak heart rate", _fmt(r.peak_bpm)),
                ("Age-predicted maximum", _fmt(r.predicted_max_bpm)),
                ("Peak as % of it", "—" if r.peak_percent is None else f"{r.peak_percent:.0f}%")]
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_table(("", "Value"), rows, 170))
        layout.addWidget(_muted(
            "Age-predicted maximum: 208 − 0.7 × age, fitted to 18,712 people, so for any "
            "one person it is only an estimate. Peak: the highest point of the 1-second "
            "heart-rate curve during the rounds."))
        return box


def open_exercise(raw, fs, phases, age, title, details="", sex=None):
    """Analyse an exercise-test recording and build its window."""
    report = analyse_exercise(raw, fs, phases, age=age or None)
    return ExerciseWindow(report, title, details, sex)


def open_saved(path):
    """Build the window for a saved exercise test (path without extension)."""
    import json
    from pathlib import Path

    from app.acquisition.record_loader import RecordLoader
    from app.analysis.exercise_test import phases_from_dicts

    path = str(Path(path).with_suffix(""))
    with open(path + ".json", encoding="utf-8") as f:
        meta = json.load(f)
    if not meta.get("phases"):
        raise SystemExit(f"{path} is not an exercise test.")
    signal, fs = RecordLoader(path, channel_name="ECG").load()
    details = " · ".join(str(meta[k]) for k in ("gender", "age", "notes") if meta.get(k))
    return open_exercise(signal, fs, phases_from_dicts(meta["phases"]), meta.get("age"),
                         Path(path).name, details, meta.get("gender"))


if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setStyleSheet(theme.stylesheet())
    if len(sys.argv) > 1:
        window = open_saved(sys.argv[1])
    else:
        from tests.test_exercise_test import FS, PHASES, synthetic_ecg, true_beats
        window = open_exercise(synthetic_ecg(true_beats()), FS, PHASES, 49, "Synthetic test",
                               "known answer: rounds end at 120, 125, 130 bpm")
    window.show()
    sys.exit(app.exec())