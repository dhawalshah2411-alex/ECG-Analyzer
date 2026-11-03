"""Reusable display widgets for the ECG Analyzer interface."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QVBoxLayout)

from app.ui import theme

PLACEHOLDER = "—"   # shown when no trustworthy value exists


def format_mmss(seconds):
    """Format a number of seconds as MM:SS."""
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class MetricCard(QFrame):
    """A labelled number with a unit, e.g. 'Heart rate  76 bpm'."""

    def __init__(self, label, unit="", decimals=0, value_size=20, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.decimals = decimals

        self._label = QLabel(label)
        self._label.setObjectName("cardLabel")

        self._value = QLabel(PLACEHOLDER)
        self._value.setStyleSheet(f"font-size: {value_size}px; font-weight: 600;")

        self._unit = QLabel(unit)
        self._unit.setObjectName("muted")

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self._value, 0, Qt.AlignmentFlag.AlignBottom)
        row.addWidget(self._unit, 0, Qt.AlignmentFlag.AlignBottom)
        row.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        layout.addWidget(self._label)
        layout.addLayout(row)

    def set_value(self, value):
        """Show a number, or the placeholder if value is None."""
        if value is None:
            self._value.setText(PLACEHOLDER)
        else:
            self._value.setText(f"{value:.{self.decimals}f}")


class QualityCard(QFrame):
    """Signal-quality indicator whose colour follows its state."""

    STATE_TEXT = {"good": "Good", "fair": "Fair", "poor": "Poor",
                  "unknown": "Checking…"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("quality")

        self._title = QLabel("Signal quality")
        self._title.setStyleSheet("font-size: 12px;")
        self._state = QLabel()
        self._state.setStyleSheet("font-size: 16px; font-weight: 600;")
        self._reason = QLabel()
        self._reason.setStyleSheet("font-size: 11px;")
        self._reason.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        layout.addWidget(self._title)
        layout.addWidget(self._state)
        layout.addWidget(self._reason)

        self.set_state("unknown")

    def set_state(self, state, reason=""):
        """Set 'good', 'fair', 'poor' or 'unknown', with an optional reason."""
        bg, fg = theme.QUALITY_COLOURS.get(state, theme.QUALITY_COLOURS["unknown"])
        self.setStyleSheet(
            f"QFrame#quality {{ background: {bg}; border-radius: 8px; }}"
            f"QLabel {{ color: {fg}; background: transparent; }}"
        )
        self._state.setText(self.STATE_TEXT.get(state, "Checking…"))
        self._reason.setText(reason)
        self._reason.setVisible(bool(reason))


class RecordingCard(QFrame):
    """Shows the session state: idle, settling, or recording."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")

        self._title = QLabel("Recording")
        self._title.setObjectName("cardLabel")
        self._state = QLabel()
        self._detail = QLabel()
        self._detail.setObjectName("muted")
        self._detail.setWordWrap(True)

        self._bar = QProgressBar()
        self._bar.setRange(0, 1000)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        self._bar.setStyleSheet(
            f"QProgressBar {{ background: {theme.BORDER}; border: none; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {theme.ACCENT}; border-radius: 3px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(4)
        layout.addWidget(self._title)
        layout.addWidget(self._state)
        layout.addWidget(self._detail)
        layout.addWidget(self._bar)

        self.set_idle()

    def _set_state(self, text, colour):
        self._state.setText(text)
        self._state.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {colour};")

    def set_idle(self, message="Press “New recording” to start."):
        """Show the not-recording state, with an optional message."""
        self._set_state("Not recording", theme.TEXT_SECONDARY)
        self._detail.setText(message)
        self._bar.hide()

    def set_settling(self, remaining_s, subject_id):
        """Show the settling countdown before recording begins."""
        self._set_state(f"Settling  {format_mmss(remaining_s)}", theme.SELECTED_TEXT)
        self._detail.setText(f"{subject_id} · recording starts automatically. Keep still.")
        self._bar.hide()

    def set_progress(self, elapsed_s, total_s, subject_id):
        """Show a running recording's elapsed and remaining time."""
        self._set_state(f"● REC  {format_mmss(elapsed_s)}", theme.ACCENT)
        remaining = max(0.0, total_s - elapsed_s)
        self._detail.setText(
            f"{subject_id} · {format_mmss(remaining)} left of {format_mmss(total_s)}")
        fraction = min(1.0, elapsed_s / total_s) if total_s else 0.0
        self._bar.setValue(int(1000 * fraction))
        self._bar.show()


class PhaseBanner(QFrame):
    """Large coloured strip telling the person what to do now, during an exercise test."""

    COLOURS = {                       # kind: (background, text)
        "baseline": (theme.SELECTED_BG, theme.SELECTED_TEXT),
        "exercise": (theme.ACCENT, "#FFFFFF"),
        "rest": theme.QUALITY_COLOURS["good"],
        "recovery": (theme.SELECTED_BG, theme.SELECTED_TEXT),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("banner")
        self._title = QLabel()
        self._title.setStyleSheet("font-size: 22px; font-weight: 700;")
        self._instruction = QLabel()
        self._instruction.setStyleSheet("font-size: 13px;")
        self._time = QLabel()
        self._time.setStyleSheet("font-size: 30px; font-weight: 700;")
        self._next = QLabel()
        self._next.setStyleSheet("font-size: 12px;")
        self._next.setAlignment(Qt.AlignmentFlag.AlignRight)

        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self._title)
        text.addWidget(self._instruction)
        clock = QVBoxLayout()
        clock.setSpacing(0)
        clock.addWidget(self._time, 0, Qt.AlignmentFlag.AlignRight)
        clock.addWidget(self._next)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.addLayout(text, 1)
        layout.addLayout(clock)
        self.hide()

    def show_phase(self, kind, title, instruction, left_s, next_text):
        """Show the current phase, its time left, and what comes next."""
        bg, fg = self.COLOURS.get(kind, self.COLOURS["baseline"])
        self.setStyleSheet(
            f"QFrame#banner {{ background: {bg}; border-radius: 8px; }}"
            f"QLabel {{ color: {fg}; background: transparent; }}")
        self._title.setText(title)
        self._instruction.setText(instruction)
        self._time.setText(format_mmss(left_s))
        self._next.setText(next_text)
        self.show()