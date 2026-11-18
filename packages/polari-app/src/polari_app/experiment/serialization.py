"""Turn experiments into JSON and back.

The JSON is what the storage layer (WebDAV) uploads. Loading checks a file
as carefully as the form: a broken or hand-edited file gives a list of
``FieldError`` instead of a crash. Nested fields are named like
``details.tiredness`` or ``recordings[0].sample_rate_hz``.

Loading works in two steps: first check every field and collect the
problems, then, only if there are none, build the objects.
"""

import datetime as dt
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

from polari_app.experiment.models import (
    SCHEMA_VERSION,
    Comment,
    Experiment,
    ExperimentDetails,
    FieldError,
    Recording,
)
from polari_app.experiment.validation import DATE_FORMAT, parse_form, validate

# --- Saving ------------------------------------------------------------------


def experiment_to_json(experiment: Experiment) -> str:
    """Stable, human-readable JSON (sorted keys, so diffs stay small)."""
    data = experiment_to_dict(experiment)
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)


def experiment_to_dict(experiment: Experiment) -> dict[str, Any]:
    """A JSON-ready dict of the experiment."""
    details = experiment.details
    return {
        "schema_version": SCHEMA_VERSION,
        "id": str(experiment.id),
        "revision": experiment.revision,
        "created_at": experiment.created_at.isoformat(),
        "updated_at": experiment.updated_at.isoformat(),
        "local_only": experiment.local_only,
        "details": {
            "title": details.title,
            "pilot": details.pilot,
            "purpose": details.purpose,
            "tiredness": details.tiredness,
            "date": details.date.strftime(DATE_FORMAT),
            "experimenter": details.experimenter,
            "notes": details.notes,
        },
        "recordings": [_recording_to_dict(r) for r in experiment.recordings],
        "comments": [_comment_to_dict(c) for c in experiment.comments],
    }


def _recording_to_dict(recording: Recording) -> dict[str, Any]:
    return {
        "id": str(recording.id),
        "file_name": recording.file_name,
        "started_at": recording.started_at.isoformat(),
        "duration_s": recording.duration_s,
        "sample_rate_hz": recording.sample_rate_hz,
        "channel_count": recording.channel_count,
        "marker_stream": recording.marker_stream,
    }


def _comment_to_dict(comment: Comment) -> dict[str, Any]:
    return {
        "author": comment.author,
        "created_at": comment.created_at.isoformat(),
        "text": comment.text,
    }


# --- Loading -----------------------------------------------------------------


