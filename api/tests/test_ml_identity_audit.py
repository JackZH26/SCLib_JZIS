"""Pure identity/adversarial units; native SQL tests prove complete build paths."""
from copy import deepcopy

import pytest

from models.ml_task import default_task
from services import ml_identity_audit as audit
from services.ml_dataset_builder import _Groups, _split
from services.ml_dataset_builder_v2 import _groups
from services.ml_frozen_provenance import resolve_result_contexts
from services.research_release_manifest import digest
from tests.test_ml_label_companion_contract import fixture, row, uid


def graph_fixture():
    """Typed synthetic row graph, deliberately not a scientifically valid base."""
    manifest, _, _ = fixture()
    index = {(item["table"], item["row_id"]): deepcopy(item) for item in manifest["rows"]}
    first = next(item["data"] for key, item in index.items() if key[0] == "materials")
    dataset_id = manifest["dataset_id"]
    for offset, formula in ((1, "Nb"), (2, "Ta")):
        material_id, claim_id, example_id = "synthetic:" + formula, uid(10 + offset), uid(20 + offset)
        material = row("materials", material_id, formula=formula, formula_normalized=formula,
                       status="active", records=[], family="family_" + formula)
        claim = row("material_claims", claim_id, material_id=material_id, source_snapshot_id=uid(3),
                    validity_status="accepted", raw_record={"formula": formula})
        example = row("ml_examples", example_id, claim_id=claim_id, dataset_snapshot_id=dataset_id, material_id=material_id)
        for table, value in (("materials", material), ("material_claims", claim), ("ml_examples", example)):
            index[(table, value["id"])] = {"data": value, "row_sha256": digest(value)}
    # A second exact example shares the first claim: not independent evidence.
    original = index[("ml_examples", uid(4))]["data"]
    second = {**original, "id": uid(25)}
    index[("ml_examples", uid(25))] = {"data": second, "row_sha256": digest(second)}
    first["family"] = "family_MgB2"
    index[("materials", first["id"])]["row_sha256"] = digest(first)
    for (table, identifier), envelope in index.items():
        envelope.update(table=table, row_id=identifier)
    task = default_task()
    contexts = resolve_result_contexts(index, {})
    ids, families, _, _ = _groups(index, contexts, {}, {}, task, {})
    graph = audit._reconstruct(index, {}, {}, contexts, {}, task, {}, audit._Budget())
    assert graph.identifiers() == ids
    identities = {}
    for key, component in ids.items():
        identities.setdefault(component, set())
        identity = graph.identity(key)
        if identity:
            identities[component].add(identity)
    examples = {identifier: value["data"] for (table, identifier), value in index.items() if table == "ml_examples"}
    assigned, held = _split(sorted(set(ids[("result", "material_claims:" + value["claim_id"])] for value in examples.values())), families, task)
    assert not held
    rows = [{"example_id": identifier, "claim_id": value["claim_id"],
             "group_id": ids[("result", "material_claims:" + value["claim_id"])],
             "split": assigned[ids[("result", "material_claims:" + value["claim_id"])]],
             "assignment_sha256": digest([identifier, "synthetic-unit"])} for identifier, value in sorted(examples.items())]
    base = {"task": {"label_task": task, "physical_features": [], "structure_features": []},
        "input_pins": {"dataset_id": dataset_id},
        "candidates": [{"example_id": value["example_id"], "claim_id": value["claim_id"], "group_id": value["group_id"], "status": "included"} for value in rows],
        "rows": rows, "split_report": {"base_assignments": assigned},
        "cohorts": {name: {"example_ids": sorted(examples) if name == "B" else [],
                            "sha256": digest(sorted(examples) if name == "B" else [])} for name in audit.COHORTS},
        "views": {"C@B": {"rows": deepcopy(rows), "cohort_sha256": digest(sorted(examples))}}, "comparisons": []}
    return base, index, ids, families, identities, graph


def inspect(base, index, ids, families, identities):
    return audit._assignment_audit(base, index, ids, families, identities, audit._Budget())


