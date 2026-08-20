"""Phase-1 helpers for turning legacy SCLib records into typed claims.

The package is deliberately database-free.  Migrations and ingestion jobs can
use the pure functions here without importing the API ORM or opening a
production connection.
"""

from ingestion.claims.mapper import CLAIM_MAPPER_VERSION, map_record_to_claim
from ingestion.claims.work_identity import (
    WORK_IDENTITY_VERSION,
    WorkIdentityConflict,
    canonicalize_arxiv_id,
    canonicalize_doi,
    plan_work_identities,
)

__all__ = [
    "CLAIM_MAPPER_VERSION",
    "WORK_IDENTITY_VERSION",
    "WorkIdentityConflict",
    "canonicalize_arxiv_id",
    "canonicalize_doi",
    "map_record_to_claim",
    "plan_work_identities",
]
