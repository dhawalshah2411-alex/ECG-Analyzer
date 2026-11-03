"""Dialog for starting a recording, in two steps.

Step 1 - the person: name, age, gender, profession, city, consent.
Step 2 - the test: resting recording or exercise test, its timing, notes.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSpinBox, QVBoxLayout,
                               QWidget)

from app.analysis.exercise_test import build_phases, phases_to_dicts
from app.ui import theme

GENDERS = ["Male", "Female", "Other", "Prefer not to say"]
TESTS = [("Resting recording", "resting"), ("Exercise test", "exercise")]

# The whole recording is held in memory and saved only when it ends, and
# the laptop must run on battery while electrodes are on, so a dead
# battery or a crash loses everything. 60 minutes keeps that risk small.
MAX_MINUTES = 60
SCREEN_SHARE = 0.9   # the dialog never gets taller than 90% of the screen

# Exercise-test settings: (label, shortest, longest, default, unit)
EXERCISE_FIELDS = {
    "rest_before": ("Rest before", 1, 10, 2, " min"),
    "rounds": ("Rounds", 1, 10, 3, ""),
    "exercise": ("Exercise per round", 1, 20, 4, " min"),
    "rest_between": ("Rest between rounds", 0, 10, 1, " min"),
    "recovery": ("Final recovery", 3, 20, 5, " min"),
}

EXERCISE_NOTE = (
    "<b>Exercise test.</b> Recording runs the whole time, exercise included. A banner "
    "and a beep tell the person when to start and stop; nothing needs pressing. "
    "During the rests between rounds, stand still (on a treadmill: stop the belt and "
    "stand on it). For the final recovery, sit down at once and stay still.<br><br>"
    f"<b style='color:{theme.ACCENT}'>Safety:</b> moderate effort only; walking pace "
    "on a treadmill, with its safety key clipped on. Stop at once for chest pain, "
    "dizziness or unusual breathlessness (press “Stop and save”). Not for anyone "
    "told by a doctor to avoid exercise. Laptop charger unplugged; cable taped to "
    "clothing, away from any moving belt."
)

STEPS = ("Step 1 of 2 · The person", "Step 2 of 2 · The test")


class RecordingDialog(QDialog):
    """Collects subject details, then recording settings, before starting."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New recording")
        self.setMinimumWidth(480)

        # --- step 1: the person ---------------------------------------
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

        self.consent_box = QCheckBox(
            "This person has agreed to be recorded and to the recording being stored."
        )
        privacy = QLabel("Name, profession and city are kept only in the private "
                         "subject list — never in the recording files.")
        privacy.setObjectName("muted")
        privacy.setWordWrap(True)

        person_form = QFormLayout()
        person_form.setSpacing(10)
        person_form.addRow("Name", self.name_edit)
        person_form.addRow("Age", self.age_spin)
        person_form.addRow("Gender", self.gender_combo)
        person_form.addRow("Profession", self.profession_edit)
        person_form.addRow("City", self.city_edit)
        person_page = self._page(person_form, self.consent_box, privacy)

        # --- step 2: the test -----------------------------------------
        self.test_combo = QComboBox()
        for name, key in TESTS:
            self.test_combo.addItem(name, key)

        self.duration_spin = self._spin(1, MAX_MINUTES, 5, " min")
        self.exercise_spins = {key: self._spin(lo, hi, default, unit)
                               for key, (_label, lo, hi, default, unit)
                               in EXERCISE_FIELDS.items()}
        self.total_label = QLabel()
        self.notes_edit = QLineEdit()

        self.test_note = QLabel(EXERCISE_NOTE)
        self.test_note.setWordWrap(True)
        self.test_note.setStyleSheet(
            f"background: {theme.CARD_BG}; border: 1px solid {theme.BORDER};"
            f" border-radius: 6px; padding: 8px; font-size: 12px;")

        self.form = QFormLayout()
        self.form.setSpacing(10)
        self.form.addRow("Test", self.test_combo)
        self.form.addRow("Duration", self.duration_spin)
        for key, spin in self.exercise_spins.items():
            self.form.addRow(EXERCISE_FIELDS[key][0], spin)
            spin.valueChanged.connect(self._show_total)
        self.form.addRow("Total", self.total_label)
        self.form.addRow("Notes", self.notes_edit)
        test_page = self._page(self.form, self.test_note)

        # --- the two steps, one at a time -----------------------------
        self.step_label = QLabel()
        self.step_label.setObjectName("cardLabel")
        self.pages = (person_page, test_page)     # only one is shown at a time

        # The page area scrolls if it is ever taller than the screen.
        content = QWidget()
        inner = QVBoxLayout(content)
        inner.setContentsMargins(20, 16, 20, 8)
        inner.setSpacing(12)
        inner.addWidget(self.step_label)
        for page in self.pages:
            inner.addWidget(page)
        inner.addStretch()
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(content)
        self._content = content

        self.error_label = QLabel()
        self.error_label.setStyleSheet(f"color: {theme.ACCENT}; font-size: 12px;")
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.back_button = QPushButton("← Back")
        self.back_button.clicked.connect(lambda: self._go_to(0))
        self.next_button = QPushButton("Next →")
        self.next_button.clicked.connect(self._try_next)
        self.start_button = QPushButton("Start recording")
        self.start_button.clicked.connect(self._try_accept)

        buttons = QHBoxLayout()
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        for button in (self.back_button, self.next_button, self.start_button):
            buttons.addWidget(button)

        self._bottom = QWidget()
        bottom = QVBoxLayout(self._bottom)
        bottom.setContentsMargins(20, 6, 20, 16)
        bottom.addWidget(self.error_label)
        bottom.addLayout(buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._scroll, 1)
        layout.addWidget(self._bottom)

        self.test_combo.currentIndexChanged.connect(self._show_test)
        self._show_test()
        self._go_to(0)

    # --- building blocks ----------------------------------------------

    @staticmethod
    def _page(form, *widgets):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(form)
        for widget in widgets:
            layout.addWidget(widget)
        return page

    @staticmethod
    def _spin(lo, hi, default, unit):
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setValue(default)
        spin.setSuffix(unit)
        return spin

    def _set_row_visible(self, field, visible):
        self.form.labelForField(field).setVisible(visible)
        field.setVisible(visible)

    # --- moving between the steps -------------------------------------

    def _go_to(self, index):
        """Show step 1 or step 2, with its own buttons; size the dialog to it."""
        for i, page in enumerate(self.pages):
            page.setVisible(i == index)
        self.step_label.setText(STEPS[index])
        self.back_button.setVisible(index == 1)
        self.next_button.setVisible(index == 0)
        self.start_button.setVisible(index == 1)
        (self.next_button if index == 0 else self.start_button).setDefault(True)
        self.error_label.hide()
        self._fit_to_screen()

    def _try_next(self):
        if self._show_problems(self._person_problems()):
            self._go_to(1)

    def _try_accept(self):
        if self._show_problems(self._test_problems()):
            self.accept()

    def _show_problems(self, problems):
        """Show what must be fixed; True if nothing."""
        self.error_label.setText("\n".join(problems))
        self.error_label.setVisible(bool(problems))
        self._fit_to_screen()
        return not problems

    def _person_problems(self):
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

    def _test_problems(self):
        if self._is_exercise() and self._total_minutes() > MAX_MINUTES:
            return [f"The test adds up to more than {MAX_MINUTES} minutes."]
        return []

    # --- step 2 contents ----------------------------------------------

    def _is_exercise(self):
        return self.test_combo.currentData() == "exercise"

    def _show_test(self):
        """Show the settings and instructions for the chosen test."""
        exercise = self._is_exercise()
        self._set_row_visible(self.duration_spin, not exercise)
        for spin in self.exercise_spins.values():
            self._set_row_visible(spin, exercise)
        self._set_row_visible(self.total_label, exercise)
        self.test_note.setVisible(exercise)
        self.notes_edit.setPlaceholderText(
            "Exercise: e.g. treadmill walk, speed and slope" if exercise else "Seated, resting")
        self._show_total()
        self._fit_to_screen()

    def _phases(self):
        m = {key: spin.value() for key, spin in self.exercise_spins.items()}
        return build_phases(m["rest_before"] * 60, m["rounds"], m["exercise"] * 60,
                            m["rest_between"] * 60, m["recovery"] * 60)

    def _total_minutes(self):
        return self._phases()[-1].end_s / 60.0

    def _show_total(self):
        total = self._total_minutes()
        colour = theme.ACCENT if total > MAX_MINUTES else theme.TEXT_PRIMARY
        self.total_label.setText(f"{total:.0f} min" + (f"  (limit {MAX_MINUTES})"
                                                         if total > MAX_MINUTES else ""))
        self.total_label.setStyleSheet(f"color: {colour}; font-weight: 600;")

    # --- size ---------------------------------------------------------

    def _fit_to_screen(self):
        """Resize once Qt has finished laying out what was just shown or hidden."""
        QTimer.singleShot(0, self._fit_now)

    def _fit_now(self):
        """As tall as the current step, but never taller than the screen; kept on screen."""
        screen = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        self._content.layout().activate()
        wanted = (self._content.sizeHint().height() + self._bottom.sizeHint().height()
                  + 2 * self._scroll.frameWidth())
        self.resize(self.width(), min(wanted, int(SCREEN_SHARE * screen.height())))
        if self.isVisible():
            frame = self.frameGeometry()
            top = min(frame.top(), screen.bottom() - frame.height())
            self.move(frame.left(), max(screen.top(), top))

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_now()

    # --- result -------------------------------------------------------

    def values(self):
        """The details entered, once the dialog has been accepted.

        For an exercise test, phases is its timetable (one dict per phase,
        times in seconds from the start), and duration_s its total length.
        """
        exercise = self._is_exercise()
        phases = self._phases() if exercise else []
        return {
            "name": self.name_edit.text().strip(),
            "age": self.age_spin.value(),
            "gender": self.gender_combo.currentText(),
            "profession": self.profession_edit.text().strip(),
            "city": self.city_edit.text().strip(),
            "test": self.test_combo.currentData(),
            "phases": phases_to_dicts(phases),
            "duration_s": phases[-1].end_s if exercise else self.duration_spin.value() * 60,
            "notes": self.notes_edit.text().strip(),
        }