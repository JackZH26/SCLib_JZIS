"""Offline scientific-evaluation integrity, never authenticated adjudication.

No provider, database or filesystem operation is performed. A self-consistent
portable object cannot authenticate its reviewer, originating roots, capture
rights, execution history or preregistration date. Those remain external gates.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from uuid import UUID, uuid5

from pydantic import ValidationError

from models.scientific_evaluation import ScientificEvaluationPackage

VERSION = "scientific-evaluation-audit/1.0.0"
HASH_PROFILE = "scientific-eval-json/1"
MAX_BYTES = 64 * 1024 * 1024
MAX_NODES = 500000
MAX_DEPTH = 32
_CITATION = re.compile(r"\[([0-9]{1,9})\]")


class ScientificEvaluationError(ValueError):
    """A static reason code, without source text, credentials or provider errors."""


def require(condition, code):
    if not condition:
        raise ScientificEvaluationError(code)


def canonical(value):
    """Canonical JSON is an integrity convention, not raw-file authentication."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    pending, nodes, string_bytes = [(value, 0)], 0, 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        require(nodes <= MAX_NODES and depth <= MAX_DEPTH, "json_resource_limit")
        if type(item) is dict:
            require(all(type(key) is str for key in item), "invalid_json_keys")
            require(nodes + len(pending) + 2 * len(item) <= MAX_NODES, "json_resource_limit")
            pending.extend((key, depth + 1) for key in item)
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            require(nodes + len(pending) + len(item) <= MAX_NODES, "json_resource_limit")
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            try:
                string_bytes += len(item.encode("utf-8"))
            except UnicodeError:
                raise ScientificEvaluationError("invalid_utf8") from None
            require(string_bytes <= MAX_BYTES, "json_byte_limit")
        elif type(item) is float:
            require(math.isfinite(item), "nonfinite_json_number")
        else:
            require(item is None or type(item) in {int, bool}, "invalid_json_value")
    try:
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ScientificEvaluationError("invalid_canonical_json") from None
    require(len(encoded) <= MAX_BYTES, "json_byte_limit")
    return encoded


