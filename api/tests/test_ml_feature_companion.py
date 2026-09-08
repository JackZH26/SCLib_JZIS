"""Real disposable SQL companions; every source/reviewer assertion is synthetic."""
from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from models.ml_feature_companion_v1 import TABLE_NAME
from services import ml_feature_companion as service
from services.research_release_manifest import canonical, digest
from tests.test_ml_task_dataset_sql import freeze_task_candidates, seed_task_candidates
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state
from tests.test_research_release_schema import add, capture


async def feature_fixture(db, *, flags=None, applicability=None, related_source=False):
    fixture = await seed_task_candidates(db, [{"key": "one", "formula": "MgB2", "tc": 39.0,
        "reviewed": True, "raw_overrides": {"synthetic_band_gap_ev": 0.25}}])
    candidate = fixture["candidates"]["one"]
    prop = await add(db, "event_properties", event_id=candidate["event"]["id"], property_key="band_gap",
        relation="exact", value=0.25, unit="eV", raw={"synthetic_band_gap_ev": 0.25}, record_sha256=digest({"synthetic": True}))
    inp = await add(db, "ml_example_inputs", example_id=candidate["example"]["id"], input_kind="property",
        input_event_id=candidate["event"]["id"], input_property_id=prop["id"], feature_key="band_gap",
        matching_policy_version="synthetic-exact-state/1", record_sha256=digest({"property_id": str(prop["id"])}))
    related = None
    if related_source:
        work = await add(db, "works", canonical_title="Synthetic related source")
        paper = await add(db, "papers", id="related-feature:" + uuid4().hex, source="arxiv",
            title="Synthetic related source", abstract="Synthetic source fixture", authors=[], status="published")
        await add(db, "paper_work_map", paper_id=paper["id"], work_id=work["id"],
            relation_type="preprint", match_method="manual", review_status="accepted")
        await db.execute(sa.text("UPDATE papers SET related_paper_id=:related WHERE id=:id"),
            {"related": paper["id"], "id": candidate["paper"]["id"]})
        related = {"paper_id": paper["id"], "work_id": str(work["id"])}
    frozen, base_bytes = await freeze_task_candidates(db, fixture)
    bundle = candidate["source_bundle"]
    revision = await capture(db, "source_revisions", bundle["source_revisions"][0]["id"])
    captured = await capture(db, "source_captures", bundle["source_captures"][0]["id"])
    locator = {"table": "1", "row": 1}
    application = applicability or {"mode": "exact", "scope": "same_composition_pressure_field_phase",
        "applicability_verified": True, "rationale": "Synthetic exact relational state fixture",
        "uncertainty_note": "Synthetic test, not physical evidence"}
    doc = service.feature_source_review_payload(frozen["manifest"], example_input_id=str(inp["id"]),
        source_revision=revision, capture=captured, locator=locator,
        scientific_context={"version": "synthetic-uninterpreted-context/1", "normal_state": True}, applicability=application)
    doc.update({"binding_verified": True, "version_resolved": True, "public_time_verified": True, **(flags or {})})
    payload = canonical(doc)
    artifact = await add(db, "evidence_artifacts", kind="review", schema_version=service.REVIEW_VERSION,
        source="synthetic-ml-feature-review", record_sha256=digest(doc), bytes_sha256=digest(doc),
        hash_status="verified", access="restricted", metadata={"ml_feature_source_review": doc})
    args = dict(base_release_id=frozen["release_id"], example_input_id=str(inp["id"]), source_revision_id=revision["id"],
        capture_id=captured["id"], locator=locator, review_artifact_id=str(artifact["id"]), expected_review_sha256=digest(doc),
        source_bytes=base_bytes[captured["bytes_sha256"]], review_bytes=payload)
    return {"fixture": fixture, "frozen": frozen, "base_bytes": base_bytes, "args": args, "review": doc,
        "artifact_bytes": {**base_bytes, digest(doc): payload}, "input": inp, "property": prop,
        "source_revision": revision, "capture": captured, "review_artifact": artifact, "related": related}


async def companion(db, fixture):
    return await service.capture_feature_companion(db, base_manifest=fixture["frozen"]["manifest"],
        expected_base_manifest_sha256=fixture["frozen"]["manifest_sha256"], artifact_bytes=fixture["artifact_bytes"])


def verify(value, fixture):
    return service.verify_feature_companion(value, base_manifest=fixture["frozen"]["manifest"],
        expected_base_manifest_sha256=fixture["frozen"]["manifest_sha256"], expected_companion_sha256=digest(value))


