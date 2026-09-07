"""Bounded internal metadata-publication workflow and live public admission.

Writers take authenticated actor IDs from trusted callers, require explicit DB
grants and own only a savepoint. No function authenticates a person from JSON,
commits the outer transaction, or grants scientific/training approval.
"""
from __future__ import annotations

import re
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import sqlalchemy as sa

from services import research_public_contract as public
from services import research_release_manifest as capsule
from services.research_access import (
    ResearchAccessDenied,
    active_grant,
    active_user,
    check_grant_inventory,
    require_research_admin,
    table,
)
from services.research_freeze import (
    ResearchFreezeError,
    _bundle_hash,
    _capture_artifact_bytes,
    _stored,
    _verify_pins,
)
from services.source_lifecycle import SourceLifecycleError

VERSION = "research-publication-service/1.0.0"
MAX_PROPOSAL_SCAN = 100


class PublicationUnavailable(ValueError):
    """Missing, unpublished, invalid or currently ineligible publication."""


def _uuid(value):
    return UUID(str(value))


def _token(value):
    if type(value) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,159}", value) is None:
        raise ValueError("A bounded reason/basis code is required")
    return value


def _hash(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("An independently pinned SHA-256 is required")
    return value


def _wire(values):
    return {str(key): str(value) if isinstance(value, UUID) else value for key, value in values.items()}


async def _insert(db, name, values):
    # Record identity is not an authority token. DB constraints validate actors,
    # exact parent references and lifecycle independently of this hash.
    values = {**values, "id": uuid4(), "record_sha256": capsule.digest(_wire(values))}
    return dict((await db.execute(table(name).insert().values(**values).returning(table(name)))).mappings().one())


def _verify_record(row):
    body = {key: value for key, value in row.items() if key not in {"id", "created_at", "record_sha256"}}
    if capsule.digest(_wire(body)) != row["record_sha256"]:
        raise PublicationUnavailable("Publication audit record integrity mismatch")


async def _get(db, name, identifier):
    relation = table(name)
    # The only large field is the proposal body; reject expanded size before
    # receiving source JSON. No unbounded admin metadata is emitted publicly.
    size = (await db.execute(sa.select(sa.func.octet_length(sa.cast(
        sa.func.to_jsonb(relation.table_valued()), sa.Text))).where(relation.c.id == _uuid(identifier)))).scalar_one_or_none()
    if size is None or size > 9 * 1024 * 1024:
        raise PublicationUnavailable("Publication record unavailable")
    row = dict((await db.execute(sa.select(relation).where(relation.c.id == _uuid(identifier)))).mappings().one())
    _verify_record(row)
    return row


@asynccontextmanager
async def _write(db, dry_run):
    if type(dry_run) is not bool or db.new or db.dirty or db.deleted:
        raise ValueError("A clean dedicated session and Boolean dry_run are required")
    if (await db.execute(sa.text("SHOW transaction_isolation"))).scalar_one() != "serializable":
        raise ValueError("Publication writes require SERIALIZABLE isolation")
    nested = await db.begin_nested()
    try:
        await db.execute(sa.text("SELECT public.sclib_research_publication_lock_v1()"))
        yield
        if dry_run:
            await nested.rollback()
        else:
            await nested.commit()
    except BaseException:
        if nested.is_active:
            await nested.rollback()
        raise


def _report(row, dry_run):
    return {"id": str(row["id"]), "record_sha256": row["record_sha256"],
            "dry_run": dry_run, "committed": False}


async def grant_role(db, *, actor_user_id, user_id, role, reason_code, dry_run=True):
    actor_user_id, user_id = _uuid(actor_user_id), _uuid(user_id)
    if type(role) is not str or role not in {"curator", "reviewer", "publisher"}:
        raise ValueError("Unsupported research role")
    reason_code = _token(reason_code)
    async with _write(db, dry_run):
        await require_research_admin(db, actor_user_id)
        await active_user(db, user_id)
        row = await _insert(db, "research_role_grants", dict(user_id=user_id, role=role,
            granted_by=actor_user_id, reason_code=reason_code))
    return _report(row, dry_run)


async def revoke_role(db, *, actor_user_id, grant_id, reason_code, dry_run=True):
    actor_user_id, grant_id = _uuid(actor_user_id), _uuid(grant_id)
    reason_code = _token(reason_code)
    async with _write(db, dry_run):
        await require_research_admin(db, actor_user_id)
        await _get(db, "research_role_grants", grant_id)
        row = await _insert(db, "research_role_revocations", dict(grant_id=grant_id,
            revoked_by=actor_user_id, reason_code=reason_code))
    return _report(row, dry_run)


async def decide_permission(db, *, actor_user_id, release_id, table_name, row_id,
                            row_sha256, decision, license_code, basis_code, reason_code,
                            supersedes_id=None, dry_run=True):
    actor_user_id, release_id = _uuid(actor_user_id), _uuid(release_id)
    supersedes_id = _uuid(supersedes_id) if supersedes_id is not None else None
    reason_code, basis_code = _token(reason_code), _token(basis_code)
    if (type(table_name) is not str or table_name not in capsule.TABLE_FIELDS
            or type(row_id) is not str or not 0 < len(row_id) <= 200
            or type(row_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", row_sha256) is None
            or type(license_code) is not str or license_code not in public.LICENSE_CODES
            or decision not in {"allow", "revoke"}):
        raise ValueError("Unsupported exact metadata permission")
    async with _write(db, dry_run):
        grant = await active_grant(db, actor_user_id, role="reviewer")
        release = await _stored(db, "research_releases", release_id)
        if release is None:
            raise PublicationUnavailable("Capsule unavailable")
        row = await _insert(db, "research_publication_permissions", dict(
            release_id=release_id, manifest_sha256=release["manifest_sha256"], table_name=table_name,
            row_id=row_id, row_sha256=row_sha256, decision=decision, scope=public.SCOPE,
            license_code=license_code, basis_code=basis_code, actor_user_id=actor_user_id,
            actor_grant_id=grant["id"], supersedes_id=supersedes_id, reason_code=reason_code))
    return _report(row, dry_run)


async def _permissions(db, release):
    permissions = table("research_publication_permissions")
    successor = permissions.alias("successor")
    rows = (await db.execute(sa.select(permissions).where(permissions.c.release_id == release["id"],
        ~sa.exists(sa.select(successor.c.id).where(successor.c.supersedes_id == permissions.c.id))).limit(1001))).mappings().all()
    if len(rows) > 1000:
        raise PublicationUnavailable("Metadata permission inventory exceeds limit")
    await check_grant_inventory(db, [(row["actor_user_id"], row["actor_grant_id"], "reviewer") for row in rows])
    result = []
    for row in rows:
        _verify_record(row)
        if row["decision"] != "allow" or row["manifest_sha256"] != release["manifest_sha256"]:
            raise PublicationUnavailable("A dependency lacks current metadata permission")
        result.append({"table": row["table_name"], "row_id": row["row_id"], "row_sha256": row["row_sha256"],
            "permission_id": str(row["id"]), "permission_sha256": row["record_sha256"],
            "scope": row["scope"], "license_code": row["license_code"]})
    return result


async def _current_catalogue(db, release):
    """Conservative source/material holds; metadata rights do not waive them."""
    from models.db import Material
    from services.material_visibility_adapter import prepare_material_views
    from services.source_lifecycle import resolve_paper_lifecycle, resolve_work_lifecycle
    from services.source_visibility import source_visibility
    ids = {name: [row["row_id"] for row in release["manifest"]["rows"] if row["table"] == name]
           for name in ("materials", "papers", "works")}
    # Preflight the entire live ancestor chain before the shared adapter loads
    # any full material row. Repeatable-read/serializable callers keep these
    # sizes and relationships stable; no compressed/TOAST size shortcut.
    material_table = Material.__table__
    frontier, seen, size_total = set(ids["materials"]), set(), 0
    for _ in range(33):
        if not frontier:
            break
        sizes = (await db.execute(sa.select(Material.id, Material.parent_material_id,
            sa.func.octet_length(sa.cast(sa.func.to_jsonb(material_table.table_valued()), sa.Text))).where(
                Material.id.in_(frontier)).limit(1001))).all()
        if len(sizes) != len(frontier) or len(seen) + len(sizes) > 1000:
            raise PublicationUnavailable("Live material ancestry inventory unavailable")
        size_total += sum(size for _, _, size in sizes)
        if size_total > 4 * 1024 * 1024:
            raise PublicationUnavailable("Live material governance byte budget exceeded")
        seen.update(frontier)
        frontier = {parent for _, parent, _ in sizes if parent is not None} - seen
    if frontier:
        raise PublicationUnavailable("Live material ancestry depth exceeded")
    # Bounded records also bound the adapter's related paper-ID inventory and
    # material-review work; a row can otherwise contain many tiny references.
    inventory = (await db.execute(sa.select(Material.records).where(Material.id.in_(seen)))).scalars().all()
    if any(not isinstance(records, list) for records in inventory) or sum(len(records) for records in inventory) > 5000:
        raise PublicationUnavailable("Live material record inventory exceeded")
    materials = (await db.execute(sa.select(Material).where(Material.id.in_(ids["materials"])))).scalars().all()
    if len(materials) != len(ids["materials"]):
        raise PublicationUnavailable("Current catalogue identity unavailable")
    views = await prepare_material_views(db, materials)
    if any(not view.visibility.get("public_catalogue_eligible") for view in views):
        raise PublicationUnavailable("Current material governance hold")
    for name, resolver in (("papers", resolve_paper_lifecycle), ("works", resolve_work_lifecycle)):
        keys = [_uuid(value) for value in ids[name]] if name == "works" else ids[name]
        states = await resolver(db, keys)
        if len(states) != len(keys) or any(not source_visibility(value)["reported_claim_filter_eligible"] for value in states.values()):
            raise PublicationUnavailable("Current source governance hold")


async def _release(db, release_id):
    release = await _stored(db, "research_releases", release_id)
    if release is None:
        raise PublicationUnavailable("Capsule unavailable")
    await _verify_pins(db, release)
    if _bundle_hash(release["manifest"]) != release["bundle_sha256"]:
        raise PublicationUnavailable("Capsule bundle binding mismatch")
    notices = table("research_release_notices")
    if (await db.execute(sa.select(notices.c.id).where(notices.c.release_id == release["id"]).limit(1))).first():
        raise PublicationUnavailable("Capsule has a post-freeze notice")
    await _current_catalogue(db, release)
    return release


async def propose_publication(db, *, actor_user_id, release_id, expected_capsule_sha256,
                              artifact_bytes, dry_run=True):
    actor_user_id, release_id = _uuid(actor_user_id), _uuid(release_id)
    captured = _capture_artifact_bytes(artifact_bytes)
    expected_capsule_sha256 = _hash(expected_capsule_sha256)
    async with _write(db, dry_run):
        grant = await active_grant(db, actor_user_id, role="curator")
        release = await _release(db, release_id)
        if release["manifest_sha256"] != expected_capsule_sha256:
            raise PublicationUnavailable("Exact capsule digest required")
        body = public.build_public_document(manifest=release["manifest"], expected_capsule_sha256=expected_capsule_sha256,
            permissions=await _permissions(db, release), artifact_bytes=captured)
        row = await _insert(db, "research_publication_proposals", dict(release_id=release_id,
            manifest_sha256=expected_capsule_sha256, actor_user_id=actor_user_id, actor_grant_id=grant["id"],
            public_payload=body, payload_sha256=capsule.digest(body), policy_version=public.VERSION))
    return {**_report(row, dry_run), "public_payload": body, "payload_sha256": row["payload_sha256"]}


async def _proposal(db, proposal_id, expected_payload_sha256=None):
    proposal = await _get(db, "research_publication_proposals", proposal_id)
    if expected_payload_sha256 is not None and proposal["payload_sha256"] != expected_payload_sha256:
        raise PublicationUnavailable("Exact reviewed payload digest required")
    public.verify_public_document(proposal["public_payload"], expected_public_sha256=proposal["payload_sha256"])
    await active_grant(db, proposal["actor_user_id"], role="curator", grant_id=proposal["actor_grant_id"])
    release = await _release(db, proposal["release_id"])
    if proposal["manifest_sha256"] != release["manifest_sha256"] or proposal["public_payload"]["capsule_sha256"] != release["manifest_sha256"]:
        raise PublicationUnavailable("Proposal capsule identity mismatch")
    permissions = await _permissions(db, release)
    # Reconstruct metadata receipts without re-fetching source bytes during a
    # read. Source bytes were checked at proposal creation; no such read claim.
    grants = {(item["table"], item["row_id"]): item for item in permissions}
    if set(grants) != {(item["table"], item["row_id"]) for item in release["manifest"]["rows"]}:
        raise PublicationUnavailable("Incomplete recursive metadata permission")
    expected = []
    for row in release["manifest"]["rows"]:
        permission = grants[(row["table"], row["row_id"])]
        if permission["row_sha256"] != row["row_sha256"]:
            raise PublicationUnavailable("Stale metadata permission")
        expected.append({"table": row["table"], "object_sha256": public.public_object_sha256(
            capsule_sha256=release["manifest_sha256"], table=row["table"], row_id=row["row_id"], row_sha256=row["row_sha256"]),
            **{key: permission[key] for key in ("permission_id", "permission_sha256", "scope", "license_code")}})
    expected.sort(key=lambda item: (item["table"], item["object_sha256"]))
    if capsule.digest(expected) != capsule.digest(proposal["public_payload"]["objects"]):
        raise PublicationUnavailable("Publication permission has changed")
    root = next(row for row in release["manifest"]["rows"] if row["table"] == "ml_dataset_snapshots"
                and row["row_id"] == release["manifest"]["dataset_id"])
    if (proposal["policy_version"] != public.VERSION or proposal["public_payload"]["dataset_object_sha256"]
            != public.public_object_sha256(capsule_sha256=release["manifest_sha256"], table=root["table"],
                                          row_id=root["row_id"], row_sha256=root["row_sha256"])):
        raise PublicationUnavailable("Publication root or policy binding mismatch")
    return proposal


async def review_publication(db, *, actor_user_id, proposal_id, expected_payload_sha256,
                             disclosure_approved, reason_code, dry_run=True):
    actor_user_id, proposal_id = _uuid(actor_user_id), _uuid(proposal_id)
    expected_payload_sha256 = _hash(expected_payload_sha256)
    if type(disclosure_approved) is not bool:
        raise ValueError("Explicit Boolean disclosure decision required")
    reason_code = _token(reason_code)
    async with _write(db, dry_run):
        grant = await active_grant(db, actor_user_id, role="reviewer")
        proposal = (await _proposal(db, proposal_id, expected_payload_sha256) if disclosure_approved
                    else await _get(db, "research_publication_proposals", proposal_id))
        if proposal["payload_sha256"] != expected_payload_sha256:
            raise PublicationUnavailable("Exact reviewed payload digest required")
        if proposal["actor_user_id"] == actor_user_id:
            raise ResearchAccessDenied("A different reviewer must assess the proposal")
        row = await _insert(db, "research_publication_reviews", dict(proposal_id=proposal_id,
            manifest_sha256=proposal["manifest_sha256"], payload_sha256=expected_payload_sha256,
            actor_user_id=actor_user_id, actor_grant_id=grant["id"], disclosure_approved=disclosure_approved,
            scientific_acceptance=False, ml_training_approved=False, reason_code=reason_code))
    return _report(row, dry_run)


async def publication_action(db, *, actor_user_id, proposal_id, review_id, expected_payload_sha256,
                             kind, reason_code, dry_run=True):
    actor_user_id, proposal_id, review_id = _uuid(actor_user_id), _uuid(proposal_id), _uuid(review_id)
    expected_payload_sha256 = _hash(expected_payload_sha256)
    if kind not in {"publish", "withdraw"}:
        raise ValueError("Unsupported publication action")
    reason_code = _token(reason_code)
    async with _write(db, dry_run):
        grant = await active_grant(db, actor_user_id, role="publisher")
        # Withdrawal must remain possible after a permission/source hold.
        proposal = (await _proposal(db, proposal_id, expected_payload_sha256) if kind == "publish"
                    else await _get(db, "research_publication_proposals", proposal_id))
        review = await _get(db, "research_publication_reviews", review_id)
        if (proposal["payload_sha256"] != expected_payload_sha256 or review["proposal_id"] != proposal_id
                or review["payload_sha256"] != expected_payload_sha256 or review["disclosure_approved"] is not True):
            raise PublicationUnavailable("Exact approved disclosure review required")
        if kind == "publish":
            await active_grant(db, review["actor_user_id"], role="reviewer", grant_id=review["actor_grant_id"])
        if actor_user_id in {proposal["actor_user_id"], review["actor_user_id"]}:
            raise ResearchAccessDenied("Publication requires a third distinct actor")
        row = await _insert(db, "research_publication_actions", dict(proposal_id=proposal_id,
            manifest_sha256=proposal["manifest_sha256"], payload_sha256=expected_payload_sha256,
            actor_user_id=actor_user_id, actor_grant_id=grant["id"], kind=kind, review_id=review_id, reason_code=reason_code))
    return _report(row, dry_run)


async def admitted_publication(db, proposal_id):
    """Caller owns a consistent read transaction; no cross-request cache."""
    actions = table("research_publication_actions")
    rows = (await db.execute(sa.select(actions).where(actions.c.proposal_id == _uuid(proposal_id)).limit(3))).mappings().all()
    if len(rows) != 1 or rows[0]["kind"] != "publish":
        raise PublicationUnavailable("Publication unavailable")
    reviews = table("research_publication_reviews")
    if (await db.execute(sa.select(reviews.c.id).where(reviews.c.proposal_id == _uuid(proposal_id),
        reviews.c.disclosure_approved.is_(False)).limit(1))).first():
        raise PublicationUnavailable("Publication has a disclosure-review hold")
    proposal = await _proposal(db, proposal_id)
    action = rows[0]
    _verify_record(action)
    await active_grant(db, action["actor_user_id"], role="publisher", grant_id=action["actor_grant_id"])
    review = await _get(db, "research_publication_reviews", action["review_id"])
    await active_grant(db, review["actor_user_id"], role="reviewer", grant_id=review["actor_grant_id"])
    if (review["disclosure_approved"] is not True or review["scientific_acceptance"] is not False
            or review["ml_training_approved"] is not False
            or len({proposal["actor_user_id"], review["actor_user_id"], action["actor_user_id"]}) != 3):
        raise PublicationUnavailable("Independent disclosure approvals required")
    for row in (review, action):
        if (row["proposal_id"] != proposal["id"] or row["manifest_sha256"] != proposal["manifest_sha256"]
                or row["payload_sha256"] != proposal["payload_sha256"]):
            raise PublicationUnavailable("Publication decision binding mismatch")
    return proposal


async def public_inventory(db):
    proposals = table("research_publication_proposals")
    actions = table("research_publication_actions")
    ids = (await db.execute(sa.select(proposals.c.id).where(
        sa.exists(sa.select(actions.c.id).where(actions.c.proposal_id == proposals.c.id, actions.c.kind == "publish")),
        ~sa.exists(sa.select(actions.c.id).where(actions.c.proposal_id == proposals.c.id, actions.c.kind == "withdraw"))
        ).order_by(proposals.c.id).limit(MAX_PROPOSAL_SCAN + 1))).scalars().all()
    if len(ids) > MAX_PROPOSAL_SCAN:
        raise PublicationUnavailable("Publication inventory requires a paginated policy revision")
    result = []
    for identifier in ids:
        try:
            proposal = await admitted_publication(db, identifier)
        except (PublicationUnavailable, ResearchAccessDenied, ResearchFreezeError, SourceLifecycleError,
                public.PublicResearchVerificationError, capsule.ResearchReleaseVerificationError):
            continue
        result.append({"id": str(proposal["id"]), "payload_sha256": proposal["payload_sha256"],
                       "scope": public.SCOPE, "object_count": len(proposal["public_payload"]["objects"]),
                       "scientific_acceptance": False, "ml_training_approved": False})
    return {"version": VERSION, "items": result, "count": len(result), "scope": public.SCOPE}
