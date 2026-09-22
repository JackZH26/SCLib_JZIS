"""Private captured label currentness, never a replacement label or authority.

The independently pinned document declares a complete SQL observation. Offline
verification cannot discover a row omitted before that capture was sealed or
authenticate the database. Root selection is always the original frozen dataset.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from uuid import UUID

from services.ml_review_source_observation import (
    HELD,
    PAPER_FIELDS,
    WORK_FIELDS,
    account,
    decode_rows,
    equal,
    lifecycle_record_sha,
    parse,
    pg_json,
    raw_sha,
    read_rows,
)
from services.research_release_manifest import _rows, canonical
from services.research_release_spec import FKS, SPEC

VERSION = "ml-label-observation/1.0.0"
EXPORT_SCOPE = "ml_label_full_audit/1.0.0"
MAX_BYTES = 16 * 1024 * 1024
MAX_ROWS = 4000
MAX_DEPTH = 48
MAX_NODES = 200000
OWNED = {
    "research_events": (("event_evidence", "event_id"),
                        ("snapshot_event_memberships", "event_id"),
                        ("research_events", "supersedes_id")),
    "material_claims": (("claim_source_occurrences", "claim_id"), ("claim_qc", "claim_id")),
    "papers": (("paper_work_map", "paper_id"),),
    "source_revisions": (("source_captures", "source_revision_id"),),
}
LABEL_HOLD_CODES = frozenset({
    "label_scientific_content_changed", "label_review_state_changed",
    "label_current_result_held", "label_current_material_held", "label_current_source_held",
    "label_source_identity_changed", "label_source_binding_changed",
    "label_source_inventory_changed", "label_dependency_inventory_changed",
    "label_event_superseded", "label_example_binding_changed",
})
_SOURCE_TABLES = frozenset({"claim_source_occurrences", "source_revisions", "source_captures",
    "event_evidence", "snapshot_event_memberships", "source_snapshots", "paper_work_map", "evidence_artifacts"})
_MATERIAL_FIELDS = frozenset({"id", "formula", "formula_normalized", "parent_material_id",
    "material_semantics", "formula_substrate", "formula_overlayer", "family"})
_OPERATIONAL = frozenset({"created_at", "updated_at", "record_sha256"})


class MlLabelObservationError(ValueError):
    """Static private capture error; no source text or identifiers are echoed."""


def require(condition, code="ml_label_observation_invalid"):
    if not condition:
        raise MlLabelObservationError(code)


def bounded(value):
    pending, nodes, size = [(value, 0)], 0, 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        require(depth <= MAX_DEPTH and nodes + len(pending) <= MAX_NODES, "ml_label_node_limit")
        if type(item) is dict:
            require(all(type(key) is str for key in item))
            require(nodes + len(pending) + 2 * len(item) <= MAX_NODES, "ml_label_node_limit")
            pending.extend((part, depth + 1) for pair in item.items() for part in pair)
        elif type(item) is list:
            require(nodes + len(pending) + len(item) <= MAX_NODES, "ml_label_node_limit")
            pending.extend((part, depth + 1) for part in item)
        elif type(item) is str:
            require("\x00" not in item)
            size += len(item.encode("utf-8"))
            require(size <= MAX_BYTES, "ml_label_byte_limit")
    raw = canonical(value)
    require(len(raw) <= MAX_BYTES, "ml_label_byte_limit")
    return raw


def _uuid(value):
    require(type(value) is str and str(UUID(value)) == value)
    return value


def _hash(value):
    require(type(value) is str and re.fullmatch("[0-9a-f]{64}", value))
    return value


def _admission(value):
    require(type(value) is dict and set(value) == {"version", "actor_user_id", "actor_grant_id"})
    require(value["version"] == EXPORT_SCOPE)
    _uuid(value["actor_user_id"])
    _uuid(value["actor_grant_id"])


def label_inventory(base_manifest):
    """All frozen root examples, including excluded labels and no-input rows."""
    try:
        bounded(base_manifest)
        index = _rows(base_manifest["rows"])
        examples, claims = {}, {}
        for (table, identifier), wire in sorted(index.items()):
            if table != "ml_examples" or wire["data"]["dataset_snapshot_id"] != base_manifest["dataset_id"]:
                continue
            _uuid(identifier)
            claim_id = _uuid(wire["data"]["claim_id"])
            claim = index.get(("material_claims", claim_id))
            require(claim is not None, "ml_label_missing_frozen_root")
            require(claim["data"]["material_id"] == wire["data"]["material_id"], "ml_label_frozen_binding_invalid")
            examples[identifier] = {"table": table, "row_id": identifier, "row_sha256": wire["row_sha256"]}
            claims[claim_id] = {"table": "material_claims", "row_id": claim_id, "row_sha256": claim["row_sha256"]}
        require(examples, "ml_label_missing_frozen_root")
        return {"example_pins": examples, "claim_pins": dict(sorted(claims.items()))}
    except MlLabelObservationError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, UnicodeError):
        raise MlLabelObservationError("ml_label_inventory_invalid") from None


def _inventory_lists(base_manifest, inventory):
    frozen = {(row["table"], row["row_id"]): row["data"] for row in base_manifest["rows"]}
    return {
        "examples": [{"example_id": key, "frozen_example_row_sha256": pin["row_sha256"],
                      "claim_id": frozen[("ml_examples", key)]["claim_id"]}
                     for key, pin in inventory["example_pins"].items()],
        "claims": [{"claim_id": key, "frozen_claim_row_sha256": pin["row_sha256"]}
                   for key, pin in inventory["claim_pins"].items()],
    }


def references(table, row):
    # Unlike the frozen feature-source helper, event review artifact is required.
    return {(target, str(row[fields[0]])) for fields, target, _ in FKS.get(table, ())
            if all(row[field] is not None for field in fields)}


def closure(index, roots):
    reverse = defaultdict(set)
    for key, row in index.items():
        for parent, relations in OWNED.items():
            for table, column in relations:
                if table == key[0] and row[column] is not None:
                    reverse[(parent, str(row[column]))].add(key)
    found, pending = set(), [(key, 0) for key in roots]
    while pending:
        key, depth = pending.pop()
        if key in found:
            continue
        require(depth <= MAX_DEPTH and len(found) + len(pending) <= MAX_ROWS * 4, "ml_label_closure_limit")
        require(key in index, "ml_label_missing_dependency")
        found.add(key)
        row = index[key]
        for fields, target, columns in FKS.get(key[0], ()):
            if all(row[field] is not None for field in fields):
                parent = (target, str(row[fields[0]]))
                require(parent in index and all(equal(row[field], index[parent][column])
                    for field, column in zip(fields, columns, strict=True)), "ml_label_composite_binding_invalid")
        pending.extend((ref, depth + 1) for ref in (references(key[0], row) | reverse[key]) - found)
        require(len(found) <= MAX_ROWS, "ml_label_row_limit")
    return found


def _roots(inventory):
    return {("ml_examples", key) for key in inventory["example_pins"]} | {
        ("material_claims", key) for key in inventory["claim_pins"]}


def _row_budget(budget, count):
    require(type(budget.get("rows")) is int and budget["rows"] >= 0
            and budget["rows"] + count <= MAX_ROWS, "ml_label_row_limit")
    budget["rows"] += count


def _decode_rows(rows):
    """Apply a cumulative node budget to decoded SQL bodies, not just strings."""
    index, keys, nodes = {}, [], 0
    for wire in rows:
        decoded = decode_rows([wire])
        key, row = next(iter(decoded.items()))
        pending = [(row, 0)]
        while pending:
            item, depth = pending.pop()
            nodes += 1
            require(depth <= MAX_DEPTH and nodes + len(pending) <= MAX_NODES, "ml_label_node_limit")
            if type(item) is dict:
                require(nodes + len(pending) + 2 * len(item) <= MAX_NODES, "ml_label_node_limit")
                pending.extend((part, depth + 1) for pair in item.items() for part in pair)
            elif type(item) is list:
                require(nodes + len(pending) + len(item) <= MAX_NODES, "ml_label_node_limit")
                pending.extend((part, depth + 1) for part in item)
        keys.append(key)
        index[key] = row
    require(keys == sorted(set(keys)), "ml_label_row_inventory")
    return index


async def capture_label_observation(db, *, base_manifest, capture_admission, byte_budget):
    """Read-only caller-owned bounded snapshot; caller authenticates before entry."""
    import sqlalchemy as sa

    try:
        _admission(capture_admission)
        require(type(byte_budget) is dict and type(byte_budget.get("bytes")) is int
                and 0 <= byte_budget["bytes"] <= MAX_BYTES)
        _row_budget(byte_budget, 0)
        inventory = label_inventory(base_manifest)
        found, expanded, pending = {}, set(), _roots(inventory)
        for _ in range(MAX_DEPTH + 1):
            if not pending:
                break
            require(len(found) + len(pending - found.keys()) + byte_budget["rows"] <= MAX_ROWS, "ml_label_row_limit")
            groups = defaultdict(set)
            for table, identifier in pending - found.keys():
                groups[table].add(identifier)
            for table, identifiers in sorted(groups.items()):
                wires = await read_rows(db, table, identifiers, byte_budget=byte_budget)
                require({row["row_id"] for row in wires} == identifiers, "ml_label_missing_current_root_or_dependency")
                found.update(((row["table"], row["row_id"]), row) for row in wires)
            groups = defaultdict(set)
            for table, identifier in pending - expanded:
                groups[table].add(identifier)
            new = set()
            for table, identifiers in sorted(groups.items()):
                for child, column in OWNED.get(table, ()):
                    wires = await read_rows(db, child, identifiers, column=column, byte_budget=byte_budget)
                    for wire in wires:
                        key = wire["table"], wire["row_id"]
                        require(key not in found or found[key] == wire)
                        found[key] = wire
                        new.add(key)
            for key in pending:
                new.update(references(key[0], parse(found[key]["row_text"])))
            expanded.update(pending)
            pending = new - expanded
        require(not pending, "ml_label_closure_limit")
        _row_budget(byte_budget, len(found))
        lifecycle = []
        for (table, identifier), wire in sorted(list(found.items())):
            if table not in {"papers", "works"}:
                continue
            kind = "paper" if table == "papers" else "work"
            fields = PAPER_FIELDS if kind == "paper" else WORK_FIELDS
            expression = "jsonb_build_object(" + ",".join("'" + key + "',t.\"" + key + "\"" for key in fields) + ")"
            body = "jsonb_build_object('version','source-lifecycle-snapshot/1.0.0','kind',CAST(:kind AS text),'snapshot'," + expression + ")::text"
            params = {"kind": kind, "id": identifier}
            length = await db.scalar(sa.text(f'SELECT octet_length({body}) FROM public."{table}" t WHERE id::text=:id'), params)
            require(type(length) is int)
            account(byte_budget, length + 256)
            text = await db.scalar(sa.text(f'SELECT {body} FROM public."{table}" t WHERE id::text=:id'), params)
            events = await read_rows(db, "source_lifecycle_events", [identifier], column=kind + "_id", byte_budget=byte_budget)
            _row_budget(byte_budget, len(events) + 1)
            for event in events:
                found[(event["table"], event["row_id"])] = event
            ordered = sorted(events, key=lambda value: parse(value["row_text"])["revision"])
            lifecycle.append({"kind": kind, "row_id": identifier, "snapshot_text": text,
                "snapshot_sha256": raw_sha(text), "event_ids": [row["row_id"] for row in ordered]})
        result = {"version": VERSION, "capture_admission": dict(capture_admission),
            **_inventory_lists(base_manifest, inventory), "rows": [found[key] for key in sorted(found)], "lifecycle": lifecycle}
        return json.loads(bounded(result))
    except MlLabelObservationError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, UnicodeError, OverflowError):
        raise MlLabelObservationError("ml_label_capture_invalid") from None


def _lifecycle(value, index, expected):
    seen, used, held = [], set(), set()
    for item in value:
        require(type(item) is dict and set(item) == {"kind", "row_id", "snapshot_text", "snapshot_sha256", "event_ids"})
        require(item["kind"] in {"paper", "work"})
        key = ("papers" if item["kind"] == "paper" else "works", item["row_id"])
        require(key in index and raw_sha(item["snapshot_text"]) == _hash(item["snapshot_sha256"]))
        fields = PAPER_FIELDS if item["kind"] == "paper" else WORK_FIELDS
        snapshot = {"version": "source-lifecycle-snapshot/1.0.0", "kind": item["kind"],
                    "snapshot": {field: index[key][field] for field in fields}}
        require(equal(parse(item["snapshot_text"]), snapshot) and pg_json(snapshot) == item["snapshot_text"], "ml_label_lifecycle_snapshot_mismatch")
        require(type(item["event_ids"]) is list and len(item["event_ids"]) <= MAX_ROWS
                and len(set(item["event_ids"])) == len(item["event_ids"]))
        previous = None
        for sequence, identifier in enumerate(item["event_ids"], 1):
            event_key = "source_lifecycle_events", _uuid(identifier)
            require(event_key in index and event_key not in used)
            event = index[event_key]
            for field in ("old_snapshot_sha256", "snapshot_sha256", "record_sha256"):
                if event[field] is not None or field != "old_snapshot_sha256":
                    _hash(event[field])
            if event["predecessor_id"] is not None:
                _uuid(event["predecessor_id"])
            for field in ("prior_status", "observed_status"):
                require(event[field] is None and field == "prior_status" or
                        type(event[field]) is str and len(event[field]) <= 20, "ml_label_lifecycle_scalar_invalid")
            require(type(event["created_at"]) is str, "ml_label_lifecycle_scalar_invalid")
            require(datetime.fromisoformat(event["created_at"]).tzinfo is not None, "ml_label_lifecycle_scalar_invalid")
            require(event["record_sha256"] == lifecycle_record_sha(event), "ml_label_lifecycle_record_mismatch")
            require(event["event_kind"] in {"baseline_observed", "lifecycle_change", "catalogue_revision"})
            require(event[item["kind"] + "_id"] == key[1]
                    and event["work_id" if item["kind"] == "paper" else "paper_id"] is None)
            require(type(event["revision"]) is int and event["revision"] == sequence)
            require(event["predecessor_id"] == (previous["id"] if previous else None))
            if previous:
                require(event["old_snapshot_sha256"] == previous["snapshot_sha256"] and event["prior_status"] == previous["observed_status"])
            else:
                require(event["observed_status"] in HELD or event["prior_status"] in HELD)
            previous = event
            used.add(event_key)
        status = index[key]["status" if item["kind"] == "paper" else "publication_status"].strip().lower()
        if previous:
            require(previous["snapshot_sha256"] == item["snapshot_sha256"]
                    and previous["observed_status"] == status, "ml_label_lifecycle_head_mismatch")
        if previous or status in HELD:
            held.add(key)
        seen.append(key)
    require(seen == sorted(key for key in expected if key[0] in {"papers", "works"}), "ml_label_lifecycle_inventory")
    require(used == {key for key in index if key[0] == "source_lifecycle_events"}, "ml_label_lifecycle_inventory")
    return held


def _projection(table, row):
    # SQL number scale and equivalent UTC timestamp spellings are not scientific changes.
    fields = set(row) - _OPERATIONAL
    if table == "materials":
        fields = _MATERIAL_FIELDS
    elif table == "papers":
        fields = {"id", "source", "arxiv_id", "doi", "external_id", "id_scheme", "related_paper_id"}
    elif table == "works":
        fields = {"id", "canonical_doi", "canonical_arxiv_id", "identity_metadata"}
    elif table == "evidence_artifacts":
        fields -= {"access", "license"}
    elif table == "claim_qc":
        fields -= {"reviewer_notes"}
    result = {}
    for field in fields:
        value = row[field]
        if value is not None and SPEC[table]["fields"][field]["type"] == "DATETIME":
            timestamp = datetime.fromisoformat(value)
            require(timestamp.tzinfo is not None)
            value = timestamp.astimezone(timezone.utc).isoformat()
        result[field] = value
    return result


def _material_held(row):
    """Versioned negative subset of SC07, not a catalogue/label approval call.

    No source-scope exemption clears a global hold. Unbound sibling records do
    not assert this exact label false; material-wide provenance quarantine is
    still an unconditional processing restriction. Raw positive flags are not
    consulted and no stored visibility/anomaly acceptance is trusted.
    """
    status = row["status"].strip().lower()
    if (row["needs_review"] or row["retracted"] or row["disputed"]
            or row["status"] != "" and status not in {"active", "active_research"}):
        return True
    reason = row["review_reason"]
    if isinstance(reason, str) and reason.lstrip()[:200].lower().startswith("provenance_quarantine"):
        return True
    records = row["records"]
    if type(records) is not list:
        return True
    for record in records:
        if type(record) is not dict:
            return True
        reason = record.get("review_reason")
        statuses = {value.strip().lower() for field in ("status", "review_status", "source_status", "validity_status", "provenance_status")
                    if type(value := record.get(field)) is str}
        if statuses & {"quarantined", "quarantine", "provenance_quarantined"} or (
                type(reason) is str and reason.lstrip()[:200].lower().startswith("provenance_quarantine")):
            return True
    return False


def _assessed_events(historical, refs):
    """Exact result/explicit dependency events, excluding history-only parents."""
    result = set()
    for table, identifier in refs:
        row = historical[(table, identifier)]
        if table in {"material_claims", "event_properties"} and row["event_id"] is not None:
            result.add(row["event_id"])
        elif table == "event_evidence" and row["input_event_id"] is not None:
            result.add(row["input_event_id"])
    return result


def _verify(value, *, base_manifest, review_companion):
    require(type(value) is dict and set(value) == {"version", "capture_admission", "examples", "claims", "rows", "lifecycle"})
    require(value["version"] == VERSION)
    bounded(value)
    _admission(value["capture_admission"])
    review_observation = review_companion["observation"]
    other = review_observation["capture_admission"]
    require(all(value["capture_admission"][key] == other[key] for key in ("actor_user_id", "actor_grant_id")), "ml_label_capture_actor_mismatch")
    inventory = label_inventory(base_manifest)
    lists = _inventory_lists(base_manifest, inventory)
    require(value["examples"] == lists["examples"] and value["claims"] == lists["claims"], "ml_label_root_inventory_mismatch")
    require(type(value["rows"]) is list and type(value["lifecycle"]) is list
            and len(value["rows"]) + len(value["lifecycle"]) <= MAX_ROWS, "ml_label_row_limit")
    index = _decode_rows(value["rows"])
    for (table, _), row in index.items():
        if table == "claim_qc":
            require(row["review_status"] in {"pending", "approved", "rejected"}, "ml_label_review_enum_invalid")
    expected = closure(index, _roots(inventory))
    require(expected == {key for key in index if key[0] != "source_lifecycle_events"}, "ml_label_complete_closure_required")
    held_sources = _lifecycle(value["lifecycle"], index, expected)
    # Both independently pinned captures claim the same SQL snapshot. Shared
    # row text is identically projected, so require exact original SQL bytes.
    source = review_observation["source_observation"]
    shared = {(row["table"], row["row_id"]): row for row in source["rows"]}
    for row in value["rows"]:
        key = row["table"], row["row_id"]
        require(key not in shared or row == shared[key], "ml_label_review_overlap_mismatch")
    shared_lifecycle = {(row["kind"], row["row_id"]): row for row in source["lifecycle"]}
    for row in value["lifecycle"]:
        key = row["kind"], row["row_id"]
        require(key not in shared_lifecycle or row == shared_lifecycle[key], "ml_label_review_overlap_mismatch")
    historical = {(row["table"], row["row_id"]): parse(canonical(row["data"]).decode()) for row in base_manifest["rows"]}
    holds = {}
    for claim_id in inventory["claim_pins"]:
        roots = {("material_claims", claim_id)}
        current_refs = closure(index, roots)
        old_refs = closure(historical, roots)
        assessed_events = _assessed_events(historical, old_refs)
        codes = set()
        added_or_removed = current_refs ^ old_refs
        if added_or_removed:
            codes.add("label_source_inventory_changed" if any(key[0] in _SOURCE_TABLES for key in added_or_removed)
                      else "label_dependency_inventory_changed")
        for key in current_refs:
            table, _ = key
            row, old = index[key], historical.get(key)
            if key in held_sources:
                codes.add("label_current_source_held")
            if table in {"material_claims", "research_events"} and (
                    row["validity_status"] in HELD or row.get("review_status") == "rejected"):
                codes.add("label_current_result_held")
            if table == "claim_qc" and row["review_status"] != "approved":
                codes.add("label_current_result_held")
            if table == "materials" and _material_held(row):
                codes.add("label_current_material_held")
            if table == "paper_work_map" and row["review_status"] != "accepted":
                codes.add("label_source_binding_changed")
            if table == "research_events" and row["supersedes_id"] in assessed_events:
                codes.add("label_event_superseded")
            if old is None or not equal(_projection(table, row), _projection(table, old)):
                if table in {"papers", "works"}:
                    codes.add("label_source_identity_changed")
                elif table in _SOURCE_TABLES:
                    codes.add("label_source_binding_changed")
                elif table == "claim_qc":
                    codes.add("label_review_state_changed")
                else:
                    codes.add("label_scientific_content_changed")
        for example in lists["examples"]:
            if example["claim_id"] == claim_id:
                key = "ml_examples", example["example_id"]
                if not equal(_projection(key[0], index[key]), _projection(key[0], historical[key])):
                    codes.add("label_example_binding_changed")
        holds[claim_id] = sorted(codes)
    return {"claim_holds": holds}


def verify_label_observation(value, *, base_manifest, review_companion):
    """Negative-only replay. Caller independently verifies the review companion."""
    try:
        return _verify(value, base_manifest=base_manifest, review_companion=review_companion)
    except MlLabelObservationError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, UnicodeError, OverflowError):
        raise MlLabelObservationError("ml_label_observation_invalid") from None
