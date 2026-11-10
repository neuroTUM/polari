"""Parse and validate the "New Experiment" form.

Usage from the GUI::

    raw = parse_form({"title": title_edit.text(), "tiredness": str(slider.value()), ...})
    result = validate(raw)
    if isinstance(result, ExperimentDetails):
        ...  # save it
    else:
        for error in result:
            ...  # highlight error.field, show error.message

Validation never raises for bad user input. It returns every problem at
once, so the user can fix the whole form in one go.
"""

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import fields

from polari_app.experiment.models import (
    TIREDNESS_MAX,
    TIREDNESS_MIN,
    ExperimentDetails,
    FieldError,
    RawExperiment,
)

TITLE_MAX = 120
PILOT_MAX = 32
PURPOSE_MAX = 2000
EXPERIMENTER_MAX = 80
NOTES_MAX = 5000

# Pilot ids end up in folder and file names, so only allow safe characters.
_PILOT_PATTERN = re.compile(r"[A-Za-z0-9_-]+")

_FORM_FIELDS = frozenset(f.name for f in fields(RawExperiment))


def parse_form(values: Mapping[str, str]) -> RawExperiment:
    """Turn the form's text values into a ``RawExperiment``.

    Missing keys become empty strings. Unknown keys are ignored, so the
    GUI can pass extra widgets without breaking anything.
    """
    known = {key: value for key, value in values.items() if key in _FORM_FIELDS}
    return RawExperiment(**known)


def validate(raw: RawExperiment) -> ExperimentDetails | list[FieldError]:
    """Check a ``RawExperiment``.

    Returns the typed ``ExperimentDetails`` if everything is fine, otherwise
    the list of all problems (never an empty list).
    """
    errors: list[FieldError] = []

    title = _required_text(raw.title, "title", "Title", TITLE_MAX, errors)
    pilot = _pilot(raw.pilot, errors)
    purpose = _required_text(raw.purpose, "purpose", "Purpose", PURPOSE_MAX, errors)
    tiredness = _tiredness(raw.tiredness, errors)
    date = _date(raw.date, errors)
    experimenter = _optional_text(
        raw.experimenter, "experimenter", "Experimenter", EXPERIMENTER_MAX, errors
    )
    notes = _optional_text(raw.notes, "notes", "Notes", NOTES_MAX, errors)

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


def _required_text(
    value: str, name: str, label: str, max_len: int, errors: list[FieldError]
) -> str:
    text = value.strip()
    if not text:
        errors.append(FieldError(name, f"{label} is required."))
    elif len(text) > max_len:
        errors.append(
            FieldError(
                name,
                f"{label} is too long: {len(text)} characters, the limit is {max_len}.",
            )
        )
    return text


def _optional_text(
    value: str, name: str, label: str, max_len: int, errors: list[FieldError]
) -> str:
    text = value.strip()
    if len(text) > max_len:
        errors.append(
            FieldError(
                name,
                f"{label} is too long: {len(text)} characters, the limit is {max_len}.",
            )
        )
    return text


def _pilot(value: str, errors: list[FieldError]) -> str:
    text = value.strip()
    if not text:
        errors.append(FieldError("pilot", "Pilot is required, e.g. 'p01'."))
    elif len(text) > PILOT_MAX:
        errors.append(
            FieldError(
                "pilot",
                f"Pilot is too long: {len(text)} characters, the limit is {PILOT_MAX}.",
            )
        )
    elif not _PILOT_PATTERN.fullmatch(text):
        errors.append(
            FieldError(
                "pilot",
                f"Pilot may only contain letters, digits, '-' and '_' (got {text!r}). "
                "It is used in folder names.",
            )
        )
    return text


def _tiredness(value: str, errors: list[FieldError]) -> int | None:
    text = value.strip()
    if not text:
        errors.append(
            FieldError(
                "tiredness",
                f"Tiredness is required ({TIREDNESS_MIN} to {TIREDNESS_MAX}).",
            )
        )
        return None
    try:
        number = int(text)
    except ValueError:
        errors.append(
            FieldError(
                "tiredness",
                f"Tiredness must be a whole number from {TIREDNESS_MIN} to {TIREDNESS_MAX} (got {text!r}).",
            )
        )
        return None
    if not TIREDNESS_MIN <= number <= TIREDNESS_MAX:
        errors.append(
            FieldError(
                "tiredness",
                f"Tiredness must be from {TIREDNESS_MIN} to {TIREDNESS_MAX} (got {number}).",
            )
        )
        return None
    return number


def _date(value: str, errors: list[FieldError]) -> dt.date | None:
    text = value.strip()
    if not text:
        errors.append(
            FieldError("date", "Date is required, format YYYY-MM-DD (e.g. 2026-11-14).")
        )
        return None
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        errors.append(
            FieldError(
                "date",
                f"Date must be a real date in the format YYYY-MM-DD (got {text!r}).",
            )
        )
        return None
