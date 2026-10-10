"""Real relational/HTTP counterexamples on disposable PostgreSQL only."""

import hashlib
from copy import deepcopy
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from models.db import Base, get_session_factory
from models.materials_v3 import TABLE_ORDER
from services.material_reports_v3 import report_projection
from tests.test_material_source_scope_surfaces import seed
from tests.test_research_shadow_schema import add
from tests.test_research_shadow_schema import seed as seed_research


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        yield session


def test_tc_has_one_canonical_store_and_frozen_schema_is_unchanged():
    from models.materials_v3 import NUMERIC_UNITS
    from models.research_schema_v2 import PROPERTY_UNITS

    assert "tc" not in NUMERIC_UNITS
    assert "coulomb_mu_star" not in PROPERTY_UNITS
    assert set(TABLE_ORDER) <= Base.metadata.tables.keys()


async def test_pressure_interval_is_known_not_ambient(db_session):
    material, artifact, _, _ = await seed_research(db_session)
    series = await add(
        db_session,
        "research_series",
        material_id=material,
        source_artifact_id=artifact,
        context_sha256="c" * 64,
    )
    point = await add(
        db_session,
        "research_series_points",
        material_id=material,
        series_id=series,
        ordinal=0,
        path_direction="loading",
        position_sha256="d" * 64,
    )
    base = dict(
        point_id=point,
        material_id=material,
        condition_key="measurement_pressure",
        status="reported",
        relation="interval",
        lower_gpa=150,
        upper_gpa=170,
        source_artifact_id=artifact,
        locator={"table": 1, "row": 2},
        record_sha256="e" * 64,
    )
    interval = await add(db_session, "research_condition_quantities", **base)
    assert interval
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await add(
                db_session,
                "research_condition_quantities",
                **{
                    **base,
                    "condition_key": "synthesis_pressure",
                    "status": "explicit_ambient",
                    "lower_gpa": 0,
                    "upper_gpa": 1,
                },
            )
    assert "pressure_relation" not in Base.metadata.tables["material_states"].c
    assert "pressure_relation" not in Base.metadata.tables["material_claims"].c


async def test_extended_registry_retains_mu_star_and_qualitative_claims(db_session):
    _, _, _, event = await seed_research(db_session)
    prop = await add(
        db_session,
        "event_properties",
        event_id=event,
        property_key="coulomb_mu_star",
        registry_version="materials-properties/3.0",
        relation="exact",
        value=0.1,
        unit="1",
        record_sha256="d" * 64,
    )
    assert prop
    qualitative = await add(
        db_session,
        "event_qualitative_claims",
        event_id=event,
        property_key="pairing_symmetry",
        value_raw="reported d wave",
        knowledge_origin="Observed",
        source_role="primary",
        record_sha256="e" * 64,
    )
    assert qualitative
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await add(
                db_session,
                "event_properties",
                event_id=event,
                property_key="tc",
                registry_version="materials-properties/3.0",
                relation="exact",
                value=20,
                unit="K",
                record_sha256="d" * 64,
            )


