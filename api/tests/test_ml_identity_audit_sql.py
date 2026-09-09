"""Typed identity accounting over actual disposable SQL/frozen audit inputs.

These records and review declarations are synthetic. Their exact database
identities, source bindings and immutable bytes are real technical fixtures,
not evidence of independently replicated experiments or scientific approval.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa

from models.db import Base
from models.ml_task_v2 import selector_for
from services.ml_dataset_builder import GROUP_REVIEW_VERSION
from services.ml_dataset_builder_v4 import build_task_dataset_v4, verify_task_dataset_v4
from services.research_release_manifest import canonical, digest
from services.source_registry import (
    SOURCE_REGISTRY_VERSION,
    import_source_provenance_bundle,
    normalize_source_provenance_bundle,
    source_occurrence_review_payload,
)
from tests.test_ml_dataset_v4 import compiler_inputs, hold_label, recapture
from tests.test_ml_label_capture import db_session as db_session
from tests.test_ml_label_capture import label_fixture, read_snapshot, write_snapshot
from tests.test_ml_physical_feature_sql import computed_property, write_cli_capsule
from tests.test_ml_task_dataset_sql import eligible_specs
from tests.test_research_freeze import add, state
from tests.test_research_release_schema import capture


def build(arguments):
    from services.ml_audited_dataset import build_audited_task_dataset
    return build_audited_task_dataset(**arguments)


def verify(package, arguments):
    from services.ml_audited_dataset import digest as package_digest
    from services.ml_audited_dataset import verify_audited_task_dataset
    return verify_audited_task_dataset(package, expected_package_sha256=package_digest(package), **arguments)


def audit_example(package, seeded, key):
    identifier = str(seeded["fixture"]["candidates"][key]["example"]["id"])
    return next(item for item in package["identity_audit"]["examples"] if item["example_id"] == identifier)


def component_for(package, example):
    return next(item for item in package["identity_audit"]["components"]
                if item["component_sha256"] == example["component_sha256"])


def count_for(package, cohort="B", partition="all"):
    return next(item for item in package["identity_audit"]["counts"]
                if item["cohort"] == cohort and item["partition"] == partition)


async def retain_review(db, fixture, document, *, event_id, schema=GROUP_REVIEW_VERSION):
    payload = canonical(document)
    artifact = await add(db, "evidence_artifacts", kind="review", schema_version=schema,
        source="synthetic-identity-audit-declaration", record_sha256=digest(document),
        bytes_sha256=hashlib.sha256(payload).hexdigest(), hash_status="verified", access="restricted",
        metadata={"synthetic": True})
    fixture["args"]["artifact_bytes"][artifact["bytes_sha256"]] = payload
    if event_id is not None:
        await add(db, "event_evidence", event_id=event_id, link_type="source", artifact_id=artifact["id"],
            locator={"section": "synthetic declared identity grouping"})
    return artifact


@pytest.mark.parametrize("features", [False, True])
async def test_actual_complete_identity_audit_preserves_v4_bytes_and_full_sql(db_session, features):
    from services.ml_identity_audit import build_identity_audit
    seeded = await label_fixture(db_session, features=features)
    arguments = compiler_inputs(seeded)
    before = await state(db_session)
    base = build_task_dataset_v4(**arguments)
    old = canonical(base)
    direct_audit = build_identity_audit(base, **{key: arguments[key] for key in (
        "manifest", "artifact_bytes", "companion", "expected_manifest_sha256", "expected_companion_sha256")})
    package = build(arguments)
    assert package["version"] == "ml-identity-audited-dataset/1.0.0"
    assert package["gate"]["status"] == package["identity_audit"]["gate"]["status"] == "pass"
    assert canonical(package["base_dataset"]) == old
    assert package["base_dataset_sha256"] == digest(base)
    assert package["identity_audit"] == direct_audit
    assert old == canonical(build_task_dataset_v4(**arguments))
    assert verify_task_dataset_v4(base, expected_bundle_sha256=digest(base), **arguments)["integrity_verified"]
    assert package == build(arguments)
    verify(package, arguments)
    assert before == await state(db_session)
    audit = package["identity_audit"]
    assert len(audit["examples"]) == 5
    assert all(item["candidate_status"] == "included" for item in audit["examples"])
    total = count_for(package)
    assert total["rows"] == total["components"] == 5
    assert total["direct_label"]["identity_counts"]["claim"] == 5
    assert total["direct_label"]["identity_counts"]["work"] == 5
    assert total["direct_label"]["missing_identity_counts"]["structure"] == (0 if features else 5)
    assert total["full_components"]["identity_counts"]["work"] == (10 if features else 5)
    assert all(value is False for value in package["authority"].values())
    assert all(not violations for violations in audit["checks"].values())
    for cohort in ("B", "P", "S", "PS"):
        expected = 5 if features or cohort == "B" else 0
        assert count_for(package, cohort)["rows"] == expected
        assert sum(count_for(package, cohort, split)["rows"] for split in ("train", "validation", "test")) == expected
    for module, expected in package["audit_implementation"].items():
        namespace, name = module.rsplit(".", 1)
        assert hashlib.sha256(files(namespace).joinpath(name + ".py").read_bytes()).hexdigest() == expected
    assert set(package["audit_implementation"]) == {"services.ml_identity_audit", "services.ml_audited_dataset"}


async def test_paper_versions_and_repeated_occurrences_do_not_count_as_independent_work(db_session):
    specs = eligible_specs()
    specs[0]["work_group"] = specs[1]["work_group"] = "same-work"
    async def aliases(db, fixture):
        one, two = [fixture["candidates"][key] for key in ("one", "two")]
        maps = Base.metadata.tables["paper_work_map"]
        await db.execute(maps.update().where(maps.c.paper_id == one["paper"]["id"]).values(relation_type="preprint"))
        await db.execute(maps.update().where(maps.c.paper_id == two["paper"]["id"]).values(relation_type="published_version"))
        old = one["source_bundle"]
        revision = {**old["source_revisions"][0], "id": str(uuid4()), "revision_key": "arxiv-v2", "provider_revision": "v2"}
        captured = {**old["source_captures"][0], "id": str(uuid4()), "source_revision_id": revision["id"],
                    "capture_key": "synthetic-second-version"}
        occurrence = {"id": str(uuid4()), "claim_id": str(one["claim"]["id"]), "work_id": str(one["work"]["id"]),
            "source_revision_id": revision["id"], "capture_id": captured["id"], "occurrence_key": "synthetic-repeated-citation",
            "locator": {"table": "2", "row": 1}, "binding_status": "pending"}
        bundle = {"version": SOURCE_REGISTRY_VERSION, "source_revisions": [revision],
                  "source_captures": [captured], "claim_source_occurrences": [occurrence]}
        normalized = normalize_source_provenance_bundle(bundle)
        document = source_occurrence_review_payload(normalized["source_revisions"][0], normalized["source_captures"][0],
            normalized["claim_source_occurrences"][0], one["claim"])
        document.update(binding_verified=True, version_resolved=True, public_time_verified=True)
        payload = canonical(document)
        artifact = await add(db, "evidence_artifacts", kind="review", schema_version="source-occurrence-review/1.0.0",
            source="synthetic-repeated-source-citation", record_sha256=digest(document), bytes_sha256=digest(document),
            hash_status="verified", access="restricted", metadata={"source_provenance_review": document})
        fixture["args"]["artifact_bytes"][digest(document)] = payload
        occurrence.update(binding_status="reviewed", review_artifact_id=str(artifact["id"]), review_artifact_sha256=artifact["record_sha256"])
        await import_source_provenance_bundle(db, bundle, dry_run=False)
        fixture["args"]["source_roots"].append({"table": "claim_source_occurrences", "row_id": occurrence["id"]})
    seeded = await label_fixture(db_session, specs=specs, before_freeze=aliases)
    package = build(compiler_inputs(seeded))
    one, two = [audit_example(package, seeded, key) for key in ("one", "two")]
    assert one["candidate_status"] == two["candidate_status"] == "included"
    assert one["component_sha256"] == two["component_sha256"]
    assert one["base_partition"] == two["base_partition"]
    counts = component_for(package, one)["identity_counts"]
    assert {key: counts[key] for key in ("claim", "paper", "work", "source_revision", "capture", "occurrence")} == {
        "claim": 2, "paper": 2, "work": 1, "source_revision": 3, "capture": 3, "occurrence": 3}
    assert count_for(package)["direct_label"]["identity_counts"]["work"] == 4
    assert package["identity_audit"]["independent_support_count"] is None
    # Deliberately altered compiled rows are an audit adversary, not new source
    # evidence. Known partitions must produce measured crossings, not a literal []
    # or an opportunity to reconstruct a different leakage component.
    from services.ml_identity_audit import build_identity_audit
    crossed = deepcopy(package["base_dataset"])
    selected = next(row for row in crossed["rows"] if row["example_id"] == one["example_id"])
    selected["split"] = "validation" if selected["split"] != "validation" else "test"
    arguments = compiler_inputs(seeded)
    audit = build_identity_audit(crossed, **{key: arguments[key] for key in (
        "manifest", "artifact_bytes", "companion", "expected_manifest_sha256", "expected_companion_sha256")})
    assert audit["gate"]["status"] == "no_go"
    crossing = next(item for item in audit["checks"]["component_crossings"]
                    if item["component_sha256"] == one["component_sha256"])
    assert set(crossing["example_ids"]) == {one["example_id"], two["example_id"]}
    assert len(crossing["partitions"]) == 2
    assert any(item["kind"] == "work" and item["id"] == str(seeded["fixture"]["candidates"]["one"]["work"]["id"])
               for item in audit["checks"]["identity_crossings"])


async def test_exact_samples_states_and_parent_series_are_not_name_heuristics(db_session):
    specs = [
        {"key": "sample_a", "formula": "Pb", "material_group": "same", "sample_group": "same"},
        {"key": "sample_b", "formula": "Pb", "material_group": "same", "sample_group": "same"},
        {"key": "named_a", "formula": "Nb", "sample_group": "same-text"},
        {"key": "named_b", "formula": "Sn", "sample_group": "same-text"},
        {"key": "parent", "formula": "FeSe"},
        {"key": "child", "formula": "FeSe0.5Te0.5", "parent_key": "parent"},
    ]
    seeded = await label_fixture(db_session, specs=[{**item, "reviewed": True} for item in specs])
    package = build(compiler_inputs(seeded))
    rows = {key: audit_example(package, seeded, key) for key in seeded["fixture"]["candidates"]}
    assert rows["sample_a"]["component_sha256"] == rows["sample_b"]["component_sha256"]
    assert rows["named_a"]["component_sha256"] != rows["named_b"]["component_sha256"]
    assert rows["parent"]["component_sha256"] == rows["child"]["component_sha256"]
    same = component_for(package, rows["sample_a"])["identity_counts"]
    assert same["state"] == 2 and same["sample"] == same["material"] == 1
    relation = package["identity_audit"]["relationship_components"]["material_series"]
    assert relation["declared_edge_count"] == 1
    expected = {seeded["fixture"]["candidates"][key]["material"]["id"] for key in ("parent", "child")}
    assert len(relation["components"]) == 1 and set(relation["components"][0]["members"]) == expected
    assert count_for(package)["components"] == 4


@pytest.mark.parametrize("kind", ["sample_trajectory", "structure_near_duplicate"])
async def test_declared_relationship_membership_is_exact_and_pinned(db_session, kind):
    declarations = {}
    async def declared(db, fixture):
        candidates = [fixture["candidates"][key] for key in ("one", "two")]
        table = "research_samples" if kind == "sample_trajectory" else "structure_records"
        if kind == "sample_trajectory":
            ids = [str(item["sample"]["id"]) for item in candidates]
        else:
            ids = []
            events = Base.metadata.tables["research_events"]
            for item in candidates:
                row = await add(db, table, material_id=item["material"]["id"], structure_kind="prototype",
                    source_version="synthetic-identity/1", record_sha256=digest({"material": item["material"]["id"]}))
                await db.execute(events.update().where(events.c.id == item["event"]["id"]).values(structure_id=row["id"]))
                ids.append(str(row["id"]))
        ids.sort()
        rows = [await capture(db, table, identifier) for identifier in ids]
        document = {"version": GROUP_REVIEW_VERSION, "kind": kind, "table": table,
            "left_id": ids[0], "right_id": ids[1], "left_row_sha256": digest(rows[0]), "right_row_sha256": digest(rows[1]),
            "merge_for_leakage_control": True, "reviewer_authority_authenticated": False, "scientific_acceptance": False}
        review = await retain_review(db, fixture, document, event_id=candidates[0]["event"]["id"])
        wrong = await retain_review(db, fixture, {**document, "left_row_sha256": "0" * 64}, event_id=candidates[0]["event"]["id"])
        declarations.update(ids=ids, review=str(review["id"]), wrong=str(wrong["id"]))
    seeded = await label_fixture(db_session, before_freeze=declared)
    task = deepcopy(seeded["inputs"]["task"])
    task["label_task"]["grouping_links"] = [{"kind": kind, "left_id": declarations["ids"][0],
        "right_id": declarations["ids"][1], "review_artifact_id": declarations["review"]}]
    arguments = compiler_inputs(seeded, task=task)
    package = build(arguments)
    relation = package["identity_audit"]["relationship_components"][kind]
    assert relation["declared_edge_count"] == 1
    assert len(relation["components"]) == 1 and relation["components"][0]["members"] == declarations["ids"]
    left, right = [audit_example(package, seeded, key) for key in ("one", "two")]
    assert left["component_sha256"] == right["component_sha256"] and left["base_partition"] == right["base_partition"]
    wrong = deepcopy(task)
    wrong["label_task"]["grouping_links"][0]["review_artifact_id"] = declarations["wrong"]
    with pytest.raises(ValueError):
        build(compiler_inputs(seeded, task=wrong))


async def test_excluded_bridge_membership_and_family_conflict_do_not_erase_other_valid_components(db_session):
    specs = [
        {"key": "bridge", "formula": "MgB2", "work_group": "left"},
        {"key": "left", "formula": "FeSe", "work_group": "left"},
        {"key": "right", "formula": "Nb"},
        {"key": "train", "formula": "Pb"},
        {"key": "validation", "formula": "Ta"},
        {"key": "test", "formula": "Sn"},
    ]
    async def bridge(db, fixture):
        candidates = fixture["candidates"]
        await add(db, "event_evidence", event_id=candidates["bridge"]["event"]["id"], link_type="context",
                  input_event_id=candidates["right"]["event"]["id"])
        materials = Base.metadata.tables["materials"]
        for key, family in (("bridge", "validation-family"), ("left", "validation-family"),
                            ("right", "test-family"), ("train", "train-family"),
                            ("validation", "validation-family"), ("test", "test-family")):
            await db.execute(materials.update().where(materials.c.id == candidates[key]["material"]["id"]).values(family=family))
    seeded = await label_fixture(db_session, specs=[{**item, "reviewed": True} for item in specs], before_freeze=bridge)
    review, label = await hold_label(db_session, seeded, "bridge")
    task = deepcopy(seeded["inputs"]["task"])
    task["label_task"]["split"].update(mode="family_holdout", validation_families=["validation-family"], test_families=["test-family"])
    package = build(compiler_inputs(seeded, task=task, review=review, label=label))
    assert package["gate"]["status"] == "pass"
    excluded = [audit_example(package, seeded, key) for key in ("bridge", "left", "right")]
    assert len({item["component_sha256"] for item in excluded}) == 1
    assert all(item["candidate_status"] == "excluded" and item["base_partition"] is None and not item["cohorts"] for item in excluded)
    complete = component_for(package, excluded[0])
    assert complete["identity_counts"]["claim"] == 3
    assert set(complete["families"]) == {"validation-family", "test-family"}
    assert count_for(package)["rows"] == count_for(package)["components"] == 3
    assert len(package["identity_audit"]["examples"]) == 6
    assert all(not items for items in package["identity_audit"]["checks"].values())


async def test_held_optional_source_keeps_all_component_members_but_not_direct_support_counts(db_session):
    seeded = await label_fixture(db_session, features=True)
    original = build(compiler_inputs(seeded))
    source = seeded["fixture"]["feature_bindings"][("one", "band_gap")]["source"]
    await write_snapshot(db_session)
    await db_session.execute(sa.text("UPDATE papers SET status='retracted' WHERE id=:id"), {"id": source["revision"]["paper_id"]})
    await read_snapshot(db_session)
    review, label = await recapture(db_session, seeded)
    package = build(compiler_inputs(seeded, review=review, label=label))
    assert {cohort: count_for(package, cohort)["rows"] for cohort in ("B", "P", "S", "PS")} == {"B": 5, "P": 4, "S": 4, "PS": 4}
    example = audit_example(package, seeded, "one")
    assert example["candidate_status"] == "included" and example["cohorts"] == ["B"]
    members = component_for(package, example)["members"]
    assert {"kind": "paper", "id": source["revision"]["paper_id"]} in members
    assert {"kind": "source_revision", "id": source["revision"]["id"]} in members
    assert count_for(package)["direct_label"]["identity_counts"]["work"] == 5
    assert count_for(package)["full_components"]["identity_counts"]["work"] == 10
    assert package["identity_audit"]["nodes"] == original["identity_audit"]["nodes"]
    assert package["identity_audit"]["components"] == original["identity_audit"]["components"]
    assert original == build(compiler_inputs(seeded))


async def test_target_derived_renamed_physics_keeps_real_run_and_result_graph(db_session):
    chain = []
    async def derived(db, fixture):
        candidate = fixture["candidates"]["one"]
        dependency = {"table": "material_claims", "row_id": candidate["claim"]["id"], "event_id": candidate["event"]["id"]}
        for name in ("electron_phonon_lambda", "dos_at_fermi"):
            item = await computed_property(db, fixture, "one", name,
                structure=fixture["structures"]["one"], protocol=fixture["protocols"][name], settings=fixture["settings"][name],
                reference_artifacts=fixture["reference_artifacts"], value=1.5, dependencies=[dependency],
                feature_key="renamed-normal-state-descriptor" if name == "dos_at_fermi" else name)
            fixture["physics"]["one"][name] = item
            fixture["task"]["physical_features"].append(selector_for(fixture["protocols"][name]))
            chain.append(item)
            dependency = {"table": "event_properties", "row_id": item["property"]["id"], "event_id": item["event"]["id"]}
        fixture["task"]["physical_features"].sort(key=lambda item: item["feature_key"])
    seeded = await label_fixture(db_session, features=True, before_freeze=derived)
    package = build(compiler_inputs(seeded))
    assert count_for(package)["rows"] == 5
    example = audit_example(package, seeded, "one")
    component = component_for(package, example)
    assert component["identity_counts"]["run"] == 3
    for item in chain:
        identifier = str(item["input"]["id"])
        admission = next(row for row in package["base_dataset"]["dependency_manifest"]["feature_admission"] if row["input_id"] == identifier)
        assert admission["status"] == "excluded" and "target_dependency" in admission["reason_codes"]
        assert {"kind": "run", "id": str(item["run"]["id"])} in component["members"]
        assert {"kind": "result", "id": "event_properties:" + str(item["property"]["id"])} in component["members"]
    assert all(value is False for value in package["authority"].values())


async def test_resealed_package_tampering_requires_full_recomputation(db_session):
    from services.ml_audited_dataset import digest as package_digest
    seeded = await label_fixture(db_session, features=True)
    arguments = compiler_inputs(seeded)
    original = build(arguments)
    changes = {
        "base_split": lambda package: package["base_dataset"]["rows"][0].update(split="not-a-partition"),
        "base_value": lambda package: package["base_dataset"]["rows"][0]["label"].update(value=9876),
        "member": lambda package: package["identity_audit"]["components"][0]["members"].pop(),
        "duplicate_node": lambda package: package["identity_audit"]["nodes"].append(deepcopy(package["identity_audit"]["nodes"][0])),
        "count": lambda package: package["identity_audit"]["counts"][0].update(rows=999),
        "cohort": lambda package: package["identity_audit"]["examples"][0].update(cohorts=[]),
        "false_check": lambda package: package["identity_audit"]["checks"].update(component_crossings=["synthetic-forged-crossing"]),
        "source_pin": lambda package: package["audit_implementation"].update({"services.ml_identity_audit": "0" * 64}),
        "authority": lambda package: package["authority"].update(ml_training_approved=True),
    }
    for change in changes.values():
        value = deepcopy(original)
        change(value)
        value["base_dataset_sha256"] = digest(value["base_dataset"])
        value["identity_audit_sha256"] = package_digest(value["identity_audit"])
        value["audit_implementation_sha256"] = package_digest(value["audit_implementation"])
        with pytest.raises(ValueError):
            verify(value, arguments)
    assert original == build(arguments)


def cli_inputs(tmp_path, seeded, arguments):
    values = write_cli_capsule(tmp_path, {**seeded["inputs"], "task": arguments["task"]})
    for name in ("review", "label"):
        document = arguments[name + "_companion"]
        path = tmp_path.resolve() / (name + ".json")
        path.write_bytes(canonical(document))
        values.extend(["--" + name + "-companion", str(path), "--" + name + "-companion-sha256", digest(document)])
    return values


def invoke_cli(mode, arguments, extra):
    root = Path(__file__).resolve().parents[2]
    runner = """import runpy,sys
