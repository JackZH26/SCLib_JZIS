"""Actual SQL formatting parity and fail-closed source observation replay."""
from __future__ import annotations

from copy import deepcopy

import pytest
import sqlalchemy as sa

from services import ml_review_source_observation as source
from services.ml_review_projection import sql_canonical
from tests.test_ml_review_capture import reviewed_fixture
from tests.test_research_freeze import db_session as db_session


@pytest.mark.parametrize("document", [
    '{"x":1e-7,"long key":{"b":[true,1,1.00,null,"香港"],"a":-0.00000003}}',
    '{"é":1,"aaa":2,"aa":3,"a":4,"𐀀":5,"escape":"\\n\\t\\\"\\\\"}',
    '{"minimum":-1.2345678901234567890123456789,"large":123456789012345678901234567890}',
])
async def test_pg_snapshot_text_serializer_matches_actual_jsonb_sql(db_session, document):
    actual = await db_session.scalar(sa.text("SELECT CAST(:document AS jsonb)::text"), {"document": document})
    assert source.pg_json(source.parse(actual)) == actual
    assert source.raw_sha(actual) == source.raw_sha(source.pg_json(source.parse(document)))


def test_lossless_source_equality_does_not_coerce_booleans_or_numeric_strings():
    assert source.equal(source.parse('{"x":0.000001}'), source.parse('{"x":1e-6}'))
    assert not source.equal(source.parse('{"x":true}'), source.parse('{"x":1}'))
    assert not source.equal(source.parse('{"x":"1"}'), source.parse('{"x":1}'))
    assert not source.equal(source.parse('[1,2]'), source.parse('[2,1]'))


async def test_resealed_changed_source_fields_cannot_reuse_old_record_hash(db_session):
    seeded = await reviewed_fixture(db_session, decision=None, properties=["band_gap"])
    args = seeded["args"]
    ids = [str(value["band_gap"]["property"]["id"]) for value in seeded["fixture"]["physics"].values()]
    observed = await source.capture_source_observation(db_session, base_manifest=args["base_manifest"],
        source_companion=args["source_companion"], property_ids=ids, byte_budget={"bytes": 0})
    binding = args["source_companion"]["bindings"][0]
    revision_id, capture_id, review_id = binding["source_revision_id"], binding["capture_id"], binding["review_artifact_id"]
    for table, identifier, field, changed in (
        ("source_revisions", revision_id, "metadata_sha256", "0" * 64),
        ("source_captures", capture_id, "bytes_sha256", "0" * 64),
        ("evidence_artifacts", review_id, "metadata", {"forged_but_same_record_sha256": True}),
    ):
        modified = deepcopy(observed)
        wire = next(row for row in modified["rows"] if (row["table"], row["row_id"]) == (table, identifier))
        row = source.parse(wire["row_text"])
        retained = row["record_sha256"]
        row[field] = changed
        wire["row_text"] = sql_canonical(row)
        wire["row_sha256"] = source.raw_sha(wire["row_text"])
        assert source.parse(wire["row_text"])["record_sha256"] == retained
        report = source.verify_source_observation(modified, base_manifest=args["base_manifest"],
            source_companion=args["source_companion"], property_ids=ids)
        assert "feature_source_binding_changed" in report["input_source_holds"][binding["example_input_id"]]
    for invalidity in ("boolean_governance", "unknown_governance", "composite_fk"):
        modified = deepcopy(observed)
        table = "event_evidence" if invalidity == "composite_fk" else "research_events"
        wire = next(row for row in modified["rows"] if row["table"] == table)
        row = source.parse(wire["row_text"])
        if invalidity == "composite_fk":
            props = [source.parse(item["row_text"]) for item in modified["rows"] if item["table"] == "event_properties"]
            first = props[0]
            other = next(item for item in props if item["event_id"] != first["event_id"])
            row.update(input_property_id=first["id"], input_event_id=other["event_id"])
        else:
            row["validity_status"] = False if invalidity == "boolean_governance" else "arbitrarily_clear"
        wire["row_text"] = sql_canonical(row)
        wire["row_sha256"] = source.raw_sha(wire["row_text"])
        with pytest.raises(source.ReviewSourceError, match="field_type|governance_enum|composite_binding"):
            source.verify_source_observation(modified, base_manifest=args["base_manifest"],
                source_companion=args["source_companion"], property_ids=ids)


async def test_missing_owned_source_capture_and_lifecycle_snapshot_fail_closed(db_session):
    seeded = await reviewed_fixture(db_session, decision=None, properties=["band_gap"])
    args = seeded["args"]
    ids = [str(value["band_gap"]["property"]["id"]) for value in seeded["fixture"]["physics"].values()]
    observed = await source.capture_source_observation(db_session, base_manifest=args["base_manifest"],
        source_companion=args["source_companion"], property_ids=ids, byte_budget={"bytes": 0})
    for remove in ("source_capture", "snapshot"):
        modified = deepcopy(observed)
        if remove == "source_capture":
            identifier = args["source_companion"]["bindings"][0]["capture_id"]
            modified["rows"] = [row for row in modified["rows"] if (row["table"], row["row_id"]) != ("source_captures", identifier)]
        else:
            modified["lifecycle"].pop()
        with pytest.raises(source.ReviewSourceError):
            source.verify_source_observation(modified, base_manifest=args["base_manifest"],
                source_companion=args["source_companion"], property_ids=ids)


async def test_sql_size_preflight_rejects_before_hydrating_row_text():
    class Result:
        def scalars(self):
            return self
        def all(self):
            return [source.MAX_BYTES + 1]
    class Database:
        calls = []
        async def execute(self, statement, params):
            self.calls.append(str(statement))
            return Result()
    db = Database()
    with pytest.raises(source.ReviewSourceError, match="byte_limit"):
        await source.read_rows(db, "materials", ["synthetic-only"], byte_budget={"bytes": 0})
    assert len(db.calls) == 1 and "octet_length" in db.calls[0]
    assert " AS row_text" not in db.calls[0]
