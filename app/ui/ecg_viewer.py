"""The whole recording as ECG strips, the way it would look printed on ECG paper.

Each row is 10 seconds and a page holds 5 minutes (30 rows). Marked
beats (early, or shaped unlike the usual beat) get a ▼ above them; in
an exercise test every row says which phase it is in. Any page can be
saved as an image, labelled with the subject ID only.

To view a saved recording:

    py -m app.ui.ecg_viewer recordings/S001/S001_20261022_100003
"""

from pathlib import Path

import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters  # noqa: F401  (makes pg.exporters available)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from app.ui import theme
from app.ui.widgets import format_mmss

ROW_S = 10.0              # seconds per row
ROWS_PER_PAGE = 30        # 5 minutes per page
ROW_PX = 125              # height of one row on screen
SMALL_S, LARGE_S = 0.04, 0.20   # ECG paper: small and large squares (25 mm/s)
SQUARES_HIGH = 25         # small squares from the bottom to the top of a row
EXPORT_WIDTH = 2400       # pixels across a saved page

PAPER = QColor(255, 251, 250)
MINOR = QColor(252, 234, 230)
MAJOR = QColor(242, 190, 180)
TRACE = QColor(15, 15, 15)
MARK = QColor(133, 79, 11)
PHASE = QColor(12, 68, 124)


def _segments(xs0, xs1, ys0, ys1):
    """Points for many separate straight lines, drawn as one item (connect='pairs')."""
    x = np.column_stack([xs0, xs1]).ravel()
    y = np.column_stack([ys0, ys1]).ravel()
    return x, y


class ECGViewer(QWidget):
    """A window showing a whole recording as rows of ECG paper, a page at a time."""

    def __init__(self, filtered, fs, title, details="", marks=(), phases=(),
                 save_dir=None, parent=None):
        super().__init__(parent)
        self.setObjectName("central")
        self.setWindowTitle(f"ECG · {title}")
        self.resize(1400, 900)
        self._x = np.asarray(filtered, dtype=float)
        self._fs = float(fs)
        self._title = title
        self._marks = np.asarray(marks, dtype=float)
        self._phases = list(phases)
        self._save_dir = Path(save_dir) if save_dir else None
        self._duration = len(self._x) / self._fs

        # One vertical scale for the whole recording: the trace's usual
        # extent (ignoring the most extreme 0.5% at each end), with room
        # above for the markers. Anything bigger is clipped to its row.
        lo, hi = np.percentile(self._x, [0.5, 99.5]) if len(self._x) else (-1.0, 1.0)
        span = max(hi - lo, 1e-9)
        self._row_lo, self._row_hi = lo - 0.20 * span, hi + 0.30 * span
        self._row_h = self._row_hi - self._row_lo

        pages = max(1, int(np.ceil(self._duration / (ROW_S * ROWS_PER_PAGE))))
        self.page_box = QComboBox()
        for p in range(pages):
            start = p * ROW_S * ROWS_PER_PAGE
            end = min(self._duration, start + ROW_S * ROWS_PER_PAGE)
            self.page_box.addItem(f"{format_mmss(start)} – {format_mmss(end)}", p)
        self.page_box.currentIndexChanged.connect(self._draw)

        self.save_button = QPushButton("Save this page as an image")
        self.save_button.clicked.connect(self._save)
        self.save_button.setEnabled(self._save_dir is not None)
        self.saved_label = QLabel()
        self.saved_label.setObjectName("muted")

        self.plot = pg.PlotWidget()
        self.plot.setBackground(PAPER)
        self.plot.setMenuEnabled(False)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.hideButtons()
        for side in ("left", "bottom"):
            self.plot.hideAxis(side)
        self.plot.getPlotItem().layout.setContentsMargins(4, 4, 12, 4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.plot)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._header(title, details))
        root.addWidget(scroll, 1)
        self._draw()

    # --- pieces -------------------------------------------------------

    def _header(self, title, details):
        bar = QFrame()
        bar.setObjectName("panel")
        name = QLabel("Whole ECG")
        name.setStyleSheet("font-size: 17px; font-weight: 600;")
        sub = QLabel(" · ".join(x for x in (title, format_mmss(self._duration), details) if x))
        sub.setObjectName("muted")
        scale = QLabel("10 s per row · small square 0.04 s · filtered 0.5–40 Hz · "
                       "amplitude uncalibrated · ▼ marked beat (early, or shaped "
                       "unlike the usual beat)")
        scale.setObjectName("muted")
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(name)
        text.addWidget(sub)
        text.addWidget(scale)

        page = QLabel("Minutes")
        page.setObjectName("cardLabel")
        controls = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(page)
        row.addWidget(self.page_box)
        row.addWidget(self.save_button)
        controls.addLayout(row)
        controls.addWidget(self.saved_label)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.addLayout(text)
        layout.addStretch()
        layout.addLayout(controls)
        return bar

    def _phase_at(self, t):
        for p in self._phases:
            if p.start_s <= t < p.end_s:
                return p
        return None

    # --- drawing ------------------------------------------------------

    def _draw(self):
        """Draw the current page: paper, trace, time labels, phases, markers."""
        self.plot.clear()
        self.saved_label.setText("")
        page = self.page_box.currentData() or 0
        first = page * ROWS_PER_PAGE
        rows = [first + i for i in range(ROWS_PER_PAGE)
                if (first + i) * ROW_S < self._duration]
        n = len(rows)
        tops = -np.arange(n) * self._row_h          # each row sits below the last
        bottoms = tops - self._row_h

        # Paper: vertical lines every 0.04 s (darker every 0.2 s) and
        # horizontal lines, in every row.
        for step, colour, every in ((SMALL_S, MINOR, 1), (LARGE_S, MAJOR, 5)):
            ticks = np.arange(0.0, ROW_S + 1e-9, step)
            xs = np.tile(ticks, n)
            y0 = np.repeat(bottoms, len(ticks))
            y1 = np.repeat(tops, len(ticks))
            levels = np.linspace(0.0, 1.0, SQUARES_HIGH + 1)[::every]
            hy = (bottoms[:, None] + levels[None, :] * self._row_h).ravel()
            x, y = _segments(np.concatenate([xs, np.zeros(len(hy))]),
                             np.concatenate([xs, np.full(len(hy), ROW_S)]),
                             np.concatenate([y0, hy]), np.concatenate([y1, hy]))
            item = pg.PlotDataItem(x, y, connect="pairs", pen=pg.mkPen(colour, width=1))
            item.setZValue(-10 if colour == MINOR else -9)
            self.plot.addItem(item)

        # The trace: all rows as one line, broken (NaN) between rows.
        xs, ys = [], []
        for i, r in enumerate(rows):
            a = int(r * ROW_S * self._fs)
            b = min(len(self._x), int((r + 1) * ROW_S * self._fs))
            seg = np.clip(self._x[a:b], self._row_lo, self._row_hi)
            xs += [np.arange(b - a) / self._fs, [np.nan]]
            ys += [seg - self._row_hi + tops[i], [np.nan]]
        if xs:
            self.plot.plot(np.concatenate(xs), np.concatenate(ys),
                           pen=pg.mkPen(TRACE, width=1.1), connect="finite")

        for i, r in enumerate(rows):
            start = r * ROW_S
            label = pg.TextItem(format_mmss(start), color=theme.TEXT_SECONDARY, anchor=(1, 0.5))
            label.setPos(-0.08, tops[i] - self._row_h / 2)
            self.plot.addItem(label)
            phase = self._phase_at(start)
            if phase is not None:
                tag = pg.TextItem(phase.label, color=PHASE, anchor=(0, 0))
                tag.setPos(0.05, tops[i])
                self.plot.addItem(tag)
            # A phase that starts inside this row: a line and its name.
            for p in self._phases:
                if start < p.start_s < start + ROW_S:
                    x = p.start_s - start
                    self.plot.plot([x, x], [bottoms[i], tops[i]],
                                   pen=pg.mkPen(PHASE, width=1.5))
                    tag = pg.TextItem(p.label, color=PHASE, anchor=(0, 0))
                    tag.setPos(x + 0.05, tops[i])
                    self.plot.addItem(tag)
            here = self._marks[(self._marks >= start) & (self._marks < start + ROW_S)]
            if len(here):
                self.plot.plot(here - start, np.full(len(here), tops[i] - 0.08 * self._row_h),
                               pen=None, symbol="t", symbolSize=10, symbolPen=None,
                               symbolBrush=pg.mkBrush(MARK))

        self.plot.setFixedHeight(max(1, n) * ROW_PX + 8)
        self.plot.setXRange(-0.9, ROW_S + 0.02, padding=0)
        self.plot.setYRange(bottoms[-1] if n else -1, 0, padding=0)

    # --- saving -------------------------------------------------------

    def _save(self):
        page = (self.page_box.currentData() or 0) + 1
        path = self._save_dir / f"{self._title}_ecg_page{page}.png"
        exporter = pg.exporters.ImageExporter(self.plot.getPlotItem())
        exporter.parameters()["width"] = EXPORT_WIDTH
        exporter.export(str(path))
        self.saved_label.setText(f"Saved: {path}")