def reseal(value):
    value["inventory_sha256"] = digest(value["bindings"])
    value["companion_sha256"] = digest({key: item for key, item in value.items() if key != "companion_sha256"})
    return value


def test_additive_foreign_keys_do_not_modify_frozen_wire():
    from services.research_release_spec import SPEC
    assert TABLE_NAME not in SPEC
    table = Base.metadata.tables[TABLE_NAME]
    assert {fk.target_fullname for fk in table.foreign_keys} >= {
        "research_releases.id", "ml_example_inputs.id", "source_revisions.id", "source_revisions.work_id",
        "source_captures.id", "source_captures.source_revision_id", "evidence_artifacts.id", "evidence_artifacts.kind"}


async def test_actual_sql_binding_capture_offline_verification_and_exact_replay(db_session):
    fixture = await feature_fixture(db_session)
    await db_session.commit()
    before = await state(db_session)
    preview = await service.register_feature_source_binding(db_session, **fixture["args"])
    assert preview["dry_run"] is True and preview["committed"] is False
    assert await state(db_session) == before
    await service.register_feature_source_binding(db_session, **fixture["args"], dry_run=False)
    await db_session.rollback()
    assert await state(db_session) == before
    first = await service.register_feature_source_binding(db_session, **fixture["args"], dry_run=False)
    await db_session.commit()
    written = await state(db_session)
    replay = await service.register_feature_source_binding(db_session, **fixture["args"], dry_run=False)
    assert replay == {**first, "replayed": True}
    await db_session.commit()
    assert await state(db_session) == written
    value = await companion(db_session, fixture)
    result = verify(value, fixture)[str(fixture["input"]["id"])]
    assert result["target_ref"] == ["event_properties", str(fixture["property"]["id"])]
    assert result["temporal"]["status"] == "known_by"
    assert result["temporal"]["result_available_at"] == "2020-01-01T00:00:00Z"
    assert result["temporal"]["captured_at"] == "2026-01-01T00:00:00Z"
    assert result["scientific_acceptance"] is result["ml_training_approved"] is result["reviewer_authority_authenticated"] is False
    assert service.decode_companion_artifacts(value) == fixture["artifact_bytes"]
    assert await state(db_session) == written


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
async def test_bindings_are_immutable(db_session, operation):
    fixture = await feature_fixture(db_session)
    await service.register_feature_source_binding(db_session, **fixture["args"], dry_run=False)
    sql = {"UPDATE": f"UPDATE {TABLE_NAME} SET record_sha256=record_sha256", "DELETE": f"DELETE FROM {TABLE_NAME}",
           "TRUNCATE": f"TRUNCATE {TABLE_NAME}"}[operation]
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested(): await db_session.execute(sa.text(sql))


@pytest.mark.parametrize("flag", ["binding_verified", "version_resolved", "public_time_verified"])
@pytest.mark.parametrize("value", [1, "true", None])
async def test_review_flags_never_coerce_to_boolean(db_session, flag, value):
    fixture = await feature_fixture(db_session, flags={flag: value})
    with pytest.raises(service.FeatureCompanionError):
        await service.register_feature_source_binding(db_session, **fixture["args"], dry_run=False)


@pytest.mark.parametrize("change", ["source_bytes", "review_bytes", "input", "capture", "locator", "review_hash"])
async def test_registration_requires_actual_exact_sources_and_review(db_session, change):
    fixture = await feature_fixture(db_session)
    args = dict(fixture["args"])
    if change in {"source_bytes", "review_bytes"}: args[change] = b"Changed synthetic bytes"
    elif change == "input": args["example_input_id"] = str(uuid4())
    elif change == "capture": args["capture_id"] = str(uuid4())
    elif change == "locator": args["locator"] = {"table": "1", "row": 2}
    else: args["expected_review_sha256"] = "f" * 64
    with pytest.raises(service.FeatureCompanionError):
        await service.register_feature_source_binding(db_session, **args, dry_run=False)


