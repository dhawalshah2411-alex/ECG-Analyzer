"""Report window: everything measured in one finished recording.

Opens by itself when a recording is saved. It shows the average beat
with every boundary drawn on it, the gap between every pair of beats
across the whole recording, and a table of measurements, each beside
its typical adult range. Every number can be checked against the
picture it came from.

To preview it on a saved recording without recording again:

    py -m app.ui.report_window recordings/S001/S001_20261020_193742
"""

import json
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QVBoxLayout, QWidget)

from app.analysis.references import SOURCES, reference
from app.ui import theme
from app.ui.widgets import format_mmss

PAPER = QColor(255, 251, 250)
TRACE = QColor(15, 15, 15)
MARK = QColor(163, 45, 45)
SHADE_P = QColor(12, 68, 124, 28)        # light blue behind the P wave
SHADE_QRS = QColor(163, 45, 45, 30)      # light red behind the QRS
SHADE_T = QColor(39, 80, 10, 26)         # light green behind the T wave
UNCLEAN = QColor(138, 137, 132, 45)      # grey behind parts left out
NOTE = ("Estimates from one lead, not a diagnosis. Ranges are typical adult "
        "values, shown for context. The average beat is built from clean, "
        "normally-timed beats only.")


def _fmt(value, unit="ms"):
    return "—" if value is None else f"{value:.0f} {unit}"