def digest(kind, value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return hashlib.sha256(canonical([HASH_PROFILE, kind, value])).hexdigest()


def text_digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def observation_digest(observation):
    value = observation.model_dump(mode="json") if hasattr(observation, "model_dump") else dict(observation)
    # Reviews are append-only records about this observation, not its identity.
    return digest("observation", {key: value for key, value in value.items() if key not in {"judgments", "resolution"}})


def _unique(values, code):
    require(len(set(values)) == len(values), code)


def _references(values, known, code):
    require(all(value in known for value in values), code)


def _validate_corpus(package):
    from models.index_generations_v1 import PROFILE
    from services.index_generations import _resource, manifest_sha256
    from services.rag_evidence_contract import (
        NAMESPACE,
        PROJECTION_VERSION,
        extraction_projection,
        input_record_sha256,
    )
    from services.rag_evidence_contract import canonical as evidence_canonical

    corpus = package.corpus
    require(corpus.index_profile == PROFILE, "unsupported_index_profile")
    try:
        _resource(corpus.index_resource)
    except (ValueError, TypeError):
        raise ScientificEvaluationError("unsupported_index_resource") from None
    require(bool(corpus.sources), "missing_declared_corpus")
    _unique([source.id for source in corpus.sources], "duplicate_source_id")
    _unique([source.vector_id for source in corpus.sources], "duplicate_vector_id")
    _unique([result.id for result in corpus.results], "duplicate_result_id")
    sources = {source.id: source for source in corpus.sources}
    by_vector = {source.vector_id: source for source in corpus.sources}
    prefix = "ig62_" + UUID(corpus.generation.generation_id).hex + "_"
    revisions, work_bindings, root_bindings = {}, {}, {}
    for source in corpus.sources:
        evidence = source.evidence_provenance
        require(source.vector_id.startswith(prefix), "source_generation_mismatch")
        require(text_digest(source.text) == evidence["content_sha256"], "source_content_mismatch")
        require(evidence["chunk_kind"] != "legacy_unknown", "legacy_evidence_not_frozen")
        # Reject contradictory aliases of the very same retained revision. Do
        # not infer roots from identical boilerplate or merely similar formulas.
        revision = evidence["evidence_revision_id"]
        identity = (source.paper_id, source.source_snapshot_sha256, evidence["content_sha256"],
                    source.work_id, source.root_id, source.capture_sha256)
        require(revision not in revisions or revisions[revision] == identity, "conflicting_evidence_alias")
        revisions[revision] = identity
        require(source.paper_id not in work_bindings or work_bindings[source.paper_id] == source.work_id,
                "conflicting_work_binding")
        work_bindings[source.paper_id] = source.work_id
        occurrence = (source.paper_id, source.source_snapshot_sha256, evidence["content_sha256"],
                      canonical(evidence["source_locator"]))
        require(occurrence not in root_bindings or root_bindings[occurrence] == source.root_id,
                "conflicting_root_alias")
        root_bindings[occurrence] = source.root_id
    members = [{"vector_id": source.vector_id, "content_sha256": source.evidence_provenance["content_sha256"],
                "vector_sha256": source.vector_sha256} for source in corpus.sources]
    require(manifest_sha256(members) == corpus.generation.manifest_sha256, "incomplete_generation_manifest")
    parents = {}
    for result in corpus.results:
        binding = result.binding
        require(all(getattr(binding, name) == getattr(corpus.generation, name) for name in
                    ("generation_id", "activation_event_id", "manifest_sha256")), "result_generation_mismatch")
        require(binding.vector_id in by_vector, "result_source_missing")
        source = by_vector[binding.vector_id]
        evidence = source.evidence_provenance
        require(binding.paper_id == source.paper_id and evidence["chunk_kind"] == "derived_fact", "result_source_mismatch")
        require(all(getattr(binding, name) == evidence[name] for name in (
            "content_sha256", "evidence_revision_id", "evidence_record_sha256", "parent_result_revision_id", "parent_result_sha256")),
            "result_evidence_mismatch")
        require(result.input_record_sha256 == input_record_sha256(result.raw_record), "raw_record_mismatch")
        parent = {"paper_id": source.paper_id, "input_record_sha256": result.input_record_sha256,
            "extractor_version": evidence["extraction_version"], "projection_version": PROJECTION_VERSION,
            "projection_json": extraction_projection(result.raw_record),
            "source_snapshot_sha256": source.source_snapshot_sha256, "scientific_acceptance": False}
        expected_id = str(uuid5(NAMESPACE, "extraction:" + hashlib.sha256(evidence_canonical(parent)).hexdigest()))
        require(binding.parent_result_revision_id == expected_id, "raw_parent_identity_mismatch")
        parent_identity = (result.input_record_sha256, source.paper_id, source.source_snapshot_sha256, binding.parent_result_sha256)
        require(expected_id not in parents or parents[expected_id] == parent_identity, "conflicting_parent_alias")
        parents[expected_id] = parent_identity
    return sources, {result.id: result for result in corpus.results}


def _case_sources(case, results, sources):
    used = {identifier for condition in case.expected.conditions for identifier in condition.source_ids}
    used.update(identifier for claim in case.expected.claims for bundle in claim.evidence_alternatives for identifier in bundle)
    vector_sources = {source.vector_id: source.id for source in sources.values()}
    used.update(vector_sources[results[identifier].binding.vector_id] for identifier in case.expected.result_ids)
    return used


def _split_graph(package, sources, results):
    """Connected declared relationships, never proof of a complete root graph."""
    parent = {("case", case.id): ("case", case.id) for case in package.cases}
    parent.update({("source", identifier): ("source", identifier) for identifier in sources})
    def find(value):
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value
    def union(left, right):
        parent[find(right)] = find(left)
    memberships = {}
    missing_roots = set()
    # Build the complete declared source graph BEFORE attaching cases. An
    # unreferenced third source may bridge both cases through Work/root links.
    for identifier, source in sources.items():
        evidence = source.evidence_provenance
        keys = [("paper", source.paper_id), ("revision", evidence["evidence_revision_id"]),
                ("full_text", evidence["content_sha256"])]
        for kind, value in (("work", source.work_id), ("root", source.root_id),
                            ("capture", source.capture_sha256), ("capture_id", evidence["source_capture_id"]),
                            ("parent", evidence["parent_result_revision_id"])):
            if value is not None:
                keys.append((kind, value))
        for key in keys:
            if key in memberships:
                union(("source", identifier), memberships[key])
            else:
                memberships[key] = ("source", identifier)
    for case in package.cases:
        # Only NFC and whitespace for duplicate question detection; no isotope,
        # D/H, charge, phase or stoichiometry normalization is applied.
        keys = [("question_group", case.query_group_id),
                ("query", " ".join(unicodedata.normalize("NFC", case.query).split()))]
        for identifier in _case_sources(case, results, sources):
            source = sources[identifier]
            union(("case", case.id), ("source", identifier))
            if source.root_id is None:
                missing_roots.add(case.id)
        for key in keys:
            if key in memberships:
                union(("case", case.id), memberships[key])
            else:
                memberships[key] = ("case", case.id)
    groups = defaultdict(list)
    by_id = {case.id: case for case in package.cases}
    for identifier in by_id:
        groups[find(("case", identifier))].append(identifier)
    require(all(len({by_id[identifier].split for identifier in group}) == 1 for group in groups.values()), "split_component_overlap")
    return {"declared_component_count": len(groups), "cases_with_missing_root_links": len(missing_roots),
            "declared_split_disjoint": True, "root_graph_complete_authenticated": False}


def _case_reviews(package, case_hashes, protocol_hash, corpus_hash):
    reviews, resolutions = defaultdict(list), {}
    _unique([row.id for row in [*package.case_reviews, *package.case_resolutions]], "duplicate_review_id")
    for row in [*package.case_reviews, *package.case_resolutions]:
        require(row.case_id in case_hashes and row.case_sha256 == case_hashes[row.case_id], "review_case_binding_mismatch")
        require(row.protocol_sha256 == protocol_hash and row.corpus_sha256 == corpus_hash, "review_context_mismatch")
        require(row.submitted_at >= package.protocol.created_at, "review_precedes_protocol")
    for review in package.case_reviews:
        reviews[review.case_id].append(review)
    for resolution in package.case_resolutions:
        require(resolution.case_id not in resolutions, "multiple_case_resolutions")
        resolutions[resolution.case_id] = resolution
    decisions = {}
    for identifier in case_hashes:
        values = reviews[identifier]
        require(len(values) <= 2, "ambiguous_review_inventory")
        _unique([row.reviewer_id for row in values], "nonindependent_reviewer_alias")
        resolution = resolutions.get(identifier)
        if resolution:
            require(len(values) == 2 and set(resolution.review_ids) == {row.id for row in values}, "resolution_review_mismatch")
            require(resolution.resolver_id not in {row.reviewer_id for row in values}, "resolver_not_distinct")
            require(all(resolution.submitted_at >= row.submitted_at for row in values), "resolution_precedes_review")
            decisions[identifier] = resolution.decision
        elif len(values) < 2:
            decisions[identifier] = "unreviewed"
        elif values[0].decision == values[1].decision:
            decisions[identifier] = values[0].decision
        else:
            decisions[identifier] = "disputed"
    return decisions


def _labels(labels, observation, case, sources):
    _unique([claim.id for claim in labels.claims], "duplicate_output_claim")
    spans = sorted((claim.start, claim.end) for claim in labels.claims)
    require(all(left[1] <= right[0] for left, right in zip(spans, spans[1:])), "overlapping_output_claims")
    expected = {claim.id: claim for claim in case.expected.claims}
    for claim in labels.claims:
        require(claim.end <= len(observation.answer) and observation.answer[claim.start:claim.end].strip(), "invalid_claim_span")
        assertion = observation.answer[claim.start:claim.end]
        require(any(character.isalpha() for character in _CITATION.sub("", assertion)), "citation_only_claim_span")
        _references(claim.source_ids, sources, "unknown_judgment_source")
        _references(claim.expected_claim_ids, expected, "unknown_expected_claim")
        require(set(claim.source_ids) <= set(observation.selected_source_ids), "judgment_source_not_selected")
        require(all(index <= len(observation.selected_source_ids) for index in claim.citation_indices), "judgment_citation_out_of_range")
        citation_tokens = re.findall(r"\[([\d\s,;–-]+)\]", assertion)
        require(all(re.fullmatch(r"[1-9][0-9]?", token) for token in citation_tokens), "malformed_judged_citation")
        actual_indices = {int(token) for token in citation_tokens}
        require(set(claim.citation_indices) == actual_indices, "judgment_citation_inventory_mismatch")
        cited_sources = {observation.selected_source_ids[index - 1] for index in claim.citation_indices}
        require(set(claim.source_ids) == cited_sources, "judgment_source_citation_mismatch")
        if claim.status == "supported":
            require(bool(claim.source_ids), "unsupported_positive_label")
            require(all(sources[identifier].evidence_provenance["chunk_kind"] == "original_passage"
                and sources[identifier].evidence_provenance["permission_status"] != "restricted"
                and sources[identifier].evidence_provenance["currentness"] != "stale" for identifier in claim.source_ids),
                "nonoriginal_positive_support")
            require(all(any(set(bundle) <= set(claim.source_ids) for bundle in expected[identifier].evidence_alternatives)
                        for identifier in claim.expected_claim_ids), "incomplete_judged_support_bundle")
    return labels


def _output_review(observation, run, case, sources):
    values = observation.judgments
    expected_hash = observation_digest(observation)
    _unique([row.id for row in values], "duplicate_output_review")
    _unique([row.reviewer_id for row in values], "nonindependent_output_reviewers")
    for row in [*values, *([observation.resolution] if observation.resolution is not None else [])]:
        require(row.observation_sha256 == expected_hash, "output_review_binding_mismatch")
        require(row.submitted_at >= run.started_at, "output_review_precedes_run")
        _labels(row.labels, observation, case, sources)
    if observation.resolution is not None:
        resolution = observation.resolution
        require(len(values) == 2 and set(resolution.review_ids) == {row.id for row in values}, "output_resolution_review_mismatch")
        require(resolution.id not in {row.id for row in values} and resolution.reviewer_id not in {row.reviewer_id for row in values},
                "output_resolver_not_distinct")
        require(all(resolution.submitted_at >= row.submitted_at for row in values), "output_resolution_precedes_review")
        return resolution.labels
    if len(values) == 2 and canonical(values[0].labels) == canonical(values[1].labels):
        return values[0].labels
    return None


def _request(observation, run, case, sources):
    if observation.request_payload is None:
        return False  # Never rebuild an unavailable historical prompt from current code.
    require(observation.request_sha256 is not None, "request_digest_missing")
    body = observation.request_payload
    require(hashlib.sha256(canonical(body)).hexdigest() == observation.request_sha256, "request_digest_mismatch")
    # Only the existing fully specified text request can claim local payload
    # consistency. It does not authenticate a captured RPC or billing receipt.
    from services.rag_input_budget import INPUT_PROFILE, RagInputBudgetError, build_request
    try:
        prepared = build_request(model=body["model"], contents=body["contents"][0]["parts"][0]["text"],
            system_instruction=body["system_instruction"]["parts"][0]["text"],
            max_output_tokens=body["generation_config"]["max_output_tokens"], byte_limit=1024 * 1024)
        require(body["profile"] == INPUT_PROFILE and prepared.request_sha256 == observation.request_sha256,
                "unsupported_request_profile")
        require(run.model_requested == body["model"], "request_model_mismatch")
        prompt = body["contents"][0]["parts"][0]["text"]
        start, end = "<untrusted_sources_json>\n", "\n</untrusted_sources_json>\n\n<user_question>\n"
        require(prompt.startswith(start), "request_sources_missing")
        source_json, remainder = prompt[len(start):].split(end, 1)
        question, suffix = remainder.rsplit("\n</user_question>\n\n", 1)
        require(question == case.query and suffix == "Answer in markdown with inline [n] citations.", "request_question_mismatch")
        entries = json.loads(source_json, object_pairs_hook=_no_duplicate_pairs)
        require(type(entries) is list and len(entries) == len(observation.selected_source_ids), "request_source_inventory_mismatch")
        for index, (entry, identifier) in enumerate(zip(entries, observation.selected_source_ids, strict=True), 1):
            source = sources[identifier]
            require(type(entry) is dict and entry.get("index") == index and type(entry.get("index")) is int,
                    "request_citation_order_mismatch")
            require(set(entry) == {"index", "paper_id", "title", "authors", "year", "section", "excerpt",
                                  "material_evidence", "source_visibility", "evidence_provenance", "packing_info"},
                    "unsupported_request_source_profile")
            require(type(entry["title"]) is str and type(entry["authors"]) is str
                    and (entry["year"] is None or type(entry["year"]) is int)
                    and (entry["section"] is None or type(entry["section"]) is str)
                    and type(entry["material_evidence"]) is list and len(entry["material_evidence"]) <= 50
                    and all(type(row) is dict for row in entry["material_evidence"])
                    and type(entry["source_visibility"]) is dict, "invalid_request_source_metadata")
            require(entry.get("paper_id") == source.paper_id and entry.get("excerpt") == source.text,
                    "request_source_content_mismatch")
            require(entry.get("evidence_provenance") == source.evidence_provenance, "request_evidence_mismatch")
            if entry["packing_info"] is not None:
                _request_packing(entry["packing_info"], source, index)
    except ScientificEvaluationError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, RagInputBudgetError):
        raise ScientificEvaluationError("invalid_retained_request") from None
    return True


