"""Actual disposable SQL v2 ML fixtures; no real calculation or scientific grant.

Source documents, producer executions and review declarations are synthetic.
All base/result/source/coordinate pins are nevertheless actual SQL row hashes
and retained bytes, followed by the real 0054 freeze and 0064 companion path.
The original v1 integration fixtures are reused without modification.
"""
from __future__ import annotations

import hashlib
import json
import os
import statistics
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from models.db import Base
from models.ml_task_v2 import (
    CONTEXT_VERSION,
    STRUCTURE_FEATURES,
    UNITS,
    default_task_v2,
    protocol_template,
    selector_for,
    validate_protocol,
)
from services.ml_scientific_features import protocol_data_template
from services.research_release_manifest import canonical, digest
from services.source_registry import SOURCE_REGISTRY_VERSION, import_source_provenance_bundle
from tests.test_ml_task_dataset_sql import (
    eligible_specs,
    freeze_task_candidates,
    seed_task_candidates,
)
from tests.test_research_freeze import add
from tests.test_research_freeze import db_session as db_session
from tests.test_research_release_schema import capture


async def retain_artifact(db, fixture, kind, document, *, version, metadata=None):
    payload = document if type(document) is bytes else canonical(document)
    sha = hashlib.sha256(payload).hexdigest()
    fixture["args"]["artifact_bytes"][sha] = payload
    cache = fixture.setdefault("v2_artifacts", {})
    key = kind, version, sha
    if key not in cache:
        cache[key] = await add(db, "evidence_artifacts", kind=kind, schema_version=version,
            source="synthetic-ml-v2-not-actual-computation", record_sha256=sha, bytes_sha256=sha,
            hash_status="verified", access="restricted", metadata=metadata or {"synthetic": True})
    return cache[key]


async def row_pin(db, table, identifier):
    await db.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    row = await capture(db, table, identifier)
    return {"table": table, "row_id": str(identifier), "row_sha256": digest(row)}


async def coordinate_structure(db, fixture, key, *, coordinate_format="sclib-coordinate/1.0.0"):
    candidate = fixture["candidates"][key]
    index = list(fixture["candidates"]).index(key)
    formula = candidate["material"]["formula"]
    species = ["Mg", "B", "B"] if formula == "MgB2" else [formula]
    edge = 3.0 + index * 0.2
    sites = [{"element": symbol, "fractional": [position / len(species)] * 3, "occupancy": 1.0}
             for position, symbol in enumerate(species)]
    document = {"version": "sclib-coordinate/1.0.0", "boundary_conditions": "bulk_3d_periodic",
                "cell_angstrom": [[edge, 0.0, 0.0], [0.0, edge, 0.0], [0.0, 0.0, edge]], "sites": sites}
    if coordinate_format == "vasp-poscar/1.0.0":
        names = list(dict.fromkeys(species))
        lines = ["Synthetic POSCAR; not a measured structure", "1.0",
                 f"{edge} 0 0", f"0 {edge} 0", f"0 0 {edge}", " ".join(names),
                 " ".join(str(species.count(name)) for name in names), "Direct"]
        lines += [" ".join(str(value) for value in site["fractional"]) for site in sites]
        payload = ("\n".join(lines) + "\n").encode("utf-8")
    else:
        payload = canonical(document)
    artifact = await retain_artifact(db, fixture, "structure", payload, version=coordinate_format)
    structure = await add(db, "structure_records", material_id=candidate["material"]["id"],
        artifact_id=artifact["id"], coordinate_artifact_kind="structure", structure_kind="coordinates",
        source_version="synthetic-coordinate-version-1", occupancy_context={"synthetic": True},
        record_sha256=digest({"synthetic": True, "coordinate_bytes_sha256": artifact["bytes_sha256"]}))
    events = Base.metadata.tables["research_events"]
    await db.execute(events.update().where(events.c.id == candidate["event"]["id"]).values(structure_id=structure["id"]))
    input_row = await add(db, "ml_example_inputs", example_id=candidate["example"]["id"],
        input_kind="structure", input_structure_id=structure["id"], feature_key="coordinate_structure",
        matching_policy_version="ml-feature-application/1.0.0",
        record_sha256=digest({"synthetic": True, "structure_id": str(structure["id"])}))
    return {"structure": structure, "artifact": artifact, "input": input_row,
            "document": document, "coordinate_format": coordinate_format}


async def physical_protocols(db, fixture):
    artifacts, protocols, settings_by_key = {}, {}, {}
    for key in sorted(UNITS):
        data = protocol_data_template(key)
        if "reference_ensemble" in data:
            data["reference_ensemble"].update(thermodynamic_potential="energy", pressure_gpa=0.0,
                temperature_k=300.0, entries=[{"reference_id": "synthetic-" + formula,
                    "formula": formula, "energy_per_atom": -1.0}
                    for formula in ("Mg", "B2", "Nb", "Pb", "Ta", "Sn")])
        if "q_sampling" in data:
            data["q_sampling"].update(mode="grid", grid=[4, 4, 4], offset=[0.0, 0.0, 0.0])
        if "broadening_scheme" in data:
            data["broadening_scheme"].update(method="gaussian", electronic_width_ev=0.02,
                phonon_width_thz=0.01, integration_rule="trapezoidal", frequency_grid_thz=[0.1, 1.0, 3.0])
        settings = {"synthetic": True, "actual_calculation_executed": False, "xc": "synthetic-pbe",
                    "k_mesh": [4, 4, 4], "cutoff_ev": 500.0, "scientific_protocol_data": data}
        protocol = protocol_template(key)
        protocol.update(method_name="synthetic-normal-state-" + protocol["method_kind"],
            code_version="synthetic-not-executed/1", settings_schema_version="synthetic-physics-settings/1",
            settings_sha256=digest(settings))
        details = protocol["details"]
        if key in {"formation_energy_per_atom", "energy_above_hull"}:
            details.update(thermodynamic_potential="energy", nuclear_treatment="static_lattice",
                           reference_ensemble_sha256=digest(data["reference_ensemble"]))
        elif key == "band_gap":
            details.update(spin_treatment="non_spin_polarized", occupation_treatment="zero_temperature")
        elif key == "dos_at_fermi":
            details.update(broadening_method="gaussian", broadening_ev=0.02)
        else:
            details.update(nuclear_treatment="harmonic", q_sampling_sha256=digest(data["q_sampling"]))
            if key in {"electron_phonon_lambda", "omega_log"}:
                details["broadening_scheme_sha256"] = digest(data["broadening_scheme"])
        for name, document in data.items():
            artifacts[key + ":" + name] = await retain_artifact(db, fixture, "policy", document, version=document["version"])
        settings_by_key[key] = settings
        protocols[key] = validate_protocol(protocol)
    return protocols, settings_by_key, artifacts


