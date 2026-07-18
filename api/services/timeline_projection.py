"""Transactional refresh and read path for the Timeline projection."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import (
    Material,
    Paper,
    TimelineProjectionPoint,
    TimelineProjectionState,
)
from models.search import TimelinePoint
from services.timeline_points import extract_timeline_points, missing_year_paper_ids


PROJECTION_SCHEMA_VERSION = 1
_STATE_ID = 1
_WATERMARK_OVERLAP = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class ProjectionRefreshResult:
    full_rebuild: bool
    materials_processed: int
    active_materials: int
    active_points: int
    refreshed_at: datetime


@dataclass(frozen=True, slots=True)
class ProjectionReadResult:
    points: list[TimelinePoint]
    refreshed_at: datetime


def _date_year(value) -> int | None:
    return value.year if value is not None else None


async def refresh_timeline_projection(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> ProjectionRefreshResult:
    """Refresh changed materials atomically without touching source JSONB.

    The caller owns the transaction. Existing rows for each changed material
    are soft-disabled before the current deterministic point set is upserted.
    If any statement fails, the transaction rolls back and the previous ready
    projection remains visible.
    """
    refreshed_at = now or datetime.now(UTC)
    current_year = refreshed_at.year
    state = await session.get(TimelineProjectionState, _STATE_ID)
    full_rebuild = (
        state is None
        or state.schema_version != PROJECTION_SCHEMA_VERSION
        or state.source_year != current_year
    )
    if full_rebuild:
        await session.execute(
            update(TimelineProjectionPoint).values(
                active=False,
                updated_at=func.now(),
            )
        )

    materials_stmt = select(
        Material.id,
        Material.records,
        Material.updated_at,
    ).where(Material.updated_at <= refreshed_at)
    if not full_rebuild and state is not None:
        materials_stmt = materials_stmt.where(
            Material.updated_at >= state.source_watermark
        )
    materials_stmt = materials_stmt.order_by(Material.id)
    materials = (await session.execute(materials_stmt)).all()

    paper_ids: set[str] = set()
    for _material_id, records, _source_updated_at in materials:
        paper_ids.update(missing_year_paper_ids(records))

    paper_years: dict[str, int] = {}
    if paper_ids:
        paper_rows = await session.execute(
            select(Paper.id, Paper.date_published, Paper.date_submitted).where(
                Paper.id.in_(sorted(paper_ids))
            )
        )
        for paper_id, date_published, date_submitted in paper_rows.all():
            year = _date_year(date_published) or _date_year(date_submitted)
            if year is not None:
                paper_years[paper_id] = year

    projection_table = TimelineProjectionPoint.__table__
    for material_id, records, source_updated_at in materials:
        points = extract_timeline_points(
            material_id,
            records,
            paper_years,
            current_year=current_year,
        )
        await session.execute(
            update(TimelineProjectionPoint)
            .where(TimelineProjectionPoint.material_id == material_id)
            .values(active=False, updated_at=func.now())
        )
        if not points:
            continue

        values = [
            {
                "id": point.id,
                "material_id": point.material_id,
                "year": point.year,
                "tc_kelvin": point.tc_kelvin,
                "pressure_gpa": point.pressure_gpa,
                "paper_id": point.paper_id,
                "is_theoretical": point.is_theoretical,
                "is_aps": point.is_aps,
                "active": True,
                "source_updated_at": source_updated_at,
            }
            for point in points
        ]
        insert_stmt = pg_insert(projection_table).values(values)
        await session.execute(
            insert_stmt.on_conflict_do_update(
                index_elements=[projection_table.c.id],
                set_={
                    "year": insert_stmt.excluded.year,
                    "tc_kelvin": insert_stmt.excluded.tc_kelvin,
                    "pressure_gpa": insert_stmt.excluded.pressure_gpa,
                    "paper_id": insert_stmt.excluded.paper_id,
                    "is_theoretical": insert_stmt.excluded.is_theoretical,
                    "is_aps": insert_stmt.excluded.is_aps,
                    "active": True,
                    "source_updated_at": insert_stmt.excluded.source_updated_at,
                    "updated_at": func.now(),
                },
            )
        )

    counts = (
        await session.execute(
            select(
                func.count(TimelineProjectionPoint.id),
                func.count(func.distinct(TimelineProjectionPoint.material_id)),
            ).where(TimelineProjectionPoint.active.is_(True))
        )
    ).one()
    active_points = int(counts[0] or 0)
    active_materials = int(counts[1] or 0)
    next_watermark = refreshed_at - _WATERMARK_OVERLAP

    state_table = TimelineProjectionState.__table__
    state_insert = pg_insert(state_table).values(
        id=_STATE_ID,
        schema_version=PROJECTION_SCHEMA_VERSION,
        source_year=current_year,
        source_watermark=next_watermark,
        refreshed_at=refreshed_at,
        material_count=active_materials,
        active_point_count=active_points,
    )
    await session.execute(
        state_insert.on_conflict_do_update(
            index_elements=[state_table.c.id],
            set_={
                "schema_version": state_insert.excluded.schema_version,
                "source_year": state_insert.excluded.source_year,
                "source_watermark": state_insert.excluded.source_watermark,
                "refreshed_at": state_insert.excluded.refreshed_at,
                "material_count": state_insert.excluded.material_count,
                "active_point_count": state_insert.excluded.active_point_count,
            },
        )
    )

    return ProjectionRefreshResult(
        full_rebuild=full_rebuild,
        materials_processed=len(materials),
        active_materials=active_materials,
        active_points=active_points,
        refreshed_at=refreshed_at,
    )


async def fetch_projected_timeline_points(
    session: AsyncSession,
    *,
    family: str | None,
    include_pending: bool,
    experimental_only: bool,
    only_aps: bool,
    current_year: int | None = None,
) -> ProjectionReadResult | None:
    """Return projected points, or ``None`` until a compatible build is ready."""
    expected_year = current_year or datetime.now(UTC).year
    state = await session.get(TimelineProjectionState, _STATE_ID)
    if (
        state is None
        or state.schema_version != PROJECTION_SCHEMA_VERSION
        or state.source_year != expected_year
    ):
        return None

    point = TimelineProjectionPoint
    stmt = (
        select(
            Material.formula,
            Material.formula_latex,
            Material.family,
            point.tc_kelvin,
            point.year,
            point.pressure_gpa,
            point.paper_id,
            point.is_theoretical,
        )
        .join(point, point.material_id == Material.id)
        .where(point.active.is_(True))
    )
    if family:
        stmt = stmt.where(Material.family == family)
    if not include_pending:
        stmt = stmt.where(Material.needs_review.is_(False))
    if experimental_only:
        stmt = stmt.where(point.is_theoretical.is_(False))
    if only_aps:
        stmt = stmt.where(point.is_aps.is_(True))
    stmt = stmt.order_by(point.year, point.tc_kelvin.desc(), point.id)

    rows = (await session.execute(stmt)).all()
    points = [
        TimelinePoint(
            material=formula,
            formula_latex=formula_latex,
            family=material_family,
            tc_kelvin=tc_kelvin,
            year=year,
            pressure_gpa=pressure_gpa,
            paper_id=paper_id,
            is_theoretical=is_theoretical,
        )
        for (
            formula,
            formula_latex,
            material_family,
            tc_kelvin,
            year,
            pressure_gpa,
            paper_id,
            is_theoretical,
        ) in rows
    ]
    return ProjectionReadResult(points=points, refreshed_at=state.refreshed_at)
