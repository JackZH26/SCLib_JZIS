"""Exact material representatives over an unchanged RPS release and SQL inventory.

The compiler does not choose highest-scoring actions, grant disclosure or turn
parent-event approval into scientific acceptance. Publication is a separate
three-account operation over the complete newly compiled payload.
"""
from __future__ import annotations

import json
from collections import defaultdict

from services import priority_public_bundle as public
from services import research_distribution as distribution
from services import research_distribution_contract as contract
from services.research_priority import digest

VERSION = "discovery-scientific-projection/1.0.0"
SELECTION_VERSION = "discovery-scientific-selection/1.0.0"
MAX_MATERIALS = 25
MAX_ASSESSMENTS = 200
MAX_PROPERTIES = 100
MAX_SELECTION_BYTES = 2 * 1024 * 1024
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024
DISCLAIMER = "Policy-based research priority; empirical calibration pending"
AUTHORITY = {"scientific_acceptance": False, "ml_training_approved": False,
             "public_release_authorized": False}
REGISTRY = {
    "formation_energy_per_atom": ("eV/atom", "stability"),
    "energy_above_hull": ("eV/atom", "stability"),
    "band_gap": ("eV", "electronic"),
    "dos_at_fermi": ("states/eV/formula_unit", "electronic"),
    "electron_phonon_lambda": ("1", "pairing"),
    "omega_log": ("K", "pairing"),
    "phonon_min_frequency": ("THz", "stability"),
    "superfluid_stiffness": ("K", "coherence"),
}
GROUPS = ("stability", "electronic", "pairing", "coherence", "geometry", "competing_order")
AVAILABILITY = {"reported", "unknown", "not_computed", "not_applicable", "conflicted"}


class DiscoveryProjectionError(ValueError):
    """A static projection failure, never a source-bearing error message."""


def require(value):
    if not value:
        raise DiscoveryProjectionError("discovery_projection_rejected")


def _object(value, keys):
    require(type(value) is dict and set(value) == set(keys))


def _assessment_reference(value):
    _object(value, {"id", "revision", "sha256"})
    require(type(value["id"]) is str and contract._ID.fullmatch(value["id"])
            and type(value["revision"]) is int and value["revision"] > 0)
    contract._hash(value["sha256"])


def _row_reference(value, *, tables):
    _object(value, {"table", "row_id", "row_sha256"})
    require(type(value["table"]) is str and value["table"] in tables)
    contract.capsule.row_reference(value["table"], value["row_id"])
    contract._uuid(value["row_id"])
    contract._hash(value["row_sha256"])


