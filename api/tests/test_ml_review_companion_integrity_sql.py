"""Real SQL receipts remain complete audit bytes, never scientific grouping."""
from copy import deepcopy
from uuid import uuid4

import pytest
import sqlalchemy as sa

from services.ml_feature_review_companion import MlReviewCompanionError
from services.ml_review_capture import capture_ml_review_companion
from services.ml_review_projection import parse_sql_json, raw_text_sha256, sql_canonical
from services.research_access import active_grant
from services.research_release_manifest import digest
from tests.test_ml_review_capture import reviewed_fixture, stable, verify
from tests.test_research_freeze import add
from tests.test_research_freeze import db_session as db_session
from tests.test_scientific_adjudication_schema import capture, decision_for, item_for, request_for


def reseal(value):
    value["observation_sha256"] = digest(value["observation"])
    value["companion_sha256"] = digest({key: item for key, item in value.items() if key != "companion_sha256"})
    return value


def replace_wire(wire, row):
    wire["row_text"] = sql_canonical(row)
    wire["row_sha256"] = raw_text_sha256(wire["row_text"])


async def test_repinned_outer_envelope_does_not_hide_missing_inputs_heads_or_exact_audit_bytes(db_session):
    seeded = await reviewed_fixture(db_session)
    original = await capture_ml_review_companion(db_session, **seeded["args"])
    assert verify(original, seeded)["property_holds"][seeded["property_id"]]

    def changed(kind):
        value = deepcopy(original)
        obs = value["observation"]
        reviewed = next(row for row in obs["properties"] if row["property_id"] == seeded["property_id"])
        if kind == "omitted_property":
            obs["properties"].remove(reviewed)
        elif kind == "duplicate_property":
            obs["properties"].append(deepcopy(reviewed))
        elif kind == "omitted_input":
            obs["inputs"].pop()
        elif kind == "input_binding":
            next(row for row in obs["inputs"] if row["binding_ids"])["binding_ids"].pop()
        elif kind == "property_pin":
            reviewed["frozen_row_sha256"] = "0" * 64
        elif kind == "head":
            reviewed["heads"]["extraction_fidelity"] = None
        elif kind == "missing_decision":
            obs["audit_rows"] = [row for row in obs["audit_rows"] if row["table"] != "scientific_result_decisions"]
        elif kind == "source_row_omitted":
            obs["source_observation"]["rows"].pop()
        elif kind == "source_lifecycle_omitted":
            obs["source_observation"]["lifecycle"].pop()
        elif kind == "contradictory_current_observation":
            from decimal import Decimal
            wire = next(row for row in obs["source_observation"]["rows"]
                        if row["table"] == "event_properties" and row["row_id"] == seeded["property_id"])
            row = parse_sql_json(wire["row_text"])
            row["value"] = Decimal("42.5")
            replace_wire(wire, row)
        elif kind == "foreign_property":
            reviewed["property_id"] = str(uuid4())
        elif kind == "authority_zero":
            value["authority"]["ml_training_approved"] = 0
        elif kind == "authority_true":
            value["authority"]["scientific_acceptance"] = True
        elif kind == "admin_flag":
            wire = next(row for row in obs["audit_rows"] if row["table"] == "users"
                        and row["row_id"] == obs["capture_admission"]["actor_user_id"])
            row = parse_sql_json(wire["row_text"])
            row["is_admin"] = False
            replace_wire(wire, row)
        elif kind == "request_rationale":
            wire = next(row for row in obs["audit_rows"] if row["table"] == "scientific_adjudication_requests")
            row = parse_sql_json(wire["row_text"])
            request = parse_sql_json(row["request_json"])
            request["items"][0]["rationale"] = "Changed private request without its original identity."
            row["request_json"] = sql_canonical(request)
            replace_wire(wire, row)
        elif kind in {"boolean_revision", "boolean_xid", "invalid_audit_timestamp"}:
            from services.ml_review_projection import adjudication_record_sha256
            table = "scientific_adjudication_requests" if kind == "boolean_xid" else "scientific_result_subjects"
            wire = next(row for row in obs["audit_rows"] if row["table"] == table)
            row = parse_sql_json(wire["row_text"])
            field = {"boolean_revision": "event_revision", "boolean_xid": "assembly_xid",
                     "invalid_audit_timestamp": "created_at"}[kind]
            row[field] = True if kind != "invalid_audit_timestamp" else "not a SQL timestamp"
            row["record_sha256"] = adjudication_record_sha256(sql_canonical(row))
            replace_wire(wire, row)
        return reseal(value)

    for kind in ("omitted_property", "duplicate_property", "omitted_input", "input_binding", "property_pin",
                 "head", "missing_decision", "source_row_omitted", "source_lifecycle_omitted", "foreign_property",
                 "authority_zero", "authority_true", "admin_flag", "request_rationale", "contradictory_current_observation",
                 "boolean_revision", "boolean_xid", "invalid_audit_timestamp"):
        with pytest.raises(MlReviewCompanionError):
            verify(changed(kind), seeded)
    assert original == await capture_ml_review_companion(db_session, **seeded["args"])