def test_reconstruction_matches_real_old_group_function_without_instrumenting_it():
    base, index, ids, families, identities, graph = graph_fixture()
    assert graph.identifiers() == ids
    assert all(value["witness_sha256"] == digest({key: part for key, part in value.items() if key != "witness_sha256"})
               for value in graph.witnesses.values())
    assert all(value["row_pins"] for value in graph.witnesses.values())
    examples, counts, checks = inspect(base, index, ids, families, identities)
    assert not any(checks.values())
    assert len(examples) == 4
    selected = next(row for row in counts if row["cohort"] == "B" and row["partition"] == "all")
    assert selected["rows"] == 4 and selected["components"] == 3
    assert selected["direct_label"]["identity_counts"]["claim"] == 3
    assert selected["direct_label"]["missing_identity_counts"]["sample"] == 4
    assert selected["full_components"]["identity_counts"]["material"] == 3


def test_namespace_aliases_do_not_double_count_actual_material():
    _, _, ids, _, identities, graph = graph_fixture()
    key = "material", "synthetic:MgB2"
    assert ids[key] == ids[("material_ancestor", key[1])]
    assert graph.identity(key) == graph.identity(("material_ancestor", key[1]))
    assert audit._identity_counts(identities[ids[key]])["material"] == 1


def test_actual_same_component_partition_crossing_is_computed():
    base, index, ids, families, identities, _ = graph_fixture()
    duplicate = next(row for row in base["rows"] if row["example_id"] == uid(25))
    duplicate["split"] = next(part for part in audit.PARTITIONS if part != duplicate["split"])
    examples, counts, checks = inspect(base, index, ids, families, identities)
    assert checks["component_crossings"] == [{"component_sha256": duplicate["group_id"],
        "partitions": sorted({row["split"] for row in base["rows"] if row["claim_id"] == duplicate["claim_id"]}),
        "example_ids": sorted([uid(4), uid(25)])}]
    assert any(item["kind"] == "claim" and item["id"] == uid(1) for item in checks["identity_crossings"])
    assert checks["view_violations"] and checks["assignment_violations"]


def test_full_component_counts_include_excluded_bridge_not_direct_selected_label():
    base, index, ids, families, identities, _ = graph_fixture()
    # Simulate a valid complete component membership with an excluded ancestor;
    # this tests count units, while native tests verify its actual SQL joins.
    component = next(iter(identities))
    identities[component].add(("material", "excluded-parent"))
    _, counts, _ = inspect(base, index, ids, families, identities)
    count = next(row for row in counts if row["cohort"] == "B" and row["partition"] == "all")
    assert count["full_components"]["identity_counts"]["material"] == 4
    assert count["direct_label"]["identity_counts"]["material"] == 3


@pytest.mark.parametrize("change", ["missing_B", "outside_P", "invalid_PS", "excluded_row"])
def test_cohort_and_candidate_contradictions_are_explicit_no_go_evidence(change):
    base, index, ids, families, identities, _ = graph_fixture()
    if change == "excluded_row":
        base["candidates"][0]["status"] = "excluded"
    elif change == "missing_B":
        base["cohorts"]["B"]["example_ids"].pop()
    elif change == "outside_P":
        identifier = base["cohorts"]["B"]["example_ids"].pop()
        base["cohorts"]["P"]["example_ids"] = [identifier]
    else:
        base["cohorts"]["PS"]["example_ids"] = [base["rows"][0]["example_id"]]
    for value in base["cohorts"].values():
        value["sha256"] = digest(value["example_ids"])
    assert inspect(base, index, ids, families, identities)[2]["cohort_violations"]


@pytest.mark.parametrize("change", ["member", "split", "assignment", "cohort_hash"])
def test_view_assignment_or_membership_is_actually_checked(change):
    base, index, ids, families, identities, _ = graph_fixture()
    view = base["views"]["C@B"]
    if change == "member": view["rows"].pop()
    elif change == "split": view["rows"][0]["split"] = "test" if view["rows"][0]["split"] != "test" else "train"
    elif change == "assignment": view["rows"][0]["assignment_sha256"] = "f" * 64
    else: view["cohort_sha256"] = "f" * 64
    assert inspect(base, index, ids, families, identities)[2]["view_violations"]


def test_same_cohort_comparison_mismatch_is_computed():
    base, index, ids, families, identities, _ = graph_fixture()
    base["task"]["physical_features"] = [{"unit_fixture_only": True}]
    base["cohorts"]["P"] = deepcopy(base["cohorts"]["B"])
    base["views"].update({name: deepcopy(base["views"]["C@B"]) for name in ("C@P", "CP@P")})
    base["comparisons"] = [["C@P", "CP@P"]]
    assert not any(inspect(base, index, ids, families, identities)[2].values())
    base["views"]["CP@P"]["rows"][0]["split"] = "changed_partition"
    checks = inspect(base, index, ids, families, identities)[2]
    assert checks["comparison_violations"] and checks["view_violations"]