async def computed_property(db, fixture, key, property_key, *, structure, protocol, settings,
                            reference_artifacts, value, relation="exact", state_id=None,
                            dependencies=(), feature_key=None, raw_overrides=None, shared_result=None):
    candidate = fixture["candidates"][key]
    state_id = candidate["state"]["id"] if state_id is None else state_id
    if shared_result:
        run, event = shared_result["run"], shared_result["event"]
    else:
        decision = await retain_artifact(db, fixture, "review", {"synthetic": True,
            "property": property_key, "purpose": "declared technical fixture, not scientific approval"},
            version="synthetic-physics-review/1")
        run = await add(db, "research_runs", run_kind=protocol["method_kind"], status="completed",
            code_version=protocol["code_version"], settings_schema_version=protocol["settings_schema_version"],
            settings=settings, record_sha256=digest({"synthetic": True, "case": key, "property": property_key}))
        event = await add(db, "research_events", material_id=candidate["material"]["id"], state_id=state_id,
            structure_id=structure["structure"]["id"], producer_run_id=run["id"], event_type="calculation",
            knowledge_origin="Computed", review_status="approved", validity_status="accepted",
            decision_artifact_id=decision["id"], record_sha256=digest({"synthetic": True, "run": str(run["id"])}))
    prop = await add(db, "event_properties", event_id=event["id"], property_key=property_key,
        registry_version="rv2/1", component_key="bulk", relation=relation, value=value, unit=UNITS[property_key],
        raw={"synthetic": True, "property_key": property_key, "value": value, "unit": UNITS[property_key],
             **(raw_overrides or {})},
        record_sha256=digest({"synthetic": True, "property": property_key, "value": value}))
    for name, artifact in ({} if shared_result else reference_artifacts).items():
        await add(db, "event_evidence", event_id=event["id"], link_type="source", artifact_id=artifact["id"],
                  locator={"section": "synthetic protocol " + name})
    for dependency in dependencies:
        await add(db, "event_evidence", event_id=event["id"], link_type="derives_from",
            input_event_id=dependency["event_id"],
            input_claim_id=dependency["row_id"] if dependency["table"] == "material_claims" else None,
            input_property_id=dependency["row_id"] if dependency["table"] == "event_properties" else None)
    structure_pin = await row_pin(db, "structure_records", structure["structure"]["id"])
    property_pin = await row_pin(db, "event_properties", prop["id"])
    dependency_pins = [await row_pin(db, item["table"], item["row_id"]) for item in dependencies]
    input_document = {"version": "ml-computed-input/1.0.0", "run_id": str(run["id"]),
        "structure_id": structure_pin["row_id"], "structure_row_sha256": structure_pin["row_sha256"],
        "normal_state": True, "target_data_used": False, "dependency_results": dependency_pins}
    output_document = {"version": "ml-computed-output/1.0.0", "run_id": str(run["id"]), "result_refs": [property_pin]}
    if shared_result:
        assert input_document == shared_result["input_document"]
        output_document["result_refs"] = sorted([*shared_result["output_document"]["result_refs"], property_pin],
                                                 key=lambda row: (row["table"], row["row_id"]))
        # Retain the earlier actual output document as explicit audit evidence,
        # then replace the run's current manifest with the complete two-result inventory.
        await add(db, "event_evidence", event_id=event["id"], link_type="source",
            artifact_id=shared_result["output_artifact"]["id"], locator={"section": "synthetic prior producer output revision"})
    input_artifact = await retain_artifact(db, fixture, "run_manifest", input_document, version=input_document["version"])
    output_artifact = await retain_artifact(db, fixture, "run_manifest", output_document, version=output_document["version"])
    runs = Base.metadata.tables["research_runs"]
    await db.execute(runs.update().where(runs.c.id == run["id"]).values(
        input_manifest_id=input_artifact["id"], output_manifest_id=output_artifact["id"]))
    ml_input = await add(db, "ml_example_inputs", example_id=candidate["example"]["id"], input_kind="property",
        input_event_id=event["id"], input_property_id=prop["id"], feature_key=feature_key or property_key,
        matching_policy_version="ml-feature-application/1.0.0", record_sha256=digest(property_pin))
    return {"event": event, "property": prop, "input": ml_input, "run": run,
            "input_document": input_document, "output_document": output_document,
            "input_artifact": input_artifact, "output_artifact": output_artifact,
            "scientific_context": {"version": CONTEXT_VERSION, "normal_state": True,
                                   "target_derived": False, "protocol": protocol}}


