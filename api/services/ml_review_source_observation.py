"""Replayable private source observations, never reinstatement or read rights.

Only this new protocol uses these projections. Historical 0054/0064 documents
and their implementations remain unchanged. A self-contained observation is
not authentication of a live database, a reviewer or a source licence.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from services.research_release_spec import FKS, SPEC, TABLE_FIELDS

VERSION = "ml-review-source-observation/1.0.0"
MAX_BYTES = 16 * 1024 * 1024
MAX_ROWS = 4000
HELD = frozenset({"retracted", "withdrawn", "corrected", "disputed", "excluded"})
# Independent, versioned copies of the existing 0056 snapshot projection.
PAPER_FIELDS = (
    "id", "source", "arxiv_id", "doi", "external_id", "id_scheme", "related_paper_id",
    "title", "authors", "affiliations", "date_submitted", "date_published", "journal",
    "journal_abbrev", "publication_ref", "abstract", "categories", "material_family",
    "status", "retraction_date", "retraction_reason", "materials_extracted", "quality_flags",
    "credibility_tier", "paper_type",
)
WORK_FIELDS = ("id", "canonical_title", "canonical_doi", "canonical_arxiv_id",
               "publication_status", "available_at", "identity_metadata")
LIFECYCLE_FIELDS = {"id", "paper_id", "work_id", "revision", "predecessor_id",
    "old_snapshot_sha256", "snapshot_sha256", "prior_status", "observed_status",
    "event_kind", "record_sha256", "created_at"}
OWNED = {"research_events": (("event_evidence", "event_id"), ("snapshot_event_memberships", "event_id")),
         "material_claims": (("claim_source_occurrences", "claim_id"),),
         "papers": (("paper_work_map", "paper_id"),),
         "source_revisions": (("source_captures", "source_revision_id"),)}


class ReviewSourceError(ValueError):
    """Static bounded observation failure; never an empty successful lookup."""


def require(condition, reason="ml_review_source_unavailable"):
    if not condition:
        raise ReviewSourceError(reason)


def raw_sha(text):
    require(type(text) is str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse(text):
    # Import is lazy to preserve the pure module's API-only/offline boundary.
    from services.ml_review_projection import parse_sql_json
    return parse_sql_json(text)


def equal(left, right):
    """Lossless numeric equality without Python's True == 1 coercion."""
    if type(left) in {int, Decimal} and type(right) in {int, Decimal}:
        return left == right
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return set(left) == set(right) and all(equal(left[key], right[key]) for key in left)
    if type(left) is list:
        return len(left) == len(right) and all(equal(a, b) for a, b in zip(left, right, strict=True))
    return left == right


def pg_json(value):
    """Bounded parsed SQL JSON -> PostgreSQL jsonb::text (0056 only).

    jsonb keys use UTF-8 byte length then byte ordering. Decimal fixed notation
    preserves SQL numeric scale; this is not the 0067 recursive canonical form.
    """
    if type(value) is dict:
        keys = sorted(value, key=lambda key: (len(key.encode("utf-8")), key.encode("utf-8")))
        return "{" + ", ".join(json.dumps(key, ensure_ascii=False) + ": " + pg_json(value[key]) for key in keys) + "}"
    if type(value) is list:
        return "[" + ", ".join(pg_json(item) for item in value) + "]"
    if isinstance(value, Decimal):
        require(value.is_finite())
        return format(value, "f")
    require(value is None or type(value) in {str, bool, int})
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def lifecycle_record_sha(row):
    body = "{" + ",".join(json.dumps(key, ensure_ascii=False) + ":" + pg_json(row[key])
        for key in sorted(set(row) - {"created_at", "record_sha256"})) + "}"
    return raw_sha(body)


def account(budget, size):
    require(type(size) is int and size >= 0 and type(budget.get("bytes")) is int)
    require(budget["bytes"] + size <= MAX_BYTES, "ml_review_capture_byte_limit")
    budget["bytes"] += size


