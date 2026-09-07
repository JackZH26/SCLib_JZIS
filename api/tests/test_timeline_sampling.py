"""Display budget never defines result identity, extrema or dataset coverage."""
from __future__ import annotations

import random
import uuid

import pytest

from models.search import TimelinePoint
from routers.timeline import _load_paper_dates, _timeline_response
from services.timeline_sampling import sample_timeline


def _point(i, **kwargs):
    values = dict(point_id=f"result:{i}", material_id=f"mat:{i}", material="Same formula",
                  formula_latex=None, family="common", tc_kelvin=float(i + 1), year=2000,
                  paper_id=f"paper:{i}", pressure_gpa=None,
                  result_metadata={"year_basis": "legacy_record_year_unspecified"},
                  knowledge_origin="Observed", classification_status="resolved", source_role="primary")
    values.update(kwargs)
    return TimelinePoint(**values)


def test_stratified_sample_keeps_extrema_rare_groups_and_is_permutation_invariant():
    points = [_point(i) for i in range(100)]
    points += [_point(101, family="rare", tc_kelvin=0.03, year=2001),
               _point(102, family="rare_computed", tc_kelvin=20, knowledge_origin="Computed", year=2005)]
    selected, metadata = sample_timeline(points, 8)
    assert len(selected) == 8
    assert {"result:99", "result:101", "result:102"} <= {p.point_id for p in selected}
    assert metadata["rare_groups_omitted"] == 0
    assert metadata["total_points"] == 102
    assert metadata["display_only"] is True
    assert metadata["method"] == "deterministic_stratified"
    shuffled = points.copy()
    random.Random(418).shuffle(shuffled)
    assert sample_timeline(shuffled, 8) == (selected, metadata)


def test_insufficient_budget_discloses_unrepresented_strata():
    points = [_point(i, family=f"family:{i}") for i in range(20)]
    selected, metadata = sample_timeline(points, 4)
    assert len(selected) == 4
    assert metadata["strata_omitted"] == metadata["rare_groups_omitted"] == 16


def test_summary_is_full_unsampled_and_not_recomputed_from_page():
    points = [_point(i) for i in range(40)]
    full = _timeline_response(family=None, points=points, max_points=None)
    page = _timeline_response(family=None, points=list(reversed(points)), max_points=8, offset=4, limit=2)
    assert page.record_summary == full.record_summary
    assert page.data_version == full.data_version
    assert page.coverage.total_points == page.coverage.total_materials == 40
    assert page.record_summary["source_count"] == 40
    assert page.record_summary["max_tc_kelvin"] == 40
    assert page.record_summary["record_candidates"][0]["point_id"] == "result:39"
    assert page.record_summary["by_year_basis"] == {"legacy_record_year_unspecified": 40}
    assert page.sampling["selected_points"] == 8
    assert page.sampling["returned_points"] == 2
    assert page.sampling["is_paginated"] is True
    assert page.has_more is True
    assert page.record_summary["scientific_acceptance"] is False
    assert page.record_summary["reviewed_only_available"] is False


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), 0, -1])
def test_bad_persisted_quantity_does_not_poison_other_points_or_summary(bad):
    response = _timeline_response(family=None, points=[_point(0, tc_kelvin=0.03), _point(1, tc_kelvin=bad)], max_points=None)
    assert [p.tc_kelvin for p in response.points] == [0.03]
    assert response.record_summary["invalid_projected_points_omitted"] == 1
    assert response.record_summary["min_tc_kelvin"] == 0.03
    assert "NaN" not in response.model_dump_json()


def test_highest_reported_ties_have_bounded_candidates_without_false_world_record():
    response = _timeline_response(family=None, points=[_point(i, tc_kelvin=10) for i in range(30)], max_points=5)
    assert response.record_summary["record_candidate_count"] == 30
    assert len(response.record_summary["record_candidates"]) == 20
    assert response.record_summary["record_candidates_truncated"] is True
    assert "not a world-record" in response.record_summary["label"]


@pytest.mark.parametrize("budget", [0, -1, True])
def test_invalid_sampling_budget_fails_explicitly(budget):
    with pytest.raises(ValueError):
        sample_timeline([_point(1)], budget)


@pytest.mark.asyncio
async def test_reviewed_only_is_rejected_instead_of_silently_returning_legacy_results(client):
    response = await client.get("/v1/timeline", params={"reviewed_only": True})
    assert response.status_code == 422
    assert "revision-bound scientific acceptance" in response.text


@pytest.mark.asyncio
async def test_archive_fallback_isolates_malformed_records_without_repairing_originals(client, monkeypatch):
    from models.db import Material, get_session_factory

    async def no_projection(*args, **kwargs):
        return None

    monkeypatch.setattr("routers.timeline.fetch_projected_timeline_points", no_projection)
    suffix = uuid.uuid4().hex[:12]
    family = f"timeline-fixture-{suffix}"
    original = [{"tc_kelvin": 0.03, "year": 2020, "pressure_gpa": 1},
                {"tc_kelvin": "NaN", "year": 2020},
                {"tc_kelvin": "Infinity", "year": 2020},
                {"tc_kelvin": {"bad": "proposal"}, "year": 2020}]
    async with get_session_factory()() as db:
        db.add(Material(id=f"mat:{suffix}", formula="X", formula_normalized=suffix,
                        family=family, records=original, needs_review=False, total_papers=1))
        await db.commit()
    response = await client.get("/v1/timeline", params={"family": family, "include_pending": True})
    assert response.status_code == 200, response.text
    assert [p["tc_kelvin"] for p in response.json()["points"]] == [0.03]
    assert response.json()["points"][0]["result_metadata"]["review_status"] == "legacy_unreviewed"
    async with get_session_factory()() as db:
        assert (await db.get(Material, f"mat:{suffix}")).records == original


@pytest.mark.asyncio
async def test_fallback_source_dates_batch_above_asyncpg_parameter_limit():
    from types import SimpleNamespace

    batches = []

    class Session:
        async def execute(self, statement):
            ids = statement.compile().params["id_1"]
            batches.append(ids)
            return SimpleNamespace(all=lambda: [(paper_id, None, None, None) for paper_id in ids])

    identifiers = {f"paper:{i}" for i in range(33_001)}
    loaded = await _load_paper_dates(Session(), identifiers)
    assert set(loaded) == identifiers
    assert len(batches) == 34
    assert all(len(batch) <= 1000 for batch in batches)
