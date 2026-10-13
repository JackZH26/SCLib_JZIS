"""Synthetic multi-capture works exercise whole-paper coverage and shared budgets."""

from copy import deepcopy
from dataclasses import asdict

import pytest

from test_materials_v3 import FakeProvider, document
from ingestion.materials_v3.batch import run_batch
from ingestion.materials_v3.comparison import comparison_package
from ingestion.materials_v3.contract import digest
from ingestion.materials_v3.evaluation import evaluate, tuple_key
from ingestion.materials_v3.ledger import Ledger
from ingestion.materials_v3.manifest import FAMILIES, freeze_manifest, validate_manifest
from ingestion.materials_v3.pipeline import Budget
from ingestion.materials_v3.providers import MODEL, REVISION, ProviderConfig


def capture(doc):
    return {
        "source_version": "synthetic-v1",
        "source_url": "https://example.invalid/source",
        "source_license": "synthetic-test-only",
        "source_sha256": doc["source_sha256"],
        "content_manifest_sha256": doc["manifest_sha256"],
        "source_format": "txt",
        "coverage": {"parser_status": "synthetic"},
        "transfer_allowed": True,
        "cloud_inference_allowed": True,
    }


def paper_with_supplement(docs):
    return {
        **capture(docs[0]),
        "paper_id": "synthetic:p",
        "work_id": "synthetic:w",
        "main_text_sha256": docs[0]["source_sha256"],
        "split": "development",
        "supplement_status": "included",
        "supplement_captures": [capture(docs[1])],
    }


def test_supplement_is_a_separate_capture_of_the_same_work_and_replay_is_free(tmp_path):
    docs = [document(tmp_path, "No target claim in " + part) for part in ("main", "supplement")]
    paper = paper_with_supplement(docs)
    manifest = {"papers": [paper], "manifest_sha256": "synthetic-unfrozen"}
    provider, ledger, runs = FakeProvider(), Ledger(tmp_path / "ledger.sqlite"), []

    def publish(source, run):
        runs.append(run)
        return run["job_key"]

    args = dict(
        split="development",
        load_document=lambda c: next(d for d in docs if d["source_sha256"] == c["source_sha256"]),
        publish=publish,
    )
    first = run_batch(manifest, provider, ledger, **args)
    second = run_batch(manifest, provider, ledger, **args)
    assert first == second and provider.calls == 2
    assert len(first["outputs"]) == 1 and len(first["outputs"][0]["sources"]) == 2
    complete = comparison_package(runs[:2], manifest, "local_mlx")
    assert complete["coverage_by_work"][paper["work_id"]]["machine_text_complete"]
    partial = comparison_package(runs[:1], manifest, "local_mlx")
    assert not partial["coverage_by_work"][paper["work_id"]]["machine_text_complete"]
    assert partial["coverage_by_work"][paper["work_id"]]["missing_captures"] == [
        docs[1]["manifest_sha256"]
    ]
    with pytest.raises(ValueError, match="duplicated"):
        comparison_package(runs, manifest, "local_mlx")
    ledger.close()


def test_paper_attempt_budget_is_shared_across_main_and_supplement(tmp_path):
    docs = [document(tmp_path, "No target claim " + str(i)) for i in range(2)]
    provider, ledger = FakeProvider(), Ledger(tmp_path / "ledger.sqlite")
    out = run_batch(
        {"papers": [paper_with_supplement(docs)], "manifest_sha256": "synthetic"},
        provider,
        ledger,
        split="development",
        load_document=lambda c: next(d for d in docs if d["source_sha256"] == c["source_sha256"]),
        publish=lambda c, r: r["job_key"],
        budget=Budget(max_attempts_per_paper=1),
    )
    assert provider.calls == 1 and not out["machine_text_complete"]
    assert not out["outputs"][0]["sources"][1]["coverage"]["machine_text_complete"]
    ledger.close()


def test_supplement_cloud_permission_is_not_inherited_from_main(tmp_path):
    docs = [document(tmp_path, "No target claim " + str(i)) for i in range(2)]
    paper = paper_with_supplement(docs)
    paper["supplement_captures"][0]["cloud_inference_allowed"] = False
    provider, ledger = FakeProvider(), Ledger(tmp_path / "ledger.sqlite")
    provider.config = ProviderConfig("openai", "gpt-6.1-sol")
    with pytest.raises(ValueError, match="permissions_incomplete"):
        run_batch(
            {"papers": [paper], "manifest_sha256": "synthetic"},
            provider,
            ledger,
            split="development",
            load_document=lambda c: None,
            publish=lambda c, r: None,
        )
    assert provider.calls == 0
    ledger.close()


