"""Dialog for starting a recording: subject details, duration, consent."""

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSpinBox, QVBoxLayout)

from app.ui import theme

DURATIONS_MIN = [1, 3, 5, 10]
DEFAULT_DURATION_MIN = 5
GENDERS = ["Male", "Female", "Other", "Prefer not to say"]


class RecordingDialog(QDialog):
    """Collects subject details and recording settings before starting."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New recording")
        self.setMinimumWidth(440)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Full name")

        self.age_spin = QSpinBox()
        self.age_spin.setRange(0, 120)
        self.age_spin.setSpecialValueText("—")      # 0 means "not entered"

        self.gender_combo = QComboBox()
        self.gender_combo.addItem("Select…")
        self.gender_combo.addItems(GENDERS)

        self.profession_edit = QLineEdit()
        self.profession_edit.setPlaceholderText("Student, teacher, athlete…")
        self.city_edit = QLineEdit()
        self.city_edit.setPlaceholderText("Raipur")

        self.duration_combo = QComboBox()
        for minutes in DURATIONS_MIN:
            label = f"{minutes} minute" + ("s" if minutes > 1 else "")
            self.duration_combo.addItem(label, minutes)
        self.duration_combo.setCurrentIndex(DURATIONS_MIN.index(DEFAULT_DURATION_MIN))

        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Seated, resting")

        self.consent_box = QCheckBox(
            "This person has agreed to be recorded and to the recording being stored."
        )

        privacy = QLabel("Name, profession and city are kept only in the private "
                         "subject list — never in the recording files.")
        privacy.setObjectName("muted")
        privacy.setWordWrap(True)

        self.error_label = QLabel()
        self.error_label.setStyleSheet(f"color: {theme.ACCENT}; font-size: 12px;")
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("Name", self.name_edit)
        form.addRow("Age", self.age_spin)
        form.addRow("Gender", self.gender_combo)
        form.addRow("Profession", self.profession_edit)
        form.addRow("City", self.city_edit)
        form.addRow("Duration", self.duration_combo)
        form.addRow("Notes", self.notes_edit)

        start = QPushButton("Start recording")
        start.setDefault(True)
        start.clicked.connect(self._try_accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(start)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.consent_box)
        layout.addWidget(privacy)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

    def _problems(self):
        """List everything that must be fixed before recording can start."""
        problems = []
        if not self.name_edit.text().strip():
            problems.append("Enter the person's name.")
        if self.age_spin.value() == 0:
            problems.append("Enter their age.")
        if self.gender_combo.currentIndex() == 0:
            problems.append("Choose a gender option.")
        if not self.consent_box.isChecked():
            problems.append("Recording needs the person's consent.")
        return problems

    def _try_accept(self):
        problems = self._problems()
        if problems:
            self.error_label.setText("\n".join(problems))
            self.error_label.show()
            return
        self.accept()

    def values(self):
        """The details entered, once the dialog has been accepted."""
        return {
            "name": self.name_edit.text().strip(),
            "age": self.age_spin.value(),
            "gender": self.gender_combo.currentText(),
            "profession": self.profession_edit.text().strip(),
            "city": self.city_edit.text().strip(),
            "duration_s": self.duration_combo.currentData() * 60,
            "notes": self.notes_edit.text().strip(),
        }