"""Internal insert-or-verify source registry; no public registration endpoint.

This trusted administrative boundary records a reviewed source-occurrence
binding, not review of superconductivity. It never infers identity from formula,
Tc, a mutable paper, or a caller's extraction/provenance envelope.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import SOURCE_PROVENANCE_TABLES, Base
from services.temporal_provenance import (
    REPRESENTATIONS,
    SourceAvailabilityWitness,
    public_locator,
    utc_datetime,
)

SOURCE_REGISTRY_VERSION = "source-provenance-registry/1.0.0"
REVIEW_POLICY_VERSION = "source-occurrence-review/1.0.0"
MAX_BUNDLE_ROWS = 1000
MAX_RESOLVER_CLAIMS = 500
MAX_WITNESSES_PLUS_SENTINEL = 101
_LOCK_KEY = 523017026
_FIELDS = {
    "source_revisions": {
        "id", "paper_id", "work_id", "revision_key", "provider_revision", "version_status",
        "source_version_public_at", "availability_status", "availability_basis", "metadata_sha256",
    },
    "source_captures": {"id", "source_revision_id", "capture_key", "captured_at", "bytes_sha256", "representation"},
    "claim_source_occurrences": {
        "id", "claim_id", "work_id", "source_revision_id", "capture_id", "occurrence_key",
        "locator", "binding_status", "review_artifact_id", "review_artifact_sha256",
    },
}
_UNIQUE_KEYS = {
    "source_revisions": ("paper_id", "revision_key"),
    "source_captures": ("source_revision_id", "capture_key"),
    "claim_source_occurrences": ("claim_id", "capture_id", "occurrence_key"),
}


class SourceRegistryConflict(ValueError):
    """An immutable identifier or binding no longer matches its exact content."""


def _json(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        parsed = utc_datetime(value)
        if parsed is None:
            raise ValueError("timezone-aware timestamp required")
        return parsed.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json(item) for item in value]
    return value


def provenance_sha256(value: Mapping) -> str:
    """Canonical UTF-8 JSON hash used by this frozen registry/review contract."""
    return hashlib.sha256(json.dumps(_json(value), sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _uuid(value, field):
    if not isinstance(value, (str, UUID)):
        raise ValueError(f"{field}: UUID required")
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise ValueError(f"{field}: UUID required") from exc


def _text(value, field, maximum=160):
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{field}: bounded nonempty text required")
    return value


def _sha(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{field}: lowercase SHA-256 required")
    return value


def _instant(value, field):
    parsed = utc_datetime(value)
    if parsed is None:
        raise ValueError(f"{field}: exact timezone-aware timestamp required (no date-only fallback)")
    return parsed


def _row(name, original):
    if not isinstance(original, Mapping) or set(original) - _FIELDS[name]:
        raise ValueError(f"{name}: unexpected fields or invalid row")
    row = dict(original)
    row["id"] = _uuid(row.get("id"), "id")
    if name == "source_revisions":
        row["paper_id"] = _text(row.get("paper_id"), "paper_id", 100)
        row["work_id"] = _uuid(row["work_id"], "work_id") if row.get("work_id") is not None else None
        row["revision_key"] = _text(row.get("revision_key"), "revision_key")
        row["provider_revision"] = (_text(row["provider_revision"], "provider_revision")
                                    if row.get("provider_revision") is not None else None)
        row.setdefault("version_status", "unresolved")
        row.setdefault("availability_status", "unknown")
        row.setdefault("availability_basis", "unknown")
        if row["version_status"] not in ("pinned", "unresolved"):
            raise ValueError("version_status invalid")
        if row["version_status"] == "pinned" and row["provider_revision"] is None:
            raise ValueError("pinned provider revision required")
        if row["availability_status"] not in ("known_by", "unknown", "uncertain"):
            raise ValueError("availability_status invalid")
        row["availability_basis"] = _text(row["availability_basis"], "availability_basis", 100)
        if row["availability_status"] == "known_by":
            row["source_version_public_at"] = _instant(row.get("source_version_public_at"), "source_version_public_at")
            if row["version_status"] != "pinned" or row["availability_basis"] == "unknown":
                raise ValueError("known_by requires an explicit pinned version and availability basis")
        else:
            if row.get("source_version_public_at") is not None:
                raise ValueError("unknown/uncertain public time must remain null")
            row["source_version_public_at"] = None
        row["metadata_sha256"] = _sha(row.get("metadata_sha256"), "metadata_sha256")
    elif name == "source_captures":
        row["source_revision_id"] = _uuid(row.get("source_revision_id"), "source_revision_id")
        row["capture_key"] = _text(row.get("capture_key"), "capture_key")
        row["captured_at"] = _instant(row.get("captured_at"), "captured_at")
        row["bytes_sha256"] = _sha(row.get("bytes_sha256"), "bytes_sha256")
        if not isinstance(row.get("representation"), str) or row["representation"] not in REPRESENTATIONS:
            raise ValueError("unqualified original source representation")
    else:
        for key in ("claim_id", "work_id", "source_revision_id", "capture_id"):
            row[key] = _uuid(row.get(key), key)
        row["occurrence_key"] = _text(row.get("occurrence_key"), "occurrence_key")
        locator = row.get("locator")
        safe = public_locator(locator)
        if not isinstance(locator, Mapping) or not safe or safe != locator:
            raise ValueError("locator must contain only bounded complete source coordinates")
        row["locator"] = safe
        row["locator_sha256"] = provenance_sha256(safe)
        row.setdefault("binding_status", "pending")
        if row["binding_status"] not in ("pending", "reviewed"):
            raise ValueError("binding_status invalid")
        if row["binding_status"] == "reviewed":
            row["review_artifact_id"] = _uuid(row.get("review_artifact_id"), "review_artifact_id")
            row["review_artifact_kind"] = "review"
            row["review_artifact_sha256"] = _sha(row.get("review_artifact_sha256"), "review_artifact_sha256")
        else:
            if row.get("review_artifact_id") is not None or row.get("review_artifact_sha256") is not None:
                raise ValueError("pending binding cannot carry a reviewed reference")
            row.update(review_artifact_id=None, review_artifact_kind=None, review_artifact_sha256=None)
    row["record_sha256"] = provenance_sha256(row)
    return row


def normalize_source_provenance_bundle(bundle: Mapping) -> dict[str, list[dict]]:
    """Pure strict bounded validation; no dates or identities are synthesized."""
    if (not isinstance(bundle, Mapping) or set(bundle) - {"version", *_FIELDS}
            or bundle.get("version") != SOURCE_REGISTRY_VERSION):
        raise ValueError("source registry bundle version/fields invalid")
    prepared = {}
    total = 0
    for name in _FIELDS:
        rows = bundle.get(name, [])
        if not isinstance(rows, list):
            raise ValueError("bundle rows must be arrays")
        total += len(rows)
        if total > MAX_BUNDLE_ROWS:
            raise ValueError("source registry bundle exceeds bounded row limit")
        prepared[name] = sorted((_row(name, row) for row in rows), key=lambda row: str(row["id"]))
    return prepared


def source_occurrence_review_payload(
    revision: Mapping, capture: Mapping, occurrence: Mapping, claim: Mapping,
) -> dict:
    """Exact review linkage contract. Producing this dict does not approve it.