async def seed_scientific_candidates(db, *, specs=None, properties=None, coordinate_format="sclib-coordinate/1.0.0",
                                    property_options=None, property_states=None, joint_epc=True):
    fixture = await seed_task_candidates(db, eligible_specs() if specs is None else specs)
    protocols, settings, artifacts = await physical_protocols(db, fixture)
    fixture.update(protocols=protocols, physics={}, structures={}, settings=settings, reference_artifacts=artifacts)
    selected = sorted(UNITS if properties is None else properties)
    for index, key in enumerate(fixture["candidates"]):
        states = Base.metadata.tables["material_states"]
        await db.execute(states.update().where(states.c.id == fixture["candidates"][key]["state"]["id"]).values(
            temperature_role="measurement", temperature_k=300.0,
            conditions={"magnetic_field_t": 0.0, "phase": "synthetic-bulk-phase"}))
        structure = await coordinate_structure(db, fixture, key, coordinate_format=coordinate_format)
        fixture["structures"][key] = structure
        values = {"formation_energy_per_atom": -0.3 - index * 0.1, "energy_above_hull": index * 0.01,
                  "band_gap": index * 0.1, "dos_at_fermi": 1.5 + index * 0.1,
                  "electron_phonon_lambda": 0.7 + index * 0.1, "omega_log": 200.0 + index * 10,
                  "phonon_min_frequency": float(index)}
        fixture["physics"][key] = {}
        alternate_state = None
        if key in (property_states or {}):
            old = dict(await capture(db, "material_states", fixture["candidates"][key]["state"]["id"]))
            for removed in ("id", "created_at"):
                old.pop(removed)
            old.update(deepcopy(property_states[key]))
            if old["sample_id"] == "synthetic-different-sample":
                sample = await add(db, "research_samples", material_id=old["material_id"],
                    work_id=fixture["candidates"][key]["work"]["id"], sample_label="different-synthetic-specimen",
                    source_artifact_id=old["source_artifact_id"])
                old["sample_id"] = sample["id"]
            alternate_state = (await add(db, "material_states", **old))["id"]
        for property_key in selected:
            options = {"value": values[property_key], "state_id": alternate_state,
                       **deepcopy((property_options or {}).get((key, property_key), {}))}
            if joint_epc and property_key == "omega_log" and "electron_phonon_lambda" in fixture["physics"][key]:
                options["shared_result"] = fixture["physics"][key]["electron_phonon_lambda"]
            fixture["physics"][key][property_key] = await computed_property(db, fixture, key, property_key,
                structure=structure, protocol=protocols[property_key], settings=settings[property_key],
                reference_artifacts=artifacts, **options)
    task = default_task_v2()
    task["physical_features"] = [selector_for(protocols[key]) for key in selected]
    task["structure_features"] = list(STRUCTURE_FEATURES)
    fixture["task"] = task
    return fixture


def input_items(fixture):
    for key, structure in fixture["structures"].items():
        context = {"version": "ml-structure-context/1.0.0", "coordinate_format": structure["coordinate_format"],
            "geometry_scope": "bulk_3d_no_vacuum", "source_formula": fixture["candidates"][key]["material"]["formula"],
            "normal_state_verified": True, "target_derived": False,
            "phase": "synthetic-bulk-phase", "magnetic_field_t": 0.0, "pressure_gpa": 0.0}
        yield key, "structure", structure, context
        for name, item in fixture["physics"][key].items():
            yield key, name, item, item["scientific_context"]


async def feature_source(db, fixture, key, *, available_at="2019-01-01T00:00:00Z", version_status="pinned", work_group=None):
    token = uuid4().hex
    work_cache = fixture.setdefault("feature_source_works", {})
    work_key = work_group or token
    if work_key not in work_cache:
        work_cache[work_key] = await add(db, "works", canonical_title="Synthetic normal-state input " + token)
    work = work_cache[work_key]
    paper = await add(db, "papers", id="ml-v2-source-" + token, source="arxiv", status="published",
        title="Synthetic normal-state feature fixture", authors=[], abstract="Not a real computation")
    await add(db, "paper_work_map", paper_id=paper["id"], work_id=work["id"], relation_type="preprint",
        match_method="manual", review_status="accepted")
    payload = canonical({"synthetic": True, "case": key,
        "coordinates": fixture["structures"][key]["document"],
        "properties": {name: {"value": item["property"]["value"], "unit": item["property"]["unit"]}
                       for name, item in fixture["physics"][key].items()}})
    sha = hashlib.sha256(payload).hexdigest()
    bundle = {"version": SOURCE_REGISTRY_VERSION, "source_revisions": [{"id": str(uuid4()),
        "paper_id": paper["id"], "work_id": str(work["id"]), "revision_key": "synthetic-v1",
        "provider_revision": "v1", "version_status": version_status,
        "availability_status": "known_by" if available_at else "unknown",
        "availability_basis": "verified_provider_version_history" if available_at else "unknown",
        "source_version_public_at": available_at, "metadata_sha256": digest({"synthetic": True, "id": token})}],
        "source_captures": [], "claim_source_occurrences": []}
    bundle["source_captures"] = [{"id": str(uuid4()), "source_revision_id": bundle["source_revisions"][0]["id"],
        "capture_key": "synthetic-own-feature-source", "captured_at": max(available_at or "", "2026-01-01T00:00:00Z"),
        "bytes_sha256": sha, "representation": "arxiv_source"}]
    await import_source_provenance_bundle(db, bundle, dry_run=False)
    return {"revision": await capture(db, "source_revisions", bundle["source_revisions"][0]["id"]),
        "capture": await capture(db, "source_captures", bundle["source_captures"][0]["id"]),
        "bytes": payload, "sha": sha}


