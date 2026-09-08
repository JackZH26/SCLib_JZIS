"""Fixed-cohort composition/physics/coordinate comparisons, private and offline.

V1 contracts remain unchanged. Optional feature failures never erase an
independently eligible composition label. All captured relations are grouped
before one base split; subset comparisons reuse it without split repair.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict
from importlib.resources import files

from models.ml_task import require
from models.ml_task_v2 import selector_for, validate_task_v2
from services.ml_composition import ELEMENTS, FEATURE_NAMES, composition_features
from services.ml_coordinate_features import coordinate_features
from services.ml_dataset_builder import (
    AUTHORITY,
    DISCLOSURES,
    _claim_composition,
    _compiler,
    _declared_links,
    _Groups,
    _label_reasons,
    _pin,
    _ref,
    _split,
)
from services.ml_feature_companion import decode_companion_artifacts, verify_feature_companion
from services.ml_feature_provenance_v2 import (
    applicability_reasons,
    computed_lineage,
    data,
    validate_structure_context,
)
from services.ml_frozen_provenance import resolve_result_contexts
from services.ml_preprocessing import fit_transform
from services.ml_scientific_features import validate_property_feature
from services.research_release_manifest import canonical, digest, verify_manifest
from services.temporal_provenance import utc_datetime
from services.temporal_snapshots import evaluate_temporal_snapshot

VERSION = "ml-task-dataset/2.0.0"
PARTITIONS = ("train", "validation", "test")
_PROPERTY_SOURCE_REASONS = {"property_source_occurrence_contract_unavailable", "result_availability_unresolved",
                            "work_identity_unresolved"}


def _implementation():
    result = _compiler()
    result["version"] = VERSION
    result["required_runtime"] = "CPython >=3.11; locked API runtime; descriptor arithmetic uses standard library"
    for package, names in {"models": ["ml_task_v2"], "services": ["ml_dataset_builder_v2",
            "ml_feature_provenance_v2", "ml_feature_companion", "ml_scientific_features", "ml_coordinate_features"]}.items():
        for name in names:
            result["source_sha256"][package + "." + name] = hashlib.sha256(
                files(package).joinpath(name + ".py").read_bytes()).hexdigest()
    return result


def _groups(index, contexts, witnesses, lineage, task, artifacts):
    groups = _Groups()
    for ref, context in contexts.items():
        groups.join([("result", _ref(ref)), *context.group_keys,
                     *([("event", context.root.event_id)] if context.root.event_id else [])])
    for (table, identifier), envelope in sorted(index.items()):
        row = envelope["data"]
        if table == "research_events":
            groups.join([("event", identifier), ("material", row["material_id"]), ("state", row["state_id"]),
                *([("structure", row["structure_id"])] if row["structure_id"] else []),
                *([("run", row["producer_run_id"])] if row["producer_run_id"] else [])])
        elif table == "material_states":
            groups.join([("state", identifier), ("material", row["material_id"]),
                         *([("sample", row["sample_id"])] if row["sample_id"] else [])])
        elif table == "research_samples":
            groups.join([("sample", identifier), ("material", row["material_id"]),
                         *([("work", row["work_id"])] if row["work_id"] else [])])
        elif table == "structure_records":
            artifact = data(index, "evidence_artifacts", row["artifact_id"])
            groups.join([("structure", identifier), ("structure_ancestor", identifier),
                ("result", _ref((table, identifier))), ("material", row["material_id"]),
                *([("structure", row["parent_structure_id"])] if row["parent_structure_id"] else []),
                *([("coordinate_bytes", artifact["bytes_sha256"])] if row["structure_kind"] == "coordinates"
                  and artifact and artifact["hash_status"] == "verified" else [])])
        elif table == "event_evidence" and row["link_type"] != "source":
            groups.join([("event", row["event_id"]), ("event", row["input_event_id"])])
        elif table == "paper_work_map":
            groups.join([("paper", row["paper_id"]), ("work", row["work_id"])])
        elif table == "research_runs":
            groups.join([("run", identifier), *([("run", row["parent_run_id"])] if row["parent_run_id"] else []),
                *[("run_artifact", row[key]) for key in ("input_manifest_id", "output_manifest_id") if row[key]]])
        elif table == "ml_example_inputs":
            example = data(index, "ml_examples", row["example_id"])
            keys = [("result", _ref(("material_claims", example["claim_id"])))]
            for key, kind in (("input_claim_id", "claim"), ("input_property_id", "property"),
                              ("input_structure_id", "structure"), ("input_artifact_id", "artifact"),
                              ("input_event_id", "event")):
                if row[key]:
                    keys.append(("result", _ref(("material_claims" if kind == "claim" else "event_properties", row[key])))
                                if kind in {"claim", "property"} else (kind, row[key]))
            groups.join(keys)
    compositions, claim_compositions = {}, {}
    for (table, identifier), envelope in sorted(index.items()):
        if table == "materials":
            row = envelope["data"]
            descriptor = composition_features(row)
            compositions[identifier] = descriptor
            group_key = ("material", identifier)
            groups.join([group_key, *([("material", row["parent_material_id"])] if row["parent_material_id"] else [])])
        elif table == "material_claims":
            descriptor = _claim_composition(envelope["data"]["raw_record"])
            claim_compositions[(table, identifier)] = descriptor
            group_key = ("result", _ref((table, identifier)))
        else:
            continue
        if descriptor["status"] == "computed":
            fractions = descriptor["values"][:len(ELEMENTS)]
            groups.join([group_key, ("exact_composition", digest(fractions))])
            if task["split"]["mode"] == "chemical_system_extrapolation":
                system = "-".join(element for element, value in zip(ELEMENTS, fractions) if value > 0)
                groups.join([group_key, ("chemical_system", system)])
    for input_id, witness in sorted(witnesses.items()):
        row = data(index, "ml_example_inputs", input_id)
        example = data(index, "ml_examples", row["example_id"])
        groups.join([("result", _ref(("material_claims", example["claim_id"]))),
                     *[tuple(key) for key in witness["group_keys"]]])
    for ref, run in lineage.items():
        groups.join([("result", _ref(ref)), *[("result", _ref(dep)) for dep in run["dependencies"]]])
    _declared_links(task, index, artifacts, groups)
    ids = groups.identifiers()
    families = {}
    for (table, identifier), envelope in index.items():
        if table == "materials":
            families.setdefault(ids[("material", identifier)], set()).add(envelope["data"]["family"] or None)
    return ids, families, compositions, claim_compositions


def _target_ancestry(ref, dependencies, nodes):
    seen, pending = set(), [ref]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(dependencies.get(current, ()))
    # Any superconductivity outcome (including a non-transition, not only the
    # selected Tc), RPS, or superconducting-response
    # ancestor is excluded. A different material or a renamed key is no escape.
    return any(current[0] == "material_claims"
               or current[0] == "event_properties" and (
                   nodes[current].result_data["property_key"].startswith("rps_")
                   or nodes[current].result_data["property_key"] == "superfluid_stiffness")
               for current in seen if current in nodes)


def _own_source_gate(witness, label_temporal, task):
    temporal = witness["temporal"]
    report = evaluate_temporal_snapshot({"feature": {"dependency_ids": [], "dependencies_complete": True}},
        cutoff=task["cutoff"], mode=task["temporal_mode"], resolve_provenance=lambda _: temporal)["nodes"]["feature"]
    reasons = set(report["reason_codes"])
    if not report["eligible"]:
        reasons.add("feature_temporal_ineligible")
    own_at = utc_datetime(report["effective_admission_at"])
    label_at = utc_datetime(label_temporal["effective_admission_at"])
    if own_at is None or label_at is None or own_at > label_at:
        reasons.add("feature_not_known_by_label_witness")
    return reasons, report


def _dependency_semantics(index, nodes, witnesses, artifacts):
    """Qualify supporting leaves independently of which columns are requested.

    A child manifest's non-target flag cannot override an actual coordinate or
    property parent's contradictory declaration. Task column protocol pins are
    still applied separately; this does not admit unselected values as columns.
    """
    failures = {}
    for input_id, witness in sorted(witnesses.items()):
        item = data(index, "ml_example_inputs", input_id)
        ref = tuple(witness["target_ref"])
        example = data(index, "ml_examples", item["example_id"])
        label = nodes[("material_claims", example["claim_id"])]
        context = witness["scientific_context"]
        reasons = set(applicability_reasons(index, label, item, witness["applicability"],
            structure_context=context if item["input_kind"] == "structure" else None))
        try:
            if item["input_kind"] == "structure":
                validate_structure_context(context)
                structure = data(index, *ref)
                artifact = data(index, "evidence_artifacts", structure["artifact_id"])
                require(structure["structure_kind"] == "coordinates" and artifact
                        and artifact["kind"] == "structure" and artifact["hash_status"] == "verified",
                        "coordinate structure unavailable")
                value = coordinate_features(artifacts.get(artifact["bytes_sha256"]), artifact["bytes_sha256"],
                    context["source_formula"], coordinate_format=context["coordinate_format"],
                    geometry_scope=context["geometry_scope"])
                require(value["status"] == "computed", "coordinate input semantics unavailable")
                left = _claim_composition(label.result_data["raw_record"])
                right = _claim_composition({"formula_raw": context["source_formula"]})
                require(left["status"] == right["status"] == "computed"
                        and left["values"][:len(ELEMENTS)] == right["values"][:len(ELEMENTS)], "coordinate formula mismatch")
            else:
                node = nodes[ref]
                reasons.update(set(node.reason_codes) - DISCLOSURES - _PROPERTY_SOURCE_REASONS
                    - ({"sample_identity_unresolved"} if witness["applicability"]["mode"] == "normal_state_surrogate" else set()))
                selector = selector_for(context["protocol"])
                value = validate_property_feature(node.result_data, node.event_data, node.state_data,
                    data(index, "research_runs", node.event_data["producer_run_id"]),
                    data(index, "structure_records", node.structure_id), selector, context,
                    source_formula=_claim_composition(label.result_data["raw_record"]).get("formula_raw"))
                reasons.update(value["reason_codes"])
                require(value["status"] == "admitted", "physical input semantics unavailable")
        except (ValueError, TypeError, KeyError):
            reasons.add("dependency_scientific_context_unavailable")
        failures.setdefault(ref, set()).update(reasons)
    return failures


def _view(name, members, feature_names, extras, rows, preprocessing_config):
    selected = []
    for row in rows:
        if row["example_id"] not in members:
            continue
        copied = dict(row)
        copied["raw_features"] = row["raw_features"] + extras.get(row["example_id"], [])
        copied.update(features=None, missingness=None)
        selected.append(copied)
    reasons, fitted = [], None
    counts = Counter(row["split"] for row in selected)
    if any(not counts[split] for split in PARTITIONS):
        reasons.append("nonempty_train_validation_test_required")
    if counts["train"]:
        fitted = fit_transform([row["raw_features"] for row in selected], [row["split"] for row in selected],
                               feature_names, preprocessing_config)
        for row, values, missing in zip(selected, fitted["transformed"], fitted["missingness"]):
            row["features"], row["missingness"] = values, missing
        if not fitted["parameters"]["selected_indices"]:
            reasons.append("no_training_features")
        base_width = len(rows[0]["raw_features"]) if rows else len(feature_names)
        if extras and not any(i >= base_width for i in fitted["parameters"]["selected_indices"]):
            reasons.append("no_added_features_observed_in_train")
    return {"name": name, "feature_names": feature_names, "rows": selected, "preprocessing": fitted,
            "cohort_sha256": digest(sorted(members)), "coverage": {
                "rows": len(selected), "by_split": {split: {
                    "rows": counts[split], "groups": len({row["group_id"] for row in selected if row["split"] == split}),
                    "missing_counts": [sum(row["raw_features"][i] is None for row in selected if row["split"] == split)
                                       for i in range(len(feature_names))],
                    "families": dict(sorted(Counter(row["family"] or "unknown" for row in selected
                                                     if row["split"] == split).items()))}
                    for split in PARTITIONS}},
            "gate": {"status": "no_go" if reasons else "pass", "reason_codes": reasons}}


def build_task_dataset_v2(manifest, *, artifact_bytes, expected_manifest_sha256, companion,
                          expected_companion_sha256, task, expected_task_sha256):
    validate_task_v2(task)
    _pin(task, expected_task_sha256, "v2 task")
    _pin(manifest, expected_manifest_sha256, "capsule")
    verify_manifest(manifest, artifact_bytes=artifact_bytes, expected_manifest_sha256=expected_manifest_sha256)
    verified = verify_feature_companion(companion, base_manifest=manifest,
        expected_base_manifest_sha256=expected_manifest_sha256, expected_companion_sha256=expected_companion_sha256)
    companion_bytes = decode_companion_artifacts(companion)
    require(all(companion_bytes.get(key) == value for key, value in artifact_bytes.items()),
            "companion and independent capsule bytes disagree")
    task, manifest = json.loads(canonical(task)), json.loads(canonical(manifest))
    label_task = task["label_task"]
    index = {(row["table"], row["row_id"]): row for row in manifest["rows"]}
    witnesses = verified
    contexts = resolve_result_contexts(index, artifact_bytes)
    nodes = {ref: context.root for ref, context in contexts.items()}
    edges = {edge.event_evidence_id + ":" + _ref(edge.output_ref): edge
             for context in contexts.values() for edge in context.edges}
    dependencies = {ref: set() for ref in nodes}
    complete = {ref: node.dependency_complete for ref, node in nodes.items()}
    temporal_sources = {ref: node.temporal for ref, node in nodes.items()}
    for (table, identifier) in index:
        if table == "structure_records":
            structure = data(index, table, identifier)
            dependencies[(table, identifier)] = ({("structure_records", structure["parent_structure_id"])}
                                                 if structure["parent_structure_id"] else set())
            complete[(table, identifier)] = True
    for edge in edges.values():
        if edge.link_type == "derives_from" and edge.input_ref:
            dependencies[edge.output_ref].add(edge.input_ref)
    by_target = {}
    for input_id, witness in sorted(witnesses.items()):
        row = data(index, "ml_example_inputs", input_id)
        ref = (("event_properties", row["input_property_id"]) if row["input_kind"] == "property"
               else ("structure_records", row["input_structure_id"]))
        by_target.setdefault(ref, []).append(witness["temporal"])
    for ref, sources in by_target.items():
        # Do not silently select a convenient earliest review when the exact
        # same result was assigned incompatible availability assertions.
        pins = {digest(source) for source in sources}
        temporal_sources[ref] = sources[0] if len(pins) == 1 else None
    lineage = {}
    for ref, node in nodes.items():
        if ref[0] == "event_properties" and node.knowledge_origin == "Computed":
            run = computed_lineage(index, artifact_bytes, ref)
            lineage[ref] = run
            dependencies[ref].update(run["dependencies"])
            if node.structure_id:
                dependencies[ref].add(("structure_records", node.structure_id))
            complete[ref] = complete[ref] and not run["reason_codes"]
    semantic_failures = _dependency_semantics(index, nodes, witnesses, artifact_bytes)
    for ref, failures in semantic_failures.items():
        complete[ref] = complete[ref] and not failures
    temporal = evaluate_temporal_snapshot({_ref(ref): {"dependency_ids": sorted(_ref(dep) for dep in deps),
        "dependencies_complete": complete[ref]} for ref, deps in dependencies.items()}, cutoff=label_task["cutoff"],
        mode=label_task["temporal_mode"], resolve_provenance=lambda ref: temporal_sources.get(tuple(ref.split(":", 1))))
    temporal_rows = temporal["nodes"]
    group_ids, families, compositions, claim_compositions = _groups(
        index, contexts, witnesses, lineage, label_task, artifact_bytes)
    base_names = list(FEATURE_NAMES)
    if label_task["feature_budget"] == "composition_conditions":
        base_names += ["reported_pressure_gpa", "reported_magnetic_field_t"]
    selectors = {item["feature_key"]: item for item in task["physical_features"]}
    examples = sorted((row["data"] for (table, _), row in index.items() if table == "ml_examples"
                       and row["data"]["dataset_snapshot_id"] == manifest["dataset_id"]), key=lambda row: row["id"])
    candidates, rows, audits, physical, structural = [], [], [], {}, {}
    for example in examples:
        ref = ("material_claims", example["claim_id"])
        node, descriptor = nodes[ref], claim_compositions[ref]
        reasons = _label_reasons(node, label_task, index)
        if example["task_type"] != "tc_regression":
            reasons.add("candidate_task_type_mismatch")
        claim = node.result_data
        if example["material_id"] != node.material_id or example["work_id"] != claim["work_id"]:
            reasons.add("candidate_label_identity_mismatch")
        label_time = temporal_rows[_ref(ref)]
        if not label_time["eligible"]:
            reasons.update(["label_temporal_ineligible", *label_time["reason_codes"]])
        if descriptor["status"] != "computed":
            reasons.add("claim_bound_composition_requires_resolution")
        catalog = compositions[node.material_id]
        if catalog["status"] == descriptor["status"] == "computed" and (
                catalog["values"][:len(ELEMENTS)] != descriptor["values"][:len(ELEMENTS)]):
            reasons.add("claim_catalogue_composition_conflict")
        candidate = {"example_id": example["id"], "claim_id": claim["id"],
            "status": "excluded" if reasons else "included", "reason_codes": sorted(reasons),
            "label_row_sha256": node.row_sha256, "group_id": group_ids[("result", _ref(ref))]}
        candidates.append(candidate)
        physical[example["id"]], structural[example["id"]] = {}, []
        physical_contexts = {}
        inputs = sorted((row for (table, _) , row in index.items() if table == "ml_example_inputs"
                         and row["data"]["example_id"] == example["id"]), key=lambda row: row["row_id"])
        for envelope in inputs:
            item, failures, validation = envelope["data"], set(), None
            input_ref = (("event_properties", item["input_property_id"]) if item["input_kind"] == "property"
                         else ("structure_records", item["input_structure_id"]) if item["input_kind"] == "structure"
                         else ("material_claims", item["input_claim_id"]) if item["input_kind"] == "claim" else None)
            witness = witnesses.get(item["id"])
            if input_ref and _target_ancestry(input_ref, dependencies, nodes):
                failures.add("target_dependency")
            if not witness:
                failures.add("independent_feature_source_binding_missing")
            else:
                source_failures, own_temporal = _own_source_gate(witness, label_time, label_task)
                failures.update(source_failures)
                context = witness["scientific_context"]
                failures.update(applicability_reasons(index, node, item, witness["applicability"],
                    structure_context=context if item["input_kind"] == "structure" else None))
            if input_ref and not temporal_rows[_ref(input_ref)]["eligible"]:
                failures.update(["feature_temporal_ineligible", *temporal_rows[_ref(input_ref)]["reason_codes"]])
            if input_ref:
                full_at = utc_datetime(temporal_rows[_ref(input_ref)]["effective_admission_at"])
                label_at = utc_datetime(label_time["effective_admission_at"])
                if full_at is None or label_at is None or full_at > label_at:
                    failures.add("feature_dependency_not_known_by_label_witness")
            if item["input_kind"] == "property":
                leaf = nodes[input_ref]
                failures.update(set(leaf.reason_codes) - DISCLOSURES - _PROPERTY_SOURCE_REASONS
                                - ({"sample_identity_unresolved"} if witness and witness["applicability"]["mode"]
                                   == "normal_state_surrogate" else set()))
                selector = selectors.get(item["feature_key"])
                if not selector:
                    failures.add("unrequested_or_unsupported_property")
                if witness and selector:
                    validation = validate_property_feature(leaf.result_data, leaf.event_data, leaf.state_data,
                        data(index, "research_runs", leaf.event_data["producer_run_id"]),
                        data(index, "structure_records", leaf.structure_id), selector, context,
                        source_formula=descriptor.get("formula_raw"))
                    failures.update(validation["reason_codes"])
                    if validation["status"] != "admitted":
                        failures.add("scientific_semantics_unavailable")
                if not failures:
                    physical[example["id"]].setdefault(item["feature_key"], []).append(validation["value"])
                    physical_contexts[item["feature_key"]] = {"run_id": leaf.event_data["producer_run_id"],
                        "state_id": leaf.state_id, "structure_id": leaf.structure_id,
                        "protocol": {key: value for key, value in context["protocol"].items()
                                     if key not in {"property_key", "semantics_profile", "definition", "normalization"}}}
            elif item["input_kind"] == "structure":
                structure = data(index, *input_ref)
                artifact = data(index, "evidence_artifacts", structure["artifact_id"])
                if not (structure["structure_kind"] == "coordinates" and artifact and artifact["kind"] == "structure"
                        and artifact["hash_status"] == "verified"):
                    failures.add("coordinate_structure_unavailable")
                if witness:
                    try:
                        validate_structure_context(context)
                        validation = coordinate_features(artifact_bytes.get(artifact["bytes_sha256"]) if artifact else None,
                            artifact["bytes_sha256"] if artifact else None, context["source_formula"],
                            coordinate_format=context["coordinate_format"], geometry_scope=context["geometry_scope"])
                        failures.update(validation["reason_codes"])
                        if validation["status"] != "computed":
                            failures.add("coordinate_features_unavailable")
                        claim_formula = _claim_composition({"formula_raw": context["source_formula"]})
                        if not (claim_formula["status"] == descriptor["status"] == "computed" and
                                claim_formula["values"][:len(ELEMENTS)] == descriptor["values"][:len(ELEMENTS)]):
                            failures.add("coordinate_source_formula_conflict")
                    except (ValueError, TypeError):
                        failures.add("coordinate_context_or_bytes_invalid")
                if not task["structure_features"]:
                    failures.add("unrequested_structure_features")
                if not failures:
                    structural[example["id"]].append((item["id"], validation["values"]))
            else:
                failures.add("unsupported_feature_binding")
            audits.append({"example_id": example["id"], "input_id": item["id"],
                "input_ref": list(input_ref) if input_ref else None, "input_row_sha256": envelope["row_sha256"],
                "declared_feature_key": item["feature_key"], "status": "excluded" if failures else "admitted",
                "reason_codes": sorted(failures), "validation": validation,
                "source_temporal": own_temporal if witness else None})
        # SQL already has UNIQUE(example_id, feature_key). Retain an explicit
        # compiler-level guard as well; no UUID-order value selection if a
        # independently supplied capsule violates that scientific assumption.
        ambiguous = {key for key, values in physical[example["id"]].items() if len(values) != 1}
        for audit in audits:
            if audit["example_id"] == example["id"] and audit["declared_feature_key"] in ambiguous:
                audit["status"] = "excluded"
                audit["reason_codes"] = sorted(set(audit["reason_codes"]) | {"ambiguous_physical_feature_choice"})
        physical[example["id"]] = {key: values[0] for key, values in physical[example["id"]].items() if key not in ambiguous}
        epc_keys = {"electron_phonon_lambda", "omega_log"}
        if epc_keys <= selectors.keys() and epc_keys <= physical[example["id"]].keys() and (
                physical_contexts["electron_phonon_lambda"] != physical_contexts["omega_log"]):
            for key in epc_keys:
                del physical[example["id"]][key]
            for audit in audits:
                if audit["example_id"] == example["id"] and audit["declared_feature_key"] in epc_keys:
                    audit["status"] = "excluded"
                    audit["reason_codes"] = sorted(set(audit["reason_codes"]) | {"epc_joint_run_or_spectral_protocol_mismatch"})
        if reasons:
            continue
        features = descriptor["values"] + ([claim["pressure_gpa"], claim["magnetic_field_t"]]
                                          if label_task["feature_budget"] == "composition_conditions" else [])
        rows.append({"example_id": example["id"], "claim_id": claim["id"], "material_id": node.material_id,
            "event_id": node.event_id, "state_id": node.state_id, "sample_id": node.sample_id, "work_id": claim["work_id"],
            "structure_id": node.structure_id, "group_id": candidate["group_id"], "split": None,
            "family": data(index, "materials", node.material_id)["family"],
            "chemical_system": "-".join(element for element, value in zip(ELEMENTS, descriptor["values"]) if value > 0),
            "label": {"value": claim["value_kelvin"], "unit": "K", "tc_definition": claim["tc_definition"],
                      "knowledge_origin": "Observed", "value_relation": "exact"},
            "raw_features": features, "composition_provenance": descriptor["provenance"], "label_temporal": label_time})
    assignments, held = _split(sorted({row["group_id"] for row in rows}), families, label_task)
    for candidate in candidates:
        if candidate["status"] == "included" and candidate["group_id"] in held:
            candidate.update(status="excluded", reason_codes=[held[candidate["group_id"]]])
    rows = [row for row in rows if row["group_id"] in assignments]
    for row in rows:
        row["split"] = assignments[row["group_id"]]
        row["assignment_sha256"] = digest({"task_sha256": expected_task_sha256, "example_id": row["example_id"],
            "label_row_sha256": nodes[("material_claims", row["claim_id"])].row_sha256,
            "group_id": row["group_id"], "split": row["split"]})
    B = {row["example_id"] for row in rows}
    P = {identifier for identifier in B if physical[identifier]}
    # More than one admitted structure is an unresolved choice, not a license
    # to pick the most favorable geometry or average distinct structural states.
    S = {identifier for identifier in B if len(structural[identifier]) == 1}
    PS = P & S
    p_names, s_names = list(selectors), list(task["structure_features"])
    p_values = {identifier: [physical[identifier].get(key) for key in p_names] for identifier in B}
    s_values = {identifier: list(structural[identifier][0][1]) for identifier in S}
    specifications = [("C@B", B, base_names, {})]
    comparisons = []
    if p_names:
        specifications += [("C@P", P, base_names, {}), ("CP@P", P, base_names + p_names, p_values)]
        comparisons.append(["C@P", "CP@P"])
    if s_names:
        specifications += [("C@S", S, base_names, {}), ("CS@S", S, base_names + s_names, s_values)]
        comparisons.append(["C@S", "CS@S"])
    if p_names and s_names:
        specifications += [("C@PS", PS, base_names, {}), ("CP@PS", PS, base_names + p_names, p_values),
            ("CS@PS", PS, base_names + s_names, s_values), ("CPS@PS", PS, base_names + p_names + s_names,
                {identifier: p_values[identifier] + s_values[identifier] for identifier in PS})]
        comparisons.append(["C@PS", "CP@PS", "CS@PS", "CPS@PS"])
    views = {name: _view(name, members, names, extras, rows, label_task["preprocessing"])
             for name, members, names, extras in specifications}
    for names in comparisons:
        require(len({views[name]["cohort_sha256"] for name in names}) == 1, "comparison cohort mismatch")
        require(len({digest([[row["example_id"], row["assignment_sha256"]] for row in views[name]["rows"]])
                     for name in names}) == 1, "comparison assignments mismatch")
    no_go = sorted(name for name, view in views.items() if view["gate"]["status"] != "pass")
    bundle = {"version": VERSION, "task": task, "authority": dict(AUTHORITY), "compiler": _implementation(),
        "input_pins": {"manifest_sha256": expected_manifest_sha256, "companion_sha256": expected_companion_sha256,
                       "task_sha256": expected_task_sha256, "dataset_id": manifest["dataset_id"]},
        "candidates": candidates, "rows": rows, "views": views,
        "cohorts": {key: {"example_ids": sorted(members), "sha256": digest(sorted(members))}
                    for key, members in (("B", B), ("P", P), ("S", S), ("PS", PS))},
        "coverage": {"candidate_count": len(examples), "included_count": len(rows), "excluded_count": len(examples)-len(rows),
            "cohort_counts": {"B": len(B), "P": len(P), "S": len(S), "PS": len(PS)},
            "exclusion_reason_counts": dict(sorted(Counter(reason for item in candidates for reason in item["reason_codes"]).items())),
            "feature_reason_counts": dict(sorted(Counter(reason for audit in audits for reason in audit["reason_codes"]).items())),
            "ambiguous_structure_example_ids": sorted(identifier for identifier in B if len(structural[identifier]) > 1)},
        "dependency_manifest": {"scope": "all_frozen_results_inputs_run_documents_and_companion_relations",
            "nodes": [{"ref": list(ref), "dependency_ids": [list(dep) for dep in sorted(deps)],
                       "dependency_complete": complete[ref],
                       "scientific_context_reason_codes": sorted(semantic_failures.get(ref, set()))}
                      for ref, deps in sorted(dependencies.items())],
            "sql_edges": [{**asdict(edge), "output_ref": list(edge.output_ref),
                           "input_ref": list(edge.input_ref) if edge.input_ref else None}
                          for _, edge in sorted(edges.items())],
            "run_manifests": [{"ref": list(ref), **run, "dependencies": [list(dep) for dep in run["dependencies"]]}
                              for ref, run in sorted(lineage.items())],
            "temporal_report": temporal, "feature_admission": audits},
        "split_report": {"method": label_task["split"], "base_assignments": assignments, "subset_resplitting": False,
            "component_crossings": [], "grouping_links": label_task["grouping_links"],
            "undeclared_trajectories_or_near_duplicates_proven_absent": False},
        "comparisons": comparisons,
        "gate": {"status": "no_go" if no_go else "pass", "reason_codes": ["required_comparison_view_no_go"] if no_go else [],
                 "no_go_views": no_go},
        "data_card": {"artifact_kind": "restricted_internal_technical_dataset_report", "classification_negatives_created": 0,
            "known_positive_selection_bias": True, "physical_cohort_rule": "at_least_one_selected_physical_feature_admitted",
            "structural_cohort_rule": "exactly_one_admitted_coordinate_structure",
            "fair_comparisons": "only same-cohort views; C@B is coverage context, not a fair enhanced-feature comparator",
            "time_scope": "own source witness and complete declared ancestry by cutoff and by label witness; publication equality does not prove pre-measurement availability",
            "retrospective_computation": "deterministic descriptors computed now from witnessed inputs, not historical software availability",
            "physical_scope": "seven computed normal-state DFT/DFPT quantities with exact protocol pins, not all families or experimental proxies",
            "epc_pair_policy": "jointly present lambda/omega require the same declared run/state/structure/shared protocol; incomplete pairs remain missing, no imputed spectral equivalence",
            "scientific_surrogacy": "declared exact contexts or reviewed normal-state bridges; no authenticated physical entailment",
            "unsupported": ["classification", "censor-aware targets", "unpublished operational run receipts", "general CIF symmetry",
                "partial occupancy", "isotope structures", "2D vacuum cells", "learned adapters", "model training", "live source rights"]}}
    canonical(bundle)
    return bundle


def verify_task_dataset_v2(bundle, *, expected_bundle_sha256, **inputs):
    _pin(bundle, expected_bundle_sha256, "compiled v2 bundle")
    recomputed = build_task_dataset_v2(**inputs)
    require(canonical(bundle) == canonical(recomputed), "compiled v2 bundle recomputation mismatch")
    return {"version": VERSION, "bundle_sha256": expected_bundle_sha256, "integrity_verified": True,
            "technical_gate": bundle["gate"]["status"], **AUTHORITY}