def capture_selection(selection, expected_selection_sha256):
    """Copy every caller-owned field before any database await."""
    raw = contract._bounded(selection)
    require(len(raw) <= MAX_SELECTION_BYTES)
    result = json.loads(raw)
    require(digest(result) == contract._hash(expected_selection_sha256))
    _object(result, {"version", "release_manifest_sha256", "public_bundle_sha256", "representatives"})
    require(result["version"] == SELECTION_VERSION)
    for key in ("release_manifest_sha256", "public_bundle_sha256"):
        contract._hash(result[key])
    choices = result["representatives"]
    require(type(choices) is list and 0 < len(choices) <= MAX_MATERIALS)
    property_ids, seen = set(), []
    for choice in choices:
        _object(choice, {"material", "assessment", "structure", "rationale", "alternatives", "cells"})
        _object(choice["material"], {"id", "sha256"})
        require(type(choice["material"]["id"]) is str and contract._ID.fullmatch(choice["material"]["id"]))
        contract._hash(choice["material"]["sha256"])
        seen.append(choice["material"]["id"])
        _assessment_reference(choice["assessment"])
        if choice["structure"] is not None:
            _row_reference(choice["structure"], tables={"structure_records"})
        require(type(choice["rationale"]) is str and 0 < len(choice["rationale"]) <= 2000
                and bool(choice["rationale"].strip()) and "\x00" not in choice["rationale"])
        require(type(choice["alternatives"]) is list and len(choice["alternatives"]) < MAX_ASSESSMENTS)
        for alternative in choice["alternatives"]:
            _assessment_reference(alternative)
        require(type(choice["cells"]) is list and len(choice["cells"]) == len(REGISTRY))
        keys = []
        for cell in choice["cells"]:
            _object(cell, {"property_key", "availability", "reason_code", "result_refs", "evidence_refs"})
            require(type(cell["property_key"]) is str and cell["property_key"] in REGISTRY)
            require(type(cell["availability"]) is str and cell["availability"] in AVAILABILITY)
            distribution._code(cell["reason_code"])
            keys.append(cell["property_key"])
            for name, tables, maximum in (("result_refs", {"event_properties"}, 8),
                    ("evidence_refs", {"event_evidence", "evidence_artifacts", "research_runs"}, 20)):
                references = cell[name]
                require(type(references) is list and len(references) <= maximum)
                for ref in references:
                    _row_reference(ref, tables=tables)
                identities = [(ref["table"], ref["row_id"]) for ref in references]
                require(identities == sorted(set(identities)))
            property_ids.update(ref["row_id"] for ref in cell["result_refs"])
            if cell["availability"] in {"not_computed", "not_applicable", "conflicted"}:
                require(bool(cell["evidence_refs"]))
        require(keys == sorted(REGISTRY))
    require(seen == sorted(set(seen)) and len(property_ids) <= MAX_PROPERTIES)
    return result


def representative_assessments(public_bundle, selection):
    """Complete explicit membership; the compiler never chooses a representative."""
    release = public_bundle["release"]
    require(0 < len(release["assessments"]) <= MAX_ASSESSMENTS)
    require(selection["release_manifest_sha256"] == release["manifest_sha256"]
            and selection["public_bundle_sha256"] == public_bundle["bundle_sha256"])
    groups = defaultdict(dict)
    rows = {row["id"]: row for row in public_bundle["rows"]}
    entries = {entry["assessment"]["id"]: entry for entry in release["assessments"]}
    for entry in entries.values():
        assessment = entry["assessment"]
        groups[assessment["material"]["id"]][assessment["id"]] = {
            "id": assessment["id"], "revision": assessment["revision"], "sha256": digest(assessment)}
    require({choice["material"]["id"] for choice in selection["representatives"]} == set(groups))
    chosen = []
    for choice in selection["representatives"]:
        material_id, ref = choice["material"]["id"], choice["assessment"]
        require(ref["id"] in groups[material_id] and ref == groups[material_id][ref["id"]])
        assessment = entries[ref["id"]]["assessment"]
        require(choice["material"] == assessment["material"])
        expected = [value for key, value in sorted(groups[material_id].items()) if key != ref["id"]]
        require(choice["alternatives"] == expected)
        chosen.append({"selection": choice, "assessment": assessment,
            "assessment_row": rows[ref["id"]], "assessment_review": entries[ref["id"]]["review"],
            "alternate_rows": [rows[item["id"]] for item in expected]})
    return chosen


def registry_capabilities(rows=()):
    counts = {key: 0 for key in REGISTRY}
    for row in rows:
        for cell in row["cells"]:
            counts[cell["property_key"]] += len(cell["observations"])
    return {"version": VERSION, "registry_version": "rv2/1", "groups": list(GROUPS),
        "scientific_properties": [{"property_key": key, "unit": unit, "group": group,
            "storage_supported": True, "quantity_projection_supported": True,
            "exact_scientific_review_supported": key == "phonon_min_frequency",
            "scientific_review_profile": "sampled-phonon-minimum-review/1.0.0" if key == "phonon_min_frequency" else None,
            "scientific_review_relations": ["exact"] if key == "phonon_min_frequency" else [],
            "populated_observations": counts[key]} for key, (unit, group) in sorted(REGISTRY.items())],
        "planned_groups": ["geometry", "competing_order"],
        "unregistered_dictionary_fields": "planned_not_database_properties",
        "rps_fields": {"kind": "policy_assessment_not_scientific_ground_truth",
            "keys": ["rps_score", "rps_physical", "rps_gain", "rps_action"]}}