def _request_packing(value, source, index):
    from models.evidence_packing import EvidencePackingSelection, PackingCandidate
    from services.evidence_packing import packing_group_ids

    item = EvidencePackingSelection.model_validate(value, strict=True)
    require(item.position == index and item.chunk_id == source.vector_id
            and item.source_snapshot_sha256 == source.source_snapshot_sha256, "request_packing_source_mismatch")
    groups = packing_group_ids(PackingCandidate(chunk_id=source.vector_id, paper_id=source.paper_id,
        source_snapshot_sha256=source.source_snapshot_sha256, content_sha256=source.evidence_provenance["content_sha256"],
        chunk_kind=source.evidence_provenance["chunk_kind"], role_hint=item.role_hint,
        accepted_work_id=source.work_id if item.group_basis == "accepted_work_mapping" else None))
    require(all(getattr(item, name) == expected for name, expected in groups.items()), "request_packing_group_mismatch")


def _no_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _protocol(protocol):
    metrics = {"condition_match", "numerical_correct", "unit_correct", "refusal_correct",
               "claim_support_precision", "expected_claim_coverage", "mechanical_citation_precision"}
    metrics.update(f"{name}_at_{k}" for k in protocol.k_values
                   for name in ("evidence_bundle_completion", "declared_root_recall"))
    _unique([(gate.metric, gate.direction) for gate in protocol.gates], "duplicate_metric_gate")
    _unique([(quota.dimension, quota.key) for quota in protocol.strata], "duplicate_stratum_requirement")
    for gate in protocol.gates:
        require(gate.metric in metrics, "unsupported_metric_gate")
        require(0 <= gate.threshold <= 1, "ratio_gate_out_of_range")
    bounds = defaultdict(dict)
    for gate in protocol.gates:
        bounds[gate.metric][gate.direction] = gate.threshold
    require(all(row.get("min", 0) <= row.get("max", 1) for row in bounds.values()), "contradictory_metric_gates")


