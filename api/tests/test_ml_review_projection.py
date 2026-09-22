"""Lossless bridges and native SQL parity; every scientific fixture is synthetic."""
from __future__ import annotations

import hashlib
from copy import deepcopy
from decimal import Decimal

import pytest
import sqlalchemy as sa

from services import ml_review_projection as service
from services.research_release_manifest import digest
from tests.test_research_freeze import db_session as db_session


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}',
    '"\\ud800"', '"\\u0000"', '{', '[' * 50 + '0' + ']' * 50, '1e999999999', '"' + 'x' * service.MAX_BYTES + '"'],
    ids=["duplicate", "nan", "infinity", "negative-infinity", "surrogate", "nul", "syntax", "depth", "exponent", "bytes"])
def test_strict_parser_rejects_ambiguous_nonfinite_and_resource_excess(text):
    with pytest.raises(service.MLReviewProjectionError): service.parse_sql_json(text)


def test_lossless_decimal_and_raw_hash_are_not_float_or_reserialized_bytes():
    text = '{ "value": 0.10000000000000000000000000000000001, "n": 9007199254740993 }'
    row = service.parse_sql_json(text)
    assert row["value"] == Decimal("0.10000000000000000000000000000000001")
    assert row["n"] == 9007199254740993
    assert service.raw_text_sha256(text) == hashlib.sha256(text.encode()).hexdigest()
    assert service.raw_text_sha256(service.sql_canonical(row)) != service.raw_text_sha256(text)
    assert service._compare(Decimal("1e-7"), Decimal("0.0000001")) == "matched"
    assert service._compare(True, 1) == "mismatch"
    assert service._compare("1", 1) == "mismatch"
    assert service._compare([1, 2], [2, 1]) == "mismatch"
    assert service._compare(Decimal("0.1"), row["value"], json_field=True) == "unresolved"
    assert service._compare(Decimal("0.1"), Decimal("0.1001"), json_field=True) == "mismatch"


@pytest.mark.parametrize("value", [1.0, Decimal("NaN"), Decimal("Infinity"), {1: "key"}, {"x": object()}])
def test_canonical_never_coerces_python_floats_or_nonjson_objects(value):
    with pytest.raises(service.MLReviewProjectionError): service.sql_canonical(value)


@pytest.mark.parametrize("change", ["extra", "wrong_hash", "wrong_identity", "duplicate_key", "unknown_table", "noncanonical"])
def test_row_wire_has_its_own_exact_raw_text_hash(change):
    text = '{"id":"synthetic-paper","title":"Synthetic"}'
    wire = {"table": "papers", "row_id": "synthetic-paper", "row_text": text,
            "row_sha256": service.raw_text_sha256(text)}
    if change == "extra": wire["approved"] = True
    elif change == "wrong_hash": wire["row_sha256"] = "a" * 64
    elif change == "wrong_identity": wire["row_id"] = "another-paper"
    elif change == "duplicate_key":
        wire["row_text"] = '{"id":"synthetic-paper","id":"synthetic-paper"}'
        wire["row_sha256"] = service.raw_text_sha256(wire["row_text"])
    elif change == "noncanonical":
        wire["row_text"] = '{ "id": "synthetic-paper", "title": "Synthetic" }'
        wire["row_sha256"] = service.raw_text_sha256(wire["row_text"])
    else: wire["table"] = "arbitrary_private_table"
    with pytest.raises(service.MLReviewProjectionError): service.validate_row_wire(wire)


@pytest.mark.parametrize("text", ['{"unicode":"汉字𝛌\\n", "z":0.0000001, "a":1.00}',
    '{"a":[-0.0,1e30,1.234567890123456789e-17],"ä":true,"z":null}',
    '{"nested":{"longer":12,"a":1,"𝄞":"value"},"numbers":[0,-42,9007199254740993]}'])
async def test_actual_0067_sql_canonical_matches_decimal_encoder(db_session, text):
    actual = await db_session.scalar(sa.text("SELECT sclib_scientific_adjudication_canonical_v1(CAST(:body AS jsonb))"), {"body": text})
    assert service.sql_canonical(service.parse_sql_json(actual)) == actual
    assert service.sql_canonical(service.parse_sql_json(text)) == actual


async def test_real_0067_records_and_0055_grants_have_distinct_hash_rules(db_session):
    from services import research_publication
    from tests.test_scientific_adjudication_schema import accepted
    seeded, subject, request, decision = await accepted(db_session)
    for table, row in (("scientific_result_subjects", subject), ("scientific_adjudication_requests", request),
                       ("scientific_result_decisions", decision)):
        text, checksum = (await db_session.execute(sa.text(f"SELECT sclib_scientific_adjudication_canonical_v1(to_jsonb(t)),"
            f"sclib_scientific_adjudication_record_hash_v1(to_jsonb(t)) FROM {table} t WHERE id=:id"), {"id": row["id"]})).one()
        assert service.adjudication_record_sha256(text) == checksum == row["record_sha256"]
        assert service.validate_row_wire({"table": table, "row_id": str(row["id"]), "row_text": text,
            "row_sha256": service.raw_text_sha256(text)})["id"] == str(row["id"])
    await db_session.commit()
    await db_session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    await db_session.execute(sa.text("SET LOCAL statement_timeout='10s'"))
    revoked = await research_publication.revoke_role(db_session, actor_user_id=seeded["actors"]["admin"],
        grant_id=seeded["grant"]["id"], reason_code="synthetic_projection_test", dry_run=False)
    for table, identifier in (("research_role_grants", seeded["grant"]["id"]), ("research_role_revocations", revoked["id"])):
        text, checksum, native = (await db_session.execute(sa.text(f"SELECT sclib_scientific_adjudication_canonical_v1(to_jsonb(t)),"
            f"record_sha256,sclib_research_distribution_record_hash_v1(to_jsonb(t)-'id') FROM {table} t WHERE id=:id"),
            {"id": identifier})).one()
        assert service.publication_role_record_sha256(text) == checksum == native
        assert service.adjudication_record_sha256(text) != checksum