def test_mixed_or_unknown_family_component_cannot_be_assigned():
    base, index, ids, families, identities, _ = graph_fixture()
    base["task"]["label_task"]["split"].update(mode="family_holdout", validation_families=["family_Nb"], test_families=["family_Ta"])
    assigned_component = base["rows"][0]["group_id"]
    families[assigned_component] = {"family_Nb", "family_Ta"}
    checks = inspect(base, index, ids, families, identities)[2]
    assert any(item["component_sha256"] == assigned_component and item["expected_partition"] is None
               and item["reason_code"] == "family_holdout_component_conflict_or_unknown" for item in checks["assignment_violations"])


@pytest.mark.parametrize("change", ["group", "missing_candidate", "duplicate_candidate", "duplicate_row", "unknown_row", "cohort_hash", "duplicate_cohort"])
def test_unknown_missing_duplicate_or_hash_mismatch_rejects_whole_audit(change):
    base, index, ids, families, identities, _ = graph_fixture()
    if change == "group": base["rows"][0]["group_id"] = "f" * 64
    elif change == "missing_candidate": base["candidates"].pop()
    elif change == "duplicate_candidate": base["candidates"].append(deepcopy(base["candidates"][0]))
    elif change == "duplicate_row": base["rows"].append(deepcopy(base["rows"][0]))
    elif change == "unknown_row": base["rows"][0]["example_id"] = "unknown"
    elif change == "cohort_hash": base["cohorts"]["B"]["sha256"] = "f" * 64
    else: base["cohorts"]["B"]["example_ids"].append(base["rows"][0]["example_id"])
    with pytest.raises(audit.MlIdentityAuditError):
        inspect(base, index, ids, families, identities)


def test_edge_defined_relationship_components_separate_unlinked_identities():
    base, index, _, _, _, _ = graph_fixture()
    materials = sorted(key for table, key in index if table == "materials")
    index[("materials", materials[1])]["data"]["parent_material_id"] = materials[0]
    for number in (80, 81, 82):
        index[("research_samples", uid(number))] = {"data": {"id": uid(number)}}
    task = base["task"]["label_task"]
    task["grouping_links"] = [{"kind": "sample_trajectory", "left_id": uid(80), "right_id": uid(81), "review_artifact_id": uid(90)}]
    result = audit._relationship_components(index, task, audit._Budget())
    assert result["material_series"]["components"][0]["members"] == materials[:2]
    assert result["material_series"]["unlinked_ids"] == materials[2:]
    assert result["sample_trajectory"]["declared_edge_count"] == 1
    assert result["sample_trajectory"]["components"][0]["edge_count"] == 1
    assert result["sample_trajectory"]["unlinked_ids"] == [uid(82)]
    assert result["structure_near_duplicate"] == {"components": [], "unlinked_ids": [], "declared_edge_count": 0}


@pytest.mark.parametrize("table,kind,field", [("research_samples", "sample", "sample_label"), ("works", "work", "canonical_title")])
def test_same_name_does_not_create_an_identity_join(table, kind, field):
    _, index, _, _, _, _ = graph_fixture()
    graph = audit._Graph(index, {}, {}, audit._Budget())
    for number in (70, 71):
        value = {"id": uid(number), field: "same text"}
        index[(table, uid(number))] = {"data": value, "row_sha256": digest(value)}
        graph.join([(kind, uid(number))], rule="sample_foreign_keys", refs=[(table, uid(number))])
    ids = graph.identifiers()
    assert ids[(kind, uid(70))] != ids[(kind, uid(71))]