def _declared_review_kinds(package):
    """Reject known synthetic/real mixing; declarations still cannot prove identity."""
    kind = "synthetic" if package.purpose == "development_synthetic" else "declared_human"
    expected_execution = "synthetic" if kind == "synthetic" else "captured"
    rows = [*package.case_reviews, *package.case_resolutions]
    for run in package.runs:
        require(run.execution == expected_execution, "run_purpose_mismatch")
        for observation in run.observations:
            rows.extend(observation.judgments)
            if observation.resolution is not None:
                rows.append(observation.resolution)
    _unique([row.id for row in rows], "duplicate_global_review_id")
    require(all(getattr(row, "reviewer_kind", getattr(row, "resolver_kind", None)) == kind for row in rows),
            "review_purpose_mismatch")


def _validate(value):
    canonical(value)  # Bound resources before recursive model parsing.
    try:
        package = ScientificEvaluationPackage.model_validate(value.model_dump(mode="json")
            if isinstance(value, ScientificEvaluationPackage) else value, strict=True)
    except (ValidationError, ValueError, TypeError, RecursionError):
        raise ScientificEvaluationError("invalid_evaluation_schema") from None
    canonical(package)
    _protocol(package.protocol)
    _declared_review_kinds(package)
    sources, results = _validate_corpus(package)
    _unique([case.id for case in package.cases], "duplicate_case_id")
    require(bool(package.cases), "missing_case_inventory")
    protocol_hash, corpus_hash = digest("protocol", package.protocol), digest("corpus", package.corpus)
    dataset_hash = digest("dataset", [case.model_dump(mode="json") for case in package.cases])
    case_hashes = {case.id: digest("case", case) for case in package.cases}
    by_case = {case.id: case for case in package.cases}
    for case in package.cases:
        _unique([claim.id for claim in case.expected.claims], "duplicate_expected_claim")
        _references(case.expected.result_ids, results, "unknown_expected_result")
        for condition in case.expected.conditions:
            _references(condition.source_ids, sources, "unknown_condition_source")
        for claim in case.expected.claims:
            for bundle in claim.evidence_alternatives:
                _references(bundle, sources, "unknown_expected_source")
                require(all(sources[identifier].evidence_provenance["chunk_kind"] == "original_passage" for identifier in bundle),
                        "derived_extraction_is_not_original_support")
        # Multiple renderings of one parent are not multiple expected results.
        _unique([results[identifier].binding.parent_result_revision_id for identifier in case.expected.result_ids],
                "duplicate_expected_parent")
    graph = _split_graph(package, sources, results)
    decisions = _case_reviews(package, case_hashes, protocol_hash, corpus_hash)
    _unique([run.id for run in package.runs], "duplicate_run_id")
    _unique([run.arm for run in package.runs], "duplicate_run_arm")
    output_labels, retained_payloads = {}, 0
    for run in package.runs:
        require(run.protocol_sha256 == protocol_hash and run.corpus_sha256 == corpus_hash and run.dataset_sha256 == dataset_hash,
                "run_frozen_objects_mismatch")
        require(run.config_sha256 == digest("run_config", run.config), "run_config_mismatch")
        require(run.started_at >= package.protocol.created_at, "run_precedes_protocol")
        require(package.purpose != "development_synthetic" or run.execution == "synthetic", "synthetic_run_mislabeled")
        _unique([row.case_id for row in run.observations], "duplicate_run_case")
        require({row.case_id for row in run.observations} == set(by_case), "incomplete_run_inventory")
        labels = {}
        for observation in run.observations:
            case = by_case[observation.case_id]
            require(observation.case_sha256 == case_hashes[case.id], "observation_case_mismatch")
            require(observation.answer_sha256 == text_digest(observation.answer), "answer_content_mismatch")
            _references(observation.retrieved_source_ids, sources, "unknown_retrieved_source")
            _references(observation.selected_source_ids, sources, "unknown_selected_source")
            _references(observation.result_ids, results, "unknown_observed_result")
            require(set(observation.selected_source_ids) <= set(observation.retrieved_source_ids), "selected_source_not_retrieved")
            _unique([results[identifier].binding.parent_result_revision_id for identifier in observation.result_ids], "duplicate_observed_parent")
            if observation.status == "not_run":
                require(not observation.answer and not observation.retrieved_source_ids and not observation.selected_source_ids
                    and not observation.result_ids and observation.request_payload is None and observation.request_sha256 is None
                    and all(getattr(observation, name) is None for name in ("latency_ms", "input_tokens", "total_tokens", "cost_usd", "provider_fallback")),
                    "not_run_has_observations")
            if observation.status != "completed":
                require(observation.answer_mode == "unavailable" and not observation.result_ids, "unavailable_has_completed_results")
            else:
                require(observation.answer_mode != "unavailable", "completed_mode_unavailable")
            labels[case.id] = _output_review(observation, run, case, sources)
            retained_payloads += int(_request(observation, run, case, sources))
        output_labels[run.id] = labels
    audit = {"version": VERSION, "status": "structurally_consistent", "purpose": package.purpose,
        "integrity_scope": "declared_portable_objects_only", "hash_profile": HASH_PROFILE,
        "bindings": {"protocol_sha256": protocol_hash, "corpus_sha256": corpus_hash, "dataset_sha256": dataset_hash},
        "counts": {"cases": len(package.cases), "sources": len(sources), "results": len(results), "runs": len(package.runs),
                   "case_reviews": len(package.case_reviews), "case_resolutions": len(package.case_resolutions),
                   "retained_request_payloads": retained_payloads},
        "declared_case_decisions": dict(sorted(Counter(decisions.values()).items())), "split_audit": graph,
        "reviewer_authority_authenticated": False, "source_roots_authenticated": False,
        "catalogue_bindings_authenticated": False, "execution_authenticated": False, "preregistration_authenticated": False,
        "scientific_acceptance": False, "release_authorized": False, "ann_replay_available": False,
        "release_blockers": ["reviewer_authority_unverified", "original_roots_unverified", "capture_permissions_unverified",
                             "preregistration_unverified", "execution_receipts_unverified"]}
    if package.purpose == "development_synthetic":
        audit["release_blockers"].append("synthetic_development_only")
    if len(package.cases) < package.protocol.target_question_count:
        audit["release_blockers"].append("target_coverage_not_met")
    if not package.protocol.gates:
        audit["release_blockers"].append("release_thresholds_not_declared")
    if any(decision != "accept" for decision in decisions.values()):
        audit["release_blockers"].append("case_adjudication_incomplete")
    return package, audit, decisions, output_labels


