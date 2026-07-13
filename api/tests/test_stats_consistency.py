"""Stats refresh timestamps and ingestion-stage state stay distinct."""
from __future__ import annotations

from datetime import UTC, datetime

from models.search import StatsDataPipeline, StatsResponse
from routers.stats import stats as stats_endpoint
from services import stats_refresh


def _payload() -> dict:
    return {
        "total_papers": 10,
        "total_materials": 4,
        "total_chunks": 50,
        "papers_by_year": {"2026": 10},
        "papers_by_year_arxiv": {"2026": 8},
        "papers_by_year_aps": {"2026": 2},
        "top_material_families": [],
        "last_ingest_at": "2026-07-12T10:00:00+00:00",
        "dataset_version": "v2026.07.12",
        "stats_refreshed_at": "2026-07-13T01:00:00+00:00",
        "updated_at": "2026-07-13T01:00:00+00:00",
    }


class _Cached:
    def __init__(self, value: dict, updated_at: datetime | None = None) -> None:
        self.value = value
        self.updated_at = updated_at or datetime(2026, 7, 13, 2, tzinfo=UTC)


class _FakeDb:
    def __init__(self, cached: dict[str, _Cached] | None = None) -> None:
        self.cached = cached or {}
        self.executed = []
        self.committed = False

    async def get(self, model, key):  # noqa: ARG002
        return self.cached.get(key)

    async def execute(self, statement):
        self.executed.append(statement)

    async def commit(self):
        self.committed = True


def test_legacy_stats_payload_gets_explicit_unknown_pipeline_state():
    response = StatsResponse(**_payload())

    assert response.stats_refreshed_at == "2026-07-13T01:00:00+00:00"
    assert response.last_ingest_at == "2026-07-12T10:00:00+00:00"
    assert response.data_pipeline.status == "unknown"
    assert response.data_pipeline.stages == {}


async def test_periodic_refresh_preserves_last_reported_pipeline_state(monkeypatch):
    pipeline = {
        "status": "partial",
        "last_run_at": "2026-07-13T00:30:00Z",
        "stages": {
            "incremental": {"status": "failed", "exit_code": 1},
            "aggregate": {"status": "complete", "exit_code": 0},
        },
    }
    db = _FakeDb({"data_pipeline": _Cached(pipeline)})

    async def fake_compute_stats(session):  # noqa: ARG001
        return _payload()

    monkeypatch.setattr(stats_refresh, "compute_stats", fake_compute_stats)
    result = await stats_refresh.refresh_dashboard_cache(db)  # type: ignore[arg-type]

    assert result["data_pipeline"] == pipeline
    assert db.committed is True
    assert len(db.executed) == 1


async def test_explicit_cron_pipeline_state_replaces_preserved_state(monkeypatch):
    db = _FakeDb({
        "data_pipeline": _Cached({"status": "failed"}),
    })

    async def fake_compute_stats(session):  # noqa: ARG001
        return _payload()

    monkeypatch.setattr(stats_refresh, "compute_stats", fake_compute_stats)
    reported = StatsDataPipeline.model_validate({
        "status": "complete",
        "last_run_at": "2026-07-13T01:00:00Z",
        "stages": {
            "incremental": {"status": "complete", "exit_code": 0},
            "retry": {"status": "complete", "exit_code": 0},
            "aggregate": {"status": "complete", "exit_code": 0},
        },
    })

    result = await stats_refresh.refresh_dashboard_cache(  # type: ignore[arg-type]
        db,
        data_pipeline=reported,
    )

    assert result["data_pipeline"]["status"] == "complete"
    assert result["data_pipeline"]["stages"]["aggregate"]["exit_code"] == 0
    assert len(db.executed) == 2


async def test_cached_row_timestamp_is_authoritative_stats_refresh_time():
    cached_at = datetime(2026, 7, 13, 3, 45, tzinfo=UTC)
    db = _FakeDb({
        "dashboard": _Cached(_payload(), updated_at=cached_at),
        "data_pipeline": _Cached({
            "status": "complete",
            "last_run_at": "2026-07-13T03:30:00Z",
            "stages": {},
        }),
    })

    response = await stats_endpoint(identity=None, db=db)  # type: ignore[arg-type]

    assert response.stats_refreshed_at == cached_at.isoformat()
    assert response.updated_at == cached_at.isoformat()
    assert response.last_ingest_at == "2026-07-12T10:00:00+00:00"
    assert response.data_pipeline.status == "complete"
