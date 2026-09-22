"""Actual private label snapshots on capability-owned disposable PostgreSQL.

Scientific values, producer declarations and identities are synthetic; the
0054/0052/0064 rows, audit-role checks and captured SQL bytes are nevertheless
real. These fixtures do not authorize model training or scientific acceptance.
"""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Base, Material, get_engine
from models.ml_task_v2 import default_task_v2
from services import ml_label_capture as service
from services import ml_review_capture, research_publication
from services.ml_feature_companion import capture_feature_companion
from services.ml_label_companion import verify_ml_label_companion
from services.research_access import ResearchAccessDenied
from services.research_release_manifest import canonical, digest
from services.source_registry import SOURCE_REGISTRY_VERSION, import_source_provenance_bundle
from tests.test_ml_physical_feature_sql import (
    freeze_scientific_candidates,
    seed_scientific_candidates,
)
from tests.test_ml_task_dataset_sql import (
    eligible_specs,
    freeze_task_candidates,
    seed_task_candidates,
)
from tests.test_research_freeze import add, state
from tests.test_research_publication import actors


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with AsyncSession(get_engine().execution_options(isolation_level="SERIALIZABLE"), expire_on_commit=False) as session:
        try:
            yield session
        finally:
            await session.rollback()
            identifiers = session.info.get("ml_label_fixture_material_ids", set())
            if identifiers:
                # Only this test's synthetic catalogue rows; retain frozen
                # dependencies and avoid polluting unrelated public-read tests.
                await session.execute(sa.update(Material).where(Material.id.in_(identifiers)).values(needs_review=True))
                await session.commit()


async def read_snapshot(db):
    await db.commit()
    await db.execute(sa.text("SET TRANSACTION READ ONLY"))
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))


async def write_snapshot(db):
    await db.rollback()
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))


async def label_fixture(db, *, features=False, specs=None, before_freeze=None):
    """Reusable real frozen inputs and fully admitted review/label captures."""
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    people = await actors(db)
    grant = await research_publication.grant_role(db, actor_user_id=people["admin"], user_id=people["admin"],
        role="curator", reason_code="synthetic_label_full_audit", dry_run=False)
    specs = eligible_specs() if specs is None else specs
    fixture = (await seed_scientific_candidates(db, specs=specs, properties=["band_gap"]) if features
               else await seed_task_candidates(db, specs))
    db.info.setdefault("ml_label_fixture_material_ids", set()).update(
        item["material"]["id"] for item in fixture["candidates"].values())
    if before_freeze is not None:
        await before_freeze(db, fixture)
    if features:
        inputs = await freeze_scientific_candidates(db, fixture)
    else:
        release, artifact_bytes = await freeze_task_candidates(db, fixture)
        companion = await capture_feature_companion(db, base_manifest=release["manifest"],
            expected_base_manifest_sha256=release["manifest_sha256"], artifact_bytes=artifact_bytes)
        inputs = {"release": release, "artifact_bytes": artifact_bytes, "companion": companion, "task": default_task_v2()}
    await read_snapshot(db)
    common = {"actor_user_id": people["admin"], "expected_actor_grant_id": UUID(grant["id"]),
        "base_manifest": inputs["release"]["manifest"], "expected_base_manifest_sha256": inputs["release"]["manifest_sha256"],
        "source_companion": inputs["companion"], "expected_source_companion_sha256": digest(inputs["companion"]),
        "artifact_bytes": inputs["artifact_bytes"]}
    review = await ml_review_capture.capture_ml_review_companion(db, **common, export_scope=ml_review_capture.EXPORT_SCOPE)
    args = {**common, "export_scope": service.EXPORT_SCOPE,
        "review_companion": review, "expected_review_companion_sha256": digest(review)}
    label = await service.capture_ml_label_companion(db, **args)
    return {"fixture": fixture, "inputs": inputs, "people": people, "args": args,
        "review_companion": review, "label_companion": label, "first": next(iter(fixture["candidates"]))}


def verify(label, seeded):
    return verify_ml_label_companion(label, **{key: seeded["args"][key] for key in (
        "base_manifest", "expected_base_manifest_sha256", "source_companion", "expected_source_companion_sha256",
        "review_companion", "expected_review_companion_sha256")}, expected_label_companion_sha256=digest(label))


