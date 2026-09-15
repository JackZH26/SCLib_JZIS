"""Portable, bounded ML08 canary kernel; no ORM, network, source reads or writes.

Only implementation-owned package resources are read for source observations.
Context bytes are supplied and hashed by the caller, never followed by reference.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

from services import ml_pilot_accounting as pilot
from services import ml_pilot_documents as documents

VERSION = "ml08-canary/1.2.0"
SCOPE = "private_replayable_human_asserted_pilot_not_scientific_acceptance"
HASH = documents.HASH
MAX_BYTES = 32 * 1024 * 1024
MAX_CONTEXTS = 6000
MAX_CONTEXT_BYTES = 8 * 1024 * 1024
MAX_EVIDENCE_BYTES = 64 * 1024 * 1024
AUTHORITY = {
    "scientific_acceptance": False,
    "scientific_pilot_accepted": False,
    "human_identity_authenticated": False,
    "reviewer_independence_authenticated": False,
    "actual_event_existence_verified": False,
    "source_permissions_verified": False,
    "source_content_scientifically_verified": False,
    "public_release": False,
    "ml_training_approved": False,
    "run_authorization_granted": False,
}
SOURCE_FILES = (
    "ml_pilot_canary.py",
    "ml_pilot_accounting.py",
    "ml_pilot_documents.py",
    "ml08_pilot.schema.json",
)
_ESCAPES = re.compile(r'["\\\x00-\x1f]')


def require(condition, code="pilot_canary_invalid"):
    if not condition:
        raise ValueError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def implementation():
    # Runtime identity is deliberately not self-asserted inside the portable
    # artifact. Exact byte replay still requires matching selected source files.
    return {
        "version": VERSION,
        "scope": "selected_installed_canary_sources_not_runtime_attestation",
        "files": {name: sha(Path(__file__).with_name(name).read_bytes()) for name in SOURCE_FILES},
    }


def _bounded_tree(value):
    pending, active, scheduled, size = [(value, 0, False)], set(), 1, 0
    while pending:
        item, depth, leaving = pending.pop()
        if leaving:
            active.remove(id(item))
            continue
        require(depth <= documents.MAX_DEPTH and scheduled <= documents.MAX_NODES)
        if type(item) in {dict, list}:
            require(id(item) not in active)
            active.add(id(item))
            scheduled += 2 * len(item) if type(item) is dict else len(item)
            require(scheduled <= documents.MAX_NODES)
            size += 2 + max(0, len(item) - 1) + (len(item) if type(item) is dict else 0)
            pending.append((item, depth, True))
            if type(item) is dict:
                require(all(type(key) is str for key in item))
                pending.extend((part, depth + 1, False) for pair in item.items() for part in pair)
            else:
                pending.extend((part, depth + 1, False) for part in item)
        elif type(item) is str:
            require(len(item) <= MAX_BYTES)
            size += 2
            for offset in range(0, len(item), 32768):
                chunk = item[offset : offset + 32768]
                size += len(chunk.encode("utf-8"))
                size += sum(
                    1 if match.group() in '"\\\b\t\n\f\r' else 5
                    for match in _ESCAPES.finditer(chunk)
                )
                require(size <= MAX_BYTES)
        elif item is None:
            size += 4
        elif type(item) is bool:
            size += 4 if item else 5
        elif type(item) is int:
            require(item.bit_length() <= MAX_BYTES * 4)
            size += len(str(item))
        elif type(item) is float:
            require(math.isfinite(item))
            size += len(repr(item))
        else:
            raise ValueError("pilot_canary_json_type")
        require(size <= MAX_BYTES)


def canonical(value):
    try:
        _bounded_tree(value)
        raw = pilot.canonical(value)
        require(len(raw) <= MAX_BYTES)
        return raw
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise ValueError("pilot_canary_json_invalid") from None


def digest(value):
    return sha(canonical(value))


def loads(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES)
    documents._preparse(raw)
    value = pilot._loads(raw.decode("utf-8"))
    require(canonical(value) == raw, "pilot_canary_canonical_required")
    return value


def evidence_hashes(reviews):
    """Every permitted-context assertion in all revisions, not licence checks."""
    hashes = {
        result["source"]["context_sha256"]
        for review in reviews
        for result in review["results"]
        if result["source"]["context_reference"]
        and result["source"]["context_sha256"]
        and result["source"]["access_status"] == "permitted"
    }
    require(len(hashes) <= MAX_CONTEXTS)
    require(all(type(pin) is str and HASH.fullmatch(pin) for pin in hashes))
    return sorted(hashes)


def event_index(selection, reviews):
    latest = {(row["candidate_id"], row["role"]): row for row in reviews}
    entries = []
    for candidate in selection["candidates"]:
        cid = candidate["candidate_id"]
        primary = latest[cid, "primary"]
        secondary, arbitration = latest.get((cid, "secondary")), latest.get((cid, "arbitration"))
        current = (
            arbitration
            and secondary
            and set(arbitration["compares_review_ids"])
            == {primary["review_id"], secondary["review_id"]}
        )
        effective = arbitration if current else primary
        entries.append(
            {
                "candidate_id": cid,
                "primary_review_id": primary["review_id"],
                "secondary_review_id": None if secondary is None else secondary["review_id"],
                "current_arbitration_review_id": arbitration["review_id"] if current else None,
                "effective_review_id": effective["review_id"],
                "outcome": effective["outcome"],
                "result_ids": [row["result_id"] for row in effective["results"]],
            }
        )
    return entries


def compile_canary(
    selection, reviews, *, selection_sha256, review_log_sha256, input_pins, source, evidence
):
    require(
        type(input_pins) is dict
        and set(input_pins)
        == {name + "_file_sha256" for name in ("selection", "reviews", "protocol")}
    )
    require(
        all(
            type(pin) is str and HASH.fullmatch(pin)
            for pin in [*input_pins.values(), selection_sha256, review_log_sha256]
        )
    )
    require(
        pilot.selection_hash(selection) == selection_sha256
        and pilot.review_hash(reviews) == review_log_sha256,
        "pilot_logical_anchor_mismatch",
    )
    report = pilot.validate(selection, reviews, expected_selection_sha256=selection_sha256)
    require(
        not report["errors"]
        and report["ready_for_review"]
        and report["final_gaps"] == ["conclusion_not_submitted"],
        "pilot_review_package_incomplete",
    )
    require(
        selection["protocol_sha256"] == input_pins["protocol_file_sha256"],
        "pilot_protocol_bytes_mismatch",
    )
    require(type(evidence) is list and len(evidence) <= MAX_CONTEXTS)
    require(
        all(
            type(item) is dict
            and set(item) == {"sha256", "size_bytes"}
            and type(item["size_bytes"]) is int
            and 0 < item["size_bytes"] <= MAX_CONTEXT_BYTES
            for item in evidence
        )
    )
    require(sum(item["size_bytes"] for item in evidence) <= MAX_EVIDENCE_BYTES)
    require(
        [item["sha256"] for item in evidence] == evidence_hashes(reviews),
        "pilot_context_inventory_mismatch",
    )
    require(source == implementation(), "pilot_implementation_changed")
    bundle = {
        "version": VERSION,
        "scope": SCOPE,
        "input_pins": input_pins,
        "selection_sha256": selection_sha256,
        "review_log_sha256": review_log_sha256,
        "implementation": source,
        "selection": selection,
        "reviews_including_superseded": reviews,
        "event_accounting": event_index(selection, reviews),
        "accounting": report,
        "accounting_component": "services.ml_pilot_accounting_documentary_only",
        "context_integrity_scope": "enclosing_canary_hashes_explicit_supplied_bytes_not_content_support_or_permission",
        "context_inventory": evidence,
        "context_bytes_embedded": False,
        "authority": dict(AUTHORITY),
        "training_execution": "disabled",
    }
    canonical(bundle)
    return bundle