async def build_projection(db, *, distribution_package_id, expected_distribution_record_sha256,
        expected_inventory_sha256, public_bundle, selection, expected_selection_sha256):
    """Build from actual retained SQL rows; never publish or accept a review."""
    from services.discovery_scientific_cells import build_observations

    selection = capture_selection(selection, expected_selection_sha256)
    bundle = json.loads(contract._bounded(public_bundle))
    public.verify_public_bundle(bundle, expected_bundle_sha256=selection["public_bundle_sha256"],
        expected_release_sha256=selection["release_manifest_sha256"])
    chosen = representative_assessments(bundle, selection)
    await distribution._read_session(db)
    package, inventory = await distribution._package(db, distribution_package_id)
    require(package["record_sha256"] == contract._hash(expected_distribution_record_sha256)
            and package["inventory_sha256"] == contract._hash(expected_inventory_sha256)
            and package["release_manifest_sha256"] == selection["release_manifest_sha256"]
            and package["public_bundle_sha256"] == selection["public_bundle_sha256"])
    await distribution._current_sources(db, inventory)
    dependencies = {(item["table"], item["row_id"]): item for item in inventory["dependencies"]}
    bindings = {item["artifact_id"]: item for item in inventory["artifact_bindings"]}
    artifacts = {item["id"]: item for item in bundle["release"]["artifacts"]}
    rows, scientific_pins, material_ids = [], {}, set()

    def resolve(ref):
        found = dependencies.get((ref["table"], ref["row_id"]))
        require(found is not None and found["row_sha256"] == ref["row_sha256"])
        return found["projection"]

    for item in chosen:
        choice, assessment = item["selection"], item["assessment"]
        identities = {}
        for name in ("material", "state"):
            binding = bindings.get(assessment[name]["id"])
            require(binding is not None and binding["artifact_sha256"] == assessment[name]["sha256"]
                    and binding["artifact_kind"] == name and binding["identity"] is not None)
            identities[name] = binding["identity"]
            resolve(binding["identity"])
        material_id, state_id = identities["material"]["row_id"], identities["state"]["row_id"]
        require(material_id not in material_ids)
        material_ids.add(material_id)
        structure_id = None
        if choice["structure"] is not None:
            structure = resolve(choice["structure"])
            require(structure["material_id"] == material_id)
            structure_id = choice["structure"]["row_id"]
        # A source in the same sealed package is not necessarily applicable to
        # this candidate. Missingness/conflict declarations need a direct
        # selected-context source or producer, never unrelated ancestor prose.
        context_events = {identifier: dependency["projection"]
            for (name, identifier), dependency in dependencies.items()
            if name == "research_events" and
            (dependency["projection"]["material_id"], dependency["projection"]["state_id"],
             dependency["projection"]["structure_id"]) == (material_id, state_id, structure_id)}
        evidence_ids = {identifier for (name, identifier), dependency in dependencies.items()
            if name == "event_evidence" and dependency["projection"]["event_id"] in context_events
            and dependency["projection"]["link_type"] == "source"}
        run_ids = {event["producer_run_id"] for event in context_events.values()} - {None}
        artifact_ids = {dependencies[("event_evidence", identifier)]["projection"]["artifact_id"]
            for identifier in evidence_ids}
        for identifier in run_ids:
            run = dependencies.get(("research_runs", identifier))
            require(run is not None)
            artifact_ids.update(run["projection"][key] for key in ("input_manifest_id", "output_manifest_id"))
        applicable_evidence = {"event_evidence": evidence_ids, "research_runs": run_ids,
            "evidence_artifacts": artifact_ids - {None}}
        candidates = defaultdict(set)
        for (name, identifier), dependency in dependencies.items():
            if name != "event_properties":
                continue
            prop = dependency["projection"]
            event = dependencies.get(("research_events", prop["event_id"]))
            require(event is not None)
            event = event["projection"]
            if (event["material_id"], event["state_id"], event["structure_id"]) == (material_id, state_id, structure_id):
                if prop["property_key"] in REGISTRY:
                    candidates[prop["property_key"]].add(identifier)
        refs = [ref for cell in choice["cells"] for ref in cell["result_refs"]]
        observed = (await build_observations(db, inventory=inventory, property_refs=refs,
            material_id=material_id, state_id=state_id, structure_id=structure_id)) if refs else {
                "observations": [], "scientific_pins": {}, "dependency_ids": []}
        by_id = {value["property"]["id"]: value for value in observed["observations"]}
        require(set(by_id) == {ref["row_id"] for ref in refs})
        scientific_pins.update(observed["scientific_pins"])
        cells = []
        for cell in choice["cells"]:
            key, status = cell["property_key"], cell["availability"]
            require({ref["row_id"] for ref in cell["result_refs"]} == candidates[key])
            values = [by_id[ref["row_id"]] for ref in cell["result_refs"]]
            require(all(value["property"]["property_key"] == key for value in values))
            for ref in cell["evidence_refs"]:
                resolve(ref)
                require(ref["row_id"] in applicable_evidence[ref["table"]])
            quantified = [value for value in values if value["quantity"]["relation"] != "unreported"]
            if status == "reported":
                require(bool(quantified))
            elif status == "conflicted":
                require(len(quantified) >= 2 and len({value["property"]["component_key"] for value in quantified}) == 1)
            else:
                require(not quantified)
                if status == "unknown":
                    require(cell["reason_code"] == ("source_does_not_report_value" if values else "no_matching_registered_result"))
            cells.append({**cell, "unit": REGISTRY[key][0], "group": REGISTRY[key][1],
                "observations": values, "availability_basis": "explicit_review_required_declaration"
                    if status in {"not_computed", "not_applicable", "conflicted"} else "registered_result_inventory"})
        rows.append({"material": identities["material"], "state": identities["state"], "structure": choice["structure"],
            "representative": choice["assessment"], "selection_rationale": choice["rationale"],
            "assessment": item["assessment_row"], "assessment_review": item["assessment_review"],
            "state_context": artifacts[assessment["state"]["id"]]["content"],
            "profile_assignment": artifacts[assessment["profile_assignment"]["id"]]["content"],
            "alternatives": [{"reference": ref, "assessment": row} for ref, row in zip(choice["alternatives"], item["alternate_rows"], strict=True)],
            "cells": cells})
    require(len(scientific_pins) <= MAX_PROPERTIES)
    payload = {"version": VERSION, "disclaimer": DISCLAIMER, "comparison_scope": "same_frozen_campaign_budget_policy_release",
        "evaluation_protocol": "https://github.com/JackZH26/SCLib_JZIS/issues/78",
        "base": {"distribution_package_id": str(package["id"]), "distribution_record_sha256": package["record_sha256"],
            "inventory_sha256": package["inventory_sha256"], "release_id": package["release_id"],
            "release_manifest_sha256": package["release_manifest_sha256"], "public_bundle_sha256": package["public_bundle_sha256"]},
        "campaign": bundle["release"]["campaign"], "campaign_sha256": bundle["release"]["campaign_hash"],
        "policy_sha256": bundle["release"]["policy_hash"], "selection": selection,
        "selection_sha256": expected_selection_sha256, "rows": rows, "capabilities": registry_capabilities(rows), **AUTHORITY}
    require(len(contract._bounded(payload)) <= MAX_PAYLOAD_BYTES)
    return {"payload": payload, "selection_sha256": expected_selection_sha256,
        "dependency_ids": sorted(item["dependency_id"] for item in inventory["dependencies"]),
        "scientific_pins": scientific_pins}
