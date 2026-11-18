"""Check the "New Experiment" form.

The GUI reads the form as text, turns it into a ``RawExperiment`` with
``parse_form`` and checks it with ``validate``::

    result = validate(parse_form({"title": title_edit.text(), ...}))
    if isinstance(result, ExperimentDetails):
        ...  # save it
    else:
        ...  # show each error next to error.field

``validate`` never raises for bad input. It returns every problem at once,
so the user can fix the whole form in one go.
"""

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import fields

from polari_app.experiment.models import ExperimentDetails, FieldError, RawExperiment

DATE_FORMAT = "%d-%m-%Y"  # day-month-year, e.g. 14-11-2026
TIREDNESS_MIN = 0
TIREDNESS_MAX = 10
MAX_LENGTH = {
    "title": 120,
    "pilot": 32,
    "purpose": 2000,
    "experimenter": 80,
    "notes": 5000,
}

# Pilot ids are used in folder names, so only allow safe characters.
PILOT_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
DATE_PATTERN = re.compile(r"[0-9]{2}-[0-9]{2}-[0-9]{4}")


def parse_form(values: Mapping[str, str]) -> RawExperiment:
    """Turn the form's text values into a ``RawExperiment``.

    Missing keys become empty strings. Unknown keys are ignored, so the GUI
    can pass extra widgets without breaking anything.
    """
    names = {f.name for f in fields(RawExperiment)}
    return RawExperiment(**{k: v for k, v in values.items() if k in names})


def validate(raw: RawExperiment) -> ExperimentDetails | list[FieldError]:
    """Return the checked details, or the list of all problems (never empty)."""
    errors: list[FieldError] = []

    title = _text(raw.title, "title", errors, required=True)
    pilot = _pilot(raw.pilot, errors)
    purpose = _text(raw.purpose, "purpose", errors, required=True)
    tiredness = _tiredness(raw.tiredness, errors)
    date = _date(raw.date, errors)
    experimenter = _text(raw.experimenter, "experimenter", errors)
    notes = _text(raw.notes, "notes", errors)

    if errors or tiredness is None or date is None:
        return errors

    return ExperimentDetails(
        title=title,
        pilot=pilot,
        purpose=purpose,
        tiredness=tiredness,
        date=date,
        experimenter=experimenter,
        notes=notes,
    )


def _text(
    value: str, field: str, errors: list[FieldError], required: bool = False
) -> str:
    text = value.strip()
    label = field.capitalize()
    limit = MAX_LENGTH[field]
    if required and not text:
        errors.append(FieldError(field, f"{label} is required."))
    elif len(text) > limit:
        message = f"{label} is too long: {len(text)} characters, the limit is {limit}."
        errors.append(FieldError(field, message))
    return text


def _pilot(value: str, errors: list[FieldError]) -> str:
    pilot = _text(value, "pilot", errors, required=True)
    length_ok = 0 < len(pilot) <= MAX_LENGTH["pilot"]
    if length_ok and not PILOT_PATTERN.fullmatch(pilot):
        message = (
            f"Pilot may only contain letters, digits, '-' and '_' (got {pilot!r}). "
            "It is used in folder names."
        )
        errors.append(FieldError("pilot", message))
    return pilot


def _tiredness(value: str, errors: list[FieldError]) -> int | None:
    text = value.strip()
    allowed = f"a whole number from {TIREDNESS_MIN} to {TIREDNESS_MAX}"
    if not text:
        errors.append(FieldError("tiredness", f"Tiredness is required ({allowed})."))
        return None

    try:
        number = int(text)
    except ValueError:
        number = None
    if number is None or not TIREDNESS_MIN <= number <= TIREDNESS_MAX:
        message = f"Tiredness must be {allowed} (got {text})."
        errors.append(FieldError("tiredness", message))
        return None
    return number


def _date(value: str, errors: list[FieldError]) -> dt.date | None:
    text = value.strip()
    hint = "format DD-MM-YYYY, e.g. 14-11-2026"
    if not text:
        errors.append(FieldError("date", f"Date is required ({hint})."))
        return None

    # strptime alone would also accept "1-11-2026", so check the shape first.
    if DATE_PATTERN.fullmatch(text):
        try:
            return dt.datetime.strptime(text, DATE_FORMAT).date()
        except ValueError:  # right shape but not a real day, e.g. 30-02-2026
            pass
    message = f"Date must be a real date ({hint}), got {text!r}."
    errors.append(FieldError("date", message))
    return None