async def attach_companion(db, fixture, release, base_bytes, *, overrides=None, omit=()):
    from services import ml_feature_companion as companion_service

    overrides = overrides or {}
    all_bytes, sources, bindings = dict(base_bytes), {}, {}
    for key, name, item, context in input_items(fixture):
        if (key, name) in omit:
            continue
        options = deepcopy(overrides.get((key, name), {}))
        source_key = (key, options.get("available_at", "2019-01-01T00:00:00Z"), options.get("version_status", "pinned"), options.get("work_group"))
        if source_key not in sources:
            sources[source_key] = await feature_source(db, fixture, key,
                available_at=source_key[1], version_status=source_key[2], work_group=source_key[3])
        source = sources[source_key]
        all_bytes[source["sha"]] = source["bytes"]
        locator = {"section": "synthetic coordinates"} if name == "structure" else {
            "table": "normal-state", "row": sorted(UNITS).index(name) + 1}
        application = {"mode": options.get("mode", "exact"), "scope": "same_composition_pressure_field_phase",
            "applicability_verified": True, "rationale": "Synthetic exact reviewed applicability declaration",
            "uncertainty_note": "Technical fixture only, not independent scientific or source authority"}
        document = companion_service.feature_source_review_payload(release["manifest"],
            example_input_id=str(item["input"]["id"]), source_revision=source["revision"], capture=source["capture"],
            locator=locator, scientific_context=options.get("context", context), applicability=application)
        document.update(binding_verified=True, version_resolved=source_key[2] == "pinned",
                        public_time_verified=source_key[1] is not None)
        artifact = await retain_artifact(db, fixture, "review", document, version=companion_service.REVIEW_VERSION,
            metadata={"ml_feature_source_review": document})
        all_bytes[artifact["bytes_sha256"]] = canonical(document)
        binding = await companion_service.register_feature_source_binding(db,
            base_release_id=release["release_id"], example_input_id=str(item["input"]["id"]),
            source_revision_id=source["revision"]["id"], capture_id=source["capture"]["id"], locator=locator,
            review_artifact_id=str(artifact["id"]), expected_review_sha256=artifact["record_sha256"],
            source_bytes=source["bytes"], review_bytes=canonical(document), dry_run=False)
        bindings[(key, name)] = {"binding": binding, "review": document, "source": source}
    companion = await companion_service.capture_feature_companion(db, base_manifest=release["manifest"],
        expected_base_manifest_sha256=release["manifest_sha256"], artifact_bytes=all_bytes)
    fixture["feature_bindings"] = bindings
    return companion


async def freeze_scientific_candidates(db, fixture, *, overrides=None, omit=()):
    release, base_bytes = await freeze_task_candidates(db, fixture)
    companion = await attach_companion(db, fixture, release, base_bytes, overrides=overrides, omit=omit)
    return {"release": release, "artifact_bytes": base_bytes, "companion": companion, "task": fixture["task"]}


def compile_scientific(inputs):
    from services.ml_dataset_builder_v2 import build_task_dataset_v2
    return build_task_dataset_v2(inputs["release"]["manifest"], artifact_bytes=inputs["artifact_bytes"],
        expected_manifest_sha256=inputs["release"]["manifest_sha256"], companion=inputs["companion"],
        expected_companion_sha256=digest(inputs["companion"]), task=inputs["task"],
        expected_task_sha256=digest(inputs["task"]))


@pytest.mark.parametrize("coordinate_format", ["sclib-coordinate/1.0.0", "vasp-poscar/1.0.0"])
async def test_actual_frozen_inputs_get_own_reviewed_source_companion(db_session, coordinate_format):
    from services.ml_feature_companion import verify_feature_companion
    fixture = await seed_scientific_candidates(db_session, properties=["band_gap"], coordinate_format=coordinate_format)
    inputs = await freeze_scientific_candidates(db_session, fixture)
    contexts = verify_feature_companion(inputs["companion"], base_manifest=inputs["release"]["manifest"],
        expected_base_manifest_sha256=inputs["release"]["manifest_sha256"],
        expected_companion_sha256=digest(inputs["companion"]))
    assert len(contexts) == 10
    for context in contexts.values():
        assert context["temporal"]["result_available_at"] == "2019-01-01T00:00:00Z"
        assert context["scientific_acceptance"] is context["ml_training_approved"] is False
        assert context["reviewer_authority_authenticated"] is False
    bundle = compile_scientific(inputs)
    assert bundle["coverage"]["cohort_counts"] == {"B": 5, "P": 5, "S": 5, "PS": 5}, bundle["dependency_manifest"]["feature_admission"]
    assert bundle["gate"]["status"] == "pass", bundle["views"]


