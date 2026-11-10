"""Turn experiments into JSON and back.

The JSON is what the storage layer (WebDAV) uploads. Loading checks the
file just as carefully as the form: a broken or hand-edited file gives a
list of ``FieldError`` instead of a crash. Nested fields use dotted names,
e.g. ``details.tiredness`` or ``recordings[0].sample_rate_hz``.
"""

import datetime as dt
import json
from typing import Any
from uuid import UUID

from polari_app.experiment.models import (
    DATE_FORMAT,
    SCHEMA_VERSION,
    Comment,
    Experiment,
    ExperimentDetails,
    FieldError,
    RawExperiment,
    Recording,
)
from polari_app.experiment.validation import validate


def experiment_to_dict(experiment: Experiment) -> dict[str, Any]:
    """A JSON-ready dict of the experiment."""
    d = experiment.details
    return {
        "schema_version": SCHEMA_VERSION,
        "id": str(experiment.id),
        "revision": experiment.revision,
        "created_at": experiment.created_at.isoformat(),
        "updated_at": experiment.updated_at.isoformat(),
        "local_only": experiment.local_only,
        "details": {
            "title": d.title,
            "pilot": d.pilot,
            "purpose": d.purpose,
            "tiredness": d.tiredness,
            "date": d.date.strftime(DATE_FORMAT),
            "experimenter": d.experimenter,
            "notes": d.notes,
        },
        "recordings": [
            {
                "id": str(r.id),
                "file_name": r.file_name,
                "started_at": r.started_at.isoformat(),
                "duration_s": r.duration_s,
                "sample_rate_hz": r.sample_rate_hz,
                "channel_count": r.channel_count,
                "marker_stream": r.marker_stream,
            }
            for r in experiment.recordings
        ],
        "comments": [
            {"author": c.author, "created_at": c.created_at.isoformat(), "text": c.text}
            for c in experiment.comments
        ],
    }


def experiment_to_json(experiment: Experiment) -> str:
    """Stable, human-readable JSON (sorted keys, so diffs stay small)."""
    return json.dumps(
        experiment_to_dict(experiment), indent=2, sort_keys=True, ensure_ascii=False
    )


