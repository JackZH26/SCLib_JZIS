"""Read-only exact-result evidence preparation, not an adjudication contract.

The descriptor hashes complete current SQL rows and a bounded reverse inventory.
Only explicit typed quantities and non-content locators leave this service.
Raw/context/metadata/source text and source URLs never enter its public DTOs.
This private snapshot neither authenticates scientific review nor opens rights.
"""
from __future__ import annotations

import math
from collections import defaultdict
from uuid import UUID

import sqlalchemy as sa

from models.db import Base
from services import research_release_manifest as closure
from services.research_access import ResearchAccessDenied, active_grant, active_user
from services.research_freeze import _fetch

VERSION = "scientific-result-dossier/1.0.0"
COUNT_BASIS = ("Canonical non-Tc, non-RPS properties; review status belongs to each parent event. "
               "This page is not a reviewed-result total.")
MAX_ROWS = 1000
MAX_ARTIFACTS = 200
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
AUTHORITY = {"scientific_accepted": False, "ml_training_approved": False,
             "public_release": False, "review_write_available": False}


class ScientificDossierError(ValueError):
    """Static private-read failure; never raw source/error contents."""


def require(condition, code):
    if not condition:
        raise ScientificDossierError(code)


def identifier(value):
    require(type(value) is str or isinstance(value, UUID), "invalid_result_identifier")
    try:
        result = UUID(str(value))
    except ValueError:
        raise ScientificDossierError("invalid_result_identifier") from None
    require(str(result) == str(value), "canonical_result_identifier_required")
    return result


async def _session(db):
    require(not (db.new or db.dirty or db.deleted), "clean_scientific_read_session_required")
    require(await db.scalar(sa.text("SHOW transaction_isolation")) in {"repeatable read", "serializable"},
            "stable_scientific_read_snapshot_required")
    require(await db.scalar(sa.text("SHOW TimeZone")) == "UTC", "utc_scientific_read_required")
    # LIMIT bounds hydrated rows, not reverse-scan cost; require a real SQL cap.
    timeout = await db.scalar(sa.text("SELECT setting::bigint FROM pg_settings WHERE name='statement_timeout'"))
    require(type(timeout) is int and 0 < timeout <= 10000, "bounded_scientific_read_timeout_required")


async def capabilities(db, *, actor_user_id):
    await _session(db)
    await active_user(db, actor_user_id)
    roles = []
    for role in ("curator", "reviewer", "publisher"):
        try:
            await active_grant(db, actor_user_id, role=role)
        except ResearchAccessDenied:
            continue
        roles.append(role)
    return {"version": "scientific-review-capabilities/1.0.0", "roles": roles,
            "can_read": bool(set(roles) & {"curator", "reviewer"}), "review_write_available": False}


async def _admit(db, actor_user_id):
    result = await capabilities(db, actor_user_id=actor_user_id)
    if not result["can_read"]:
        raise ResearchAccessDenied("scientific_review_read_role_required")


def _text(value, maximum):
    require(type(value) is str and 0 < len(value) <= maximum
            and all(ord(char) >= 32 and ord(char) != 127 for char in value), "unsupported_scientific_display_text")
    return value


def _number(value):
    require(value is None or type(value) in {int, float} and math.isfinite(value), "nonfinite_scientific_display_value")
    return value


def _supported(properties, events):
    return sa.and_(~properties.c.property_key.startswith("rps_", autoescape=True), properties.c.property_key != "tc",
                   properties.c.property_key != "tc_kelvin", events.c.event_type != "priority_assessment")