def experiment_from_json(text: str) -> Experiment | list[FieldError]:
    """Load an experiment from JSON. Returns errors instead of raising."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        message = f"Not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})."
        return [FieldError("file", message)]
    return experiment_from_dict(data)


def experiment_from_dict(data: object) -> Experiment | list[FieldError]:
    """Load an experiment from an already parsed JSON object."""
    if not isinstance(data, dict):
        return [FieldError("file", "The top level must be a JSON object.")]

    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        message = f"Unsupported schema version {version!r}, expected {SCHEMA_VERSION}."
        return [FieldError("schema_version", message)]

    # Step 1: check everything.
    errors: list[FieldError] = []
    _check_fields(data, EXPERIMENT_CHECKS, "", errors)
    details = _load_details(data.get("details"), errors)
    _check_list(data, "recordings", RECORDING_CHECKS, errors)
    _check_list(data, "comments", COMMENT_CHECKS, errors)
    if errors or details is None:
        return errors

    # Step 2: every value is known to be fine, so build the objects.
    return Experiment(
        id=UUID(data["id"]),
        details=details,
        revision=data["revision"],
        created_at=dt.datetime.fromisoformat(data["created_at"]),
        updated_at=dt.datetime.fromisoformat(data["updated_at"]),
        local_only=data["local_only"],
        recordings=tuple(_build_recording(r) for r in data.get("recordings", [])),
        comments=tuple(_build_comment(c) for c in data.get("comments", [])),
    )


def _load_details(data: object, errors: list[FieldError]) -> ExperimentDetails | None:
    if not isinstance(data, dict):
        errors.append(FieldError("details", "Missing or not an object."))
        return None
    # Stored files follow the same rules as the form.
    as_text = {key: "" if value is None else str(value) for key, value in data.items()}
    result = validate(parse_form(as_text))
    if isinstance(result, list):
        errors.extend(FieldError(f"details.{e.field}", e.message) for e in result)
        return None
    return result


def _build_recording(data: dict[str, Any]) -> Recording:
    return Recording(
        id=UUID(data["id"]),
        file_name=data["file_name"],
        started_at=dt.datetime.fromisoformat(data["started_at"]),
        duration_s=float(data["duration_s"]),
        sample_rate_hz=float(data["sample_rate_hz"]),
        channel_count=data["channel_count"],
        marker_stream=data.get("marker_stream") or "",
    )


def _build_comment(data: dict[str, Any]) -> Comment:
    return Comment(
        author=data["author"],
        created_at=dt.datetime.fromisoformat(data["created_at"]),
        text=data["text"],
    )


# --- Field checks ------------------------------------------------------------
# Each check takes a value from the file and returns an error message,
# or None if the value is fine.

Check = Callable[[object], str | None]
EXAMPLE_TIME = "'2026-11-14T10:00:00+01:00'"


def _check_uuid(value: object) -> str | None:
    if isinstance(value, str):
        try:
            UUID(value)
            return None
        except ValueError:
            pass
    return f"Must be a UUID (got {value!r})."


def _check_timestamp(value: object) -> str | None:
    if not isinstance(value, str):
        return f"Must be an ISO date and time like {EXAMPLE_TIME} (got {value!r})."
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return f"Must be an ISO date and time like {EXAMPLE_TIME} (got {value!r})."
    if parsed.tzinfo is None:
        return f"Must include a time zone like {EXAMPLE_TIME} (got {value!r})."
    return None


def _check_whole_number(value: object, minimum: int) -> str | None:
    # bool is a subclass of int in Python, so True would pass as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        return f"Must be a whole number (got {value!r})."
    if value < minimum:
        return f"Must be at least {minimum} (got {value})."
    return None


def _check_revision(value: object) -> str | None:
    return _check_whole_number(value, minimum=0)


def _check_channel_count(value: object) -> str | None:
    return _check_whole_number(value, minimum=1)


def _check_positive_number(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        return f"Must be a number of at least 0 (got {value!r})."
    return None


def _check_bool(value: object) -> str | None:
    if not isinstance(value, bool):
        return f"Must be true or false (got {value!r})."
    return None


def _check_required_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return "Must be a non-empty string."
    return None


def _check_optional_text(value: object) -> str | None:
    if value is not None and not isinstance(value, str):
        return "Must be a string."
    return None


EXPERIMENT_CHECKS: dict[str, Check] = {
    "id": _check_uuid,
    "revision": _check_revision,
    "created_at": _check_timestamp,
    "updated_at": _check_timestamp,
    "local_only": _check_bool,
}

RECORDING_CHECKS: dict[str, Check] = {
    "id": _check_uuid,
    "file_name": _check_required_text,
    "started_at": _check_timestamp,
    "duration_s": _check_positive_number,
    "sample_rate_hz": _check_positive_number,
    "channel_count": _check_channel_count,
    "marker_stream": _check_optional_text,
}

COMMENT_CHECKS: dict[str, Check] = {
    "author": _check_required_text,
    "created_at": _check_timestamp,
    "text": _check_required_text,
}


def _check_fields(
    data: dict[str, Any], checks: dict[str, Check], path: str, errors: list[FieldError]
) -> None:
    for key, check in checks.items():
        problem = check(data.get(key))
        if problem:
            errors.append(FieldError(f"{path}.{key}" if path else key, problem))


def _check_list(
    data: dict[str, Any], key: str, checks: dict[str, Check], errors: list[FieldError]
) -> None:
    items = data.get(key, [])
    if not isinstance(items, list):
        errors.append(FieldError(key, "Must be a list."))
        return
    for i, item in enumerate(items):
        path = f"{key}[{i}]"
        if isinstance(item, dict):
            _check_fields(item, checks, path, errors)
        else:
            errors.append(FieldError(path, "Must be an object."))