async def test_actual_physical_and_coordinate_inputs_freeze_with_real_producer_bytes(db_session):
    fixture = await seed_scientific_candidates(db_session)
    release, artifact_bytes = await freeze_task_candidates(db_session, fixture)
    rows = {(row["table"], row["row_id"]): row for row in release["manifest"]["rows"]}
    assert sum(table == "ml_examples" for table, _ in rows) == 5
    assert sum(table == "ml_example_inputs" for table, _ in rows) == 40
    assert sum(table == "event_properties" for table, _ in rows) == 35
    assert sum(table == "structure_records" for table, _ in rows) == 5
    for inputs in fixture["physics"].values():
        left, right = inputs["electron_phonon_lambda"], inputs["omega_log"]
        assert left["run"]["id"] == right["run"]["id"]
        assert left["event"]["id"] == right["event"]["id"]
        actual_run = rows[("research_runs", str(left["run"]["id"]))]["data"]
        actual_output = rows[("evidence_artifacts", actual_run["output_manifest_id"])]["data"]
        output_document = json.loads(artifact_bytes[actual_output["bytes_sha256"]])
        assert {item["row_id"] for item in output_document["result_refs"]} == {
            str(left["property"]["id"]), str(right["property"]["id"])}
        for item in inputs.values():
            prop_pin = item["output_document"]["result_refs"][0]
            assert rows[(prop_pin["table"], prop_pin["row_id"])]["row_sha256"] == prop_pin["row_sha256"]
            for name in ("input", "output"):
                artifact = item[name + "_artifact"]
                assert artifact_bytes[artifact["bytes_sha256"]] == canonical(item[name + "_document"])
    for structure in fixture["structures"].values():
        assert artifact_bytes[structure["artifact"]["bytes_sha256"]] == canonical(structure["document"])
    assert release["scientific_acceptance"] is release["ml_training_approved"] is False
    companion = await attach_companion(db_session, fixture, release, artifact_bytes)
    inputs = {"release": release, "artifact_bytes": artifact_bytes, "companion": companion, "task": fixture["task"]}
    bundle = compile_scientific(inputs)
    assert bundle == compile_scientific(inputs)
    assert bundle["coverage"]["cohort_counts"] == {"B": 5, "P": 5, "S": 5, "PS": 5}
    assert len(bundle["dependency_manifest"]["feature_admission"]) == 40
    assert all(item["status"] == "admitted" for item in bundle["dependency_manifest"]["feature_admission"])
    assert bundle["gate"]["status"] == "pass"
    assert_fair_views(bundle)
    view = bundle["views"]["CP@P"]
    first = next(row for row in view["rows"] if row["example_id"] == str(fixture["candidates"]["one"]["example"]["id"]))
    for name in ("band_gap", "energy_above_hull", "phonon_min_frequency"):
        index = view["feature_names"].index(name)
        assert first["raw_features"][index] == 0.0
        assert first["missingness"][index] is False
    assert bundle["data_card"]["classification_negatives_created"] == 0
    assert all(value is False for value in bundle["authority"].values())


def assert_fair_views(bundle):
    base = {row["example_id"]: (row["group_id"], row["split"], row["assignment_sha256"]) for row in bundle["rows"]}
    assert bundle["split_report"]["subset_resplitting"] is False
    for comparison in bundle["comparisons"]:
        inventories = []
        for name in comparison:
            view = bundle["views"][name]
            inventories.append([(row["example_id"], row["assignment_sha256"]) for row in view["rows"]])
        assert all(inventory == inventories[0] for inventory in inventories)
    for view in bundle["views"].values():
        for row in view["rows"]:
            assert (row["group_id"], row["split"], row["assignment_sha256"]) == base[row["example_id"]]
        if view["preprocessing"]:
            training = [row for row in view["rows"] if row["split"] == "train"]
            for item in view["preprocessing"]["parameters"]["statistics"]:
                values = [row["raw_features"][item["index"]] for row in training if row["raw_features"][item["index"]] is not None]
                assert item["observed_train_count"] == len(values)
                assert item["median"] == statistics.median(values)
                fitted = [row["raw_features"][item["index"]] if row["raw_features"][item["index"]] is not None
                          else statistics.median(values) for row in training]
                assert item["mean"] == pytest.approx(statistics.fmean(fitted))
                assert item["std"] == pytest.approx(statistics.pstdev(fitted))


def audit_for(bundle, fixture, key, feature):
    item = fixture["structures"][key] if feature == "structure" else fixture["physics"][key][feature]
    return next(row for row in bundle["dependency_manifest"]["feature_admission"] if row["input_id"] == str(item["input"]["id"]))


@pytest.mark.parametrize(("name", "options", "reason"), [
    ("band_gap", {"available_at": "2021-01-01T00:00:00Z"}, "feature_not_known_by_label_witness"),
    ("band_gap", {"available_at": "2026-02-01T00:00:00Z"}, "feature_temporal_ineligible"),
    ("band_gap", {"available_at": None}, "feature_temporal_ineligible"),
    ("band_gap", {"available_at": None, "version_status": "unresolved"}, "feature_temporal_ineligible"),
    ("structure", {"available_at": "2021-01-01T00:00:00Z"}, "feature_not_known_by_label_witness"),
])
async def test_feature_own_public_time_not_inherited_from_target_or_other_input(db_session, name, options, reason):
    fixture = await seed_scientific_candidates(db_session, properties=["band_gap"])
    inputs = await freeze_scientific_candidates(db_session, fixture, overrides={("one", name): options})
    bundle = compile_scientific(inputs)
    assert reason in audit_for(bundle, fixture, "one", name)["reason_codes"]
    assert bundle["coverage"]["cohort_counts"]["B"] == 5
    assert bundle["coverage"]["cohort_counts"]["P"] == 4
    assert bundle["coverage"]["cohort_counts"]["S"] == (4 if name == "structure" else 5)
    assert_fair_views(bundle)


async def test_missing_coordinate_source_vetoes_computed_temporal_dependency_but_not_base(db_session):
    fixture = await seed_scientific_candidates(db_session, properties=["band_gap"])
    inputs = await freeze_scientific_candidates(db_session, fixture, omit={("one", "structure")})
    bundle = compile_scientific(inputs)
    assert "independent_feature_source_binding_missing" in audit_for(bundle, fixture, "one", "structure")["reason_codes"]
    assert "feature_temporal_ineligible" in audit_for(bundle, fixture, "one", "band_gap")["reason_codes"]
    assert bundle["coverage"]["cohort_counts"] == {"B": 5, "P": 4, "S": 4, "PS": 4}
    assert_fair_views(bundle)