def validate_package(value):
    return _validate(value)[1]


def compare_package(value):
    package, audit, decisions, output_labels = _validate(value)
    require(len(package.runs) == 2 and {run.arm for run in package.runs} == {"baseline", "candidate"}, "paired_runs_required")
    from services.scientific_evaluation_metrics import compute_metrics
    comparison = compute_metrics(package, case_decisions=decisions, output_labels=output_labels)
    candidate = next(run for run in package.runs if run.arm == "candidate")
    metrics = comparison["arms"][candidate.id]["splits"]["held_out"]["metrics"]
    checks = []
    for gate in package.protocol.gates:
        metric = metrics[gate.metric]
        # The denominator may count claims or roots; it must not inflate min_n.
        eligible = metric["scored_cases"] >= gate.min_n and metric["value"] is not None and metric["missing"] == 0
        meets = None if not eligible else (metric["value"] >= gate.threshold if gate.direction == "min"
                                          else metric["value"] <= gate.threshold)
        checks.append({**gate.model_dump(mode="json"), "scored_cases": metric["scored_cases"],
                       "missing_cases": metric["missing"], "value": metric["value"],
                       "declared_threshold_met": meets})
    if not checks or any(check["declared_threshold_met"] is not True for check in checks):
        audit["release_blockers"].append("held_out_declared_thresholds_unmet_or_unmeasured")
    if any(not quota["declared_quota_met"] for quota in comparison["coverage"]["quotas"]):
        audit["release_blockers"].append("declared_stratum_coverage_unmet")
    return {**audit, "comparison": comparison,
            "declared_threshold_checks": {"arm": "candidate", "split": "held_out", "checks": checks,
                "min_n_unit": "scored_case_not_independent_experiment", "preregistration_authenticated": False},
            "comparison_scope": "captured_declared_judgments_not_authenticated_scientific_benchmark"}
