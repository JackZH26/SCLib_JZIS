"""Blinded source-bound tuple comparison; model agreement is never gold."""

from __future__ import annotations

import random
from collections import Counter, defaultdict

from .contract import digest
from .manifest import source_captures, validate_manifest
from .evaluation_gates import evidence_audit, field_metrics, null_recovery
from .providers import ProviderConfig, common_configuration_hash

CRITICAL_FIELDS = (
    "material",
    "sample",
    "state",
    "point",
    "property",
    "criterion",
    "quantity",
    "method",
    "knowledge_origin",
    "source_role",
)


def tuple_key(claim):
    missing = set(CRITICAL_FIELDS) - set(claim)
    if missing:
        raise ValueError("evaluation_tuple_missing_fields:" + ",".join(sorted(missing)))

    def canonical_numbers(value):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, dict):
            return {k: canonical_numbers(v) for k, v in value.items()}
        if isinstance(value, list):
            return [canonical_numbers(v) for v in value]
        return value

    return digest(canonical_numbers({k: claim[k] for k in CRITICAL_FIELDS}))


def counts(predicted, gold):
    p, g = Counter(map(tuple_key, predicted)), Counter(map(tuple_key, gold))
    tp = sum((p & g).values())
    fp, fn = sum(p.values()) - tp, sum(g.values()) - tp
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def paired_bootstrap(local, reference, gold, papers, *, iterations=5000, seed=20261010):
    """Resample work/data-dependency groups, keeping all claims in each cluster."""
    groups = defaultdict(list)
    for paper in papers:
        groups[paper["study_dependency_group"]].append(paper["work_id"])
    if len(groups) < 2:
        return {"status": "insufficient_clusters", "lower": None, "upper": None}
    clusters, rng, differences = list(groups.values()), random.Random(seed), []
    for _ in range(iterations):
        ids = [work for cluster in rng.choices(clusters, k=len(clusters)) for work in cluster]
        ll = counts(
            [c for w in ids for c in local.get(w, [])], [c for w in ids for c in gold.get(w, [])]
        )["f1"]
        rr = counts(
            [c for w in ids for c in reference.get(w, [])],
            [c for w in ids for c in gold.get(w, [])],
        )["f1"]
        if ll is not None and rr is not None:
            differences.append(ll - rr)
    if not differences:
        return {"status": "insufficient_denominator", "lower": None, "upper": None}
    differences.sort()
    lower, upper = (
        differences[int(0.025 * (len(differences) - 1))],
        differences[int(0.975 * (len(differences) - 1))],
    )
    return {
        "status": "pass" if lower >= -0.02 else "not_demonstrated",
        "lower": lower,
        "upper": upper,
        "confidence_level": 0.95,
        "clusters": len(groups),
        "iterations": len(differences),
        "seed": seed,
    }