@pytest.mark.parametrize("features", [False, True])
async def test_actual_capture_includes_all_root_labels_and_preserves_full_sql(db_session, features):
    seeded = await label_fixture(db_session, features=features)
    before = await state(db_session)
    originals = canonical({key: seeded["args"][key] for key in ("base_manifest", "source_companion", "review_companion")})
    first = seeded["label_companion"]
    second = await service.capture_ml_label_companion(db_session, **seeded["args"])
    assert first == second
    assert before == await state(db_session)
    assert originals == canonical({key: seeded["args"][key] for key in ("base_manifest", "source_companion", "review_companion")})
    assert len(first["observation"]["examples"]) == len(first["observation"]["claims"]) == 5
    expected = {str(item["claim"]["id"]) for item in seeded["fixture"]["candidates"].values()}
    assert {row["claim_id"] for row in first["observation"]["claims"]} == expected
    if not features:
        assert seeded["review_companion"]["observation"]["properties"] == []
        assert seeded["review_companion"]["observation"]["inputs"] == []
    assert all(flag is False for flag in first["authority"].values())
    assert all(flag is False for flag in verify(first, seeded)["authority"].values())


@pytest.mark.parametrize("role", ["reviewer", "curator", "publisher", "member", "wrong_grant"])
async def test_admin_and_current_exact_curator_required_without_writes(db_session, role):
    seeded = await label_fixture(db_session, specs=eligible_specs()[:1])
    args = dict(seeded["args"])
    if role == "wrong_grant":
        args["expected_actor_grant_id"] = seeded["people"]["grants"]["curator"]
    else:
        args["actor_user_id"] = seeded["people"][role]
        args["expected_actor_grant_id"] = seeded["people"]["grants"].get(role, uuid4())
    before = await state(db_session)
    with pytest.raises(ResearchAccessDenied):
        await service.capture_ml_label_companion(db_session, **args)
    assert before == await state(db_session)


@pytest.mark.parametrize("scope", [None, True, "curator", "ml_review_full_audit/1.0.0", "ml_label_full_audit/2.0.0"])
async def test_explicit_label_export_scope_is_required(scope):
    with pytest.raises(service.MlLabelCaptureError, match="scope"):
        await service.capture_ml_label_companion(None, actor_user_id=uuid4(), expected_actor_grant_id=uuid4(),
            export_scope=scope, base_manifest={}, expected_base_manifest_sha256="0" * 64,
            source_companion={}, expected_source_companion_sha256="0" * 64,
            review_companion={}, expected_review_companion_sha256="0" * 64, artifact_bytes={})


