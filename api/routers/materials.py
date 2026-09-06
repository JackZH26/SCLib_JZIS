"""GET /materials and GET /materials/{id} — public materials DB.

Section 7 of PROJECT_SPEC marks these as public, so we use
peek_identity (never consumes guest quota). Filters mirror the
frontend MaterialTable controls: family, tc_min, ordering, and
offset/limit pagination.
"""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONPATH
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.db import HydrideTcParameter, Material
from models.search import (
    HydrideTcParameterRecord,
    MaterialDetail,
    MaterialListResponse,
    MaterialSummary,
    PhaseDiagramPoint,
    VariantSummary,
)
from routers.deps import Identity, peek_identity
from services.anomaly_review import eligible_for_property
from services.material_anomalies import record_assessment, review_context
from services.pressure_semantics import classify_pressure
from services.scientific_filters import ResultFilters, matching_result_references
from services.scientific_values import record_quantity

router = APIRouter(tags=["materials"])

@router.get("/materials", response_model=MaterialListResponse)
async def list_materials(
    family: str | None = Query(
        None,
        description=(
            "Filter by material family. Accepts a single slug (``cuprate``) "
            "or a comma-separated list (``cuprate,iron_based``) to match any "
            "of several families with OR semantics."
        ),
    ),
    tc_min: float | None = Query(None, ge=0, allow_inf_nan=False),
    pressure_min: float | None = Query(None, ge=0, allow_inf_nan=False),
    pressure_max: float | None = Query(None, ge=0, allow_inf_nan=False),
    include_unknown_pressure: bool = Query(False),
    knowledge_origin: Literal["Observed", "Computed", "Inferred", "AI-Proposed", "Unknown"] | None = Query(None),
    source_role: Literal["primary", "cited"] | None = Query(None),
    experimental_only: bool = Query(False),
    # v2 filter params
    ambient_sc: bool | None = Query(None, description="True requires an explicit ambient, observed positive result. False is unsupported: absence is not a negative experiment."),
    is_unconventional: bool | None = Query(None),
    has_competing_order: bool | None = Query(None),
    pairing_symmetry: str | None = Query(None),
    structure_phase: str | None = Query(None),
    # P2: parent grouping — when true, only return parent materials
    # (those with no parent_material_id) and include rolled-up
    # total_papers from all variants.
    parents_only: bool = Query(
        False,
        description=(
            "Only return parent materials (no doping variants). "
            "variant_count shows how many children each parent has."
        ),
    ),
    min_tier: str | None = Query(
        None,
        pattern="^(T1|T2|T3)$",
        description=(
            "Only show materials whose best credibility tier is at most "
            "this value (T1 = best). T1 → only T1; T2 → T1 or T2; T3 → T1-T3."
        ),
    ),
    min_papers: int | None = Query(
        None,
        ge=1,
        description="Only show materials cited in at least this many papers.",
    ),
    sort: str = Query("tc_max", pattern="^(tc_max|arxiv_year|total_papers|tc_ambient)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_pending: bool = Query(
        False,
        description=(
            "Include materials flagged needs_review=True (physically "
            "implausible values, usually NER confusing Curie temp / "
            "melting point with Tc). Off by default so the list stays "
            "trustworthy; admins set it to audit / unflag."
        ),
    ),
    include_skeletons: bool = Query(
        False,
        description=(
            "Include materials with ``total_papers = 0`` — typically "
            "NIMS SuperCon reference-only catalog entries that carry "
            "no measured data (Tc / pressure / structure all null). "
            "Off by default so the list surfaces materials with real "
            "content. Turn on to browse the full NIMS index."
        ),
    ),
    only_aps: bool = Query(
        False,
        description="Only show materials that have at least one APS-sourced record.",
    ),
    identity: Identity = Depends(peek_identity),  # noqa: ARG001 — presence sets guest counter header
    db: AsyncSession = Depends(get_db),
) -> MaterialListResponse:
    if ambient_sc is False:
        raise HTTPException(422, "ambient_sc=false is unsupported: missing ambient evidence is not a negative experiment.")
    if pressure_min is not None and pressure_max is not None and pressure_min > pressure_max:
        raise HTTPException(422, "pressure_min cannot exceed pressure_max")
    scientific_filters = ResultFilters(
        families=tuple(s.strip() for s in (family or "").split(",") if s.strip()),
        tc_min=tc_min, pressure_min=pressure_min, pressure_max=pressure_max,
        ambient_only=ambient_sc is True, positive_tc=ambient_sc is True,
        include_unknown_pressure=include_unknown_pressure,
        origins=(knowledge_origin,) if knowledge_origin else (), source_role=source_role,
        experimental_only=experimental_only or ambient_sc is True,
        only_aps=only_aps, min_tier=min_tier,
    )
    stmt = select(Material)
    count_stmt = select(func.count()).select_from(Material)

    def _apply(where_clause):
        nonlocal stmt, count_stmt
        stmt = stmt.where(where_clause)
        count_stmt = count_stmt.where(where_clause)

    # NIMS provenance quarantine — UNCONDITIONAL: the broken NIMS
    # import left the whole NIMS set without Tc/papers, so it is
    # hidden site-wide until re-ingested. Excluded even when admins
    # pass include_pending / include_skeletons (those toggles are for
    # auditing data-quality flags, not for resurfacing quarantined
    # provenance).
    _apply(
        or_(
            Material.review_reason.is_(None),
            Material.review_reason != "provenance_quarantine_nims",
        )
    )

    # Automatic sanity gate. Rows where the aggregator detected an
    # implausible Tc (>250 K at ambient pressure) are hidden from the
    # public list; they remain fetchable via GET /materials/{id} so
    # old bookmarks keep working and admins can reach them to review.
    if not include_pending:
        _apply(Material.needs_review.is_(False))

    # Skeleton entries are rows that came from the NIMS CSV as a bare
    # DOI reference — no Tc, no pressure, total_papers = 0. Hiding
    # them by default keeps the default list feeling informative; the
    # opt-in flag lets admins / power users browse the full catalog.
    if not include_skeletons:
        _apply(Material.total_papers > 0)

    # P2: only return parent materials (those with no parent_material_id)
    if parents_only:
        _apply(Material.parent_material_id.is_(None))

    # Necessary-condition prefilters only: never use aggregate Tc, ambient or
    # best-tier fields to establish a scientific match. Record-family hits must
    # survive even when the catalogue family is absent or stale.
    if scientific_filters.families:
        clauses = [
            f"@.{key} == {json.dumps(slug)}"
            for slug in scientific_filters.families for key in ("family", "material_family")
        ]
        _apply(or_(
            Material.family.in_(scientific_filters.families),
            func.jsonb_path_exists(Material.records, cast("$[*] ? (" + " || ".join(clauses) + ")", JSONPATH)),
        ))
    if only_aps:
        _apply(func.jsonb_path_exists(Material.records, cast('$[*] ? (@.paper_id like_regex "^aps:")', JSONPATH)))

    if is_unconventional is not None:
        _apply(Material.is_unconventional.is_(is_unconventional))
    if has_competing_order is not None:
        _apply(Material.has_competing_order.is_(has_competing_order))
    if pairing_symmetry:
        _apply(Material.pairing_symmetry == pairing_symmetry)
    if structure_phase:
        _apply(Material.structure_phase == structure_phase)
    if min_papers is not None:
        _apply(Material.total_papers >= min_papers)

    sort_col = {
        "tc_max": Material.tc_max,
        "tc_ambient": Material.tc_ambient,
        "arxiv_year": Material.arxiv_year,
        "total_papers": Material.total_papers,
    }[sort]
    # Postgres treats NULLS LAST as an extension — spell it out so
    # "sort by tc_max" doesn't put unmeasured materials on top.
    # A deterministic tie-breaker is required for reproducible exports and
    # pagination.  Many materials share the same sort value (especially NULL),
    # so ordering by the headline field alone can move rows between pages as
    # PostgreSQL changes query plans.
    stmt = stmt.order_by(sort_col.desc().nulls_last(), Material.id.asc())

    if scientific_filters.active:
        # One canonical predicate for Search and Materials. Stream bounded
        # batches so rich/raw pressure notation is not reinterpreted by a
        # divergent SQL shortcut. Count *all* matches before applying paging;
        # never return a capped/estimated count as exact. A versioned indexed
        # result projection is the later performance path, not an implicit
        # relaxation of scientific semantics.
        stream = await db.stream_scalars(stmt.execution_options(yield_per=128))
        selected = []
        total = 0
        try:
            async for material in stream:
                matching = matching_result_references(
                    material.records, scientific_filters, scope_id=material.id,
                    material_family=material.family,
                    compound_thresholds=review_context(material)["compound_thresholds"],
                )
                if not matching:
                    continue
                if offset <= total < offset + limit:
                    summary = MaterialSummary.model_validate(material)
                    summary.matching_results = matching
                    selected.append(summary)
                total += 1
        finally:
            await stream.close()
        return MaterialListResponse(total=total, results=selected, limit=limit, offset=offset)

    total = (await db.execute(count_stmt)).scalar_one()
    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()

    return MaterialListResponse(
        total=total,
        results=[MaterialSummary.model_validate(m) for m in rows],
        limit=limit,
        offset=offset,
    )


