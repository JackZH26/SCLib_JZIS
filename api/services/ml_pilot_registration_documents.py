"""Pure document-to-commitment mapping; no database, source access or approval."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from services import ml_pilot_accounting as accounting
from services import ml_pilot_documents as documents

VERSION = "ml08-registration-documents/1.1.0"
ROLES = ("primary", "secondary", "arbitration")
MAX_ENVELOPE_BYTES = 2 * ((documents.MAX_BYTES + 2) // 3 * 4) + 65536


def require(value):
    if not value:
        raise ValueError("invalid_pilot_registration_documents")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def identifier(value):
    require(type(value) is str and str(UUID(value)) == value)
    return value


def implementation():
    names = (
        "ml_pilot_accounting.py",
        "ml_pilot_documents.py",
        "ml_pilot_registration_documents.py",
        "ml_pilot_registration_worker.py",
        "ml_use_reconstruction_worker.py",
        "ml08_pilot.schema.json",
    )
    return {
        "version": VERSION,
        "scope": "selected_installed_disk_sources_not_runtime_attestation",
        "files": {name: sha(Path(__file__).with_name(name).read_bytes()) for name in names},
    }


def decode(value):
    require(type(value) is str and 0 < len(value) <= (documents.MAX_BYTES + 2) // 3 * 4)
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, UnicodeError):
        raise ValueError("invalid_pilot_registration_documents") from None
    require(0 < len(raw) <= documents.MAX_BYTES and base64.b64encode(raw).decode("ascii") == value)
    return raw


def chronology(selection):
    """Normalize declared instants, without asserting their external truth."""
    return {
        key: accounting._date(selection[key]).astimezone(UTC).isoformat(timespec="microseconds")
        for key in ("selected_at", "frozen_at")
    }


def check_chronology(value, *, observed_at=None):
    require(type(value) is dict and set(value) == {"selected_at", "frozen_at"})
    require(all(type(v) is str for v in value.values()))
    require(chronology(value) == value)
    selected, frozen = (accounting._date(value[k]) for k in ("selected_at", "frozen_at"))
    require(selected <= frozen)
    if observed_at is not None:
        require(isinstance(observed_at, datetime) and observed_at.utcoffset() is not None)
        require(frozen <= observed_at)


def _selection(
    *, selection_raw, protocol_raw, selection_file_sha256, protocol_file_sha256, selection_sha256
):
    observed = documents.inspect_documents(
        selection_raw=selection_raw,
        protocol_raw=protocol_raw,
        reviews_raw=b"",
        selection_file_sha256=selection_file_sha256,
        protocol_file_sha256=protocol_file_sha256,
        reviews_file_sha256=sha(b""),
        selection_sha256=selection_sha256,
        review_log_sha256=accounting.review_hash([]),
    )
    report = observed["accounting"]
    require(
        not report["errors"]
        and report["ready_for_review"]
        and report["counts"]["selected_candidates"] == 60
        and report["counts"]["unreviewed_candidates"] == 60
    )
    return documents.json_value(selection_raw)


def verify_files(**args):
    selection = _selection(**args)
    return {
        "version": VERSION,
        **{
            key: args[key]
            for key in ("selection_file_sha256", "protocol_file_sha256", "selection_sha256")
        },
        "selected_candidates": 60,
        "selection_chronology": chronology(selection),
        "reviewer_roles": sorted(
            [
                {
                    "alias_sha256": sha(r["id"].encode("utf-8")),
                    "roles": [role for role in ROLES if role in r["roles"]],
                }
                for r in selection["reviewers"]
            ],
            key=lambda row: row["alias_sha256"],
        ),
    }


def check(
    *,
    selection_raw,
    protocol_raw,
    selection_file_sha256,
    protocol_file_sha256,
    selection_sha256,
    bindings,
):
    """Bind every declared alias without persisting its name or source text."""
    selection = _selection(
        selection_raw=selection_raw,
        protocol_raw=protocol_raw,
        selection_file_sha256=selection_file_sha256,
        protocol_file_sha256=protocol_file_sha256,
        selection_sha256=selection_sha256,
    )
    require(type(bindings) is list and 2 <= len(bindings) <= 30)
    reviewers = {r["id"]: r for r in selection["reviewers"]}
    require(len(reviewers) == len(bindings))
    rows, aliases, users = [], set(), set()
    for binding in bindings:
        require(
            type(binding) is dict
            and set(binding) == {"reviewer_alias", "user_id", "reviewer_grant_id"}
        )
        alias = binding["reviewer_alias"]
        require(type(alias) is str and alias in reviewers and alias not in aliases)
        user = identifier(binding["user_id"])
        require(user not in users)
        aliases.add(alias)
        users.add(user)
        roles = [role for role in ROLES if role in reviewers[alias]["roles"]]
        rows.append(
            {
                "alias_sha256": sha(alias.encode("utf-8")),
                "user_id": user,
                "reviewer_grant_id": identifier(binding["reviewer_grant_id"]),
                "roles": roles,
            }
        )
    require(aliases == set(reviewers))
    rows.sort(key=lambda row: row["alias_sha256"])
    # A primary/secondary pair must be different accounts, even without reviews.
    require(
        any(
            a["user_id"] != b["user_id"] and "primary" in a["roles"] and "secondary" in b["roles"]
            for a in rows
            for b in rows
        )
    )
    return {
        "version": VERSION,
        "selection_file_sha256": selection_file_sha256,
        "protocol_file_sha256": protocol_file_sha256,
        "selection_sha256": selection_sha256,
        "participant_bindings": rows,
        "selected_candidates": 60,
        "selection_chronology": chronology(selection),
    }
