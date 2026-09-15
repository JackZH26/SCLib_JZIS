"""Authenticated byte replay and joint account snapshot; no scientific acceptance."""

from __future__ import annotations

from services import ml_pilot_attestations as attestations
from services import ml_pilot_evidence_worker as worker
from services import ml_pilot_review_coverage as coverage

VERSION = "ml08-evidence-inspection/1.0.0"


async def inspect(db, *, actor_user_id, worker_result):
    # This entry is only for the trusted route's newly executed owned worker.
    # A cached/browser-supplied proof is never an accepted HTTP input.
    value = worker.checked(worker_result)
    account_snapshot = await coverage.inspect(
        db,
        actor_user_id=actor_user_id,
        **value["parameters"],
        document_check=value["document_check"],
        implementation=value["implementation"],
    )
    return {
        **attestations.boundary(),
        "version": VERSION,
        "scope": "private_authenticated_byte_integrity_not_scientific_acceptance",
        "actor_user_id": account_snapshot["actor_user_id"],
        "participant_id": account_snapshot["participant_id"],
        "participant_sha256": account_snapshot["participant_sha256"],
        "registration_sha256": account_snapshot["registration_sha256"],
        "evidence_input_sha256": value["input_sha256"],
        "canary": value["canary_check"],
        "account_snapshot": account_snapshot,
        "context_bytes_checked": True,
        "canary_replay_verified": True,
        "attestation_recorded": False,
    }
