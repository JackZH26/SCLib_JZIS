"""Complete review-document projection for authenticated preregistration checks.

This is not a signature, canary replay, source permission or scientific verdict.
All review revisions contribute to the projection, including failed events.
"""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

from services import ml_pilot_accounting as accounting
from services import ml_pilot_documents as documents
from services import ml_pilot_registration_documents as registration

VERSION = "ml08-review-documents/1.0.0"
MAX_ENVELOPE_BYTES = 4 * ((documents.MAX_BYTES + 2) // 3 * 4) + 65536
MAX_PROJECTION_BYTES = 256 * 1024
require = registration.require
sha = registration.sha


def implementation():
    names = (
        "ml_pilot_accounting.py",
        "ml_pilot_documents.py",
        "ml08_pilot.schema.json",
        "ml_pilot_registration_documents.py",
        "ml_pilot_review_documents.py",
        "ml_pilot_review_worker.py",
        "ml_use_reconstruction_worker.py",
    )
    return {
        "version": VERSION,
        "scope": "selected_installed_sources_not_runtime_attestation",
        "files": {name: sha(Path(__file__).with_name(name).read_bytes()) for name in names},
    }


def instant(value):
    return accounting._date(value).astimezone(UTC).isoformat(timespec="microseconds")


def project(**args):
    """Inspect all four original files, returning only opaque attribution metadata."""
    require(
        args.get("conclusion_raw") is not None and args.get("conclusion_file_sha256") is not None
    )
    inspected = documents.inspect_documents(**args)
    report = inspected["accounting"]
    require(
        not report["errors"]
        and report["ready_for_final_human_signoff"]
        and report["counts"]["selected_candidates"] == 60
        and report["counts"]["unreviewed_candidates"] == 0
    )
    selection = documents.json_value(args["selection_raw"])
    reviews = documents.review_records(args["reviews_raw"])
    conclusion = documents.json_value(args["conclusion_raw"])
    contributions = []
    for reviewer in selection["reviewers"]:
        rows = [row for row in reviews if row["reviewer_id"] == reviewer["id"]]
        contributions.append(
            {
                "alias_sha256": sha(reviewer["id"].encode("utf-8")),
                "roles": [role for role in registration.ROLES if role in reviewer["roles"]],
                "review_record_count": len(rows),
                "review_records_sha256": accounting.review_hash(rows),
                "declared_completion_instants": sorted(
                    {instant(row["completed_at"]) for row in rows}
                ),
            }
        )
    result = {
        "version": VERSION,
        "input_pins": inspected["input_pins"],
        "selection_sha256": inspected["selection_sha256"],
        "review_log_sha256": inspected["review_log_sha256"],
        "selected_candidates": 60,
        "review_record_count": len(reviews),
        "selection_chronology": registration.chronology(selection),
        "conclusion_author_alias_sha256": sha(conclusion["reviewer_id"].encode("utf-8")),
        "conclusion_completed_at": instant(conclusion["completed_at"]),
        "recommendation": conclusion["recommendation"],
        "declared_canary_sha256": conclusion["canary_bundle_sha256"],
        "reviewer_contributions": sorted(contributions, key=lambda row: row["alias_sha256"]),
    }
    require(len(documents.canonical(result)) <= MAX_PROJECTION_BYTES)
    return result


def checked(value):
    """Validate trusted child output again; never accept it directly from HTTP."""
    value = documents.json_value(documents.canonical(value))
    require(
        type(value) is dict
        and set(value)
        == {
            "version",
            "input_pins",
            "selection_sha256",
            "review_log_sha256",
            "selected_candidates",
            "review_record_count",
            "selection_chronology",
            "conclusion_author_alias_sha256",
            "conclusion_completed_at",
            "recommendation",
            "declared_canary_sha256",
            "reviewer_contributions",
        }
        and value["version"] == VERSION
        and type(value["selected_candidates"]) is int
        and value["selected_candidates"] == 60
    )
    pins = value["input_pins"]
    require(
        type(pins) is dict
        and set(pins)
        == {name + "_file_sha256" for name in ("selection", "reviews", "protocol", "conclusion")}
    )
    require(
        all(
            type(pin) is str and documents.HASH.fullmatch(pin)
            for pin in [
                *pins.values(),
                value["selection_sha256"],
                value["review_log_sha256"],
                value["conclusion_author_alias_sha256"],
                value["declared_canary_sha256"],
            ]
        )
    )
    registration.check_chronology(value["selection_chronology"])
    require(
        type(value["review_record_count"]) is int
        and 61 <= value["review_record_count"] <= accounting.MAX_REVIEWS
        and value["recommendation"] in {"go", "narrow", "stop"}
        and type(value["conclusion_completed_at"]) is str
        and instant(value["conclusion_completed_at"]) == value["conclusion_completed_at"]
    )
    rows = value["reviewer_contributions"]
    require(type(rows) is list and 2 <= len(rows) <= 30)
    for row in rows:
        require(
            type(row) is dict
            and set(row)
            == {
                "alias_sha256",
                "roles",
                "review_record_count",
                "review_records_sha256",
                "declared_completion_instants",
            }
        )
        require(
            all(
                type(row[key]) is str and documents.HASH.fullmatch(row[key])
                for key in ("alias_sha256", "review_records_sha256")
            )
        )
        require(
            type(row["roles"]) is list
            and row["roles"]
            and row["roles"] == [r for r in registration.ROLES if r in row["roles"]]
        )
        count, times = row["review_record_count"], row["declared_completion_instants"]
        require(
            type(count) is int
            and 0 <= count <= accounting.MAX_REVIEWS
            and type(times) is list
            and len(times) <= count
            and bool(times) == bool(count)
            and all(type(t) is str and instant(t) == t for t in times)
            and times == sorted(set(times))
        )
        require(
            all(
                value["selection_chronology"]["frozen_at"] <= t <= value["conclusion_completed_at"]
                for t in times
            )
        )
        if count == 0:
            require(row["review_records_sha256"] == accounting.review_hash([]))
    require(
        len({r["alias_sha256"] for r in rows}) == len(rows)
        and rows == sorted(rows, key=lambda row: row["alias_sha256"])
        and sum(r["review_record_count"] for r in rows) == value["review_record_count"]
        and value["conclusion_author_alias_sha256"] in {r["alias_sha256"] for r in rows}
        and len(documents.canonical(value)) <= MAX_PROJECTION_BYTES
    )
    return value
