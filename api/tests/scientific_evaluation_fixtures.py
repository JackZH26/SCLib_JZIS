"""Self-consistent SYNTHETIC portable evaluation; no real sources or review.

Every portable digest, complete declared manifest and extraction parent UUID is
computed. Record/capture hashes describe synthetic fixture bytes, not an actual
SQL ledger, PDF, authenticated person, provider call or approved scientific root.
No provider, database, filesystem or network operation is performed.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

from models.index_generations_v1 import PROFILE
from models.scientific_evaluation import ScientificEvaluationPackage
from services.embedding_contract import vector_sha256
from services.index_generations import _resource, manifest_sha256, vector_id_for
from services.rag_evidence_contract import build_revision_rows, canonical, input_record_sha256
from services.scientific_evaluation import digest, observation_digest, text_digest

PROTOCOL_AT = "2026-09-08T00:00:00.000000Z"
REVIEW_AT = "2026-09-08T00:01:00.000000Z"
RUN_AT = "2026-09-08T00:02:00.000000Z"
OUTPUT_AT = "2026-09-08T00:03:00.000000Z"
RESOLUTION_AT = "2026-09-08T00:04:00.000000Z"
MODEL = "gemini-3.5-flash"


def uid(label):
    return str(uuid5(NAMESPACE_URL, "sclib-synthetic-evaluation-fixture:" + label))


def raw_record():
    return {"formula": "Nb", "tc_kelvin": "9 K", "pressure_condition": "ambient pressure",
        "knowledge_origin": "Observed", "source_role": "primary", "result_status": "positive_reported",
        "measurement_method": "resistivity", "sample_label": "Synthetic specimen A"}


def make_source(identifier, paper="a", *, derived=False):
    text = {"a-methods": "Synthetic specimen A was measured using four-probe resistivity.",
            "a-results": "Synthetic specimen A displayed a resistive transition at 9 K under explicitly ambient conditions.",
            "a-derived": "Synthetic retrieval-only Fact: Nb, Tc 9 K, ambient pressure, Observed, primary.",
            "b-original": "The synthetic pairing model couples electrons through a lattice vibration."}.get(
                identifier, "Synthetic unrelated retained passage " + identifier + ".")
    snapshot = text_digest("Synthetic catalogue snapshot " + paper)
    candidate = {"version": "rag-evidence/1.0.0", "chunk_kind": "derived_fact" if derived else "original_passage",
        "parent_record": raw_record() if derived else None, "extraction_version": "synthetic-extractor/1" if derived else None,
        "rendering_version": "synthetic-fact-renderer/1" if derived else "synthetic-chunker/1",
        "source_capture_id": uid("capture-" + paper), "source_locator": {"section": identifier, "char_start": 0, "char_end": len(text)},
        "unresolved_reason": "missing_original_source" if derived else "original_binding_unreviewed", "permission_status": "unresolved"}
    rows = build_revision_rows(paper_id="synthetic:" + paper, chunk_id=identifier, chunk_text=text,
        chunk_binding_sha256=text_digest("Synthetic chunk binding " + identifier), source_snapshot_sha256=snapshot,
        candidate=candidate)
    parent, evidence = rows["extraction"], rows["evidence"]
    parent_hash = hashlib.sha256(canonical(parent)).hexdigest() if parent else None
    descriptor = {"version": "rag-evidence/1.0.0", "chunk_kind": candidate["chunk_kind"],
        "evidence_revision_id": evidence["id"], "evidence_record_sha256": hashlib.sha256(canonical(evidence)).hexdigest(),
        "content_sha256": evidence["content_sha256"], "parent_result_revision_id": parent["id"] if parent else None,
        "parent_result_sha256": parent_hash, "extraction_version": candidate["extraction_version"],
        "rendering_version": candidate["rendering_version"], "source_capture_id": candidate["source_capture_id"],
        "source_locator": candidate["source_locator"], "root_status": "unresolved", "permission_status": "unresolved",
        "currentness": "current", "warning_codes": ["original_root_unresolved"], "support_eligible": False,
        "independent_evidence": False, "scientific_acceptance": False}
    return {"id": identifier, "paper_id": "synthetic:" + paper,
        "vector_id": vector_id_for(uid("generation"), text_digest("Synthetic chunk revision " + identifier)),
        "vector_sha256": vector_sha256([1.0] + [float(ord(identifier[0]))] + [0.0] * 766),
        "source_snapshot_sha256": snapshot, "text": text, "evidence_provenance": descriptor,
        "work_id": uid("work-" + paper), "root_id": "synthetic-root-" + paper,
        "capture_sha256": text_digest("Synthetic capture bytes " + paper)}


def reseal(value):
    """Return a new normalized test artifact with all dependent package hashes.

    Does not repair evidence/content/parent identities, add missing cases/runs,
    change judgments, or authenticate the explicitly declared fixture records.
    """
    value = deepcopy(value)
    sources = value["corpus"]["sources"]
    manifest = manifest_sha256([{"vector_id": source["vector_id"], "content_sha256": source["evidence_provenance"]["content_sha256"],
        "vector_sha256": source["vector_sha256"]} for source in sources])
    value["corpus"]["generation"]["manifest_sha256"] = manifest
    for result in value["corpus"].get("results", []):
        result["binding"]["manifest_sha256"] = manifest
    value = ScientificEvaluationPackage.model_validate(value).model_dump(mode="json")
    protocol_hash, corpus_hash = digest("protocol", value["protocol"]), digest("corpus", value["corpus"])
    dataset_hash = digest("dataset", value["cases"])
    case_hashes = {case["id"]: digest("case", case) for case in value["cases"]}
    for row in value["case_reviews"] + value["case_resolutions"]:
        row.update(case_sha256=case_hashes.get(row["case_id"], row["case_sha256"]),
                   protocol_sha256=protocol_hash, corpus_sha256=corpus_hash)
    for run in value["runs"]:
        run.update(protocol_sha256=protocol_hash, corpus_sha256=corpus_hash, dataset_sha256=dataset_hash,
                   config_sha256=digest("run_config", run["config"]))
        for observation in run["observations"]:
            observation.update(case_sha256=case_hashes.get(observation["case_id"], observation["case_sha256"]),
                               answer_sha256=text_digest(observation["answer"]))
            if observation["request_payload"] is not None:
                from services.scientific_evaluation import canonical as evaluation_canonical
                observation["request_sha256"] = hashlib.sha256(evaluation_canonical(observation["request_payload"])).hexdigest()
            observation_hash = observation_digest(observation)
            for review in observation["judgments"] + ([observation["resolution"]] if observation["resolution"] else []):
                review["observation_sha256"] = observation_hash
    return value


def _labels(answer, sources, expected_id=None, *, numerical=False):
    return {"condition_match": "correct", "numerical_correct": "correct" if numerical else "not_applicable",
        "unit_correct": "correct" if numerical else "not_applicable", "refusal_correct": "not_applicable",
        "answer_claims_complete": True, "claims": ([{"id": "answer-claim", "start": 0, "end": len(answer),
            "source_ids": sources, "citation_indices": list(range(1, len(sources) + 1)), "status": "supported",
            "expected_claim_ids": [expected_id]}] if expected_id else [])}


def make_package(*, runs=True):
    placeholder = text_digest("unsealed synthetic fixture placeholder; replaced by reseal")
    sources = [make_source("a-methods"), make_source("a-results"), make_source("a-derived", derived=True), make_source("b-original", "b")]
    evidence = sources[2]["evidence_provenance"]
    result = {"id": "result-a", "binding": {"paper_id": sources[2]["paper_id"], "vector_id": sources[2]["vector_id"],
        "generation_id": uid("generation"), "activation_event_id": uid("activation"), "manifest_sha256": placeholder,
        **{key: evidence[key] for key in ("content_sha256", "evidence_revision_id", "evidence_record_sha256",
            "parent_result_revision_id", "parent_result_sha256")}}, "raw_record": raw_record(), "input_record_sha256": input_record_sha256(raw_record())}
    cases = [
        {"id": "case-methods", "query_group_id": "query-a-methods", "split": "development", "query": "Explain the synthetic superconductivity evidence.",
            "language": "en", "task": "mechanism", "families": ["conventional"], "tags": ["synthetic", "complementary"],
            "expected": {"route": "mechanism", "acceptable_modes": ["limited_synthesis"], "claims": [{"id": "claim-a",
                "text": "Synthetic resistive evidence requires both method and result.", "evidence_alternatives": [["a-methods", "a-results"]]}]}},
        {"id": "case-numerical", "query_group_id": "query-a-numerical", "split": "development", "query": "Nb 的临界温度是多少？",
            "language": "zh", "task": "numerical", "families": ["conventional"], "tags": ["synthetic", "units"],
            "expected": {"route": "numerical", "acceptable_modes": ["structured_results"], "conditions": [{"field": "pressure",
                "raw_expectation": "Explicit ambient report, not inferred from missing pressure.", "source_ids": ["a-derived"]}], "result_ids": ["result-a"]}},
        {"id": "case-pairing", "query_group_id": "query-b-pairing", "split": "held_out", "query": "Explain the synthetic pairing model.",
            "language": "en", "task": "mechanism", "families": ["conventional"], "tags": ["synthetic"],
            "expected": {"route": "mechanism", "acceptable_modes": ["limited_synthesis"], "claims": [{"id": "claim-b",
                "text": "The synthetic model uses lattice vibration coupling.", "evidence_alternatives": [["b-original"]]}]}}]
    package = {"purpose": "development_synthetic", "protocol": {"id": "synthetic-protocol", "created_at": PROTOCOL_AT,
        "scope_note": "Synthetic pipeline regression only; not real gold, actual review or production observations.",
        "k_values": [1, 3, 5], "strata": [{"dimension": "language", "key": "zh", "min_n": 1}], "gates": []},
        "corpus": {"id": "synthetic-corpus", "generation": {"mode": "generation_snapshot", "generation_id": uid("generation"),
            "activation_event_id": uid("activation"), "manifest_sha256": placeholder}, "index_profile": deepcopy(PROFILE),
            "index_resource": _resource({"backend": "disposable", "project": "synthetic-evaluation", "location": "local",
                "index_resource": "synthetic-index", "endpoint_resource": "synthetic-endpoint", "deployed_index_id": "synthetic-deployment",
                "distance_measure": "COSINE_DISTANCE", "feature_norm": "NONE"}), "sources": sources, "results": [result]},
        "cases": cases, "case_reviews": [], "case_resolutions": [], "runs": []}
    for case in cases:
        for number in (1, 2):
            package["case_reviews"].append({"id": f"{case['id']}-review-{number}", "case_id": case["id"], "case_sha256": placeholder,
                "protocol_sha256": placeholder, "corpus_sha256": placeholder, "reviewer_id": f"synthetic-case-reviewer-{number}",
                "reviewer_kind": "synthetic", "submitted_at": REVIEW_AT, "decision": "accept", "rationale": "Synthetic fixture decision only."})
    if runs:
        for arm in ("baseline", "candidate"):
            observations = []
            for case in cases:
                numerical = case["id"] == "case-numerical"
                selected = ["a-derived"] if numerical else ["a-methods", "a-results"] if case["id"] == "case-methods" else ["b-original"]
                answer = ("Synthetic source-linked extraction rows only." if numerical else
                    "The synthetic resistive evidence uses the stated method and result [1] [2]." if case["id"] == "case-methods" else
                    "The synthetic model invokes lattice vibration coupling [1].")
                labels = _labels(answer, selected, None if numerical else case["expected"]["claims"][0]["id"], numerical=numerical)
                judgments = [{"id": f"{arm}-{case['id']}-output-review-{number}", "reviewer_id": f"synthetic-output-reviewer-{number}",
                    "reviewer_kind": "synthetic", "observation_sha256": placeholder, "submitted_at": OUTPUT_AT,
                    "rationale": "Synthetic output judgment; not an actual scientific adjudication.", "labels": deepcopy(labels)} for number in (1, 2)]
                observations.append({"case_id": case["id"], "case_sha256": placeholder, "status": "completed",
                    "retrieved_source_ids": selected, "selected_source_ids": selected, "result_ids": ["result-a"] if numerical else [],
                    "answer": answer, "answer_mode": "structured_results" if numerical else "limited_synthesis", "answer_sha256": text_digest(answer),
                    "latency_ms": 10.0, "input_tokens": 0 if numerical else 100, "total_tokens": 0 if numerical else 130,
                    "cost_usd": None, "provider_fallback": False, "judgments": judgments})
            package["runs"].append({"id": "run-" + arm, "arm": arm, "execution": "synthetic", "protocol_sha256": placeholder,
                "corpus_sha256": placeholder, "dataset_sha256": placeholder, "code_revision": hashlib.sha1(b"synthetic fixture code").hexdigest(),
                "config": {"fixture": "scientific-evaluation-fixture/1", "arm": arm}, "config_sha256": placeholder,
                "lock_sha256": text_digest("Synthetic lock artifact"), "prompt_version": "synthetic/1", "model_requested": MODEL,
                "model_observed": None, "policy_versions": {"result": "scientific-query-result/1.0.0"}, "started_at": RUN_AT,
                "observations": observations})
    return reseal(package)
