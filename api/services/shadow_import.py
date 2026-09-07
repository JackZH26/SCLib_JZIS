"""Bounded internal shadow loader: no canonical claims, releases or public writes.

The offline verifier must run first. Its complete payload is pinned by a separate
internal-processing review artifact; a checksum or lookalike dictionary is not
authorization. Callers own a clean SERIALIZABLE transaction and its final commit.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, date, datetime
from uuid import UUID, uuid5

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from models.db import RESEARCH_IMPORT_TABLES, Base, Material
from services.claim_outcomes import negative_outcome_issues
from services.material_visibility import normalize_source_status
from services.material_visibility_adapter import prepare_material_views
from services.temporal_provenance import utc_datetime

LOADER_VERSION = "shadow-research-loader/1.0.0"
REVIEW_VERSION = "shadow-import-processing-review/1.0.0"
VERIFIER_VERSION = "verified-shadow-import/1.0.0"
MAX_RECORDS = 1000
_NAMESPACE = UUID("71064629-85fc-4146-8853-067305841300")
_LEGACY_CLAIM_NAMESPACE = UUID("ce9da7e7-6db1-4ca1-bb9b-9b1a3ecf2c6e")
_LOCK_KEY = 530017026
_DERIVED = frozenset({"result_classification", "pressure_semantics", "property_evidence",
                      "anomaly_review", "visibility", "structure_evidence", "ingestion_capture", "temporal_provenance"})
_DISPOSITIONS = ("reused", "inserted", "revised", "quarantined", "failed")
_CLAIM_FIELDS = frozenset({
    "id", "material_id", "paper_id", "work_id", "source_snapshot_id", "chunk_id", "property_type",
    "evidence_role", "result_status", "value_relation", "value_kelvin", "value_lower_kelvin", "value_upper_kelvin",
    "tc_definition", "pressure_state", "pressure_gpa", "minimum_temperature_k", "magnetic_field_t",
    "measurement_method", "sample_form", "structure_phase_raw", "doping_raw", "sample_label", "source_kind",
    "source_locator", "extraction_confidence", "relation_confidence", "validity_status", "raw_record",
    "extraction_metadata", "source_record_hash", "semantic_fingerprint", "duplicate_cluster_id", "available_at",
    "extractor_version", "ingestion_run_id",
})


class ShadowImportError(ValueError):
    """Unsafe/stale input, approval or immutable ledger conflict."""


def _json(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        instant = utc_datetime(value)
        if instant is None:
            raise ShadowImportError("timezone-aware timestamp required")
        return instant.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def digest(value):
    return hashlib.sha256(json.dumps(_json(value), sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _id(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ShadowImportError("invalid UUID") from exc


def _raw_identity(raw):
    def normalize(item):
        if isinstance(item, float) and item == 0:
            return 0.0
        if isinstance(item, dict):
            return {key: normalize(value) for key, value in item.items()}
        if isinstance(item, list):
            return [normalize(value) for value in item]
        return item
    return normalize({key: value for key, value in raw.items() if key not in _DERIVED})


def _records(value):
    """Decode the legacy field for iteration without replacing captured bytes."""
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ShadowImportError("duplicate key in encoded legacy records")
            result[key] = item
        return result
    def invalid(_):
        raise ShadowImportError("nonfinite encoded legacy records")
    if isinstance(value, str):
        value = json.loads(value, object_pairs_hook=pairs, parse_constant=invalid)
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_RECORDS or any(not isinstance(row, dict) for row in value):
        raise ShadowImportError("invalid or over-budget legacy records")
    return value


def _sealed(row):
    return {**row, "record_sha256": digest(row)}


def _intact(row):
    return digest({key: value for key, value in row.items()
                   if key not in {"created_at", "completed_at", "record_sha256"}}) == row["record_sha256"]


def _validated(verified):
    if not isinstance(verified, dict) or verified.get("version") != VERIFIER_VERSION:
        raise ShadowImportError("verified offline bundle required")
    encoded = json.dumps(verified, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode()) > 64 * 1024 * 1024:
        raise ShadowImportError("verified payload exceeds canary byte limit")
    if digest({key: value for key, value in verified.items() if key != "payload_sha256"}) != verified.get("payload_sha256"):
        raise ShadowImportError("verified payload digest mismatch")
    if verified.get("failures", []) or verified["parity_report"].get("gate_status") != "pass":
        raise ShadowImportError("unresolved offline parity or input failures")
    if any(not isinstance(verified.get(key), list) for key in ("materials", "papers", "claims", "paper_work_map")):
        raise ShadowImportError("invalid verified row arrays")
    if len(verified["materials"]) > MAX_RECORDS or len(verified["papers"]) > 2000 or len(verified["claims"]) > MAX_RECORDS:
        raise ShadowImportError("verified bundle exceeds canary row limit")
    count = sum(len(_records(row["records"])) for row in verified["materials"])
    if count > MAX_RECORDS or count != verified["source_manifest"]["counts"]["material_records"]:
        raise ShadowImportError("input occurrence accounting mismatch")
    for claim in verified["claims"]:
        if not isinstance(claim, dict) or set(claim) != _CLAIM_FIELDS:
            raise ShadowImportError("unsupported proposed claim fields")
        source_hash = digest({"hash_schema": "sclib-source-record/v1", "material_id": claim["material_id"].strip(),
                              "paper_id": claim["paper_id"], "raw_record": _raw_identity(claim["raw_record"]),
                              "source_locator": claim["source_locator"]})
        if source_hash != claim["source_record_hash"] or uuid5(_LEGACY_CLAIM_NAMESPACE, source_hash) != _id(claim["id"]):
            raise ShadowImportError("original source hash or stable claim identity mismatch")
        if claim["source_snapshot_id"] != verified["source_manifest"]["source_snapshot_id"]:
            raise ShadowImportError("claim source snapshot mismatch")
    return verified


def _interpretation(claim):
    excluded = {"id", "material_id", "paper_id", "work_id", "source_snapshot_id", "raw_record",
                "source_record_hash", "source_locator", "available_at", "ingestion_run_id",
                "event_id", "result_key", "interpretation_revision"}
    payload = {key: value for key, value in claim.items() if key not in excluded}
    payload["extraction_metadata"] = {key: value for key, value in claim["extraction_metadata"].items()
                                       if key not in {"temporal_provenance", "ingestion_capture"}}
    if payload.get("validity_status") == "accepted" or claim.get("available_at") is not None:
        raise ShadowImportError("legacy import cannot confer scientific or temporal acceptance")
    return payload


async def _load(db, name, ids, *, key="id"):
    if not ids:
        return {}
    table = Base.metadata.tables[name]
    return {str(row[key]): dict(row) for row in (await db.execute(
        sa.select(table).where(table.c[key].in_(ids)),
    )).mappings().all()}


async def _isolation(db):
    if db.new or db.dirty or db.deleted:
        raise ShadowImportError("loader requires a clean dedicated session")
    if (await db.execute(sa.text("SHOW transaction_isolation"))).scalar_one() != "serializable":
        raise ShadowImportError("loader requires SERIALIZABLE isolation; caller owns transaction")


async def _claim_shape_issues(db, claims):
    """Use the actual current canonical SQL shape checks without inserting there."""
    if not claims:
        return {}
    checks = sorted((constraint.name, str(constraint.sqltext)) for constraint in
                    Base.metadata.tables["material_claims"].constraints if isinstance(constraint, sa.CheckConstraint))
    expressions = ",".join(f"CASE WHEN ({expression}) IS NOT TRUE THEN '{name}' END" for name, expression in checks)
    query = sa.text(f"SELECT id, array_remove(ARRAY[{expressions}], NULL) AS issues "
                    "FROM jsonb_populate_recordset(NULL::material_claims, CAST(:claims AS jsonb))")
    return {str(row.id): row.issues for row in (await db.execute(query, {
        "claims": json.dumps(claims, allow_nan=False),
    })).all()}


async def _prepare(db, verified):
    """Read current associations/governance and forecast one complete import."""
    v = _validated(verified)
    await _isolation(db)
    claim_by_id = {str(_id(row["id"])): row for row in v["claims"]}
    if len(claim_by_id) != len(v["claims"]):
        raise ShadowImportError("duplicate proposed claim identifiers")
    materials = await _load(db, "materials", [row["id"] for row in v["materials"]])
    papers = await _load(db, "papers", [row["id"] for row in v["papers"]])
    maps = await _load(db, "paper_work_map", list(papers), key="paper_id")
    works = await _load(db, "works", {_id(row["work_id"]) for row in v["claims"] if row.get("work_id")})
    material_orm = (await db.execute(sa.select(Material).where(Material.id.in_(materials)))).scalars().all() if materials else []
    contexts = {ctx.id: ctx for ctx in await prepare_material_views(db, material_orm)}
    source_materials = {row["id"]: row for row in v["materials"]}
    source_papers = {row["id"]: row for row in v["papers"]}
    if len(source_materials) != len(v["materials"]) or len(source_papers) != len(v["papers"]):
        raise ShadowImportError("duplicate exported source identifiers")
    # Bind the entire declared canary capture, including unused papers and
    # zero-record materials, rather than claiming parity only for selected rows.
    for supplied, live, label in ((source_materials, materials, "material"), (source_papers, papers, "paper")):
        if set(supplied) != set(live):
            raise ShadowImportError(f"live {label} capture incomplete")
        for key, row in supplied.items():
            if digest({field: live[key][field] for field in row}) != digest(row):
                raise ShadowImportError(f"live {label} source capture drift")
    raw_by_claim = {key: [] for key in claim_by_id}
    identity_lookup = {}
    for cid, claim in claim_by_id.items():
        lookup = (claim["material_id"], digest(_raw_identity(claim["raw_record"])))
        if lookup in identity_lookup:
            raise ShadowImportError("ambiguous raw occurrence association")
        identity_lookup[lookup] = cid
    for material in v["materials"]:
        for ordinal, raw in enumerate(_records(material["records"])):
            cid = identity_lookup.get((material["id"], digest(_raw_identity(raw))))
            if cid is None:
                raise ShadowImportError("input record missing exact proposed claim")
            raw_by_claim[cid].append({"record_ordinal": ordinal, "raw_record": raw})
    if any(not values for values in raw_by_claim.values()):
        raise ShadowImportError("proposed claim has no source occurrence")
    shape_issues = await _claim_shape_issues(db, v["claims"])
    old_occurrences = await _load(db, "research_import_occurrences", [_id(key) for key in claim_by_id])
    revisions_table = RESEARCH_IMPORT_TABLES["research_import_revisions"]
    revisions = (await db.execute(sa.select(revisions_table).where(
        revisions_table.c.occurrence_id.in_([_id(key) for key in claim_by_id]),
    ).order_by(revisions_table.c.revision_number).limit(10001))).mappings().all() if claim_by_id else []
    if len(revisions) > 10000:
        raise ShadowImportError("revision history exceeds bounded canary assessment")
    heads, by_content = {}, {}
    for row in revisions:
        if not _intact(row):
            raise ShadowImportError("stored revision hash mismatch")
        key = str(row["occurrence_id"])
        heads[key] = dict(row)
        by_content[(key, row["mapper_version"], row["interpretation_sha256"])] = dict(row)
    tables = {name: [] for name in RESEARCH_IMPORT_TABLES}
    manifest = v["source_manifest"]
    snapshot_id = _id(manifest["source_snapshot_id"])
    snapshot = _sealed({
        "id": snapshot_id, "export_manifest_sha256": v["source_manifest_sha256"],
        "export_manifest": manifest, "dataset_version": manifest["dataset_version"],
        "site_git_sha": manifest["site_git_sha"], "database_watermark": utc_datetime(manifest["database_watermark"]),
        "source_alembic_revision": manifest["alembic_revision"], "schema_version": manifest["schema_version"],
        "paper_count": manifest["counts"]["papers"], "material_count": manifest["counts"]["materials"],
        "chunk_count": manifest["counts"]["chunks"], "input_record_count": manifest["counts"]["material_records"],
        "license_manifest_sha256": manifest["license_manifest_sha256"], "status": "captured",
    })
    tables["research_import_snapshots"].append(snapshot)
    selected, dispositions = [], []
    for cid, claim in sorted(claim_by_id.items()):
        mid, pid, wid = claim["material_id"], claim["paper_id"], str(claim["work_id"])
        reasons, action = [], "inserted"
        material, paper, mapping, work = materials.get(mid), papers.get(pid), maps.get(pid), works.get(wid)
        if material is None or paper is None or work is None:
            reasons.append("live_material_paper_or_work_missing")
        if not mapping or mapping["review_status"] != "accepted" or str(mapping["work_id"]) != wid:
            reasons.append("live_work_mapping_not_accepted_or_mismatched")
        if material and digest({key: material[key] for key in source_materials[mid]}) != digest(source_materials[mid]):
            reasons.append("live_material_source_drift")
        if paper and (pid not in source_papers or digest({key: paper[key] for key in source_papers[pid]}) != digest(source_papers[pid])):
            reasons.append("live_paper_source_drift")
        reasons.extend(shape_issues.get(cid, []))
        if reasons:
            action = "failed"
        elif (not contexts[mid].visibility["public_catalogue_eligible"] or normalize_source_status(paper["status"]) != "active"
              or normalize_source_status(work["publication_status"]) != "active"
              or claim["validity_status"] in {"retracted", "disputed", "excluded"}):
            action, reasons = "quarantined", ["current_governance_or_source_hold"]
        elif claim["result_status"] == "not_detected" and negative_outcome_issues(claim):
            action, reasons = "quarantined", list(negative_outcome_issues(claim))
        if action not in {"failed", "quarantined"}:
            occurrence = _sealed({
                "id": _id(cid), "legacy_claim_id": _id(cid), "material_id": mid, "paper_id": pid, "work_id": _id(wid),
                "source_record_sha256": claim["source_record_hash"], "raw_record": _raw_identity(claim["raw_record"]),
                "source_locator": claim["source_locator"], "identity_version": "sclib-source-record/v1",
            })
            previous = old_occurrences.get(cid)
            if previous and (not _intact(previous) or any(previous[key] != value for key, value in occurrence.items())):
                raise ShadowImportError("immutable occurrence identity/content mismatch")
            payload = _interpretation(claim)
            policy = v["plan_manifest"]["claim_mapper_version"]
            interpretation_hash = digest(payload)
            existing = by_content.get((cid, policy, interpretation_hash))
            head = heads.get(cid)
            if existing:
                revision, action = {key: value for key, value in existing.items() if key != "created_at"}, "reused"
            else:
                action = "revised" if head else "inserted"
                number = head["revision_number"] + 1 if head else 1
                predecessor = head["id"] if head else None
                rid = uuid5(_NAMESPACE, f"revision:{cid}:{policy}:{interpretation_hash}:{predecessor}")
                revision = _sealed({"id": rid, "occurrence_id": _id(cid), "revision_number": number,
                    "supersedes_id": predecessor, "supersedes_revision_number": number - 1 if head else None,
                    "mapper_version": policy, "interpretation_sha256": interpretation_hash, "payload": payload,
                    "review_status": "pending", "scientific_acceptance": False})
            membership = _sealed({"id": uuid5(_NAMESPACE, f"membership:{snapshot_id}:{cid}:{revision['id']}"),
                "snapshot_id": snapshot_id, "occurrence_id": _id(cid), "revision_id": revision["id"],
                "source_record_sha256": claim["source_record_hash"], "raw_records": raw_by_claim[cid]})
            tables["research_import_occurrences"].append(occurrence)
            tables["research_import_revisions"].append(revision)
            tables["research_import_memberships"].append(membership)
            selected.append({"occurrence_id": cid, "revision_id": str(revision["id"]),
                             "membership_id": str(membership["id"]), "interpretation_sha256": interpretation_hash})
        for index, raw in enumerate(raw_by_claim[cid]):
            dispositions.append({"material_id": mid, "record_ordinal": raw["record_ordinal"], "occurrence_id": cid,
                "disposition": "reused" if index and action in {"inserted", "revised"} else action,
                "reason_codes": reasons or (["repeat_source_occurrence_not_independent_evidence"] if index else [])})
    dispositions.sort(key=lambda row: (row["material_id"], row["record_ordinal"]))
    counts = Counter(row["disposition"] for row in dispositions)
    guard = digest({"materials": materials, "papers": papers, "mappings": maps, "works": works,
                    "visibility": {mid: context.visibility for mid, context in contexts.items()}})
    report = {"version": LOADER_VERSION, "payload_sha256": v["payload_sha256"],
        "source_manifest_sha256": v["source_manifest_sha256"], "plan_manifest_sha256": v["plan_manifest_sha256"],
        "snapshot_id": str(snapshot_id), "governance_sha256": guard,
        "expected_heads": {cid: str(heads[cid]["id"]) if cid in heads else None for cid in sorted(claim_by_id)},
        "accounting": {"input_occurrences": len(dispositions), **{key: counts[key] for key in _DISPOSITIONS}, "rows": dispositions},
        "selection_manifest": {"selected": selected, "source_counts": dict(sorted(Counter(row.get("source") or "unknown" for row in v["papers"]).items()))},
        "scientific_acceptance": False, "public_release": False, "database_mutated": False}
    report["preview_sha256"] = digest(report)
    return report, tables


async def preview_shadow_import(db, verified):
    """Read-only forecast; neither an import nor scientific/processing approval."""
    report, _ = await _prepare(db, verified)
    return report


def processing_review_payload(preview):
    """Payload to be independently reviewed; this helper grants no authority."""
    return {"version": REVIEW_VERSION, "preview_sha256": preview["preview_sha256"],
            "payload_sha256": preview["payload_sha256"], "plan_manifest_sha256": preview["plan_manifest_sha256"],
            "source_manifest_sha256": preview["source_manifest_sha256"],
            "restricted_internal_processing_approved": True, "scientific_acceptance": False,
            "public_release_approved": False}


async def _review(db, review_id, expected=None):
    artifact = (await _load(db, "evidence_artifacts", [_id(review_id)])).get(str(_id(review_id)))
    metadata = artifact.get("metadata") if artifact else None
    review = metadata.get("shadow_import_review") if isinstance(metadata, dict) else None
    if (not artifact or artifact["kind"] != "review" or artifact["schema_version"] != REVIEW_VERSION
            or artifact["hash_status"] != "verified" or not artifact["bytes_sha256"] or not isinstance(review, dict)
            or digest(review) != artifact["record_sha256"]
            or review.get("restricted_internal_processing_approved") is not True
            or review.get("scientific_acceptance") is not False or review.get("public_release_approved") is not False
            or (expected is not None and digest(review) != digest(expected))):
        raise ShadowImportError("exact approved internal-processing review artifact required")
    return artifact


async def _write_identical(db, name, row):
    table = RESEARCH_IMPORT_TABLES[name]
    inserted = (await db.execute(insert(table).values(**row).on_conflict_do_nothing().returning(table.c.id))).scalar_one_or_none()
    stored = (await _load(db, name, [row["id"]])).get(str(row["id"]))
    if stored is None or not _intact(stored) or any(stored[key] != value for key, value in row.items() if key != "completed_at"):
        raise ShadowImportError(f"{name}: immutable content mismatch")
    return inserted is not None


async def import_shadow_research(db, verified, *, review_artifact_id, dry_run=True):
    """One savepoint, no partial writes and no implicit outer commit.

    The caller must commit the clean SERIALIZABLE outer transaction. Retry the
    entire operation after serialization failure. Existing receipt replay checks
    pinned historic selections, rather than moving an old receipt to a new head.
    """
    if type(dry_run) is not bool:
        raise ShadowImportError("dry_run must be boolean")
    _validated(verified)
    await _isolation(db)
    transaction = await db.begin_nested()
    try:
        if not (await db.execute(sa.text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _LOCK_KEY})).scalar_one():
            raise ShadowImportError("shadow importer busy; retry the entire transaction")
        receipt_id = uuid5(_NAMESPACE, "receipt:" + verified["plan_manifest_sha256"])
        receipt = (await _load(db, "research_import_receipts", [receipt_id])).get(str(receipt_id))
        if receipt:
            artifact = await _review(db, review_artifact_id)
            if (not _intact(receipt) or receipt["approval_artifact_id"] != _id(review_artifact_id)
                    or receipt["approval_artifact_sha256"] != artifact["record_sha256"]
                    or receipt["selection_manifest"]["payload_sha256"] != verified["payload_sha256"]):
                raise ShadowImportError("receipt replay content/approval mismatch")
            for name, identifiers in receipt["selection_manifest"]["row_ids"].items():
                if name not in RESEARCH_IMPORT_TABLES or name == "research_import_receipts" or len(identifiers) > 1001:
                    raise ShadowImportError("receipt history scope invalid")
                stored = await _load(db, name, [_id(value) for value in identifiers])
                pinned = receipt["selection_manifest"]["row_hashes"][name]
                if len(stored) != len(identifiers) or any(not _intact(row) or row["record_sha256"] != pinned.get(key)
                                                         for key, row in stored.items()):
                    raise ShadowImportError("receipt replay history integrity failure")
            report = {"version": LOADER_VERSION, "receipt_id": str(receipt_id), "replayed": True,
                      "original_accounting": receipt["accounting"], "rows_inserted": 0,
                      "dry_run": dry_run, "committed": False, "scientific_acceptance": False,
                      "current_eligibility_reassessed": False}
        else:
            preview, tables = await _prepare(db, verified)
            if preview["accounting"]["failed"]:
                raise ShadowImportError("failed input occurrences prevent shadow import")
            artifact = await _review(db, review_artifact_id, processing_review_payload(preview))
            inserted = 0
            for name, rows in tables.items():
                for row in rows:
                    inserted += await _write_identical(db, name, row)
            # Independently read exact rows after insertion, compare all fields,
            # and recompute hashes before writing the final receipt.
            row_ids = {}
            row_hashes = {}
            for name, expected in tables.items():
                if not expected:
                    continue
                actual = await _load(db, name, [row["id"] for row in expected])
                if len(actual) != len(expected):
                    raise ShadowImportError("post-load row accounting mismatch")
                for row in expected:
                    if not _intact(actual[str(row["id"])]) or any(actual[str(row["id"])][key] != value for key, value in row.items()):
                        raise ShadowImportError("post-load exact semantic parity failure")
                row_ids[name] = [str(row["id"]) for row in expected]
                row_hashes[name] = {str(row["id"]): row["record_sha256"] for row in expected}
            selected = {**preview["selection_manifest"], "payload_sha256": verified["payload_sha256"],
                        "governance_sha256": preview["governance_sha256"], "row_ids": row_ids, "row_hashes": row_hashes}
            receipt_row = _sealed({"id": receipt_id, "snapshot_id": _id(preview["snapshot_id"]),
                "plan_manifest_sha256": verified["plan_manifest_sha256"], "loader_version": LOADER_VERSION,
                "approval_artifact_id": _id(review_artifact_id), "approval_artifact_kind": "review",
                "approval_artifact_sha256": artifact["record_sha256"], "selection_manifest": selected,
                "accounting": preview["accounting"]})
            receipt_row["completed_at"] = datetime.now(UTC)
            await _write_identical(db, "research_import_receipts", receipt_row)
            report = {"version": LOADER_VERSION, "receipt_id": str(receipt_id), "replayed": False,
                      "accounting": preview["accounting"], "rows_inserted": inserted + 1,
                      "dry_run": dry_run, "committed": False, "scientific_acceptance": False,
                      "post_load_parity": "exact_shadow_rows_verified"}
        if dry_run:
            await transaction.rollback()
        else:
            await transaction.commit()
    except BaseException:
        if transaction.is_active:
            await transaction.rollback()
        raise
    return report