def evaluate(models, gold_package, manifest):
    annotators = gold_package.get("annotators", [])
    if (
        gold_package.get("status") != "adjudicated"
        or len(annotators) != 2
        or any(not isinstance(a, str) or not a.strip() for a in annotators)
        or len(set(annotators)) != 2
        or not isinstance(gold_package.get("adjudicator"), str)
        or not gold_package["adjudicator"].strip()
    ):
        raise ValueError("independent_adjudicated_gold_required")
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    if (
        manifest.get("status") != "frozen"
        or manifest.get("manifest_sha256") != digest(body)
        or validate_manifest(manifest, freeze=True)
    ):
        raise ValueError("evaluation_requires_frozen_manifest")
    if gold_package.get("manifest_sha256") != manifest["manifest_sha256"]:
        raise ValueError("gold_manifest_hash_mismatch")
    papers = [p for p in manifest["papers"] if p["split"] == "blind_test"]
    expected = {p["work_id"] for p in papers}
    gold = gold_package["claims_by_work"]
    if not expected <= set(gold):
        raise ValueError("gold_missing_blind_works")
    if set(models) != {"local_mlx", "gemini", "openai"}:
        raise ValueError("three_model_comparison_required")
    common_configurations = set()
    for name, output in models.items():
        config = output.get("configuration")
        if (
            not isinstance(config, dict)
            or digest(config) != output.get("config_sha256")
            or output.get("provider") != name
            or config.get("provider", {}).get("provider") != name
        ):
            raise ValueError("comparison_provider_configuration_unbound")
        try:
            ProviderConfig(**config["provider"])
        except (TypeError, ValueError):
            raise ValueError("comparison_provider_configuration_invalid") from None
        common_configurations.add(common_configuration_hash(config))
        if (
            not expected <= set(output["claims_by_work"])
            or output.get("manifest_sha256") != manifest["manifest_sha256"]
        ):
            raise ValueError("comparison_missing_work_or_input_hash_mismatch")
        if not expected <= set(output.get("coverage_by_work", {})):
            raise ValueError("comparison_missing_coverage_receipts")
    if len(common_configurations) != 1:
        raise ValueError("comparison_semantic_prompt_schema_code_or_budget_differs")
    report = {
        "version": "materials-ner-evaluation/1",
        "manifest_sha256": manifest["manifest_sha256"],
        "evaluation_split": "blind_test",
        "blind_works": len(papers),
        "models": {},
        "quality_acceptance": "not_fully_assessed",
    }
    for name, output in models.items():
        predicted = output["claims_by_work"]
        metric = counts(
            [c for w in expected for c in predicted[w]], [c for w in expected for c in gold[w]]
        )
        metric["by_family"] = {}
        for family in sorted({p["family"] for p in papers}):
            ids = [p["work_id"] for p in papers if p["family"] == family]
            metric["by_family"][family] = counts(
                [c for w in ids for c in predicted[w]], [c for w in ids for c in gold[w]]
            )
        metric["core_thresholds_met"] = (
            metric["precision"] is not None
            and metric["precision"] >= 0.98
            and metric["recall"] is not None
            and metric["recall"] >= 0.95
            and all(
                m["recall"] is not None and m["recall"] >= 0.9 for m in metric["by_family"].values()
            )
        )
        metric["failed_or_incomplete_works"] = sorted(
            w for w in expected if not output["coverage_by_work"][w].get("machine_text_complete")
        )
        metric["end_to_end_incomplete_works"] = sorted(
            w for w in expected if not output["coverage_by_work"][w].get("end_to_end_complete")
        )
        metric["fields"] = field_metrics(predicted, gold, expected, counts)
        metric["evidence_audit"] = evidence_audit(
            output,
            gold_package.get("prediction_audits", {}).get(name),
            expected,
            annotators,
            gold_package["adjudicator"],
        )
        metric["null_recovery"] = null_recovery(
            predicted,
            gold,
            expected,
            gold_package.get("baseline_recoverable_claim_ids_by_work"),
            tuple_key,
        )
        metric["by_challenge"] = {}
        for tag in sorted({tag for p in papers for tag in p.get("verified_case_tags", [])}):
            ids = [p["work_id"] for p in papers if tag in p.get("verified_case_tags", [])]
            metric["by_challenge"][tag] = counts(
                [c for w in ids for c in predicted[w]], [c for w in ids for c in gold[w]]
            )
        report["models"][name] = metric
    local = models["local_mlx"]["claims_by_work"]
    report["paired_noninferiority"] = {
        name: paired_bootstrap(local, models[name]["claims_by_work"], gold, papers)
        for name in ("gemini", "openai")
    }
    local_metric = report["models"]["local_mlx"]
    fields, audit = local_metric["fields"], local_metric["evidence_audit"]
    gates = {
        "core_tuples": local_metric["core_thresholds_met"],
        "numeric_unit_accuracy": fields["numeric_unit_accuracy"]["accuracy"],
        "knowledge_origin_macro_f1": fields["knowledge_origin"]["macro_f1"],
        "source_role_macro_f1": fields["source_role"]["macro_f1"],
        "extension_macro_f1": fields["extension_properties"]["macro_f1"],
        "evidence_support": audit.get("evidence_support_precision"),
        "locator_resolves": audit.get("locator_resolves_rate"),
        "severe_errors": audit.get("severe_error_count"),
        "null_recovery": local_metric["null_recovery"]["recall"],
    }
    thresholds = {
        "numeric_unit_accuracy": 0.99,
        "knowledge_origin_macro_f1": 0.98,
        "source_role_macro_f1": 0.98,
        "extension_macro_f1": 0.9,
        "evidence_support": 0.98,
        "locator_resolves": 1.0,
        "null_recovery": 0.95,
    }
    passed = local_metric["core_thresholds_met"] and gates["severe_errors"] == 0
    passed = passed and all(
        gates[k] is not None and gates[k] >= value for k, value in thresholds.items()
    )
    passed = passed and all(m["status"] == "pass" for m in report["paired_noninferiority"].values())
    passed = (
        passed
        and not local_metric["failed_or_incomplete_works"]
        and not local_metric["end_to_end_incomplete_works"]
    )
    report["quality_gate_values"] = gates
    report["unassessed_gates"] = [k for k, value in gates.items() if value is None]
    report["operational_acceptance"] = "node_soak_and_real_runtime_receipts_required_separately"
    report["quality_acceptance"] = (
        "passed"
        if passed
        else "not_fully_assessed"
        if report["unassessed_gates"]
        else "not_demonstrated"
    )
    return report


def blank_annotation(manifest, annotator_slot):
    return {
        "version": "materials-ner-gold/1",
        "manifest_sha256": manifest["manifest_sha256"],
        "annotator_slot": annotator_slot,
        "annotator_identity": None,
        "status": "unannotated",
        "claims_by_work": {p["work_id"]: None for p in manifest["papers"]},
        "sources_by_work": {
            p["work_id"]: [
                {
                    k: c.get(k)
                    for k in (
                        "capture_kind",
                        "source_version",
                        "source_url",
                        "source_sha256",
                        "content_manifest_sha256",
                        "source_format",
                    )
                }
                for c in source_captures(p)
            ]
            for p in manifest["papers"]
        },
        "adjudication": None,
    }