@router.get("/materials/{material_id:path}/phase_diagram", response_model=list[PhaseDiagramPoint])
async def material_phase_diagram(
    material_id: str,
    identity: Identity = Depends(peek_identity),  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> list[PhaseDiagramPoint]:
    """Return Tc-vs-doping/pressure data points for a material and all its variants.

    Used by the frontend to render an interactive phase diagram scatter plot.
    Collects record-level data from the parent and all children, extracting
    tc_kelvin, doping_level (or x composition), and pressure_gpa.
    """
    parent = await db.get(Material, material_id)
    if parent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Material {material_id!r} not found")
    # NIMS provenance quarantine — hidden site-wide (see material_detail).
    if parent.review_reason == "provenance_quarantine_nims":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Material {material_id!r} not found")

    # Collect this material + all variants
    materials = [parent]
    if parent.variant_count > 0:
        variant_stmt = (
            select(Material)
            .where(Material.parent_material_id == material_id)
            .where(or_(Material.review_reason.is_(None), Material.review_reason != "provenance_quarantine_nims"))
            .order_by(Material.formula)
        )
        variants = (await db.execute(variant_stmt)).scalars().all()
        materials.extend(variants)

    points: list[PhaseDiagramPoint] = []
    for mat in materials:
        if not isinstance(mat.records, list):
            continue
        for r in mat.records:
            if not isinstance(r, dict):
                continue
            assessment = record_assessment(r, scope_id=mat.id, context=review_context(mat))
            quantity = record_quantity(r, "tc_kelvin", "tc")
            tc = quantity["value"]
            if (not all(eligible_for_property(assessment, field) for field in ("tc_kelvin", "pressure_gpa", "doping_level", "year")) or quantity["status"] != "parsed"
                    or quantity["relation"] != "exact" or quantity["approximate"] or quantity["errors"]
                    or quantity["uncertainty"] is not None or tc is None or tc <= 0):
                continue
            pressure = classify_pressure(r)
            doping = record_quantity(r, "doping_level")
            points.append(PhaseDiagramPoint(
                formula=mat.formula,
                tc_kelvin=float(tc),
                # Doping is an observation-level condition.  Falling back to
                # the material aggregate silently assigns one value to every
                # pressure/sample record and creates false phase-diagram data.
                doping_level=(
                    doping["value"]
                    if doping["status"] == "parsed" and doping["relation"] == "exact"
                    and not doping["errors"] and not doping["approximate"] and doping["uncertainty"] is None
                    else None
                ),
                pressure_gpa=pressure.pressure_gpa if pressure.pressure_state in {"reported", "explicit_ambient"} else None,
                pressure_semantics=pressure.to_dict(),
                paper_id=r.get("paper_id"),
                year=r.get("year") if isinstance(r.get("year"), int) else None,
            ))

    return points


@router.get(
    "/materials/{material_id:path}/hydride_parameters",
    response_model=list[HydrideTcParameterRecord],
)
async def material_hydride_parameters(
    material_id: str,
    identity: Identity = Depends(peek_identity),  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> list[HydrideTcParameterRecord]:
    """Return hydride-specific Tc/pressure/lambda/mu*/omega_log rows.

    This is an enrichment layer produced by the independent hydride NER
    runner. It is intentionally not folded into the generic material detail
    schema because the parameters are meaningful mainly for superhydrides
    and need separate validation/provenance.
    """
    m = await db.get(Material, material_id)
    if m is None or m.review_reason == "provenance_quarantine_nims":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Material {material_id!r} not found")

    stmt = (
        select(HydrideTcParameter)
        .where(HydrideTcParameter.material_id == material_id)
        .order_by(
            HydrideTcParameter.pressure_gpa.asc().nulls_last(),
            HydrideTcParameter.tc_kelvin.desc().nulls_last(),
            HydrideTcParameter.year.desc().nulls_last(),
        )
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [HydrideTcParameterRecord.model_validate(r) for r in rows]


@router.get("/materials/{material_id:path}", response_model=MaterialDetail)
async def material_detail(
    material_id: str,
    identity: Identity = Depends(peek_identity),  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> MaterialDetail:
    m = await db.get(Material, material_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Material {material_id!r} not found")
    # NIMS provenance quarantine: treat as non-existent publicly (the
    # NIMS import is broken — Tc/papers missing — so the whole NIMS
    # set is hidden site-wide until re-ingested). Same 404 as missing
    # so it's indistinguishable from a bad id.
    if m.review_reason == "provenance_quarantine_nims":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Material {material_id!r} not found")

    detail = MaterialDetail.model_validate(m)

    # P2: populate variants list if this material has children
    if m.variant_count > 0:
        variant_stmt = (
            select(Material)
            .where(Material.parent_material_id == material_id)
            .where(or_(Material.review_reason.is_(None), Material.review_reason != "provenance_quarantine_nims"))
            .order_by(Material.tc_max.desc().nulls_last(), Material.id.asc())
            .limit(100)
        )
        variants = (await db.execute(variant_stmt)).scalars().all()
        detail.variants = [VariantSummary.model_validate(v) for v in variants]

    return detail
