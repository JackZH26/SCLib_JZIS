"""Native SQL boundary tests; synthetic writer assertions are not RPS review.

This small inventory isolates database governance. The service/HTTP suite owns
actual complete RPS/public-bundle recomputation and source-byte admission.
"""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base, get_session_factory
from models.research_distribution_v1 import HISTORY_TABLES, IDENTITY_FIELDS, TABLE_ORDER
from services.research_audit_retention import AUDIT_USER_FK_CONSTRAINTS, AUDIT_USER_REFERENCES
from services.research_release_manifest import canonical, digest
from services.research_release_spec import SPEC
from tests.test_research_freeze import db_session as db_session
from tests.test_research_freeze import state
from tests.test_research_publication import actors


async def add(db, name, /, **values):
    table = Base.metadata.tables[name]
    return (await db.execute(table.insert().values(**values).returning(table))).mappings().one()


async def projection(db, table, identifier):
    return await db.scalar(sa.text("SELECT public.sclib_research_distribution_projection_v1(:table,:id)"),
                           {"table": table, "id": str(identifier)})


def actor(people, role):
    return {"actor_user_id": people[role], "actor_grant_id": people["grants"][role], "request_key": uuid4().hex}


async def package_values(db, *, target="evidence_artifacts"):
    people = await actors(db)
    if target == "evidence_artifacts":
        document = {"synthetic": "SQL-only writer witness"}
        source = await add(db, target, kind="policy", schema_version="rps-artifact-record/1.0.0", source="synthetic-test",
            record_sha256=digest(document), bytes_sha256=digest(document), hash_status="verified", access="restricted")
    elif target == "papers":
        source = await add(db, target, id="rd63-paper:" + uuid4().hex, source="arxiv",
            title="Synthetic SQL-only writer witness", authors=[], abstract="Synthetic source", status="published")
    else:
        raise AssertionError(target)
    raw = await projection(db, target, source["id"])
    row_sha = digest(raw)
    dependency_id = digest({"version": "research-distribution-dependency/1.0.0", "table": target,
                            "row_id": str(source["id"]), "row_sha256": row_sha})
    dependency = {"dependency_id": dependency_id, "table": target, "row_id": str(source["id"]),
        "row_sha256": row_sha, "record_sha256": raw.get("record_sha256"),
        "bytes_sha256": raw.get("bytes_sha256") if target == "evidence_artifacts" else None,
        "projection": raw, "capsule_manifest_sha256s": []}
    extra_dependencies = []
    root_row = raw
    if target == "papers":
        document = {"synthetic": "SQL-only internal witness"}
        root_artifact = await add(db, "evidence_artifacts", kind="policy", schema_version="rps-artifact-record/1.0.0",
            source="synthetic-test", record_sha256=digest(document), bytes_sha256=digest(document),
            hash_status="verified", access="restricted")
        root_row = await projection(db, "evidence_artifacts", root_artifact["id"])
        root_sha = digest(root_row)
        root_dependency_id = digest({"version": "research-distribution-dependency/1.0.0", "table": "evidence_artifacts",
                                     "row_id": str(root_artifact["id"]), "row_sha256": root_sha})
        extra_dependencies.append({"dependency_id": root_dependency_id, "table": "evidence_artifacts",
            "row_id": str(root_artifact["id"]), "row_sha256": root_sha, "record_sha256": root_row["record_sha256"],
            "bytes_sha256": root_row["bytes_sha256"], "projection": root_row, "capsule_manifest_sha256s": []})
    binding = {"artifact_id": "synthetic-sql-witness", "artifact_sha256": "a" * 64, "artifact_kind": "rubric",
        "root": {"kind": "internal_artifact", "evidence_artifact_id": root_row["id"],
                 "artifact_kind": "policy", "record_sha256": root_row["record_sha256"],
                 "bytes_sha256": root_row["bytes_sha256"]}, "identity": None}
    # Opaque package pins below are trusted-writer declarations for SQL tests,
    # not proof that a full public package was verified or can be served.
    bindings = {"version": "research-distribution-bindings/1.0.0", "release_id": "synthetic-" + uuid4().hex,
        "release_manifest_sha256": "1" * 64, "public_bundle_sha256": "2" * 64, "bindings": [binding]}
    inventory = {"version": "research-distribution-inventory/1.0.0",
        **{key: bindings[key] for key in ("release_id", "release_manifest_sha256", "public_bundle_sha256")},
        "bindings_sha256": digest(bindings), "artifact_bindings": [{**binding,
            "dependency_ids": sorted([dependency_id, *(d["dependency_id"] for d in extra_dependencies)])}],
        "dependencies": sorted([dependency, *extra_dependencies], key=lambda d: d["dependency_id"]),
        "scientific_acceptance": False, "ml_training_approved": False,
        "source_rights_verified": False, "current_authorization_checked": False,
        "database_observation_authenticated": False}
    values = {"id": uuid4(), **{key: bindings[key] for key in ("release_id", "release_manifest_sha256", "public_bundle_sha256")},
        "binding_manifest": canonical(bindings).decode(), "bindings_sha256": digest(bindings),
        "inventory_json": canonical(inventory).decode(), "inventory_sha256": digest(inventory), **actor(people, "curator")}
    return {"people": people, "source": source, "dependency": dependency, "values": values,
            "bindings": bindings, "inventory": inventory, "target": target, "extra_dependencies": extra_dependencies}


