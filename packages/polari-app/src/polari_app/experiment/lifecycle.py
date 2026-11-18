"""Create and change experiments.

These functions are pure: they take the current time as an argument and
return new objects instead of changing old ones. That keeps them easy to
test and keeps the storage layer (WebDAV) in charge of I/O.
"""

import datetime as dt
from dataclasses import replace
from uuid import UUID, uuid4

from polari_app.experiment.models import (
    Comment,
    Experiment,
    ExperimentDetails,
    Recording,
)


def new_experiment(
    details: ExperimentDetails, now: dt.datetime, experiment_id: UUID | None = None
) -> Experiment:
    """A brand-new experiment. It is local only and starts at revision 0."""
    return Experiment(
        id=experiment_id or uuid4(),
        details=details,
        revision=0,
        created_at=now,
        updated_at=now,
        local_only=True,
    )


def revise(
    experiment: Experiment, details: ExperimentDetails, now: dt.datetime
) -> Experiment:
    """Edit the form fields of an experiment. Bumps the revision."""
    return replace(
        experiment, details=details, revision=experiment.revision + 1, updated_at=now
    )


def add_comment(experiment: Experiment, comment: Comment) -> Experiment:
    """Add a comment. Bumps the revision."""
    return replace(
        experiment,
        comments=(*experiment.comments, comment),
        revision=experiment.revision + 1,
        updated_at=comment.created_at,
    )


def add_recording(
    experiment: Experiment, recording: Recording, now: dt.datetime
) -> Experiment:
    """Attach a recording. Bumps the revision."""
    return replace(
        experiment,
        recordings=(*experiment.recordings, recording),
        revision=experiment.revision + 1,
        updated_at=now,
    )


def mark_uploaded(experiment: Experiment) -> Experiment:
    """Mark an experiment as stored online. Does not bump the revision."""
    return replace(experiment, local_only=False)