def recording_folder(title):
    """The folder a recording called `title` (e.g. S001_20261022_100003) is saved in.

    None if there isn't one (e.g. a replayed MIT-BIH record): then there
    is nowhere to save pages, and saving is switched off.
    """
    folder = Path("recordings") / title.split("_")[0]
    return folder if folder.is_dir() and (folder / f"{title}.json").exists() else None


def saved_viewer(path):
    """Build the viewer for a saved recording (path without extension)."""
    import json

    from app.acquisition.record_loader import RecordLoader
    from app.signal_processing.filters import preprocess

    path = Path(path).with_suffix("")
    meta_file = path.with_suffix(".json")
    meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    signal, fs = RecordLoader(str(path), channel_name="ECG" if "recordings" in
                              str(path).replace("\\", "/") else "MLII").load()
    details = " · ".join(str(meta[k]) for k in ("gender", "age", "notes") if meta.get(k))
    if meta.get("phases"):
        from app.analysis.exercise_test import analyse_exercise, phases_from_dicts
        phases = phases_from_dicts(meta["phases"])
        marks = analyse_exercise(signal, fs, phases, meta.get("age")).unusual_t
    else:
        from app.analysis.report import build_report
        phases, marks = [], build_report(signal, fs).early_times_s
    save_dir = path.parent if "recordings" in str(path).replace("\\", "/") else None
    return ECGViewer(preprocess(signal, fs), fs, path.name, details, marks, phases, save_dir)


if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setStyleSheet(theme.stylesheet())
    window = saved_viewer(sys.argv[1] if len(sys.argv) > 1 else "data/sample/100")
    window.show()
    sys.exit(app.exec())