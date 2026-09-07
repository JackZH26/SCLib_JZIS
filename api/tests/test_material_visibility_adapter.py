"""Bounded ancestor resolution and current source/governance read regressions.

Adapters use a read-only in-memory SQL-result stand-in; the repository-wide API
test bootstrap still requires the disposable PostgreSQL/Redis runner.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from models.db import Material, Paper
from services.material_visibility_adapter import (
    MAX_PARENT_DEPTH,
    material_view,
    prepare_material_views,
)


def _material(identity, *, parent=None, records=None, **changes):
    return SimpleNamespace(
        id=identity, parent_material_id=parent, records=records or [],
        status="active_research", needs_review=False, disputed=False, retracted=False,
        family=None, anomaly_context={}, updated_at=datetime(2026, 9, 6, tzinfo=UTC),
        **{"review_reason": None, **changes},
    )


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _ReadSession:
    """Only the adapter's bounded SELECTs are accepted; mutation is an error."""
    def __init__(self, materials, sources=None):
        self.materials = {material.id: material for material in materials}
        self.sources = sources or {}
        self.request_sizes = []

    async def execute(self, statement):
        assert statement.is_select
        entity = statement.column_descriptions[0]["entity"]
        parameters = statement.compile().params
        assert len(parameters) == 1
        identifiers = next(iter(parameters.values()))
        self.request_sizes.append(len(identifiers))
        if entity is Material:
            return _Result([self.materials[key] for key in identifiers if key in self.materials])
        assert entity is Paper
        return _Result([(key, self.sources[key]) for key in identifiers if key in self.sources])


def _views_by_id(views):
    return {item.id: item.visibility for item in views}


@pytest.mark.asyncio
async def test_missing_parent_closes_archive_without_asserting_retraction_or_quarantine():
    child = _material("child", parent="missing")
    session = _ReadSession([child])
    visibility = (await prepare_material_views(session, [child]))[0].visibility
    assert visibility["state"] == "unknown"
    assert visibility["archive_available"] is False
    assert visibility["public_catalogue_eligible"] is False
    assert "ancestry_missing_parent" in visibility["reason_codes"]
    assert "ancestry_provenance_unresolved" in visibility["reason_codes"]
    assert "material_retracted" not in visibility["reason_codes"]
    assert "provenance_quarantined" not in visibility["reason_codes"]
    assert await material_view(session, child) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("self_cycle", [False, True])
async def test_cycle_revisions_are_request_order_independent(self_cycle):
    first = _material("a", parent="a" if self_cycle else "b")
    second = _material("b", parent="a")
    third = _material("descendant", parent="a")
    materials = [first, second, third]
    forward = _views_by_id(await prepare_material_views(_ReadSession(materials), materials))
    reverse = _views_by_id(await prepare_material_views(_ReadSession(materials), list(reversed(materials))))
    separately = {}
    for material in materials:
        separately.update(_views_by_id(await prepare_material_views(_ReadSession(materials), [material])))
    assert forward == reverse == separately
    for visibility in forward.values():
        assert visibility["state"] == "unknown"
        assert not visibility["archive_available"]
        assert "ancestry_cycle_detected" in visibility["reason_codes"]


def _chain(edges, *, quarantine_last=False):
    return [
        _material(f"chain-{index}", parent=f"chain-{index + 1}" if index < edges else None,
                  review_reason="provenance_quarantine_nims" if quarantine_last and index == edges else None)
        for index in range(edges + 1)
    ]


@pytest.mark.asyncio
async def test_exact_depth_budget_can_resolve_complete_ancestry():
    materials = _chain(MAX_PARENT_DEPTH)
    visibility = (await prepare_material_views(_ReadSession(materials), [materials[0]]))[0].visibility
    assert visibility["state"] == "catalogue"
    assert visibility["archive_available"]


@pytest.mark.asyncio
async def test_quarantine_at_last_resolvable_ancestor_is_inherited():
    materials = _chain(MAX_PARENT_DEPTH, quarantine_last=True)
    visibility = (await prepare_material_views(_ReadSession(materials), [materials[0]]))[0].visibility
    assert visibility["state"] == "quarantined"
    assert not visibility["archive_available"]


@pytest.mark.asyncio
@pytest.mark.parametrize("quarantine_last", [False, True])
async def test_depth_exhaustion_closes_archive_independently_of_other_preloaded_ancestors(quarantine_last):
    materials = _chain(MAX_PARENT_DEPTH + 1, quarantine_last=quarantine_last)
    single = (await prepare_material_views(_ReadSession(materials), [materials[0]]))[0].visibility
    together = _views_by_id(await prepare_material_views(_ReadSession(materials), materials))[materials[0].id]
    reverse = _views_by_id(await prepare_material_views(_ReadSession(materials), list(reversed(materials))))[materials[0].id]
    assert single == together == reverse
    assert single["state"] == "unknown"
    assert not single["archive_available"]
    assert "ancestry_depth_exceeded" in single["reason_codes"]


@pytest.mark.asyncio
async def test_live_ancestor_source_retraction_is_a_scientific_hold_not_a_rights_quarantine():
    parent = _material("parent", records=[{"paper_id": "p", "tc_kelvin": 10}])
    child = _material("child", parent="parent")
    visibility = (await prepare_material_views(_ReadSession([parent, child], {"p": "retracted"}), [child]))[0].visibility
    assert visibility["state"] == "pending"
    assert visibility["archive_available"]
    assert "parent_review_hold" in visibility["reason_codes"]


@pytest.mark.asyncio
async def test_explicit_retained_record_hold_is_not_lost_by_adapter():
    material = _material("material", records=[{"paper_id": "p", "tc_kelvin": 10,
                                              "review_status": "retracted", "reviewed": True}])
    visibility = (await prepare_material_views(_ReadSession([material], {"p": "published"}), [material]))[0].visibility
    assert visibility["state"] == "pending"
    assert visibility["archive_available"]
    assert "record_retracted" in visibility["reason_codes"]


@pytest.mark.asyncio
async def test_context_sources_are_material_scoped_and_missing_sources_remain_unknown():
    first = _material("a", records=[{"paper_id": "p"}])
    second = _material("b", records=[{"paper_id": "missing"}])
    views = await prepare_material_views(_ReadSession([first, second], {"p": "published"}), [first, second])
    assert views[0].source_statuses == {"p": "published"}
    assert views[1].source_statuses == {"missing": None}
    assert views[1].visibility["source_status"] == "unknown"


@pytest.mark.asyncio
async def test_large_parent_frontier_is_split_into_bounded_read_queries():
    parents = [_material(f"p-{index}") for index in range(1001)]
    children = [_material(f"c-{index}", parent=f"p-{index}") for index in range(1001)]
    session = _ReadSession(parents + children)
    views = await prepare_material_views(session, children)
    assert len(views) == len(children)
    assert all(item.visibility["public_catalogue_eligible"] for item in views)
    assert session.request_sizes == [1000, 1]