@pytest.mark.parametrize("change", ["extra_key", "authority", "authority_numeric", "base", "omit_source", "omit_bytes", "bad_bytes", "bad_locator", "duplicate_binding"])
async def test_offline_cannot_launder_tampering_by_rehashing(db_session, change):
    fixture = await feature_fixture(db_session)
    await service.register_feature_source_binding(db_session, **fixture["args"], dry_run=False)
    value = deepcopy(await companion(db_session, fixture))
    if change == "extra_key": value["private_unused"] = "SYNTHETIC-CANARY"
    elif change == "authority": value["authority"]["ml_training_approved"] = True
    elif change == "authority_numeric": value["authority"]["ml_training_approved"] = 0
    elif change == "base": value["base_manifest_sha256"] = "e" * 64
    elif change == "omit_source": value["source_rows"] = value["source_rows"][1:]
    elif change == "omit_bytes": value["artifacts_base64"].pop(next(iter(value["artifacts_base64"])))
    elif change == "bad_bytes": value["artifacts_base64"][next(iter(value["artifacts_base64"]))] = "YWJj"
    elif change == "bad_locator": value["bindings"][0]["locator"] = {"row": 99}
    else: value["bindings"].append(deepcopy(value["bindings"][0]))
    reseal(value)
    with pytest.raises(service.FeatureCompanionError): verify(value, fixture)


async def test_live_accepted_mapping_change_blocks_capture(db_session):
    fixture = await feature_fixture(db_session)
    await service.register_feature_source_binding(db_session, **fixture["args"], dry_run=False)
    # This source also belongs to the base capsule, whose 0054 guards preserve
    # its exact mapping. A source correction uses its actual lifecycle ledger.
    paper_id = fixture["source_revision"]["paper_id"]
    await db_session.execute(sa.text("UPDATE papers SET status='corrected' WHERE id=:id"), {"id": paper_id})
    with pytest.raises(service.FeatureCompanionError): await companion(db_session, fixture)


async def test_empty_capture_is_complete_empty_inventory_not_inferred_features(db_session):
    fixture = await feature_fixture(db_session)
    value = await service.capture_feature_companion(db_session, base_manifest=fixture["frozen"]["manifest"],
        expected_base_manifest_sha256=fixture["frozen"]["manifest_sha256"], artifact_bytes=fixture["base_bytes"])
    assert value["bindings"] == value["source_rows"] == [] and verify(value, fixture) == {}


async def test_independent_hash_pins_full_companion_bytes_not_its_internal_body_hash(db_session):
    fixture = await feature_fixture(db_session)
    await service.register_feature_source_binding(db_session, **fixture["args"], dry_run=False)
    value = await companion(db_session, fixture)
    assert digest(value) != value["companion_sha256"]
    with pytest.raises(service.FeatureCompanionError):
        service.verify_feature_companion(value, base_manifest=fixture["frozen"]["manifest"],
            expected_base_manifest_sha256=fixture["frozen"]["manifest_sha256"],
            expected_companion_sha256=value["companion_sha256"])
    assert verify(value, fixture)


async def test_related_source_closure_is_grouping_only_and_offline_holds_propagate(db_session):
    fixture = await feature_fixture(db_session, related_source=True)
    await service.register_feature_source_binding(db_session, **fixture["args"], dry_run=False)
    value = await companion(db_session, fixture)
    result = verify(value, fixture)[str(fixture["input"]["id"])]
    assert ("paper", fixture["related"]["paper_id"]) in result["group_keys"]
    assert ("work", fixture["related"]["work_id"]) in result["group_keys"]
    assert len(result["witnesses"]) == 1
    changed = deepcopy(value)
    for row in changed["source_rows"]:
        if row["table"] == "works" and row["row_id"] == fixture["related"]["work_id"]:
            row["data"]["publication_status"] = "retracted"
            row["row_sha256"] = digest(row["data"])
    reseal(changed)
    with pytest.raises(service.FeatureCompanionError): verify(changed, fixture)


async def test_actual_conflicting_capture_sibling_blocks_replay_and_new_capture(db_session):
    fixture = await feature_fixture(db_session)
    await service.register_feature_source_binding(db_session, **fixture["args"], dry_run=False)
    conflicting = canonical({"synthetic": True, "conflicting_source_version_bytes": True})
    sha = digest({"synthetic": True, "conflicting_source_version_bytes": True})
    values = {"id": str(uuid4()), "source_revision_id": fixture["source_revision"]["id"],
        "capture_key": "synthetic-conflicting-copy", "captured_at": "2026-01-02T00:00:00Z",
        "bytes_sha256": sha, "representation": fixture["capture"]["representation"]}
    await add(db_session, "source_captures", **{**values, "id": UUID(values["id"]),
        "source_revision_id": UUID(values["source_revision_id"]),
        "captured_at": service.utc_datetime(values["captured_at"]), "record_sha256": digest(values)})
    fixture["artifact_bytes"][sha] = conflicting
    with pytest.raises(service.FeatureCompanionError):
        await service.register_feature_source_binding(db_session, **fixture["args"], dry_run=False)
    with pytest.raises(service.FeatureCompanionError): await companion(db_session, fixture)
