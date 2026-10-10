"""Scalar ranking keeps the full evidence projector's scientific decisions."""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

from services.material_scoped_properties import scoped_property_evidence, scoped_tc_selection
from services.property_evidence import build_property_evidence
from tests.test_material_source_scope_ordering import db_session as _owned_db_session
from tests.test_material_source_scope_ordering import material_row, ordered_fixture

db_session = _owned_db_session


def record(**changes):
    return {"paper_id": "synthetic-source", "tc_kelvin": 39, "pressure_gpa": 0,
            "pressure_condition": "ambient pressure", "knowledge_origin": "Observed",
            "measurement": "resistivity", "year": 2025, **changes}


def full_selection(records, *, scope_id, field, anomaly_context, legacy_summary=None, scoped=False):
    options = dict(scope_id=scope_id, property_fields=[field],
                   include_joint_epc=False, anomaly_context=anomaly_context)
    envelope = (scoped_property_evidence(records, **options) if scoped else
                build_property_evidence(records, legacy_summary=legacy_summary, **options))
    binding = envelope["properties"][field]
    selected = binding["selected"]
    return {"status": binding["status"], "selected":
            {key: selected[key] for key in ("result_id", "value")} if selected else None}


@pytest.mark.parametrize("field", ["tc_max", "tc_ambient"])
@pytest.mark.parametrize("records", [
    [], [record()], [record(), record()],
    [record(tc_kelvin=30), record(paper_id="calculation", tc_kelvin=100,
                                knowledge_origin="Computed", measurement="dft")],
    [record(knowledge_origin="Unknown", measurement=None)],
    [record(knowledge_origin="Observed", source_role="cited", evidence_role="primary")],
    [record(tc_kelvin="30–50 K")], [record(tc_kelvin=True)], [record(tc_kelvin=9999)],
    [record(pressure_gpa=None, pressure_condition=None)], [record(pressure_gpa=100)],
    [record(lattice_a=-1)], [record(lattice_params={"a": 3.9, "unit": "angstrom"})],
    [record(tc_kelvin=None)], [record(tc_kelvin=0)], [record(source_locator={"page": 2})],
])
def test_scoped_scalar_preserves_full_status_and_selected_occurrence(field, records):
    before = deepcopy(records)
    options = dict(scope_id="synthetic-material", field=field,
                   anomaly_context={"current_year": 2026})
    assert scoped_tc_selection(records, **options) == full_selection(records, scoped=True, **options)
    assert records == before


def test_scoped_no_origin_pool_stays_pending_and_nonmapping_still_raises():
    options = dict(scope_id="synthetic-material", field="tc_max", anomaly_context={})
    assert scoped_tc_selection([record(knowledge_origin="Unknown", measurement=None)], **options) == {
        "status": "pending", "selected": None,
    }
    with pytest.raises(AttributeError):
        full_selection([None], scoped=True, **options)
    with pytest.raises(AttributeError):
        scoped_tc_selection([None], **options)


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [
    {}, {"sort": "tc_ambient"}, {"sort": "total_papers"}, {"sort": "arxiv_year"},
    {"tc_min": 25, "pressure_max": 1}, {"experimental_only": True, "ambient_sc": True},
    {"min_tier": "T1", "min_papers": 2}, {"pairing_symmetry": "s-wave"},
    {"is_unconventional": True}, {"has_competing_order": True},
])
async def test_real_sql_complete_pages_equal_original_projectors(client, db_session, monkeypatch, extra):
    import routers.materials as routes

    family, rows = await ordered_fixture(db_session)
    # Nonzero source-level filter matches, including one held high-Tc source.
    for row in rows.values():
        row.records = [{**value, "credibility_tier": "T1", "pairing_symmetry": "s-wave",
                        "is_unconventional": True, "has_competing_order": True,
                        "measurement_temperature_k": 4, "doping_level": 0.1,
                        "lattice_a": 3.9} for value in row.records]
    await db_session.commit()
    for row in rows.values():
        await db_session.refresh(row)
    original_rows = {row.id: (deepcopy(row.records), row.updated_at) for row in rows.values()}

    async def pages():
        monkeypatch.setattr(routes, "_material_pages", routes._MaterialPageCache())
        monkeypatch.setattr(routes, "_material_rankings", routes._MaterialPageCache())
        results = []
        for offset in (0, 2, 0):
            response = await client.get("/v1/materials", params={
                "family": family, "limit": 2, "offset": offset, **extra,
            })
            assert response.status_code == 200, response.text
            assert response.json()["total"] > 0
            results.append(response.content)
        assert results[0] == results[2], "Page-cache reuse must preserve the exact response"
        return results

    scalar_pages = await pages()
    monkeypatch.setattr(routes, "build_tc_selection", full_selection)
    monkeypatch.setattr(routes, "scoped_tc_selection", lambda records, **options:
                        full_selection(records, scoped=True, **options))
    assert await pages() == scalar_pages
    for row in rows.values():
        await db_session.refresh(row)
        assert (row.records, row.updated_at) == original_rows[row.id]


