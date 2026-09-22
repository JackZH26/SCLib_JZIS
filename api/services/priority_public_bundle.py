"""Public-safe RPS recomputation packages, never scientific or rights approval.

The embedded release is unchanged. Unsafe/private old releases are rejected,
not redacted and rehashed behind an old review. Closed fields and explicit
disclosure assertions do not detect secrets hidden inside allowed prose or
authenticate consent; separate server-side approval of BOTH digests is required.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import ConfigDict, Field

from services.priority_releases import (
    ActionContent,
    EvidenceContent,
    PriorityRelease,
    RubricContent,
    StateContent,
    TemplateReviewContent,
)
from services.research_priority import (
    POLICY,
    PROFILES,
    ActionTemplate,
    Contract,
    Hash,
    Nonnegative,
    canonical_json,
    digest,
)

VERSION = "rps-public-bundle/1.0.0"
VERIFIER_VERSION = "rps-public-verifier/1.0.0"
DISCLOSURE_VERSION = "rps-public-disclosure/1.0.0"
MAX_BYTES = 16 * 1024 * 1024
MAX_NODES = 500000
MAX_DEPTH = 32
MAX_STRING_BYTES = 16384
MAX_ASSESSMENTS = 1000
MAX_ARTIFACTS = 5000
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,120}\Z")
_REVIEWER = re.compile(r"public-(reviewer|attestation):[0-9a-f]{32}\Z")
_SOURCE_FILES = (
    "priority_public_bundle.py", "priority_public_bundle_cli.py", "priority_release_cache.py",
    "priority_releases.py", "research_priority.py",
)
_KEYS = {"schema_version", "release", "policy", "rows", "verifier", "disclosure", "bundle_sha256"}
_DISCLOSURE_KEYS = {"version", "release_manifest_sha256", "scope", "free_text_review", "review_attestations"}
_ATTESTATION_KEYS = {"artifact_id", "artifact_sha256", "public_reviewer_id", "attestation_kind", "consent_reference_sha256"}


class PublicPriorityBundleError(ValueError):
    """Sanitized closed-contract failure, never raw source/private path output."""


def _require(condition, message):
    if not condition:
        raise PublicPriorityBundleError(message)


def _hash(value):
    _require(type(value) is str and _HASH.fullmatch(value), "invalid SHA-256 reference")
    return value


def _bounded(value):
    nodes = 0
    characters = 0

    def visit(item, depth=0):
        nonlocal nodes, characters
        nodes += 1
        _require(nodes <= MAX_NODES and depth <= MAX_DEPTH, "public bundle structure limit exceeded")
        if type(item) is str:
            length = len(item.encode("utf-8"))
            characters += length
            _require(length <= MAX_STRING_BYTES and characters <= MAX_BYTES, "public bundle text limit exceeded")
        elif type(item) is dict:
            _require(len(item) <= MAX_ARTIFACTS, "public bundle object limit exceeded")
            for key, child in item.items():
                _require(type(key) is str, "public bundle requires string object keys")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            _require(len(item) <= MAX_ARTIFACTS, "public bundle array limit exceeded")
            for child in item:
                visit(child, depth + 1)
        elif item is None or type(item) is bool:
            return
        elif type(item) in {int, float}:
            _require(math.isfinite(item), "public bundle requires finite numbers")
        else:
            raise PublicPriorityBundleError("public bundle contains a non-JSON value")

    try:
        visit(value)
        encoded = canonical_json(value).encode("utf-8")
    except PublicPriorityBundleError:
        raise
    except (UnicodeError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise PublicPriorityBundleError("invalid or excessive public JSON") from exc
    _require(len(encoded) <= MAX_BYTES, "public bundle byte limit exceeded")
    return encoded


def strict_json(payload):
    """Decode bounded UTF-8, refusing duplicate keys, NaN and Infinity."""
    _require(type(payload) is bytes and len(payload) <= MAX_BYTES, "public bundle byte limit exceeded")
    def pairs(values):
        result = {}
        for key, value in values:
            _require(key not in result, "duplicate public JSON key")
            result[key] = value
        return result
    def constant(_value):
        raise PublicPriorityBundleError("public bundle requires finite numbers")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        _bounded(value)
        return value
    except PublicPriorityBundleError:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise PublicPriorityBundleError("invalid or excessive public JSON") from exc


def verifier_source_sha256():
    """Bind actual installed verifier/contract/scorer bytes, not a Git assertion.

    A clean offline verifier needs these source files plus its locked runtime.
    This digest is not a code signature, dependency hash or author attestation.
    """
    inventory = {}
    try:
        for name in _SOURCE_FILES:
            payload = Path(__file__).with_name(name).read_bytes()
            _require(len(payload) <= 1024 * 1024, "verifier source inventory unavailable")
            inventory[name] = hashlib.sha256(payload).hexdigest()
    except OSError as exc:
        raise PublicPriorityBundleError("verifier source inventory unavailable") from exc
    return digest({"version": VERIFIER_VERSION, "sources": inventory})


class _Closed(Contract):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class _Material(_Closed):
    formula: Annotated[str, Field(min_length=1, max_length=200)]


class _Review(_Closed):
    assessment_hash: Hash
    campaign_hash: Hash
    policy_hash: Hash
    decision: Literal["approved"]
    reviewer_id: Annotated[str, Field(pattern=r"^public-(reviewer|attestation):[0-9a-f]{32}$")]
    rationale: Annotated[str, Field(min_length=1, max_length=4000)] | None = None


class _ProfileAssignment(_Closed):
    campaign_hash: Hash
    mix: dict[Literal["common", "epc_hydride", "layered_correlated", "multiband", "flatband"], Nonnegative]


_ARTIFACT_CONTRACTS = {
    "material": _Material, "review": _Review, "profile_assignment": _ProfileAssignment,
    "state": StateContent, "action": ActionContent, "evidence": EvidenceContent,
    "rubric": RubricContent, "action_template": ActionTemplate, "template_review": TemplateReviewContent,
}


def _release(value):
    _require(type(value) is dict, "a complete unchanged RPS release is required")
    _bounded(value)
    _require(type(value.get("assessments")) is list and len(value["assessments"]) <= MAX_ASSESSMENTS,
             "public assessment inventory limit exceeded")
    _require(type(value.get("artifacts")) is list and len(value["artifacts"]) <= MAX_ARTIFACTS,
             "public artifact inventory limit exceeded")
    try:
        # Strict JSON parsing keeps timestamp strings valid without permitting
        # Python coercion of bool/string numeric inputs into scientific values.
        release = PriorityRelease.model_validate_json(_bounded(value), strict=True)
        _require(canonical_json(value) == canonical_json(release.model_dump(mode="json")),
                 "public release must retain its complete canonical contract")
        for artifact in release.artifacts:
            _ARTIFACT_CONTRACTS[artifact.kind].model_validate(artifact.content, strict=True)
            if artifact.kind in {"review", "template_review"}:
                _require(type(artifact.content.get("reviewer_id")) is str
                         and _REVIEWER.fullmatch(artifact.content["reviewer_id"]),
                         "private reviewer identities cannot be published")
            if artifact.kind == "profile_assignment":
                _require(set(artifact.content["mix"]) <= set(PROFILES), "unknown public profile")
            if artifact.kind == "evidence":
                address = urlsplit(artifact.content["url"])
                _require(address.username is None and address.password is None,
                         "credential-bearing evidence URLs cannot be published")
    except PublicPriorityBundleError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as exc:
        raise PublicPriorityBundleError("public release contract or complete scoring inputs invalid") from exc
    return release


def _disclosure(value, release):
    _require(type(value) is dict and set(value) == _DISCLOSURE_KEYS, "exact public disclosure fields required")
    _require(value["version"] == DISCLOSURE_VERSION and value["scope"] == "complete_rps_release"
             and value["free_text_review"] == "declared_cleared_for_publication"
             and value["release_manifest_sha256"] == release.manifest_sha256,
             "public disclosure must bind the exact complete release")
    rows = value["review_attestations"]
    _require(type(rows) is list and len(rows) <= MAX_ARTIFACTS, "bounded public review attestations required")
    reviews = {artifact.id: artifact for artifact in release.artifacts if artifact.kind in {"review", "template_review"}}
    seen = set()
    for row in rows:
        _require(type(row) is dict and set(row) == _ATTESTATION_KEYS, "exact public review attestation fields required")
        identifier = row["artifact_id"]
        _require(type(identifier) is str and identifier in reviews and identifier not in seen,
                 "public review attestation inventory mismatch")
        seen.add(identifier)
        artifact = reviews[identifier]
        _require(row["artifact_sha256"] == artifact.sha256
                 and row["public_reviewer_id"] == artifact.content["reviewer_id"],
                 "public review attestation binding mismatch")
        kind = row["attestation_kind"]
        _require((kind == "consented_public_pseudonym" and row["public_reviewer_id"].startswith("public-reviewer:"))
                 or (kind == "public_review_attestation" and row["public_reviewer_id"].startswith("public-attestation:")),
                 "explicit consented pseudonym or public attestation required")
        _hash(row["consent_reference_sha256"])
    _require(seen == set(reviews), "every public review artifact requires its exact disclosure attestation")
    _require([row["artifact_id"] for row in rows] == sorted(seen), "public review attestations require canonical ordering")


def bundle_sha256(value):
    """Canonical envelope hash, excluding only its own digest field."""
    _require(type(value) is dict, "public bundle must be an object")
    return hashlib.sha256(_bounded({key: item for key, item in value.items() if key != "bundle_sha256"})).hexdigest()


def build_public_bundle(release, *, disclosure):
    """Pure preparation, not approval, persistence or a legacy redaction tool."""
    value = release.model_dump(mode="json") if isinstance(release, PriorityRelease) else release
    verified = _release(value)
    _disclosure(disclosure, verified)
    envelope = {"schema_version": VERSION, "release": value,
        "policy": json.loads(canonical_json(POLICY)), "rows": verified.rows(),
        "verifier": {"version": VERIFIER_VERSION, "source_sha256": verifier_source_sha256()},
        "disclosure": disclosure}
    envelope["bundle_sha256"] = bundle_sha256(envelope)
    # Detach every nested object; neither caller mutations nor cached _rows
    # objects may later rewrite a prepared public document.
    return json.loads(_bounded(envelope))


def verify_public_bundle(value, *, expected_bundle_sha256, expected_release_sha256=None):
    """Recompute all score outputs and hashes without private data or services."""
    _hash(expected_bundle_sha256)
    _bounded(value)
    _require(type(value) is dict and set(value) == _KEYS and value["schema_version"] == VERSION,
             "exact public bundle fields/version required")
    _require(value["bundle_sha256"] == expected_bundle_sha256 == bundle_sha256(value),
             "public bundle digest mismatch")
    _require(type(value["verifier"]) is dict and set(value["verifier"]) == {"version", "source_sha256"}
             and value["verifier"]["version"] == VERIFIER_VERSION
             and value["verifier"]["source_sha256"] == verifier_source_sha256(),
             "public verifier version or actual source digest mismatch")
    _require(canonical_json(value["policy"]) == canonical_json(POLICY), "complete scoring policy mismatch")
    release = _release(value["release"])
    if expected_release_sha256 is not None:
        _require(release.manifest_sha256 == _hash(expected_release_sha256), "independently pinned release digest mismatch")
    _disclosure(value["disclosure"], release)
    rows = release.rows()
    _require(canonical_json(value["rows"]) == canonical_json(rows), "complete recomputed score rows mismatch")
    return {"schema_version": "rps-public-verification/1.0.0", "release_id": release.id,
        "bundle_sha256": expected_bundle_sha256, "release_manifest_sha256": release.manifest_sha256,
        "verifier_version": VERIFIER_VERSION, "verifier_source_sha256": value["verifier"]["source_sha256"],
        "assessment_count": len(rows), "artifact_count": len(release.artifacts),
        "integrity_verified": True, "scoring_recomputed": True, "recursive_field_contract_verified": True,
        "disclosure_status": "declared_complete_release_disclosure",
        "review_status": "declared_artifact_reviews_not_authenticated",
        "reviewer_identity_authenticated": False, "source_rights_verified": False,
        "current_public_authorization_checked": False, "scientific_acceptance": False,
        "empirical_calibration_verified": False,
        "meaning": "Policy-based research priority; empirical calibration pending"}


@dataclass(frozen=True, slots=True)
class VerifiedPublicPriorityBundle:
    release_id: str
    bundle_sha256: str
    release_manifest_sha256: str
    verifier_version: str
    canonical_bytes: bytes = field(repr=False)
    _metadata_json: str = field(repr=False)

    @property
    def document(self):
        return json.loads(self.canonical_bytes)

    @property
    def metadata(self):
        return json.loads(self._metadata_json)


def read_public_bundle(directory, release_id, expected_bundle_sha256, *, expected_release_sha256=None):
    """One bounded safe file, shared cache; no implied server authorization."""
    _require(type(release_id) is str and _ID.fullmatch(release_id), "invalid public release identity")
    _hash(expected_bundle_sha256)
    if expected_release_sha256 is not None:
        _hash(expected_release_sha256)
    from services.priority_release_cache import read_verified_file
    def validate(payload):
        value = strict_json(payload)
        _require(type(value) is dict and type(value.get("release")) is dict
                 and value["release"].get("id") == release_id, "public bundle filename identity mismatch")
        metadata = verify_public_bundle(value, expected_bundle_sha256=expected_bundle_sha256,
            expected_release_sha256=expected_release_sha256)
        canonical = _bounded(value)
        _require(payload == canonical, "public bundle requires exact canonical UTF-8 bytes")
        return VerifiedPublicPriorityBundle(release_id, expected_bundle_sha256,
            metadata["release_manifest_sha256"], VERIFIER_VERSION, canonical, canonical_json(metadata))
    try:
        return read_verified_file(Path(directory) / f"{release_id}.public.json",
            identity=(VERSION, release_id, expected_bundle_sha256, expected_release_sha256, verifier_source_sha256()), validator=validate)
    except PublicPriorityBundleError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as exc:
        raise PublicPriorityBundleError("public bundle capture or verification failed") from exc