async def read_rows(db, table, identifiers, *, column=None, byte_budget, limit=MAX_ROWS):
    """Preflight bounded exact SQL text before hydrating any row body."""
    import sqlalchemy as sa

    from models.db import Base

    allowed = set(TABLE_FIELDS) | {"source_lifecycle_events", "scientific_result_subjects",
        "scientific_adjudication_requests", "scientific_result_decisions", "research_role_grants",
        "research_role_revocations", "users", "ml_feature_source_bindings"}
    require(table in allowed and type(limit) is int and 0 < limit <= MAX_ROWS)
    keys = sorted(set(str(value) for value in identifiers))
    require(len(keys) <= MAX_ROWS)
    if not keys:
        return []
    primary = "paper_id" if table == "paper_work_map" else "id"
    column = column or primary
    require(column in Base.metadata.tables[table].c)
    if table == "users":
        fields = ("id", "is_active", "email_verified", "is_admin")
    else:
        fields = sorted(TABLE_FIELDS[table]) if table in TABLE_FIELDS else None
    # PostgreSQL functions accept at most 100 arguments; the historical
    # material projection has more than 50 fields. Concatenate bounded pieces.
    body = ("(" + "||".join("jsonb_build_object(" + ",".join(
        "'" + key + "',t.\"" + key + "\"" for key in fields[start:start + 40]) + ")"
        for start in range(0, len(fields), 40)) + ")" if fields else "to_jsonb(t)")
    where = f't."{column}"::text IN :ids'
    params = {"ids": keys}
    sizes_query = sa.text(f'SELECT octet_length(({body})::text) FROM public."{table}" t WHERE {where} LIMIT {limit + 1}')
    sizes = (await db.execute(sizes_query.bindparams(sa.bindparam("ids", expanding=True)), params)).scalars().all()
    require(len(sizes) <= limit, "ml_review_capture_row_limit")
    require(sum(sizes) + byte_budget["bytes"] <= MAX_BYTES, "ml_review_capture_byte_limit")
    query = sa.text(f'SELECT t."{primary}"::text AS row_id, public.sclib_scientific_adjudication_canonical_v1({body}) AS row_text '
                    f'FROM public."{table}" t WHERE {where} ORDER BY t."{primary}"::text LIMIT {limit + 1}')
    rows = (await db.execute(query.bindparams(sa.bindparam("ids", expanding=True)), params)).mappings().all()
    require(len(rows) == len(sizes))
    result = []
    for row in rows:
        account(byte_budget, len(row["row_text"].encode("utf-8")) + len(row["row_id"]) + len(table) + 160)
        result.append({"table": table, "row_id": row["row_id"], "row_text": row["row_text"], "row_sha256": raw_sha(row["row_text"])})
    return result


def decode_rows(rows):
    from services.ml_review_projection import validate_row_wire
    require(type(rows) is list and len(rows) <= MAX_ROWS)
    keys, result = [], {}
    for wire in rows:
        row = validate_row_wire(wire)
        key = wire["table"], wire["row_id"]
        require(key[0] in TABLE_FIELDS or key[0] == "source_lifecycle_events")
        require(set(row) == (set(TABLE_FIELDS[key[0]]) if key[0] in TABLE_FIELDS else LIFECYCLE_FIELDS))
        if key[0] in SPEC:
            require(all(valid_field(row[field], declaration) for field, declaration in SPEC[key[0]]["fields"].items()),
                    "ml_review_source_field_type")
        if key[0] in {"research_events", "material_claims"}:
            require(row["validity_status"] in {"pending", "accepted", "disputed", "retracted", "excluded"},
                    "ml_review_source_governance_enum")
        if key[0] == "research_events":
            require(row["review_status"] in {"pending", "approved", "rejected"}, "ml_review_source_governance_enum")
        if key[0] == "paper_work_map":
            require(row["review_status"] in {"pending", "accepted", "rejected"}, "ml_review_source_governance_enum")
        if key[0] == "works":
            require(row["publication_status"] in {"active", "retracted", "withdrawn", "corrected", "unknown"},
                    "ml_review_source_governance_enum")
        require(row.get("paper_id" if key[0] == "paper_work_map" else "id") == key[1])
        keys.append(key)
        result[key] = row
    require(keys == sorted(set(keys)), "ml_review_source_row_inventory")
    return result


