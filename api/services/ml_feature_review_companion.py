"""Private, negative-only captured review observations for frozen ML inputs.

This independent artifact is not a modification of the 0054 capsule or 0064
source companion. Full private requests are audit closure, never feature DAG
edges, scientific groups, public-time witnesses or training authority. An
offline checksum cannot authenticate a database, reviewer or absence of newer
decisions; every observation is explicitly historical and all authority false.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from uuid import UUID

from services.ml_feature_companion import decode_companion_artifacts, verify_feature_companion
from services.ml_feature_provenance_v2 import computed_lineage
from services.ml_frozen_provenance import resolve_result_contexts
from services.research_release_manifest import _rows, canonical, digest
from services.scientific_adjudication_contract import SCOPES, validate_request

VERSION = "ml-feature-review-companion/1.0.0"
OBSERVATION_VERSION = "ml-review-observation/1.0.0"
EXPORT_SCOPE = "ml_review_full_audit/1.0.0"
MAX_BYTES = 16 * 1024 * 1024
MAX_REVIEWED = 200
MAX_AUDIT_ROWS = 4000
MAX_REQUESTS = 200
AUTHORITY = {
    "scientific_acceptance": False, "ml_training_approved": False,
    "public_release_authorized": False, "reviewer_authority_authenticated": False,
    "database_observation_authenticated": False, "live_source_rights_checked": False,
}
_TOP = {"version", "base_release_id", "base_manifest_sha256", "source_companion_sha256",
        "observation", "observation_sha256", "authority", "companion_sha256"}
_OBSERVATION = {"version", "capture_admission", "properties", "inputs", "audit_rows", "source_observation"}
_COMMON = {"id", "record_sha256", "created_at"}
_ACTOR = {"actor_user_id", "actor_grant_id"}
_FIELDS = {
    "users": {"id", "is_active", "email_verified", "is_admin"},
    "research_role_grants": _COMMON | {"user_id", "role", "granted_by", "reason_code"},
    "research_role_revocations": _COMMON | {"grant_id", "revoked_by", "reason_code"},
    "scientific_result_subjects": _COMMON | {"property_id", "event_id", "event_revision", "material_id",
        "state_id", "sample_id", "structure_id", "producer_run_id", "native_outcome_id", "subject_version",
        "property_row_sha256", "basis_json", "subject_sha256"},
    "scientific_adjudication_requests": _COMMON | _ACTOR | {"request_key", "request_version", "request_json",
        "request_sha256", "item_count", "assembly_xid"},
    "scientific_result_decisions": _COMMON | _ACTOR | {"request_id", "item_index", "subject_id", "property_id",
        "event_id", "scope", "profile_version", "decision", "reason_code", "predecessor_id", "resolves_decision_id",
        "extraction_decision_id", "item_sha256"},
}


class MlReviewCompanionError(ValueError):
    """Static private-input error; never echo request or source text."""


def require(condition, code="ml_review_companion_invalid"):
    if not condition:
        raise MlReviewCompanionError(code)


def _object(value, fields):
    require(type(value) is dict and set(value) == set(fields), "ml_review_closed_object_required")


def _uuid(value):
    require(type(value) is str, "ml_review_identifier_required")
    try:
        require(str(UUID(value)) == value, "ml_review_identifier_required")
    except (ValueError, AttributeError):
        raise MlReviewCompanionError("ml_review_identifier_required") from None
    return value


def _hash(value):
    require(type(value) is str and re.fullmatch("[0-9a-f]{64}", value), "ml_review_hash_required")
    return value


def _bounded(value):
    # Bound source strings before allocation of the full canonical envelope.
    pending, total, count = [value], 0, 0
    while pending:
        item = pending.pop()
        count += 1
        require(count + len(pending) <= 200000, "ml_review_node_limit")
        if type(item) is str:
            total += len(item.encode("utf-8"))
            require(total <= MAX_BYTES, "ml_review_byte_limit")
        elif type(item) is dict:
            pending.extend(item.keys())
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
    raw = canonical(value)
    require(len(raw) <= MAX_BYTES, "ml_review_byte_limit")
    return raw


def _audit_scalars(table, row):
    """Fixed SQL scalar domains; Python bool is never a revision or xid."""
    nullable_ids = {"sample_id", "structure_id", "producer_run_id", "native_outcome_id",
                    "predecessor_id", "resolves_decision_id", "extraction_decision_id"}
    for key, value in row.items():
        if key == "id" or key.endswith("_id") and key != "material_id":
            if value is not None or key not in nullable_ids:
                _uuid(value)
        elif key.endswith("sha256"):
            _hash(value)
    require(type(row["created_at"]) is str, "ml_review_audit_timestamp_invalid")
    try:
        timestamp = datetime.fromisoformat(row["created_at"])
        require(timestamp.tzinfo is not None and timestamp.utcoffset() == timedelta(0),
                "ml_review_audit_timestamp_invalid")
    except (ValueError, TypeError, OverflowError):
        raise MlReviewCompanionError("ml_review_audit_timestamp_invalid") from None
    if "reason_code" in row:
        require(type(row["reason_code"]) is str and re.fullmatch("[a-z][a-z0-9_]{0,159}", row["reason_code"]),
                "ml_review_audit_reason_invalid")
    if table == "scientific_result_subjects":
        require(type(row["event_revision"]) is int and 0 < row["event_revision"] < 2**31
                and type(row["material_id"]) is str and 0 < len(row["material_id"]) <= 100,
                "ml_review_audit_subject_scalar_invalid")
    elif table == "scientific_adjudication_requests":
        require(type(row["item_count"]) is int and 1 <= row["item_count"] <= 20
                and type(row["assembly_xid"]) is int and 0 < row["assembly_xid"] < 2**63,
                "ml_review_audit_request_scalar_invalid")
    elif table == "scientific_result_decisions":
        require(type(row["item_index"]) is int and 0 <= row["item_index"] < 20,
                "ml_review_audit_decision_scalar_invalid")


def review_feature_inventory(base_manifest, artifact_bytes):
    """Complete input targets and exact forward result/run dependencies.

    Unsupported review quantities remain inventory entries. Audit requests and
    shared event/run names never add dependencies; only the existing explicit
    evidence and retained producer-manifest semantics do.
    """
    index = _rows(base_manifest["rows"])
    contexts = resolve_result_contexts(index, artifact_bytes)
    dependencies = {ref: set() for ref in contexts}
    for context in contexts.values():
        for edge in context.edges:
            if edge.link_type == "derives_from" and edge.input_ref:
                dependencies.setdefault(edge.output_ref, set()).add(edge.input_ref)
    for ref, context in contexts.items():
        if ref[0] == "event_properties" and context.root.knowledge_origin == "Computed":
            dependencies[ref].update(computed_lineage(index, artifact_bytes, ref)["dependencies"])
            if context.root.structure_id:
                dependencies[ref].add(("structure_records", context.root.structure_id))
    for (table, identifier), row in index.items():
        if table == "structure_records":
            parent = row["data"]["parent_structure_id"]
            dependencies[(table, identifier)] = {("structure_records", parent)} if parent else set()
    inputs, pending = {}, []
    for (table, identifier), row in index.items():
        if table != "ml_example_inputs":
            continue
        inputs[identifier] = {"table": table, "row_id": identifier, "row_sha256": row["row_sha256"]}
        data = row["data"]
        if data["input_property_id"]:
            pending.append(("event_properties", data["input_property_id"]))
        if data["input_structure_id"]:
            pending.append(("structure_records", data["input_structure_id"]))
        if data["input_claim_id"]:
            pending.append(("material_claims", data["input_claim_id"]))
    visited = set()
    while pending:
        ref = pending.pop()
        if ref in visited:
            continue
        require(ref in index, "ml_review_frozen_dependency_missing")
        visited.add(ref)
        pending.extend(dependencies.get(ref, ()))
    properties = {identifier: {"table": table, "row_id": identifier,
                  "row_sha256": index[(table, identifier)]["row_sha256"]}
                  for table, identifier in sorted(visited) if table == "event_properties"}
    return {"property_pins": properties, "input_pins": inputs}


def _audit(rows):
    """Reconstruct full atomic requests and historical decision references."""
    from services.ml_review_projection import (
        adjudication_record_sha256,
        parse_sql_json,
        parse_subject,
        publication_role_record_sha256,
        raw_text_sha256,
        sql_canonical,
        validate_row_wire,
    )
    require(type(rows) is list and len(rows) <= MAX_AUDIT_ROWS, "ml_review_audit_row_limit")
    index, keys = {}, []
    for wire in rows:
        value = validate_row_wire(wire)
        table, identifier = wire["table"], _uuid(wire["row_id"])
        require(table in _FIELDS, "ml_review_audit_table_unsupported")
        _object(value, _FIELDS[table])
        require(value["id"] == identifier, "ml_review_audit_identity_mismatch")
        if table == "users":
            require(all(type(value[key]) is bool for key in _FIELDS[table] - {"id"}), "ml_review_user_flags_required")
        else:
            _audit_scalars(table, value)
            record_hash = (publication_role_record_sha256 if table.startswith("research_role_")
                           else adjudication_record_sha256)(wire["row_text"])
            require(record_hash == _hash(value["record_sha256"]), "ml_review_audit_record_hash_mismatch")
        key = table, identifier
        keys.append(key)
        index[key] = value
    require(keys == sorted(set(keys)), "ml_review_audit_inventory_invalid")
    def get(table, identifier):
        require((table, identifier) in index, "ml_review_audit_dependency_missing")
        return index[(table, identifier)]
    subjects, requests, decisions, revoked = {}, {}, {}, set()
    for (table, identifier), row in index.items():
        if table == "research_role_revocations":
            get("research_role_grants", row["grant_id"])
            get("users", row["revoked_by"])
            require(row["grant_id"] not in revoked, "ml_review_duplicate_revocation")
            revoked.add(row["grant_id"])
        elif table == "research_role_grants":
            get("users", row["user_id"])
            get("users", row["granted_by"])
            require(row["role"] in {"curator", "reviewer", "publisher"}, "ml_review_role_invalid")
        elif table == "scientific_result_subjects":
            body = parse_subject(row["basis_json"], expected_sha256=row["subject_sha256"])
            require(row["subject_version"] == body["version"]
                    and all(row[key] == value for key, value in body["target"].items()),
                    "ml_review_subject_target_mismatch")
            prop = next(item["snapshot"] for item in body["rows"]
                        if item["table"] == "event_properties" and item["row_id"] == row["property_id"])
            require(raw_text_sha256(sql_canonical(prop)) == row["property_row_sha256"],
                    "ml_review_subject_property_hash_mismatch")
            subjects[identifier] = body
        elif table == "scientific_adjudication_requests":
            require(raw_text_sha256(row["request_json"]) == _hash(row["request_sha256"]), "ml_review_request_hash_mismatch")
            body = parse_sql_json(row["request_json"], max_bytes=128 * 1024)
            require(sql_canonical(body) == row["request_json"], "ml_review_request_canonical_required")
            validate_request(body)
            require(body["version"] == row["request_version"] and body["request_key"] == row["request_key"]
                    and type(row["item_count"]) is int and row["item_count"] == len(body["items"]),
                    "ml_review_request_inventory_mismatch")
            grant = get("research_role_grants", row["actor_grant_id"])
            require(grant["user_id"] == row["actor_user_id"] and grant["role"] == "reviewer",
                    "ml_review_request_actor_mismatch")
            requests[identifier] = body
        elif table == "scientific_result_decisions":
            decisions[identifier] = row
    require(len(requests) <= MAX_REQUESTS, "ml_review_request_limit")
    successors, by_request, initial = {}, defaultdict(set), set()
    for identifier, decision in decisions.items():
        request = get("scientific_adjudication_requests", decision["request_id"])
        require(decision["subject_id"] in subjects and decision["request_id"] in requests,
                "ml_review_decision_dependencies_missing")
        body = subjects[decision["subject_id"]]
        subject = get("scientific_result_subjects", decision["subject_id"])
        items, item_index = requests[decision["request_id"]]["items"], decision["item_index"]
        require(type(item_index) is int and 0 <= item_index < len(items), "ml_review_item_index_invalid")
        item = items[item_index]
        mapping = {"id": "decision_id", "subject_id": "subject_id", "property_id": "property_id", "scope": "scope",
            "profile_version": "profile_version", "decision": "decision", "reason_code": "reason_code",
            "predecessor_id": "expected_previous_decision_id", "resolves_decision_id": "resolves_decision_id",
            "extraction_decision_id": "extraction_decision_id"}
        require(all(decision[key] == item[target] for key, target in mapping.items())
                and all(decision[key] == request[key] for key in _ACTOR)
                and decision["property_id"] == subject["property_id"] and decision["event_id"] == subject["event_id"]
                and item["expected_subject_sha256"] == subject["subject_sha256"]
                and raw_text_sha256(sql_canonical(item)) == decision["item_sha256"], "ml_review_exact_item_mismatch")
        require(item_index not in by_request[decision["request_id"]], "ml_review_duplicate_request_item")
        by_request[decision["request_id"]].add(item_index)
        prop = next(row["snapshot"] for row in body["rows"] if row["table"] == "event_properties"
                    and row["row_id"] == decision["property_id"])
        require(prop["property_key"] == "phonon_min_frequency" and prop["unit"] == "THz",
                "ml_review_profile_quantity_mismatch")
        artifacts = {value["artifact_id"]: value for value in body["artifacts"]}
        require(all(value["artifact_id"] in artifacts
                    and artifacts[value["artifact_id"]]["hash_status"] == "verified"
                    and artifacts[value["artifact_id"]]["bytes_sha256"] == value["bytes_sha256"]
                    for value in item["evidence_refs"]), "ml_review_exact_evidence_mismatch")
        native_profile = decision["profile_version"] == "native-sampled-frequency-extraction/1.0.0"
        require(not native_profile or body["native_import"] is not None, "ml_review_native_profile_mismatch")
        if decision["decision"] == "accept":
            require(prop["relation"] == "exact", "ml_review_acceptance_quantity_mismatch")
            refs = {value["artifact_id"] for value in item["evidence_refs"]}
            require(({value["artifact_id"] for value in body["native_import"]["source_files"]} <= refs)
                    if native_profile else bool(refs & set(body["support_artifact_ids"])),
                    "ml_review_acceptance_support_missing")
        prior_id = decision["predecessor_id"]
        if prior_id:
            prior = get("scientific_result_decisions", prior_id)
            require(prior_id != identifier and prior_id not in successors
                    and all(prior[key] == decision[key] for key in ("property_id", "scope")),
                    "ml_review_predecessor_invalid")
            successors[prior_id] = identifier
            if decision["decision"] == "accept" and prior["subject_id"] == decision["subject_id"] \
                    and prior["decision"] in {"reject", "request_clarification"}:
                require(prior["actor_user_id"] != decision["actor_user_id"]
                        and decision["resolves_decision_id"] == prior_id, "ml_review_negative_resolution_invalid")
        else:
            target = decision["property_id"], decision["scope"]
            require(target not in initial, "ml_review_multiple_initial_decisions")
            initial.add(target)
        dependency_id = decision["extraction_decision_id"]
        if dependency_id:
            dependency = get("scientific_result_decisions", dependency_id)
            require(dependency["subject_id"] == decision["subject_id"] and dependency["scope"] == "extraction_fidelity"
                    and dependency["decision"] == "accept" and dependency["property_id"] == decision["property_id"]
                    and (dependency["request_id"] != decision["request_id"] or dependency["item_index"] < item_index),
                    "ml_review_fidelity_dependency_invalid")
    for identifier, body in requests.items():
        require(by_request[identifier] == set(range(len(body["items"]))), "ml_review_complete_request_required")
    for identifier in decisions:
        seen, current = set(), identifier
        while current:
            require(current not in seen, "ml_review_predecessor_cycle")
            seen.add(current)
            current = decisions[current]["predecessor_id"]
    return index, subjects, decisions, successors, revoked


def _available(index, revoked, user_id, grant_id, role):
    user = index.get(("users", user_id))
    grant = index.get(("research_role_grants", grant_id))
    require(user is not None and grant is not None, "ml_review_current_role_observation_missing")
    require(grant["user_id"] == user_id and grant["role"] == role, "ml_review_role_binding_mismatch")
    return user["is_active"] and user["email_verified"] and grant_id not in revoked


def _status(scope, head, *, current_sha256, source_held, available, extraction):
    # Version-owned negative policy, not an import of a live SQL resolver.
    if head is None:
        return "unreviewed", []
    if head["subject_sha256"] != current_sha256:
        return "stale", ["scientific_subject_changed"]
    if source_held:
        return "source_held", ["scientific_source_held"]
    if head["decision"] == "reject":
        return "rejected", ["exact_result_rejected"]
    if head["decision"] == "request_clarification":
        return "clarification_required", ["exact_result_clarification_required"]
    if not available:
        return "reviewer_unavailable", ["current_reviewer_grant_unavailable"]
    if scope == "scientific_result" and not (extraction and extraction["status"] == "accepted"
                                            and extraction["decision_id"] == head["extraction_decision_id"]):
        return "dependency_review_held", ["current_extraction_fidelity_required"]
    return "accepted", []


def _verify(value, *, base_manifest, expected_base_manifest_sha256, source_companion,
            expected_source_companion_sha256, expected_review_companion_sha256):
    from services.ml_review_projection import (
        bridge_frozen_subject,
        parse_subject,
        projection_fields,
    )
    from services.ml_review_source_observation import decode_rows, equal, verify_source_observation
    _bounded(value)
    _object(value, _TOP)
    require(digest(value) == _hash(expected_review_companion_sha256), "ml_review_external_hash_mismatch")
    require(value["companion_sha256"] == digest({key: item for key, item in value.items() if key != "companion_sha256"}),
            "ml_review_internal_hash_mismatch")
    require(value["version"] == VERSION and type(value["authority"]) is dict
            and set(value["authority"]) == set(AUTHORITY)
            and all(item is False for item in value["authority"].values()), "ml_review_version_or_authority_invalid")
    require(value["base_manifest_sha256"] == _hash(expected_base_manifest_sha256)
            and value["source_companion_sha256"] == _hash(expected_source_companion_sha256)
            and value["base_release_id"] == source_companion["base_release_id"], "ml_review_independent_binding_mismatch")
    verify_feature_companion(source_companion, base_manifest=base_manifest,
        expected_base_manifest_sha256=expected_base_manifest_sha256,
        expected_companion_sha256=expected_source_companion_sha256)
    inventory = review_feature_inventory(base_manifest, decode_companion_artifacts(source_companion))
    frozen = _rows(base_manifest["rows"])
    observation = value["observation"]
    _object(observation, _OBSERVATION)
    require(observation["version"] == OBSERVATION_VERSION
            and digest(observation) == value["observation_sha256"], "ml_review_observation_hash_mismatch")
    properties, inputs = observation["properties"], observation["inputs"]
    require(type(properties) is list and type(inputs) is list, "ml_review_inventory_required")
    require([row.get("property_id") for row in properties] == sorted(inventory["property_pins"])
            and [row.get("input_id") for row in inputs] == sorted(inventory["input_pins"]),
            "ml_review_complete_feature_inventory_required")
    bindings = defaultdict(list)
    for binding in source_companion["bindings"]:
        bindings[binding["example_input_id"]].append(binding["id"])
    for row in inputs:
        _object(row, {"input_id", "frozen_row_sha256", "binding_ids"})
        require(row["frozen_row_sha256"] == inventory["input_pins"][row["input_id"]]["row_sha256"]
                and row["binding_ids"] == sorted(bindings[row["input_id"]]), "ml_review_input_binding_mismatch")
    index, subjects, decisions, successors, revoked = _audit(observation["audit_rows"])
    admission = observation["capture_admission"]
    _object(admission, {"version", "actor_user_id", "actor_grant_id"})
    user_id, grant_id = _uuid(admission["actor_user_id"]), _uuid(admission["actor_grant_id"])
    require(admission["version"] == EXPORT_SCOPE
            and _available(index, revoked, user_id, grant_id, "curator")
            and index[("users", user_id)]["is_admin"], "ml_review_full_audit_admission_required")
    sources = verify_source_observation(observation["source_observation"], base_manifest=base_manifest,
        source_companion=source_companion, property_ids=sorted(inventory["property_pins"]))
    require(set(sources["property_source_holds"]) == set(inventory["property_pins"])
            and set(sources["input_source_holds"]) == set(inventory["input_pins"]), "ml_review_source_inventory_mismatch")
    for mapping in sources.values():
        require(type(mapping) is dict, "ml_review_source_holds_invalid")
        for codes in mapping.values():
            require(type(codes) is list and len(codes) <= 100
                    and all(type(code) is str and re.fullmatch("[a-z][a-z0-9_]{0,119}", code) for code in codes)
                    and codes == sorted(set(codes)), "ml_review_source_holds_invalid")
    source_rows = decode_rows(observation["source_observation"]["rows"])
    statuses, holds, reviewed = {}, {}, 0
    seeds = set()
    for row in properties:
        _object(row, {"property_id", "frozen_row_sha256", "current_subject_text", "current_subject_sha256", "heads"})
        prop_id = row["property_id"]
        require(row["frozen_row_sha256"] == inventory["property_pins"][prop_id]["row_sha256"], "ml_review_property_pin_mismatch")
        _object(row["heads"], SCOPES)
        found = {scope: [key for key, decision in decisions.items() if decision["property_id"] == prop_id
                        and decision["scope"] == scope and key not in successors] for scope in SCOPES}
        require(all(len(keys) <= 1 and row["heads"][scope] == (keys[0] if keys else None)
                    for scope, keys in found.items()), "ml_review_current_head_inventory_mismatch")
        any_head = any(row["heads"].values())
        review_codes, projection = set(), None
        if any_head:
            reviewed += 1
            require(reviewed <= MAX_REVIEWED, "ml_review_reviewed_target_limit")
            body = parse_subject(row["current_subject_text"], expected_sha256=row["current_subject_sha256"])
            require(body["target"]["property_id"] == prop_id, "ml_review_current_property_mismatch")
            native_sources = ({item["artifact_id"] for item in body["native_import"]["source_files"]}
                              if body["native_import"] else set())
            for current in body["rows"]:
                key = current["table"], current["row_id"]
                observed = source_rows.get(key)
                # 0067 additionally retains every native package source file;
                # files outside its FK closure need not be new source roots.
                # Their original bytes remain pinned by the native subject.
                if observed is None:
                    require(key[0] == "evidence_artifacts" and key[1] in native_sources,
                            "ml_review_current_source_row_missing")
                else:
                    projected = {field: observed[field] for field in projection_fields(key[0])}
                    require(equal(projected, current["snapshot"]), "ml_review_inconsistent_current_observations")
            projection = bridge_frozen_subject(frozen, property_id=prop_id,
                subject_text=row["current_subject_text"], expected_subject_sha256=row["current_subject_sha256"])
            if projection["status"] != "matched":
                review_codes.add("frozen_subject_projection_" + projection["status"])
        else:
            require(row["current_subject_text"] is None and row["current_subject_sha256"] is None,
                    "ml_review_unreviewed_subject_must_be_absent")
        scoped, extraction = [], None
        for scope in SCOPES:
            identifier = row["heads"][scope]
            available, head = False, None
            if identifier is not None:
                seeds.add(identifier)
                head = dict(decisions[identifier])
                head["subject_sha256"] = index[("scientific_result_subjects", head["subject_id"])]["subject_sha256"]
                available = _available(index, revoked, head["actor_user_id"], head["actor_grant_id"], "reviewer")
            status, codes = _status(scope, head, current_sha256=row["current_subject_sha256"],
                source_held=bool(sources["property_source_holds"][prop_id]), available=available, extraction=extraction)
            entry = {"scope": scope, "decision_id": identifier, "status": status, "reason_codes": codes}
            scoped.append(entry)
            if scope == "extraction_fidelity":
                extraction = entry
            review_codes.update(codes)
        # Source gates are independent of the existence of a 0067 review.
        review_codes.update(sources["property_source_holds"][prop_id])
        holds[prop_id] = sorted(review_codes)
        statuses[prop_id] = {"scopes": scoped, "projection": projection}
    # Exact audit closure includes complete sibling requests plus every history
    # dependency; unrelated surplus records cannot masquerade as feature data.
    used, pending = set(), list(seeds)
    while pending:
        identifier = pending.pop()
        if identifier in used:
            continue
        used.add(identifier)
        decision = decisions[identifier]
        pending.extend(key for key, other in decisions.items() if other["request_id"] == decision["request_id"])
        pending.extend(decision[key] for key in ("predecessor_id", "resolves_decision_id", "extraction_decision_id") if decision[key])
    require(used == set(decisions), "ml_review_audit_closure_mismatch")
    expected_subjects = {decision["subject_id"] for decision in decisions.values()}
    expected_requests = {decision["request_id"] for decision in decisions.values()}
    require(expected_subjects == set(subjects)
            and expected_requests == {key for table, key in index if table == "scientific_adjudication_requests"},
            "ml_review_audit_subject_request_closure_mismatch")
    expected_grants = {grant_id} | {decision["actor_grant_id"] for decision in decisions.values()}
    require(expected_grants == {key for table, key in index if table == "research_role_grants"},
            "ml_review_audit_role_closure_mismatch")
    expected_users = {user_id}
    for (table, _), row in index.items():
        if table == "research_role_grants":
            expected_users.update((row["user_id"], row["granted_by"]))
        elif table == "research_role_revocations":
            expected_users.add(row["revoked_by"])
    require(expected_users == {key for table, key in index if table == "users"},
            "ml_review_audit_user_closure_mismatch")
    return {"version": VERSION, "observation_semantics": "captured_not_live", "review_companion_sha256": digest(value),
        "observation_sha256": value["observation_sha256"], "base_manifest_sha256": expected_base_manifest_sha256,
        "source_companion_sha256": expected_source_companion_sha256, **inventory,
        "property_holds": holds, "input_source_holds": sources["input_source_holds"],
        "property_statuses": statuses, "authority": dict(AUTHORITY)}


def verify_ml_review_companion(review_companion, *, base_manifest, expected_base_manifest_sha256,
                               source_companion, expected_source_companion_sha256, expected_review_companion_sha256):
    """Pure bounded internal verification; neither fresh nor authenticated."""
    try:
        return _verify(review_companion, base_manifest=base_manifest,
            expected_base_manifest_sha256=expected_base_manifest_sha256, source_companion=source_companion,
            expected_source_companion_sha256=expected_source_companion_sha256,
            expected_review_companion_sha256=expected_review_companion_sha256)
    except (ValueError, TypeError, KeyError, AttributeError, StopIteration, RecursionError, UnicodeError) as exc:
        if isinstance(exc, MlReviewCompanionError):
            raise
        raise MlReviewCompanionError("ml_review_companion_invalid") from None


def assemble_ml_review_companion(*, base_manifest, expected_base_manifest_sha256, source_companion,
                                 expected_source_companion_sha256, observation):
    """Seal already captured private observations, then independently replay."""
    detached = json.loads(_bounded(observation))
    value = {"version": VERSION, "base_release_id": source_companion["base_release_id"],
        "base_manifest_sha256": expected_base_manifest_sha256,
        "source_companion_sha256": expected_source_companion_sha256, "observation": detached,
        "observation_sha256": digest(detached), "authority": dict(AUTHORITY)}
    value["companion_sha256"] = digest(value)
    verify_ml_review_companion(value, base_manifest=base_manifest,
        expected_base_manifest_sha256=expected_base_manifest_sha256, source_companion=source_companion,
        expected_source_companion_sha256=expected_source_companion_sha256, expected_review_companion_sha256=digest(value))
    return value