class ReportWindow(QWidget):
    """A separate window showing one recording's report."""

    def __init__(self, report, title, details="", units="adu", sex=None, parent=None):
        super().__init__(parent)
        self.setObjectName("central")
        self.setWindowTitle(f"Report · {title}")
        self.resize(1280, 800)
        self._report = report
        self._units = units
        self._sex = sex

        header = self._header(title, details)
        left = QVBoxLayout()
        left.setSpacing(10)
        left.addWidget(self._section("Average beat", self._beat_plot()), 3)
        left.addWidget(self._section("Gap between beats, whole recording",
                                     self._gaps_plot()), 2)

        body = QHBoxLayout()
        body.setContentsMargins(18, 14, 18, 14)
        body.setSpacing(14)
        body.addLayout(left, 1)
        body.addWidget(self._table(), 0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(header)
        root.addLayout(body, 1)

    # --- header -------------------------------------------------------

    def _header(self, title, details):
        r = self._report
        bar = QFrame()
        bar.setObjectName("panel")
        name = QLabel("Recording report")
        name.setStyleSheet("font-size: 17px; font-weight: 600;")
        sub = QLabel(f"{title} · {format_mmss(r.duration_s)}" + (f" · {details}" if details else ""))
        sub.setObjectName("muted")
        summary = QLabel(f"{r.beats_total} beats found · {r.clean_fraction:.0%} of the "
                         f"recording clean · average beat built from {r.intervals.n_beats} beats")
        summary.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 13px;")

        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(name)
        text.addWidget(sub)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.addLayout(text)
        layout.addStretch()
        layout.addWidget(summary)
        return bar

    @staticmethod
    def _section(title, widget):
        frame = QFrame()
        frame.setObjectName("panel")
        label = QLabel(title)
        label.setObjectName("cardLabel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        layout.addWidget(label)
        layout.addWidget(widget, 1)
        return frame

    # --- average beat -------------------------------------------------

    def _beat_plot(self):
        iv = self._report.intervals
        plot = pg.PlotWidget()
        plot.setBackground(PAPER)
        plot.setMenuEnabled(False)
        plot.setMouseEnabled(x=False, y=False)
        plot.hideButtons()
        plot.showGrid(x=True, y=True, alpha=0.12)
        plot.setLabel("bottom", "Time from the R peak", units="ms")
        plot.setLabel("left", "Amplitude" + (" (ADC counts, uncalibrated)"
                                             if self._units != "mV" else " (mV)"))
        if iv.template is None:
            plot.addItem(pg.TextItem("Too few clean beats to build an average beat.",
                                     color=theme.TEXT_SECONDARY))
            return plot

        fs, r, y = iv.fs, iv.r_index, iv.template
        ms = (np.arange(len(y)) - r) * 1000.0 / fs
        pts = {k: (v - r) * 1000.0 / fs for k, v in iv.points.items()}
        top, bottom = float(y.max()), float(y.min())
        span = top - bottom

        for start, end, colour in (("p_on", "p_off", SHADE_P),
                                   ("qrs_on", "qrs_off", SHADE_QRS),
                                   ("qrs_off", "t_off", SHADE_T)):
            if start in pts and end in pts:
                region = pg.LinearRegionItem((pts[start], pts[end]), movable=False,
                                             brush=pg.mkBrush(colour), pen=pg.mkPen(None))
                region.setZValue(-5)
                plot.addItem(region)

        plot.plot(ms, y, pen=pg.mkPen(TRACE, width=2))

        # Wave names above their peaks.
        for key, name in (("p_peak", "P"), ("r", "R"), ("t_peak", "T")):
            if key in pts:
                i = iv.points[key]
                label = pg.TextItem(name, color=MARK, anchor=(0.5, 1.0))
                label.setPos(pts[key], y[i] + 0.04 * span)
                plot.addItem(label)

        # Interval brackets below the beat.
        rows = (("PR", "p_on", "qrs_on", iv.pr_interval_ms),
                ("QRS", "qrs_on", "qrs_off", iv.qrs_ms),
                ("QT", "qrs_on", "t_off", iv.qt_ms))
        for row, (name, a, b, value) in enumerate(rows):
            if a in pts and b in pts and value is not None:
                level = bottom - (0.12 + 0.15 * row) * span
                plot.plot([pts[a], pts[a], pts[b], pts[b]],
                          [level + 0.03 * span, level, level, level + 0.03 * span],
                          pen=pg.mkPen(MARK, width=1.4))
                text = pg.TextItem(f"{name} {value:.0f} ms", color=MARK, anchor=(0.5, 0))
                text.setPos((pts[a] + pts[b]) / 2, level - 0.005 * span)
                plot.addItem(text)

        plot.setXRange(ms[0], ms[-1], padding=0.01)
        plot.setYRange(bottom - 0.60 * span, top + 0.12 * span, padding=0)
        return plot

    # --- beat-to-beat gaps --------------------------------------------

    def _gaps_plot(self):
        r = self._report
        plot = pg.PlotWidget()
        plot.setBackground(theme.PANEL_BG)
        plot.setMenuEnabled(False)
        plot.setMouseEnabled(x=False, y=False)
        plot.hideButtons()
        plot.showGrid(x=False, y=True, alpha=0.15)
        plot.setLabel("bottom", "Time in the recording (s)")
        plot.setLabel("left", "Gap", units="ms")
        plot.getAxis("left").enableAutoSIPrefix(False)

        # Grey bands where the recording was not clean.
        from app.analysis.report import BLOCK_S
        blocks = r.clean_blocks
        i = 0
        while i < len(blocks):
            if not blocks[i]:
                j = i
                while j < len(blocks) and not blocks[j]:
                    j += 1
                band = pg.LinearRegionItem((i * BLOCK_S, j * BLOCK_S), movable=False,
                                           brush=pg.mkBrush(UNCLEAN), pen=pg.mkPen(None))
                band.setZValue(-5)
                plot.addItem(band)
                i = j
            else:
                i += 1

        if len(r.rr_ms):
            clean = r.rr_clean
            plot.plot(r.rr_times_s[clean], r.rr_ms[clean], pen=None, symbol="o",
                      symbolSize=4, symbolPen=None, symbolBrush=pg.mkBrush(TRACE))
            plot.plot(r.rr_times_s[~clean], r.rr_ms[~clean], pen=None, symbol="o",
                      symbolSize=4, symbolPen=None,
                      symbolBrush=pg.mkBrush(theme.TEXT_MUTED))
            if len(r.early_times_s):
                idx = np.searchsorted(r.rr_times_s, r.early_times_s)
                idx = idx[idx < len(r.rr_ms)]
                plot.plot(r.rr_times_s[idx], r.rr_ms[idx], pen=None, symbol="t",
                          symbolSize=11, symbolPen=None, symbolBrush=pg.mkBrush(MARK))
            good = r.rr_ms[clean]
            if len(good):
                low, high = np.percentile(good, [1, 99])
                pad = 0.25 * (high - low) + 40
                plot.setYRange(max(0, low - pad), high + pad, padding=0)
            plot.setXRange(0, r.duration_s, padding=0.01)
        return plot

    # --- measurement table --------------------------------------------

    def _table(self):
        r, iv = self._report, self._report.intervals
        hr_range = (f"{r.heart_rate_range[0]:.0f}–{r.heart_rate_range[1]:.0f} bpm"
                    if r.heart_rate_range else "—")

        groups = (
            ("Rhythm", (
                ("Heart rate (average)", _fmt(r.heart_rate_bpm, "bpm"), "heart_rate"),
                ("Lowest – highest", hr_range, None),
                ("Early beats", f"{len(r.early_times_s)}", "early"),
                ("Long gaps", f"{len(r.long_times_s)}", None),
            )),
            ("Variability (normal-to-normal gaps)", (
                ("SDNN", _fmt(r.sdnn_ms), None),
                ("RMSSD", _fmt(r.rmssd_ms), None),
            )),
            ("Average beat", (
                ("P wave duration", _fmt(iv.p_duration_ms), "p_duration"),
                ("PR interval", _fmt(iv.pr_interval_ms), "pr_interval"),
                ("PR segment", _fmt(iv.pr_segment_ms), None),
                ("QRS duration", _fmt(iv.qrs_ms), "qrs"),
                ("QT interval", _fmt(iv.qt_ms), None),
                ("QTc (Bazett)", _fmt(iv.qtc_bazett_ms), "qtc"),
                ("QTc (Fridericia)", _fmt(iv.qtc_fridericia_ms), "qtc"),
            )),
        )

        frame = QFrame()
        frame.setObjectName("panel")
        frame.setFixedWidth(430)
        grid = QGridLayout(frame)
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(5)
        row = 0
        for heading in ("", "Value", "Typical range"):
            label = QLabel(heading)
            label.setObjectName("cardLabel")
            grid.addWidget(label, row, ("", "Value", "Typical range").index(heading))
        row += 1

        used_sources = []
        for title, items in groups:
            group = QLabel(title)
            group.setStyleSheet("font-size: 13px; font-weight: 600; padding-top: 8px;")
            grid.addWidget(group, row, 0, 1, 3)
            row += 1
            for label, value, ref_name in items:
                ref = reference(ref_name, self._sex) if ref_name else None
                if ref and ref.source not in used_sources:
                    used_sources.append(ref.source)
                hint = ("marked ▼ in the chart" if ref_name == "early"
                        and len(r.early_times_s) else "")
                name = QLabel(label)
                name.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 13px;")
                number = QLabel(value)
                number.setStyleSheet("font-size: 14px; font-weight: 600;")
                typical = QLabel(ref.text if ref else hint)
                typical.setObjectName("muted")
                typical.setWordWrap(True)
                grid.addWidget(name, row, 0)
                grid.addWidget(number, row, 1)
                grid.addWidget(typical, row, 2)
                row += 1

        note = QLabel(NOTE)
        note.setObjectName("muted")
        note.setWordWrap(True)
        grid.addWidget(note, row, 0, 1, 3)
        row += 1
        sources = QLabel("Sources: " + " · ".join(
            f"[{n + 1}] {SOURCES[s]}" for n, s in enumerate(used_sources)))
        sources.setObjectName("muted")
        sources.setStyleSheet("font-size: 11px;")
        sources.setWordWrap(True)
        grid.addWidget(sources, row, 0, 1, 3)
        grid.setRowStretch(row + 1, 1)
        grid.setColumnMinimumWidth(0, 150)
        grid.setColumnMinimumWidth(1, 80)
        grid.setColumnStretch(2, 1)
        return frame


def open_saved(path):
    """Build a ReportWindow for a saved recording (path without extension)."""
    from app.acquisition.record_loader import RecordLoader
    from app.analysis.report import build_report

    loader = RecordLoader(path, channel_name="ECG" if "recordings" in
                          str(path).replace("\\", "/") else "MLII")
    signal, fs = loader.load()
    info = {}
    meta = Path(f"{path}.json")
    if meta.exists():
        info = json.loads(meta.read_text(encoding="utf-8"))
    details = " · ".join(str(x) for x in (info.get("gender"), info.get("age"),
                                          info.get("notes")) if x)
    return ReportWindow(build_report(signal, fs), Path(path).name, details,
                        units=loader.units, sex=info.get("gender"))


if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setStyleSheet(theme.stylesheet())
    window = open_saved(sys.argv[1] if len(sys.argv) > 1 else "data/sample/100")
    window.show()
    sys.exit(app.exec())