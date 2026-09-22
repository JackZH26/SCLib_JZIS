"""Private same-snapshot declaration coverage, never collective scientific signoff."""

from __future__ import annotations

import sqlalchemy as sa

from models.ml_pilot_attestations_v1 import BASIS_FIELDS
from services import ml_pilot_attestation_contract as contract
from services import ml_pilot_attestations as attestations
from services import ml_pilot_review_admission as admission
from services.ml_pilot_documents import json_value
from services.ml_use_access import _read_session

VERSION = "ml08-review-coverage/1.0.0"
COMMON_FIELDS = tuple(
    key
    for key in BASIS_FIELDS
    if key
    not in {
        "own_review_record_count",
        "own_review_records_sha256",
        "conclusion_author_is_current_account",
    }
)


async def inspect(db, **args):
    """Only a newly verified worker result may enter this trusted service.

    A revoked account/grant, withdrawn participation or invalid chronology fails
    the complete check. A new accepted participation head makes older declarations
    stale even when the originals are unchanged. No write or approval token exists.
    """
    await _read_session(db)
    context = await admission.binding_context(db, **args)
    own = context["own"]
    projection = admission.project_member(context, own)
    counts = dict.fromkeys(("current", "missing", "withdrawn", "stale"), 0)
    own_status = "not_required"
    conclusion_current = False
    for member in context["members"]:
        checked = admission.project_member(context, member)
        required = (
            checked["own_review_record_count"] > 0
            or checked["conclusion_author_is_current_account"]
        )
        if not required:
            continue
        basis = {key: checked[key] for key in BASIS_FIELDS}
        latest = await attestations.head(db, member["id"])
        participation = context["participation_heads"][member["id"]]
        if latest is None:
            status = "missing"
        else:
            # Corrupt or foreign bindings fail closed, rather than becoming a
            # benign missing/stale declaration in otherwise complete coverage.
            admission.require(
                latest["actor_user_id"] == member["user_id"]
                and latest["participant_id"] == member["id"]
                and latest["participant_sha256"] == member["record_sha256"]
                and latest["registration_sha256"] == context["registration"]["record_sha256"]
                and latest["action"] in {"attest", "withdraw"}
            )
            if latest["action"] == "withdraw":
                status = "withdrawn"
            elif (
                latest["version"] == attestations.VERSION
                and latest["declaration_version"] == contract.VERSION
                and latest["declaration_sha256"] == contract.SHA256
                and latest["participation_id"] == participation["id"]
                and latest["participation_sha256"] == participation["record_sha256"]
                and latest["basis_sha256"] == attestations.digest(basis)
                and json_value(latest["basis_json"].encode()) == basis
            ):
                status = "current"
            else:
                status = "stale"
        counts[status] += 1
        if member["id"] == own["id"]:
            own_status = status
        if checked["conclusion_author_is_current_account"]:
            conclusion_current = status == "current"
    required_count = sum(counts.values())
    admission.require(2 <= required_count <= 30)
    return {
        **attestations.boundary(),
        "version": VERSION,
        "scope": "private_same_snapshot_account_declaration_coverage_only",
        "actor_user_id": str(own["user_id"]),
        "participant_id": str(own["id"]),
        "participant_sha256": own["record_sha256"],
        "registration_sha256": context["registration"]["record_sha256"],
        **{key: projection[key] for key in COMMON_FIELDS},
        "snapshot_started_at": (
            await db.scalar(sa.select(sa.func.transaction_timestamp()))
        ).isoformat(),
        "historical_snapshot_only": True,
        "current_accounts_and_roles_checked": True,
        "declared_review_times_fit_recorded_participation": True,
        "documentary_binding_checked": True,
        "latest_declaration_heads_checked": True,
        "attestation_recorded": False,
        "required_declaration_count": required_count,
        "matching_declaration_count": counts["current"],
        "missing_declaration_count": counts["missing"],
        "withdrawn_declaration_count": counts["withdrawn"],
        "stale_declaration_count": counts["stale"],
        "account_declarations_complete": counts["current"] == required_count,
        "conclusion_author_declaration_current": conclusion_current,
        "own_declaration_status": own_status,
    }
