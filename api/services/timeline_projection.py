"""Transactional refresh and read path for the Timeline projection."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from math import isfinite

from pydantic import ValidationError
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import (
    Material,
    Paper,
    TimelineProjectionPoint,
    TimelineProjectionState,
)
from models.search import TimelinePoint
from services.anomaly_review import ANOMALY_POLICY_VERSION
from services.material_anomalies import review_context
from services.material_visibility import sanitize_review_metadata, visibility_allows_view
from services.material_visibility_adapter import prepare_material_views
from services.pressure_semantics import PRESSURE_POLICY_VERSION
from services.result_semantics import CLASSIFIER_VERSION
from services.timeline_points import (
    TIMELINE_RESULT_CONTRACT_VERSION,
    extract_timeline_points,
    referenced_paper_ids,
)

PROJECTION_SCHEMA_VERSION = 5
_STATE_ID = 1
_WATERMARK_OVERLAP = timedelta(minutes=5)
_SOURCE_SNAPSHOT_KEY = "_projection_source_snapshot"
_RESULT_METADATA_KEYS = frozenset({
    "version", "result_id", "result_revision", "identity_basis", "identity_conflict",
    "identity_warnings", "source_date", "source_date_basis", "source_version",
    "year_basis", "chronology_warnings", "state", "tc_criterion", "source_locator",
    "occurrence_count", "review_status",
})
_STATE_KEYS = frozenset({
    "state_id", "sample_id", "structure_id", "run_id", "formula", "formula_raw",
    "structure_phase", "sample_form", "substrate", "doping_type", "doping_level",
    "magnetic_field_tesla", "strain_percent", "carrier_density_cm3",
})
_LOCATOR_KEYS = frozenset({"page", "table", "figure", "row", "column", "section", "chunk_id", "span_id"})
_YEAR_BASES = frozenset({
    "explicit_measurement_year", "explicit_measurement_date", "explicit_report_year",
    "explicit_report_date", "legacy_record_year_unspecified", "source_publication_year",
    "source_submission_year", "source_publication_date", "source_submission_date",
    "legacy_source_year", "unknown",
})
_CHRONOLOGY_WARNINGS = frozenset({
    "invalid_source_publication_date", "invalid_source_submission_date",
    "source_date_assertions_disagree", "year_basis_unrecognized", "chronology_fields_disagree",
})
_IDENTITY_WARNINGS = frozenset({"supplied_result_revision_has_conflicting_occurrences"})


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


def _bounded_scalar(value, limit: int, *, nullable: bool = False) -> bool:
    if value is None:
        return nullable
    if isinstance(value, str):
        return bool(value.strip()) and value == value.strip() and len(value) <= limit
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
    except OverflowError:
        return False


def _bounded_map(value, keys: frozenset[str], limit: int) -> bool:
    return (isinstance(value, dict) and set(value) <= keys
            and all(_bounded_scalar(item, limit) for item in value.values()))


def _known_warnings(value, allowed: frozenset[str]) -> bool:
    return (isinstance(value, list) and len(value) <= len(allowed)
            and all(isinstance(item, str) and item in allowed for item in value)
            and len(value) == len(set(value)))


def _valid_result_metadata(metadata: dict) -> bool:
    """A matching version string cannot self-approve or expand cached facts.

    This allowlist is the public timeline-result/1.0.0 shape. Any unexpected
    derived content falls back to current extraction, not silent repair.
    """
    if set(metadata) != _RESULT_METADATA_KEYS:
        return False
    if (metadata["version"] != TIMELINE_RESULT_CONTRACT_VERSION
            or metadata["review_status"] != "legacy_unreviewed"
            or metadata["identity_basis"] not in ("result_revision_content", "legacy_occurrence_content")
            or type(metadata["identity_conflict"]) is not bool
            or not _known_warnings(metadata["identity_warnings"], _IDENTITY_WARNINGS)
            or not _known_warnings(metadata["chronology_warnings"], _CHRONOLOGY_WARNINGS)
            or not isinstance(metadata["result_id"], str)
            or not _bounded_scalar(metadata["result_id"], 500)
            or not _bounded_scalar(metadata["result_revision"], 160, nullable=True)
            or not _bounded_scalar(metadata["source_version"], 160, nullable=True)
            or not isinstance(metadata["tc_criterion"], str)
            or not _bounded_scalar(metadata["tc_criterion"], 120)
            or not isinstance(metadata["year_basis"], str)
            or metadata["year_basis"] not in _YEAR_BASES
            or metadata["source_date_basis"] not in ("publication", "submission", "unknown")
            or type(metadata["occurrence_count"]) is not int
            or not 1 <= metadata["occurrence_count"] <= 2**31 - 1
            or not _bounded_map(metadata["state"], _STATE_KEYS, 160)
            or not _bounded_map(metadata["source_locator"], _LOCATOR_KEYS, 120)):
        return False
    if metadata["identity_conflict"] != bool(metadata["identity_warnings"]):
        return False
    if metadata["identity_conflict"] and metadata["identity_basis"] != "result_revision_content":
        return False
    source_date = metadata["source_date"]
    if source_date is None:
        return metadata["source_date_basis"] == "unknown"
    if not isinstance(source_date, str) or len(source_date) != 10:
        return False
    try:
        return date.fromisoformat(source_date).isoformat() == source_date and metadata["source_date_basis"] != "unknown"
    except ValueError:
        return False


def _source_snapshot(metadata: dict | None) -> dict:
    """Internal cache dependency metadata, never a scientific source version."""
    return {"present": metadata is not None, **{
        key: value.isoformat() if value is not None else None
        for key in ("date_published", "date_submitted", "updated_at")
        for value in ((metadata or {}).get(key),)
    }}


async def _sources_changed_since(session: AsyncSession, watermark: datetime) -> bool:
    # A missing-date record has no projection point to join. Until a complete
    # dependency index exists, any changed paper invalidates the derived view.
    changed = await session.execute(
        select(Paper.id).where(Paper.updated_at > watermark).limit(1)
    )
    return bool(changed.all())


async def _projected_sources_removed(session: AsyncSession) -> bool:
    point = TimelineProjectionPoint
    removed = await session.execute(select(point.id).outerjoin(Paper, Paper.id == point.paper_id).where(
        point.active.is_(True), Paper.id.is_(None),
        point.result_metadata[_SOURCE_SNAPSHOT_KEY]["present"].as_boolean().is_(True),
    ).limit(1))
    return bool(removed.all())


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
        or getattr(state, "classifier_version", None) != CLASSIFIER_VERSION
        or getattr(state, "pressure_policy_version", None) != PRESSURE_POLICY_VERSION
        or getattr(state, "anomaly_policy_version", None) != ANOMALY_POLICY_VERSION
        or state.source_year != current_year
    )
    if not full_rebuild and state is not None:
        full_rebuild = (
            await _sources_changed_since(session, state.source_watermark)
            or await _projected_sources_removed(session)
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
        Material.family,
        Material.anomaly_context,
    ).where(Material.updated_at <= refreshed_at)
    if not full_rebuild and state is not None:
        materials_stmt = materials_stmt.where(
            Material.updated_at >= state.source_watermark
        )
    materials_stmt = materials_stmt.order_by(Material.id)
    materials = (await session.execute(materials_stmt)).all()

    paper_ids: set[str] = set()
    for _material_id, records, _source_updated_at, _family, _context in materials:
        paper_ids.update(referenced_paper_ids(records))

    paper_metadata: dict[str, dict] = {}
    ordered_paper_ids = sorted(paper_ids)
    for start in range(0, len(ordered_paper_ids), 1000):
        paper_rows = await session.execute(
            select(Paper.id, Paper.date_published, Paper.date_submitted, Paper.updated_at).where(
                Paper.id.in_(ordered_paper_ids[start:start + 1000])
            )
        )
        for paper_id, date_published, date_submitted, updated_at in paper_rows.all():
            paper_metadata[paper_id] = {
                "date_published": date_published,
                "date_submitted": date_submitted,
                "updated_at": updated_at,
            }

    projection_table = TimelineProjectionPoint.__table__
    for material_id, records, source_updated_at, family, context in materials:
        points = extract_timeline_points(
            material_id,
            records,
            paper_metadata,
            current_year=current_year,
            family=family,
            compound_thresholds=review_context({"family": family, "anomaly_context": context})["compound_thresholds"],
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
                "pressure_semantics": point.pressure_semantics,
                "result_metadata": {**point.result_metadata,
                    _SOURCE_SNAPSHOT_KEY: _source_snapshot(paper_metadata.get(point.paper_id))},
                "paper_id": point.paper_id,
                "is_theoretical": point.is_theoretical,
                "knowledge_origin": point.knowledge_origin,
                "classification_status": point.classification_status,
                "source_role": point.source_role,
                "classifier_version": point.classifier_version,
                "is_aps": point.is_aps,
                "active": True,
                "source_updated_at": source_updated_at,
            }
            for point in points
        ]
        for start in range(0, len(values), 1000):
            # Provenance-distinct results are no longer compressed by Tc/year
            # buckets; bound parameters even for a heavily studied material.
            insert_stmt = pg_insert(projection_table).values(values[start:start + 1000])
            await session.execute(
                insert_stmt.on_conflict_do_update(
                    index_elements=[projection_table.c.id],
                    set_={
                        "year": insert_stmt.excluded.year,
                        "tc_kelvin": insert_stmt.excluded.tc_kelvin,
                        "pressure_gpa": insert_stmt.excluded.pressure_gpa,
                        "pressure_semantics": insert_stmt.excluded.pressure_semantics,
                        "result_metadata": insert_stmt.excluded.result_metadata,
                        "paper_id": insert_stmt.excluded.paper_id,
                        "is_theoretical": insert_stmt.excluded.is_theoretical,
                        "knowledge_origin": insert_stmt.excluded.knowledge_origin,
                        "classification_status": insert_stmt.excluded.classification_status,
                        "source_role": insert_stmt.excluded.source_role,
                        "classifier_version": insert_stmt.excluded.classifier_version,
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
        classifier_version=CLASSIFIER_VERSION,
        pressure_policy_version=PRESSURE_POLICY_VERSION,
        anomaly_policy_version=ANOMALY_POLICY_VERSION,
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
                "classifier_version": state_insert.excluded.classifier_version,
                "pressure_policy_version": state_insert.excluded.pressure_policy_version,
                "anomaly_policy_version": state_insert.excluded.anomaly_policy_version,
                "source_year": state_insert.excluded.source_year,
                "source_watermark": state_insert.excluded.source_watermark,
                "refreshed_at": state_insert.excluded.refreshed_at,
                "material_count": state_insert.excluded.material_count,
                "active_point_count": state_insert.excluded.active_point_count,
            },
        )
    )
    if state is not None:
        # Core upserts do not refresh an already-loaded ORM singleton. A
        # second refresh/read in this same transaction must see the new epoch.
        session.expire(state)

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
        or getattr(state, "classifier_version", None) != CLASSIFIER_VERSION
        or getattr(state, "pressure_policy_version", None) != PRESSURE_POLICY_VERSION
        or getattr(state, "anomaly_policy_version", None) != ANOMALY_POLICY_VERSION
        or state.source_year != expected_year
    ):
        return None

    # A newly created/changed material may have no old point at all. Checking
    # only returned projection rows would silently hide its current results.
    changed_materials = await session.execute(
        select(Material.id).where(Material.updated_at > state.refreshed_at).limit(1)
    )
    if changed_materials.all() or await _sources_changed_since(session, state.refreshed_at):
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
            point.pressure_semantics,
            point.paper_id,
            point.is_theoretical,
            point.knowledge_origin,
            point.classification_status,
            point.source_role,
            point.classifier_version,
            Material.id,
            point.source_updated_at,
            point.id,
            point.result_metadata,
            Paper.id,
            Paper.date_published,
            Paper.date_submitted,
            Paper.updated_at,
        )
        .join(point, point.material_id == Material.id)
        .outerjoin(Paper, Paper.id == point.paper_id)
        .where(point.active.is_(True), point.classifier_version == CLASSIFIER_VERSION,
               or_(Material.review_reason.is_(None), Material.review_reason != "provenance_quarantine_nims"))
    )
    if family:
        stmt = stmt.where(Material.family == family)
    if not include_pending:
        stmt = stmt.where(Material.needs_review.is_(False))
    if experimental_only:
        stmt = stmt.where(
            point.knowledge_origin == "Observed",
            point.classification_status == "resolved",
            point.source_role != "conflicted",
        )
    if only_aps:
        stmt = stmt.where(point.is_aps.is_(True))
    stmt = stmt.order_by(point.year, point.tc_kelvin.desc(), point.id)

    rows = (await session.execute(stmt)).all()
    material_ids = sorted({row[13] for row in rows})
    material_rows = []
    for start in range(0, len(material_ids), 1000):
        material_rows.extend((await session.execute(
            select(Material).where(Material.id.in_(material_ids[start:start + 1000]))
        )).scalars().all())
    contexts = {m.id: m for m in await prepare_material_views(session, material_rows)}
    eligible_rows = []
    for row in rows:
        material = contexts.get(row[13])
        if material is None or not visibility_allows_view(material.visibility, include_archive=include_pending):
            continue
        if material.updated_at and row[14] and material.updated_at > row[14]:
            # A stale rebuildable point is not allowed to outrun its source.
            # Return to the current-raw fallback until refresh catches up.
            return None
        eligible_rows.append(row)
    points: list[TimelinePoint] = []
    for (
        formula, formula_latex, material_family, tc_kelvin, year,
        pressure_gpa, pressure_semantics, paper_id, is_theoretical,
        knowledge_origin, classification_status, source_role, classifier_version,
        material_id, _source_updated_at, point_id, result_metadata,
        live_paper_id, live_date_published, live_date_submitted, live_paper_updated,
    ) in eligible_rows:
        if (
            not isinstance(result_metadata, dict)
            or result_metadata.get("version") != TIMELINE_RESULT_CONTRACT_VERSION
            or not isinstance(pressure_semantics, dict)
            or not isinstance(point_id, str)
            or len(point_id) != 64
            or any(character not in "0123456789abcdef" for character in point_id)
            or isinstance(year, bool) or not isinstance(year, int)
            or not 1900 <= year <= expected_year + 1
            or isinstance(tc_kelvin, bool) or not isinstance(tc_kelvin, (int, float))
            or not isfinite(tc_kelvin) or tc_kelvin <= 0
            or (pressure_gpa is not None and (
                isinstance(pressure_gpa, bool) or not isinstance(pressure_gpa, (int, float))
                or not isfinite(pressure_gpa) or pressure_gpa < 0
            ))
        ):
            # Corrupt/legacy derived metadata cannot substitute for raw facts.
            # The caller falls back to current raw extraction for this response.
            return None
        live_source_snapshot = _source_snapshot({
            "date_published": live_date_published,
            "date_submitted": live_date_submitted,
            "updated_at": live_paper_updated,
        } if live_paper_id is not None else None)
        if result_metadata.get(_SOURCE_SNAPSHOT_KEY) != live_source_snapshot:
            return None
        public_metadata = {key: value for key, value in result_metadata.items()
                           if key != _SOURCE_SNAPSHOT_KEY}
        if not _valid_result_metadata(public_metadata):
            return None
        try:
            projected = TimelinePoint(
                material_id=material_id,
                point_id=point_id,
                result_metadata=sanitize_review_metadata(public_metadata),
                visibility=contexts[material_id].visibility,
                material=formula,
                formula_latex=formula_latex,
                family=material_family,
                tc_kelvin=tc_kelvin,
                year=year,
                pressure_gpa=pressure_gpa,
                pressure_semantics=sanitize_review_metadata(pressure_semantics),
                paper_id=paper_id,
                is_theoretical=is_theoretical,
                knowledge_origin=knowledge_origin,
                classification_status=classification_status,
                source_role=source_role,
                classifier_version=classifier_version,
            )
        except (ValidationError, ValueError, TypeError):
            return None
        points.append(projected)
    return ProjectionReadResult(points=points, refreshed_at=state.refreshed_at)
