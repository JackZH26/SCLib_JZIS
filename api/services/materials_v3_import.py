"""Validated pilot import into append-only candidate history, never catalogue rows."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from models.db import MATERIALS_V3_TABLES as T
from models.db import Paper, PaperWorkMap


def sha(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


async def _insert_once(db, name, values, conflict):
    table = T[name]
    statement = (
        insert(table)
        .values(**values)
        .on_conflict_do_nothing(index_elements=conflict)
        .returning(table.c.id)
    )
    identifier = (await db.execute(statement)).scalar_one_or_none()
    if identifier is not None:
        return identifier
    query = select(table).where(*(table.c[key] == values[key] for key in conflict))
    old = (await db.execute(query)).mappings().one()
    for key, value in values.items():
        if old[key] != value:
            raise ValueError("immutable_ner_import_conflict")
    return old["id"]


async def import_validated_run(db, package):
    """Caller supplies a source-bound, server-validated package and owns transaction.

    This has no general write route. No material, source hold, claim, event,
    scientific decision or public projection is changed by this operation.
    """
    if (
        len(json.dumps(package).encode()) > 8 * 1024**2
        or len(package.get("validated_candidates", [])) > 1000
    ):
        raise ValueError("ner_import_resource_limit")
    if sha(package["config"]) != package["config_sha256"]:
        raise ValueError("ner_import_config_hash_mismatch")
    source = package["source_manifest"]
    body = {k: v for k, v in source.items() if k != "manifest_sha256"}
    if (
        sha(body) != package["manifest_sha256"]
        or source["source_sha256"] != package["source_sha256"]
    ):
        raise ValueError("ner_import_source_manifest_mismatch")
    for candidate in package["validated_candidates"]:
        validation = candidate.get("validation", {})
        if (
            validation.get("locator_verified") is not True
            or validation.get("scientific_acceptance") is not False
            or validation.get("schema_valid") is not True
        ):
            raise ValueError("verified_pending_candidate_required")
        if sha(candidate["positions"]["source_anchors"]) != candidate["position_sha256"]:
            raise ValueError("ner_import_source_position_hash_mismatch")
        for proof in validation.get("bound_evidence", []):
            start, end = proof["source_start"], proof["source_end"]
            text = "\n".join(r["text"] for r in source["records"])
            if (
                proof["source_sha256"] != package["source_sha256"]
                or type(start) is not int
                or type(end) is not int
                or start < 0
                or end <= start
                or text[start:end] != proof["quote"]
            ):
                raise ValueError("ner_import_evidence_source_mismatch")
    async with db.begin_nested():
        return await _import_run(db, package)


async def _import_run(db, package):
    paper_id = package["paper_id"]
    if await db.get(Paper, paper_id) is None:
        raise ValueError("existing_sclib_paper_required")
    mapping = (
        await db.execute(
            select(PaperWorkMap).where(
                PaperWorkMap.paper_id == paper_id, PaperWorkMap.review_status == "accepted"
            )
        )
    ).scalar_one_or_none()
    work_id = mapping.work_id if mapping else None
    if package.get("sclib_work_id") is not None and work_id != UUID(package["sclib_work_id"]):
        raise ValueError("source_work_mapping_conflict")
    capture = await _insert_once(
        db,
        "ner_source_captures",
        {
            "paper_id": paper_id,
            "work_id": work_id,
            "source_sha256": package["source_sha256"],
            "manifest_sha256": package["manifest_sha256"],
            "parser_version": package["parser_version"],
            "source_version": package["source_version"],
            "source_license": package["source_license"],
            "transfer_allowed": package["transfer_allowed"],
            "manifest": package["source_manifest"],
        },
        ["manifest_sha256"],
    )
    # Import receipt identity includes exact provider/config/source hash.
    run_key = package["job_key"]
    import uuid

    run_id = uuid.uuid5(uuid.NAMESPACE_URL, "urn:sclib:ner-run:" + run_key)
    run = await _insert_once(
        db,
        "ner_extraction_runs",
        {
            "id": run_id,
            "capture_id": capture,
            "provider": package["provider"],
            "model": package["model"],
            "model_revision": package.get("model_revision"),
            "config_sha256": package["config_sha256"],
            "schema_version": "materials-ner-candidate/3.0",
            "prompt_version": package["prompt_version"],
            "status": package["status"],
            "config": package["config"],
            "usage": package["usage"],
        },
        ["id"],
    )
    candidates = []
    for candidate in package["validated_candidates"]:
        if (
            candidate.get("validation", {}).get("locator_verified") is not True
            or candidate.get("validation", {}).get("scientific_acceptance") is not False
        ):
            raise ValueError("verified_pending_candidate_required")
        occurrence = await _insert_once(
            db,
            "ner_source_occurrences",
            {
                "capture_id": capture,
                "position_sha256": candidate["position_sha256"],
                "positions": candidate["positions"],
            },
            ["capture_id", "position_sha256"],
        )
        identifier = await _insert_once(
            db,
            "ner_candidates",
            {
                "run_id": run,
                "capture_id": capture,
                "occurrence_id": occurrence,
                "local_id": candidate["local_id"],
                "interpretation_sha256": sha(candidate["payload"]),
                "payload": candidate["payload"],
                "validation": candidate["validation"],
            },
            ["run_id", "occurrence_id", "interpretation_sha256"],
        )
        candidates.append(str(identifier))
    for block in package["block_coverage"]:
        await _insert_once(
            db,
            "ner_block_coverage",
            {
                "run_id": run,
                "block_id": block["block_id"],
                "input_sha256": block["input_sha256"],
                "status": block["status"],
                "receipt": block["receipt"],
            },
            ["run_id", "block_id"],
        )
    return {
        "run_id": str(run),
        "capture_id": str(capture),
        "candidate_ids": candidates,
        "scientific_acceptance": False,
        "catalogue_changed": False,
    }