def audit(event,args):
    if event in {'socket.connect','socket.getaddrinfo','subprocess.Popen','os.system','sqlite3.connect'}:
        raise RuntimeError('offline_io_forbidden')
sys.addaudithook(audit)
path=sys.argv.pop(1)
runpy.run_path(path,run_name='__main__')
"""
    return subprocess.run([sys.executable, "-c", runner, str(root / "scripts/ml_audited_dataset.py"), mode,
        *arguments, *extra], cwd=root, capture_output=True, text=True, timeout=60, check=False,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": "0",
             "DATABASE_URL": "postgresql://unused:unused@127.0.0.1:1/unused", "REDIS_URL": "redis://127.0.0.1:1/0"})


async def test_actual_audited_cli_build_verify_and_resealed_refusal_are_offline(db_session, tmp_path):
    from services.ml_audited_dataset import canonical as package_bytes
    from services.ml_audited_dataset import digest as package_digest
    seeded = await label_fixture(db_session, features=True)
    arguments = compiler_inputs(seeded)
    cli = cli_inputs(tmp_path, seeded, arguments)
    output = tmp_path.resolve() / "audited-dataset.json"
    built = invoke_cli("build", cli, ["--output", str(output)])
    assert built.returncode == 0, built.stderr
    assert json.loads(built.stdout)["output_written"] is True
    actual = json.loads(output.read_bytes())
    assert actual == build(arguments)
    checked = invoke_cli("verify", cli, ["--bundle", str(output), "--bundle-sha256", package_digest(actual)])
    assert checked.returncode == 0, checked.stderr
    changed = deepcopy(actual)
    changed["identity_audit"]["counts"][0]["rows"] += 1
    changed["identity_audit_sha256"] = package_digest(changed["identity_audit"])
    tampered = tmp_path.resolve() / "repinned-audit.json"
    tampered.write_bytes(package_bytes(changed))
    refused = invoke_cli("verify", cli, ["--bundle", str(tampered), "--bundle-sha256", package_digest(changed)])
    assert refused.returncode == 2 and not refused.stdout
    assert json.loads(refused.stderr) == {"status": "invalid", "output_written": False}


async def test_audited_cli_no_go_writes_nothing(db_session, tmp_path):
    seeded = await label_fixture(db_session, specs=eligible_specs()[:2])
    arguments = compiler_inputs(seeded)
    package = build(arguments)
    assert package["gate"]["status"] == "no_go"
    output = tmp_path.resolve() / "must-not-exist.json"
    result = invoke_cli("build", cli_inputs(tmp_path, seeded, arguments), ["--output", str(output)])
    assert result.returncode == 3, result.stderr
    assert json.loads(result.stdout)["output_written"] is False
    assert not output.exists()