async def list_results(db, *, actor_user_id, after=None, limit=25):
    await _admit(db, actor_user_id)
    require(type(limit) is int and 1 <= limit <= 50, "scientific_review_page_limit")
    after = identifier(after) if after is not None else None
    properties, events, materials = (Base.metadata.tables[name] for name in
                                    ("event_properties", "research_events", "materials"))
    # Formula is natively VARCHAR(200), not an unbounded source-text field.
    statement = sa.select(properties.c.id.label("property_id"), events.c.id.label("event_id"),
        events.c.revision.label("event_revision"), events.c.material_id, materials.c.formula,
        properties.c.property_key, properties.c.unit, events.c.knowledge_origin,
        events.c.review_status, events.c.validity_status).select_from(
            properties.join(events, properties.c.event_id == events.c.id)
            .join(materials, events.c.material_id == materials.c.id)).where(_supported(properties, events))
    if after is not None:
        statement = statement.where(properties.c.id > after)
    rows = (await db.execute(statement.order_by(properties.c.id).limit(limit + 1))).mappings().all()
    items = []
    for row in rows[:limit]:
        items.append({"property_id": str(row["property_id"]), "event_id": str(row["event_id"]),
            "event_revision": row["event_revision"], "material_id": _text(row["material_id"], 100),
            "formula": _text(row["formula"], 512), "property_key": _text(row["property_key"], 50),
            "unit": _text(row["unit"], 40), "knowledge_origin": _text(row["knowledge_origin"], 20),
            "review_status": _text(row["review_status"], 20), "validity_status": _text(row["validity_status"], 20)})
    return {"version": "scientific-review-queue/1.0.0", "items": items,
            "next_cursor": items[-1]["property_id"] if len(rows) > limit else None,
            "has_more": len(rows) > limit, "total_count": None, "count_basis": COUNT_BASIS}


def _owned_relations(name):
    # A result dossier is not an entire source-snapshot freeze. Enumerate the
    # exact occurrences of reached events, never all other snapshot members.
    # The frozen 0054 policy remains unchanged and independently versioned.
    if name == "source_snapshots":
        return ()
    relations = closure.owned_relations(name)
    if name == "research_events":
        return (*relations, ("snapshot_event_memberships", "event_id"))
    return relations


async def _collect(db, property_id):
    """Current event-local FK/owned closure, not a frozen integrity capsule."""
    pending, captured, expanded, budget = {("event_properties", str(property_id))}, {}, set(), {}
    while pending:
        requested = pending - captured.keys()
        require(len(requested) + len(captured) <= MAX_ROWS, "scientific_dossier_row_limit")
        grouped = defaultdict(set)
        for name, row_id in requested:
            grouped[name].add(row_id)
        for name, ids in sorted(grouped.items()):
            rows = await _fetch(db, name, identifiers=ids, byte_budget=budget)
            require({row["row_id"] for row in rows} == ids, "scientific_dossier_reference_unavailable")
            captured.update({(name, row["row_id"]): row for row in rows})
        current = pending - expanded
        owned = defaultdict(set)
        discovered = set()
        for name, row_id in current:
            for child, field in _owned_relations(name):
                owned[(child, field)].add(row_id)
        for (name, field), ids in sorted(owned.items()):
            for row in await _fetch(db, name, column=field, identifiers=ids, byte_budget=budget):
                key = name, row["row_id"]
                captured[key] = row
                discovered.add(key)
        require(len(captured) <= MAX_ROWS, "scientific_dossier_row_limit")
        dependencies = set()
        for key in current:
            dependencies.update(closure.dependencies(key[0], captured[key]["data"]))
        expanded.update(current)
        # Newly discovered owned children can themselves have owned relations.
        pending = (dependencies | discovered) - expanded
    return captured


def _locator(value):
    if type(value) is dict:
        value = value.get("source_locator", value)
        if (type(value) is dict and set(value) >= {"line", "start_byte", "end_byte"}
                and all(type(value[key]) is int for key in ("line", "start_byte", "end_byte"))
                and 1 <= value["line"] <= 1_000_000
                and 0 <= value["start_byte"] <= value["end_byte"] <= 64 * 1024 * 1024):
            return {key: value[key] for key in ("line", "start_byte", "end_byte")}
    return {"scope": "locator_not_disclosed"}