@pytest.mark.parametrize(("mode", "overrides", "reason"), [
    ("exact", {}, "exact_feature_state_or_structure_mismatch"),
    ("normal_state_surrogate", {}, None),
    ("normal_state_surrogate", {"pressure_gpa": 1.0, "pressure_status": "reported"}, "feature_pressure_conflict"),
    ("normal_state_surrogate", {"conditions": {"magnetic_field_t": 0.0, "phase": "different-phase"}}, "feature_phase_conflict"),
    ("normal_state_surrogate", {"pressure_gpa": None, "pressure_status": "not_reported"}, "surrogate_requires_equal_explicit_pressure"),
    ("normal_state_surrogate", {"sample_id": "synthetic-different-sample"}, "feature_sample_conflict"),
])
async def test_exact_state_and_explicit_reviewed_normal_state_surrogate(db_session, mode, overrides, reason):
    state = {"temperature_role": "simulation", "temperature_k": 0.0, "sample_id": None, **overrides}
    fixture = await seed_scientific_candidates(db_session, properties=["band_gap"], property_states={"one": state})
    inputs = await freeze_scientific_candidates(db_session, fixture, overrides={("one", "band_gap"): {"mode": mode}})
    bundle = compile_scientific(inputs)
    audit = audit_for(bundle, fixture, "one", "band_gap")
    if reason:
        assert reason in audit["reason_codes"]
        assert audit["status"] == "excluded"
    else:
        assert audit["status"] == "admitted", audit
    assert bundle["coverage"]["cohort_counts"]["B"] == 5
    assert bundle["coverage"]["cohort_counts"]["P"] == (4 if reason else 5)
    assert_fair_views(bundle)


async def test_unreported_optional_value_is_missing_not_zero_or_negative_label(db_session):
    fixture = await seed_scientific_candidates(db_session, properties=["band_gap", "dos_at_fermi"],
        property_options={("one", "band_gap"): {"value": None, "relation": "unreported"}})
    bundle = compile_scientific(await freeze_scientific_candidates(db_session, fixture))
    assert "exact_finite_property_required" in audit_for(bundle, fixture, "one", "band_gap")["reason_codes"]
    view = bundle["views"]["CP@P"]
    row = next(row for row in view["rows"] if row["example_id"] == str(fixture["candidates"]["one"]["example"]["id"]))
    position = view["feature_names"].index("band_gap")
    assert row["raw_features"][position] is None
    assert row["missingness"][position] is True
    assert row["label"]["value"] == 39.0
    assert bundle["data_card"]["classification_negatives_created"] == 0
    assert_fair_views(bundle)


@pytest.mark.parametrize("alias", ["superconducting_gap", "coherence_length_nm"])
async def test_superconducting_responses_not_silently_renamed_to_band_gap(db_session, alias):
    fixture = await seed_scientific_candidates(db_session, properties=["band_gap"],
        property_options={("one", "band_gap"): {"feature_key": alias}})
    bundle = compile_scientific(await freeze_scientific_candidates(db_session, fixture))
    assert "unrequested_or_unsupported_property" in audit_for(bundle, fixture, "one", "band_gap")["reason_codes"]
    assert bundle["coverage"]["cohort_counts"]["B"] == 5
    assert bundle["coverage"]["cohort_counts"]["P"] == 4


async def test_actual_tc_lambda_renamed_dos_transitive_lineage_is_excluded(db_session):
    fixture = await seed_scientific_candidates(db_session, properties=["dos_at_fermi"])
    candidate = fixture["candidates"]["one"]
    prior = {"table": "material_claims", "row_id": candidate["claim"]["id"], "event_id": candidate["event"]["id"]}
    for name in ("electron_phonon_lambda", "dos_at_fermi"):
        item = await computed_property(db_session, fixture, "one", name,
            structure=fixture["structures"]["one"], protocol=fixture["protocols"][name], settings=fixture["settings"][name],
            reference_artifacts=fixture["reference_artifacts"], value=1.0, dependencies=[prior],
            feature_key="renamed_innocent_descriptor" if name == "dos_at_fermi" else name)
        fixture["physics"]["one"][name] = item
        prior = {"table": "event_properties", "row_id": item["property"]["id"], "event_id": item["event"]["id"]}
    bundle = compile_scientific(await freeze_scientific_candidates(db_session, fixture))
    audit = audit_for(bundle, fixture, "one", "dos_at_fermi")
    assert "target_dependency" in audit["reason_codes"]
    assert audit["status"] == "excluded"
    assert "unrequested_or_unsupported_property" in audit["reason_codes"]
    assert bundle["coverage"]["cohort_counts"]["B"] == 5
    assert any(row["dependencies"] for row in bundle["dependency_manifest"]["run_manifests"])


def write_cli_capsule(tmp_path, inputs):
    directory = tmp_path.resolve()
    capsule = directory / "capsule"
    capsule.mkdir()
    (capsule / "manifest.json").write_bytes(canonical(inputs["release"]["manifest"]))
    for sha, payload in inputs["artifact_bytes"].items():
        (capsule / (sha + ".bin")).write_bytes(payload)
    task, companion = directory / "task.json", directory / "companion.json"
    task.write_bytes(canonical(inputs["task"]))
    companion.write_bytes(canonical(inputs["companion"]))
    return ["--manifest", str(capsule / "manifest.json"), "--manifest-sha256", inputs["release"]["manifest_sha256"],
            "--task", str(task), "--task-sha256", digest(inputs["task"]),
            "--companion", str(companion), "--companion-sha256", digest(inputs["companion"])]


