"""Read-only batch context for public material visibility; no review mutations.

This internal wrapper is not a response DTO. It binds live source statuses and
bounded parent ancestry to original material data before scientific projection.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Material, Paper
from services.material_anomalies import material_review, review_context
from services.material_visibility import visibility_allows_view, visibility_for_material

MAX_PARENT_DEPTH = 32
_SQL_BATCH_SIZE = 1000


@dataclass(frozen=True)
class MaterialReadContext:
    material: Any
    visibility: dict[str, Any]
    source_statuses: dict[str, str | None]

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
        r["paper_id"] for m in known.values() for r in (m.records if isinstance(m.records, list) else [])
        if isinstance(r, dict) and isinstance(r.get("paper_id"), str) and r["paper_id"]
    }
    statuses = {}
    # Avoid unbounded SQL parameter lists when a material has many sources.
    identifiers = sorted(paper_ids)
    for start in range(0, len(identifiers), _SQL_BATCH_SIZE):
        rows = (await session.execute(select(Paper.id, Paper.status).where(Paper.id.in_(identifiers[start:start + _SQL_BATCH_SIZE])))).all()
        statuses.update(rows)
    own_sources = {
        material.id: {
            r["paper_id"]: statuses.get(r["paper_id"])
            for r in (material.records if isinstance(material.records, list) else [])
            if isinstance(r, dict) and isinstance(r.get("paper_id"), str) and r["paper_id"]
        }
        for material in known.values()
    }
    resolved = {}

    def assess(mid, *, parent=None, ancestry_error=None):
        material = known[mid]
        anomaly = material_review(material.records, scope_id=material.id, context=review_context(material), compact=True)
        resolved[mid] = visibility_for_material(
            material, anomaly_review=anomaly, source_statuses=own_sources[mid],
            parent_visibility=parent, ancestry_error=ancestry_error,
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

    return [MaterialReadContext(m, resolve(m.id), own_sources[m.id]) for m in originals]


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
    return context if visibility_allows_view(context.visibility, include_archive=True) else None
