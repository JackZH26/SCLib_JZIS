"""Real-database identity, source-date freshness, and raw-fallback parity."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text, update

from models.db import (
    Material,
    Paper,
    TimelineProjectionPoint,
    TimelineProjectionState,
    get_session_factory,
)
from routers.timeline import _build_timeline_fallback
from services.timeline_projection import (
    _projected_sources_changed,
    _sources_changed_since,
    fetch_projected_timeline_points,
    refresh_timeline_projection,
)


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    # Keep rollback/close on the same loop even when an assertion fails; other
    # modules legitimately retain append-only fixture history in this database.
    async with get_session_factory()() as session:
        yield session


async def _assert_content_converged(session):
    """Content repair converges independently of the global overlap watermark.

    Other tests or real ingestion may have written unrelated papers within the
    five-minute overlap. Such papers intentionally request another full rebuild
    even when every active point's source snapshot already matches exactly.
    """
    assert await _projected_sources_changed(session) is False
    state = await session.get(TimelineProjectionState, 1)
    timestamp_trigger = await _sources_changed_since(session, state.source_watermark)
    repeated = await refresh_timeline_projection(session)
    assert repeated.full_rebuild is timestamp_trigger
    assert await _projected_sources_changed(session) is False
    return repeated


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
    assert await _projected_sources_changed(db_session) is True
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
@pytest.mark.parametrize("field,corrected", (
    ("date_published", date(2021, 6, 7)),
    ("date_published", None),
    ("date_submitted", date(2018, 1, 2)),
))
async def test_source_date_correction_with_unchanged_timestamp_converges(db_session, field, corrected):
    material, papers = await _seed(db_session)
    await refresh_timeline_projection(db_session)
    assert await _projected_sources_changed(db_session) is False
    original_updated = material.updated_at
    paper_updated = papers[0].updated_at
    # External metadata imports can preserve provider timestamps. Content, not
    # timestamp ordering alone, must decide whether a projection needs repair.
    await db_session.execute(update(Paper).where(Paper.id == papers[0].id).values(
        **{field: corrected, "updated_at": paper_updated},
    ))
    assert material.updated_at == original_updated
    assert await _projected_sources_changed(db_session) is True
    assert await _read(db_session, material) is None
    raw = await _fallback(db_session, material)
    refreshed = await refresh_timeline_projection(db_session)
    assert refreshed.full_rebuild
    current = await _read(db_session, material)
    assert current is not None
    assert [point.model_dump() for point in current.points] == [point.model_dump() for point in raw.points]
    await _assert_content_converged(db_session)
    repeated_read = await _read(db_session, material)
    assert repeated_read is not None
    assert [point.model_dump() for point in repeated_read.points] == [point.model_dump() for point in current.points]
    await db_session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("future", [False, True])
async def test_unrelated_timestamp_trigger_is_distinct_from_stale_content(db_session, future):
    material, _ = await _seed(db_session)
    unrelated = Paper(
        id=f"arxiv:unrelated-projection-{uuid4().hex}", source="arxiv",
        title="Synthetic unrelated timestamp signal", authors=[], abstract="Test only.",
        status="published", updated_at=datetime.now(UTC) + (
            timedelta(days=1) if future else -timedelta(minutes=1)
        ),
    )
    db_session.add(unrelated)
    await db_session.flush()
    await refresh_timeline_projection(db_session)
    ids = (await db_session.execute(select(TimelineProjectionPoint.id).where(
        TimelineProjectionPoint.material_id == material.id,
    ).order_by(TimelineProjectionPoint.id))).scalars().all()
    assert len(ids) == 2
    for _ in range(2):
        # Both ordinary overlapping writes and future provider timestamps
        # intentionally cause conservative rebuilds even without dependencies.
        # The latter also retains the pre-existing fail-closed raw read path.
        assert (await _assert_content_converged(db_session)).full_rebuild is True
        current = await _read(db_session, material)
        if future:
            assert current is None
            assert len((await _fallback(db_session, material)).points) == 2
        else:
            assert current is not None and len(current.points) == 2
        current_ids = (await db_session.execute(select(TimelineProjectionPoint.id).where(
            TimelineProjectionPoint.material_id == material.id,
        ).order_by(TimelineProjectionPoint.id))).scalars().all()
        assert current_ids == ids
    await db_session.rollback()


@pytest.mark.asyncio
async def test_backdated_source_timestamp_does_not_leave_permanent_fallback(db_session):
    material, papers = await _seed(db_session)
    await refresh_timeline_projection(db_session)
    initial = await _read(db_session, material)
    assert initial is not None
    await db_session.execute(update(Paper).where(Paper.id == papers[0].id).values(
        updated_at=papers[0].updated_at - timedelta(days=1),
    ))
    assert await _projected_sources_changed(db_session) is True
    assert await _read(db_session, material) is None
    assert (await refresh_timeline_projection(db_session)).full_rebuild
    current = await _read(db_session, material)
    assert current is not None
    # A provider timestamp is a dependency token, not a new scientific result.
    assert [point.point_id for point in current.points] == [point.point_id for point in initial.points]
    await _assert_content_converged(db_session)
    await db_session.rollback()


@pytest.mark.asyncio
async def test_status_correction_with_old_timestamp_rebuilds_without_approving_claims(db_session):
    material, papers = await _seed(db_session)
    await refresh_timeline_projection(db_session)
    initial = await _read(db_session, material)
    assert initial is not None
    await db_session.execute(update(Paper).where(Paper.id == papers[0].id).values(
        status="retracted", updated_at=papers[0].updated_at,
    ))
    assert await _projected_sources_changed(db_session) is True
    # SC07 deliberately keeps a conservative material-wide hold until explicit
    # occurrence-scoped dependencies and independent result reviews are ready.
    held = await _read(db_session, material)
    assert held is not None and held.points == []
    assert (await refresh_timeline_projection(db_session)).full_rebuild
    archive = await fetch_projected_timeline_points(
        db_session, family=material.family, include_pending=True,
        experimental_only=False, only_aps=False,
    )
    assert archive is not None and len(archive.points) == 2
    assert [point.point_id for point in archive.points] == [point.point_id for point in initial.points]
    assert all(not point.visibility["public_catalogue_eligible"] for point in archive.points)
    assert all("source_retracted" in point.visibility["reason_codes"] for point in archive.points)
    await _assert_content_converged(db_session)
    await db_session.rollback()


@pytest.mark.asyncio
async def test_explicit_invalidation_recovers_missing_date_without_timestamp_signal(db_session):
    material, papers = await _seed(db_session, with_dates=False)
    await refresh_timeline_projection(db_session)
    initial = await _read(db_session, material)
    assert initial is not None and initial.points == []
    await db_session.execute(update(Paper).where(Paper.id == papers[0].id).values(
        date_submitted=date(2019, 5, 1), updated_at=papers[0].updated_at,
    ))
    refreshed = await refresh_timeline_projection(db_session, force_full_rebuild=True)
    assert refreshed.full_rebuild
    current = await _read(db_session, material)
    assert current is not None and len(current.points) == 1
    assert current.points[0].result_metadata["year_basis"] == "source_submission_date"
    assert [point.model_dump() for point in current.points] == [
        point.model_dump() for point in (await _fallback(db_session, material)).points
    ]
    repeated = await refresh_timeline_projection(db_session, force_full_rebuild=True)
    assert repeated.full_rebuild
    repeated_read = await _read(db_session, material)
    assert repeated_read is not None
    assert [point.point_id for point in repeated_read.points] == [point.point_id for point in current.points]
    rows = (await db_session.execute(select(TimelineProjectionPoint.id).where(
        TimelineProjectionPoint.material_id == material.id,
    ))).all()
    assert len(rows) == 1
    await db_session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ("invalid_scalar", "extra_field", "missing_field"))
async def test_malformed_dependency_snapshot_is_rebuilt_without_timestamp_cast(db_session, mutation):
    material, _ = await _seed(db_session)
    await refresh_timeline_projection(db_session)
    point = (await db_session.execute(select(TimelineProjectionPoint).where(
        TimelineProjectionPoint.material_id == material.id,
    ).limit(1))).scalar_one()
    snapshot = deepcopy(point.result_metadata["_projection_source_snapshot"])
    if mutation == "invalid_scalar":
        snapshot.update({"present": "not a boolean", "date_published": {"unsafe": "not a date"},
                         "updated_at": "not a timestamp"})
    elif mutation == "extra_field":
        snapshot["not_in_dependency_contract"] = True
    else:
        snapshot.pop("status")
    await db_session.execute(update(TimelineProjectionPoint).where(
        TimelineProjectionPoint.id == point.id,
    ).values(result_metadata={**point.result_metadata, "_projection_source_snapshot": snapshot}))
    assert await _read(db_session, material) is None
    assert (await refresh_timeline_projection(db_session)).full_rebuild
    assert await _read(db_session, material) is not None
    await db_session.rollback()


@pytest.mark.asyncio
async def test_dependency_comparison_is_independent_of_database_timezone_and_date_style(db_session):
    material, papers = await _seed(db_session)
    papers[0].updated_at = papers[0].updated_at.replace(microsecond=0)
    await db_session.flush()
    await refresh_timeline_projection(db_session)
    await db_session.execute(text("SET LOCAL TIME ZONE 'Asia/Singapore'"))
    await db_session.execute(text("SET LOCAL DateStyle TO 'German, DMY'"))
    await _assert_content_converged(db_session)
    assert await _read(db_session, material) is not None
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
