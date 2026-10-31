"""Real isolated PostgreSQL regressions for the bounded 0093 increment.

Scientific examples mirror the published A/B film distinctions; fixture rows
are synthetic and never constitute a source-verified canonical promotion.
"""
import json
from pathlib import Path
import runpy
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from models.materials_result_definitions_v1 import REGISTRY_VERSION, VERSION
from tests.test_research_release_schema import add, capture, seed, release, flush_constraints
from tests.test_research_release_schema import db_session as db_session


def semantics(criterion="resistance_fraction", *, threshold=90, key="film-a-hc2-90-perpendicular", target="property"):  # Synthetic result identifier. gitleaks:allow
    value = {
        "version": VERSION,
        "definition": {
            "criterion": criterion,
            "criterion_raw": {"resistance_fraction": "90% of the normal-state resistance",
                              "zero_resistance": "zero resistance", "onset": "onset"}.get(criterion, criterion),
            "parameters": [] if criterion != "resistance_fraction" else [{
                "kind": "resistance_fraction", "name_raw": "normal-state resistance fraction",
                "quantity": {"status": "reported", "relation": "exact", "raw": f"{threshold}%",
                             "value": threshold, "unit": "%", "lower": None, "upper": None,
                             "uncertainty": None, "approximate": False},
            }],
        },
        "qualifiers": [],
    }
    if target == "property": value["result_key"] = key
    return value


async def property_row(db, fixture, definition=None, **overrides):
    return await add(db, "event_properties", **{
        "event_id": fixture["event"]["id"], "property_key": "hc2", "registry_version": REGISTRY_VERSION,
        "component_key": "perpendicular", "relation": "exact", "value": 134.4, "unit": "T",
        "record_sha256": uuid4().hex * 2, "raw": {"result_semantics": definition or semantics()}, **overrides,
    })


async def claim_row(db, fixture, definition=None, **overrides):
    return await add(db, "material_claims", **{
        "material_id": fixture["material"]["id"], "source_snapshot_id": fixture["source"]["id"],
        "event_id": fixture["event"]["id"], "result_key": "film-a-secondary-onset",
        "interpretation_revision": 1, "source_record_hash": uuid4().hex * 2, "extractor_version": "synthetic-definition-test",
        "property_type": "tc", "result_status": "observed", "value_relation": "exact", "value_kelvin": 15.5,
        "tc_definition": "onset", "extraction_metadata": {"result_semantics": definition or semantics("onset", target="claim")},
        **overrides,
    })


async def migration(db, action):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0093_materials_result_definitions.py"
    module = runpy.run_path(str(path))
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    connection = await db.connection()
    def apply(sync):
        with Operations.context(MigrationContext.configure(sync)):
            module[action]()
    await connection.run_sync(apply)


async def test_one_event_retains_thresholds_and_repeated_same_definition(db_session):
    fixture = await seed(db_session)
    rows = [await property_row(db_session, fixture)]
    rows.append(await property_row(db_session, fixture, semantics(threshold=50, key="film-a-hc2-50-perpendicular"), value=45.3))  # Synthetic result identifier. gitleaks:allow
    rows.append(await property_row(db_session, fixture, semantics(key="film-a-independent-reported-repeat"), value=135))
    assert len({row["id"] for row in rows}) == 3
    assert len({row["event_id"] for row in rows}) == len({row["component_key"] for row in rows}) == 1
    assert [row["raw"]["result_semantics"]["definition"]["parameters"][0]["quantity"]["value"] for row in rows] == [90, 50, 90]
    # Same result identity remains a collision even if the value/definition changes.
    with pytest.raises(IntegrityError, match="uq_mrd93_event_result_key"):
        async with db_session.begin_nested():
            await property_row(db_session, fixture, semantics(threshold=50), value=45.3)
    assert (await capture(db_session, "research_events", fixture["event"]["id"]))["review_status"] == "pending"


async def test_secondary_onset_is_orthogonal_to_criterion(db_session):
    fixture = await seed(db_session)
    definition = semantics("onset", target="claim")
    definition["qualifiers"] = [{"kind": "transition_stage", "stage": "secondary", "raw": "secondary transition onset"}]
    secondary = await claim_row(db_session, fixture, definition)
    zero = await claim_row(db_session, fixture, semantics("zero_resistance", target="claim"),
                           result_key="film-a-zero", tc_definition="zero_resistance", value_kelvin=6)
    assert secondary["event_id"] == zero["event_id"]
    assert secondary["tc_definition"] == "onset"
    assert secondary["extraction_metadata"]["result_semantics"]["qualifiers"][0]["stage"] == "secondary"
    with pytest.raises(IntegrityError, match="ck_material_claims_tc_definition"):
        async with db_session.begin_nested():
            await claim_row(db_session, fixture, definition, result_key="wrong-projection", tc_definition="zero_resistance")


