"""Exact SQL subject identity and detached private snapshots; no real sources."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from models.db import Base
from services import scientific_result_subject as subject
from tests.test_research_freeze import add, seed, state
from tests.test_research_freeze import db_session as _serializable_db_session
from tests.test_scientific_result_dossier import prepared

db_session = _serializable_db_session


async def test_actual_sql_text_is_identity_not_python_reserialization(db_session):
    _, ids = await prepared(db_session)
    before = await state(db_session)
    first = await subject.capture_result_subject(db_session, ids["property"])
    actual = await db_session.scalar(
        sa.text("SELECT public.sclib_scientific_subject_capture_v1(:id)"),
        {"id": UUID(ids["property"])},
    )
    assert first.text == actual
    assert first.sha256 == hashlib.sha256(actual.encode("utf-8")).hexdigest()
    property_text = await db_session.scalar(
        sa.text("""SELECT public.sclib_scientific_adjudication_canonical_v1(item->'snapshot')
        FROM jsonb_array_elements(CAST(:body AS jsonb)->'rows') item
        WHERE item->>'table'='event_properties' AND item->>'row_id'=:id"""),
        {"body": actual, "id": ids["property"]},
    )
    assert first.property_row_sha256 == hashlib.sha256(property_text.encode()).hexdigest()
    assert first == await subject.capture_result_subject(db_session, UUID(ids["property"]))
    assert await state(db_session) == before
    data = first.data
    assert data["target"]["property_id"] == ids["property"]
    data["rows"].clear()
    assert first.data["rows"]


async def test_sibling_property_does_not_change_subject_basis(db_session):
    _, ids = await prepared(db_session)
    first = await subject.capture_result_subject(db_session, ids["property"])
    await add(
        db_session,
        "event_properties",
        id=uuid4(),
        event_id=UUID(ids["event"]),
        property_key="phonon_min_frequency",
        registry_version="rv2/1",
        component_key="independent-sibling",
        relation="exact",
        value=999,
        unit="THz",
        uncertainty={},
        raw={},
        record_sha256="a" * 64,
    )
    assert first == await subject.capture_result_subject(db_session, ids["property"])


async def test_new_reverse_ml_consumer_does_not_change_subject_basis(db_session):
    _, ids = await prepared(db_session)
    first = await subject.capture_result_subject(db_session, ids["property"])
    other = await seed(db_session)
    await add(
        db_session,
        "ml_example_inputs",
        example_id=other["example"],
        input_kind="property",
        input_event_id=UUID(ids["event"]),
        input_property_id=UUID(ids["property"]),
        feature_key="exact-new-consumer",
        matching_policy_version="synthetic/1",
        record_sha256="b" * 64,
    )
    assert first == await subject.capture_result_subject(db_session, ids["property"])


@pytest.mark.parametrize(
    "mutation",
    [
        "extra_top",
        "boolean_revision",
        "duplicate_row",
        "invalid_artifact",
        "native_binding",
        "finite_exponent_overflow",
    ],
)
async def test_closed_private_subject_rejects_malformed_snapshots(db_session, mutation):
    _, ids = await prepared(db_session)
    captured = await subject.capture_result_subject(db_session, ids["property"])
    data = captured.data
    if mutation == "extra_top":
        data["scientific_acceptance"] = True
    if mutation == "boolean_revision":
        data["target"]["event_revision"] = True
    if mutation == "duplicate_row":
        data["rows"].append(data["rows"][0])
    if mutation == "invalid_artifact":
        data["artifacts"][0]["bytes_sha256"] = True
    if mutation == "native_binding":
        data["native_import"]["outcome_id"] = str(uuid4())
    if mutation == "finite_exponent_overflow":
        data["rows"][0]["snapshot"]["overflow"] = "EXPONENT_SENTINEL"
    payload = json.dumps(data).replace('"EXPONENT_SENTINEL"', "1e999")
    with pytest.raises(subject.ScientificSubjectError):
        subject._json(payload)


@pytest.mark.parametrize(
    "table,key,field,value",
    [
        ("event_properties", "property", "raw", {"private_source": "SCIENTIFIC_SUBJECT_SENTINEL"}),
        ("material_states", "state", "conditions", {"phase": "new-phase"}),
        ("research_runs", "run", "settings", {"changed": "exact-scientific-protocol"}),
    ],
)
async def test_exact_forward_scientific_input_mutation_changes_basis(
    db_session, table, key, field, value
):
    _, ids = await prepared(db_session)
    first = await subject.capture_result_subject(db_session, ids["property"])
    relation = Base.metadata.tables[table]
    await db_session.execute(
        relation.update().where(relation.c.id == UUID(ids[key])).values(**{field: value})
    )
    second = await subject.capture_result_subject(db_session, ids["property"])
    assert second.sha256 != first.sha256 and second.subject_id != first.subject_id


async def test_capture_requires_bounded_stable_session(db_session):
    _, ids = await prepared(db_session)
    await db_session.execute(sa.text("SET LOCAL statement_timeout=0"))
    with pytest.raises(subject.ScientificSubjectError, match="bounded_statement_timeout"):
        await subject.capture_result_subject(db_session, ids["property"])
    assert await db_session.scalar(sa.text("SHOW statement_timeout")) == "0"


@pytest.mark.parametrize(
    "identifier",
    [True, 1, None, {}, "private-invalid-source", "00000000-0000-0000-0000-00000000000A"],
)
async def test_bad_identity_fails_without_sql_or_source_echo(identifier):
    with pytest.raises(subject.ScientificSubjectError) as exc:
        await subject.capture_result_subject(None, identifier)
    assert "private-invalid-source" not in str(exc.value)


@pytest.mark.parametrize("payload", ['{"a":1,"a":2}', '{"a":NaN}', "null", "[]", "\ud800"])
def test_subject_json_rejects_ambiguous_or_nonobject_data(payload):
    with pytest.raises(subject.ScientificSubjectError):
        subject._json(payload)


def test_private_snapshot_detects_text_substitution():
    text = json.dumps({"version": subject.VERSION, "target": {}, "rows": [{}], "artifacts": []})
    value = subject.ResultSubject(text, "0" * 64, uuid4(), "1" * 64)
    with pytest.raises(subject.ScientificSubjectError, match="private_snapshot_changed"):
        _ = value.data
