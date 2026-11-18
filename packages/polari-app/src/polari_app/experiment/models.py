"""Data models for an experiment.

An experiment goes through three shapes:

* ``RawExperiment``: what the "New Experiment" form gives us, plain strings.
* ``ExperimentDetails``: the same form after ``validate`` checked it.
* ``Experiment``: a stored experiment, the details plus id, revision,
  timestamps, recordings and comments.

All models are frozen. To change one, build a new object (see ``lifecycle``).
"""

import datetime as dt
from dataclasses import dataclass
from uuid import UUID

SCHEMA_VERSION = 1
"""Version of the stored JSON layout. Bump it when the layout changes."""


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
    """One recording of an experiment. An experiment can have many."""

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

    ``local_only`` is True while the experiment exists only on this computer
    and becomes False once it is uploaded. ``revision`` counts the edits, so
    the storage layer can notice when two people edited the same experiment.
    """

    id: UUID
    details: ExperimentDetails
    revision: int
    created_at: dt.datetime
    updated_at: dt.datetime
    local_only: bool = True
    recordings: tuple[Recording, ...] = ()
    comments: tuple[Comment, ...] = ()