@pytest.mark.parametrize("bad", [
    None, {}, [], "malformed", {"version": VERSION},
    {**semantics(), "version": "future/999"},
    {**semantics(), "result_key": " "},
    {**semantics(), "unregistered": "no"},
    {**semantics(), "definition": None},
    {**semantics(), "qualifiers": None},
    {**semantics(), "definition": {"criterion": None, "criterion_raw": None, "parameters": []}},
    {**semantics(), "definition": {"criterion": "resistance_fraction", "criterion_raw": "90%", "parameters": []}},
])
async def test_malformed_or_null_json_never_bypasses_check(db_session, bad):
    fixture = await seed(db_session)
    with pytest.raises(IntegrityError, match="ck_rv2_property_registry"):
        async with db_session.begin_nested():
            await property_row(db_session, fixture, raw={"result_semantics": bad})


@pytest.mark.parametrize(("path", "bad"), [
    (("value",), "90"), (("value",), -1), (("value",), 101), (("unit",), "K"),
    (("lower",), 90), (("approximate",), None), (("relation",), "interval"),
    (("uncertainty",), {}), (("raw",), None),
])
async def test_threshold_shape_domain_and_literal_are_checked(db_session, path, bad):
    fixture = await seed(db_session)
    definition = semantics()
    definition["definition"]["parameters"][0]["quantity"][path[0]] = bad
    with pytest.raises(IntegrityError, match="ck_rv2_property_registry"):
        async with db_session.begin_nested(): await property_row(db_session, fixture, definition)


async def test_registry_distinguishes_geometry_fit_and_field_units(db_session):
    fixture = await seed(db_session)
    definition = semantics("fit_parameter", key="film-a-fitted-layer")
    row = await property_row(db_session, fixture, definition, property_key="superconducting_layer_thickness", value=7.5, unit="nm")
    assert row["property_key"] == "superconducting_layer_thickness"
    assert fixture["state"]["conditions"] == {}  # No silent sample thickness overwrite.
    for invalid in (dict(unit="A/m"), dict(property_key="tc", unit="K"), dict(registry_version="rv2/1")):
        with pytest.raises(IntegrityError, match="ck_rv2_property_registry"):
            async with db_session.begin_nested(): await property_row(db_session, fixture, **invalid)
    with pytest.raises(IntegrityError, match="ck_rv2_property_registry"):
        async with db_session.begin_nested(): await property_row(db_session, fixture, raw={})


async def test_legacy_meanings_uniqueness_and_release_remain_usable(db_session):
    fixture = await seed(db_session)
    # An old broad label is retained; no migration sharpens it to a new onset.
    legacy = await claim_row(db_session, fixture, tc_definition="diamagnetic", extraction_metadata={}, result_key="legacy-diamagnetic")
    assert legacy["tc_definition"] == "diamagnetic" and legacy["extraction_metadata"] == {}
    with pytest.raises(IntegrityError, match="uq_mrd93_legacy_component"):
        async with db_session.begin_nested():
            await add(db_session, "event_properties", event_id=fixture["event"]["id"], property_key="band_gap",
                      relation="exact", value=1, unit="eV", record_sha256="d" * 64)
    await release(db_session, fixture)
    await flush_constraints(db_session)


@pytest.mark.parametrize("target", ["claim", "property"])
async def test_new_definition_refuses_old_release_policy(db_session, target):
    fixture = await seed(db_session)
    await (claim_row(db_session, fixture) if target == "claim" else property_row(db_session, fixture))
    with pytest.raises(IntegrityError, match="materials_result_definition_release_policy_pending"):
        async with db_session.begin_nested(): await release(db_session, fixture)


async def test_exact_row_capture_roundtrip_and_empty_downgrade_upgrade(db_session):
    fixture = await seed(db_session)
    before = {name: await capture(db_session, name, fixture[key]["id"])
              for name, key in (("material_claims", "claim"), ("event_properties", "prop"))}
    await migration(db_session, "downgrade")
    await migration(db_session, "upgrade")
    assert before == {name: await capture(db_session, name, fixture[key]["id"])
                      for name, key in (("material_claims", "claim"), ("event_properties", "prop"))}
    row = await property_row(db_session, fixture)
    captured = await capture(db_session, "event_properties", row["id"])
    # PostgreSQL record reconstruction: exact current canonical row shape.
    restored = (await db_session.execute(sa.text(
        "SELECT to_jsonb(x) FROM jsonb_populate_record(NULL::public.event_properties,CAST(:row AS jsonb)) x"
    ), {"row": json.dumps(captured)})).scalar_one()
    assert restored == captured
    with pytest.raises(IntegrityError, match="retained_data_refuses_downgrade"):
        async with db_session.begin_nested(): await migration(db_session, "downgrade")
    assert await capture(db_session, "event_properties", row["id"]) == captured


async def test_preexisting_reserved_payload_stops_migration_without_reinterpretation(db_session):
    fixture = await seed(db_session)
    await migration(db_session, "downgrade")
    await db_session.execute(sa.text("UPDATE public.event_properties SET raw=CAST(:raw AS jsonb) WHERE id=:id"),
        {"id": fixture["prop"]["id"], "raw": json.dumps({"result_semantics": {"unknown_legacy_payload": True}})})
    before = await capture(db_session, "event_properties", fixture["prop"]["id"])
    with pytest.raises(IntegrityError, match="reserved_member_collision"):
        async with db_session.begin_nested(): await migration(db_session, "upgrade")
    assert before == await capture(db_session, "event_properties", fixture["prop"]["id"])