def run_scientific_cli(mode, arguments):
    root = Path(__file__).resolve().parents[2]
    return subprocess.run([sys.executable, str(root / "scripts" / "ml_scientific_dataset.py"), mode, *arguments],
        cwd=root, env={**os.environ, "DATABASE_URL": "postgresql://unused:unused@127.0.0.1:1/unused",
                      "REDIS_URL": "redis://127.0.0.1:1/0"},
        capture_output=True, text=True, timeout=45, check=False)


async def test_actual_sql_v2_cli_build_verify_and_repinned_tampering(db_session, tmp_path):
    fixture = await seed_scientific_candidates(db_session, properties=["band_gap"])
    inputs = await freeze_scientific_candidates(db_session, fixture)
    arguments = write_cli_capsule(tmp_path, inputs)
    output = tmp_path.resolve() / "compiled.json"
    result = run_scientific_cli("build", [*arguments, "--output", str(output)])
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["technical_gate"] == "pass" and report["output_written"] is True
    document = json.loads(output.read_bytes())
    assert document == compile_scientific(inputs)
    assert output.stat().st_mode & 0o777 == 0o600
    verified = run_scientific_cli("verify", [*arguments, "--bundle", str(output), "--bundle-sha256", digest(document)])
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["integrity_verified"] is True
    changed = deepcopy(document)
    changed["views"]["CP@P"]["rows"][0]["label"]["value"] = 1234.0
    output.write_bytes(canonical(changed))
    rejected = run_scientific_cli("verify", [*arguments, "--bundle", str(output), "--bundle-sha256", digest(changed)])
    assert rejected.returncode == 2
    assert json.loads(rejected.stderr) == {"status": "invalid", "output_written": False}
    missing_pin = run_scientific_cli("build", [*arguments[:-2], "--output", str(tmp_path.resolve() / "unwritten.json")])
    assert missing_pin.returncode == 2
    assert not (tmp_path.resolve() / "unwritten.json").exists()


async def test_actual_sql_v2_cli_no_go_does_not_write_training_dataset(db_session, tmp_path):
    fixture = await seed_scientific_candidates(db_session, properties=["band_gap"])
    omitted = {(key, "band_gap") for key in fixture["candidates"]}
    inputs = await freeze_scientific_candidates(db_session, fixture, omit=omitted)
    arguments = write_cli_capsule(tmp_path, inputs)
    output = tmp_path.resolve() / "not-approved.json"
    result = run_scientific_cli("build", [*arguments, "--output", str(output)])
    assert result.returncode == 3, result.stderr
    report = json.loads(result.stdout)
    assert report["technical_gate"] == "no_go" and report["output_written"] is False
    assert report["coverage"]["cohort_counts"]["B"] == 5
    assert not output.exists()


async def test_companion_work_bridge_groups_before_optional_feature_exclusion(db_session):
    fixture = await seed_scientific_candidates(db_session, properties=["band_gap"])
    inputs = await freeze_scientific_candidates(db_session, fixture, overrides={
        ("one", "band_gap"): {"work_group": "shared-physical-study", "available_at": "2021-01-01T00:00:00Z"},
        ("two", "band_gap"): {"work_group": "shared-physical-study"}})
    bundle = compile_scientific(inputs)
    rows = {row["example_id"]: row for row in bundle["rows"]}
    one, two = [rows[str(fixture["candidates"][key]["example"]["id"])] for key in ("one", "two")]
    assert one["group_id"] == two["group_id"]
    assert one["split"] == two["split"]
    assert len({row["group_id"] for row in rows.values()}) == 4
    assert audit_for(bundle, fixture, "one", "band_gap")["status"] == "excluded"
    assert_fair_views(bundle)


@pytest.mark.parametrize("target", ["source_bytes", "review_context", "base_row"])
async def test_actual_companion_source_review_and_base_tamper_rejected_even_with_new_outer_pin(db_session, target):
    import base64
    fixture = await seed_scientific_candidates(db_session, properties=["band_gap"])
    inputs = await freeze_scientific_candidates(db_session, fixture)
    changed = deepcopy(inputs)
    if target == "base_row":
        row = next(row for row in changed["release"]["manifest"]["rows"] if row["table"] == "event_properties")
        row["data"]["value"] = 9876.0
        row["row_sha256"] = digest(row["data"])
        changed["release"]["manifest_sha256"] = digest(changed["release"]["manifest"])
    elif target == "source_bytes":
        sha = fixture["feature_bindings"][("one", "band_gap")]["source"]["sha"]
        changed["companion"]["artifacts_base64"][sha] = base64.b64encode(b"different actual source bytes").decode()
    else:
        row = next(row for row in changed["companion"]["source_rows"] if row["table"] == "evidence_artifacts")
        row["data"]["metadata"]["ml_feature_source_review"]["scientific_context"]["target_derived"] = True
        row["row_sha256"] = digest(row["data"])
    changed["companion"]["companion_sha256"] = digest({key: value for key, value in changed["companion"].items() if key != "companion_sha256"})
    with pytest.raises(ValueError):
        compile_scientific(changed)


async def test_sql_rejects_duplicate_same_key_feature_instead_of_uuid_order_selection(db_session):
    fixture = await seed_scientific_candidates(db_session, properties=["band_gap"])
    original = dict(fixture["physics"]["one"]["band_gap"]["input"])
    original.pop("id")
    original.pop("created_at", None)
    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await add(db_session, "ml_example_inputs", **original)
    assert "uq_rv2_ml_feature" in str(error.value)
    table = Base.metadata.tables["ml_example_inputs"]
    assert (await db_session.execute(sa.select(sa.func.count()).select_from(table).where(
        table.c.example_id == original["example_id"], table.c.feature_key == "band_gap"))).scalar_one() == 1