async def test_atomic_request_sibling_is_retained_but_never_added_to_feature_inventory(db_session):
    seeded = await reviewed_fixture(db_session, decision=None, properties=["phonon_min_frequency"])
    property_id = seeded["fixture"]["physics"][seeded["first"]]["phonon_min_frequency"]["property"]["id"]
    original_event = seeded["fixture"]["physics"][seeded["first"]]["phonon_min_frequency"]["event"]
    # A separate pending event shares the material/state, but does not change
    # any frozen event's owned property inventory or producer output document.
    event = await add(db_session, "research_events", material_id=original_event["material_id"],
        state_id=original_event["state_id"], structure_id=original_event["structure_id"],
        event_type="curation", knowledge_origin="Inferred", review_status="pending", validity_status="pending",
        record_sha256=digest({"audit_only": True}))
    other = await add(db_session, "event_properties", event_id=event["id"],
        property_key="phonon_min_frequency", unit="THz", value=0.123, relation="exact",
        registry_version="rv2/1", component_key="audit-only",
        raw={"synthetic": True, "value": 0.123}, record_sha256=digest({"audit_only": True}))
    await stable(db_session)
    subjects = [dict(await add(db_session, "scientific_result_subjects", **await capture(db_session, key)))
                for key in (property_id, other["id"])]
    items = [await item_for(db_session, subject, profile="recorded-sampled-frequency-fidelity/1.0.0", decision="reject")
             for subject in subjects]
    reviewer = {"reviewer": seeded["people"]["reviewer"],
                "grant": await active_grant(db_session, seeded["people"]["reviewer"], role="reviewer")}
    request = await request_for(db_session, reviewer, items)
    decisions = [await decision_for(db_session, request, subject, item, index)
                 for index, (subject, item) in enumerate(zip(subjects, items))]
    await db_session.execute(sa.text("SET CONSTRAINTS sa67_complete IMMEDIATE"))
    await stable(db_session)
    value = await capture_ml_review_companion(db_session, **seeded["args"])
    receipt = verify(value, seeded)
    assert str(other["id"]) not in receipt["property_pins"]
    assert str(property_id) in receipt["property_pins"]
    assert receipt["property_holds"][str(property_id)]
    assert all(not codes for key, codes in receipt["property_holds"].items() if key != str(property_id))
    rows = value["observation"]["audit_rows"]
    actual = {row["row_id"] for row in rows if row["table"] == "scientific_result_decisions"}
    assert actual == {str(row["id"]) for row in decisions}
    wire = next(row for row in rows if row["table"] == "scientific_adjudication_requests")
    body = parse_sql_json(wire["row_text"])
    assert body["request_json"] == request["request_json"] and body["item_count"] == 2
    incomplete = deepcopy(value)
    incomplete["observation"]["audit_rows"] = [row for row in incomplete["observation"]["audit_rows"]
        if row["row_id"] != str(decisions[1]["id"])]
    with pytest.raises(MlReviewCompanionError):
        verify(reseal(incomplete), seeded)
