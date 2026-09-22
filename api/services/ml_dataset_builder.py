"""Compile a pinned candidate capsule into a restricted, reproducible ML report.

No DB, network, training, public export, or scientific authorization. Frozen
labels/splits are not authority. Labels come from exact reviewed declarations;
source time comes only from reverified exact source-version witnesses.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict
from importlib.resources import files

from models.ml_task import HASH, require, validate_task
from services.ml_composition import ELEMENTS, FEATURE_NAMES, composition_features
from services.ml_frozen_provenance import resolve_result_contexts
from services.ml_preprocessing import fit_transform
from services.research_release_manifest import canonical, digest, verify_manifest
from services.temporal_provenance import utc_datetime
from services.temporal_snapshots import evaluate_temporal_snapshot

VERSION = "ml-task-dataset/1.0.0"
GROUP_REVIEW_VERSION = "ml-grouping-declaration/1.0.0"
AUTHORITY = {"scientific_acceptance": False, "public_release": False,
             "ml_training_approved": False, "reviewer_authority_authenticated": False,
             "live_source_rights_checked": False, "external_dependency_completeness_proven": False}
DISCLOSURES = frozenset({"scientific_review_authority_not_authenticated", "live_source_currentness_not_checked",
                         "event_scientific_decision_contract_unavailable"})


def _pin(value, expected, label):
    require(type(expected) is str and HASH.fullmatch(expected), f"independent {label} SHA-256 required")
    require(digest(value) == expected, f"{label} pin mismatch")


def _ref(ref):
    return ref[0] + ":" + ref[1]


def _claim_composition(raw):
    if type(raw) is not dict:
        result = composition_features({})
        result["reason_codes"] = ["source_record_not_object"]
        return result
    nested = raw.get("raw_extraction") if type(raw.get("raw_extraction")) is dict else {}
    formulas = [value for value in (raw.get("formula_raw"), nested.get("formula_raw"),
                                   raw.get("formula"), nested.get("formula")) if value is not None]
    selected = composition_features({"formula_raw": formulas[0] if formulas else None, "records": [raw]})
    for formula in formulas:
        alternative = composition_features({"formula_raw": formula, "records": [raw]})
        if alternative["status"] != "computed" or alternative["values"] != selected["values"]:
            selected.update(status="unavailable", values=[None] * len(FEATURE_NAMES),
                            reason_codes=sorted(set(selected["reason_codes"] + ["source_formula_ambiguous_or_unresolved"])))
            break
    return selected


class _Groups:
    def __init__(self):
        self.parent = {}

    def find(self, key):
        self.parent.setdefault(key, key)
        root = key
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[key] != key:
            following = self.parent[key]
            self.parent[key] = root
            key = following
        return root

    def join(self, keys):
        roots = sorted({self.find(key) for key in keys})
        if roots:
            for key in roots[1:]:
                self.parent[key] = roots[0]

    def identifiers(self):
        groups = {}
        for key in sorted(self.parent):
            groups.setdefault(self.find(key), []).append(list(key))
        hashes = {key: digest(value) for key, value in groups.items()}
        return {key: hashes[self.find(key)] for key in self.parent}


def _compiler():
    modules = {
        "models": ["ml_task"],
        "services": ["ml_dataset_builder", "ml_composition", "ml_preprocessing", "ml_frozen_provenance",
                     "research_release_manifest", "research_release_spec", "temporal_provenance", "temporal_snapshots"],
        "services._composition": ["formula_enrichment", "formula_validator"],
    }
    return {"version": VERSION, "required_runtime": "CPython >=3.11; standard library only",
            "learned_feature_adapter": "none", "source_sha256": {
                package + "." + name: hashlib.sha256(files(package).joinpath(name + ".py").read_bytes()).hexdigest()
                for package, names in modules.items() for name in names}}


def _declared_links(task, index, artifacts, groups):
    for link in task["grouping_links"]:
        table, kind = (("research_samples", "sample") if link["kind"] == "sample_trajectory"
                       else ("structure_records", "structure"))
        require(all((table, link[key]) in index for key in ("left_id", "right_id")), "group endpoint outside capsule")
        artifact = index.get(("evidence_artifacts", link["review_artifact_id"]), {}).get("data")
        document = {"version": GROUP_REVIEW_VERSION, "kind": link["kind"], "table": table,
                    "left_id": link["left_id"], "right_id": link["right_id"],
                    "left_row_sha256": index[(table, link["left_id"])]["row_sha256"],
                    "right_row_sha256": index[(table, link["right_id"])]["row_sha256"],
                    "merge_for_leakage_control": True, "reviewer_authority_authenticated": False,
                    "scientific_acceptance": False}
        require(artifact and artifact["kind"] == "review" and artifact["schema_version"] == GROUP_REVIEW_VERSION
                and artifact["hash_status"] == "verified" and artifact["record_sha256"] == digest(document)
                and artifacts.get(artifact["bytes_sha256"]) == canonical(document), "group declaration not exactly bound")
        groups.join([(kind, link["left_id"]), (kind, link["right_id"])])


def _split(group_ids, families, task):
    config = task["split"]
    result, held = {}, {}
    if config["mode"] == "family_holdout":
        validation, test = set(config["validation_families"]), set(config["test_families"])
        for group_id in group_ids:
            labels = families.get(group_id, set())
            destinations = {"test" if label in test else "validation" if label in validation else "train"
                            for label in labels if label}
            if None in labels or not labels or len(destinations) != 1:
                held[group_id] = "family_holdout_component_conflict_or_unknown"
            else:
                result[group_id] = next(iter(destinations))
        return result, held
    ordered = sorted(group_ids, key=lambda key: (digest([config["seed"], key]), key))
    if len(ordered) < 3:
        return {}, {key: "insufficient_independent_groups" for key in ordered}
    # Fixed candidate capture and seed define the rank. Rounded group quotas,
    # not row quotas, keep components intact; all three partitions are nonempty.
    validation = max(1, len(ordered) * config["fractions_percent"][1] // 100)
    test = max(1, len(ordered) * config["fractions_percent"][2] // 100)
    train = len(ordered) - validation - test
    if train < 1:
        return {}, {key: "split_quotas_require_more_independent_groups" for key in ordered}
    for index, group_id in enumerate(ordered):
        result[group_id] = "train" if index < train else "validation" if index < train + validation else "test"
    return result, held


def _label_reasons(node, task, index):
    claim, event, state = node.result_data, node.event_data or {}, node.state_data or {}
    reasons = set(node.reason_codes) - DISCLOSURES
    if not event or not state or not claim.get("interpretation_revision") or not claim.get("result_key"):
        reasons.add("exact_label_revision_or_state_missing")
    if node.knowledge_origin != "Observed" or event.get("event_type") != "measurement":
        reasons.add("label_origin_not_observed_measurement")
    if claim["evidence_role"] != "primary_experimental":
        reasons.add("label_not_primary_experimental")
    if claim["property_type"] != "tc" or claim["result_status"] != "observed":
        reasons.add("label_not_observed_tc_no_negative_inference")
    if claim["value_relation"] != "exact" or claim["value_kelvin"] is None:
        reasons.add("label_censored_missing_or_nonpoint")
    elif not task["label_window_k"]["minimum"] < claim["value_kelvin"] <= task["label_window_k"]["maximum"]:
        reasons.add("label_outside_positive_point_window")
    if claim["tc_definition"] != task["tc_definition"]:
        reasons.add("tc_criterion_mismatch")
    qc = [row["data"] for (table, _), row in index.items()
          if table == "claim_qc" and row["data"]["claim_id"] == claim["id"]]
    decision = index.get(("evidence_artifacts", event.get("decision_artifact_id")), {}).get("data")
    if not (claim["validity_status"] == "accepted" and node.event_review_status == "approved"
            and node.event_validity_status == "accepted" and decision and decision["kind"] == "review"
            and decision["hash_status"] == "verified" and len(qc) == 1
            and qc[0]["review_status"] == "approved" and utc_datetime(qc[0]["reviewed_at"]) is not None):
        reasons.add("declared_label_review_incomplete")
    pressure = task["pressure"]
    if (claim["pressure_state"] != state.get("pressure_status")
            or claim["pressure_gpa"] != state.get("pressure_gpa")):
        reasons.add("claim_state_pressure_conflict")
    allowed = {"explicit_ambient"} if pressure["mode"] == "explicit_ambient" else {"reported", "explicit_ambient"}
    if (claim["pressure_state"] not in allowed or claim["pressure_gpa"] is None
            or not pressure["minimum_gpa"] <= claim["pressure_gpa"] <= pressure["maximum_gpa"]):
        reasons.add("pressure_outside_task_scope_or_unknown")
    field = claim["magnetic_field_t"]
    if field is None and task["magnetic_field"]["unknown"] == "exclude":
        reasons.add("magnetic_field_unknown")
    elif field is not None and field > task["magnetic_field"]["maximum_t"]:
        reasons.add("magnetic_field_outside_task_scope")
    conditions = state.get("conditions", {})
    if type(conditions) is not dict:
        reasons.add("state_conditions_not_object")
        conditions = {}
    if "magnetic_field_t" in conditions:
        state_field = conditions["magnetic_field_t"]
        if state_field is not None and (type(state_field) not in {int, float} or not 0 <= state_field <= 1e9):
            reasons.add("state_magnetic_field_invalid")
        elif state_field != field:
            reasons.add("claim_state_magnetic_field_conflict")
    tmin = claim["minimum_temperature_k"]
    if task["measurement_window"]["require_reported_minimum_temperature"] and tmin is None:
        reasons.add("reported_measurement_minimum_missing")
    if tmin is not None and claim["value_kelvin"] is not None and tmin > claim["value_kelvin"]:
        reasons.add("measurement_window_does_not_include_label")
    if not claim["measurement_method"]:
        reasons.add("measurement_method_missing")
    sample = node.sample_data or {}
    if claim["sample_label"] and sample.get("sample_label") and claim["sample_label"] != sample["sample_label"]:
        # A mismatch is a veto without an alias-resolution contract. Equality
        # is NOT positive specimen identity or a global grouping key.
        reasons.add("claim_sample_label_conflict")
    if state.get("resolution") not in {"resolved", "source_scoped"}:
        reasons.add("label_state_unresolved")
    return reasons


def build_task_dataset(manifest, *, artifact_bytes, expected_manifest_sha256, task, expected_task_sha256):
    """Return a deterministic internal report; a no-go is never publishable."""
    validate_task(task)
    _pin(task, expected_task_sha256, "task")
    _pin(manifest, expected_manifest_sha256, "capsule")
    verification = verify_manifest(manifest, artifact_bytes=artifact_bytes,
                                   expected_manifest_sha256=expected_manifest_sha256)
    # Capture caller-owned mutable dictionaries before invoking subcomponents.
    task, manifest = json.loads(canonical(task)), json.loads(canonical(manifest))
    index = {(row["table"], row["row_id"]): row for row in manifest["rows"]}
    contexts = resolve_result_contexts(index, artifact_bytes)
    nodes = {ref: context.root for ref, context in contexts.items()}
    all_edges = {edge.event_evidence_id + ":" + _ref(edge.output_ref): edge
                 for context in contexts.values() for edge in context.edges}
    dependencies = {ref: set() for ref in nodes}
    for edge in all_edges.values():
        if edge.link_type == "derives_from" and edge.input_ref:
            dependencies[edge.output_ref].add(edge.input_ref)
    temporal_sources = {_ref(ref): node.temporal for ref, node in nodes.items()}
    temporal = evaluate_temporal_snapshot(
        {_ref(ref): {"dependency_ids": sorted(_ref(dep) for dep in dependencies[ref]),
                    "dependencies_complete": node.dependency_complete} for ref, node in nodes.items()},
        cutoff=task["cutoff"], mode=task["temporal_mode"], resolve_provenance=temporal_sources.get)
    temporal_rows = temporal["nodes"]
    groups = _Groups()
    for ref, context in contexts.items():
        groups.join([("result", _ref(ref)), *context.group_keys,
                     *([("event", context.root.event_id)] if context.root.event_id else [])])
    # Include relational bridge nodes even when no result in that branch was
    # selected as a candidate. Never infer sample identity from a printed name.
    for (table, identifier), envelope in index.items():
        data = envelope["data"]
        if table == "research_events":
            groups.join([("event", identifier), ("material", data["material_id"]), ("state", data["state_id"]),
                         *([("structure", data["structure_id"])] if data["structure_id"] else [])])
        elif table == "material_states":
            groups.join([("state", identifier), ("material", data["material_id"]),
                         *([("sample", data["sample_id"])] if data["sample_id"] else [])])
        elif table == "event_evidence" and data["link_type"] != "source":
            # Even unresolved event-only links merge identities conservatively;
            # this does NOT turn a context/support/refute link into causality.
            groups.join([("event", data["event_id"]), ("event", data["input_event_id"])])
        elif table == "research_samples":
            groups.join([("sample", identifier), ("material", data["material_id"]),
                         *([("work", data["work_id"])] if data["work_id"] else [])])
        elif table == "structure_records":
            groups.join([("structure", identifier), ("structure_ancestor", identifier),
                         ("material", data["material_id"]),
                         *([("structure", data["parent_structure_id"])] if data["parent_structure_id"] else [])])
        elif table == "paper_work_map":
            groups.join([("paper", data["paper_id"]), ("work", data["work_id"])])
    compositions, systems = {}, {}
    for (table, identifier), envelope in index.items():
        if table != "materials":
            continue
        data = envelope["data"]
        descriptor = composition_features(data)
        compositions[identifier] = descriptor
        groups.join([("material", identifier), *([("material", data["parent_material_id"])]
                                               if data["parent_material_id"] else [])])
        if descriptor["status"] == "computed":
            fractions = descriptor["values"][:len(ELEMENTS)]
            systems[identifier] = "-".join(element for element, value in zip(ELEMENTS, fractions) if value > 0)
            groups.join([("material", identifier), ("exact_composition", digest(fractions))])
            if task["split"]["mode"] == "chemical_system_extrapolation":
                groups.join([("material", identifier), ("chemical_system", systems[identifier])])
    _declared_links(task, index, artifact_bytes, groups)
    # Source-bound formula strings, not contemporary catalogue descriptors,
    # supply model inputs. Their complete raw_record is included in the exact
    # source-occurrence review digest. Catalogue agreement does not authenticate
    # the sample, but disagreement must not silently become a joint observation.
    claim_compositions = {}
    for ref, node in nodes.items():
        if ref[0] != "material_claims":
            continue
        raw = node.result_data["raw_record"]
        descriptor = _claim_composition(raw)
        claim_compositions[ref] = descriptor
        if descriptor["status"] == "computed":
            fractions = descriptor["values"][:len(ELEMENTS)]
            groups.join([("result", _ref(ref)), ("exact_composition", digest(fractions))])
            if task["split"]["mode"] == "chemical_system_extrapolation":
                chemical_system = "-".join(element for element, value in zip(ELEMENTS, fractions) if value > 0)
                groups.join([("result", _ref(ref)), ("chemical_system", chemical_system)])
    group_ids = groups.identifiers()
    families = {}
    for (table, identifier), envelope in index.items():
        if table == "materials":
            family = envelope["data"]["family"]
            families.setdefault(group_ids[("material", identifier)], set()).add(family or None)
    feature_names = list(FEATURE_NAMES)
    if task["feature_budget"] == "composition_conditions":
        feature_names += ["reported_pressure_gpa", "reported_magnetic_field_t"]
    examples = sorted((row["data"] for (table, _), row in index.items()
                       if table == "ml_examples" and row["data"]["dataset_snapshot_id"] == manifest["dataset_id"]),
                      key=lambda row: row["id"])
    candidates, rows, feature_audits = [], [], []
    for example in examples:
        ref = ("material_claims", example["claim_id"])
        node = nodes[ref]
        reasons = _label_reasons(node, task, index)
        if example["task_type"] != "tc_regression":
            reasons.add("candidate_task_type_mismatch")
        claim = node.result_data
        if example["material_id"] != node.material_id or example["work_id"] != claim["work_id"]:
            reasons.add("candidate_label_identity_mismatch")
        admission = temporal_rows[_ref(ref)]
        if not admission["eligible"]:
            reasons.add("label_temporal_ineligible")
            reasons.update(admission["reason_codes"])
        descriptor = claim_compositions[ref]
        if descriptor["status"] != "computed":
            reasons.add("claim_bound_composition_requires_resolution")
        catalog = compositions[node.material_id]
        if catalog["status"] == "computed" and descriptor["status"] == "computed" and (
                catalog["values"][:len(ELEMENTS)] != descriptor["values"][:len(ELEMENTS)]):
            reasons.add("claim_catalogue_composition_conflict")
        inputs = sorted((row for (table, _), row in index.items()
                         if table == "ml_example_inputs" and row["data"]["example_id"] == example["id"]),
                        key=lambda row: row["row_id"])
        for envelope in inputs:
            item = envelope["data"]
            input_ref = (("material_claims", item["input_claim_id"]) if item["input_kind"] == "claim"
                         else ("event_properties", item["input_property_id"]) if item["input_kind"] == "property" else None)
            failures = {"unsupported_feature_binding"}
            if input_ref:
                reachable, pending = set(), [input_ref]
                while pending:
                    current = pending.pop()
                    if current in reachable:
                        continue
                    reachable.add(current)
                    pending.extend(dependencies[current])
                if ref in reachable or any(nodes[value].ref[0] == "material_claims"
                                           and nodes[value].material_id == node.material_id
                                           and nodes[value].state_id == node.state_id for value in reachable):
                    failures.add("target_dependency")
                if not temporal_rows[_ref(input_ref)]["eligible"]:
                    failures.add("feature_temporal_ineligible")
                if nodes[input_ref].state_id != node.state_id or nodes[input_ref].material_id != node.material_id:
                    failures.add("feature_state_binding_mismatch")
            feature_audits.append({"example_id": example["id"], "input_id": item["id"],
                                   "input_row_sha256": envelope["row_sha256"], "declared_feature_key": item["feature_key"],
                                   "input_ref": list(input_ref) if input_ref else None,
                                   "status": "excluded", "reason_codes": sorted(failures)})
            reasons.update(failures)
        candidate = {"example_id": example["id"], "claim_id": claim["id"],
                     "status": "excluded" if reasons else "included", "reason_codes": sorted(reasons),
                     "label_row_sha256": node.row_sha256, "group_id": group_ids[("result", _ref(ref))]}
        candidates.append(candidate)
        if reasons:
            continue
        raw_features = list(descriptor["values"])
        if task["feature_budget"] == "composition_conditions":
            raw_features += [claim["pressure_gpa"], claim["magnetic_field_t"]]
        rows.append({"example_id": example["id"], "claim_id": claim["id"], "material_id": node.material_id,
                     "event_id": node.event_id, "event_revision": node.event_revision,
                     "interpretation_revision": claim["interpretation_revision"], "state_id": node.state_id,
                     "sample_id": node.sample_id, "work_id": claim["work_id"], "structure_id": node.structure_id,
                     "group_id": candidate["group_id"], "split": None,
                     "family": index[("materials", node.material_id)]["data"]["family"],
                     "chemical_system": "-".join(element for element, value in
                                                  zip(ELEMENTS, descriptor["values"][:len(ELEMENTS)]) if value > 0),
                     "label": {"value": claim["value_kelvin"], "unit": "K", "tc_definition": claim["tc_definition"],
                               "knowledge_origin": "Observed", "value_relation": "exact",
                               "minimum_temperature_k": claim["minimum_temperature_k"],
                               "measurement_method": claim["measurement_method"]},
                     "raw_features": raw_features, "features": None, "missingness": None,
                     "composition_provenance": descriptor["provenance"],
                     "label_temporal": admission})
    assignments, held = _split(sorted({row["group_id"] for row in rows}), families, task)
    for candidate in candidates:
        if candidate["status"] == "included" and candidate["group_id"] in held:
            candidate.update(status="excluded", reason_codes=[held[candidate["group_id"]]])
    rows = [row for row in rows if row["group_id"] in assignments]
    for row in rows:
        row["split"] = assignments[row["group_id"]]
        row["assignment_sha256"] = digest({"task_sha256": expected_task_sha256,
            "example_id": row["example_id"], "label_row_sha256": nodes[("material_claims", row["claim_id"])].row_sha256,
            "group_id": row["group_id"], "split": row["split"]})
    gate_reasons = []
    counts = Counter(row["split"] for row in rows)
    if any(not counts[key] for key in ("train", "validation", "test")):
        gate_reasons.append("nonempty_train_validation_test_required")
    preprocessing = None
    if counts["train"]:
        preprocessing = fit_transform([row["raw_features"] for row in rows], [row["split"] for row in rows],
                                      feature_names, task["preprocessing"])
        for row, values, missing in zip(rows, preprocessing["transformed"], preprocessing["missingness"]):
            row["features"], row["missingness"] = values, missing
        if not preprocessing["parameters"]["selected_indices"]:
            gate_reasons.append("no_training_features")
    crossing = []
    for group_id in {row["group_id"] for row in rows}:
        if len({row["split"] for row in rows if row["group_id"] == group_id}) != 1:
            crossing.append(group_id)
    require(not crossing, "component crossed partitions")
    balance = {}
    for split in ("train", "validation", "test"):
        selected = [row for row in rows if row["split"] == split]
        balance[split] = {"rows": len(selected), "leakage_components": len({row["group_id"] for row in selected}),
                          **{key + "_count": len({row[key] for row in selected if row[key] is not None})
                             for key in ("work_id", "state_id", "sample_id", "material_id")},
                          "families": dict(sorted(Counter(row["family"] or "unknown" for row in selected).items())),
                          "chemical_systems": dict(sorted(Counter(row["chemical_system"] for row in selected).items())),
                          "label_min_k": min((row["label"]["value"] for row in selected), default=None),
                          "label_max_k": max((row["label"]["value"] for row in selected), default=None),
                          "feature_missing_counts": [sum(row["raw_features"][i] is None for row in selected)
                                                     for i in range(len(feature_names))]}
    bundle = {"version": VERSION, "task": task,
              "input_pins": {"manifest_sha256": expected_manifest_sha256, "task_sha256": expected_task_sha256,
                             "dataset_id": manifest["dataset_id"]},
              "compiler": _compiler(), "authority": dict(AUTHORITY),
              "feature_schema": {"names": feature_names, "budget": task["feature_budget"],
                                 "columns": [{"name": name, "dtype": "float64",
                                     "unit": "g/mol" if name == "molar_mass_g_mol" else "GPa" if name == "reported_pressure_gpa"
                                     else "T" if name == "reported_magnetic_field_t" else "1",
                                     "source": "exact_claim_condition" if name.startswith("reported_") else "exact_claim_formula",
                                     "nullable": name == "reported_magnetic_field_t"} for name in feature_names],
                                 "state_temperature_used": False, "target_or_discovery_score_used": False},
              "candidates": candidates, "rows": rows, "preprocessing": preprocessing,
              "coverage": {"candidate_count": len(examples), "included_count": len(rows),
                           "excluded_count": len(examples) - len(rows),
                           "exclusion_reason_counts": dict(sorted(Counter(reason for candidate in candidates
                                 for reason in candidate["reason_codes"]).items())), "by_split": balance},
              "dependency_manifest": {"scope": "all_frozen_results_including_nonselected_bridges",
                  "nodes": [{"ref": list(ref), "row_sha256": node.row_sha256,
                             "dependency_complete": node.dependency_complete, "source_audit": node.source_audit,
                             "reason_codes": list(node.reason_codes)} for ref, node in sorted(nodes.items())],
                  "edges": [{**asdict(edge), "output_ref": list(edge.output_ref),
                             "input_ref": list(edge.input_ref) if edge.input_ref else None}
                            for _, edge in sorted(all_edges.items())],
                  "temporal_report": temporal, "feature_admission": feature_audits},
              "split_report": {"method": task["split"], "component_crossings": crossing,
                               "verified_within_declared_capture": True,
                               "grouping_links": task["grouping_links"],
                               "undeclared_trajectories_or_near_duplicates_proven_absent": False},
              "gate": {"status": "no_go" if gate_reasons else "pass", "reason_codes": gate_reasons},
              "data_card": {"artifact_kind": "restricted_internal_technical_dataset_report",
                  "candidate_scope": "only root dataset ml_examples; stored label_data and assignments ignored",
                  "known_positive_selection_bias": True, "classification_negatives_created": 0,
                  "group_units_are_not_proven_independent_experiments": True,
                  "family_labels": "frozen catalogue declarations, not authenticated taxonomy",
                  "composition_identity": "exact claim raw formula; sample stoichiometry not independently authenticated",
                  "conditional_features": "reported with target; not proof of prospective experimental controllability",
                  "measurement_window": "reported lower bound only; upper acquisition bound unavailable",
                  "historical_features": "deterministic formula descriptors recomputed now; not historical software availability",
                  "unsupported": ["classification", "censored regression", "Computed Tc labels", "structure features",
                                  "physical-property admission", "trained adapters", "live source lifecycle/rights gate"],
                  "capsule_integrity_verified": verification["integrity_verified"]}}
    canonical(bundle)
    return bundle


def verify_task_dataset(bundle, *, manifest, artifact_bytes, expected_manifest_sha256,
                        task, expected_task_sha256, expected_bundle_sha256):
    """Verify an independent pin, then recompute every output from original inputs."""
    _pin(bundle, expected_bundle_sha256, "compiled bundle")
    recomputed = build_task_dataset(manifest, artifact_bytes=artifact_bytes,
        expected_manifest_sha256=expected_manifest_sha256, task=task, expected_task_sha256=expected_task_sha256)
    require(canonical(bundle) == canonical(recomputed), "compiled bundle recomputation mismatch")
    return {"version": VERSION, "bundle_sha256": expected_bundle_sha256, "integrity_verified": True,
            "technical_gate": bundle["gate"]["status"], **AUTHORITY}