An external authorized review must validate these assertions and register the
review artifact; this helper does not create an artifact or invoke a reviewer.
"""
    return _json({
        "version": REVIEW_POLICY_VERSION, "claim_id": occurrence["claim_id"],
        "paper_id": revision["paper_id"], "work_id": occurrence["work_id"],
        "source_revision_id": revision["id"], "capture_id": capture["id"],
        "provider_revision": revision["provider_revision"],
        "source_version_public_at": revision["source_version_public_at"],
        "captured_at": capture["captured_at"], "bytes_sha256": capture["bytes_sha256"],
        "representation": capture["representation"], "locator_sha256": occurrence["locator_sha256"],
        "claim_record_sha256": provenance_sha256({
            key: value for key, value in claim.items() if key not in {"created_at", "updated_at"}
        }),
    })


def _review_valid(artifact, revision, capture, occurrence, claim):
    if (not artifact or occurrence["binding_status"] != "reviewed" or artifact["kind"] != "review"
            or artifact["schema_version"] != REVIEW_POLICY_VERSION
            or artifact["hash_status"] != "verified" or not artifact["bytes_sha256"]
            or artifact["record_sha256"] != occurrence["review_artifact_sha256"]):
        return False
    metadata = artifact.get("metadata")
    review = metadata.get("source_provenance_review") if isinstance(metadata, dict) else None
    if not isinstance(review, dict):
        return False
    expected = source_occurrence_review_payload(revision, capture, occurrence, claim)
    if (set(review) != {*expected, "binding_verified", "version_resolved", "public_time_verified"}
            or any(review.get(key) != value for key, value in expected.items())
            or any(type(review.get(key)) is not bool for key in (
                "binding_verified", "version_resolved", "public_time_verified"))):
        return False
    return provenance_sha256(review) == artifact["record_sha256"] and review["binding_verified"] is True


async def _get(db, name, row_id):
    table = Base.metadata.tables[name]
    return (await db.execute(sa.select(table).where(table.c.id == row_id))).mappings().first()


def _intact(name, row):
    payload = {key: row[key] for key in row if key not in ("created_at", "record_sha256")}
    return provenance_sha256(payload) == row["record_sha256"]


async def _verify_relations(db, name, row):
    if name == "source_revisions" and row["work_id"] is not None:
        mapping = Base.metadata.tables["paper_work_map"]
        accepted = (await db.execute(sa.select(mapping.c.work_id).where(
            mapping.c.paper_id == row["paper_id"], mapping.c.review_status == "accepted",
        ))).scalar_one_or_none()
        if accepted != row["work_id"]:
            raise SourceRegistryConflict("source work requires an existing accepted bibliographic work mapping")
    elif name == "source_captures":
        revision = await _get(db, "source_revisions", row["source_revision_id"])
        if not revision or not _intact("source_revisions", revision):
            raise SourceRegistryConflict("source revision missing or content hash mismatch")
        if revision["source_version_public_at"] and row["captured_at"] < revision["source_version_public_at"]:
            raise SourceRegistryConflict("capture precedes claimed public version time")
        table = SOURCE_PROVENANCE_TABLES[name]
        conflict = (await db.execute(sa.select(table.c.id).where(
            table.c.source_revision_id == row["source_revision_id"],
            table.c.representation == row["representation"], table.c.bytes_sha256 != row["bytes_sha256"],
        ).limit(1))).first()
        if conflict:
            raise SourceRegistryConflict("same source version and representation have conflicting bytes")
    elif name == "claim_source_occurrences":
        revision = await _get(db, "source_revisions", row["source_revision_id"])
        capture = await _get(db, "source_captures", row["capture_id"])
        claim = await _get(db, "material_claims", row["claim_id"])
        if (not revision or not capture or not claim or not _intact("source_revisions", revision)
                or not _intact("source_captures", capture)
                or capture["source_revision_id"] != revision["id"]
                or revision["work_id"] != row["work_id"] or claim["work_id"] != row["work_id"]):
            raise SourceRegistryConflict("claim/work/revision/capture association mismatch")
        if row["binding_status"] == "reviewed":
            artifact = await _get(db, "evidence_artifacts", row["review_artifact_id"])
            if not _review_valid(artifact, revision, capture, row, claim):
                raise SourceRegistryConflict("review artifact does not verify this exact source occurrence")


async def import_source_provenance_bundle(
    db: AsyncSession, bundle: Mapping, *, dry_run: bool = True,
) -> dict:
    """Insert or verify identically, inside a savepoint; never commit caller work.

