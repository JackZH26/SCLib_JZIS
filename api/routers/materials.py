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
from models.db import HydrideTcParameter, Material, Paper
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
from services.material_anomalies import material_review, record_assessment, review_context
from services.material_property_projection import project_material_semantics
from services.material_visibility import (
    sanitize_review_metadata,
    visibility_allows_view,
    visibility_for_material,
)
from services.material_visibility_adapter import (
    material_prefilter,
    material_view,
    prepare_material_views,
)
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
    is_unconventional: bool | None = Query(None, description="Reported classification summary, not a family prior or a joint Tc/state predicate."),
    has_competing_order: bool | None = Query(None, description="Reported classification summary. False requires qualified explicit absence; missing evidence does not match."),
    pairing_symmetry: str | None = Query(None, max_length=100, description="Reported pairing classification, not a family default or joint Tc/state predicate."),
    structure_phase: str | None = Query(None, max_length=100, description="Unavailable until reviewed local material/state/structure associations exist. Nonempty values return 422; pending text proposals are not filterable physical properties."),
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
        description="Legacy catalogue source-link threshold; may include parent rollups and does not count independent replications.",
    ),
    sort: str = Query("tc_max", pattern="^(tc_max|arxiv_year|total_papers|tc_ambient)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_pending: bool = Query(
        False,
        description=(
            "Include Archive materials with explicit pending/disputed/source warnings. "
            "This does not waive provenance quarantine or establish scientific acceptance."
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
    if structure_phase:
        raise HTTPException(422, "structure_phase filtering is unavailable until reviewed material/state associations exist. Inspect pending structure_evidence proposals; text labels are not coordinate structures.")
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
    def _apply(where_clause):
        nonlocal stmt
        stmt = stmt.where(where_clause)

    for clause in material_prefilter(include_archive=include_pending):
        _apply(clause)

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

    # Historical scalar/default/weighted-vote columns are not valid necessary
    # prefilters: they can both include a prior and exclude a reported value.
    classification_filters = {
        key: value for key, value in {
            "is_unconventional": is_unconventional,
            "has_competing_order": has_competing_order,
            "pairing_symmetry": pairing_symmetry,
        }.items() if value is not None and value != ""
    }
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

    # Count after the SAME live visibility/record policy used for returned rows.
    # SQL is only a necessary prefilter; stale aggregate holds cannot approve a row.
    stream = await db.stream_scalars(stmt.execution_options(yield_per=128))
    selected, total = [], 0
    try:
        async for batch in stream.partitions(128):
            for material in await prepare_material_views(db, batch):
                if not visibility_allows_view(material.visibility, include_archive=include_pending):
                    continue
                if classification_filters:
                    semantics = project_material_semantics(material)
                    if any(
                        semantics["properties"][field]["status"] != "reported"
                        or type(semantics["properties"][field]["value"]) is not type(expected)
                        or semantics["properties"][field]["value"] != expected
                        for field, expected in classification_filters.items()
                    ):
                        continue
                matching = matching_result_references(
                    material.records, scientific_filters, scope_id=material.id,
                    material_family=material.family,
                    compound_thresholds=review_context(material)["compound_thresholds"],
                ) if scientific_filters.active else []
                if scientific_filters.active and not matching:
                    continue
                if offset <= total < offset + limit:
                    summary = MaterialSummary.model_validate(material)
                    summary.matching_results = [{**record, "visibility": material.visibility} for record in matching]
                    selected.append(summary)
                total += 1
    finally:
        await stream.close()
    return MaterialListResponse(total=total, results=selected, limit=limit, offset=offset)


@router.get("/materials/{material_id:path}/phase_diagram", response_model=list[PhaseDiagramPoint])
async def material_phase_diagram(
    material_id: str,
    include_pending: bool = Query(False, description="Archive opt-in; scientific anomaly gates still apply."),
    identity: Identity = Depends(peek_identity),  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> list[PhaseDiagramPoint]:
    """Return Tc-vs-doping/pressure data points for a material and all its variants.

    Used by the frontend to render an interactive phase diagram scatter plot.
    Collects record-level data from the parent and all children, extracting
    tc_kelvin, doping_level (or x composition), and pressure_gpa.
    """
    parent = await material_view(db, await db.get(Material, material_id))
    if parent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Material {material_id!r} not found")
    if not visibility_allows_view(parent.visibility, include_archive=include_pending):
        return []

    # Collect this material + all variants
    materials = [parent.material]
    variant_stmt = (
        select(Material)
        .where(Material.parent_material_id == material_id)
        .where(*material_prefilter(include_archive=include_pending))
        .order_by(Material.formula, Material.id)
    )
    variants = (await db.execute(variant_stmt)).scalars().all()
    materials.extend(variants)

    points: list[PhaseDiagramPoint] = []
    for mat in await prepare_material_views(db, materials):
        if not visibility_allows_view(mat.visibility, include_archive=include_pending):
            continue
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
                formula=mat.formula, material_id=mat.id, visibility=mat.visibility,
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
                pressure_semantics=sanitize_review_metadata(pressure.to_dict()),
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
    include_pending: bool = Query(False, description="Archive opt-in; not validated paired calculation inputs."),
    identity: Identity = Depends(peek_identity),  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> list[HydrideTcParameterRecord]:
    """Return hydride-specific Tc/pressure/lambda/mu*/omega_log rows.

    This is an enrichment layer produced by the independent hydride NER
    runner. It is intentionally not folded into the generic material detail
    schema because the parameters are meaningful mainly for superhydrides
    and need separate validation/provenance.
    """
    m = await material_view(db, await db.get(Material, material_id))
    if m is None:
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
    if not visibility_allows_view(m.visibility, include_archive=include_pending):
        return []
    rows = (await db.execute(stmt)).scalars().all()
    paper_ids = {r.paper_id for r in rows}
    statuses = dict((await db.execute(select(Paper.id, Paper.status).where(Paper.id.in_(paper_ids)))).all()) if paper_ids else {}
    result = []
    for row in rows:
        raw = {column.name: getattr(row, column.name) for column in HydrideTcParameter.__table__.columns}
        raw["status"] = "active_research"
        flags = raw.get("validation_flags")
        raw["needs_review"] = not isinstance(flags, list) or bool(flags)
        # Use the retained typed proposal when present: a normalized scalar
        # must not erase an original range, unit conflict or invalid value.
        provenance = raw.get("provenance")
        proposal = provenance.get("extraction_proposal") if isinstance(provenance, dict) else None
        if isinstance(proposal, dict) and "scientific_values" in proposal:
            raw["scientific_values"] = proposal["scientific_values"]
        # This enrichment row is independently sourced, not a scientific approval
        # inherited from a material catalogue entry.
        anomaly = material_review([raw], scope_id=f"hydride:{row.id}", context=review_context(m), compact=True)
        visibility = visibility_for_material(raw, anomaly_review=anomaly,
                        source_statuses={row.paper_id: statuses.get(row.paper_id)}, parent_visibility=m.visibility)
        if not visibility_allows_view(visibility, include_archive=include_pending):
            continue
        public = sanitize_review_metadata(raw)
        public["created_at"], public["updated_at"] = row.created_at, row.updated_at
        # Malformed legacy JSON remains held, but must not crash Archive reads.
        if not isinstance(flags, list):
            public["validation_flags"] = ["invalid_validation_flags_requires_review"]
        if not isinstance(public.get("provenance"), dict):
            public["provenance"] = {}
        dto = HydrideTcParameterRecord.model_validate(public)
        dto.visibility = visibility
        result.append(dto)
    return result


@router.get("/materials/{material_id:path}", response_model=MaterialDetail)
async def material_detail(
    material_id: str,
    identity: Identity = Depends(peek_identity),  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> MaterialDetail:
    m = await material_view(db, await db.get(Material, material_id))
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Material {material_id!r} not found")
    detail = MaterialDetail.model_validate(m)
    # Do not use a stale aggregate variant_count as an authorization/existence
    # gate. Count currently Archive-accessible children before limiting display.
    variant_stmt = (
        select(Material)
        .where(Material.parent_material_id == material_id)
        .where(*material_prefilter(include_archive=True))
        .order_by(Material.tc_max.desc().nulls_last(), Material.id.asc())
    )
    variants = (await db.execute(variant_stmt)).scalars().all()
    views = [v for v in await prepare_material_views(db, variants)
             if visibility_allows_view(v.visibility, include_archive=True)]
    detail.variant_count = len(views)
    detail.variants = [VariantSummary.model_validate(v) for v in views[:100]]

    return detail
