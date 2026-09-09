"""Typed audit of the unchanged frozen leakage grouping rules.

These conservative joins are evidence for partition control, not causal links,
reviewed aliases, source support or independent experiments. The caller builds
the base with the unchanged v4 compiler; this audit does not authenticate it.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from models.ml_task_v4 import validate_task_v4
from services.ml_composition import ELEMENTS, composition_features
from services.ml_dataset_builder import AUTHORITY, _claim_composition, _declared_links, _ref, _split
from services.ml_dataset_builder_v2 import _groups
from services.ml_feature_companion import decode_companion_artifacts, verify_feature_companion
from services.ml_feature_provenance_v2 import computed_lineage
from services.ml_frozen_provenance import resolve_result_contexts
from services.research_release_manifest import canonical, digest, verify_manifest

VERSION = "ml-identity-audit/1.0.0"
POLICY_VERSION = "captured-typed-identity/1.0.0"
LIMITS = {"nodes": 20000, "joins": 50000, "references": 200000,
          "serialized_bytes": 16 * 1024 * 1024, "json_nodes": 200000, "json_depth": 48}
AUDIT_FIELDS = frozenset({"version", "policy_version", "input_pins", "completeness", "limits",
    "nodes", "components", "join_witnesses", "examples", "counts", "relationship_components",
    "checks", "gate", "authority", "independent_support_count"})
CHECK_CODES = {
    "component_crossings": "component_partition_crossing",
    "identity_crossings": "identity_partition_crossing",
    "cohort_violations": "cohort_membership_violation",
    "view_violations": "view_assignment_violation",
    "comparison_violations": "comparison_membership_violation",
    "assignment_violations": "assignment_policy_violation",
}
PARTITIONS = ("train", "validation", "test")
COHORTS = ("B", "P", "S", "PS")
DIRECT_KINDS = ("material", "claim", "event", "state", "sample", "structure", "run",
                "paper", "work", "source_revision", "capture", "occurrence", "coordinate_bytes")
IDENTITY_KINDS = tuple(sorted(set(DIRECT_KINDS) | {"property", "artifact", "feature_binding"}))
_TABLES = {"material": "materials", "material_ancestor": "materials", "state": "material_states",
    "sample": "research_samples", "structure": "structure_records", "structure_ancestor": "structure_records",
    "event": "research_events", "run": "research_runs", "run_artifact": "evidence_artifacts",
    "artifact": "evidence_artifacts", "paper": "papers", "work": "works",
    "source_revision": "source_revisions", "capture": "source_captures", "occurrence": "claim_source_occurrences",
    "feature_binding": "ml_feature_source_bindings"}
_RULES = frozenset({"conservative_result_context", "event_foreign_keys", "state_foreign_keys",
    "sample_foreign_keys", "structure_identity_and_ancestry", "non_source_event_relation",
    "captured_paper_work_mapping", "run_parent_and_manifests", "example_input_binding",
    "material_parent_series", "exact_composition", "declared_chemical_system_split",
    "verified_feature_source_binding", "declared_run_dependencies", "sample_trajectory", "structure_near_duplicate"})


class MlIdentityAuditError(ValueError):
    """Static malformed/budget failure; source data is never echoed."""


def require(condition, code="ml_identity_audit_invalid"):
    if not condition:
        raise MlIdentityAuditError(code)


def canonical_audit(value):
    # Preflight strings before allocating the serialization; capsule canonical
    # independently validates finite scalars, dictionary keys and UTF-8.
    pending, nodes, size = [(value, 0)], 0, 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        require(depth <= LIMITS["json_depth"] and nodes + len(pending) <= LIMITS["json_nodes"], "ml_identity_json_limit")
        if type(item) is str:
            size += len(item.encode("utf-8"))
            require(size <= LIMITS["serialized_bytes"], "ml_identity_byte_limit")
        elif type(item) is dict:
            require(nodes + len(pending) + len(item) * 2 <= LIMITS["json_nodes"], "ml_identity_json_limit")
            pending.extend((part, depth + 1) for pair in item.items() for part in pair)
        elif type(item) is list:
            require(nodes + len(pending) + len(item) <= LIMITS["json_nodes"], "ml_identity_json_limit")
            pending.extend((part, depth + 1) for part in item)
    raw = canonical(value)
    require(len(raw) <= LIMITS["serialized_bytes"], "ml_identity_byte_limit")
    return raw


def digest_audit(value):
    return hashlib.sha256(canonical_audit(value)).hexdigest()


def _member(key):
    return {"kind": key[0], "id": key[1]}


class _Budget:
    def __init__(self):
        self.references = 0

    def add(self, count):
        require(type(count) is int and count >= 0 and self.references + count <= LIMITS["references"], "ml_identity_reference_limit")
        self.references += count


class _Graph:
    """Local union-find; never patches, instruments or subclasses old _groups."""
    def __init__(self, index, source_index, artifacts, budget):
        self.index, self.source_index, self.artifacts, self.budget = index, source_index, artifacts, budget
        self.parent, self.witnesses = {}, {}

    def row_pins(self, ref):
        pins = []
        for source, index in (("base", self.index), ("companion", self.source_index)):
            if ref in index:
                pins.append({"source": source, "table": ref[0], "row_id": ref[1], "row_sha256": index[ref]["row_sha256"]})
        require(pins, "ml_identity_unknown_reference")
        return pins

    def key_ref(self, key):
        require(type(key) is tuple and len(key) == 2 and type(key[0]) is str
                and type(key[1]) is str and 0 < len(key[1]) <= 300, "ml_identity_typed_member_required")
        if key[0] == "result":
            parts = key[1].split(":", 1)
            require(len(parts) == 2 and parts[0] in {"material_claims", "event_properties", "structure_records"})
            return tuple(parts)
        if key[0] in _TABLES:
            return _TABLES[key[0]], key[1]
        require(key[0] in {"coordinate_bytes", "exact_composition", "chemical_system"}, "ml_identity_unknown_member_kind")
        if key[0] in {"coordinate_bytes", "exact_composition"}:
            require(len(key[1]) == 64 and all(char in "0123456789abcdef" for char in key[1]), "ml_identity_hash_required")
        if key[0] == "coordinate_bytes":
            require(key[1] in self.artifacts and hashlib.sha256(self.artifacts[key[1]]).hexdigest() == key[1], "ml_identity_coordinate_bytes_missing")
        return None

    def identity(self, key):
        ref = self.key_ref(key)
        if ref:
            kind = {"material_claims": "claim", "event_properties": "property", "structure_records": "structure",
                    "evidence_artifacts": "artifact", "materials": "material"}.get(ref[0], key[0])
            return kind, ref[1]
        return key if key[0] == "coordinate_bytes" else None

    def find(self, key):
        if key not in self.parent:
            ref = self.key_ref(key)
            if ref:
                self.row_pins(ref)
            require(len(self.parent) < LIMITS["nodes"], "ml_identity_node_limit")
            self.parent[key] = key
        root = key
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[key] != key:
            following = self.parent[key]
            self.parent[key] = root
            key = following
        return root

    def join(self, keys, *, rule, refs=(), artifact_hashes=()):
        require(rule in _RULES, "ml_identity_join_rule_invalid")
        keys = sorted(set(keys))
        self.budget.add(len(keys))
        roots = sorted({self.find(key) for key in keys})
        if not roots:
            return
        for key in roots[1:]:
            self.parent[key] = roots[0]
        row_refs = set(refs) | {ref for key in keys if (ref := self.key_ref(key))}
        pins, hashes = {}, set(artifact_hashes)
        for ref in sorted(row_refs):
            for pin in self.row_pins(ref):
                pins[(pin["source"], pin["table"], pin["row_id"])] = pin
        # Explicit retained artifact references supplement row hashes, without
        # turning the conservative join into a reviewed causal assertion.
        for pin in list(pins.values()):
            index = self.index if pin["source"] == "base" else self.source_index
            row = index[(pin["table"], pin["row_id"])]["data"]
            if pin["table"] in {"evidence_artifacts", "source_captures"} and row["bytes_sha256"] in self.artifacts:
                hashes.add(row["bytes_sha256"])
            for field in ("review_artifact_id", "decision_artifact_id", "artifact_id", "input_manifest_id", "output_manifest_id"):
                if row.get(field):
                    for extra in self.row_pins(("evidence_artifacts", row[field])):
                        pins[(extra["source"], extra["table"], extra["row_id"])] = extra
                        source = self.index if extra["source"] == "base" else self.source_index
                        sha = source[("evidence_artifacts", row[field])]["data"]["bytes_sha256"]
                        if sha in self.artifacts:
                            hashes.add(sha)
        require(all(sha in self.artifacts and hashlib.sha256(self.artifacts[sha]).hexdigest() == sha for sha in hashes), "ml_identity_join_artifact_mismatch")
        self.budget.add(len(pins) + len(hashes))
        body = {"rule": rule, "endpoints": [_member(key) for key in keys],
                "row_pins": [pins[key] for key in sorted(pins)], "artifact_sha256": sorted(hashes)}
        sha = digest(body)
        require(len(self.witnesses) < LIMITS["joins"] or sha in self.witnesses, "ml_identity_join_limit")
        self.witnesses[sha] = {"witness_sha256": sha, **body}

    def identifiers(self):
        members = defaultdict(list)
        for key in sorted(self.parent):
            members[self.find(key)].append(list(key))
        hashes = {root: digest(values) for root, values in members.items()}
        return {key: hashes[self.find(key)] for key in self.parent}


def _reconstruct(index, source_index, witnesses, contexts, lineage, task, artifacts, budget):
    graph = _Graph(index, source_index, artifacts, budget)
    for ref, context in contexts.items():
        graph.join([("result", _ref(ref)), *context.group_keys,
                    *([("event", context.root.event_id)] if context.root.event_id else [])],
            rule="conservative_result_context", refs=[node.ref for node in context.nodes]
            + [("event_evidence", edge.event_evidence_id) for edge in context.edges])
    for (table, identifier), envelope in sorted(index.items()):
        row, keys, rule = envelope["data"], None, None
        if table == "research_events":
            keys = [("event", identifier), ("material", row["material_id"]), ("state", row["state_id"]),
                *([("structure", row["structure_id"])] if row["structure_id"] else []),
                *([("run", row["producer_run_id"])] if row["producer_run_id"] else [])]
            rule = "event_foreign_keys"
        elif table == "material_states":
            keys = [("state", identifier), ("material", row["material_id"]), *([("sample", row["sample_id"])] if row["sample_id"] else [])]
            rule = "state_foreign_keys"
        elif table == "research_samples":
            keys = [("sample", identifier), ("material", row["material_id"]), *([("work", row["work_id"])] if row["work_id"] else [])]
            rule = "sample_foreign_keys"
        elif table == "structure_records":
            artifact = index.get(("evidence_artifacts", row["artifact_id"]), {}).get("data")
            keys = [("structure", identifier), ("structure_ancestor", identifier), ("result", _ref((table, identifier))),
                ("material", row["material_id"]), *([("structure", row["parent_structure_id"])] if row["parent_structure_id"] else []),
                *([("coordinate_bytes", artifact["bytes_sha256"])] if row["structure_kind"] == "coordinates"
                  and artifact and artifact["hash_status"] == "verified" else [])]
            rule = "structure_identity_and_ancestry"
        elif table == "event_evidence" and row["link_type"] != "source":
            keys, rule = [("event", row["event_id"]), ("event", row["input_event_id"])], "non_source_event_relation"
        elif table == "paper_work_map":
            keys, rule = [("paper", row["paper_id"]), ("work", row["work_id"])], "captured_paper_work_mapping"
        elif table == "research_runs":
            keys = [("run", identifier), *([("run", row["parent_run_id"])] if row["parent_run_id"] else []),
                    *[("run_artifact", row[key]) for key in ("input_manifest_id", "output_manifest_id") if row[key]]]
            rule = "run_parent_and_manifests"
        elif table == "ml_example_inputs":
            example = index[("ml_examples", row["example_id"])]["data"]
            keys = [("result", _ref(("material_claims", example["claim_id"])))]
            for field, kind in (("input_claim_id", "claim"), ("input_property_id", "property"),
                                ("input_structure_id", "structure"), ("input_artifact_id", "artifact"), ("input_event_id", "event")):
                if row[field]:
                    keys.append(("result", _ref(("material_claims" if kind == "claim" else "event_properties", row[field])))
                                if kind in {"claim", "property"} else (kind, row[field]))
            rule = "example_input_binding"
        if keys is not None:
            graph.join(keys, rule=rule, refs=[(table, identifier)])
    for (table, identifier), envelope in sorted(index.items()):
        if table == "materials":
            row = envelope["data"]
            descriptor, key = composition_features(row), ("material", identifier)
            graph.join([key, *([("material", row["parent_material_id"])] if row["parent_material_id"] else [])],
                       rule="material_parent_series", refs=[(table, identifier)])
        elif table == "material_claims":
            descriptor, key = _claim_composition(envelope["data"]["raw_record"]), ("result", _ref((table, identifier)))
        else:
            continue
        if descriptor["status"] == "computed":
            fractions = descriptor["values"][:len(ELEMENTS)]
            graph.join([key, ("exact_composition", digest(fractions))], rule="exact_composition", refs=[(table, identifier)])
            if task["split"]["mode"] == "chemical_system_extrapolation":
                system = "-".join(element for element, fraction in zip(ELEMENTS, fractions) if fraction > 0)
                graph.join([key, ("chemical_system", system)], rule="declared_chemical_system_split", refs=[(table, identifier)])
    for input_id, witness in sorted(witnesses.items()):
        row = index[("ml_example_inputs", input_id)]["data"]
        example = index[("ml_examples", row["example_id"])]["data"]
        # The frozen verifier derives bibliography joins using exact source
        # mappings. Retain those mapping rows as witnesses, not just endpoints;
        # their presence still does not authenticate reviewer authority.
        mapping_refs = [("paper_work_map", identifier) for kind, identifier in witness["group_keys"]
                        if kind == "paper" and ("paper_work_map", identifier) in source_index]
        graph.join([("result", _ref(("material_claims", example["claim_id"]))), *map(tuple, witness["group_keys"])],
            rule="verified_feature_source_binding", refs=[("ml_example_inputs", input_id)]
            + [("ml_feature_source_bindings", key) for key in witness["binding_ids"]] + mapping_refs)
    for ref, run in lineage.items():
        refs = [ref] + list(run["dependencies"])
        if run["run_id"]:
            refs.append(("research_runs", run["run_id"]))
        graph.join([("result", _ref(ref)), *[("result", _ref(dep)) for dep in run["dependencies"]]],
                   rule="declared_run_dependencies", refs=refs)
    # The unchanged validator checks declaration bytes before this reconstruction
    # records the specific edge; no global instrumentation of its grouping object.
    class _DeclarationValidator:
        def join(self, keys):
            require(len(keys) == 2)
    _declared_links(task, index, artifacts, _DeclarationValidator())
    for link in task["grouping_links"]:
        table, kind = ("research_samples", "sample") if link["kind"] == "sample_trajectory" else ("structure_records", "structure")
        graph.join([(kind, link["left_id"]), (kind, link["right_id"])], rule=link["kind"],
                   refs=[(table, link["left_id"]), (table, link["right_id"]), ("evidence_artifacts", link["review_artifact_id"])])
    return graph


def _identity_counts(identities):
    return {kind: sum(key[0] == kind for key in identities) for kind in IDENTITY_KINDS}


def _direct(index, claim_id):
    claim = index[("material_claims", claim_id)]["data"]
    keys = {("claim", claim_id), ("material", claim["material_id"])}
    for field, kind in (("paper_id", "paper"), ("work_id", "work"), ("event_id", "event")):
        if claim[field]:
            keys.add((kind, claim[field]))
    if claim["event_id"]:
        event = index[("research_events", claim["event_id"])]["data"]
        keys.add(("state", event["state_id"]))
        state = index[("material_states", event["state_id"])]["data"]
        if state["sample_id"]:
            keys.add(("sample", state["sample_id"]))
        for field, kind in (("structure_id", "structure"), ("producer_run_id", "run")):
            if event[field]:
                keys.add((kind, event[field]))
        if event["structure_id"]:
            structure = index[("structure_records", event["structure_id"])]["data"]
            artifact = index.get(("evidence_artifacts", structure["artifact_id"]), {}).get("data")
            if structure["structure_kind"] == "coordinates" and artifact and artifact["hash_status"] == "verified":
                keys.add(("coordinate_bytes", artifact["bytes_sha256"]))
    for (table, identifier), envelope in index.items():
        row = envelope["data"]
        if table == "claim_source_occurrences" and row["claim_id"] == claim_id:
            revision = index[("source_revisions", row["source_revision_id"])]["data"]
            keys.update({("occurrence", identifier), ("source_revision", row["source_revision_id"]),
                         ("capture", row["capture_id"]), ("work", row["work_id"]), ("paper", revision["paper_id"])})
    return keys


def _relationship_components(index, task, budget):
    definitions = {
        "material_series": ({key for table, key in index if table == "materials"},
            [(identifier, row["data"]["parent_material_id"]) for (table, identifier), row in index.items()
             if table == "materials" and row["data"]["parent_material_id"]]),
        "sample_trajectory": ({key for table, key in index if table == "research_samples"},
            [(link["left_id"], link["right_id"]) for link in task["grouping_links"] if link["kind"] == "sample_trajectory"]),
        "structure_near_duplicate": ({key for table, key in index if table == "structure_records"},
            [(link["left_id"], link["right_id"]) for link in task["grouping_links"] if link["kind"] == "structure_near_duplicate"]),
    }
    result = {}
    for kind, (all_ids, edges) in definitions.items():
        adjacency = defaultdict(set)
        for left, right in edges:
            require(left in all_ids and right in all_ids, "ml_identity_relationship_endpoint_missing")
            adjacency[left].add(right)
            adjacency[right].add(left)
        seen, components = set(), []
        for identifier in sorted(adjacency):
            if identifier in seen:
                continue
            members, pending = set(), [identifier]
            while pending:
                key = pending.pop()
                if key in members:
                    continue
                members.add(key)
                pending.extend(adjacency[key] - members)
            seen.update(members)
            budget.add(len(members))
            components.append({"component_sha256": digest([kind, sorted(members)]), "members": sorted(members),
                "edge_count": sum(left in members and right in members for left, right in edges)})
        unlinked = sorted(all_ids - seen)
        budget.add(len(unlinked))
        result[kind] = {"components": sorted(components, key=lambda row: row["component_sha256"]),
                        "unlinked_ids": unlinked, "declared_edge_count": len(edges)}
    return result


def _example_rows(value, known):
    require(type(value) is list and len(value) <= 100, "ml_identity_example_limit")
    found = {}
    for row in value:
        require(type(row) is dict and type(row.get("example_id")) is str and row["example_id"] in known)
        require(row["example_id"] not in found, "ml_identity_duplicate_example")
        found[row["example_id"]] = row
    return found


def _assignment_audit(base, index, ids, families, identities, budget):
    task = base["task"]["label_task"]
    roots = {identifier: row["data"] for (table, identifier), row in index.items()
             if table == "ml_examples" and row["data"]["dataset_snapshot_id"] == base["input_pins"]["dataset_id"]}
    candidates = _example_rows(base["candidates"], roots)
    require(candidates.keys() == roots.keys(), "ml_identity_candidate_inventory_missing")
    rows = _example_rows(base["rows"], roots)
    checks = {key: [] for key in CHECK_CODES}
    components_to_rows, identity_to_rows = defaultdict(list), defaultdict(list)
    direct, examples = {}, []
    require(type(base["cohorts"]) is dict and set(base["cohorts"]) == set(COHORTS))
    cohorts = {}
    for name in COHORTS:
        cohort = base["cohorts"][name]
        require(type(cohort) is dict and set(cohort) == {"example_ids", "sha256"})
        members = cohort["example_ids"]
        require(type(members) is list and all(type(key) is str and key in roots for key in members)
                and members == sorted(set(members)), "ml_identity_cohort_inventory_invalid")
        require(cohort["sha256"] == digest(members), "ml_identity_cohort_hash_mismatch")
        cohorts[name] = set(members)
    for name in COHORTS:
        difference = cohorts[name] ^ set(rows) if name == "B" else cohorts[name] - cohorts["B"]
        if name == "PS":
            difference |= cohorts[name] ^ (cohorts["P"] & cohorts["S"])
        if difference:
            checks["cohort_violations"].append({"reason_code": "cohort_subset_or_row_mismatch", "cohort": name, "example_ids": sorted(difference)})
    for identifier, example in sorted(roots.items()):
        claim_id = example["claim_id"]
        component = ids[("result", _ref(("material_claims", claim_id)))]
        candidate, row = candidates[identifier], rows.get(identifier)
        require(candidate["claim_id"] == claim_id and candidate["group_id"] == component, "ml_identity_candidate_group_mismatch")
        require(candidate["status"] in {"included", "excluded"})
        if row:
            require(row["claim_id"] == claim_id and row["group_id"] == component, "ml_identity_selected_group_mismatch")
            require(row["split"] in PARTITIONS, "ml_identity_partition_invalid")
            components_to_rows[component].append((identifier, row["split"]))
            for identity in identities[component]:
                identity_to_rows[identity].append((identifier, row["split"]))
            budget.add(len(identities[component]))
        if (row is not None) != (candidate["status"] == "included"):
            checks["cohort_violations"].append({"reason_code": "candidate_status_row_mismatch", "cohort": "B", "example_ids": [identifier]})
        direct[identifier] = _direct(index, claim_id)
        require(direct[identifier] <= identities[component], "ml_identity_direct_identity_outside_component")
        budget.add(len(direct[identifier]))
        examples.append({"example_id": identifier, "claim_id": claim_id, "component_sha256": component,
            "candidate_status": candidate["status"], "base_partition": row["split"] if row else None,
            "cohorts": [name for name in COHORTS if identifier in cohorts[name]],
            "direct_identities": [_member(key) for key in sorted(direct[identifier])],
            "missing_direct_identity_kinds": [kind for kind in DIRECT_KINDS if not any(key[0] == kind for key in direct[identifier])]})
    for component, members in sorted(components_to_rows.items()):
        partitions = sorted({part for _, part in members})
        if len(partitions) > 1:
            checks["component_crossings"].append({"component_sha256": component, "partitions": partitions,
                                                 "example_ids": sorted(key for key, _ in members)})
    for identity, members in sorted(identity_to_rows.items()):
        partitions = sorted({part for _, part in members})
        if len(partitions) > 1:
            checks["identity_crossings"].append({**_member(identity), "partitions": partitions,
                                                "example_ids": sorted({key for key, _ in members})})
    assignments, held = _split(sorted(components_to_rows), families, task)
    require(type(base["split_report"]["base_assignments"]) is dict)
    for component in sorted(set(components_to_rows) | set(base["split_report"]["base_assignments"])):
        require(component in identities, "ml_identity_unknown_component")
        actual = sorted({part for _, part in components_to_rows[component]})
        declared = base["split_report"]["base_assignments"].get(component)
        expected = assignments.get(component)
        if actual != ([expected] if expected else []) or declared != expected:
            checks["assignment_violations"].append({"component_sha256": component, "expected_partition": expected,
                "actual_partitions": actual, "reason_code": held.get(component, "declared_split_assignment_mismatch")})
    expected_views = {"C@B": "B"}
    if base["task"]["physical_features"]:
        expected_views.update({"C@P": "P", "CP@P": "P"})
    if base["task"]["structure_features"]:
        expected_views.update({"C@S": "S", "CS@S": "S"})
    if base["task"]["physical_features"] and base["task"]["structure_features"]:
        expected_views.update({"C@PS": "PS", "CP@PS": "PS", "CS@PS": "PS", "CPS@PS": "PS"})
    require(type(base["views"]) is dict and set(base["views"]) == set(expected_views), "ml_identity_view_inventory_invalid")
    view_members = {}
    for name, cohort in expected_views.items():
        view = base["views"][name]
        selected = _example_rows(view["rows"], roots)
        view_members[name] = selected
        difference = set(selected) ^ cohorts[cohort]
        for identifier, row in selected.items():
            if identifier not in rows or any(row.get(field) != rows[identifier].get(field) for field in ("claim_id", "group_id", "split", "assignment_sha256")):
                difference.add(identifier)
        if view["cohort_sha256"] != digest(sorted(cohorts[cohort])):
            difference.update(cohorts[cohort])
            if not difference:
                checks["view_violations"].append({"reason_code": "empty_view_cohort_hash_mismatch", "view": name, "example_ids": []})
        if difference:
            checks["view_violations"].append({"reason_code": "view_membership_or_assignment_mismatch", "view": name, "example_ids": sorted(difference)})
    expected_comparisons = []
    for cohort in ("P", "S", "PS"):
        names = [name for name, target in expected_views.items() if target == cohort]
        if names:
            expected_comparisons.append(names)
    require(type(base["comparisons"]) is list)
    if base["comparisons"] != expected_comparisons:
        checks["comparison_violations"].append({"reason_code": "declared_comparison_inventory_mismatch", "views": [], "example_ids": []})
    for names in expected_comparisons:
        projections = [{key: [row["group_id"], row["split"], row["assignment_sha256"]] for key, row in view_members[name].items()} for name in names]
        if any(projection != projections[0] for projection in projections[1:]):
            checks["comparison_violations"].append({"reason_code": "same_cohort_comparison_assignment_mismatch", "views": names,
                "example_ids": sorted(set().union(*(projection.keys() for projection in projections)))})
    counts = []
    for cohort in COHORTS:
        for partition in ("all", *PARTITIONS):
            selected = sorted(key for key in cohorts[cohort] if key in rows and (partition == "all" or rows[key]["split"] == partition))
            components = {rows[key]["group_id"] for key in selected}
            selected_direct = set().union(*(direct[key] for key in selected)) if selected else set()
            full = set().union(*(identities[key] for key in components)) if components else set()
            budget.add(len(selected) + len(selected_direct) + len(full))
            counts.append({"cohort": cohort, "partition": partition, "rows": len(selected), "components": len(components),
                "direct_label": {"identity_counts": _identity_counts(selected_direct), "missing_identity_counts": {
                    kind: sum(not any(key[0] == kind for key in direct[identifier]) for identifier in selected) for kind in DIRECT_KINDS}},
                "full_components": {"identity_counts": _identity_counts(full)}})
    return examples, counts, checks


def build_identity_audit(base_dataset, *, manifest, artifact_bytes, companion,
                         expected_manifest_sha256, expected_companion_sha256):
    """Reconstruct grouping joins and compute crossings; no scientific approval."""
    try:
        canonical_audit(base_dataset)
        require(type(base_dataset) is dict and base_dataset.get("version") == "ml-task-dataset/4.0.0")
        task = validate_task_v4(base_dataset["task"])
        require(base_dataset["input_pins"]["manifest_sha256"] == expected_manifest_sha256
                and base_dataset["input_pins"]["companion_sha256"] == expected_companion_sha256
                and base_dataset["input_pins"]["dataset_id"] == manifest["dataset_id"]
                and base_dataset["input_pins"]["task_sha256"] == digest(task), "ml_identity_input_pin_mismatch")
        verify_manifest(manifest, artifact_bytes=artifact_bytes, expected_manifest_sha256=expected_manifest_sha256)
        witnesses = verify_feature_companion(companion, base_manifest=manifest,
            expected_base_manifest_sha256=expected_manifest_sha256, expected_companion_sha256=expected_companion_sha256)
        artifacts = decode_companion_artifacts(companion)
        require(all(artifacts.get(key) == value for key, value in artifact_bytes.items()), "ml_identity_artifact_pin_mismatch")
        index = {(row["table"], row["row_id"]): row for row in manifest["rows"]}
        source_index = {(row["table"], row["row_id"]): row for row in companion["source_rows"]}
        for binding in companion["bindings"]:
            source_index[("ml_feature_source_bindings", binding["id"])] = {"data": binding, "row_sha256": digest(binding)}
        contexts = resolve_result_contexts(index, artifact_bytes)
        lineage = {ref: computed_lineage(index, artifact_bytes, ref) for ref, context in contexts.items()
                   if ref[0] == "event_properties" and context.root.knowledge_origin == "Computed"}
        task_policy = task["label_task"]
        expected_ids, families, _, _ = _groups(index, contexts, witnesses, lineage, task_policy, artifact_bytes)
        budget = _Budget()
        graph = _reconstruct(index, source_index, witnesses, contexts, lineage, task_policy, artifacts, budget)
        ids = graph.identifiers()
        require(ids == expected_ids, "ml_identity_group_reconstruction_mismatch")
        members, identities = defaultdict(list), defaultdict(set)
        nodes = []
        for key, component in sorted(ids.items()):
            identity, ref = graph.identity(key), graph.key_ref(key)
            nodes.append({**_member(key), "component_sha256": component,
                "identity": _member(identity) if identity else None, "row_pins": graph.row_pins(ref) if ref else []})
            members[component].append(key)
            if identity:
                identities[component].add(identity)
            else:
                identities[component]  # Retain even a component of synthetic grouping keys.
        budget.add(len(nodes) + sum(map(len, identities.values())))
        components = [{"component_sha256": component, "members": [_member(key) for key in keys],
            "identity_counts": _identity_counts(identities[component]),
            "families": sorted(families.get(component, set()), key=lambda value: (value is not None, value or ""))}
            for component, keys in sorted(members.items())]
        for witness in graph.witnesses.values():
            require(len({ids[(item["kind"], item["id"])] for item in witness["endpoints"]}) == 1, "ml_identity_join_crosses_component")
        examples, counts, checks = _assignment_audit(base_dataset, index, ids, families, identities, budget)
        reasons = sorted(code for key, code in CHECK_CODES.items() if checks[key])
        result = {"version": VERSION, "policy_version": POLICY_VERSION,
            "input_pins": {"base_dataset_sha256": digest(base_dataset), "manifest_sha256": expected_manifest_sha256,
                "companion_sha256": expected_companion_sha256, "task_sha256": digest(task)},
            "completeness": {"scope": "complete_captured_grouping_declarations", "uncaptured_relationships_known": False,
                             "replication_registry_available": False},
            "limits": dict(LIMITS), "nodes": nodes, "components": components,
            "join_witnesses": [graph.witnesses[key] for key in sorted(graph.witnesses)], "examples": examples, "counts": counts,
            "relationship_components": _relationship_components(index, task_policy, budget), "checks": checks,
            "gate": {"status": "no_go" if reasons else "pass", "reason_codes": reasons},
            "authority": dict(AUTHORITY), "independent_support_count": None}
        return json.loads(canonical_audit(result))
    except MlIdentityAuditError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, UnicodeError, OverflowError):
        raise MlIdentityAuditError("ml_identity_audit_invalid") from None