Dry-run always rolls back this function's changes. Live mode releases only its
savepoint: the administrative caller must explicitly commit its transaction.
Any mismatch rolls back the complete bundle. There is no overwrite/upsert path.
"""
    if type(dry_run) is not bool:
        raise ValueError("dry_run must be boolean")
    prepared = normalize_source_provenance_bundle(bundle)
    report = {"version": SOURCE_REGISTRY_VERSION, "dry_run": dry_run,
              "inserted": 0, "verified_existing": 0, "committed": False}
    transaction = await db.begin_nested()
    try:
        # Serialize registry writers through this interface, including checks
        # across captures. The SQL triggers also forbid UPDATE/DELETE/TRUNCATE.
        await db.execute(sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK_KEY})
        for name, rows in prepared.items():
            table = SOURCE_PROVENANCE_TABLES[name]
            for row in rows:
                await _verify_relations(db, name, row)
                inserted = (await db.execute(insert(table).values(**row).on_conflict_do_nothing()
                                             .returning(table.c.id))).scalar_one_or_none()
                if inserted is not None:
                    report["inserted"] += 1
                    continue
                same = (await db.execute(sa.select(table).where(sa.or_(
                    table.c.id == row["id"], sa.and_(*(table.c[key] == row[key] for key in _UNIQUE_KEYS[name])),
                )))).mappings().all()
                if len(same) != 1 or any(same[0][key] != value for key, value in row.items()):
                    raise SourceRegistryConflict(f"{name}: immutable identity/content mismatch")
                report["verified_existing"] += 1
        if dry_run:
            await transaction.rollback()
        else:
            await transaction.commit()
    except BaseException:
        if transaction.is_active:
            await transaction.rollback()
        raise
    return report


async def resolve_claim_source_witnesses(
    db: AsyncSession, claim_ids: Sequence[UUID | str],
) -> dict[str, list[SourceAvailabilityWitness]]:
    """Resolve authoritative rows in a bounded batch; DB errors propagate.

