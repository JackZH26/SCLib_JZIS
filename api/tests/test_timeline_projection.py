"""Timeline projection extraction, refresh, and dual-read behavior."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from models.search import TimelineCoverage, TimelineResponse
from services.anomaly_review import ANOMALY_POLICY_VERSION
from services.pressure_semantics import PRESSURE_POLICY_VERSION, classify_pressure
from services.result_semantics import CLASSIFIER_VERSION, is_observed_result
from services.timeline_points import (
    TIMELINE_RESULT_CONTRACT_VERSION,
    extract_timeline_points,
    is_theoretical,
)
from services.timeline_projection import (
    PROJECTION_SCHEMA_VERSION,
    ProjectionReadResult,
    fetch_projected_timeline_points,
    refresh_timeline_projection,
)


class _Result:
    def __init__(self, value=None):
        self.value = value

    def scalars(self):
        return self

    def all(self):
        return self.value or []

    def one(self):
        return self.value


class _FakeSession:
    def __init__(self, *, state=None, results=()):
        self.state = state
        self.results = iter(results)
        self.statements = []

    async def get(self, model, identity, **options):  # noqa: ARG002
        return self.state

    async def execute(self, statement):
        self.statements.append(statement)
        return next(self.results)


def test_classifier_uses_result_evidence_not_paper_genre_or_pressure():
    assert not is_theoretical({
        "measurement": "resistivity",
        "paper_type": "theoretical",
        "pressure_gpa": 200,
    })
    assert is_theoretical({"measurement": "DFT"})
    assert not is_theoretical({"paper_type": "computational"})
    assert not is_theoretical({
        "paper_type": "computational",
        "pressure_gpa": 150,
    })
    assert is_theoretical({"evidence_type": "primary_theoretical", "pressure_gpa": None})
    assert is_theoretical({"evidence_type": "primary_theoretical", "pressure_gpa": 0})
    assert not is_observed_result({"paper_type": "experimental"})


def test_extraction_is_stable_deduplicated_and_uses_paper_year_fallback():
    records = [
        {
            "tc_kelvin": 92.04,
            "year": 2020,
            "pressure_gpa": 0,
            "measurement": "resistivity",
            "paper_id": "arxiv:one",
        },
        {
            "tc_kelvin": 92.03,
            "year": 2020,
            "pressure_gpa": 0.2,
            "measurement": "susceptibility",
            "paper_id": "arxiv:duplicate",
        },
        {
            "tc_kelvin": 250,
            "pressure_gpa": 180,
            "paper_type": "theoretical",
            "evidence_type": "primary_theoretical",
            "paper_id": "aps:10.1103/test",
        },
        {"tc_kelvin": 301, "year": 2021},
        {"tc_kelvin": 10, "year": 1800},
    ]

    points = extract_timeline_points(
        "mat:test",
        records,
        {"aps:10.1103/test": 2024},
        current_year=2026,
    )

    # Legacy zero is ambiguous, not the same pressure state as reported 0.2.
    assert len(points) == 3
    assert points[0].tc_kelvin == pytest.approx(92.04)
    assert points[1].pressure_gpa == 0.2
    assert points[2].year == 2024
    assert points[2].is_theoretical
    assert points[2].is_aps
    assert points == extract_timeline_points(
        "mat:test",
        records,
        {"aps:10.1103/test": 2024},
        current_year=2026,
    )


@pytest.mark.asyncio
async def test_projection_read_returns_none_until_compatible_state_exists():
    session = _FakeSession(state=None)

    result = await fetch_projected_timeline_points(
        session,  # type: ignore[arg-type]
        family=None,
        include_pending=False,
        experimental_only=False,
        only_aps=False,
        current_year=2026,
    )

    assert result is None
    assert session.statements == []


@pytest.mark.asyncio
async def test_classifier_version_change_requires_rebuild_before_reading():
    session = _FakeSession(state=SimpleNamespace(
        schema_version=PROJECTION_SCHEMA_VERSION, source_year=2026,
        classifier_version="legacy/unclassified",
    ))
    result = await fetch_projected_timeline_points(
        session, family=None, include_pending=False, experimental_only=True,
        only_aps=False, current_year=2026,
    )
    assert result is None
    assert session.statements == []


@pytest.mark.asyncio
async def test_projection_read_rechecks_live_material_governance_after_flat_points(monkeypatch):
    async def source_statuses(_session, identifiers):
        return {identifier: "published" for identifier in identifiers}
    monkeypatch.setattr("services.source_lifecycle.resolve_paper_lifecycle", source_statuses)
    monkeypatch.setattr("services.material_visibility_adapter.resolve_paper_lifecycle", source_statuses)
    refreshed_at = datetime(2026, 7, 13, tzinfo=UTC)
    state = SimpleNamespace(
        schema_version=PROJECTION_SCHEMA_VERSION,
        classifier_version=CLASSIFIER_VERSION,
        pressure_policy_version=PRESSURE_POLICY_VERSION,
        anomaly_policy_version=ANOMALY_POLICY_VERSION,
        source_year=2026,
        refreshed_at=refreshed_at,
    )
    rows = [
        ("H3S", "H_3S", "hydride", 203.0, 2015, 150.0, classify_pressure({"pressure_gpa": 150}).to_dict(), "aps:test", True,
         "Computed", "resolved", "primary", CLASSIFIER_VERSION, "mat:flat", refreshed_at),
    ]
    material = SimpleNamespace(id="mat:flat", parent_material_id=None, family="hydride",
        records=[{"tc_kelvin": 203, "pressure_gpa": 150, "paper_id": "aps:test", "year": 2015}],
        updated_at=refreshed_at, needs_review=False, status="active_research", disputed=False, retracted=False)
    rows = [row + ("a" * 64, {
        **extract_timeline_points("mat:flat", material.records, {}, current_year=2026)[0].result_metadata,
        "_projection_source_snapshot": {"present": True,
            "date_published": None, "date_submitted": None,
            "status": "published", "updated_at": refreshed_at.isoformat(timespec="microseconds")},
    }, "aps:test", None, None, refreshed_at, "published") for row in rows]
    session = _FakeSession(state=state, results=[
        _Result([]), _Result([]), _Result(rows), _Result([material]),
    ])

    result = await fetch_projected_timeline_points(
        session,  # type: ignore[arg-type]
        family="hydride",
        include_pending=False,
        experimental_only=False,
        only_aps=True,
        current_year=2026,
    )

    assert result is not None
    assert result.refreshed_at == refreshed_at
    assert result.points[0].material == "H3S"
    assert result.points[0].is_theoretical
    assert result.points[0].knowledge_origin == "Computed"
    assert result.points[0].classifier_version == CLASSIFIER_VERSION
    assert "records" not in str(session.statements[2]).lower()
    assert result.points[0].visibility["public_catalogue_eligible"] is True
    assert result.points[0].point_id == "a" * 64
    assert result.points[0].result_metadata["version"] == TIMELINE_RESULT_CONTRACT_VERSION
    assert "materials.records" in str(session.statements[3]).lower()


@pytest.mark.asyncio
async def test_initial_refresh_soft_disables_then_atomically_upserts_projection():
    now = datetime(2026, 7, 13, tzinfo=UTC)
    records = [{
        "tc_kelvin": 203,
        "year": 2015,
        "pressure_gpa": 150,
        "paper_type": "theoretical",
        "paper_id": "aps:test",
    }]
    session = _FakeSession(
        state=None,
        results=[
            _Result(),
            _Result(),
            _Result([("mat:test", records, now, "hydride", {})]),
            _Result([("aps:test", None, None, now, "published")]),
            _Result(),
            _Result(),
            _Result((1, 1)),
            _Result(),
        ],
    )

    result = await refresh_timeline_projection(
        session,  # type: ignore[arg-type]
        now=now,
    )

    assert result.full_rebuild
    assert result.materials_processed == 1
    assert result.active_points == 1
    statements = [str(statement).lower() for statement in session.statements]
    assert "sclib_source_task_lock_v1" in statements[0]
    assert "update timeline_projection_points" in statements[1]
    assert any("on conflict" in statement for statement in statements)
    assert all("materials.records" not in statement for statement in statements[3:])


@pytest.mark.asyncio
async def test_refresh_batches_uncompressed_occurrences_below_driver_parameter_limit(monkeypatch):
    now = datetime(2026, 7, 13, tzinfo=UTC)
    seed = extract_timeline_points("mat:many", [{"tc_kelvin": 10, "year": 2020}], {}, current_year=2026)[0]
    points = [replace(seed, id=f"{index:064x}") for index in range(1001)]
    monkeypatch.setattr("services.timeline_projection.extract_timeline_points", lambda *args, **kwargs: points)
    session = _FakeSession(state=None, results=[
        _Result(), _Result(), _Result([("mat:many", [], now, "other", {})]), _Result(),
        _Result(), _Result(), _Result((1001, 1)), _Result(),
    ])
    result = await refresh_timeline_projection(session, now=now)
    inserts = [stmt for stmt in session.statements if str(stmt).startswith("INSERT INTO timeline_projection_points")]
    assert result.active_points == 1001
    assert len(inserts) == 2
    assert all(len(stmt.compile().params) < 32767 for stmt in inserts)


def test_migration_is_additive_and_starts_projection_empty():
    source = Path("alembic/versions/0041_timeline_projection.py").read_text()

    assert 'down_revision = "0040_hydride_tc_parameters"' in source
    assert '"timeline_projection_points"' in source
    assert '"timeline_projection_state"' in source
    assert "sclib_touch_material_updated_at" in source
    assert "UPDATE materials SET records" not in source
    assert "jsonb_array_elements" not in source


def test_identity_migration_only_changes_rebuildable_projection_metadata():
    source = Path("alembic/versions/0050_timeline_identity.py").read_text()
    assert 'down_revision = "0049_anomaly_review"' in source
    assert '"result_metadata", postgresql.JSONB()' in source
    assert source.count("UPDATE timeline_projection_state SET schema_version = 0") == 2
    assert "UPDATE materials" not in source
    assert "DELETE FROM" not in source


@pytest.mark.asyncio
async def test_endpoint_rolls_back_and_uses_fallback_when_projection_fails(
    monkeypatch,
):
    from starlette.requests import Request

    from routers import timeline as timeline_router

    class _Redis:
        async def get(self, key):  # noqa: ARG002
            return None

        async def set(self, key, value, *, ex):  # noqa: ARG002
            return True

    class _DB:
        rolled_back = False

        async def rollback(self):
            self.rolled_back = True

    async def _projection_failure(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("projection unavailable")

    fallback = TimelineResponse(
        family=None,
        points=[],
        coverage=TimelineCoverage(
            total_points=0,
            total_materials=0,
            year_min=None,
            year_max=None,
            returned_points=0,
        ),
    )

    async def _fallback(**kwargs):  # noqa: ARG001
        return fallback

    monkeypatch.setattr(
        timeline_router,
        "fetch_projected_timeline_points",
        _projection_failure,
    )
    monkeypatch.setattr(timeline_router, "_build_timeline_fallback", _fallback)
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/v1/timeline",
        "headers": [],
        "query_string": b"",
    })
    db = _DB()

    response = await timeline_router.timeline(
        request=request,
        family=None,
        include_pending=False,
        experimental_only=False,
        only_aps=False,
        reviewed_only=False,
        max_points=None,
        compact=False,
        offset=0,
        limit=None,
        schema_version="1",
        db=db,  # type: ignore[arg-type]
    )

    assert response.status_code == 200
    assert db.rolled_back


@pytest.mark.asyncio
async def test_endpoint_prefers_ready_projection_over_jsonb_fallback(monkeypatch):
    from starlette.requests import Request

    from routers import timeline as timeline_router

    class _Redis:
        async def get(self, key):  # noqa: ARG002
            return None

        async def set(self, key, value, *, ex):  # noqa: ARG002
            return True

    async def _projection(*args, **kwargs):  # noqa: ARG001
        return ProjectionReadResult(
            points=[],
            refreshed_at=datetime(2026, 7, 13, tzinfo=UTC),
        )

    async def _unexpected_fallback(**kwargs):  # noqa: ARG001
        raise AssertionError("ready projection must bypass JSONB fallback")

    monkeypatch.setattr(timeline_router, "fetch_projected_timeline_points", _projection)
    monkeypatch.setattr(
        timeline_router,
        "_build_timeline_fallback",
        _unexpected_fallback,
    )
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/v1/timeline",
        "headers": [],
        "query_string": b"",
    })

    response = await timeline_router.timeline(
        request=request,
        family=None,
        include_pending=False,
        experimental_only=False,
        only_aps=False,
        reviewed_only=False,
        max_points=None,
        compact=False,
        offset=0,
        limit=None,
        schema_version="1",
        db=_FakeSession(),  # type: ignore[arg-type]
    )

    assert response.status_code == 200
