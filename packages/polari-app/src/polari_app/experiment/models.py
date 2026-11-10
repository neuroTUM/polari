"""Data models for an experiment.

The flow follows the whiteboard from the 2026-11-07 software meeting::

    str -> RawExperiment -> validate -> ExperimentDetails | list[FieldError]

* ``RawExperiment`` holds exactly what the "New Experiment" form gives us:
  plain strings, nothing checked yet.
* ``ExperimentDetails`` is the checked, typed version of the form.
* ``Experiment`` is a stored experiment: the details plus the bookkeeping
  fields (id, revision, timestamps, recordings, comments).

All models are immutable. To change something, build a new object
(see ``revise`` in ``polari_app.experiment.lifecycle``).
"""

import datetime as dt
from dataclasses import dataclass, field
from uuid import UUID

SCHEMA_VERSION = 1
"""Version of the stored JSON layout. Bump it when the layout changes."""

DATE_FORMAT = "%d-%m-%Y"
"""How the experiment date is typed and stored: day-month-year, e.g. 14-11-2026."""

TIREDNESS_MIN = 0
TIREDNESS_MAX = 10


@dataclass(frozen=True, slots=True)
class FieldError:
    """One problem with one field, phrased so the user knows how to fix it."""

    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


@dataclass(frozen=True, slots=True)
class RawExperiment:
    """Unchecked form input. Every value is the text the user typed."""

    title: str = ""
    pilot: str = ""
    purpose: str = ""
    tiredness: str = ""
    experimenter: str = ""
    date: str = ""
    notes: str = ""


@dataclass(frozen=True, slots=True)
class ExperimentDetails:
    """Checked form input: the fields a user can edit."""

    title: str
    pilot: str
    purpose: str
    tiredness: int
    date: dt.date
    experimenter: str = ""
    notes: str = ""


@dataclass(frozen=True, slots=True)
class Comment:
    """A comment in the experiment's comments section."""

    author: str
    created_at: dt.datetime
    text: str


@dataclass(frozen=True, slots=True)
class Recording:
    """One recording that belongs to an experiment (an experiment has n)."""

    id: UUID
    file_name: str
    started_at: dt.datetime
    duration_s: float
    sample_rate_hz: float
    channel_count: int
    marker_stream: str = ""


@dataclass(frozen=True, slots=True)
class Experiment:
    """A stored experiment.

    ``local_only`` is True for new experiments that exist only on this
    computer. Once uploaded (WebDAV), it becomes False. ``revision`` counts
    edits and lets the storage layer detect editing conflicts.
    """

    id: UUID
    details: ExperimentDetails
    revision: int
    created_at: dt.datetime
    updated_at: dt.datetime
    local_only: bool = True
    recordings: tuple[Recording, ...] = field(default_factory=tuple)
    comments: tuple[Comment, ...] = field(default_factory=tuple)
