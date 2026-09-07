"""Versioned, metadata-only public projection of an internal ML04 capsule.

This pure module consumes permission receipts supplied by a trusted database
caller; it cannot authenticate a reviewer, grant permission, or publish a
release. Every captured row (including excluded source text/artifact payloads)
requires a separately reviewed grant for the exact metadata projection. No
internal JSON is traversed for egress, and no arbitrary field is copied.

License codes record reviewed decisions, not a legal determination or proof of
attribution compliance. A future text/structured-results scope needs its own
versioned projection, attribution manifest and rights review.
"""
from __future__ import annotations

import hashlib
import re
from uuid import UUID

from .research_release_manifest import (
    ResearchReleaseVerificationError,
    canonical,
    digest,
    verify_manifest,
)
from .research_release_spec import TABLE_FIELDS

VERSION = "research-public-metadata/1.0.0"
SCOPE = "metadata_only"
LICENSE_CODES = frozenset({"CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "permission-on-file"})
LIMITS = {"objects": 1000, "file_bytes": 8 * 1024 * 1024}
EXCLUSIONS = {
    "scientific_values": True,
    "training_examples_and_features": True,
    "source_text_and_raw_records": True,
    "artifact_bytes_and_coordinates": True,
    "raw_object_and_material_identifiers": True,
    "source_locators_and_uris": True,
    "reviewer_and_account_identifiers": True,
    "free_text_and_flexible_json": True,
    "run_settings_and_connection_configuration": True,
}
_HASH = re.compile(r"^[0-9a-f]{64}$")
_PERMISSION_FIELDS = frozenset({"table", "row_id", "row_sha256", "permission_id",
                                "permission_sha256", "scope", "license_code"})
_OBJECT_FIELDS = frozenset({"table", "object_sha256", "permission_id", "permission_sha256",
                            "scope", "license_code"})
_DOCUMENT_FIELDS = frozenset({"version", "scope", "capsule_sha256", "dataset_object_sha256",
                              "objects", "counts", "exclusions", "limits",
                              "scientific_acceptance", "ml_training_approved"})


class PublicResearchVerificationError(ValueError):
    """The public metadata projection violates its closed egress contract."""


def _require(condition, message):
    if not condition:
        raise PublicResearchVerificationError(message)


def _hash(value):
    return type(value) is str and _HASH.fullmatch(value) is not None


def _uuid(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _same(value, expected, message):
    _require(canonical(value) == canonical(expected), message)


def public_object_sha256(*, capsule_sha256, table, row_id, row_sha256):
    """Opaque, release-scoped reference; not an authorization or anonymization proof."""
    _require(_hash(capsule_sha256) and _hash(row_sha256), "invalid object digest binding")
    _require(type(table) is str and table in TABLE_FIELDS, "unsupported object table")
    _require(type(row_id) is str and 0 < len(row_id) <= 200, "invalid internal row identifier")
    return digest({"version": VERSION, "capsule_sha256": capsule_sha256,
                   "table": table, "row_id": row_id, "row_sha256": row_sha256})


def _permissions(manifest, permissions):
    _require(type(permissions) is list and len(permissions) <= LIMITS["objects"],
             "permission inventory limit or shape")
    found = {(row["table"], row["row_id"]): row for row in manifest["rows"]}
    collected, identifiers = {}, set()
    for permission in permissions:
        _require(type(permission) is dict and set(permission) == _PERMISSION_FIELDS,
                 "unknown or incomplete permission fields")
        table, row_id = permission["table"], permission["row_id"]
        _require(type(table) is str and table in TABLE_FIELDS and type(row_id) is str,
                 "invalid permission object binding")
        key = table, row_id
        _require(key in found and key not in collected, "extra or duplicate permission object")
        _require(_hash(permission["row_sha256"])
                 and permission["row_sha256"] == found[key]["row_sha256"], "stale permission row digest")
        _require(_uuid(permission["permission_id"]) and permission["permission_id"] not in identifiers,
                 "invalid or reused permission identifier")
        _require(_hash(permission["permission_sha256"]), "invalid permission receipt digest")
        _require(permission["scope"] == SCOPE, "every dependency requires reviewed metadata permission")
        _require(type(permission["license_code"]) is str and permission["license_code"] in LICENSE_CODES,
                 "unresolved or unsupported metadata license")
        identifiers.add(permission["permission_id"])
        collected[key] = permission
    _require(set(collected) == set(found), "missing recursive dependency permission")
    return collected


def build_public_document(*, manifest, expected_capsule_sha256, permissions, artifact_bytes):
    """Build a deterministic metadata body, never an authorization decision.

    The caller must load authentic, active, release-bound grants under its
    publication transaction. A dict supplied by an untrusted user is not a grant.
    This module verifies actual capsule bytes but deliberately exports none.
    """
    try:
        _require(_hash(expected_capsule_sha256), "independently pinned capsule digest required")
        verify_manifest(manifest, artifact_bytes=artifact_bytes,
                        expected_manifest_sha256=expected_capsule_sha256)
        grants = _permissions(manifest, permissions)
        objects, root = [], None
        for row in manifest["rows"]:
            permission = grants[(row["table"], row["row_id"])]
            identifier = public_object_sha256(capsule_sha256=expected_capsule_sha256,
                                              table=row["table"], row_id=row["row_id"],
                                              row_sha256=row["row_sha256"])
            objects.append({"table": row["table"], "object_sha256": identifier,
                            **{key: permission[key] for key in
                               ("permission_id", "permission_sha256", "scope", "license_code")}})
            if row["table"] == "ml_dataset_snapshots" and row["row_id"] == manifest["dataset_id"]:
                root = identifier
        objects.sort(key=lambda item: (item["table"], item["object_sha256"]))
        counts = [{"table": table, "object_count": sum(item["table"] == table for item in objects)}
                  for table in sorted(TABLE_FIELDS)]
        document = {"version": VERSION, "scope": SCOPE, "capsule_sha256": expected_capsule_sha256,
                    "dataset_object_sha256": root, "objects": objects, "counts": counts,
                    "exclusions": dict(EXCLUSIONS), "limits": dict(LIMITS),
                    "scientific_acceptance": False, "ml_training_approved": False}
        verify_public_document(document, expected_public_sha256=digest(document))
        return document
    except PublicResearchVerificationError:
        raise
    except (ResearchReleaseVerificationError, KeyError, TypeError, ValueError,
            AttributeError, RecursionError, OverflowError) as exc:
        raise PublicResearchVerificationError("capsule or public projection verification failed") from exc


def verify_public_document(document, *, expected_public_sha256):
    """Verify a pinned public body without authenticating embedded permissions.

    An attacker can construct a new self-consistent document and recompute its
    hash. The independent expected hash and server publication admission are
    essential trust boundaries; this offline function cannot replace either.
    """
    try:
        _require(_hash(expected_public_sha256), "independently pinned public digest required")
        _require(type(document) is dict and set(document) == _DOCUMENT_FIELDS,
                 "unknown or incomplete public document fields")
        encoded = canonical(document)
        _require(len(encoded) <= LIMITS["file_bytes"], "public document byte limit")
        actual = hashlib.sha256(encoded).hexdigest()
        _require(actual == expected_public_sha256, "pinned public document digest mismatch")
        _require(document["version"] == VERSION and document["scope"] == SCOPE,
                 "unsupported public projection version or scope")
        _require(_hash(document["capsule_sha256"]) and _hash(document["dataset_object_sha256"]),
                 "invalid capsule or dataset binding")
        _same(document["limits"], LIMITS, "unsupported public document limits")
        _same(document["exclusions"], EXCLUSIONS, "unsupported public egress exclusions")
        _require(document["scientific_acceptance"] is False and document["ml_training_approved"] is False,
                 "metadata publication cannot grant scientific or training approval")
        objects = document["objects"]
        _require(type(objects) is list and 0 < len(objects) <= LIMITS["objects"],
                 "public object inventory limit or shape")
        seen, permissions = {}, set()
        for item in objects:
            _require(type(item) is dict and set(item) == _OBJECT_FIELDS,
                     "unknown or incomplete nested public object fields")
            _require(type(item["table"]) is str and item["table"] in TABLE_FIELDS,
                     "unsupported public object table")
            _require(_hash(item["object_sha256"]) and item["object_sha256"] not in seen,
                     "invalid or duplicate public object digest")
            _require(_uuid(item["permission_id"]) and item["permission_id"] not in permissions,
                     "invalid or reused permission identifier")
            _require(_hash(item["permission_sha256"]), "invalid permission receipt digest")
            _require(item["scope"] == SCOPE, "unsupported nested public scope")
            _require(type(item["license_code"]) is str and item["license_code"] in LICENSE_CODES,
                     "unresolved or unsupported metadata license")
            seen[item["object_sha256"]] = item
            permissions.add(item["permission_id"])
        _same(objects, sorted(objects, key=lambda item: (item["table"], item["object_sha256"])),
              "public objects must be canonically ordered")
        root = seen.get(document["dataset_object_sha256"])
        _require(root is not None and root["table"] == "ml_dataset_snapshots", "dataset object binding unresolved")
        expected_counts = [{"table": table, "object_count": sum(item["table"] == table for item in objects)}
                           for table in sorted(TABLE_FIELDS)]
        _same(document["counts"], expected_counts, "unknown, incomplete or inconsistent nested counts")
        return {"version": VERSION, "public_document_sha256": actual,
                "capsule_sha256": document["capsule_sha256"], "object_count": len(objects),
                "integrity_verified": True, "scope": SCOPE,
                "permission_authority_authenticated": False, "capsule_integrity_rechecked": False,
                "current_public_availability_rechecked": False, "scientific_acceptance": False,
                "ml_training_approved": False}
    except PublicResearchVerificationError:
        raise
    except (ResearchReleaseVerificationError, KeyError, TypeError, ValueError,
            AttributeError, RecursionError, OverflowError) as exc:
        raise PublicResearchVerificationError("invalid or excessive public document") from exc