def synthetic_frozen_manifest():
    papers = []
    tags = [
        "multi_point_same_paper_material",
        "table_header_and_footnote_binding",
        "negative_or_inconclusive_sc_outcome",
        "cited_and_primary_results",
        "bounds_ranges_or_uncertainty",
        "multiple_tc_criteria",
        "calculated_results_with_method_parameters",
        "critical_evidence_after_old_16k_prefix_or_section_eight",
    ]
    for family in sorted(FAMILIES):
        for i in range(10):
            ident = f"synthetic:{family}:{i}"
            papers.append(
                {
                    "paper_id": ident,
                    "work_id": ident,
                    "title": "Synthetic test only",
                    "doi_or_arxiv_id": ident,
                    "family": family,
                    "study_dependency_group": ident,
                    "split": "development" if i < 2 else "validation" if i < 4 else "blind_test",
                    "source_version": "v1",
                    "source_url": "https://example.invalid",
                    "source_license": "synthetic",
                    "main_text_sha256": "s" + ident,
                    "content_manifest_sha256": "c" + ident,
                    "source_format": "txt",
                    "coverage": {"status": "synthetic"},
                    "transfer_allowed": True,
                    "supplement_status": "confirmed_absent",
                    "work_identity_status": "verified",
                    "dependency_group_review_status": "verified",
                    "family_review_status": "verified",
                    "verified_case_tags": tags,
                    "verified_independent_materials": ["synthetic:m" + str(j) for j in range(5)],
                }
            )
    return freeze_manifest({"papers": papers})


def test_freeze_refuses_unreviewed_families_and_unbound_supplements():
    manifest = synthetic_frozen_manifest()
    manifest["papers"][0]["family_review_status"] = "pending"
    manifest["papers"][1]["supplement_status"] = "included"
    errors = validate_manifest(manifest, freeze=True)
    assert "family_review_status_unconfirmed" in errors
    assert "included_supplement_capture_missing" in errors


def test_frozen_source_identity_is_portable_and_excludes_private_paths():
    manifest = synthetic_frozen_manifest()
    manifest["papers"][0]["private_document_path"] = "/synthetic/coordinator/only.json"
    frozen = freeze_manifest(manifest)
    assert "private_document_path" not in frozen["papers"][0]
    assert frozen["manifest_sha256"] == digest(
        {k: v for k, v in frozen.items() if k != "manifest_sha256"}
    )


def test_three_model_labels_and_common_configuration_are_bound_before_scoring():
    manifest = synthetic_frozen_manifest()
    works = {p["work_id"]: [] for p in manifest["papers"] if p["split"] == "blind_test"}
    gold = {
        "status": "adjudicated",
        "annotators": ["Synthetic A", "Synthetic B"],
        "adjudicator": "Synthetic C",
        "manifest_sha256": manifest["manifest_sha256"],
        "claims_by_work": works,
    }
    models = {}
    for name, model, revision in (
        ("local_mlx", MODEL, REVISION),
        ("gemini", "gemini-3.5-flash", None),
        ("openai", "gpt-6.1-sol", None),
    ):
        config = {
            "provider": asdict(ProviderConfig(name, model, revision)),
            "synthetic_common_prompt": "v1",
        }
        models[name] = {
            "provider": name,
            "configuration": config,
            "config_sha256": digest(config),
            "manifest_sha256": manifest["manifest_sha256"],
            "claims_by_work": works,
            "coverage_by_work": {
                w: {"machine_text_complete": True, "end_to_end_complete": True} for w in works
            },
        }
    assert evaluate(models, gold, manifest)["quality_acceptance"] == "not_fully_assessed"
    wrong = deepcopy(models)
    wrong["local_mlx"]["provider"] = "openai"
    with pytest.raises(ValueError, match="configuration_unbound"):
        evaluate(wrong, gold, manifest)
    wrong = deepcopy(models)
    wrong["gemini"]["configuration"]["synthetic_common_prompt"] = "other"
    wrong["gemini"]["config_sha256"] = digest(wrong["gemini"]["configuration"])
    with pytest.raises(ValueError, match="differs"):
        evaluate(wrong, gold, manifest)
    wrong = deepcopy(models)
    wrong["gemini"]["configuration"]["provider"]["max_output_tokens"] = 2048
    wrong["gemini"]["config_sha256"] = digest(wrong["gemini"]["configuration"])
    with pytest.raises(ValueError, match="differs"):
        evaluate(wrong, gold, manifest)


def test_integer_and_float_json_forms_are_the_same_numeric_claim():
    claim = {
        "material": "Synthetic",
        "sample": None,
        "state": [],
        "point": [],
        "property": "tc",
        "criterion": "onset",
        "quantity": {"value": 240},
        "method": "synthetic",
        "knowledge_origin": "Observed",
        "source_role": "primary",
    }
    equivalent = deepcopy(claim)
    equivalent["quantity"]["value"] = 240.0
    assert tuple_key(claim) == tuple_key(equivalent)
