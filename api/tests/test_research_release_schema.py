"""ML04 direct-SQL and concurrency contracts on guarded PostgreSQL only."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

from models.db import Base, get_session_factory
from models.research_release_v1 import ALLOWED_TABLES, LOCK_FUNCTION, OWNED_RELATIONS, TABLE_ORDER
from services.research_release_manifest import dependencies, owned_relations
from services.research_release_spec import FKS, SPEC


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        await session.execute(sa.text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        await session.execute(sa.text("SET LOCAL TimeZone='UTC'"))
        yield session


async def add(db, table_name, /, **values):
    table = Base.metadata.tables[table_name]
    return (await db.execute(table.insert().values(**values).returning(table))).mappings().one()


async def capture(db, name, row_id):
    key = "paper_id" if name == "paper_work_map" else "id"
    return (await db.execute(sa.text(f"SELECT to_jsonb(item) FROM public.{name} item WHERE {key}::text=:id"),
                            {"id": str(row_id)})).scalar_one()


def sha(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


async def seed(db):
    material = await add(db, "materials", id="rf54-" + uuid4().hex, formula="MgB2", formula_normalized="MgB2")
    source = await add(db, "source_snapshots", dataset_version="synthetic", schema_version="1")
    dataset = await add(db, "ml_dataset_snapshots", source_snapshot_id=source["id"], name=uuid4().hex,
                        version="1", label_policy_version="synthetic", feature_schema_version="synthetic",
                        split_ruleset_version="synthetic", row_count=1)
    artifact = await add(db, "evidence_artifacts", kind="review", schema_version="synthetic", source="synthetic",
                         record_sha256="a" * 64, hash_status="not_applicable", access="unknown")
    state = await add(db, "material_states", material_id=material["id"], resolution="source_scoped",
                      condition_schema_version="synthetic", pressure_status="not_reported", temperature_role="unknown",
                      context_sha256="b" * 64, source_artifact_id=artifact["id"])
    event = await add(db, "research_events", material_id=material["id"], state_id=state["id"],
                      event_type="measurement", knowledge_origin="Observed", record_sha256="c" * 64)
    prop = await add(db, "event_properties", event_id=event["id"], property_key="band_gap", relation="exact",
                     value=0, unit="eV", record_sha256="d" * 64)
    claim = await add(db, "material_claims", material_id=material["id"], source_snapshot_id=source["id"],
                      event_id=event["id"], result_key="pending-tc", interpretation_revision=1,
                      source_record_hash=uuid4().hex * 2, extractor_version="synthetic")
    example = await add(db, "ml_examples", dataset_snapshot_id=dataset["id"], claim_id=claim["id"],
                        material_id=material["id"], example_key="pending", split="train", task_type="tc_regression",
                        label_data={"synthetic_pending": True}, work_group="unknown", material_group=material["id"],
                        duplicate_group=uuid4().hex, assignment_hash="d" * 64)
    return dict(material=material, source=source, dataset=dataset, artifact=artifact, state=state, event=event, prop=prop,
                claim=claim, example=example)


async def release(db, fixture, targets=None, *, insert_pins=True, manifest_overrides=None, omit=(), expand_receipts=True):
    await db.execute(sa.text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
    await db.execute(sa.text("SET LOCAL TimeZone='UTC'"))
    targets = targets or [("ml_dataset_snapshots", fixture["dataset"]["id"]),
                          ("research_events", fixture["event"]["id"]), ("material_states", fixture["state"]["id"])]
    root = ("ml_dataset_snapshots", fixture["dataset"]["id"])
    if root not in targets:
        targets = [*targets, root]
    rows, seen, pending = [], set(), [(name, str(row_id)) for name, row_id in targets]
    while pending:
        table, row_id = pending.pop(0)
        if (table, row_id) in seen:
            continue
        seen.add((table, row_id))
        data = await capture(db, table, row_id)
        rows.append({"table": table, "row_id": str(row_id), "data": data, "row_sha256": sha(data)})
        if table == "research_import_receipts" and not expand_receipts:
            pending.extend((target, data[fields[0]]) for fields, target, _ in FKS[table]
                           if all(data[field] is not None for field in fields))
        else:
            pending.extend(dependencies(table, data))
        for child, field in owned_relations(table):
            key = "paper_id" if child == "paper_work_map" else "id"
            identifiers = (await db.execute(sa.text(f"SELECT {key}::text FROM public.{child} WHERE {field}::text=:id"),
                                           {"id": row_id})).scalars().all()
            pending.extend((child, identifier) for identifier in identifiers)
    rows = [row for row in rows if (row["table"], row["row_id"]) not in omit]
    manifest = {"rows": rows, **(manifest_overrides or {})}
    result = await add(db, "research_releases", id=uuid4(), dataset_snapshot_id=fixture["dataset"]["id"],
                       manifest=manifest, manifest_sha256=sha(manifest), bundle_sha256="e" * 64,
                       closure_policy_version="synthetic", assembly_xid=-123)
    if insert_pins:
        for row in rows:
            await add(db, "research_release_pins", id=uuid4(), release_id=result["id"], table_name=row["table"],
                      row_id=row["row_id"], row_data=row["data"], row_sha256=row["row_sha256"])
    return result, rows


async def flush_constraints(db):
    await db.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
    await db.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))


def test_release_schema_is_connected_and_integrity_only():
    assert len(TABLE_ORDER) == 4
    assert len(ALLOWED_TABLES) == 28
    assert set(ALLOWED_TABLES) <= set(Base.metadata.tables)
    releases = Base.metadata.tables["research_releases"]
    assert str(next(iter(releases.c.dataset_snapshot_id.foreign_keys)).column) == "ml_dataset_snapshots.id"


def test_frozen_wire_inventory_covers_exactly_current_allowed_metadata():
    # Regression alarm only: production freezing never derives a new wire
    # contract silently from ORM metadata. Changes need explicit policy review.
    assert set(SPEC) == set(FKS) == set(ALLOWED_TABLES)
    assert set(OWNED_RELATIONS) <= set(ALLOWED_TABLES)
    for name in ALLOWED_TABLES:
        assert OWNED_RELATIONS.get(name, ()) == owned_relations(name)


@pytest.mark.parametrize("table_name", ALLOWED_TABLES)
def test_frozen_wire_fields_and_traversed_fks_match_metadata(table_name):
    table = Base.metadata.tables[table_name]

    def normalized_type(value):
        # PostgreSQL/SQLAlchemy names that share the frozen JSON wire shape.
        name = " ".join(str(value).upper().split())
        return {"TIMESTAMP WITH TIME ZONE": "DATETIME", "DOUBLE PRECISION": "FLOAT"}.get(name, name)

    actual_fields = {column.name: {"nullable": column.nullable, "type": normalized_type(column.type)}
                     for column in table.columns}
    expected_fields = {name: {"nullable": field["nullable"], "type": normalized_type(field["type"])}
                       for name, field in SPEC[table_name]["fields"].items()}
    assert actual_fields == expected_fields, "Explicit closure policy revision required for changed fields"
    for column in table.columns:
        if isinstance(column.type, sa.DateTime):
            assert column.type.timezone is True, "Frozen DATETIME wire fields require an aware instant"

    actual_fks, actor_fks = set(), set()
    for constraint in table.foreign_key_constraints:
        targets = {element.column.table.name for element in constraint.elements}
        assert len(targets) == 1
        target = targets.pop()
        fields = tuple(element.parent.name for element in constraint.elements)
        if target == "users":
            actor_fks.add(fields)
            continue
        assert target in ALLOWED_TABLES, "Unclassified outbound dependency requires policy review"
        actual_fks.add((fields, target, tuple(element.column.name for element in constraint.elements)))
    assert actual_fks == set(FKS[table_name]), "Explicit closure policy revision required for changed references"
    assert actor_fks == ({("reviewed_by",)} if table_name == "claim_qc" else set())


async def test_actual_row_pins_and_internal_xid_ignore_caller_value(db_session):
    fixture = await seed(db_session)
    capsule, _ = await release(db_session, fixture)
    assert capsule["assembly_xid"] > 0
    assert capsule["scientific_acceptance"] is False
    assert capsule["public_release"] is False
    await flush_constraints(db_session)


@pytest.mark.parametrize("change", ["missing", "data", "table", "id", "hash"])
async def test_incomplete_or_tampered_pin_manifest_rejected(db_session, change):
    fixture = await seed(db_session)
    with pytest.raises((IntegrityError, DBAPIError)):
        async with db_session.begin_nested():
            capsule, rows = await release(db_session, fixture, insert_pins=False)
            for index, row in enumerate(rows):
                if change == "missing" and index == 0:
                    continue
                values = dict(id=uuid4(), release_id=capsule["id"], table_name=row["table"],
                              row_id=row["row_id"], row_data=row["data"], row_sha256=row["row_sha256"])
                if index == 0:
                    if change == "data":
                        values["row_data"] = {**row["data"], "version": "tampered"}
                    if change == "table":
                        values["table_name"] = "users"
                    if change == "id":
                        values["row_id"] = str(uuid4())
                    if change == "hash":
                        values["row_sha256"] = "0" * 64
                await add(db_session, "research_release_pins", **values)
            await flush_constraints(db_session)


@pytest.mark.parametrize("name", ["research_events", "material_states", "ml_dataset_snapshots", "evidence_artifacts",
                                 "event_properties", "source_snapshots"])
@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_pinned_scientific_rows_cannot_change_by_direct_sql(db_session, name, operation):
    fixture = await seed(db_session)
    keys = {"research_events": "event", "material_states": "state", "ml_dataset_snapshots": "dataset",
            "evidence_artifacts": "artifact", "event_properties": "prop", "source_snapshots": "source"}
    row_id = fixture[keys[name]]["id"]
    await release(db_session, fixture, [(name, row_id)])
    await flush_constraints(db_session)
    query = f"UPDATE public.{name} SET id=id WHERE id=:id" if operation == "update" else f"DELETE FROM public.{name} WHERE id=:id"
    with pytest.raises(DBAPIError, match="frozen_research_row"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(query), {"id": row_id})


async def test_frozen_owner_rejects_unselected_child_changes_and_appends(db_session):
    fixture = await seed(db_session)
    await release(db_session, fixture)
    await flush_constraints(db_session)
    with pytest.raises(DBAPIError, match="frozen_research_owned_dependency|frozen_research_row"):
        async with db_session.begin_nested():
            await add(db_session, "event_properties", event_id=fixture["event"]["id"], property_key="energy_above_hull",
                      relation="exact", value=0, unit="eV/atom", record_sha256="f" * 64)
    with pytest.raises(DBAPIError, match="frozen_research_owned_dependency|frozen_research_row"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("UPDATE event_properties SET value=0.1 WHERE id=:id"), {"id": fixture["prop"]["id"]})


async def test_catalogue_copy_is_stable_but_live_governance_can_change(db_session):
    fixture = await seed(db_session)
    capsule, rows = await release(db_session, fixture, [("materials", fixture["material"]["id"])])
    await flush_constraints(db_session)
    await db_session.execute(sa.text("UPDATE materials SET formula='Nb' WHERE id=:id"), {"id": fixture["material"]["id"]})
    stored = (await db_session.execute(sa.text("SELECT row_data FROM research_release_pins WHERE release_id=:id AND table_name='materials'"),
                                       {"id": capsule["id"]})).scalar_one()
    assert stored == rows[0]["data"]
    assert stored["formula"] == "MgB2"


async def test_new_membership_and_superseding_event_do_not_mutate_old_event(db_session):
    fixture = await seed(db_session)
    await release(db_session, fixture)
    await flush_constraints(db_session)
    other_source = await add(db_session, "source_snapshots", dataset_version="another-capture", schema_version="1")
    await add(db_session, "snapshot_event_memberships", snapshot_id=other_source["id"], event_id=fixture["event"]["id"],
              event_revision=1, source_occurrence_key="same-occurrence", source_record_sha256="a" * 64,
              result_manifest_sha256="b" * 64)
    await add(db_session, "research_events", material_id=fixture["material"]["id"], state_id=fixture["state"]["id"],
              event_type="measurement", knowledge_origin="Observed", revision=2, supersedes_id=fixture["event"]["id"],
              record_sha256="d" * 64)


async def edge(db, origin, target, kind="derives_from"):
    return await add(db, "event_evidence", event_id=origin["event"]["id"], link_type=kind,
                     input_event_id=target["event"]["id"], input_property_id=target["prop"]["id"])


@pytest.mark.parametrize("length", [2, 3, 5])
async def test_multihop_derivation_cycles_rejected(db_session, length):
    items = [await seed(db_session) for _ in range(length)]
    for origin, target in zip(items, items[1:]):
        await edge(db_session, origin, target)
    with pytest.raises(IntegrityError, match="research_dependency_cycle"):
        async with db_session.begin_nested():
            await edge(db_session, items[-1], items[0])


async def test_reciprocal_support_is_not_a_computational_cycle(db_session):
    first, second = await seed(db_session), await seed(db_session)
    await edge(db_session, first, second, "supports")
    await edge(db_session, second, first, "refutes")


@pytest.mark.parametrize("name,parent", [("research_runs", "parent_run_id"),
                                        ("structure_records", "parent_structure_id"), ("research_events", "supersedes_id")])
async def test_parent_cycles_rejected(db_session, name, parent):
    fixture = await seed(db_session)
    if name == "research_runs":
        values = dict(run_kind="curation", settings_schema_version="1", record_sha256="a" * 64)
    elif name == "structure_records":
        values = dict(material_id=fixture["material"]["id"], structure_kind="unresolved", record_sha256="a" * 64)
    else:
        values = dict(material_id=fixture["material"]["id"], state_id=fixture["state"]["id"],
                      event_type="measurement", knowledge_origin="Observed", record_sha256="a" * 64)
    first = await add(db_session, name, **values)
    second = await add(db_session, name, **values, **{parent: first["id"]})
    with pytest.raises(IntegrityError, match="research_dependency_cycle"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(f"UPDATE {name} SET {parent}=:parent WHERE id=:id"),
                                     {"parent": second["id"], "id": first["id"]})


async def test_two_connections_cannot_commit_opposing_dependencies(db_session):
    first, second = await seed(db_session), await seed(db_session)
    await db_session.commit()
    async with get_session_factory()() as other:
        await edge(db_session, first, second)
        with pytest.raises(DBAPIError, match="research_integrity_busy"):
            await asyncio.wait_for(edge(other, second, first), timeout=2)
        await other.rollback()
        await db_session.commit()
        with pytest.raises(IntegrityError, match="research_dependency_cycle"):
            await edge(other, second, first)
        await other.rollback()


async def test_stale_serializable_snapshot_cannot_freeze_after_writer_commit(db_session):
    fixture = await seed(db_session)
    await db_session.commit()
    async with get_session_factory()() as stale:
        await stale.execute(sa.text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        await stale.execute(sa.text("SELECT epoch FROM research_integrity_epoch"))
        await db_session.execute(sa.text("UPDATE research_events SET revision=2 WHERE id=:id"), {"id": fixture["event"]["id"]})
        await db_session.commit()
        with pytest.raises(DBAPIError, match="could not serialize"):
            await stale.execute(sa.text(f"SELECT public.{LOCK_FUNCTION}()"))
        await stale.rollback()


async def test_freeze_race_then_pins_close_after_commit(db_session):
    fixture = await seed(db_session)
    await db_session.commit()
    capsule, rows = await release(db_session, fixture)
    await flush_constraints(db_session)
    async with get_session_factory()() as other:
        with pytest.raises(DBAPIError, match="research_integrity_busy"):
            await asyncio.wait_for(other.execute(sa.text("UPDATE research_events SET revision=2 WHERE id=:id"),
                                                {"id": fixture["event"]["id"]}), timeout=2)
        await other.rollback()
        await db_session.commit()
        with pytest.raises(DBAPIError, match="frozen_research_row"):
            await other.execute(sa.text("UPDATE research_events SET revision=2 WHERE id=:id"), {"id": fixture["event"]["id"]})
        await other.rollback()
        with pytest.raises(DBAPIError, match="research_release_assembly_closed"):
            row = rows[0]
            await add(other, "research_release_pins", id=uuid4(), release_id=capsule["id"], table_name=row["table"],
                      row_id=row["row_id"], row_data=row["data"], row_sha256=row["row_sha256"])
        await other.rollback()


async def notice(db, fixture, capsule):
    return await add(db, "research_release_notices", id=uuid4(), release_id=capsule["id"], kind="withdrawn",
                     review_artifact_id=fixture["artifact"]["id"], review_sha256="a" * 64,
                     reason_code="synthetic_withdrawal", record_sha256="b" * 64)


@pytest.mark.parametrize("table_name", TABLE_ORDER[1:])
@pytest.mark.parametrize("operation", ["update", "delete", "truncate"])
async def test_capsule_history_is_append_only_even_for_direct_sql(db_session, table_name, operation):
    fixture = await seed(db_session)
    capsule, _ = await release(db_session, fixture)
    await notice(db_session, fixture, capsule)
    await flush_constraints(db_session)
    query = {"update": f"UPDATE public.{table_name} SET id=id", "delete": f"DELETE FROM public.{table_name}",
             "truncate": f"TRUNCATE public.{table_name} CASCADE"}[operation]
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(query))


async def test_post_release_notice_freezes_exact_review_without_rewriting_release(db_session):
    fixture = await seed(db_session)
    capsule, _ = await release(db_session, fixture)
    await flush_constraints(db_session)
    await db_session.commit()
    before = await capture(db_session, "research_releases", capsule["id"])
    await notice(db_session, fixture, capsule)
    after = await capture(db_session, "research_releases", capsule["id"])
    assert before == after
    with pytest.raises(DBAPIError, match="frozen_research_notice_review|frozen_research_row"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("UPDATE evidence_artifacts SET source='changed' WHERE id=:id"),
                                     {"id": fixture["artifact"]["id"]})


async def test_duplicate_manifest_entry_cannot_mask_an_omitted_pin(db_session):
    fixture = await seed(db_session)
    with pytest.raises(IntegrityError, match="manifest_rows_invalid|research_pin_not_declared"):
        async with db_session.begin_nested():
            data = await capture(db_session, "ml_dataset_snapshots", fixture["dataset"]["id"])
            entry = {"table": "ml_dataset_snapshots", "row_id": str(fixture["dataset"]["id"]), "data": data, "row_sha256": sha(data)}
            await release(db_session, fixture, [("ml_dataset_snapshots", fixture["dataset"]["id"]),
                                               ("research_events", fixture["event"]["id"])],
                          manifest_overrides={"rows": [entry, entry]})
            await flush_constraints(db_session)


async def test_canonical_truncate_cannot_erase_frozen_science(db_session):
    fixture = await seed(db_session)
    await release(db_session, fixture)
    await flush_constraints(db_session)
    with pytest.raises(DBAPIError, match="frozen_research_table_truncate|append-only"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("TRUNCATE public.material_states CASCADE"))


async def test_late_same_transaction_pin_cannot_extend_already_checked_capsule(db_session):
    fixture = await seed(db_session)
    capsule, _ = await release(db_session, fixture)
    await flush_constraints(db_session)
    unrelated = await add(db_session, "materials", id="unrelated-" + uuid4().hex, formula="Nb", formula_normalized="Nb")
    data = await capture(db_session, "materials", unrelated["id"])
    with pytest.raises(IntegrityError, match="research_pin_not_declared"):
        async with db_session.begin_nested():
            await add(db_session, "research_release_pins", id=uuid4(), release_id=capsule["id"], table_name="materials",
                      row_id=unrelated["id"], row_data=data, row_sha256=sha(data))


@pytest.mark.parametrize("missing", ["owned", "fk", "example"])
async def test_direct_sql_rejects_incomplete_actual_closure(db_session, missing):
    fixture = await seed(db_session)
    name, row_id = {"owned": ("event_properties", fixture["prop"]["id"]),
                    "fk": ("material_states", fixture["state"]["id"]),
                    "example": ("ml_examples", fixture["example"]["id"])}[missing]
    with pytest.raises(IntegrityError, match="missing_owned_dependency|missing_fk_dependency|dataset_count_mismatch"):
        async with db_session.begin_nested():
            await release(db_session, fixture, omit=((name, str(row_id)),))
            await flush_constraints(db_session)


@pytest.mark.parametrize("mode", ["wrong_count", "empty"])
async def test_direct_sql_rejects_empty_or_wrong_declared_dataset_count(db_session, mode):
    fixture = await seed(db_session)
    if mode == "empty":
        await db_session.execute(sa.text("DELETE FROM ml_examples WHERE id=:id"), {"id": fixture["example"]["id"]})
    await db_session.execute(sa.text("UPDATE ml_dataset_snapshots SET row_count=:count WHERE id=:id"),
                             {"id": fixture["dataset"]["id"], "count": 0 if mode == "empty" else 2})
    with pytest.raises(IntegrityError, match="dataset_count_mismatch"):
        async with db_session.begin_nested():
            await release(db_session, fixture)
            await flush_constraints(db_session)


async def test_direct_release_insert_cannot_bypass_required_serializable_snapshot(db_session):
    fixture = await seed(db_session)
    await db_session.commit()
    with pytest.raises(DBAPIError, match="requires_serializable"):
        await add(db_session, "research_releases", id=uuid4(), dataset_snapshot_id=fixture["dataset"]["id"],
                  manifest={"rows": []}, manifest_sha256="a" * 64, bundle_sha256="b" * 64, closure_policy_version="synthetic")
    await db_session.rollback()


@pytest.mark.parametrize("inventory", ["missing", "unsupported", "oversized", "invalid_shape", "valid"])
async def test_direct_sql_receipt_inventory_cannot_omit_or_invent_dependencies(db_session, inventory):
    fixture = await seed(db_session)
    snapshot = await add(db_session, "research_import_snapshots", id=uuid4(), export_manifest_sha256=uuid4().hex * 2,
                         export_manifest={}, dataset_version="synthetic", site_git_sha="a" * 40,
                         database_watermark=datetime.now(UTC), source_alembic_revision="0054_research_release", schema_version="1",
                         paper_count=0, material_count=0, chunk_count=0, input_record_count=0, license_manifest_sha256="b" * 64,
                         record_sha256="c" * 64)
    members = {"missing": {"research_import_memberships": [str(uuid4())]},
               "unsupported": {"users": []}, "oversized": {"research_import_snapshots": [str(snapshot["id"])] * 1001},
               "invalid_shape": {"research_import_snapshots": str(snapshot["id"])},
               "valid": {"research_import_snapshots": [str(snapshot["id"])]}}[inventory]
    receipt = await add(db_session, "research_import_receipts", id=uuid4(), snapshot_id=snapshot["id"],
                        plan_manifest_sha256=uuid4().hex * 2, loader_version="synthetic", approval_artifact_id=fixture["artifact"]["id"],
                        approval_artifact_sha256="d" * 64, selection_manifest={"row_ids": members}, accounting={},
                        completed_at=datetime.now(UTC), record_sha256="e" * 64)
    if inventory == "valid":
        await release(db_session, fixture, [("research_import_receipts", receipt["id"])], expand_receipts=False)
        await flush_constraints(db_session)
        return
    with pytest.raises(IntegrityError, match="receipt_inventory|missing_receipt_dependency"):
        async with db_session.begin_nested():
            await release(db_session, fixture, [("research_import_receipts", receipt["id"])], expand_receipts=False)
            await flush_constraints(db_session)


async def test_cross_material_composite_reference_cannot_be_frozen(db_session):
    fixture, other = await seed(db_session), await seed(db_session)
    with pytest.raises(IntegrityError, match="fk_rv2_event_state_material"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("UPDATE research_events SET state_id=:state WHERE id=:event"),
                                     {"state": other["state"]["id"], "event": fixture["event"]["id"]})
    await release(db_session, fixture)
    await flush_constraints(db_session)


async def test_forged_manifest_and_matching_pin_still_require_actual_canonical_row(db_session):
    fixture = await seed(db_session)
    data = await capture(db_session, "ml_dataset_snapshots", fixture["dataset"]["id"])
    data["version"] = "forged"
    row = {"table": "ml_dataset_snapshots", "row_id": str(fixture["dataset"]["id"]), "data": data, "row_sha256": sha(data)}
    manifest = {"rows": [row]}
    with pytest.raises(IntegrityError, match="research_pin_canonical_row_mismatch"):
        async with db_session.begin_nested():
            capsule = await add(db_session, "research_releases", id=uuid4(), dataset_snapshot_id=fixture["dataset"]["id"],
                                manifest=manifest, manifest_sha256=sha(manifest), bundle_sha256="f" * 64,
                                closure_policy_version="synthetic")
            await add(db_session, "research_release_pins", id=uuid4(), release_id=capsule["id"], table_name=row["table"],
                      row_id=row["row_id"], row_data=data, row_sha256=row["row_sha256"])


async def test_concurrent_catalogue_change_retries_after_fence_and_historical_pin_unchanged(db_session):
    fixture = await seed(db_session)
    await db_session.commit()
    await db_session.execute(sa.text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
    await db_session.execute(sa.text(f"SELECT public.{LOCK_FUNCTION}()"))
    capsule, rows = await release(db_session, fixture, [("materials", fixture["material"]["id"])])
    historical_material = next(row["data"] for row in rows
                               if row["table"] == "materials" and row["row_id"] == fixture["material"]["id"])
    capsule_before = await capture(db_session, "research_releases", capsule["id"])
    pin_query = sa.text("SELECT to_jsonb(p) FROM research_release_pins p WHERE release_id=:id ORDER BY id")
    pins_before = (await db_session.execute(pin_query, {"id": capsule["id"]})).scalars().all()
    async with get_session_factory()() as other:
        # 0067 added a catalogue-writer fence so an old review/capsule snapshot
        # cannot race a catalogue edit. This is a transient whole-transaction
        # retry, not a permanent freeze of mutable catalogue rows.
        with pytest.raises(DBAPIError, match="research_integrity_busy_retry_transaction") as error:
            await asyncio.wait_for(other.execute(sa.text("UPDATE materials SET formula='Nb' WHERE id=:id"),
                                                 {"id": fixture["material"]["id"]}), timeout=2)
        assert error.value.orig.sqlstate == "55P03"
        await other.rollback()
        assert (await capture(other, "materials", fixture["material"]["id"]))["formula"] == "MgB2"
        await other.rollback()
    assert (await capture(db_session, "materials", fixture["material"]["id"]))["formula"] == "MgB2"
    await db_session.commit()
    # The successful edit runs in a genuinely fresh transaction after the
    # capsule's outer commit releases the integrity fence.
    async with get_session_factory()() as other:
        await asyncio.wait_for(other.execute(sa.text("UPDATE materials SET formula='Nb' WHERE id=:id"),
                                            {"id": fixture["material"]["id"]}), timeout=2)
        await other.commit()
    await db_session.execute(sa.text("SET LOCAL TimeZone='UTC'"))
    current = await capture(db_session, "materials", fixture["material"]["id"])
    pinned = (await db_session.execute(sa.text("SELECT row_data FROM research_release_pins WHERE release_id=:id AND table_name='materials'"),
                                       {"id": capsule["id"]})).scalar_one()
    assert current["formula"] == "Nb"
    assert pinned == historical_material
    assert pinned["formula"] == "MgB2"
    assert await capture(db_session, "research_releases", capsule["id"]) == capsule_before
    assert (await db_session.execute(pin_query, {"id": capsule["id"]})).scalars().all() == pins_before


async def test_preflight_rejects_existing_cycle_without_rewriting_rows(db_session):
    first, second = await seed(db_session), await seed(db_session)
    # This owned disposable fixture deliberately represents data from before
    # 0054. Ordinary DML after migration never receives such a bypass.
    with pytest.raises(IntegrityError, match="existing_research_dependency_cycle"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("ALTER TABLE public.event_evidence DISABLE TRIGGER rf54_cycle"))
            await edge(db_session, first, second)
            await edge(db_session, second, first)
            await db_session.execute(sa.text("SELECT public.sclib_research_cycle_preflight_v1()"))
    with pytest.raises(IntegrityError, match="research_dependency_cycle"):
        async with db_session.begin_nested():
            await edge(db_session, first, second)
            await edge(db_session, second, first)