def test_chemical_system_join_only_when_the_task_requests_extrapolation():
    base, index, _, _, _, _ = graph_fixture()
    material = index[("materials", "synthetic:Nb")]
    material["data"].update(formula="MgB4", formula_normalized="MgB4")
    material["row_sha256"] = digest(material["data"])
    claim = index[("material_claims", uid(11))]
    claim["data"]["raw_record"] = {"formula": "MgB4"}
    claim["row_sha256"] = digest(claim["data"])
    contexts = resolve_result_contexts(index, {})
    task = base["task"]["label_task"]
    interpolation = audit._reconstruct(index, {}, {}, contexts, {}, task, {}, audit._Budget())
    before = interpolation.identifiers()
    assert before[("material", "synthetic:MgB2")] != before[("material", "synthetic:Nb")]
    assert not any(key[0] == "chemical_system" for key in before)
    task["split"]["mode"] = "chemical_system_extrapolation"
    extrapolation = audit._reconstruct(index, {}, {}, contexts, {}, task, {}, audit._Budget())
    after = extrapolation.identifiers()
    assert after == _groups(index, contexts, {}, {}, task, {})[0]
    assert after[("material", "synthetic:MgB2")] == after[("material", "synthetic:Nb")]
    assert any(item["rule"] == "declared_chemical_system_split" for item in extrapolation.witnesses.values())


def test_excluded_mixed_family_component_does_not_make_whole_audit_no_go():
    base, index, ids, families, identities, _ = graph_fixture()
    task = base["task"]["label_task"]
    task["split"].update(mode="family_holdout", validation_families=["family_Nb"], test_families=["family_Ta"])
    component = ids[("material", "synthetic:MgB2")]
    families[component] = {"family_Nb", "family_Ta"}
    for candidate in base["candidates"]:
        if candidate["group_id"] == component:
            candidate["status"] = "excluded"
    base["rows"] = [row for row in base["rows"] if row["group_id"] != component]
    assigned, held = _split(sorted({row["group_id"] for row in base["rows"]}), families, task)
    assert not held
    base["split_report"]["base_assignments"] = assigned
    for selected_row in base["rows"]:
        selected_row["split"] = assigned[selected_row["group_id"]]
    members = sorted(row["example_id"] for row in base["rows"])
    base["cohorts"]["B"] = {"example_ids": members, "sha256": digest(members)}
    base["views"]["C@B"] = {"rows": deepcopy(base["rows"]), "cohort_sha256": digest(members)}
    assert not any(inspect(base, index, ids, families, identities)[2].values())


def test_prototype_structure_without_coordinate_artifact_has_no_coordinate_count():
    _, index, _, _, _, _ = graph_fixture()
    claim = index[("material_claims", uid(1))]["data"]
    claim["event_id"] = uid(70)
    index[("research_events", uid(70))] = {"data": {"state_id": uid(71), "structure_id": uid(72), "producer_run_id": None}}
    index[("material_states", uid(71))] = {"data": {"sample_id": None}}
    index[("structure_records", uid(72))] = {"data": {"structure_kind": "prototype", "artifact_id": None}}
    direct = audit._direct(index, uid(1))
    assert ("structure", uid(72)) in direct
    assert not any(key[0] == "coordinate_bytes" for key in direct)


def test_unreviewed_mapping_witness_is_not_named_scientifically_reviewed():
    _, index, _, _, _, _ = graph_fixture()
    graph = audit._Graph(index, {}, {}, audit._Budget())
    for table, identifier in (("papers", "paper"), ("works", uid(50))):
        data = {"id": identifier}
        index[(table, identifier)] = {"data": data, "row_sha256": digest(data)}
    data = {"paper_id": "paper", "work_id": uid(50), "review_status": "pending"}
    index[("paper_work_map", "paper")] = {"data": data, "row_sha256": digest(data)}
    graph.join([("paper", "paper"), ("work", uid(50))], rule="captured_paper_work_mapping", refs=[("paper_work_map", "paper")])
    witness = next(iter(graph.witnesses.values()))
    assert witness["rule"] == "captured_paper_work_mapping"
    assert any(pin["table"] == "paper_work_map" and pin["row_sha256"] == digest(data) for pin in witness["row_pins"])