async def test_field_evidence_cannot_bind_another_event(db_session):
    _, artifact, _, event = await seed_research(db_session)
    _, _, _, other = await seed_research(db_session)
    qualitative = await add(
        db_session,
        "event_qualitative_claims",
        event_id=event,
        property_key="pairing_symmetry",
        value_raw="s wave",
        knowledge_origin="Computed",
        source_role="cited",
        record_sha256="e" * 64,
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await add(
                db_session,
                "event_field_evidence",
                event_id=other,
                qualitative_id=qualitative,
                artifact_id=artifact,
                knowledge_origin="Computed",
                source_role="cited",
                locator={"page": 2},
                record_sha256="f" * 64,
            )


async def test_source_capture_candidate_composite_fk_rejects_wrong_capture(db_session):
    captures = []
    for c in "ab":
        captures.append(
            await add(
                db_session,
                "ner_source_captures",
                source_sha256=c * 64,
                manifest_sha256=c * 64,
                parser_version="test",
                source_version="test",
                source_license="synthetic",
            )
        )
    occurrence = await add(
        db_session, "ner_source_occurrences", capture_id=captures[0], position_sha256="c" * 64
    )
    run = await add(
        db_session,
        "ner_extraction_runs",
        capture_id=captures[1],
        provider="fixture",
        model="fixture",
        config_sha256="d" * 64,
        schema_version="3",
        prompt_version="3",
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await add(
                db_session,
                "ner_candidates",
                run_id=run,
                capture_id=captures[1],
                occurrence_id=occurrence,
                local_id="r1",
                interpretation_sha256="e" * 64,
            )


async def test_reports_share_existing_source_hold_and_stable_positions(client, db_session):
    material, papers, _ = await seed(db_session, held=True)
    response = await client.get(f"/v1/materials/{material.id}/reports?limit=1")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_points"] == 2 and body["has_more"] is True
    assert body["report_groups"][0]["points"][0]["paper_id"] == papers[1].id
    assert body["report_groups"][0]["points"][0]["record_index"] == 1
    assert "PRIVATE-SCOPE-FIXTURE" not in response.text
    assert body["support_counts"]["independent_data_groups"] is None
    assert "no-store" in response.headers["cache-control"]
    second = await client.get(f"/v1/materials/{material.id}/reports?offset=1&limit=1")
    assert second.json()["report_groups"][0]["points"][0]["knowledge_origin"] == "Computed"


async def test_report_pagination_is_bounded(client):
    for query in ("limit=101", "offset=-1"):
        assert (await client.get("/v1/materials/none/reports?" + query)).status_code == 422
    assert (await client.get("/v1/materials/none/reports")).status_code == 404


def test_same_pressure_replicates_and_criteria_are_not_collapsed():
    rows = [
        dict(
            paper_id="p",
            tc_kelvin=tc,
            pressure_gpa=150,
            tc_type=criterion,
            sample_label="S1",
            path_direction=direction,
            series_label="scan",
        )
        for tc, criterion, direction in (
            (240, "onset", "loading"),
            (232, "zero", "loading"),
            (236, "onset", "unloading"),
        )
    ]
    projection = report_projection("m", rows)
    points = projection["report_groups"][0]["points"]
    assert len(points) == 3 and len({p["point_id"] for p in points}) == 3
    assert [p["tc"]["value"] for p in points] == [240, 232, 236]


def test_malformed_legacy_identity_fields_remain_safe_unresolved_rows():
    report = report_projection(
        "m",
        [
            {
                "paper_id": ["bad"],
                "sample_label": {"bad": "label"},
                "source_locator": [],
                "tc_type": {"bad": "criterion"},
                "measurement": [],
                "year": "2026",
            }
        ],
    )
    point = report["report_groups"][0]["points"][0]
    assert point["paper_id"] is None and point["sample_label"] is None and point["method"] is None
    assert (
        point["tc_definition"] == "unknown"
        and point["source_locator"] == {}
        and point["year"] is None
    )


def test_unknowns_never_count_as_independent_support():
    projection = report_projection("m", [dict(tc_kelvin=20), dict(tc_kelvin=30)])
    assert len(projection["report_groups"]) == 2
    assert projection["support_counts"]["verified_unique_works"] == 0
    assert projection["coverage"]["no_claim_found_allowed"] is False


def packet(paper_id, *, job_key="synthetic-v3", provider="fixture"):
    from services.materials_v3_import import sha

    text = "Synthetic LaH10 sample S1 at 150 GPa: onset Tc 240 K; zero Tc 232 K."
    source_sha = hashlib.sha256(text.encode()).hexdigest()
    source = {
        "source_sha256": source_sha,
        "parser_version": "materials-blocks/1.1.0",
        "source_id": paper_id,
        "records": [{"source_start": 0, "source_end": len(text), "text": text}],
        "gaps": [],
    }
    manifest_hash = sha(source)
    source["manifest_sha256"] = manifest_hash
    proof = {
        "block_id": "synthetic-block",
        "quote": text,
        "role": "value",
        "source_start": 0,
        "source_end": len(text),
        "source_sha256": source_sha,
    }

    def quantity(raw, value, unit):
        return dict(
            raw_text=raw,
            value=value,
            lower=None,
            upper=None,
            raw_unit=unit,
            relation="point",
            approximate=False,
            uncertainty_raw=None,
        )

    def normalized(raw, value, unit):
        return dict(
            status="normalized",
            value=value,
            lower=None,
            upper=None,
            relation="point",
            unit=unit,
            raw=quantity(raw, value, unit),
        )

    props = [
        dict(
            property_key="tc",
            status="reported",
            quantity=quantity(f"{v} K", v, "K"),
            qualitative=None,
            qualifiers={"tc_definition": c},
            knowledge_origin="Observed",
            source_role="primary",
            evidence=[{k: proof[k] for k in ("block_id", "quote", "role")}],
        )
        for v, c in ((240, "onset"), (232, "zero_resistance"))
    ]
    raw = {
        "local_id": "synthetic-result",
        "subject": {"name_raw": "LaH10"},
        "sample": {"label_raw": "S1", "form_raw": "bulk", "preparation_raw": None},
        "series_point": {
            "series_label_raw": "pressure scan",
            "point_label_raw": "150 GPa",
            "path_direction": "loading",
            "replicate_label_raw": None,
        },
        "event": {
            "method_raw": "Synthetic resistivity",
            "knowledge_origin": "Observed",
            "source_role": "primary",
        },
        "sc_outcome": "positive_reported",
        "outcome_evidence": [],
        "properties": props,
        "conditions": [
            {
                "key": "measurement_pressure",
                "status": "reported",
                "quantity": quantity("150 GPa", 150, "GPa"),
                "qualitative": None,
            }
        ],
    }
    anchors = [
        [source_sha, text.index("240 K"), text.index("240 K") + 5],
        [source_sha, text.index("232 K"), text.index("232 K") + 5],
    ]
    config = {"provider": provider, "test_fixture": True}
    return {
        "paper_id": paper_id,
        "sclib_work_id": None,
        "job_key": job_key,
        "source_sha256": source_sha,
        "manifest_sha256": manifest_hash,
        "parser_version": source["parser_version"],
        "source_manifest": source,
        "source_version": "synthetic/1",
        "source_license": "synthetic",
        "transfer_allowed": False,
        "provider": provider,
        "model": "synthetic-fixture",
        "model_revision": None,
        "config": config,
        "config_sha256": sha(config),
        "prompt_version": "synthetic/1",
        "status": "completed",
        "usage": {},
        "validated_candidates": [
            {
                "local_id": raw["local_id"],
                "position_sha256": sha(anchors),
                "positions": {"source_anchors": anchors},
                "payload": raw,
                "validation": {
                    "locator_verified": True,
                    "schema_valid": True,
                    "scientific_acceptance": False,
                    "bound_evidence": [proof],
                    "normalized": {
                        "local_id": raw["local_id"],
                        "properties": [
                            {"key": "tc", "quantity": normalized(f"{v} K", v, "K")}
                            for v in (240, 232)
                        ],
                        "conditions": [
                            {
                                "key": "measurement_pressure",
                                "quantity": normalized("150 GPa", 150, "GPa"),
                            }
                        ],
                    },
                },
            }
        ],
        "block_coverage": [
            {
                "block_id": "synthetic-block",
                "input_sha256": "1" * 64,
                "status": "validated",
                "receipt": {},
            }
        ],
    }


async def test_candidate_import_replays_without_catalogue_writes(db_session):
    from models.db import MATERIALS_V3_TABLES as T
    from services.materials_v3_import import import_validated_run

    material, papers, _ = await seed(db_session)
    before = deepcopy(material.records)
    value = packet(papers[0].id, job_key=uuid4().hex)
    first = await import_validated_run(db_session, value)
    assert first == await import_validated_run(db_session, value)
    await db_session.refresh(material)
    assert material.records == before and first["catalogue_changed"] is False
    other = {
        **value,
        "job_key": uuid4().hex,
        "provider": "openai",
        "config": {"provider": "openai", "fixture": True},
    }
    from services.materials_v3_import import sha

    other["config_sha256"] = sha(other["config"])
    second = await import_validated_run(db_session, other)
    assert first["capture_id"] == second["capture_id"] and first["run_id"] != second["run_id"]
    count = (
        await db_session.execute(
            sa.select(sa.func.count())
            .select_from(T["ner_source_occurrences"])
            .where(T["ner_source_occurrences"].c.capture_id == first["capture_id"])
        )
    ).scalar_one()
    assert count == 1


async def test_private_snapshot_retains_two_criteria_and_obeys_source_holds(db_session):
    from services.materials_v3_import import import_validated_run
    from services.materials_v3_snapshots import read_candidate_snapshot, save_candidate_snapshot

    material, papers, _ = await seed(db_session)
    imported = await import_validated_run(db_session, packet(papers[0].id, job_key=uuid4().hex))
    arguments = dict(
        run_ids=[imported["run_id"]], material_bindings={imported["candidate_ids"][0]: material.id}
    )
    preview = await save_candidate_snapshot(db_session, **arguments)
    assert await read_candidate_snapshot(db_session, preview["snapshot_id"], material.id) is None
    saved = await save_candidate_snapshot(db_session, **arguments, dry_run=False)
    assert saved == await save_candidate_snapshot(db_session, **arguments, dry_run=False)
    page = await read_candidate_snapshot(db_session, saved["snapshot_id"], material.id)
    points = page["report_groups"][0]["points"]
    assert [p["tc"]["value"] for p in points] == [240, 232]
    assert [p["tc_definition"] for p in points] == ["onset", "zero_resistance"]
    assert len({p["physical_point_id"] for p in points}) == 1
    assert page["support_counts"]["independent_data_groups"] is None
    papers[0].status = "retracted"
    await db_session.flush()
    hidden = await read_candidate_snapshot(db_session, saved["snapshot_id"], material.id)
    assert hidden["report_groups"] == [] and hidden["total_points"] == 0


async def test_candidate_snapshot_requires_model_selection(db_session):
    from services.materials_v3_import import import_validated_run
    from services.materials_v3_snapshots import save_candidate_snapshot

    material, papers, _ = await seed(db_session)
    one = packet(papers[0].id, job_key=uuid4().hex)
    first = await import_validated_run(db_session, one)
    second = await import_validated_run(db_session, {**one, "job_key": uuid4().hex})
    with pytest.raises(ValueError, match="one_interpretation"):
        await save_candidate_snapshot(
            db_session, run_ids=[first["run_id"], second["run_id"]], material_bindings={}
        )


async def test_private_snapshot_route_requires_reviewer(client, registered_user):
    path = f"/v1/admin/materials-v3/snapshots/{uuid4()}/materials/none"
    assert (await client.get(path)).status_code == 401
    assert (
        await client.get(path, headers={"Authorization": f"Bearer {registered_user[1]}"})
    ).status_code == 403


def test_preview_retains_unresolved_raw_values_separately_from_absent_fields():
    from services.materials_v3_snapshots import _quantity

    raw = {"raw_text": "4 THz", "raw_unit": "THz"}
    value = _quantity(
        {"status": "unresolved", "reason": "frequency_convention_requires_review", "raw": raw}
    )
    assert value["status"] == "unresolved" and value["raw_value"] == raw
    assert value["reason"] == "frequency_convention_requires_review" and value["value"] is None
    assert _quantity(None)["status"] == "unreported"


@pytest.mark.parametrize(
    ("origin", "role", "expected"),
    [
        ("Observed", "measurement_pressure", 150),
        ("Computed", "calculation_pressure", 170),
        ("Unknown", "unknown", None),
        ("Inferred", "unknown", None),
    ],
)
def test_preview_pairs_tc_with_its_pressure_role_and_retains_other_conditions(
    origin, role, expected
):
    from copy import deepcopy

    from services.materials_v3_snapshots import candidate_points

    value = packet("synthetic-pressure")
    candidate = value["validated_candidates"][0]
    raw, normalized = candidate["payload"], candidate["validation"]["normalized"]
    for prop in raw["properties"]:
        prop["knowledge_origin"] = origin
    for key, pressure in (("calculation_pressure", 170), ("synthesis_pressure", 100)):
        condition = deepcopy(raw["conditions"][0])
        condition["key"] = key
        condition["quantity"].update(value=pressure, raw_text=f"{pressure} GPa")
        raw["conditions"].append(condition)
        normalized["conditions"].append(
            {"key": key, "quantity": {**normalized["conditions"][0]["quantity"], "value": pressure}}
        )
    rows = candidate_points(
        {**candidate, "id": uuid4(), "occurrence_id": uuid4()},
        {
            "id": uuid4(),
            "work_id": None,
            "paper_id": value["paper_id"],
            "source_sha256": value["source_sha256"],
        },
        {"config_sha256": value["config_sha256"]},
        None,
    )
    assert len(rows) == 2 and {r["tc_definition"] for r in rows} == {"onset", "zero_resistance"}
    for row in rows:
        assert row["pressure_role"] == role and row["pressure"]["value"] == expected
        assert {c["key"]: c["quantity"]["value"] for c in row["conditions"]} == {
            "measurement_pressure": 150,
            "calculation_pressure": 170,
            "synthesis_pressure": 100,
        }
        if expected is None:
            assert row["pressure"]["status"] == "unreported"


def test_preview_never_borrows_measurement_pressure_for_computed_tc():
    from services.materials_v3_snapshots import candidate_points

    value = packet("synthetic-computed")
    candidate = value["validated_candidates"][0]
    for prop in candidate["payload"]["properties"]:
        prop["knowledge_origin"] = "Computed"
    rows = candidate_points(
        {**candidate, "id": uuid4(), "occurrence_id": uuid4()},
        {
            "id": uuid4(),
            "work_id": None,
            "paper_id": value["paper_id"],
            "source_sha256": value["source_sha256"],
        },
        {"config_sha256": value["config_sha256"]},
        None,
    )
    assert all(
        r["pressure_role"] == "calculation_pressure" and r["pressure"]["status"] == "unreported"
        for r in rows
    )
    assert all(r["conditions"][0]["quantity"]["value"] == 150 for r in rows)


def test_preview_rejects_mispaired_condition_normalization():
    from services.materials_v3_snapshots import candidate_points

    value = packet("synthetic-condition-mismatch")
    candidate = value["validated_candidates"][0]
    candidate["validation"]["normalized"]["conditions"][0]["key"] = "synthesis_pressure"
    with pytest.raises(ValueError, match="candidate_normalization_condition_mismatch"):
        candidate_points(candidate, {}, {}, None)


async def test_import_rejects_forged_evidence_before_any_insert(db_session):
    from models.db import MATERIALS_V3_TABLES as T
    from services.materials_v3_import import import_validated_run

    material, papers, _ = await seed(db_session)
    value = packet(papers[0].id, job_key=uuid4().hex)
    value["validated_candidates"][0]["validation"]["bound_evidence"][0]["quote"] = "fabricated"
    before = (
        await db_session.execute(sa.select(sa.func.count()).select_from(T["ner_extraction_runs"]))
    ).scalar_one()
    with pytest.raises(ValueError, match="evidence_source_mismatch"):
        await import_validated_run(db_session, value)
    assert (
        await db_session.execute(sa.select(sa.func.count()).select_from(T["ner_extraction_runs"]))
    ).scalar_one() == before
