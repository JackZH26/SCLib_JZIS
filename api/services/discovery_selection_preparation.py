"""Read-only curator choices over one exact registered distribution.

Preparation is not registration, disclosure or scientific acceptance. Uploaded
public-bundle text is data only: no paths/providers are opened. The original
compiler and governance writer remain the final authority on chosen results.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict

from services import discovery_main_barrier as barrier
from services import discovery_projection_governance as governance
from services import discovery_scientific_projection as projection
from services import priority_public_bundle as public
from services import research_distribution as distribution
from services import research_distribution_contract as contract
from services.discovery_scientific_cells import _quantity
from services.research_access import active_grant
from services.research_priority import digest

VERSION = "discovery-selection-preparation/1.0.0"
MAX_BUNDLE_BYTES = 16 * 1024 * 1024
MAX_CONTEXT_BYTES = 8 * 1024 * 1024
MAX_PREPARED_BYTES = 64 * 1024 * 1024
MAX_CANDIDATE_PROPERTIES = 5000
MAX_CANDIDATE_EVIDENCE = 5000
AUTHORITY = {
    **governance.AUTHORITY,
    "public_release_authorized": False,
    "registration_performed": False,
}


def require(value):
    governance.require(value, "discovery_selection_preparation_rejected")


def _bounded(value, maximum):
    text = contract._bounded(value)
    require(len(text) <= maximum)
    return text


def _text_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _preflight(text):
    """Bound nested uploaded JSON before the recursive JSON decoder runs."""
    depth = nodes = 0
    quoted = escaped = primitive = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char.isspace() or char in ",:":
            primitive = False
            continue
        if char in "}]":
            depth -= 1
            require(depth >= 0)
            primitive = False
            continue
        if char == '"':
            nodes += 1
            quoted, primitive = True, False
        elif char in "{[":
            depth += 1
            nodes += 1
            primitive = False
        elif not primitive:
            nodes += 1
            primitive = True
        require(depth <= contract.MAX_DEPTH and nodes <= contract.MAX_NODES)
    require(not quoted and depth == 0)


def capture_source(source):
    require(
        type(source) is dict
        and set(source)
        == {"distribution_package_id", "public_bundle_json", "expected_public_bundle_text_sha256"}
    )
    identifier = str(distribution._uuid(source["distribution_package_id"]))
    text, sha = (
        source["public_bundle_json"],
        contract._hash(source["expected_public_bundle_text_sha256"]),
    )
    require(
        type(text) is str
        and len(text) <= MAX_BUNDLE_BYTES
        and len(text.encode("utf-8")) <= MAX_BUNDLE_BYTES
        and _text_hash(text) == sha
    )
    # The same closed canonical text used by the standalone bundle verifier.
    # Equality also refuses duplicates, trailing bytes and noncanonical floats.
    _preflight(text)
    bundle = public.strict_json(text.encode("utf-8"))
    require(type(bundle) is dict)
    require(_bounded(bundle, MAX_BUNDLE_BYTES).decode() == text)
    return {
        "distribution_package_id": identifier,
        "public_bundle_json": text,
        "expected_public_bundle_text_sha256": sha,
    }, bundle


async def access(db, *, actor_user_id):
    await governance._session(db)
    actor = await active_grant(db, actor_user_id, role="curator")
    return {
        "version": VERSION,
        "actor_user_id": str(actor["user_id"]),
        "actor_grant_id": str(actor["id"]),
        "can_prepare_selection": True,
        **AUTHORITY,
    }


async def _context(db, *, actor_user_id, source):
    source, bundle = capture_source(source)
    admitted = await access(db, actor_user_id=actor_user_id)
    package, inventory = await distribution._package(db, source["distribution_package_id"])
    public.verify_public_bundle(
        bundle,
        expected_bundle_sha256=package["public_bundle_sha256"],
        expected_release_sha256=package["release_manifest_sha256"],
    )
    await distribution._current_sources(db, inventory)
    release = bundle["release"]
    require(
        release["id"] == package["release_id"]
        and 0 < len(release["assessments"]) <= projection.MAX_ASSESSMENTS
    )
    artifacts = {item["id"]: item for item in release["artifacts"]}
    bindings = {item["artifact_id"]: item for item in inventory["artifact_bindings"]}
    rows = {
        (item["table"], item["row_id"]): {
            "table": item["table"],
            "row_id": item["row_id"],
            "row_sha256": item["row_sha256"],
            "data": item["projection"],
        }
        for item in inventory["dependencies"]
    }
    assessment_rows = {item["id"]: item for item in bundle["rows"]}
    materials, native_ids, used_properties, used_evidence = {}, {}, set(), set()
    structures_by_material, events_by_material, properties_by_event, evidence_by_event = (
        defaultdict(list) for _ in range(4)
    )
    for (name, identifier), item in sorted(rows.items()):
        data = item["data"]
        if name == "structure_records":
            structures_by_material[data["material_id"]].append((identifier, data))
        elif name == "research_events":
            events_by_material[data["material_id"]].append((identifier, data))
        elif name == "event_properties" and data["property_key"] in projection.REGISTRY:
            properties_by_event[data["event_id"]].append((identifier, data))
        elif name == "event_evidence" and data["link_type"] == "source":
            evidence_by_event[data["event_id"]].append((identifier, data))

    def identity(ref, kind):
        entry, artifact = bindings.get(ref["id"]), artifacts.get(ref["id"])
        require(
            entry is not None
            and artifact is not None
            and entry["artifact_kind"] == kind
            and entry["artifact_sha256"] == artifact["sha256"] == ref["sha256"]
            and entry["identity"] is not None
        )
        require(
            entry["identity"]["table"] == ("materials" if kind == "material" else "material_states")
        )
        contract._identity(artifact, entry, bindings, artifacts, rows)
        return entry["identity"]

    def reference(name, identifier):
        return {
            "table": name,
            "row_id": identifier,
            "row_sha256": rows[(name, identifier)]["row_sha256"],
        }

    for entry in release["assessments"]:
        a = entry["assessment"]
        material, state = identity(a["material"], "material"), identity(a["state"], "state")
        descriptor_id, native_id = a["material"]["id"], material["row_id"]
        require(native_id not in native_ids or native_ids[native_id] == descriptor_id)
        native_ids[native_id] = descriptor_id
        if descriptor_id not in materials:
            structures = [{"reference": None, "structure_kind": "not_selected"}]
            structures += [
                {
                    "reference": reference("structure_records", identifier),
                    "structure_kind": data["structure_kind"],
                }
                for identifier, data in structures_by_material[native_id]
            ]
            materials[descriptor_id] = {
                "descriptor": a["material"],
                "material": material,
                "assessments": [],
                "structures": structures,
                "results": [],
                "declaration_evidence": [],
            }
        materials[descriptor_id]["assessments"].append(
            {
                "reference": {"id": a["id"], "revision": a["revision"], "sha256": digest(a)},
                "assessment": assessment_rows[a["id"]],
                "state": state,
                "state_context": artifacts[a["state"]["id"]]["content"],
            }
        )
    require(0 < len(materials) <= projection.MAX_MATERIALS)
    for m in materials.values():
        m["assessments"].sort(key=lambda item: item["reference"]["id"])
        states = {item["state"]["row_id"] for item in m["assessments"]}
        events = {
            identifier: data
            for identifier, data in events_by_material[m["material"]["row_id"]]
            if data["state_id"] in states
        }
        evidence = {}
        for identifier, event in events.items():

            def add_evidence(name, target, *, event=event, evidence=evidence):
                if target is not None:
                    key = (event["state_id"], event["structure_id"] or "", name, target)
                    require((name, target) in rows)
                    used_evidence.add(key)
                    require(len(used_evidence) <= MAX_CANDIDATE_EVIDENCE)
                    evidence[key] = {
                        "state_id": event["state_id"],
                        "structure_id": event["structure_id"],
                        "reference": reference(name, target),
                    }

            for target, data in properties_by_event[identifier]:
                used_properties.add(target)
                require(len(used_properties) <= MAX_CANDIDATE_PROPERTIES)
                m["results"].append(
                    {
                        "reference": reference("event_properties", target),
                        "property_key": data["property_key"],
                        "registry_version": data["registry_version"],
                        "component_key": data["component_key"],
                        "quantity": _quantity(data),
                        "state_id": event["state_id"],
                        "structure_id": event["structure_id"],
                        "event": {
                            "id": identifier,
                            "row_sha256": rows[("research_events", identifier)]["row_sha256"],
                            "revision": event["revision"],
                            "knowledge_origin": event["knowledge_origin"],
                        },
                    }
                )
            for target, data in evidence_by_event[identifier]:
                add_evidence("event_evidence", target)
                add_evidence("evidence_artifacts", data["artifact_id"])
            run = event["producer_run_id"]
            if run:
                add_evidence("research_runs", run)
                for key in ("input_manifest_id", "output_manifest_id"):
                    add_evidence("evidence_artifacts", rows[("research_runs", run)]["data"][key])
        m["results"].sort(key=lambda item: item["reference"]["row_id"])
        m["declaration_evidence"] = [evidence[key] for key in sorted(evidence)]
    context = {
        "version": VERSION,
        "actor_user_id": admitted["actor_user_id"],
        "actor_grant_id": admitted["actor_grant_id"],
        "distribution_package_id": str(package["id"]),
        "distribution_record_sha256": package["record_sha256"],
        "inventory_sha256": package["inventory_sha256"],
        "public_bundle_sha256": package["public_bundle_sha256"],
        "public_bundle_text_sha256": source["expected_public_bundle_text_sha256"],
        "release_manifest_sha256": package["release_manifest_sha256"],
        "campaign": release["campaign"],
        "materials": [materials[key] for key in sorted(materials)],
        "quantity_basis": "frozen_inventory_not_current_scientific_acceptance",
        **AUTHORITY,
    }
    raw = _bounded(context, MAX_CONTEXT_BYTES)
    # Clients hash these exact UTF-8 bytes, never JavaScript-reserialized
    # floating-point quantities (e.g. Python's 0.0 or 1e-07).
    return (
        {
            "version": VERSION,
            "context_json": raw.decode(),
            "context_sha256": hashlib.sha256(raw).hexdigest(),
            **AUTHORITY,
        },
        context,
        bundle,
    )


async def selection_context(db, *, actor_user_id, source):
    # Full source capture occurs before the first await, including for callers
    # which bypass the HTTP DTO. No caller-owned container remains live.
    source, _ = capture_source(source)
    async with asyncio.timeout(25):
        result, _, _ = await _context(db, actor_user_id=actor_user_id, source=source)
        return result


def capture_choices(choices, *, selection_version=projection.SELECTION_VERSION):
    require(type(selection_version) is str and selection_version in projection.VERSION_PAIRS)
    is_v2 = selection_version == projection.SELECTION_VERSION_V2
    raw = _bounded(choices, projection.MAX_SELECTION_BYTES)
    result = json.loads(raw)
    require(type(result) is list and 0 < len(result) <= projection.MAX_MATERIALS)
    seen = []
    for choice in result:
        require(
            type(choice) is dict
            and set(choice)
            == {"material_id", "assessment_id", "structure_id", "rationale", "cells"}
            | ({"main_barrier"} if is_v2 else set())
        )
        if is_v2:
            barrier.validate_shape(choice["main_barrier"], property_keys=projection.REGISTRY)
        require(
            all(
                type(choice[k]) is str and contract._ID.fullmatch(choice[k])
                for k in ("material_id", "assessment_id")
            )
        )
        if choice["structure_id"] is not None:
            distribution._uuid(choice["structure_id"])
        require(
            type(choice["rationale"]) is str
            and 0 < len(choice["rationale"]) <= 2000
            and bool(choice["rationale"].strip())
            and "\x00" not in choice["rationale"]
        )
        require(type(choice["cells"]) is list and len(choice["cells"]) == len(projection.REGISTRY))
        require(
            [c.get("property_key") if type(c) is dict else None for c in choice["cells"]]
            == sorted(projection.REGISTRY)
        )
        for c in choice["cells"]:
            require(
                set(c) == {"property_key", "availability", "reason_code", "evidence_refs"}
                and type(c["availability"]) is str
                and c["availability"] in projection.AVAILABILITY
                and type(c["evidence_refs"]) is list
                and len(c["evidence_refs"]) <= 20
            )
            distribution._code(c["reason_code"])
            for ref in c["evidence_refs"]:
                projection._row_reference(
                    ref, tables={"event_evidence", "evidence_artifacts", "research_runs"}
                )
        seen.append(choice["material_id"])
    require(seen == sorted(set(seen)))
    return result


def compile_selection(context, choices, *, selection_version=projection.SELECTION_VERSION):
    choices = capture_choices(choices, selection_version=selection_version)
    require(
        [c["material_id"] for c in choices] == [m["descriptor"]["id"] for m in context["materials"]]
    )
    selected = []
    for m, choice in zip(context["materials"], choices, strict=True):
        options = {a["reference"]["id"]: a for a in m["assessments"]}
        require(choice["assessment_id"] in options)
        chosen = options[choice["assessment_id"]]
        structures = {
            s["reference"]["row_id"] if s["reference"] else None: s["reference"]
            for s in m["structures"]
        }
        require(choice["structure_id"] in structures)

        def applicable(
            item, state_id=chosen["state"]["row_id"], structure_id=choice["structure_id"]
        ):
            return item["state_id"] == state_id and item["structure_id"] == structure_id

        allowed = [e["reference"] for e in m["declaration_evidence"] if applicable(e)]
        cells = []
        for c in choice["cells"]:
            require(all(ref in allowed for ref in c["evidence_refs"]))
            cells.append(
                {
                    **c,
                    "result_refs": [
                        r["reference"]
                        for r in m["results"]
                        if applicable(r) and r["property_key"] == c["property_key"]
                    ],
                }
            )
        if selection_version == projection.SELECTION_VERSION_V2:
            barrier.validate_context(
                choice["main_barrier"], result=chosen["assessment"]["result"],
                cells=[{**cell, "observations": [r for r in m["results"]
                    if applicable(r) and r["property_key"] == cell["property_key"]]}
                    for cell in cells],
            )
        selected.append(
            {
                "material": m["descriptor"],
                "assessment": chosen["reference"],
                "structure": structures[choice["structure_id"]],
                "rationale": choice["rationale"],
                "alternatives": [a["reference"] for a in m["assessments"] if a is not chosen],
                "cells": cells,
                **({"main_barrier": choice["main_barrier"]}
                   if selection_version == projection.SELECTION_VERSION_V2 else {}),
            }
        )
    selection = {
        "version": selection_version,
        "release_manifest_sha256": context["release_manifest_sha256"],
        "public_bundle_sha256": context["public_bundle_sha256"],
        "representatives": selected,
    }
    return projection.capture_selection(selection, digest(selection))


async def prepare_selection(
    db, *, actor_user_id, source, expected_context_sha256, request_key, choices,
    selection_version=projection.SELECTION_VERSION,
):
    source, _ = capture_source(source)
    choices = capture_choices(choices, selection_version=selection_version)
    expected = contract._hash(expected_context_sha256)
    key = distribution._key(request_key)
    async with asyncio.timeout(25):
        captured, context, bundle = await _context(db, actor_user_id=actor_user_id, source=source)
        governance._match(captured["context_sha256"] == expected)
        selection = compile_selection(context, choices, selection_version=selection_version)
        arguments = {
            "distribution_package_id": context["distribution_package_id"],
            "expected_distribution_record_sha256": context["distribution_record_sha256"],
            "expected_inventory_sha256": context["inventory_sha256"],
            "public_bundle": bundle,
            "selection": selection,
            "expected_selection_sha256": digest(selection),
        }
        built = await projection.build_projection(db, **arguments)
        payload_json = _bounded(built["payload"], projection.MAX_PAYLOAD_BYTES).decode()
        payload_sha256 = _text_hash(payload_json)
        request_sha256 = governance._sha(
            {"version": governance.VERSION, "operation": "register", **arguments}
        )
        command = {**arguments, "request_key": key, "expected_payload_sha256": payload_sha256}
        preview_json = _bounded({**command, "dry_run": True}, 20 * 1024 * 1024).decode()
        commit_json = _bounded({**command, "dry_run": False}, 20 * 1024 * 1024).decode()
        result = {
            "version": VERSION,
            "actor_user_id": context["actor_user_id"],
            "actor_grant_id": context["actor_grant_id"],
            "context_sha256": expected,
            "request_key": key,
            "request_sha256": request_sha256,
            "payload_json": payload_json,
            "payload_sha256": payload_sha256,
            "selection_sha256": arguments["expected_selection_sha256"],
            "preview_json": preview_json,
            "preview_sha256": _text_hash(preview_json),
            "commit_json": commit_json,
            "commit_sha256": _text_hash(commit_json),
            **AUTHORITY,
        }
        _bounded(result, MAX_PREPARED_BYTES)
        return result