def test_frozen_feature_binding_namespace_and_mapping_review_bytes_are_traceable():
    # Typed graph unit: the native test separately obtains these witness fields
    # from the real strict source-companion verifier and an actual SQL capsule.
    base, index, _, _, _, _ = graph_fixture()
    input_id, binding_id, work_id, review_id = map(uid, (90, 91, 92, 93))
    input_row = {"id": input_id, "example_id": uid(4), "input_claim_id": uid(1),
                 "input_property_id": None, "input_structure_id": None,
                 "input_artifact_id": None, "input_event_id": None}
    index[("ml_example_inputs", input_id)] = {"data": input_row, "row_sha256": digest(input_row)}
    raw = b"explicitly synthetic retained review bytes, no authority"
    sha = audit.hashlib.sha256(raw).hexdigest()
    mapping = {"paper_id": "synthetic-feature-paper", "work_id": work_id, "review_status": "accepted"}
    binding = {"id": binding_id, "review_artifact_id": review_id}
    source_rows = {
        ("ml_feature_source_bindings", binding_id): binding,
        ("papers", "synthetic-feature-paper"): {"id": "synthetic-feature-paper"},
        ("works", work_id): {"id": work_id},
        ("paper_work_map", "synthetic-feature-paper"): mapping,
        ("evidence_artifacts", review_id): {"id": review_id, "bytes_sha256": sha},
    }
    source_index = {ref: {"data": row, "row_sha256": digest(row)} for ref, row in source_rows.items()}
    witness = {"group_keys": (("feature_binding", binding_id), ("paper", "synthetic-feature-paper"), ("work", work_id)),
               "binding_ids": (binding_id,)}
    contexts = resolve_result_contexts({ref: row for ref, row in index.items() if ref[0] != "ml_example_inputs"}, {})
    task = base["task"]["label_task"]
    graph = audit._reconstruct(index, source_index, {input_id: witness}, contexts, {}, task, {sha: raw}, audit._Budget())
    assert graph.identifiers() == _groups(index, contexts, {input_id: witness}, {}, task, {})[0]
    assert graph.identity(("feature_binding", binding_id)) == ("feature_binding", binding_id)
    found = next(item for item in graph.witnesses.values() if item["rule"] == "verified_feature_source_binding")
    assert found["artifact_sha256"] == [sha]
    for ref in (("ml_feature_source_bindings", binding_id), ("paper_work_map", "synthetic-feature-paper"), ("evidence_artifacts", review_id)):
        assert {"source": "companion", "table": ref[0], "row_id": ref[1], "row_sha256": digest(source_rows[ref])} in found["row_pins"]
    with pytest.raises(audit.MlIdentityAuditError, match="ml_identity_join_artifact_mismatch"):
        audit._reconstruct(index, source_index, {input_id: witness}, contexts, {}, task, {sha: b"tampered"}, audit._Budget())


@pytest.mark.parametrize("key", [("unknown", "x"), ("material", "missing"), ("result", "bad:x"), ("coordinate_bytes", "bad"), ("event", None)])
def test_typed_member_requires_known_exact_reference(key):
    graph = audit._Graph({}, {}, {}, audit._Budget())
    with pytest.raises(audit.MlIdentityAuditError):
        graph.join([key], rule="event_foreign_keys")


def test_declared_coordinate_bytes_require_actual_matching_bytes():
    graph = audit._Graph({}, {}, {"a" * 64: b"different"}, audit._Budget())
    with pytest.raises(audit.MlIdentityAuditError):
        graph.join([("coordinate_bytes", "a" * 64)], rule="structure_identity_and_ancestry")


@pytest.mark.parametrize("kind", ["references", "nodes", "joins"])
def test_graph_budget_fails_without_truncation(monkeypatch, kind):
    _, index, _, _, _, _ = graph_fixture()
    monkeypatch.setitem(audit.LIMITS, kind, 0)
    graph = audit._Graph(index, {}, {}, audit._Budget())
    with pytest.raises(audit.MlIdentityAuditError):
        graph.join([("material", "synthetic:MgB2")], rule="material_parent_series")


@pytest.mark.parametrize("kind", ["depth", "nodes", "bytes", "nan", "surrogate"])
def test_json_bounds_and_invalid_scalars(kind):
    if kind == "depth":
        value = {}
        for _ in range(audit.LIMITS["json_depth"] + 2): value = [value]
    elif kind == "nodes": value = [None] * (audit.LIMITS["json_nodes"] + 1)
    elif kind == "bytes": value = "x" * (audit.LIMITS["serialized_bytes"] + 1)
    elif kind == "nan": value = float("nan")
    else: value = "\ud800"
    with pytest.raises((ValueError, UnicodeError)):
        audit.canonical_audit(value)


def test_local_union_hash_matches_old_sorted_typed_members():
    _, index, _, _, _, _ = graph_fixture()
    old = _Groups()
    graph = audit._Graph(index, {}, {}, audit._Budget())
    for keys in ([('material', 'synthetic:MgB2')], [('material', 'synthetic:Nb'), ('material', 'synthetic:Ta')]):
        old.join(keys)
        graph.join(keys, rule="material_parent_series")
    assert graph.identifiers() == old.identifiers()