@pytest.mark.parametrize("condition", ["write_transaction", "read_committed", "timezone", "unbounded_sql", "dirty"])
async def test_requires_clean_read_only_bounded_stable_snapshot(db_session, condition):
    seeded = await label_fixture(db_session, specs=eligible_specs()[:1])
    if condition == "dirty":
        db_session.add(Material(id="dirty-label:" + uuid4().hex, formula="Nb", formula_normalized="Nb"))
    else:
        await db_session.rollback()
        if condition == "read_committed":
            await db_session.execute(sa.text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ ONLY"))
        elif condition != "write_transaction":
            await db_session.execute(sa.text("SET TRANSACTION READ ONLY"))
        await db_session.execute(sa.text("SET LOCAL TIME ZONE 'Asia/Singapore'" if condition == "timezone" else "SET LOCAL TIME ZONE 'UTC'"))
        await db_session.execute(sa.text("SET LOCAL statement_timeout='0'" if condition == "unbounded_sql" else "SET LOCAL statement_timeout='5000ms'"))
    with pytest.raises(service.MlLabelCaptureError):
        await service.capture_ml_label_companion(db_session, **seeded["args"])


@pytest.mark.parametrize("pin", ["expected_base_manifest_sha256", "expected_source_companion_sha256", "expected_review_companion_sha256"])
async def test_independent_hash_pins_cannot_be_replaced_by_internal_hashes(db_session, pin):
    seeded = await label_fixture(db_session, specs=eligible_specs()[:1])
    before = await state(db_session)
    with pytest.raises(ValueError):
        await service.capture_ml_label_companion(db_session, **{**seeded["args"], pin: "0" * 64})
    assert before == await state(db_session)


async def test_old_verified_label_is_historical_and_fresh_source_recheck_fails(db_session):
    seeded = await label_fixture(db_session)
    original = deepcopy(seeded["label_companion"])
    report = verify(original, seeded)
    check = await service.recheck_ml_label_companion(db_session, **seeded["args"],
        label_companion=original, expected_label_companion_sha256=digest(original))
    assert check["observation_sha256"] == original["observation_sha256"]
    candidate = seeded["fixture"]["candidates"][seeded["first"]]
    await write_snapshot(db_session)
    await db_session.execute(sa.text("UPDATE papers SET status='retracted' WHERE id=:id"),
        {"id": candidate["paper"]["id"]})
    await read_snapshot(db_session)
    assert report == verify(original, seeded)
    with pytest.raises(service.MlLabelCaptureError, match="ml_label_observation_changed"):
        await service.recheck_ml_label_companion(db_session, **seeded["args"],
            label_companion=original, expected_label_companion_sha256=digest(original))
    fresh = await service.capture_ml_label_companion(db_session, **seeded["args"])
    assert fresh["observation_sha256"] != original["observation_sha256"]
    assert "label_current_source_held" in verify(fresh, seeded)["claim_holds"][str(candidate["claim"]["id"])]
    assert seeded["label_companion"] == original


@pytest.mark.parametrize("table,column,value", [
    ("material_claims", "validity_status", "disputed"),
    ("material_claims", "value_kelvin", 1.0),
    ("claim_qc", "review_status", "rejected"),
    ("research_events", "validity_status", "disputed"),
])
async def test_frozen_label_rows_cannot_be_rewritten_for_a_current_observation(db_session, table, column, value):
    seeded = await label_fixture(db_session, specs=eligible_specs()[:1])
    candidate = seeded["fixture"]["candidates"][seeded["first"]]
    await write_snapshot(db_session)
    target = Base.metadata.tables[table]
    predicate = (target.c.claim_id == candidate["claim"]["id"] if table == "claim_qc" else
                 target.c.id == candidate["event" if table == "research_events" else "claim"]["id"])
    before = await state(db_session)
    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(target.update().where(predicate).values({column: value}))
    assert error.value.orig.sqlstate == "55000"
    assert "frozen_research_row" in str(error.value.orig)
    assert await state(db_session) == before
    await read_snapshot(db_session)
    assert await service.capture_ml_label_companion(db_session, **seeded["args"]) == seeded["label_companion"]


@pytest.mark.parametrize("table,column,value,expected", [
    ("papers", "doi", "10.0000/synthetic.changed", "label_source_identity_changed"),
    ("works", "canonical_doi", "10.0000/synthetic.changed", "label_source_identity_changed"),
    ("works", "publication_status", "retracted", "label_current_source_held"),
    ("paper_work_map", "review_status", "pending", "label_source_binding_changed"),
    ("materials", "needs_review", True, "label_current_material_held"),
    ("materials", "status", "pending", "label_current_material_held"),
    ("materials", "status", "unknown", "label_current_material_held"),
    ("materials", "review_reason", "provenance_quarantine: synthetic", "label_current_material_held"),
    ("materials", "family", "synthetic changed family", "label_scientific_content_changed"),
])
async def test_live_catalogue_changes_hold_exact_label_without_features(db_session, table, column, value, expected):
    seeded = await label_fixture(db_session, specs=eligible_specs()[:1])
    candidate = seeded["fixture"]["candidates"][seeded["first"]]
    original = deepcopy(seeded["label_companion"])
    old_report = verify(original, seeded)
    assert old_report["claim_holds"][str(candidate["claim"]["id"])] == []
    await write_snapshot(db_session)
    target = Base.metadata.tables[table]
    keys = {"papers": "paper", "works": "work", "materials": "material"}
    predicate = (target.c.paper_id == candidate["paper"]["id"] if table == "paper_work_map" else
                 target.c.id == candidate[keys[table]]["id"])
    await db_session.execute(target.update().where(predicate).values({column: value}))
    await read_snapshot(db_session)
    before = await state(db_session)
    current = await service.capture_ml_label_companion(db_session, **seeded["args"])
    assert before == await state(db_session)
    assert expected in verify(current, seeded)["claim_holds"][str(candidate["claim"]["id"])]
    assert verify(original, seeded) == old_report
    assert seeded["label_companion"] == original


@pytest.mark.parametrize("addition", ["occurrence", "capture"])
async def test_new_owned_source_rows_are_not_silently_omitted(db_session, addition):
    seeded = await label_fixture(db_session, specs=eligible_specs()[:1])
    candidate = seeded["fixture"]["candidates"][seeded["first"]]
    await write_snapshot(db_session)
    identifier = str(uuid4())
    bundle = {"version": SOURCE_REGISTRY_VERSION, "source_revisions": [],
              "source_captures": [], "claim_source_occurrences": []}
    if addition == "occurrence":
        original = candidate["source_bundle"]["claim_source_occurrences"][0]
        table = "claim_source_occurrences"
        bundle[table] = [{"id": identifier, "claim_id": str(candidate["claim"]["id"]),
            "work_id": str(candidate["work"]["id"]), "source_revision_id": original["source_revision_id"],
            "capture_id": original["capture_id"], "occurrence_key": "synthetic-later-occurrence",
            "locator": {"table": "2", "row": 1}, "binding_status": "pending"}]
    else:
        original = candidate["source_bundle"]["source_captures"][0]
        table = "source_captures"
        bundle[table] = [{"id": identifier, "source_revision_id": original["source_revision_id"],
            "capture_key": "synthetic-later-capture", "captured_at": original["captured_at"],
            "bytes_sha256": original["bytes_sha256"], "representation": original["representation"]}]
    await import_source_provenance_bundle(db_session, bundle, dry_run=False)
    await read_snapshot(db_session)
    current = await service.capture_ml_label_companion(db_session, **seeded["args"])
    assert any(row["table"] == table and row["row_id"] == identifier for row in current["observation"]["rows"])
    assert "label_source_inventory_changed" in verify(current, seeded)["claim_holds"][str(candidate["claim"]["id"])]


async def test_latest_frozen_event_is_not_superseded_by_its_own_predecessor(db_session):
    async def predecessor(db, fixture):
        candidate = fixture["candidates"]["one"]
        event = candidate["event"]
        old = await add(db, "research_events", **{key: value for key, value in event.items()
            if key not in {"id", "created_at", "updated_at"}})
        membership = Base.metadata.tables["snapshot_event_memberships"]
        row = dict((await db.execute(sa.select(membership).where(membership.c.event_id == event["id"]))).mappings().one())
        await db.execute(membership.delete().where(membership.c.id == row["id"]))
        await db.execute(sa.text("UPDATE research_events SET revision=2,supersedes_id=:prior WHERE id=:id"),
            {"id": event["id"], "prior": old["id"]})
        row["event_revision"] = 2
        await db.execute(membership.insert().values(**row))
        candidate["event"] = {**event, "revision": 2, "supersedes_id": old["id"]}
    seeded = await label_fixture(db_session, specs=eligible_specs()[:1], before_freeze=predecessor)
    candidate = seeded["fixture"]["candidates"]["one"]
    claim_id = str(candidate["claim"]["id"])
    assert verify(seeded["label_companion"], seeded)["claim_holds"][claim_id] == []
    await write_snapshot(db_session)
    event = candidate["event"]
    later = {key: value for key, value in event.items() if key not in {"id", "created_at", "updated_at"}}
    later.update(revision=3, supersedes_id=event["id"])
    await add(db_session, "research_events", **later)
    await read_snapshot(db_session)
    current = await service.capture_ml_label_companion(db_session, **seeded["args"])
    assert "label_event_superseded" in verify(current, seeded)["claim_holds"][claim_id]


@pytest.mark.parametrize("change", ["revoked_grant", "inactive_user", "unverified_user", "admin_flag_removed"])
async def test_capture_authority_is_rechecked_in_fresh_snapshot(db_session, change):
    seeded = await label_fixture(db_session, specs=eligible_specs()[:1])
    original = seeded["label_companion"]
    await write_snapshot(db_session)
    if change == "revoked_grant":
        await research_publication.revoke_role(db_session, actor_user_id=seeded["people"]["admin"],
            grant_id=seeded["args"]["expected_actor_grant_id"], reason_code="synthetic_label_revocation", dry_run=False)
    else:
        field = {"inactive_user": "is_active", "unverified_user": "email_verified", "admin_flag_removed": "is_admin"}[change]
        users = Base.metadata.tables["users"]
        await db_session.execute(users.update().where(users.c.id == seeded["people"]["admin"]).values({field: False}))
    await read_snapshot(db_session)
    historical = verify(original, seeded)
    assert historical["observation_semantics"] == "captured_not_live"
    before = await state(db_session)
    with pytest.raises(ResearchAccessDenied):
        await service.recheck_ml_label_companion(db_session, **seeded["args"],
            label_companion=original, expected_label_companion_sha256=digest(original))
    assert before == await state(db_session)


async def test_other_current_admin_curator_cannot_reexport_an_actor_scoped_audit(db_session):
    seeded = await label_fixture(db_session, specs=eligible_specs()[:1])
    await write_snapshot(db_session)
    users = Base.metadata.tables["users"]
    await db_session.execute(users.update().where(users.c.id == seeded["people"]["curator"]).values(is_admin=True))
    await read_snapshot(db_session)
    with pytest.raises(service.MlLabelCaptureError, match="ml_label_review_actor_mismatch"):
        await service.capture_ml_label_companion(db_session, **{**seeded["args"],
            "actor_user_id": seeded["people"]["curator"],
            "expected_actor_grant_id": seeded["people"]["grants"]["curator"]})


@pytest.mark.parametrize("bad", ["missing", "changed", "extra"])
async def test_actual_base_artifact_bytes_are_verified_before_observation(db_session, bad):
    seeded = await label_fixture(db_session, specs=eligible_specs()[:1])
    artifacts = dict(seeded["args"]["artifact_bytes"])
    key = next(iter(artifacts))
    if bad == "missing":
        del artifacts[key]
    elif bad == "changed":
        artifacts[key] += b"synthetic corruption"
    else:
        artifacts["f" * 64] = b"synthetic extra bytes"
    with pytest.raises(ValueError):
        await service.capture_ml_label_companion(db_session, **{**seeded["args"], "artifact_bytes": artifacts})


async def test_feature_review_must_be_recaptured_in_same_snapshot_before_labels(db_session):
    seeded = await label_fixture(db_session, features=True, specs=eligible_specs()[:1])
    source = seeded["fixture"]["feature_bindings"][(seeded["first"], "band_gap")]["source"]
    original = canonical(seeded["args"]["source_companion"])
    await write_snapshot(db_session)
    await db_session.execute(sa.text("UPDATE papers SET status='retracted' WHERE id=:id"),
        {"id": source["revision"]["paper_id"]})
    await read_snapshot(db_session)
    with pytest.raises(service.MlLabelCaptureError, match="ml_label_feature_review_observation_changed"):
        await service.capture_ml_label_companion(db_session, **seeded["args"])
    review_args = {key: value for key, value in seeded["args"].items()
                  if key not in {"export_scope", "review_companion", "expected_review_companion_sha256"}}
    review = await ml_review_capture.capture_ml_review_companion(db_session, **review_args,
        export_scope=ml_review_capture.EXPORT_SCOPE)
    args = {**seeded["args"], "review_companion": review, "expected_review_companion_sha256": digest(review)}
    current = await service.capture_ml_label_companion(db_session, **args)
    assert current["review_companion_sha256"] == digest(review) != seeded["label_companion"]["review_companion_sha256"]
    assert original == canonical(seeded["args"]["source_companion"])
    assert all(flag is False for flag in current["authority"].values())


async def test_new_real_binding_cannot_reuse_old_immutable_feature_inventory(db_session):
    from services import ml_feature_companion
    seeded = await label_fixture(db_session, features=True, specs=eligible_specs()[:1])
    item = seeded["fixture"]["feature_bindings"][(seeded["first"], "band_gap")]
    source, review = item["source"], item["review"]
    input_id = str(seeded["fixture"]["physics"][seeded["first"]]["band_gap"]["input"]["id"])
    await write_snapshot(db_session)
    locator = {"table": "synthetic-later-confirmation", "row": 1}
    document = ml_feature_companion.feature_source_review_payload(seeded["args"]["base_manifest"],
        example_input_id=input_id, source_revision=source["revision"], capture=source["capture"],
        locator=locator, scientific_context=review["scientific_context"], applicability=review["applicability"])
    document.update(binding_verified=True, version_resolved=True, public_time_verified=True)
    payload = canonical(document)
    artifact = await add(db_session, "evidence_artifacts", kind="review", schema_version=ml_feature_companion.REVIEW_VERSION,
        source="synthetic-later-label-capture-binding", record_sha256=digest(document), bytes_sha256=digest(document),
        hash_status="verified", access="restricted", metadata={"ml_feature_source_review": document})
    await ml_feature_companion.register_feature_source_binding(db_session,
        base_release_id=seeded["inputs"]["release"]["release_id"], example_input_id=input_id,
        source_revision_id=source["revision"]["id"], capture_id=source["capture"]["id"], locator=locator,
        review_artifact_id=str(artifact["id"]), expected_review_sha256=artifact["record_sha256"],
        source_bytes=source["bytes"], review_bytes=payload, dry_run=False)
    await read_snapshot(db_session)
    with pytest.raises(service.MlLabelCaptureError, match="ml_label_binding_inventory_changed"):
        await service.capture_ml_label_companion(db_session, **seeded["args"])
    # Independently pinned old documents remain historical, not silently rebased.
    assert verify(seeded["label_companion"], seeded)["observation_semantics"] == "captured_not_live"


async def test_repeatable_read_is_historical_until_new_transaction_observes_concurrent_hold(db_session):
    seeded = await label_fixture(db_session, specs=eligible_specs()[:1])
    candidate = seeded["fixture"]["candidates"][seeded["first"]]
    original = seeded["label_companion"]
    async with AsyncSession(get_engine().execution_options(isolation_level="SERIALIZABLE")) as writer:
        await writer.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
        await writer.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
        await writer.execute(sa.text("UPDATE papers SET status='retracted' WHERE id=:id"),
            {"id": candidate["paper"]["id"]})
        await writer.commit()
    # An established stable transaction cannot promise observations of commits
    # after its snapshot. The service neither opens another connection nor lies.
    same = await service.recheck_ml_label_companion(db_session, **seeded["args"],
        label_companion=original, expected_label_companion_sha256=digest(original))
    assert same["observation_sha256"] == original["observation_sha256"]
    await db_session.rollback()
    await read_snapshot(db_session)
    with pytest.raises(service.MlLabelCaptureError, match="ml_label_observation_changed"):
        await service.recheck_ml_label_companion(db_session, **seeded["args"],
            label_companion=original, expected_label_companion_sha256=digest(original))
    assert verify(original, seeded)["observation_semantics"] == "captured_not_live"


@pytest.mark.parametrize("dimension", ["bytes", "rows"])
async def test_shared_review_and_label_budget_never_resets_between_phases(db_session, monkeypatch, dimension):
    from services import ml_label_observation
    seeded = await label_fixture(db_session, specs=eligible_specs()[:1])
    seen = []
    original_capture = ml_label_observation.capture_label_observation
    async def observed(*args, **kwargs):
        budget = kwargs["byte_budget"]
        before = dict(budget)
        result = await original_capture(*args, **kwargs)
        seen.append((before, dict(budget)))
        return result
    monkeypatch.setattr(ml_label_observation, "capture_label_observation", observed)
    assert await service.capture_ml_label_companion(db_session, **seeded["args"]) == seeded["label_companion"]
    before, after = seen[-1]
    prior, label = before[dimension], after[dimension] - before[dimension]
    assert prior > 0 and label > 0
    limit = max(prior, label)
    assert prior <= limit and label <= limit < after[dimension]
    monkeypatch.setattr(service, "MAX_BYTES" if dimension == "bytes" else "MAX_ROWS", limit)
    with pytest.raises(service.MlLabelCaptureError, match="limit"):
        await service.capture_ml_label_companion(db_session, **seeded["args"])
    assert seen[-1][0] == before and seen[-1][1] == after


async def test_final_synchronous_assembly_cannot_escape_total_deadline(db_session, monkeypatch):
    from services import ml_label_companion
    seeded = await label_fixture(db_session, specs=eligible_specs()[:1])
    real_clock = service.time.monotonic
    elapsed = [0]
    monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=lambda: real_clock() + elapsed[0]))
    original_assemble = ml_label_companion.assemble_ml_label_companion
    def slow_assembly(**kwargs):
        value = original_assemble(**kwargs)
        elapsed[0] = service.MAX_SECONDS + 1
        return value
    monkeypatch.setattr(ml_label_companion, "assemble_ml_label_companion", slow_assembly)
    with pytest.raises(service.MlLabelCaptureError, match="ml_label_capture_deadline"):
        await service.capture_ml_label_companion(db_session, **seeded["args"])


async def test_sql_failure_is_sanitized_and_never_returns_partial_observation(db_session, monkeypatch):
    seeded = await label_fixture(db_session, specs=eligible_specs()[:1])
    async def failed(*args, **kwargs):
        raise SQLAlchemyError("synthetic-private-source-secret")
    monkeypatch.setattr(service, "_capture_feature_review", failed)
    before = await state(db_session)
    with pytest.raises(service.MlLabelCaptureUnavailable) as error:
        await service.capture_ml_label_companion(db_session, **seeded["args"])
    assert str(error.value) == "ml_label_capture_unavailable"
    assert await state(db_session) == before
