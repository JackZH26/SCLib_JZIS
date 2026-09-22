"""Read-only batch context for public material visibility; no review mutations.

This internal wrapper is not a response DTO. It binds live source statuses and
bounded parent ancestry to original material data before scientific projection.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Material
from services.material_source_scope import (
    SourceScope,
    SourceScopeError,
    current_visibility_allows_view,
    scoped_material_visibility,
    validate_scoped_visibility,
)
from services.material_visibility import MATERIAL_VISIBILITY_VERSION, normalize_source_status
from services.source_lifecycle import resolve_paper_lifecycle

MAX_PARENT_DEPTH = 32
_SQL_BATCH_SIZE = 1000


def _lookup_paper_id(record):
    """Look up every representable legacy key; never normalize its identity.

    Legacy SQL rows may have surrounding spaces/control characters. They must
    still be checked for negative lifecycle state, even though those IDs cannot
    contribute eligible records to a new strict source scope.
    """
    value = record.get("paper_id") if isinstance(record, dict) else None
    if type(value) is not str or not 0 < len(value) <= 100 or "\x00" in value:
        return None
    try:
        value.encode("utf-8")
    except UnicodeError:
        return None
    return value


def _scope_paper_id(record):
    """Only exact canonical identifiers can enter the eligible source map."""
    value = record.get("paper_id") if isinstance(record, dict) else None
    return (value if type(value) is str and 0 < len(value) <= 100
            and value == value.strip() and not any(ord(char) < 32 for char in value) else None)


@dataclass(frozen=True)
class MaterialReadContext:
    material: Any
    visibility: dict[str, Any]
    source_statuses: dict[str, Any]
    source_scope: SourceScope | None = None

    def current_records(self):
        """Detached eligible records for scoped reads; never renumber raw data."""
        if self.source_scope is not None:
            summary = validate_scoped_visibility(self.visibility)["source_scope"]
            if (self.source_scope.material_id != self.id
                    or self.source_scope.fingerprint != summary["fingerprint"]
                    or len(self.source_scope.indices) != summary["total_records"]
                    or len(self.source_scope.eligible_indices) != summary["eligible_records"]
                    or len(self.source_scope.eligible_paper_ids) != summary["eligible_source_count"]):
                raise SourceScopeError("source_scope_context_mismatch")
            return self.source_scope.eligible_records(self.records)
        return self.records

    def record_visibility(self, index: int) -> dict[str, Any]:
        """Archive records cannot inherit an eligible mixed material's badge."""
        if self.source_scope is None:
            return self.visibility
        scope = self.source_scope
        eligible = index in scope.eligible_indices
        reasons = list(scope.reason_codes[index]) if not eligible else []
        revision = hashlib.sha256(
            f"{self.visibility['review_revision']}:{index}:{scope.record_sha256[index]}".encode()
        ).hexdigest()
        return {
            **{key: value for key, value in self.visibility.items() if key != "source_scope"},
            "version": MATERIAL_VISIBILITY_VERSION,
            "state": "catalogue" if eligible else "pending",
            "public_catalogue_eligible": eligible,
            "scientific_acceptance": False,
            "reason_codes": reasons,
            "reason_messages": [] if eligible else ["This retained record is excluded from current source-scoped summaries."],
            "review_revision": revision,
            "source_status": normalize_source_status(self.source_statuses.get(scope.paper_ids[index])),
        }

    def __getattr__(self, name):
        source = object.__getattribute__(self, "material")
        if isinstance(source, dict):
            if name in source:
                return source[name]
            raise AttributeError(name)
        return getattr(source, name)


def material_prefilter(*, include_archive=False):
    """Necessary SQL prefilter only; final policy evaluates live context."""
    clauses = [or_(Material.review_reason.is_(None), ~Material.review_reason.startswith("provenance_quarantine"))]
    if not include_archive:
        clauses += [Material.needs_review.is_(False), Material.disputed.is_not(True), Material.retracted.is_not(True)]
    return clauses


