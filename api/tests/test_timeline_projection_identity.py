"""Real-database identity, source-date freshness, and raw-fallback parity."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from models.db import Material, Paper, TimelineProjectionPoint, TimelineProjectionState
from routers.timeline import _build_timeline_fallback
from services.timeline_projection import (
    fetch_projected_timeline_points,
    refresh_timeline_projection,
)


async def _seed(session, *, with_year=False, with_dates=True):
    suffix = uuid4().hex
    old = datetime.now(UTC) - timedelta(days=2)
    papers = [Paper(
        id=f"{source}:projection-{suffix}", source=source,
        title="Projection identity fixture", authors=[], abstract="Test only.",
        status="published", date_published=date(2020, 4, 3) if with_dates else None,
        date_submitted=date(2019, 10, 2) if with_dates else None, updated_at=old,
    ) for source in ("arxiv", "aps")]
    session.add_all(papers)
    await session.flush()
    records = [{
        "tc_kelvin": 10.02, "pressure_gpa": 1, "paper_id": paper.id,
        "knowledge_origin": "Observed", "measurement": "resistivity",
        "tc_criterion": "onset" if index == 0 else "zero_resistance",
        **({"measurement_year": 2018} if with_year else {}),
    } for index, paper in enumerate(papers)]
    material = Material(
        id=f"mat:projection-{suffix}", formula=f"Pt{suffix[:8]}",
        formula_normalized=f"pt-{suffix}", family=f"projection-{suffix[:20]}",
        records=records, needs_review=False, status="active_research", updated_at=old,
    )
    session.add(material)
    await session.flush()
    return material, papers


async def _read(session, material, **options):
    return await fetch_projected_timeline_points(
        session, family=material.family, include_pending=False,
        experimental_only=False, only_aps=False, **options,
    )


async def _fallback(session, material, *, only_aps=False):
    return await _build_timeline_fallback(
        family=material.family, include_pending=False,
        experimental_only=False, only_aps=only_aps,
        max_points=None, offset=0, limit=None, db=session,
    )


@pytest.mark.asyncio
async def test_projection_fallback_parity_keeps_distinct_sources_and_ids(db_session):
    material, _ = await _seed(db_session)
    raw_before = deepcopy(material.records)
    await refresh_timeline_projection(db_session)
    projected = await _read(db_session, material)
    fallback = await _fallback(db_session, material)
    assert projected is not None and len(projected.points) == 2
    assert [point.model_dump() for point in projected.points] == [point.model_dump() for point in fallback.points]
    assert len({point.point_id for point in projected.points}) == 2
    assert all(point.result_metadata["review_status"] == "legacy_unreviewed" for point in projected.points)
    assert all(point.result_metadata["year_basis"] == "source_publication_date" for point in projected.points)
    assert material.records == raw_before
    await db_session.rollback()


@pytest.mark.asyncio
async def test_record_permutation_and_source_filter_preserve_occurrence_ids(db_session):
    material, _ = await _seed(db_session, with_year=True)
    await refresh_timeline_projection(db_session)
    first = await _read(db_session, material)
    assert first is not None
    ids = {point.paper_id: point.point_id for point in first.points}
    material.records = list(reversed(material.records))
    await db_session.flush()
    await refresh_timeline_projection(db_session)
    second = await _read(db_session, material)
    assert second is not None
    assert {point.paper_id: point.point_id for point in second.points} == ids
    aps = await fetch_projected_timeline_points(
        db_session, family=material.family, include_pending=False,
        experimental_only=False, only_aps=True,
    )
    assert aps is not None and len(aps.points) == 1
    assert aps.points[0].point_id == ids[aps.points[0].paper_id]
    assert [point.model_dump() for point in aps.points] == [point.model_dump() for point in (await _fallback(db_session, material, only_aps=True)).points]
    await db_session.rollback()


@pytest.mark.asyncio
async def test_paper_date_change_without_material_change_invalidates_and_refreshes(db_session):
    material, papers = await _seed(db_session)
    await refresh_timeline_projection(db_session)
    initial = await _read(db_session, material)
    assert initial is not None
    original_updated = material.updated_at
    papers[0].date_published = date(2021, 6, 7)
    papers[0].updated_at = datetime.now(UTC)
    await db_session.flush()
    assert material.updated_at == original_updated
    assert await _read(db_session, material) is None
    raw = await _fallback(db_session, material)
    assert {point.year for point in raw.points} == {2020, 2021}
    refreshed = await refresh_timeline_projection(db_session)
    assert refreshed.full_rebuild
    current = await _read(db_session, material)
    assert current is not None
    assert [point.model_dump() for point in current.points] == [point.model_dump() for point in raw.points]
    await db_session.rollback()


@pytest.mark.asyncio
async def test_new_source_date_recovers_previously_absent_occurrences(db_session):
    material, papers = await _seed(db_session, with_dates=False)
    await refresh_timeline_projection(db_session)
    initial = await _read(db_session, material)
    assert initial is not None and initial.points == []
    papers[0].date_submitted = date(2019, 5, 1)
    papers[0].updated_at = datetime.now(UTC)
    await db_session.flush()
    assert await _read(db_session, material) is None
    refresh = await refresh_timeline_projection(db_session)
    assert refresh.full_rebuild
    current = await _read(db_session, material)
    assert current is not None and len(current.points) == 1
    assert current.points[0].year == 2019
    assert current.points[0].result_metadata["year_basis"] == "source_submission_date"
    await db_session.rollback()


@pytest.mark.asyncio
async def test_removed_paper_cannot_leave_an_inferred_publication_year(db_session):
    material, papers = await _seed(db_session)
    await refresh_timeline_projection(db_session)
    assert await _read(db_session, material) is not None
    await db_session.delete(papers[0])
    await db_session.flush()
    assert await _read(db_session, material) is None
    rebuilt = await refresh_timeline_projection(db_session)
    assert rebuilt.full_rebuild
    projected = await _read(db_session, material)
    assert projected is not None and len(projected.points) == 1
    assert all("_projection_source_snapshot" not in point.result_metadata for point in projected.points)
    assert [point.model_dump() for point in projected.points] == [point.model_dump() for point in (await _fallback(db_session, material)).points]
    await db_session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt", ([], {"version": "legacy/0"}))
async def test_corrupt_projection_metadata_uses_current_raw_fallback(db_session, corrupt):
    material, _ = await _seed(db_session)
    await refresh_timeline_projection(db_session)
    point_id = (await db_session.execute(select(TimelineProjectionPoint.id).where(
        TimelineProjectionPoint.material_id == material.id,
    ).limit(1))).scalar_one()
    await db_session.execute(update(TimelineProjectionPoint).where(
        TimelineProjectionPoint.id == point_id,
    ).values(result_metadata=corrupt))
    assert await _read(db_session, material) is None
    assert len((await _fallback(db_session, material)).points) == 2
    await db_session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", (
    {"review_status": "accepted"},
    {"state": {"private_payload": "not part of the scientific contract"}},
    {"state": {"sample_id": {"review_status": "accepted"}}},
    {"source_locator": {"page": [1, 2]}},
    {"source_locator": {"private_notes": "confidential"}},
    {"source_locator": {"section": "x" * 121}},
    {"occurrence_count": True},
    {"occurrence_count": 0},
    {"result_id": "x" * 501},
    {"result_revision": {"approved": True}},
    {"source_version": True},
    {"source_date": "not-a-date"},
    {"year_basis": "discovery_date"},
    {"chronology_warnings": ["accepted"]},
    {"identity_warnings": ["accepted"]},
    {"scientific_acceptance": True},
))
async def test_current_version_cannot_authorize_malformed_or_accepted_derived_metadata(db_session, mutation):
    material, _ = await _seed(db_session)
    await refresh_timeline_projection(db_session)
    point = (await db_session.execute(select(TimelineProjectionPoint).where(
        TimelineProjectionPoint.material_id == material.id,
    ).limit(1))).scalar_one()
    # Core update is deliberate: Python dict equality considers True == 1,
    # whereas PostgreSQL JSONB preserves boolean versus integer semantics.
    await db_session.execute(update(TimelineProjectionPoint).where(
        TimelineProjectionPoint.id == point.id,
    ).values(result_metadata={**point.result_metadata, **mutation}))
    assert await _read(db_session, material) is None
    fallback = await _fallback(db_session, material)
    assert len(fallback.points) == 2
    assert all(item.result_metadata["review_status"] == "legacy_unreviewed" for item in fallback.points)
    await db_session.rollback()


@pytest.mark.asyncio
async def test_nonfinite_derived_pressure_cannot_crash_or_escape_projection(db_session):
    material, _ = await _seed(db_session)
    await refresh_timeline_projection(db_session)
    await db_session.execute(update(TimelineProjectionPoint).where(
        TimelineProjectionPoint.material_id == material.id,
    ).values(pressure_gpa=float("nan")))
    assert await _read(db_session, material) is None
    assert all(point.pressure_gpa == 1 for point in (await _fallback(db_session, material)).points)
    await db_session.rollback()


@pytest.mark.asyncio
async def test_new_material_not_in_old_projection_invalidates_read(db_session):
    material, _ = await _seed(db_session)
    await refresh_timeline_projection(db_session)
    state = await db_session.get(TimelineProjectionState, 1)
    assert state is not None
    new_material, _ = await _seed(db_session)
    new_material.updated_at = datetime.now(UTC)
    await db_session.flush()
    assert await _read(db_session, material) is None
    await db_session.rollback()
