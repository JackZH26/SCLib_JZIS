"""Read actual retained chunks to prepare private pending literal packages."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import UTC, datetime
from uuid import uuid4

from models.db import Chunk, Material, Paper
from services import material_enrichment as enrichment
from services import material_enrichment_read as recovery
from services import material_field_case_contract_v1_1 as case_contract
from services import material_field_cases as cases
from services import source_expression_contract_v2_1 as expression_contract
from services.claim_support import is_derived_source_hint
from services.material_literal_field_contract import FIELDS, PROFILE
from services.material_source_scope import current_visibility_allows_view
from services.material_visibility import normalize_source_status
from services.material_visibility_adapter import material_view
from services.rag_evidence import resolve_chunk_evidence
from services.research_release_manifest import canonical, digest
from services.source_lifecycle import resolve_paper_lifecycle
from services.source_lifecycle_status import lifecycle_review_required
from services.source_property_pending import SourcePropertyConflict, checksum, reader, require

VERSION = "material-literal-field-prepare/1.0.0"
REQUEST_KEYS = {"version", "material_id", "target", "candidate_id", "extractor_version", "chunk_id",
                "source_content_sha256", "retained_result_id", "retained_record_sha256"}


def validate_request(request):
    cases.contract.closed(request, REQUEST_KEYS)
    require(request["version"] == VERSION and request["extractor_version"] == enrichment.EXTRACTOR_VERSION,
            "literal_prepare_version_required")
    cases.contract.bounded_text(request["material_id"], 100)
    cases.contract.bounded_text(request["chunk_id"], 200)
    cases.contract.bounded_text(request["retained_result_id"], 160)
    require(type(request["candidate_id"]) is str and re.fullmatch(r"enrichment:[a-f0-9]{64}", request["candidate_id"]) is not None,
            "literal_prepare_candidate_pin")
    checksum(request["source_content_sha256"])
    checksum(request["retained_record_sha256"])
    cases.contract.selector(request["target"])
    require(request["target"]["material_id"] == request["material_id"]
            and request["target"]["kind"] == "retained_result", "literal_prepare_retained_target_required")
    return request


def _span(text, start, end):
    return {"start": start, "end": end, "sha256": hashlib.sha256(text[start:end].encode()).hexdigest()}


def _candidate_span(text, selected):
    require(type(selected) is dict and set(selected) == {"char_start", "char_end", "text_sha256"},
            "literal_prepare_original_span_required")
    start, end = selected["char_start"], selected["char_end"]
    require(type(start) is int and type(end) is int and 0 <= start < end <= len(text),
            "literal_prepare_original_span_required")
    span = _span(text, start, end)
    require(span["sha256"] == selected["text_sha256"], "literal_prepare_span_changed")
    return span


def package_from_candidate(candidate, *, formula, source_text, source_metadata):
    """Only server-reread candidate/source inputs. Never accept browser JSON."""
    enrichment.validate_candidate_identity(candidate)
    require(candidate["field"] in FIELDS and candidate["quantity"] is None
            and candidate["subject"]["identity_basis"] == "exact_formula_local", "literal_prepare_literal_candidate_required")
    require(hashlib.sha256(source_text.encode()).hexdigest() == candidate["source"]["content_sha256"],
            "literal_prepare_source_changed")
    literal = candidate["source_value"]
    value = _candidate_span(source_text, literal["value_span"])
    unit = _candidate_span(source_text, literal["unit_span"]) if literal["unit_span"] else None
    cue = _candidate_span(source_text, literal["cue_span"])
    windows = [(a, z, text) for a, z, text in enrichment._segments(source_text)
               if a <= cue["start"] and value["end"] <= z and (unit is None or unit["end"] <= z)
               and hashlib.sha256(text.encode()).hexdigest() == candidate["evidence_text_sha256"]]
    require(len(windows) == 1, "literal_prepare_original_window_required")
    left, right, window = windows[0]
    flat, offsets = enrichment._flat(window)
    matches = list(re.finditer(enrichment._formula_pattern(enrichment.normalize_formula(formula)), flat))
    require(matches, "literal_prepare_original_formula_required")
    closest = min(matches, key=lambda m: abs(left + offsets[m.end()-1] + 1 - cue["start"]))
    formula_span = _span(source_text, left + offsets[closest.start()], left + offsets[closest.end()-1] + 1)
    # Recover closing presentation braces without inserting a formula or alias.
    depth = source_text[formula_span["start"]:formula_span["end"]].count("{") - source_text[formula_span["start"]:formula_span["end"]].count("}")
    if 0 < depth <= 8 and source_text[formula_span["end"]:formula_span["end"]+depth] == "}" * depth:
        formula_span = _span(source_text, formula_span["start"], formula_span["end"]+depth)
    uncertainty = []
    if literal["raw_uncertainty"] is not None:
        amount = source_text[value["start"]:value["end"]]
        positions = list(re.finditer(re.escape(literal["raw_uncertainty"]), amount))
        require(len(positions) == 1, "literal_prepare_uncertainty_span_required")
        found = positions[0]
        uncertainty = [_span(source_text, value["start"]+found.start(), value["start"]+found.end())]
    loc = candidate["source"]["locator"]
    locator = {key: loc.get(key) for key in expression_contract.LOCATOR_KEYS}
    locator["member"] = candidate["source"]["capture_id"]
    origin = candidate["subject"].get("knowledge_origin")
    entry = {"field_id": candidate["field"], "profile": PROFILE, "field_role": FIELDS[candidate["field"]],
        "subject": {"formula_spans": [formula_span], "sample_label_spans": []},
        "window": {"id": "retained-window:" + digest([candidate["source"]["capture_id"], left, right]),
                   "label_spans": [_span(source_text, left, right)]},
        "source_role": "source_proposed", "knowledge_origin": origin if origin in {"Observed", "Computed"} else "unknown",
        "origin_basis": {"statement": "Retained original source chunk; publication revision and material state unverified.", "spans": []},
        "model_spans": [], "value_spans": [value], "unit_spans": [] if unit is None else [unit],
        "cue_spans": [cue], "uncertainty_spans": uncertainty, "qualifiers": literal["qualifiers"],
        "conditions": [], "locator": locator, "predecessor": None}
    package = {"version": expression_contract.VERSION, "profile": PROFILE, "source": source_metadata,
        "source_text_base64": base64.b64encode(source_text.encode()).decode(),
        "source_content_sha256": candidate["source"]["content_sha256"], "expressions": [entry]}
    prepared = expression_contract.compile_package(package)
    value_projection = prepared.projections[0]["value"]
    require(all(value_projection[key] == literal[key] for key in ("raw_value", "raw_unit", "raw_uncertainty", "field_cue", "role", "qualifiers", "value_span", "unit_span", "cue_span")),
            "literal_prepare_projection_changed")
    return package, prepared


async def prepare(db, *, actor_user_id, request):
    validate_request(request)
    _, session = await reader(db, actor_user_id)
    context_text = await cases.sql_context(db, request["target"])
    if cases.text_sha(context_text) != request["target"]["expected_context_sha256"]:
        raise SourcePropertyConflict("literal_prepare_target_changed")
    context_body = json.loads(context_text)
    closure = cases.closure(context_body)
    require(closure["legacy_result_id"] == request["retained_result_id"]
            and closure["retained_record_sha256"] == request["retained_record_sha256"], "literal_prepare_record_changed")
    status = await cases.eligibility(db, context_text, request["target"])
    require(status["eligible"], "literal_prepare_target_held")
    material = await material_view(db, await db.get(Material, request["material_id"]))
    require(material is not None and current_visibility_allows_view(material.visibility), "literal_prepare_target_held")
    chunk = await db.get(Chunk, request["chunk_id"])
    require(chunk is not None and chunk.paper_id == closure["paper_id"] and 1 <= len(chunk.text) <= 20000,
            "literal_prepare_chunk_unavailable")
    checksum_value = hashlib.sha256(chunk.text.encode()).hexdigest()
    require(checksum_value == request["source_content_sha256"], "literal_prepare_source_changed")
    lifecycle = (await resolve_paper_lifecycle(db, [chunk.paper_id])).get(chunk.paper_id)
    require(normalize_source_status(lifecycle) == "active" and not lifecycle_review_required(lifecycle),
            "literal_prepare_source_held")
    descriptor = (await resolve_chunk_evidence(db, [chunk])).get(chunk.id, {})
    require(descriptor.get("chunk_kind") in {"original_passage", "abstract"}
            and descriptor.get("currentness") == "current"
            and descriptor.get("permission_status") != "restricted"
            and not is_derived_source_hint(section=chunk.section, paper_id=chunk.paper_id, text=chunk.text),
            "literal_prepare_source_origin_held")
    paper = await db.get(Paper, chunk.paper_id)
    url = None if paper is None else recovery._primary_source_url(paper.doi, paper.arxiv_id)
    require(url is not None, "literal_prepare_source_url_unavailable")
    report = await recovery.read_material_enrichment(db, material)
    candidate = next((row for row in report["candidates"] if row["candidate_id"] == request["candidate_id"]), None)
    require(candidate is not None and candidate["source"]["capture_id"] == chunk.id
            and candidate["source"]["paper_id"] == chunk.paper_id
            and candidate["source"]["content_sha256"] == checksum_value, "literal_prepare_candidate_changed")
    references = {(row["result_id"], row["record_sha256"]) for row in candidate.get("retained_result_refs", [])}
    require((request["retained_result_id"], request["retained_record_sha256"]) in references,
            "literal_prepare_record_candidate_mismatch")
    metadata = {"source_id": "retained-chunk:" + digest(chunk.id), "url": url, "kind": "primary_paper",
        "content_kind": "plain_text", "revision": candidate["source"]["source_revision"], "revision_status": "declared",
        "original_parent_sha256": None, "parent_hash_status": "unresolved", "rights_status": "unresolved",
        "currentness": "unresolved", "captured_at": datetime.now(UTC).isoformat()}
    package, prepared = package_from_candidate(candidate, formula=material.formula, source_text=chunk.text, source_metadata=metadata)
    target_operation = {"version": case_contract.REQUEST_VERSION, "request_key": "literal-target:" + uuid4().hex,
                        "operation": "target", "payload": {"field_id": candidate["field"], "target": request["target"]}}
    case_contract.validate(target_operation)
    result = {"version": VERSION, "profile": PROFILE, "status": "prepared_pending",
        "actor_user_id": str(actor_user_id), "session_version": session, "package": package,
        "package_sha256": prepared.package_sha256, "projection_sha256": digest(prepared.projections[0]),
        "target_operation": target_operation, "context_canonical_json": context_text,
        "pins": {key: request[key] for key in REQUEST_KEYS if key not in {"version", "target", "material_id"}},
        "source_origin": {"chunk_kind": descriptor["chunk_kind"], "evidence_revision_id": str(descriptor["evidence_revision_id"]),
                          "publication_revision_verified": False, "source_rights_verified": False},
        "pending_ledger_written": False, **case_contract.AUTHORITY}
    require(len(canonical(result)) <= 2*1024*1024-4096, "literal_prepare_response_bound")
    return result