async def insert_dependency(db, context, **overrides):
    d = context["dependency"]
    return await add(db, "research_distribution_dependencies", package_id=context["values"]["id"],
        **{"dependency_id": d["dependency_id"], "table_name": d["table"], "row_id": d["row_id"],
           "row_sha256": d["row_sha256"], "source_record_sha256": d["record_sha256"],
           "bytes_sha256": d["bytes_sha256"], "projection_json": canonical(d["projection"]).decode(),
           "capsule_manifest_sha256s": d["capsule_manifest_sha256s"], **overrides})


async def registered(db, *, target="evidence_artifacts"):
    context = await package_values(db, target=target)
    context["package"] = await add(db, "research_distribution_packages", **context["values"])
    context["dependency_row"] = await insert_dependency(db, context)
    for dependency in context["extra_dependencies"]:
        await insert_dependency(db, {**context, "dependency": dependency})
    await db.execute(sa.text("SET CONSTRAINTS rd63_complete IMMEDIATE"))
    await db.execute(sa.text("SET CONSTRAINTS rd63_complete DEFERRED"))
    return context


async def permission(db, context, **overrides):
    p, d = context["package"], context["dependency"]
    document = {"version": "rps-distribution-rights/1.0.0", "scope": "rps_structured_bundle",
        "package_id": str(p["id"]), "inventory_sha256": p["inventory_sha256"], "dependency_id": d["dependency_id"],
        "dependency_row_sha256": d["row_sha256"], "public_bundle_sha256": p["public_bundle_sha256"],
        "license_code": "permission-on-file", "basis_code": "synthetic_assertion",
        "distribution_permitted": True, "scientific_acceptance": False, "ml_training_approved": False}
    rights = await add(db, "evidence_artifacts", kind="review", schema_version=document["version"],
        source="synthetic-test", record_sha256=digest(document), bytes_sha256=digest(document), hash_status="verified",
        access="restricted", metadata={"distribution_rights": document})
    raw = await projection(db, "evidence_artifacts", rights["id"])
    values = {"package_id": p["id"], "dependency_id": d["dependency_id"], "decision": "allow",
        "license_code": document["license_code"], "basis_code": document["basis_code"],
        "rights_artifact_id": rights["id"], "rights_row_sha256": digest(raw), "rights_record_sha256": rights["record_sha256"],
        "rights_bytes_sha256": rights["bytes_sha256"], "rights_projection_json": canonical(raw).decode(),
        "reason_code": "synthetic_assertion", **actor(context["people"], "reviewer"), **overrides}
    return await add(db, "research_distribution_permissions", **values)


async def review(db, context, allowed, **overrides):
    receipts = [{"dependency_id": allowed["dependency_id"], "permission_id": str(allowed["id"]),
                 "permission_sha256": allowed["record_sha256"]}]
    return await add(db, "research_distribution_reviews", **{"package_id": context["package"]["id"],
        "inventory_sha256": context["package"]["inventory_sha256"], "permission_manifest": canonical(receipts).decode(),
        "permission_manifest_sha256": digest(receipts), "disclosure_approved": True,
        "reason_code": "synthetic_disclosure", **actor(context["people"], "reviewer"), **overrides})


async def publish(db, context, reviewed, **overrides):
    return await add(db, "research_distribution_actions", **{"package_id": context["package"]["id"],
        "review_id": reviewed["id"], "inventory_sha256": context["package"]["inventory_sha256"], "kind": "publish",
        "reason_code": "synthetic_publication", **actor(context["people"], "publisher"), **overrides})


def test_six_additive_tables_and_sparse_target_fks_cover_every_frozen_identity():
    assert len(TABLE_ORDER) == 6 and set(TABLE_ORDER) <= set(Base.metadata.tables)
    deps = Base.metadata.tables["research_distribution_dependencies"]
    for table in SPEC:
        column = deps.c["target_" + table]
        assert str(next(iter(column.foreign_keys)).column) == table + "." + IDENTITY_FIELDS[table]
    for name in ("packages", "permissions", "reviews", "actions"):
        table = "research_distribution_" + name
        assert (table, "actor_user_id") in AUDIT_USER_REFERENCES
        assert table + "_actor_user_id_fkey" in AUDIT_USER_FK_CONSTRAINTS