def experiment_from_json(text: str) -> Experiment | list[FieldError]:
    """Load an experiment from JSON. Returns errors instead of raising."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [
            FieldError(
                "file",
                f"Not valid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}.",
            )
        ]
    return experiment_from_dict(data)


def experiment_from_dict(data: object) -> Experiment | list[FieldError]:
    """Load an experiment from an already parsed JSON object."""
    if not isinstance(data, dict):
        return [FieldError("file", "The top level must be a JSON object.")]

    reader = _Reader()
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        return [
            FieldError(
                "schema_version",
                f"Unsupported schema version {version!r}; this version of polari reads {SCHEMA_VERSION}.",
            )
        ]

    experiment_id = reader.read_uuid(data, "id", "id")
    revision = reader.read_int(data, "revision", "revision", minimum=0)
    created_at = reader.read_datetime(data, "created_at", "created_at")
    updated_at = reader.read_datetime(data, "updated_at", "updated_at")
    local_only = reader.read_bool(data, "local_only", "local_only")
    details = _details(data.get("details"), reader)
    recordings = [
        _recording(item, f"recordings[{i}]", reader)
        for i, item in enumerate(reader.read_list(data, "recordings"))
    ]
    comments = [
        _comment(item, f"comments[{i}]", reader)
        for i, item in enumerate(reader.read_list(data, "comments"))
    ]

    if (
        reader.errors
        or experiment_id is None
        or revision is None
        or created_at is None
        or updated_at is None
        or local_only is None
        or details is None
    ):
        return reader.errors

    return Experiment(
        id=experiment_id,
        details=details,
        revision=revision,
        created_at=created_at,
        updated_at=updated_at,
        local_only=local_only,
        recordings=tuple(r for r in recordings if r is not None),
        comments=tuple(c for c in comments if c is not None),
    )


def _details(data: object, reader: "_Reader") -> ExperimentDetails | None:
    if not isinstance(data, dict):
        reader.errors.append(FieldError("details", "Missing or not an object."))
        return None
    # Reuse the form validation so stored files follow the same rules.
    raw = RawExperiment(
        **{key: _as_text(data.get(key)) for key in RawExperiment.__dataclass_fields__}
    )
    result = validate(raw)
    if isinstance(result, list):
        reader.errors.extend(
            FieldError(f"details.{e.field}", e.message) for e in result
        )
        return None
    return result


def _recording(data: object, path: str, reader: "_Reader") -> Recording | None:
    if not isinstance(data, dict):
        reader.errors.append(FieldError(path, "Must be an object."))
        return None
    recording_id = reader.read_uuid(data, "id", f"{path}.id")
    file_name = reader.read_str(data, "file_name", f"{path}.file_name", required=True)
    started_at = reader.read_datetime(data, "started_at", f"{path}.started_at")
    duration_s = reader.read_float(data, "duration_s", f"{path}.duration_s")
    sample_rate_hz = reader.read_float(data, "sample_rate_hz", f"{path}.sample_rate_hz")
    channel_count = reader.read_int(
        data, "channel_count", f"{path}.channel_count", minimum=1
    )
    marker_stream = reader.read_str(
        data, "marker_stream", f"{path}.marker_stream", required=False
    )
    if (
        recording_id is None
        or file_name is None
        or started_at is None
        or duration_s is None
        or sample_rate_hz is None
        or channel_count is None
        or marker_stream is None
    ):
        return None
    return Recording(
        recording_id,
        file_name,
        started_at,
        duration_s,
        sample_rate_hz,
        channel_count,
        marker_stream,
    )


def _comment(data: object, path: str, reader: "_Reader") -> Comment | None:
    if not isinstance(data, dict):
        reader.errors.append(FieldError(path, "Must be an object."))
        return None
    author = reader.read_str(data, "author", f"{path}.author", required=True)
    created_at = reader.read_datetime(data, "created_at", f"{path}.created_at")
    text = reader.read_str(data, "text", f"{path}.text", required=True)
    if author is None or created_at is None or text is None:
        return None
    return Comment(author, created_at, text)


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):  # bool is an int subclass; never accept it as a number
        return repr(value)
    return str(value)


class _Reader:
    """Reads typed values from a dict and collects errors along the way."""

    def __init__(self) -> None:
        self.errors: list[FieldError] = []

    def _fail(self, path: str, message: str) -> None:
        self.errors.append(FieldError(path, message))

    def read_str(
        self, data: dict[str, Any], key: str, path: str, *, required: bool
    ) -> str | None:
        value = data.get(key, None if required else "")
        if not isinstance(value, str) or (required and not value.strip()):
            self._fail(
                path, "Must be a non-empty string." if required else "Must be a string."
            )
            return None
        return value

    def read_int(
        self, data: dict[str, Any], key: str, path: str, *, minimum: int
    ) -> int | None:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            self._fail(path, f"Must be a whole number (got {value!r}).")
            return None
        if value < minimum:
            self._fail(path, f"Must be at least {minimum} (got {value}).")
            return None
        return value

    def read_float(self, data: dict[str, Any], key: str, path: str) -> float | None:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            self._fail(path, f"Must be a number of at least 0 (got {value!r}).")
            return None
        return float(value)

    def read_bool(self, data: dict[str, Any], key: str, path: str) -> bool | None:
        value = data.get(key)
        if not isinstance(value, bool):
            self._fail(path, f"Must be true or false (got {value!r}).")
            return None
        return value

    def read_uuid(self, data: dict[str, Any], key: str, path: str) -> UUID | None:
        value = data.get(key)
        try:
            return (
                UUID(str(value))
                if isinstance(value, str)
                else self._bad_uuid(path, value)
            )
        except ValueError:
            return self._bad_uuid(path, value)

    def _bad_uuid(self, path: str, value: object) -> None:
        self._fail(
            path,
            f"Must be a UUID like '123e4567-e89b-12d3-a456-426614174000' (got {value!r}).",
        )

    def read_datetime(
        self, data: dict[str, Any], key: str, path: str
    ) -> dt.datetime | None:
        value = data.get(key)
        if isinstance(value, str):
            try:
                parsed = dt.datetime.fromisoformat(value)
            except ValueError:
                pass
            else:
                if parsed.tzinfo is not None:
                    return parsed
                self._fail(
                    path,
                    f"Must include a time zone, e.g. '2026-11-14T10:00:00+01:00' (got {value!r}).",
                )
                return None
        self._fail(
            path,
            f"Must be an ISO date and time, e.g. '2026-11-14T10:00:00+01:00' (got {value!r}).",
        )
        return None

    def read_list(self, data: dict[str, Any], key: str) -> list[object]:
        value = data.get(key, [])
        if not isinstance(value, list):
            self._fail(key, "Must be a list.")
            return []
        return value