async def prepare_material_views(session: AsyncSession, materials) -> list[MaterialReadContext]:
    """Preserve order; batch-load source membership and inherited parent holds.

    Missing/cyclic/depth-exhausted parents cannot confer public Archive access.
    No family/formula matching establishes an ancestry or source identity.
    """
    originals = list(materials)
    if not originals:
        return []
    known = {m.id: m for m in originals}
    frontier = {m.parent_material_id for m in originals if m.parent_material_id} - known.keys()
    looked_up = set(known)
    for _ in range(MAX_PARENT_DEPTH):
        if not frontier:
            break
        identifiers = sorted(frontier)
        looked_up.update(identifiers)
        rows = []
        for start in range(0, len(identifiers), _SQL_BATCH_SIZE):
            rows.extend((await session.execute(
                select(Material).where(Material.id.in_(identifiers[start:start + _SQL_BATCH_SIZE])),
            )).scalars().all())
        known.update((m.id, m) for m in rows)
        frontier = {m.parent_material_id for m in rows if m.parent_material_id} - looked_up
    paper_ids = {
        identifier for m in known.values() for r in (m.records if isinstance(m.records, list) else [])
        if (identifier := _lookup_paper_id(r)) is not None
    }
    statuses = {}
    identifiers = sorted(paper_ids)
    for start in range(0, len(identifiers), _SQL_BATCH_SIZE):
        statuses.update(await resolve_paper_lifecycle(session, identifiers[start:start + _SQL_BATCH_SIZE]))
    own_sources = {
        material.id: {
            identifier: statuses.get(identifier)
            for r in (material.records if isinstance(material.records, list) else [])
            if (identifier := _scope_paper_id(r)) is not None
        }
        for material in known.values()
    }
    # Preserve exactly the legacy nonempty-string source inventory for v1's
    # malformed-metadata checks, without sending unrepresentable keys to SQL.
    # Dropping an overlong key entirely would turn a hold into ordinary unknown.
    fallback_sources = {
        material.id: {
            record["paper_id"]: statuses.get(record["paper_id"])
            for record in (material.records if isinstance(material.records, list) else [])
            if isinstance(record, dict) and isinstance(record.get("paper_id"), str) and record["paper_id"]
        }
        for material in known.values()
    }
    resolved, scopes = {}, {}

    def assess(mid, *, parent=None, ancestry_error=None):
        material = known[mid]
        resolved[mid], scopes[mid] = scoped_material_visibility(
            material, source_statuses=own_sources[mid],
            parent_visibility=parent, ancestry_error=ancestry_error,
            fallback_source_statuses=fallback_sources[mid],
        )

    def resolve(mid):
        if mid in resolved:
            return resolved[mid]
        chain, error = _ancestry_chain(mid, known)
        if error is not None:
            # Do not recursively build/cross-cache a partial cycle: that would
            # make revisions depend on which sibling was requested first.
            assess(mid, ancestry_error=error)
        else:
            for identity in reversed(chain):
                if identity not in resolved:
                    parent_id = known[identity].parent_material_id
                    assess(identity, parent=resolved.get(parent_id) if parent_id else None)
        return resolved[mid]

    return [MaterialReadContext(m, resolve(m.id), own_sources[m.id], scopes[m.id]) for m in originals]


def _ancestry_chain(material_id, known):
    """Check up to 32 parent edges independently of traversal/cache order.

    Including unrelated/preloaded ancestors does not relax the same depth
    limit. Errors carry no private identifiers or source/reviewer text.
    """
    chain, seen = [], set()
    current = material_id
    for _ in range(MAX_PARENT_DEPTH + 1):
        if current in seen:
            return chain, "cyclic_parent"
        if current not in known:
            return chain, "missing_parent"
        seen.add(current)
        chain.append(current)
        parent = known[current].parent_material_id
        if not parent:
            return chain, None
        current = parent
    return chain, "depth_exceeded"


async def material_view(session: AsyncSession, material) -> MaterialReadContext | None:
    if material is None:
        return None
    context = (await prepare_material_views(session, [material]))[0]
    return context if current_visibility_allows_view(context.visibility, include_archive=True) else None