def valid_field(value, declaration):
    """Frozen SQL scalar semantics, without coercion or datetime string edits."""
    if value is None:
        return declaration["nullable"]
    kind = declaration["type"]
    if kind == "JSONB":
        return True  # Already parsed by the bounded lossless JSON validator.
    if kind == "BOOLEAN":
        return type(value) is bool
    if kind in {"INTEGER", "SMALLINT", "BIGINT"}:
        return type(value) is int
    if kind in {"FLOAT", "DOUBLE PRECISION"}:
        return type(value) in {int, Decimal}
    if kind == "UUID":
        return type(value) is str and str(UUID(value)) == value
    if kind == "DATE":
        return type(value) is str and date.fromisoformat(value).isoformat() == value
    if kind == "DATETIME":
        return type(value) is str and datetime.fromisoformat(value).tzinfo is not None
    if kind.startswith("ARRAY"):
        return type(value) is list
    if kind.startswith("VARCHAR("):
        return type(value) is str and len(value) <= int(kind[8:-1])
    return type(value) is str


def references(table, row):
    result = set()
    for children, parent, _ in FKS.get(table, ()):
        # Event-wide review provenance is governance, not this result's source.
        if table == "research_events" and "decision_artifact_id" in children:
            continue
        value = row.get(children[0])
        if all(row.get(child) is not None for child in children):
            result.add((parent, str(value)))
    return result


def closure(index, roots):
    found, pending = set(), set(roots)
    while pending:
        key = pending.pop()
        if key in found:
            continue
        require(key in index, "ml_review_source_missing_dependency")
        found.add(key)
        row = index[key]
        for fields, target, columns in FKS.get(key[0], ()):
            if key[0] == "research_events" and "decision_artifact_id" in fields:
                continue
            # PostgreSQL MATCH SIMPLE: any NULL disables that FK, not merely
            # its first column. Non-null composite bindings match every field.
            if all(row[field] is not None for field in fields):
                parent = (target, str(row[fields[0]]))
                require(parent in index and all(equal(row[field], index[parent][column])
                    for field, column in zip(fields, columns, strict=True)), "ml_review_source_composite_binding")
        pending.update(references(key[0], index[key]))
        for child, column in OWNED.get(key[0], ()):
            pending.update(ref for ref, row in index.items() if ref[0] == child and row[column] == key[1])
        pending -= found
        require(len(found) + len(pending) <= MAX_ROWS)
    return found


def input_roots(base_manifest, source_companion):
    result = {row["row_id"]: set() for row in base_manifest["rows"] if row["table"] == "ml_example_inputs"}
    for row in source_companion["bindings"]:
        require(row["example_input_id"] in result)
        result[row["example_input_id"]].update({("source_revisions", row["source_revision_id"]),
            ("source_captures", row["capture_id"]), ("evidence_artifacts", row["review_artifact_id"]),
            ("works", row["work_id"])})
    return result