@pytest.mark.asyncio
async def test_prepared_inventory_complete_finite_pages_equal_original_validation(client, db_session, monkeypatch):
    """Initial scope construction, selection and projection all participate."""
    import routers.materials as routes
    from models.db import Paper
    from services import material_source_scope as policy

    family, rows = await ordered_fixture(db_session)
    # Preserve occurrence positions, including an excluded unknown source and
    # a repeated retained record. Computed and Observed stay separate predicates.
    rows["a"].records = [*rows["a"].records,
                         {**rows["a"].records[1], "paper_id": f"{family}:missing"}]
    rows["b"].records = [*rows["b"].records, deepcopy(rows["b"].records[-1])]
    rows["b"].records[-1]["knowledge_origin"] = "Computed"
    rows["b"].records[-1]["measurement"] = "dft"
    # One nested excluded sibling is enough to keep the whole inventory on the
    # original full validation/deepcopy path.
    rows["c"].records = [{**value, "source_locator": {"page": 2}}
                         for value in rows["c"].records]
    rows["f"] = await material_row(db_session, family=family, label="f", tc=50,
                                    old_tc=50, source_count=1)
    held_paper = await db_session.get(Paper, rows["f"].records[0]["paper_id"])
    held_paper.status = "retracted"
    rows["g"] = await material_row(db_session, family=family, label="g", tc=50,
                                    old_tc=50, source_count=1)
    rows["g"].parent_material_id = rows["f"].id
    await db_session.commit()
    for row in rows.values():
        await db_session.refresh(row)
    before = {row.id: (deepcopy(row.records), row.updated_at) for row in rows.values()}
    capture = policy._flat_inventory
    captures = {"prepared": 0, "fallback": 0}

    def counted_capture(*args, **kwargs):
        result = capture(*args, **kwargs)
        captures["prepared" if result is not None else "fallback"] += 1
        return result

    queries = ({}, {"sort": "tc_ambient"}, {"sort": "total_papers"},
               {"knowledge_origin": "Computed"},
               {"knowledge_origin": "Observed", "tc_min": 25, "pressure_max": 1},
               {"include_pending": True}, {"offset": 1, "limit": 2})

    async def complete_pages():
        bodies = []
        for extra in queries:
            # Both arms must create scopes afresh and exercise the full scan,
            # candidate ordering and returned-page DTO construction.
            monkeypatch.setattr(routes, "_material_pages", routes._MaterialPageCache())
            monkeypatch.setattr(routes, "_material_rankings", routes._MaterialPageCache())
            response = await client.get("/v1/materials", params={
                "family": family, "limit": 100, **extra,
            })
            assert response.status_code == 200, response.text
            bodies.append(response.content)
        return bodies

    monkeypatch.setattr(policy, "_flat_inventory", counted_capture)
    prepared = await complete_pages()
    assert captures["prepared"] > 0 and captures["fallback"] > 0
    monkeypatch.setattr(policy, "_flat_inventory", lambda *args, **kwargs: None)
    assert await complete_pages() == prepared
    default = json.loads(prepared[0])
    assert default["total"] == 5
    assert [item["id"] for item in default["results"]] == [rows[key].id for key in "bcaed"]
    assert json.loads(prepared[3])["total"] == 1
    assert json.loads(prepared[4])["total"] == 3
    assert json.loads(prepared[5])["total"] == 7
    assert [item["id"] for item in json.loads(prepared[6])["results"]] == [rows[key].id for key in "ca"]
    for row in rows.values():
        await db_session.refresh(row)
        assert (row.records, row.updated_at) == before[row.id]