async def test_atomic_inventory_exact_fk_and_db_generated_hashes(db_session):
    context = await registered(db_session)
    p, d = context["package"], context["dependency_row"]
    assert p["binding_count"] == p["dependency_count"] == 1
    assert d["target_evidence_artifacts"] == context["source"]["id"]
    assert all(d["target_" + table] is None for table in SPEC if table != "evidence_artifacts")
    for name, row in (("research_distribution_packages", p), ("research_distribution_dependencies", d)):
        assert await db_session.scalar(sa.text(f"SELECT record_sha256=public.sclib_research_distribution_record_hash_v1(to_jsonb(t)) FROM {name} t WHERE id=:id"), {"id": row["id"]})


async def test_incomplete_registration_cannot_cross_constraint_boundary(db_session):
    context = await package_values(db_session)
    with pytest.raises(DBAPIError, match="incomplete_atomic_registration"):
        async with db_session.begin_nested():
            await add(db_session, "research_distribution_packages", **context["values"])
            await db_session.execute(sa.text("SET CONSTRAINTS rd63_complete IMMEDIATE"))


@pytest.mark.parametrize("mutation", ["missing", "extra", "authority", "bundle", "hash"])
async def test_inventory_mutations_fail_even_after_rehashing(db_session, mutation):
    context = await package_values(db_session)
    value = deepcopy(context["inventory"])
    if mutation == "missing": del value["source_rights_verified"]
    elif mutation == "extra": value["hidden_raw_field"] = "SYNTHETIC-PRIVATE-CANARY"
    elif mutation == "authority": value["ml_training_approved"] = True
    elif mutation == "bundle": value["public_bundle_sha256"] = "f" * 64
    else: value["bindings_sha256"] = "e" * 64
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await add(db_session, "research_distribution_packages", **{
                **context["values"], "inventory_json": canonical(value).decode(), "inventory_sha256": digest(value)})


@pytest.mark.parametrize("change", ["projection", "row_hash", "record_hash", "bytes_hash", "dependency_id", "target_fk", "capsule"])
async def test_dependency_cannot_substitute_projections_or_target_foreign_keys(db_session, change):
    context = await package_values(db_session)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await add(db_session, "research_distribution_packages", **context["values"])
            fields = {"projection": {"projection_json": "{}"}, "row_hash": {"row_sha256": "d" * 64},
                "record_hash": {"source_record_sha256": "d" * 64}, "bytes_hash": {"bytes_sha256": "d" * 64},
                "dependency_id": {"dependency_id": "d" * 64}, "target_fk": {"target_evidence_artifacts": context["source"]["id"]},
                "capsule": {"capsule_manifest_sha256s": ["d" * 64]}}[change]
            await insert_dependency(db_session, context, **fields)


@pytest.mark.parametrize("capsules", [[None], [1], ["x"], ["a" * 64, "a" * 64], ["b" * 64, "a" * 64]])
async def test_capsule_list_is_closed_sorted_and_unique_before_pin_resolution(db_session, capsules):
    context = await package_values(db_session)
    with pytest.raises(DBAPIError, match="closed_capsule_inventory"):
        async with db_session.begin_nested():
            await add(db_session, "research_distribution_packages", **context["values"])
            await insert_dependency(db_session, context, capsule_manifest_sha256s=capsules)


@pytest.mark.parametrize("change", ["duplicate_artifact", "duplicate_dependency", "evidence_internal_root", "missing_identity"])
async def test_exact_root_binding_shape_cannot_be_laundered_by_rehashing(db_session, change):
    context = await package_values(db_session)
    bindings, inventory = deepcopy(context["bindings"]), deepcopy(context["inventory"])
    if change == "duplicate_artifact":
        second = {**bindings["bindings"][0], "artifact_id": "second-synthetic-artifact"}
        bindings["bindings"].append(second)
        inventory["artifact_bindings"].append(deepcopy(inventory["artifact_bindings"][0]))
    elif change == "duplicate_dependency":
        inventory["artifact_bindings"][0]["dependency_ids"] *= 2
    else:
        kind = "evidence" if change == "evidence_internal_root" else "material"
        bindings["bindings"][0]["artifact_kind"] = kind
        inventory["artifact_bindings"][0]["artifact_kind"] = kind
    inventory["bindings_sha256"] = digest(bindings)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await add(db_session, "research_distribution_packages", **{**context["values"],
                "binding_manifest": canonical(bindings).decode(), "bindings_sha256": digest(bindings),
                "inventory_json": canonical(inventory).decode(), "inventory_sha256": digest(inventory)})