async def result_dossier(db, *, actor_user_id, property_id):
    await _admit(db, actor_user_id)
    property_id = identifier(property_id)
    captured = await _collect(db, property_id)
    def row(name, row_id):
        return captured[name, row_id]["data"]
    prop = row("event_properties", str(property_id))
    event = row("research_events", prop["event_id"])
    require(not prop["property_key"].startswith("rps_") and prop["property_key"] not in {"tc", "tc_kelvin"}
            and event["event_type"] != "priority_assessment", "unsupported_scientific_review_result")
    material, state = row("materials", event["material_id"]), row("material_states", event["state_id"])
    structure = row("structure_records", event["structure_id"]) if event["structure_id"] else None
    run = row("research_runs", event["producer_run_id"]) if event["producer_run_id"] else None
    artifact_ids = sorted(row_id for name, row_id in captured if name == "evidence_artifacts")
    require(len(artifact_ids) <= MAX_ARTIFACTS, "scientific_dossier_artifact_limit")
    links = defaultdict(list)
    for (name, _), record in captured.items():
        if name == "event_evidence" and record["data"]["artifact_id"]:
            links[record["data"]["artifact_id"]].append(record["data"])
    sources = []
    for artifact_id in artifact_ids:
        artifact, evidence = row("evidence_artifacts", artifact_id), links[artifact_id]
        require(len(evidence) <= 200, "scientific_dossier_locator_limit")
        evidence = sorted(evidence, key=lambda item: item["id"])
        sources.append({"artifact_id": artifact_id, "kind": artifact["kind"], "access": artifact["access"],
            "hash_status": artifact["hash_status"], "bytes_sha256": artifact["bytes_sha256"],
            "evidence_link_ids": [item["id"] for item in evidence], "locators": [_locator(item["locator"]) for item in evidence]})
    from services.scientific_result_impact import inspect_result_impact
    impact = await inspect_result_impact(db, property_id=property_id, event_id=UUID(event["id"]))
    inventory = [captured[key] for key in sorted(captured)]
    target = {"property_id": str(property_id), "event_id": event["id"], "event_revision": event["revision"]}
    descriptor = {"version": VERSION, "target": target, "rows": inventory, "impact": impact,
                  "review_write_available": False}
    warnings = {"source_text_not_disclosed", "descriptor_is_not_scientific_review",
                "parent_event_review_does_not_adjudicate_selected_property", "review_decision_workflow_unavailable"}
    if state["pressure_status"] == "not_reported": warnings.add("pressure_not_reported")
    if state["temperature_k"] is None: warnings.add("temperature_not_reported")
    if not structure or structure["structure_kind"] != "coordinates": warnings.add("coordinate_structure_unavailable")
    if run and run["run_kind"] == "extraction": warnings.add("producer_is_extraction_not_native_calculation")
    if any(source["access"] in {"restricted", "unknown"} for source in sources): warnings.add("restricted_or_unknown_source_access")
    if any(source["hash_status"] != "verified" for source in sources): warnings.add("source_bytes_not_verified")
    result = {"version": VERSION, "descriptor_sha256": closure.digest(descriptor), "target": target,
        "material": {"id": _text(material["id"], 100), "formula": _text(material["formula"], 512)},
        "result": {key: _number(prop[key]) if key in {"value", "lower", "upper"} else _text(prop[key], 120)
                   for key in ("property_key", "registry_version", "component_key", "relation", "value", "lower", "upper", "unit")},
        "event": {key: event[key] for key in ("event_type", "knowledge_origin", "review_status", "validity_status")},
        "state": {key: _number(state[key]) if key in {"pressure_gpa", "temperature_k"} else state[key]
                  for key in ("id", "resolution", "pressure_status", "pressure_gpa", "temperature_role", "temperature_k")},
        "structure": {key: structure[key] for key in ("id", "structure_kind", "artifact_id")} if structure else None,
        "run": {key: run[key] for key in ("id", "run_kind", "status")} if run else None,
        "sources": sources, "inventory": {"row_count": len(inventory), "artifact_count": len(artifact_ids),
                                           "sha256": closure.digest(inventory)},
        "warnings": sorted(warnings), "impact": impact, "authority": dict(AUTHORITY)}
    require(len(closure.canonical(result)) <= MAX_RESPONSE_BYTES, "scientific_dossier_response_limit")
    return result