async def capture_source_observation(db, *, base_manifest, source_companion, property_ids, byte_budget):
    import sqlalchemy as sa
    roots = {("event_properties", str(value)) for value in property_ids}
    for values in input_roots(base_manifest, source_companion).values():
        roots.update(values)
    found, pending = {}, roots
    while pending:
        require(len(found) + len(pending) <= MAX_ROWS)
        grouped = defaultdict(set)
        for table, identifier in pending:
            grouped[table].add(identifier)
        current = []
        for table, ids in sorted(grouped.items()):
            wires = await read_rows(db, table, ids, byte_budget=byte_budget)
            require({row["row_id"] for row in wires} == ids, "ml_review_source_missing_dependency")
            current.extend(wires)
        for table, ids in sorted(grouped.items()):
            for child, column in OWNED.get(table, ()):
                current.extend(await read_rows(db, child, ids, column=column, byte_budget=byte_budget))
        pending = set()
        for wire in current:
            key = wire["table"], wire["row_id"]
            require(key not in found or found[key] == wire)
            found[key] = wire
            pending.update(references(key[0], parse(wire["row_text"])))
        pending -= found.keys()
    lifecycle = []
    for (table, identifier), wire in sorted(list(found.items())):
        if table not in {"papers", "works"}:
            continue
        kind = "paper" if table == "papers" else "work"
        fields = PAPER_FIELDS if kind == "paper" else WORK_FIELDS
        expression = "jsonb_build_object(" + ",".join("'" + key + "',t.\"" + key + "\"" for key in fields) + ")"
        body = "jsonb_build_object('version','source-lifecycle-snapshot/1.0.0','kind',CAST(:kind AS text),'snapshot'," + expression + ")::text"
        length = await db.scalar(sa.text(f'SELECT octet_length({body}) FROM public."{table}" t WHERE id::text=:id'), {"kind": kind, "id": identifier})
        require(type(length) is int)
        account(byte_budget, length + 256)
        text = await db.scalar(sa.text(f'SELECT {body} FROM public."{table}" t WHERE id::text=:id'), {"kind": kind, "id": identifier})
        events = await read_rows(db, "source_lifecycle_events", [identifier], column=kind + "_id", byte_budget=byte_budget)
        ordered = sorted(events, key=lambda value: parse(value["row_text"])["revision"])
        for event in events:
            found[(event["table"], event["row_id"])] = event
        lifecycle.append({"kind": kind, "row_id": identifier, "snapshot_text": text,
            "snapshot_sha256": raw_sha(text), "event_ids": [row["row_id"] for row in ordered]})
    result = {"version": VERSION, "rows": [found[key] for key in sorted(found)], "lifecycle": lifecycle}
    verify_source_observation(result, base_manifest=base_manifest, source_companion=source_companion, property_ids=property_ids)
    return result