@pytest.mark.parametrize("table", HISTORY_TABLES)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
async def test_history_is_append_only(db_session, table, operation):
    context = await registered(db_session)
    allowed = await permission(db_session, context)
    reviewed = await review(db_session, context, allowed)
    await publish(db_session, context, reviewed)
    sql = f"{operation} {table}" if operation != "UPDATE" else f"UPDATE {table} SET record_sha256=record_sha256"
    if operation == "DELETE": sql = f"DELETE FROM {table}"
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(sa.text(sql))


async def test_permissions_review_and_third_actor_are_real_grant_bound(db_session):
    context = await registered(db_session)
    allowed = await permission(db_session, context)
    with pytest.raises(DBAPIError, match="independent_exact_review"):
        async with db_session.begin_nested():
            people = context["people"]
            from services.research_publication import grant_role
            await grant_role(db_session, actor_user_id=people["admin"], user_id=people["curator"],
                role="reviewer", reason_code="synthetic_dual_role", dry_run=False)
            grant = await db_session.scalar(sa.text("SELECT id FROM research_role_grants WHERE user_id=:id AND role='reviewer'"), {"id": people["curator"]})
            await review(db_session, context, allowed, actor_user_id=people["curator"], actor_grant_id=grant)
    reviewed = await review(db_session, context, allowed)
    assert reviewed["scientific_acceptance"] is False and reviewed["ml_training_approved"] is False
    await publish(db_session, context, reviewed)


@pytest.mark.parametrize("change", ["dependency", "rights", "role", "permission"])
async def test_warmed_approved_review_cannot_publish_after_currentness_drift(db_session, change):
    context = await registered(db_session)
    allowed = await permission(db_session, context)
    reviewed = await review(db_session, context, allowed)
    if change in {"dependency", "rights"}:
        identifier = context["source"]["id"] if change == "dependency" else allowed["rights_artifact_id"]
        await db_session.execute(sa.text("UPDATE evidence_artifacts SET source='synthetic-changed' WHERE id=:id"), {"id": identifier})
    elif change == "role":
        from services.research_publication import revoke_role
        await revoke_role(db_session, actor_user_id=context["people"]["admin"],
            grant_id=context["people"]["grants"]["reviewer"], reason_code="synthetic_revoke", dry_run=False)
    else:
        await revoke(db_session, context, allowed)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await publish(db_session, context, reviewed)


async def revoke(db, context, prior, **overrides):
    return await add(db, "research_distribution_permissions", **{
        **{key: prior[key] for key in ("package_id", "dependency_id", "license_code", "rights_artifact_id", "rights_row_sha256",
            "rights_record_sha256", "rights_bytes_sha256", "rights_projection_json")},
        "decision": "revoke", "supersedes_id": prior["id"], "basis_code": "synthetic_revoke", "reason_code": "synthetic_revoke",
        **actor(context["people"], "reviewer"), **overrides})


async def test_revocation_and_withdrawal_survive_changed_source_and_rights(db_session):
    context = await registered(db_session)
    allowed = await permission(db_session, context)
    reviewed = await review(db_session, context, allowed)
    await publish(db_session, context, reviewed)
    await db_session.execute(sa.text("UPDATE evidence_artifacts SET source='synthetic-changed' WHERE id IN (:one,:two)"),
                             {"one": context["source"]["id"], "two": allowed["rights_artifact_id"]})
    await revoke(db_session, context, allowed)
    await publish(db_session, context, reviewed, kind="withdraw")


async def test_parent_delete_is_foreign_key_restricted(db_session):
    context = await registered(db_session)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("DELETE FROM evidence_artifacts WHERE id=:id"), {"id": context["source"]["id"]})


async def test_shared_fence_requires_serializable():
    async with get_session_factory()() as db:
        with pytest.raises(DBAPIError, match="requires_serializable"):
            await db.execute(sa.text("SELECT public.sclib_research_distribution_lock_v1()"))


async def test_paper_lifecycle_aba_stays_held_in_sql_currentness(db_session):
    context = await registered(db_session, target="papers")
    p = context["source"]
    await db_session.execute(sa.text("UPDATE papers SET status='corrected' WHERE id=:id"), {"id": p["id"]})
    await db_session.execute(sa.text("UPDATE papers SET status='published' WHERE id=:id"), {"id": p["id"]})
    assert await projection(db_session, "papers", p["id"]) == context["dependency"]["projection"]
    with pytest.raises(DBAPIError, match="source_lifecycle_hold"):
        async with db_session.begin_nested():
            await db_session.execute(sa.text("SELECT public.sclib_research_distribution_current_v1(:id)"), {"id": context["package"]["id"]})


async def test_savepoint_rollback_restores_entire_database(db_session):
    before = await state(db_session)
    transaction = await db_session.begin_nested()
    context = await registered(db_session)
    await permission(db_session, context)
    await transaction.rollback()
    assert await state(db_session) == before