async def scientific_fixture(db):
    from tests.test_ml_physical_feature_sql import (
        freeze_scientific_candidates,
        seed_scientific_candidates,
    )
    fixture = await seed_scientific_candidates(db, properties=["phonon_min_frequency"])
    inputs = await freeze_scientific_candidates(db, fixture)
    key = next(iter(fixture["candidates"]))
    prop = fixture["physics"][key]["phonon_min_frequency"]["property"]["id"]
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    await db.execute(sa.text("SET LOCAL statement_timeout='10s'"))
    text = await db.scalar(sa.text("SELECT sclib_scientific_subject_capture_v1(:id)"), {"id": prop})
    index = {(row["table"], row["row_id"]): row for row in inputs["release"]["manifest"]["rows"]}
    return fixture, inputs, str(prop), text, index


async def test_real_0054_companion_and_sql_subject_match_without_hash_conflation(db_session):
    _, _, prop, text, index = await scientific_fixture(db_session)
    body = service.parse_subject(text, expected_sha256=service.raw_text_sha256(text))
    result = service.bridge_frozen_subject(index, property_id=prop, subject_text=text,
        expected_subject_sha256=service.raw_text_sha256(text))
    assert result["status"] == "matched" and not result["reason_codes"]
    prop_snapshot = next(row["snapshot"] for row in body["rows"] if row["table"] == "event_properties" and row["row_id"] == prop)
    sql_property_sha = service.raw_text_sha256(service.sql_canonical(prop_snapshot))
    assert sql_property_sha == service.raw_text_sha256(service.sql_canonical(prop_snapshot))
    # Only declared timestamp columns are normalized. JSONB timestamp-like raw
    # source strings are never interpreted or rewritten.
    altered = deepcopy(index)
    for key, envelope in altered.items():
        for name, value in envelope["data"].items():
            if value is not None and service.SPEC[key[0]]["fields"][name]["type"] == "DATETIME":
                envelope["data"][name] = service._date(value, "DATETIME").replace("+00:00", "Z")
        envelope["row_sha256"] = digest(envelope["data"])
    assert sql_property_sha != altered[("event_properties", prop)]["row_sha256"]
    assert service.bridge_frozen_subject(altered, property_id=prop, subject_text=text,
        expected_subject_sha256=service.raw_text_sha256(text))["status"] == "matched"


@pytest.mark.parametrize("mutation", ["missing_source", "extra_field", "target_id", "wrong_fk_revision", "wrong_support", "artifact_hash"])
async def test_subject_audit_rejects_resealed_omissions_or_binding_changes(db_session, mutation):
    from tests.test_scientific_adjudication_schema import fixture
    seeded = await fixture(db_session)
    text = await db_session.scalar(sa.text("SELECT sclib_scientific_subject_capture_v1(:id)"), {"id": seeded["property_id"]})
    body = service.parse_subject(text)
    if mutation == "missing_source":
        body["rows"] = [row for row in body["rows"] if row["table"] != "materials"]
    elif mutation == "extra_field": body["rows"][0]["snapshot"]["fake_approval"] = True
    elif mutation == "target_id": body["target"]["event_id"] = "00000000-0000-0000-0000-000000000000"
    elif mutation == "wrong_fk_revision":
        next(row["snapshot"] for row in body["rows"] if row["table"] == "research_runs")["input_manifest_id"] = "00000000-0000-0000-0000-000000000000"
    elif mutation == "wrong_support": body["support_artifact_ids"] = []
    else: body["artifacts"][0]["bytes_sha256"] = "f" * 64
    changed = service.sql_canonical(body)
    with pytest.raises(service.MLReviewProjectionError):
        service.parse_subject(changed, expected_sha256=service.raw_text_sha256(changed))


async def test_changed_scientific_value_and_unrecoverable_json_decimal_are_not_equivalent(db_session):
    _, _, prop, text, index = await scientific_fixture(db_session)
    body = service.parse_subject(text)
    row = next(row["snapshot"] for row in body["rows"] if row["table"] == "event_properties" and row["row_id"] == prop)
    row["value"] += 1
    changed = service.sql_canonical(body)
    assert service.bridge_frozen_subject(index, property_id=prop, subject_text=changed,
        expected_subject_sha256=service.raw_text_sha256(changed))["status"] == "mismatch"
    body = service.parse_subject(text)
    row = next(row["snapshot"] for row in body["rows"] if row["table"] == "event_properties" and row["row_id"] == prop)
    row["raw"] = {"high_precision": Decimal("0.1000000000000000000000000000001")}
    changed = service.sql_canonical(body)
    altered = deepcopy(index)
    altered[("event_properties", prop)]["data"]["raw"] = {"high_precision": 0.1}
    altered[("event_properties", prop)]["row_sha256"] = digest(altered[("event_properties", prop)]["data"])
    result = service.bridge_frozen_subject(altered, property_id=prop, subject_text=changed,
        expected_subject_sha256=service.raw_text_sha256(changed))
    assert result["status"] == "unresolved" and "legacy_numeric_precision_unresolved" in result["reason_codes"]