@pytest.mark.parametrize(("field", "value"), [("target_derived", True), ("normal_state_verified", False)])
async def test_computed_feature_cannot_launder_target_derived_or_unreviewed_coordinate_parent(db_session, field, value):
    fixture = await seed_scientific_candidates(db_session, properties=["band_gap"])
    context = next(context for key, name, _, context in input_items(fixture) if key == "one" and name == "structure")
    context[field] = value
    inputs = await freeze_scientific_candidates(db_session, fixture, overrides={("one", "structure"): {"context": context}})
    bundle = compile_scientific(inputs)
    assert audit_for(bundle, fixture, "one", "structure")["status"] == "excluded"
    assert audit_for(bundle, fixture, "one", "band_gap")["status"] == "excluded"
    assert bundle["coverage"]["cohort_counts"] == {"B": 5, "P": 4, "S": 4, "PS": 4}
    assert_fair_views(bundle)


@pytest.mark.parametrize("selection", ["composition", "physics", "structure"])
async def test_unselected_optional_view_does_not_disable_actual_source_witness_dependencies(db_session, selection):
    fixture = await seed_scientific_candidates(db_session, properties=["band_gap"])
    if selection != "physics":
        fixture["task"]["physical_features"] = []
    if selection != "structure":
        fixture["task"]["structure_features"] = []
    bundle = compile_scientific(await freeze_scientific_candidates(db_session, fixture))
    expected = {"C@B"} | ({"C@P", "CP@P"} if selection == "physics" else
                            {"C@S", "CS@S"} if selection == "structure" else set())
    assert set(bundle["views"]) == expected
    assert all(len(view["rows"]) == 5 for view in bundle["views"].values())
    assert bundle["gate"]["status"] == "pass"
    assert_fair_views(bundle)


@pytest.mark.parametrize("joint_selected", [True, False])
async def test_epc_joint_features_require_same_producer_but_single_scalar_remains_usable(db_session, joint_selected):
    selected = ["electron_phonon_lambda", "omega_log"] if joint_selected else ["electron_phonon_lambda"]
    fixture = await seed_scientific_candidates(db_session, properties=selected, joint_epc=False)
    bundle = compile_scientific(await freeze_scientific_candidates(db_session, fixture))
    assert bundle["coverage"]["cohort_counts"]["B"] == 5
    assert bundle["coverage"]["cohort_counts"]["P"] == (0 if joint_selected else 5)
    for key in fixture["candidates"]:
        for name in selected:
            audit = audit_for(bundle, fixture, key, name)
            if joint_selected:
                assert audit["status"] == "excluded"
                assert "epc_joint_run_or_spectral_protocol_mismatch" in audit["reason_codes"]
            else:
                assert audit["status"] == "admitted", audit
    assert_fair_views(bundle)


async def test_not_detected_claim_is_still_target_information_for_computed_feature(db_session):
    fixture = await seed_scientific_candidates(db_session, properties=["band_gap"])
    candidate = fixture["candidates"]["one"]
    negative = dict(candidate["claim"])
    for key in ("id", "created_at", "updated_at"):
        negative.pop(key, None)
    raw = {"synthetic": True, "formula": "MgB2", "result_status": "not_detected", "minimum_temperature_k": 2.0}
    negative.update(result_key="synthetic-negative-input", source_record_hash=digest(raw), raw_record=raw,
        property_type="non_transition", result_status="not_detected", value_relation="unreported", value_kelvin=None,
        minimum_temperature_k=2.0)
    claim = await add(db_session, "material_claims", **negative)
    name = "dos_at_fermi"
    item = await computed_property(db_session, fixture, "one", name,
        structure=fixture["structures"]["one"], protocol=fixture["protocols"][name], settings=fixture["settings"][name],
        reference_artifacts=fixture["reference_artifacts"], value=2.0,
        dependencies=[{"table": "material_claims", "row_id": claim["id"], "event_id": candidate["event"]["id"]}])
    fixture["physics"]["one"][name] = item
    fixture["task"]["physical_features"].append(selector_for(fixture["protocols"][name]))
    bundle = compile_scientific(await freeze_scientific_candidates(db_session, fixture))
    audit = audit_for(bundle, fixture, "one", name)
    assert audit["status"] == "excluded" and "target_dependency" in audit["reason_codes"]
    assert bundle["coverage"]["cohort_counts"]["B"] == 5
    assert len(bundle["candidates"]) == 5
    assert all(row["label"]["value"] > 0 for row in bundle["rows"])
    assert bundle["data_card"]["classification_negatives_created"] == 0


async def test_huge_optional_structure_number_is_a_hold_not_a_base_compiler_crash(db_session):
    fixture = await seed_scientific_candidates(db_session, properties=["band_gap"])
    context = next(context for key, name, _, context in input_items(fixture) if key == "one" and name == "structure")
    context["pressure_gpa"] = 10 ** 1000
    inputs = await freeze_scientific_candidates(db_session, fixture, overrides={("one", "structure"): {"context": context}})
    bundle = compile_scientific(inputs)
    assert audit_for(bundle, fixture, "one", "structure")["status"] == "excluded"
    assert audit_for(bundle, fixture, "one", "band_gap")["status"] == "excluded"
    assert bundle["coverage"]["cohort_counts"] == {"B": 5, "P": 4, "S": 4, "PS": 4}
