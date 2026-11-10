import datetime as dt
import json
from uuid import UUID

import pytest
from polari_app.experiment import (
    Comment,
    Experiment,
    ExperimentDetails,
    FieldError,
    RawExperiment,
    Recording,
    add_comment,
    add_recording,
    experiment_from_json,
    experiment_to_json,
    mark_uploaded,
    new_experiment,
    parse_form,
    revise,
    validate,
)

NOW = dt.datetime(2026, 11, 14, 10, 0, tzinfo=dt.UTC)
FIXED_ID = UUID("123e4567-e89b-12d3-a456-426614174000")

GOOD_FORM = {
    "title": "MI baseline",
    "pilot": "p01",
    "purpose": "Record a motor imagery baseline with the Explore device.",
    "tiredness": "3",
    "date": "2026-11-14",
    "experimenter": "Orhun",
    "notes": "",
}


def good_details() -> ExperimentDetails:
    result = validate(parse_form(GOOD_FORM))
    assert isinstance(result, ExperimentDetails)
    return result


def errors_for(**changes: str) -> list[FieldError]:
    result = validate(parse_form(GOOD_FORM | changes))
    assert isinstance(result, list)
    return result


def error_fields(errors: list[FieldError]) -> list[str]:
    return [e.field for e in errors]


# --- parse_form ---------------------------------------------------------------


def test_parse_form_fills_missing_and_ignores_unknown_keys() -> None:
    raw = parse_form({"title": "x", "widget_we_do_not_know": "y"})
    assert raw == RawExperiment(title="x")


# --- validate: good input -----------------------------------------------------


def test_valid_form_gives_typed_details() -> None:
    details = good_details()
    assert details.tiredness == 3
    assert details.date == dt.date(2026, 11, 14)
    assert details.pilot == "p01"


def test_whitespace_is_stripped() -> None:
    result = validate(
        parse_form(GOOD_FORM | {"title": "  MI baseline  ", "tiredness": " 7 "})
    )
    assert isinstance(result, ExperimentDetails)
    assert result.title == "MI baseline"
    assert result.tiredness == 7


@pytest.mark.parametrize("value", ["0", "10"])
def test_tiredness_edges_are_allowed(value: str) -> None:
    assert isinstance(
        validate(parse_form(GOOD_FORM | {"tiredness": value})), ExperimentDetails
    )


def test_optional_fields_may_be_empty() -> None:
    assert isinstance(
        validate(parse_form(GOOD_FORM | {"experimenter": "", "notes": ""})),
        ExperimentDetails,
    )


# --- validate: errors ---------------------------------------------------------


def test_empty_form_reports_every_required_field() -> None:
    result = validate(RawExperiment())
    assert isinstance(result, list)
    assert error_fields(result) == ["title", "pilot", "purpose", "tiredness", "date"]


@pytest.mark.parametrize(
    ("value", "expected_text"),
    [
        ("11", "from 0 to 10 (got 11)"),
        ("-1", "from 0 to 10 (got -1)"),
        ("abc", "whole number"),
        ("3.5", "whole number"),
        ("", "required"),
    ],
)
def test_bad_tiredness(value: str, expected_text: str) -> None:
    errors = errors_for(tiredness=value)
    assert error_fields(errors) == ["tiredness"]
    assert expected_text in errors[0].message


@pytest.mark.parametrize("value", ["14.11.2026", "2026-02-30", "tomorrow"])
def test_bad_date(value: str) -> None:
    errors = errors_for(date=value)
    assert error_fields(errors) == ["date"]
    assert "YYYY-MM-DD" in errors[0].message


@pytest.mark.parametrize("value", ["p 01", "p01/../x", "ö1"])
def test_pilot_must_be_folder_safe(value: str) -> None:
    errors = errors_for(pilot=value)
    assert error_fields(errors) == ["pilot"]
    assert "folder names" in errors[0].message


def test_too_long_title() -> None:
    errors = errors_for(title="x" * 121)
    assert error_fields(errors) == ["title"]
    assert "121 characters, the limit is 120" in errors[0].message


def test_errors_read_well_as_text() -> None:
    assert str(FieldError("tiredness", "Too high.")) == "tiredness: Too high."


# --- lifecycle ----------------------------------------------------------------


def test_new_experiment_is_local_at_revision_zero() -> None:
    experiment = new_experiment(good_details(), NOW, FIXED_ID)
    assert experiment.local_only
    assert experiment.revision == 0
    assert experiment.created_at == experiment.updated_at == NOW


def test_edits_bump_revision_and_keep_old_object() -> None:
    later = NOW + dt.timedelta(hours=1)
    first = new_experiment(good_details(), NOW, FIXED_ID)
    edited = revise(first, good_details(), later)
    commented = add_comment(edited, Comment("Emre", later, "Electrode T7 was loose."))
    assert (first.revision, edited.revision, commented.revision) == (0, 1, 2)
    assert commented.updated_at == later
    assert first.comments == ()


def test_mark_uploaded_keeps_revision() -> None:
    uploaded = mark_uploaded(new_experiment(good_details(), NOW, FIXED_ID))
    assert not uploaded.local_only
    assert uploaded.revision == 0


# --- JSON ---------------------------------------------------------------------


def full_experiment() -> Experiment:
    experiment = new_experiment(good_details(), NOW, FIXED_ID)
    experiment = add_recording(
        experiment,
        Recording(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            file_name="trial_1/data.xdf",
            started_at=NOW,
            duration_s=312.5,
            sample_rate_hz=250.0,
            channel_count=32,
            marker_stream="BasicArrowsMarkerStream",
        ),
        NOW,
    )
    return add_comment(experiment, Comment("Orhun", NOW, "Ünïcode is fine."))


def test_json_round_trip() -> None:
    experiment = full_experiment()
    assert experiment_from_json(experiment_to_json(experiment)) == experiment


def test_json_is_stable() -> None:
    assert experiment_to_json(full_experiment()) == experiment_to_json(
        full_experiment()
    )


def test_broken_json_gives_error_not_crash() -> None:
    result = experiment_from_json("{not json")
    assert isinstance(result, list)
    assert error_fields(result) == ["file"]


def test_unknown_schema_version_is_rejected() -> None:
    data = json.loads(experiment_to_json(full_experiment()))
    data["schema_version"] = 99
    result = experiment_from_json(json.dumps(data))
    assert isinstance(result, list)
    assert error_fields(result) == ["schema_version"]


def test_hand_edited_file_reports_nested_paths() -> None:
    data = json.loads(experiment_to_json(full_experiment()))
    data["details"]["tiredness"] = 42
    data["recordings"][0]["channel_count"] = 0
    data["revision"] = True
    data["comments"][0]["created_at"] = "2026-11-14T10:00:00"  # no time zone
    result = experiment_from_json(json.dumps(data))
    assert isinstance(result, list)
    assert sorted(error_fields(result)) == [
        "comments[0].created_at",
        "details.tiredness",
        "recordings[0].channel_count",
        "revision",
    ]
