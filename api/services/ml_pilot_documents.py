"""Bounded private ML08 document intake, independent of filesystem and HTTP.

Caller-supplied anchors establish consistency only. They must be bound to a
separately authenticated registration before any scientific signoff workflow.
This module neither opens context references nor authenticates their rights.
"""
from __future__ import annotations

import hashlib
import io
import re

from services import ml_pilot_accounting as accounting

VERSION = "ml08-document-intake/1.0.0"
MAX_BYTES = accounting.MAX_BYTES
MAX_NODES = 400_000
MAX_DEPTH = 64
HASH = re.compile(r"[0-9a-f]{64}\Z")
AUTHORITY = {"scientific_acceptance": False, "scientific_pilot_accepted": False,
    "human_identity_authenticated": False, "reviewer_independence_authenticated": False,
    "source_permissions_verified": False, "actual_event_existence_verified": False,
    "public_release": False, "ml_training_approved": False, "run_authorization_granted": False}


class PilotDocumentError(ValueError):
    """Static errors; no input paths, source text, identifiers or raw values."""


def require(condition, code):
    if not condition:
        raise PilotDocumentError(code)


def _preparse(raw):
    """Version-owned pilot JSON budget; no dataset/model/ORM import required."""
    depth = nodes = 0
    quoted = escaped = atom = False
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
            continue
        if byte == 34:
            nodes += 1
            quoted, atom = True, False
        elif byte in (91, 123):
            nodes += 1
            depth += 1
            atom = False
        elif byte in (93, 125):
            depth -= 1
            atom = False
        elif byte in (32, 9, 10, 13, 44, 58):
            atom = False
        elif not atom:
            nodes += 1
            atom = True
        require(0 <= depth <= MAX_DEPTH and nodes <= MAX_NODES, "pilot_document_json_invalid")


def canonical(value):
    """Encode a parsed/documentary tree, keeping this protocol's 8 MiB budget.

    Unlike the larger audited-dataset codec this is a standalone documentary
    boundary; importing that compiler would eagerly import models.db.
    """
    try:
        raw = accounting.canonical(value)
        require(len(raw) <= MAX_BYTES, "pilot_document_byte_limit")
        _preparse(raw)
        return raw
    except (ValueError, UnicodeError, RecursionError, OverflowError, TypeError):
        raise PilotDocumentError("pilot_document_json_invalid") from None


def pinned_bytes(raw, expected, *, empty=False):
    require(type(expected) is str and HASH.fullmatch(expected), "pilot_document_anchor_required")
    require(type(raw) is bytes and (0 if empty else 1) <= len(raw) <= MAX_BYTES,
            "pilot_document_byte_limit")
    require(hashlib.sha256(raw).hexdigest() == expected, "pilot_document_bytes_mismatch")


def json_value(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, "pilot_document_byte_limit")
    try:
        _preparse(raw)
        value = accounting._loads(raw.decode("utf-8"))
        canonical(value)
        return value
    except (ValueError, UnicodeError, RecursionError, OverflowError, TypeError):
        raise PilotDocumentError("pilot_document_json_invalid") from None


def review_records(raw):
    require(type(raw) is bytes and len(raw) <= MAX_BYTES, "pilot_document_byte_limit")
    _preparse(raw)  # Cumulative allocation bound before parsing any JSONL row.
    # Physical LF-delimited records, not str.splitlines(): U+2028/U+2029 inside
    # a legitimate quoted JSON string must remain part of that exact source text.
    rows = []
    for line in io.BytesIO(raw):
        if line.strip():
            require(len(rows) < accounting.MAX_REVIEWS, "pilot_document_review_limit")
            row = json_value(line)
            require(type(row) is dict, "pilot_document_review_object_required")
            rows.append(row)
    # Bound the combined tree as well as each individual JSON record.
    try:
        canonical(rows)
    except (ValueError, UnicodeError, RecursionError, OverflowError, TypeError):
        raise PilotDocumentError("pilot_document_json_invalid") from None
    return rows


def inspect_documents(*, selection_raw, reviews_raw, protocol_raw, conclusion_raw=None,
                      selection_file_sha256, reviews_file_sha256, protocol_file_sha256,
                      conclusion_file_sha256=None, selection_sha256, review_log_sha256):
    """Return private diagnostics; nothing is stored, registered or approved.

All exact raw-file anchors and distinct logical anchors are mandatory. The
protocol is opaque bytes (never executed). Context/canary bytes, permissions,
preregistration chronology and review identity need separate admission checks.
"""
    pinned_bytes(selection_raw, selection_file_sha256)
    pinned_bytes(reviews_raw, reviews_file_sha256, empty=True)
    pinned_bytes(protocol_raw, protocol_file_sha256)
    require(all(type(pin) is str and HASH.fullmatch(pin) for pin in (selection_sha256, review_log_sha256)),
            "pilot_document_logical_anchor_required")
    require((conclusion_raw is None) == (conclusion_file_sha256 is None), "pilot_document_conclusion_pair_required")
    if conclusion_raw is not None:
        pinned_bytes(conclusion_raw, conclusion_file_sha256)
    selection, reviews = json_value(selection_raw), review_records(reviews_raw)
    conclusion = None if conclusion_raw is None else json_value(conclusion_raw)
    require(type(selection) is dict and (conclusion_raw is None or type(conclusion) is dict),
            "pilot_document_object_required")
    require(accounting.selection_hash(selection) == selection_sha256
            and accounting.review_hash(reviews) == review_log_sha256, "pilot_document_logical_anchor_mismatch")
    require(selection.get("protocol_sha256") == protocol_file_sha256, "pilot_document_protocol_mismatch")
    try:
        report = accounting.validate(selection, reviews, conclusion, selection_sha256)
        canonical(report)
    except (ValueError, UnicodeError, RecursionError, OverflowError, TypeError, KeyError):
        raise PilotDocumentError("pilot_document_accounting_invalid") from None
    return {"version": VERSION, "scope": "private_documentary_consistency_not_authenticated_registration",
        "input_pins": {"selection_file_sha256": selection_file_sha256, "reviews_file_sha256": reviews_file_sha256,
            "protocol_file_sha256": protocol_file_sha256, "conclusion_file_sha256": conclusion_file_sha256},
        "selection_sha256": selection_sha256, "review_log_sha256": review_log_sha256,
        "accounting": report, "authority": dict(AUTHORITY), "training_execution": "disabled",
        "context_bytes_checked": False, "canary_replay_verified": False, "registration_recorded": False}