Registered but pending/invalid evidence is returned with false verification
flags, so the pure consumer reports uncertainty instead of dropping conflicts.
101 rows deliberately exceed the pure consumer's 100-witness bound and make
coverage incomplete. No historical dates or supplied envelopes are consulted.
"""
    if (not isinstance(claim_ids, (list, tuple)) or len(claim_ids) > MAX_RESOLVER_CLAIMS):
        raise ValueError("claim resolver requires at most 500 claim identifiers")
    ids = sorted({_uuid(value, "claim_id") for value in claim_ids}, key=str)
    result = {str(value): [] for value in ids}
    if not ids:
        return result
    occurrences = SOURCE_PROVENANCE_TABLES["claim_source_occurrences"]
    ranked = sa.select(
        occurrences.c.id, sa.func.row_number().over(
            partition_by=occurrences.c.claim_id, order_by=occurrences.c.id,
        ).label("n"),
    ).where(occurrences.c.claim_id.in_(ids)).subquery()
    rows = (await db.execute(sa.select(occurrences).join(ranked, ranked.c.id == occurrences.c.id)
                            .where(ranked.c.n <= MAX_WITNESSES_PLUS_SENTINEL)
                            .order_by(occurrences.c.claim_id, occurrences.c.id))).mappings().all()
    # One bounded query per referenced table, not one query per occurrence.
    async def load(name, row_ids):
        if not row_ids:
            return {}
        table = Base.metadata.tables[name]
        return {row["id"]: row for row in (await db.execute(
            sa.select(table).where(table.c.id.in_(row_ids)),
        )).mappings().all()}
    revisions = await load("source_revisions", {row["source_revision_id"] for row in rows})
    captures = await load("source_captures", {row["capture_id"] for row in rows})
    reviews = await load("evidence_artifacts", {row["review_artifact_id"] for row in rows if row["review_artifact_id"]})
    claims = await load("material_claims", ids)
    mapping = Base.metadata.tables["paper_work_map"]
    mappings = {row["paper_id"]: row for row in (await db.execute(sa.select(mapping).where(
        mapping.c.paper_id.in_({row["paper_id"] for row in revisions.values()}),
    ))).mappings().all()} if revisions else {}
    capture_table = SOURCE_PROVENANCE_TABLES["source_captures"]
    conflicts = set((await db.execute(sa.select(capture_table.c.source_revision_id, capture_table.c.representation)
        .where(capture_table.c.source_revision_id.in_(revisions))
        .group_by(capture_table.c.source_revision_id, capture_table.c.representation)
        .having(sa.func.count(sa.distinct(capture_table.c.bytes_sha256)) > 1))).all()) if revisions else set()
    for occurrence in rows:
        revision, capture = revisions[occurrence["source_revision_id"]], captures[occurrence["capture_id"]]
        review = reviews.get(occurrence["review_artifact_id"])
        claim = claims[occurrence["claim_id"]]
        work_map = mappings.get(revision["paper_id"])
        valid = (all(_intact(name, value) for name, value in (
            ("source_revisions", revision), ("source_captures", capture), ("claim_source_occurrences", occurrence),
        )) and capture["source_revision_id"] == revision["id"]
            and claim["work_id"] == occurrence["work_id"] == revision["work_id"]
            and work_map is not None and work_map["review_status"] == "accepted"
            and work_map["work_id"] == revision["work_id"]
            and (revision["id"], capture["representation"]) not in conflicts
            and public_locator(occurrence["locator"]) == occurrence["locator"]
            and provenance_sha256(occurrence["locator"]) == occurrence["locator_sha256"]
            and _review_valid(review, revision, capture, occurrence, claim))
        assertions = review["metadata"]["source_provenance_review"] if valid else {}
        result[str(occurrence["claim_id"])].append(SourceAvailabilityWitness(
            claim_id=str(occurrence["claim_id"]), paper_id=revision["paper_id"],
            work_id=str(occurrence["work_id"]), source_revision_id=str(revision["id"]),
            source_version=revision["provider_revision"] or revision["revision_key"],
            capture_id=str(capture["id"]), source_version_public_at=revision["source_version_public_at"],
            captured_at=capture["captured_at"], bytes_sha256=capture["bytes_sha256"],
            representation=capture["representation"], locator=public_locator(occurrence["locator"]),
            review_reference=(f"{occurrence['review_artifact_id']}:{occurrence['review_artifact_sha256']}"
                              if occurrence["review_artifact_id"] else "pending"),
            version_resolved=bool(valid and revision["version_status"] == "pinned" and assertions.get("version_resolved") is True),
            binding_verified=bool(valid),
            public_time_verified=bool(valid and revision["availability_status"] == "known_by"
                                      and assertions.get("public_time_verified") is True),
        ))
    return result
