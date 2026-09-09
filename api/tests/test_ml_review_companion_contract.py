"""Pure review artifact contract tests; SQL capture is exercised separately."""
from copy import deepcopy
from uuid import UUID

import pytest

from services.ml_feature_review_companion import (
    MAX_BYTES,
    MlReviewCompanionError,
    _audit,
    _available,
    _bounded,
    _status,
)
from services.ml_review_projection import (
    publication_role_record_sha256,
    raw_text_sha256,
    sql_canonical,
)


def uid(value):
    return str(UUID(int=value))


def wire(table, row):
    if table.startswith("research_role_"):
        row = {**row, "record_sha256": publication_role_record_sha256(sql_canonical(row))}
    text = sql_canonical(row)
    return {"table": table, "row_id": row["id"], "row_text": text, "row_sha256": raw_text_sha256(text)}


def roles(*, revoked=False):
    result = [wire("users", {"id": uid(1), "is_active": True, "email_verified": True, "is_admin": True}),
        wire("research_role_grants", {"id": uid(2), "user_id": uid(1), "granted_by": uid(1), "role": "curator",
             "reason_code": "private_audit", "created_at": "2026-09-08T00:00:00+00:00", "record_sha256": "0" * 64})]
    if revoked:
        result.append(wire("research_role_revocations", {"id": uid(3), "grant_id": uid(2), "revoked_by": uid(1),
            "reason_code": "private_audit", "created_at": "2026-09-08T00:00:01+00:00", "record_sha256": "0" * 64}))
    return sorted(result, key=lambda row: (row["table"], row["row_id"]))


@pytest.mark.parametrize("revoked", [False, True])
def test_role_current_status_is_replayed_not_serialized(revoked):
    index, subjects, decisions, successors, revocations = _audit(roles(revoked=revoked))
    assert not (subjects or decisions or successors)
    assert _available(index, revocations, uid(1), uid(2), "curator") is not revoked


@pytest.mark.parametrize("change", ["email", "token", "extra", "int_flag", "identity", "duplicate", "role_hash", "missing_user"])
def test_closed_private_audit_rejects_surplus_and_inconsistent_bytes(change):
    rows = roles()
    if change == "duplicate":
        rows.insert(0, deepcopy(rows[0]))
    elif change == "missing_user":
        rows = rows[:1]
    elif change == "role_hash":
        from services.ml_review_projection import parse_sql_json
        row = parse_sql_json(rows[0]["row_text"])
        row["reason_code"] = "tampered"
        rows[0]["row_text"] = sql_canonical(row)
        rows[0]["row_sha256"] = raw_text_sha256(rows[0]["row_text"])
    else:
        from services.ml_review_projection import parse_sql_json
        row = parse_sql_json(rows[-1]["row_text"])
        if change == "int_flag":
            row["is_admin"] = 1
        elif change == "identity":
            row["id"] = uid(4)
        else:
            row[change] = "never export this"
        rows[-1] = wire("users", row)
        if change == "identity":
            rows[-1]["row_id"] = uid(1)
    with pytest.raises(ValueError):
        _audit(rows)


@pytest.mark.parametrize(("decision", "available", "expected"), [
    ("reject", True, "rejected"), ("reject", False, "rejected"),
    ("request_clarification", False, "clarification_required"),
    ("accept", False, "reviewer_unavailable"), ("accept", True, "accepted"),
])
def test_negative_history_survives_role_loss(decision, available, expected):
    head = {"subject_sha256": "a" * 64, "decision": decision}
    result, _ = _status("extraction_fidelity", head, current_sha256="a" * 64,
                        source_held=False, available=available, extraction=None)
    assert result == expected


@pytest.mark.parametrize(("current", "held", "expected"), [
    ("b" * 64, True, "stale"), ("a" * 64, True, "source_held"),
])
def test_capture_status_does_not_override_staleness_or_sources(current, held, expected):
    head = {"subject_sha256": "a" * 64, "decision": "accept"}
    assert _status("extraction_fidelity", head, current_sha256=current, source_held=held,
                   available=True, extraction=None)[0] == expected


@pytest.mark.parametrize("extraction", [None, {"status": "rejected", "decision_id": uid(3)},
                                      {"status": "accepted", "decision_id": uid(4)}])
def test_science_acceptance_requires_exact_current_fidelity(extraction):
    head = {"subject_sha256": "a" * 64, "decision": "accept", "extraction_decision_id": uid(3)}
    assert _status("scientific_result", head, current_sha256="a" * 64, source_held=False,
                   available=True, extraction=extraction)[0] == "dependency_review_held"


def test_unreviewed_is_neither_a_positive_nor_a_serialized_source_gate():
    assert _status("scientific_result", None, current_sha256=None, source_held=True,
                   available=False, extraction=None) == ("unreviewed", [])


def test_shared_byte_budget_precedes_document_allocation():
    with pytest.raises(MlReviewCompanionError, match="byte_limit"):
        _bounded({"large_private_source": "x" * (MAX_BYTES + 1)})


@pytest.mark.parametrize("user_field", ["is_active", "email_verified"])
def test_inactive_or_unverified_curator_is_unavailable(user_field):
    from services.ml_review_projection import parse_sql_json
    rows = roles()
    user = parse_sql_json(rows[-1]["row_text"])
    user[user_field] = False
    rows[-1] = wire("users", user)
    index, _, _, _, revocations = _audit(rows)
    assert not _available(index, revocations, uid(1), uid(2), "curator")