def _verify_source_observation(value, *, base_manifest, source_companion, property_ids):
    require(type(value) is dict and set(value) == {"version", "rows", "lifecycle"} and value["version"] == VERSION)
    index = decode_rows(value["rows"])
    property_roots = {str(identifier): {("event_properties", str(identifier))} for identifier in property_ids}
    inputs = input_roots(base_manifest, source_companion)
    all_roots = set().union(*property_roots.values(), *inputs.values()) if property_roots or inputs else set()
    expected = closure(index, all_roots)
    require({key for key in index if key[0] != "source_lifecycle_events"} == expected, "ml_review_source_complete_closure")
    require(type(value["lifecycle"]) is list)
    seen, used_events, held = [], set(), {}
    for item in value["lifecycle"]:
        require(type(item) is dict and set(item) == {"kind", "row_id", "snapshot_text", "snapshot_sha256", "event_ids"})
        require(item["kind"] in {"paper", "work"})
        key = ("papers" if item["kind"] == "paper" else "works", item["row_id"])
        require(key in index and raw_sha(item["snapshot_text"]) == item["snapshot_sha256"])
        fields = PAPER_FIELDS if item["kind"] == "paper" else WORK_FIELDS
        snapshot = {"version": "source-lifecycle-snapshot/1.0.0", "kind": item["kind"],
                    "snapshot": {field: index[key][field] for field in fields}}
        require(equal(parse(item["snapshot_text"]), snapshot) and pg_json(snapshot) == item["snapshot_text"], "ml_review_source_snapshot_mismatch")
        require(type(item["event_ids"]) is list and len(item["event_ids"]) <= MAX_ROWS and len(set(item["event_ids"])) == len(item["event_ids"]))
        previous = None
        for sequence, identifier in enumerate(item["event_ids"], 1):
            event_key = "source_lifecycle_events", identifier
            require(event_key in index and event_key not in used_events)
            event = index[event_key]
            require(event["record_sha256"] == lifecycle_record_sha(event), "ml_review_lifecycle_record_mismatch")
            require(event["event_kind"] in {"baseline_observed", "lifecycle_change", "catalogue_revision"})
            require(event[item["kind"] + "_id"] == key[1] and event["work_id" if item["kind"] == "paper" else "paper_id"] is None)
            require(type(event["revision"]) is int and event["revision"] == sequence)
            require(event["predecessor_id"] == (previous["id"] if previous else None))
            if previous:
                require(event["old_snapshot_sha256"] == previous["snapshot_sha256"] and event["prior_status"] == previous["observed_status"])
            else:
                require(event["observed_status"] in HELD or event["prior_status"] in HELD)
            previous = event
            used_events.add(event_key)
        status = index[key]["status" if item["kind"] == "paper" else "publication_status"].strip().lower()
        if previous:
            require(previous["snapshot_sha256"] == item["snapshot_sha256"] and previous["observed_status"] == status, "ml_review_lifecycle_head_mismatch")
        # Preserve the earlier negative-only policy. A recognized "unknown"
        # is not a positive source/temporal acceptance, but is not invented
        # negative history either; unchanged scientific/time gates still apply.
        held[key] = bool(previous) or status in HELD
        seen.append(key)
    require(seen == sorted(key for key in expected if key[0] in {"papers", "works"}), "ml_review_source_lifecycle_inventory")
    require(used_events == {key for key in index if key[0] == "source_lifecycle_events"})

    def reasons(roots):
        codes = set()
        for key in closure(index, roots):
            row = index[key]
            if held.get(key):
                codes.add("current_source_held")
            if key[0] in {"research_events", "material_claims"} and (
                row["validity_status"] in HELD or row.get("review_status") == "rejected"):
                codes.add("current_parent_result_held")
        return codes

    property_holds = {identifier: sorted(reasons(roots)) for identifier, roots in sorted(property_roots.items())}
    input_holds = {identifier: reasons(roots) for identifier, roots in inputs.items()}
    from services.research_release_manifest import canonical
    historical = {(row["table"], row["row_id"]): parse(canonical(row["data"]).decode())
                  for row in source_companion["source_rows"]}
    for binding in source_companion["bindings"]:
        codes = input_holds[binding["example_input_id"]]
        revision = index[("source_revisions", binding["source_revision_id"])]
        mapping = index.get(("paper_work_map", revision["paper_id"]))
        if not mapping or mapping["review_status"] != "accepted" or mapping["work_id"] != binding["work_id"]:
            codes.add("feature_source_binding_changed")
        refs = closure(index, inputs[binding["example_input_id"]])
        for key in refs:
            if key[0] in {"papers", "works"}:
                identity_fields = ({"source", "arxiv_id", "doi", "external_id", "id_scheme", "related_paper_id"}
                    if key[0] == "papers" else {"canonical_doi", "canonical_arxiv_id", "identity_metadata"})
                old = historical.get(key)
                if old is None or any(not equal(index[key][field], old[field]) for field in identity_fields):
                    codes.add("feature_source_identity_changed")
            if key[0] in {"source_revisions", "source_captures", "evidence_artifacts"}:
                old = historical.get(key)
                # A copied record_sha256 cannot conceal a changed row body.
                # Disclosure permissions do not establish scientific status.
                ignored = {"access", "license"} if key[0] == "evidence_artifacts" else set()
                actual = {field: item for field, item in index[key].items() if field not in ignored}
                prior = {field: item for field, item in old.items() if field not in ignored} if old else None
                if prior is None or not equal(actual, prior):
                    codes.add("feature_source_binding_changed")
    return {"property_source_holds": property_holds,
            "input_source_holds": {identifier: sorted(codes) for identifier, codes in sorted(input_holds.items())}}


def verify_source_observation(value, *, base_manifest, source_companion, property_ids):
    """Replay the closed source inventory; no captured boolean is authority."""
    try:
        require(type(value) is dict and set(value) == {"version", "rows", "lifecycle"})
        require(type(value["rows"]) is list and len(value["rows"]) <= MAX_ROWS
                and type(value["lifecycle"]) is list and len(value["lifecycle"]) <= MAX_ROWS)
        total = 0
        for row in value["rows"]:
            require(type(row) is dict and type(row.get("row_text")) is str)
            total += len(row["row_text"].encode("utf-8"))
            require(total <= MAX_BYTES, "ml_review_source_byte_limit")
        for row in value["lifecycle"]:
            require(type(row) is dict and type(row.get("snapshot_text")) is str)
            total += len(row["snapshot_text"].encode("utf-8"))
            require(total <= MAX_BYTES, "ml_review_source_byte_limit")
        return _verify_source_observation(value, base_manifest=base_manifest,
            source_companion=source_companion, property_ids=property_ids)
    except ReviewSourceError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, UnicodeError, OverflowError):
        raise ReviewSourceError("ml_review_source_invalid") from None
