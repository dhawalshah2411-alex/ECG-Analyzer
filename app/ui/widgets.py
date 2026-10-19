"""Reusable display widgets for the ECG Analyzer interface."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from app.ui import theme

PLACEHOLDER = "—"   # shown when no trustworthy value exists


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