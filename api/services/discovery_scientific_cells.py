"""Exact source-derived Discovery observations, not redistribution authority.

The caller supplies an already verified distribution inventory and owns the
stable database transaction. Every selected row is bridged to the independently
captured current 0067 scientific subject. This adapter neither updates research
rows nor aggregates different components, converts units or invents support.
Only a current, exact positive scientific-result decision may mark its narrow
sampled-frequency proposition accepted. Other values remain recorded values.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from services import ml_review_projection as bridge
from services import research_distribution_contract as distribution
from services import research_release_manifest as capsule
from services import scientific_result_effects as effects
from services.research_publication import PublicationUnavailable, _current_catalogue
from services.scientific_result_dossier import _locator, _session
from services.scientific_result_subject import capture_result_subject

VERSION = "discovery-scientific-observation/1.0.0"
MAX_PROPERTIES = 100
MAX_BYTES = 16 * 1024 * 1024
MAX_SECONDS = 10
REGISTRY_VERSION = "rv2/1"
PROPERTY_UNITS = {
    "formation_energy_per_atom": "eV/atom",
    "energy_above_hull": "eV/atom",
    "band_gap": "eV",
    "dos_at_fermi": "states/eV/formula_unit",
    "electron_phonon_lambda": "1",
    "omega_log": "K",
    "phonon_min_frequency": "THz",
    "superfluid_stiffness": "K",
}
_DEPENDENCY_FIELDS = {
    "dependency_id", "table", "row_id", "row_sha256", "record_sha256",
    "bytes_sha256", "projection", "capsule_manifest_sha256s",
}
_INVENTORY_FIELDS = {
    "version", "release_id", "release_manifest_sha256", "public_bundle_sha256",
    "bindings_sha256", "artifact_bindings", "dependencies", *distribution.AUTHORITY,
}
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class DiscoveryScientificCellError(ValueError):
    """Static fail-closed error; no raw source, private rationale or path."""


def _require(condition, code="discovery_scientific_cells_invalid"):
    if not condition:
        raise DiscoveryScientificCellError(code)


def _hash(value):
    _require(type(value) is str and _HASH.fullmatch(value) is not None)
    return value


def _identifier(value):
    _require(type(value) is str or type(value) is UUID)
    result = str(UUID(str(value)))
    _require(result == str(value))
    return result


def _material(value):
    _require(type(value) is str and 0 < len(value) <= 100 and value == value.strip()
             and not any(ord(char) < 32 for char in value))
    value.encode("utf-8")
    return value


def _inventory(value):
    # Detach before any await. The outer verifier owns artifact bytes and root
    # admission; revalidate the normalized row inventory rather than trusting
    # arbitrary client projections or an unchecked record_sha256.
    _require(type(value) is dict and set(value) == _INVENTORY_FIELDS)
    value = json.loads(distribution._bounded(value))
    _require(value["version"] == distribution.VERSION
             and all(value[key] is False for key in distribution.AUTHORITY))
    for key in ("release_manifest_sha256", "public_bundle_sha256", "bindings_sha256"):
        _hash(value[key])
    entries = value["dependencies"]
    _require(type(entries) is list and 0 < len(entries) <= distribution.MAX_DEPENDENCIES)
    rows, identifiers, projections = {}, {}, {}
    previous = None
    for entry in entries:
        _require(type(entry) is dict and set(entry) == _DEPENDENCY_FIELDS)
        key = entry["table"], entry["row_id"]
        _require(key not in rows)
        envelope = {"table": key[0], "row_id": key[1], "row_sha256": entry["row_sha256"],
                    "data": entry["projection"]}
        verified = capsule._rows([envelope])
        _require(set(verified) == {key})
        identifier = capsule.digest({"version": distribution.DEPENDENCY_VERSION,
            "table": key[0], "row_id": key[1], "row_sha256": entry["row_sha256"]})
        _require(entry["dependency_id"] == identifier and (previous is None or previous < identifier))
        previous = identifier
        data = envelope["data"]
        _require(entry["record_sha256"] == data.get("record_sha256")
                 and entry["bytes_sha256"] == (data["bytes_sha256"]
                    if key[0] in {"evidence_artifacts", "source_captures"} else None))
        memberships = entry["capsule_manifest_sha256s"]
        _require(type(memberships) is list and len(memberships) <= distribution.MAX_CAPSULES
                 and memberships == sorted(set(memberships)))
        for sha in memberships:
            _hash(sha)
        rows[key], identifiers[key] = envelope, identifier
        projections[key] = {field: data[field] for field in bridge.projection_fields(key[0])}
    return rows, identifiers, projections


def _quantity(prop):
    key = prop["property_key"]
    _require(key in PROPERTY_UNITS and prop["registry_version"] == REGISTRY_VERSION
             and prop["unit"] == PROPERTY_UNITS[key])
    component = prop["component_key"]
    _require(type(component) is str and 0 < len(component) <= 120 and component == component.strip()
             and not any(ord(char) < 32 for char in component))
    relation = prop["relation"]
    value, lower, upper = (prop[name] for name in ("value", "lower", "upper"))
    for number in (value, lower, upper):
        _require(number is None or (type(number) in {int, float} and math.isfinite(number)))
        if key not in {"formation_energy_per_atom", "phonon_min_frequency"} and number is not None:
            _require(number >= 0)
    shapes = {
        "exact": value is not None and lower is None and upper is None,
        "interval": value is None and lower is not None and upper is not None and lower <= upper,
        "lt": value is None and lower is None and upper is not None,
        "le": value is None and lower is None and upper is not None,
        "gt": value is None and lower is not None and upper is None,
        "ge": value is None and lower is not None and upper is None,
        "unreported": value is None and lower is None and upper is None,
    }
    _require(type(relation) is str and shapes.get(relation) is True)
    return {"relation": relation, "value": value, "lower": lower, "upper": upper, "unit": prop["unit"]}


def _observation(rows, reached, property_id, status):
    def row(table, identifier):
        return rows[(table, identifier)]["data"]

    def pin(table, identifier):
        return {"id": identifier, "row_sha256": rows[(table, identifier)]["row_sha256"]}

    def artifact(identifier):
        if identifier is None:
            return None
        data = row("evidence_artifacts", identifier)
        return {**pin("evidence_artifacts", identifier), "kind": data["kind"],
                "bytes_sha256": data["bytes_sha256"], "hash_status": data["hash_status"]}

    prop = row("event_properties", property_id)
    event_id = prop["event_id"]
    event = row("research_events", event_id)
    state_id = event["state_id"]
    state = row("material_states", state_id)
    structure_id, run_id = event["structure_id"], event["producer_run_id"]
    structure = row("structure_records", structure_id) if structure_id else None
    run = row("research_runs", run_id) if run_id else None
    sources, occurrences = [], []
    for table, identifier in sorted(reached):
        data = row(table, identifier)
        if table == "event_evidence":
            sources.append({"table": table, **pin(table, identifier),
                "owner_event_id": data["event_id"],
                "relation_scope": "selected_event" if data["event_id"] == event_id else "forward_dependency",
                "link_type": data["link_type"], "artifact": artifact(data["artifact_id"]),
                "input_event_id": data["input_event_id"], "input_property_id": data["input_property_id"],
                "input_claim_id": data["input_claim_id"], "locator": _locator(data["locator"])})
        elif table == "snapshot_event_memberships":
            occurrences.append({"table": table, **pin(table, identifier),
                "relation_scope": "event_snapshot_membership", "event_id": data["event_id"],
                "snapshot_id": data["snapshot_id"], "locator": _locator(data["locator"])})
        elif table == "claim_source_occurrences":
            occurrences.append({"table": table, **pin(table, identifier),
                "relation_scope": "forward_claim_source_occurrence", "claim_id": data["claim_id"],
                "source_revision_id": data["source_revision_id"], "capture_id": data["capture_id"],
                "locator": _locator(data["locator"])})
    accepted = any(scope["scope"] == "scientific_result" and scope["effective_status"] == "accepted"
                   and scope["scientific_scope_accepted"] is True for scope in status["scopes"])
    quantity = _quantity(prop)
    _require(not accepted or (prop["property_key"] == "phonon_min_frequency"
             and quantity["relation"] == "exact"), "discovery_scientific_acceptance_scope_invalid")
    return {
        "version": VERSION,
        "property": {**pin("event_properties", property_id), "property_key": prop["property_key"],
                     "registry_version": prop["registry_version"], "component_key": prop["component_key"]},
        "quantity": quantity,
        "event": {**pin("research_events", event_id), "revision": event["revision"],
                  "event_type": event["event_type"], "knowledge_origin": event["knowledge_origin"]},
        "material": pin("materials", event["material_id"]),
        "state": {**pin("material_states", state_id), "resolution": state["resolution"],
            "pressure_status": state["pressure_status"], "pressure_gpa": state["pressure_gpa"],
            "temperature_role": state["temperature_role"], "temperature_k": state["temperature_k"],
            "context_sha256": state["context_sha256"], "source_artifact": artifact(state["source_artifact_id"])},
        "sample": pin("research_samples", state["sample_id"]) if state["sample_id"] else None,
        "structure": ({**pin("structure_records", structure_id), "structure_kind": structure["structure_kind"],
                       "artifact_id": structure["artifact_id"]} if structure else None),
        "run": ({**pin("research_runs", run_id), "run_kind": run["run_kind"], "status": run["status"],
                 "input_manifest": artifact(run["input_manifest_id"]),
                 "output_manifest": artifact(run["output_manifest_id"])} if run else None),
        "sources": sources, "source_occurrences": occurrences,
        "review": {"subject_sha256": status["subject_sha256"],
                   "status_revision_sha256": status["revision_sha256"], "scopes": status["scopes"]},
        "normalization": {"status": "not_asserted", "reason_code": "normalization_not_established_by_registry_unit"},
        "scientific_scope_accepted": accepted, "ml_training_approved": False, "public_release_authorized": False,
    }


async def build_observations(db, *, inventory, property_refs, material_id, state_id, structure_id):
    """Read and bind up to 100 exact results under one bounded stable snapshot.

    A valid old inventory is a required caller precondition, not an approval.
    No result is dropped on a hold, missing dependency or unresolved numerical
    bridge: the complete construction fails. Parent/global and source vetoes
    also apply to results with no adjudication history.
    """
    try:
        material_id = _material(material_id)
        state_id = _identifier(state_id)
        structure_id = _identifier(structure_id) if structure_id is not None else None
        _require(type(property_refs) in {list, tuple} and 0 < len(property_refs) <= MAX_PROPERTIES)
        refs = []
        for value in property_refs:
            _require(type(value) is dict and set(value) == {"table", "row_id", "row_sha256"}
                     and value["table"] == "event_properties")
            refs.append((_identifier(value["row_id"]), _hash(value["row_sha256"])))
        _require(len({identifier for identifier, _ in refs}) == len(refs))
        refs.sort()
        rows, identifiers, projections = _inventory(inventory)
        for identifier, sha in refs:
            key = "event_properties", identifier
            _require(key in rows and rows[key]["row_sha256"] == sha)
            prop = rows[key]["data"]
            _quantity(prop)
            event = rows[("research_events", prop["event_id"])]["data"]
            _require((event["material_id"], event["state_id"], event["structure_id"])
                     == (material_id, state_id, structure_id), "discovery_scientific_identity_mismatch")
        async with asyncio.timeout(MAX_SECONDS):
            await _session(db)
            closures, subjects, used, size = {}, {}, set(), 0
            for identifier, _ in refs:
                subject = await capture_result_subject(db, identifier)
                size += len(subject.text.encode("utf-8"))
                _require(size <= MAX_BYTES, "discovery_scientific_cells_byte_limit")
                body = bridge.parse_subject(subject.text, expected_sha256=subject.sha256)
                roots = {("event_properties", identifier)}
                if body["native_import"]:
                    roots.update(("evidence_artifacts", item["artifact_id"])
                                 for item in body["native_import"]["source_files"])
                reached = bridge._closure(projections, roots)
                match = bridge.bridge_frozen_subject({key: rows[key] for key in reached},
                    property_id=identifier, subject_text=subject.text, expected_subject_sha256=subject.sha256)
                _require(match["status"] == "matched", "discovery_scientific_subject_not_current")
                held, _ = await effects._sources(db, subject.data)
                _require(not held, "discovery_scientific_source_held")
                closures[identifier], subjects[identifier] = reached, subject.sha256
                used.update(reached)
            public_rows = [rows[key] for key in sorted(used) if key[0] in {"materials", "papers", "works"}]
            _require(len(public_rows) <= 1000)
            await _current_catalogue(db, {"manifest": {"rows": public_rows}})
            statuses = {}
            for start in range(0, len(refs), effects.MAX_RESULTS):
                statuses.update(await effects.resolve_result_statuses(db,
                    [identifier for identifier, _ in refs[start:start + effects.MAX_RESULTS]]))
            _require(set(statuses) == set(subjects))
            for identifier, status in statuses.items():
                _require(status["property_id"] == identifier and status["subject_sha256"] == subjects[identifier]
                         and status["ml_training_approved"] is False and status["public_release_authorized"] is False)
                _require(not any(scope["effective_status"] in effects.BLOCKED for scope in status["scopes"]),
                         "discovery_scientific_review_held")
            result = {"observations": [_observation(rows, closures[identifier], identifier, statuses[identifier])
                                       for identifier, _ in refs],
                      "scientific_pins": statuses, "dependency_ids": sorted(identifiers[key] for key in used)}
            encoded = distribution._bounded(result)
            _require(len(encoded) <= MAX_BYTES, "discovery_scientific_cells_byte_limit")
            return json.loads(encoded)
    except DiscoveryScientificCellError:
        raise
    except PublicationUnavailable:
        raise DiscoveryScientificCellError("discovery_scientific_catalogue_held") from None
    except (SQLAlchemyError, ValueError, TypeError, KeyError, AttributeError, OverflowError,
            UnicodeError, RecursionError, TimeoutError):
        raise DiscoveryScientificCellError("discovery_scientific_cells_unavailable") from None
