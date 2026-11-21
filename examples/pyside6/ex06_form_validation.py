# /// script
# requires-python = ">=3.14"
# dependencies = ["PySide6-Essentials==6.12.0"]
# ///
"""The "New Experiment" form, wired to polari's validate().

Run with the real validation (needs polari_app.experiment from PR #1):
    PYTHONPATH=../../packages/polari-app/src uv run ex06_form_validation.py
Run on its own (uses a tiny stand-in for the rules):
    uv run ex06_form_validation.py

Shows:
- The form collects plain strings -> parse_form -> validate -> details or errors.
- Every FieldError appears under its own field, which turns red.
- Typing in a field clears its error.

Try: submit an empty form, then the date 31-02-2026.
"""

import dataclasses
import datetime as dt
import json
import sys

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

try:
    from polari_app.experiment import parse_form, validate

    SOURCE = "polari_app.experiment (real code)"
except ImportError:
    SOURCE = "stand-in rules (set PYTHONPATH to use polari)"

    @dataclasses.dataclass
    class FieldError:
        field: str
        message: str

    def parse_form(values: dict[str, str]) -> dict[str, str]:
        return values

    def validate(raw: dict[str, str]) -> dict | list[FieldError]:
        errors = [
            FieldError(name, f"{name.capitalize()} is required.")
            for name in ("title", "pilot", "purpose")
            if not raw[name].strip()
        ]
        try:
            dt.datetime.strptime(raw["date"].strip(), "%d-%m-%Y")
        except ValueError:
            errors.append(FieldError("date", "Date must be a real date, DD-MM-YYYY."))
        return errors or raw


STYLE = """
QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"] { border: 2px solid #d33; }
QLabel[error="true"] { color: #d33; }
"""


class NewExperimentForm(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("06 - Form validation")
        self.setStyleSheet(STYLE)
        self.resize(520, 620)

        self.title = QLineEdit(placeholderText="e.g. MI baseline")
        self.pilot = QLineEdit(placeholderText="e.g. p18")
        # Blocks bad characters while typing; validate() still has the final say.
        self.pilot.setValidator(QRegularExpressionValidator(QRegularExpression(r"[A-Za-z0-9_-]*")))
        self.purpose = QPlainTextEdit(placeholderText="What is this experiment for?")
        self.purpose.setFixedHeight(70)
        self.tiredness = QSlider(Qt.Orientation.Horizontal, minimum=0, maximum=10)
        self.date = QLineEdit(placeholderText="DD-MM-YYYY")
        self.experimenter = QLineEdit()
        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(60)

        self.inputs = {
            "title": self.title,
            "pilot": self.pilot,
            "purpose": self.purpose,
            "date": self.date,
            "experimenter": self.experimenter,
            "notes": self.notes,
        }
        self.errors = {name: self.error_label() for name in [*self.inputs, "tiredness"]}

        tiredness_value = QLabel("0")
        self.tiredness.valueChanged.connect(lambda v: tiredness_value.setText(str(v)))
        tiredness_row = QHBoxLayout()
        tiredness_row.addWidget(self.tiredness, 1)
        tiredness_row.addWidget(tiredness_value)

        today = QPushButton("Today")
        today.clicked.connect(lambda: self.date.setText(dt.date.today().strftime("%d-%m-%Y")))
        date_row = QHBoxLayout()
        date_row.addWidget(self.date, 1)
        date_row.addWidget(today)

        form = QFormLayout()
        for label, field, name in [
            ("Title *", self.title, "title"),
            ("Pilot *", self.pilot, "pilot"),
            ("Purpose *", self.purpose, "purpose"),
            ("Tiredness", tiredness_row, "tiredness"),
            ("Date *", date_row, "date"),
            ("Experimenter", self.experimenter, "experimenter"),
            ("Notes", self.notes, "notes"),
        ]:
            form.addRow(label, field)
            form.addRow("", self.errors[name])

        self.summary = QLabel(f"Validation: {SOURCE}")
        self.create_button = QPushButton("Create experiment")
        self.create_button.clicked.connect(self.submit)
        self.preview = QPlainTextEdit(readOnly=True, placeholderText="JSON preview")

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addLayout(form)
        layout.addWidget(self.create_button)
        layout.addWidget(self.preview, 1)

        for name, widget in self.inputs.items():
            widget.textChanged.connect(lambda *_, name=name: self.clear_error(name))

    def error_label(self) -> QLabel:
        label = QLabel(wordWrap=True)
        label.setProperty("error", True)
        label.hide()
        return label

    def values(self) -> dict[str, str]:
        values = {
            name: widget.toPlainText() if isinstance(widget, QPlainTextEdit) else widget.text()
            for name, widget in self.inputs.items()
        }
        values["tiredness"] = str(self.tiredness.value())
        return values

    def submit(self) -> None:
        for name in self.errors:
            self.clear_error(name)

        result = validate(parse_form(self.values()))
        if isinstance(result, list):
            for error in result:
                self.show_error(error.field, error.message)
            self.summary.setText(f"{len(result)} problem(s), see the red fields.")
            return

        self.summary.setText("Valid. This is what would be saved:")
        details = dataclasses.asdict(result) if dataclasses.is_dataclass(result) else result
        self.preview.setPlainText(json.dumps(details, indent=2, default=str))

    def show_error(self, name: str, message: str) -> None:
        self.errors[name].setText(message)
        self.errors[name].show()
        self.set_invalid(name, True)

    def clear_error(self, name: str) -> None:
        self.errors[name].hide()
        self.set_invalid(name, False)

    def set_invalid(self, name: str, invalid: bool) -> None:
        widget = self.inputs.get(name)
        if widget is not None and bool(widget.property("invalid")) != invalid:
            widget.setProperty("invalid", invalid)
            widget.style().polish(widget)  # Qt only re-reads the stylesheet on polish


def main() -> None:
    app = QApplication(sys.argv)
    form = NewExperimentForm()
    form.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
