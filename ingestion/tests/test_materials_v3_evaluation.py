"""Metric denominator and human-audit counterexamples; fixtures are not real gold."""

from copy import deepcopy

import pytest

from test_materials_v3 import fixture
from test_materials_v3_regressions import result_run
from ingestion.materials_v3.comparison import atomic_claims
from ingestion.materials_v3.contract import digest
from ingestion.materials_v3.evaluation import counts, tuple_key
from ingestion.materials_v3.evaluation_gates import evidence_audit, field_metrics, null_recovery


def test_numeric_error_and_origin_confusion_have_separate_nonperfect_scores():
    value, block = fixture()
    gold = {"w": atomic_claims(result_run(value, block))}
    predicted = deepcopy(gold)
    predicted["w"][0]["quantity"]["value"] = 250
    predicted["w"][0]["knowledge_origin"] = "Computed"
    metric = field_metrics(predicted, gold, {"w"}, counts)
    assert metric["numeric_unit_accuracy"] == {"correct": 1, "denominator": 2, "accuracy": 0.5}
    assert metric["knowledge_origin"]["macro_f1"] < 1
    assert metric["source_role"]["macro_f1"] == 1
    assert metric["extension_properties"]["macro_f1"] is None


def test_duplicate_anchor_cannot_receive_an_arbitrary_good_alignment():
    value, block = fixture()
    gold = {"w": atomic_claims(result_run(value, block))}
    predicted = deepcopy(gold)
    predicted["w"].append(deepcopy(predicted["w"][0]))
    metric = field_metrics(predicted, gold, {"w"}, counts)
    assert metric["ambiguous_alignment_slots"] and metric["numeric_unit_accuracy"]["accuracy"] < 1


def test_audit_is_source_config_bound_and_requires_all_predictions():
    value, block = fixture()
    claims = atomic_claims(result_run(value, block))
    output = {"manifest_sha256": "m", "config_sha256": "c", "claims_by_work": {"w": claims}}
    audit = {
        "status": "adjudicated",
        "manifest_sha256": "m",
        "config_sha256": "c",
        "annotators": ["Synthetic human A", "Synthetic human B"],
        "adjudicator": "Synthetic human C",
        "items": {},
    }
    assert (
        evidence_audit(output, audit, {"w"}, audit["annotators"], audit["adjudicator"])["status"]
        == "prediction_audit_incomplete"
    )
    audit["items"] = {
        digest(c): {"evidence_support": True, "locator_resolves": True, "severe_errors": []}
        for c in claims
    }
    assert (
        evidence_audit(output, audit, {"w"}, audit["annotators"], audit["adjudicator"])[
            "evidence_support_precision"
        ]
        == 1
    )
    audit["items"][digest(claims[0])]["severe_errors"] = ["wrong_sample_or_point"]
    assert (
        evidence_audit(output, audit, {"w"}, audit["annotators"], audit["adjudicator"])[
            "severe_error_count"
        ]
        == 1
    )
    audit["config_sha256"] = "wrong"
    assert (
        evidence_audit(output, audit, {"w"}, audit["annotators"], audit["adjudicator"])["status"]
        == "independent_prediction_audit_required"
    )


def test_null_recovery_only_counts_gold_confirmed_prior_nulls():
    value, block = fixture()
    gold = {"w": atomic_claims(result_run(value, block))}
    assert null_recovery(gold, gold, {"w"}, {}, tuple_key)["recall"] is None
    baseline = {"w": [tuple_key(c) for c in gold["w"]]}
    predicted = {"w": gold["w"][:1]}
    assert null_recovery(predicted, gold, {"w"}, baseline, tuple_key)["recall"] == 0.5
    with pytest.raises(ValueError, match="not_gold_confirmed"):
        null_recovery(predicted, gold, {"w"}, {"w": ["invented"]}, tuple_key)


def review_models():
    from dataclasses import asdict
    from ingestion.materials_v3.providers import MODEL, REVISION, ProviderConfig

    value, block = fixture()
    claims = atomic_claims(result_run(value, block))
    models = {}
    for name, model, revision in (
        ("local_mlx", MODEL, REVISION),
        ("gemini", "gemini-3.5-flash", None),
        ("openai", "gpt-6.1-sol", None),
    ):
        config = {
            "provider": asdict(ProviderConfig(name, model, revision)),
            "common_prompt": "synthetic-v1",
        }
        models[name] = {
            "provider": name,
            "configuration": config,
            "config_sha256": digest(config),
            "manifest_sha256": "synthetic-m",
            "claims_by_work": {"w": claims},
            "statistics_by_work": {"model_name": model},
        }
    return models


def test_blinded_packet_retains_prediction_ids_but_no_model_or_performance_metadata():
    from ingestion.materials_v3.contract import canonical
    from ingestion.materials_v3.review import blinded_review

    models = review_models()
    packet, mapping = blinded_review(models)
    encoded = canonical(packet).decode()
    assert all(
        word not in encoded
        for word in ("local_mlx", "gemini", "openai", "Qwen", "statistics", "config_sha256")
    )
    assert len(packet["models"]) == 3
    for label, model in packet["models"].items():
        origin = mapping["aliases"][label]["provider"]
        assert model["claims_by_work"] == models[origin]["claims_by_work"]
        assert set(model["prediction_audit"]["items"]) == {
            digest(c) for c in model["claims_by_work"]["w"]
        }
        assert model["prediction_audit"]["status"] == "unannotated"
    assert mapping["review_receipt_sha256"] == packet["receipt_sha256"]


def test_blinded_packet_refuses_claim_metadata_leakage_or_different_work_scopes():
    from ingestion.materials_v3.review import blinded_review

    models = review_models()
    # Give each provider its own copy before simulating a metadata leak.
    models = {name: deepcopy(out) for name, out in models.items()}
    models["local_mlx"]["claims_by_work"]["w"][0]["model_name"] = "Qwen"
    with pytest.raises(ValueError, match="unknown_metadata"):
        blinded_review(models)
    models = review_models()
    models["openai"]["claims_by_work"] = {"other": []}
    with pytest.raises(ValueError, match="work_scopes_differ"):
        blinded_review(models)
