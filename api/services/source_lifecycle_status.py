"""Pure negative lifecycle overlay; never publication status or scientific approval.

Kept byte-identical in API and ingestion. Only trusted database resolvers may
construct these envelopes; extraction JSON is not a lifecycle authority.
"""
import hashlib
import json
import re
from collections.abc import Mapping

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_KEYS = {"status", "lifecycle_review_required", "lifecycle_revision"}


def _valid(value):
    return (isinstance(value, Mapping) and set(value) == _KEYS
            and (value["status"] is None or isinstance(value["status"], str))
            and value["lifecycle_review_required"] is True
            and isinstance(value["lifecycle_revision"], str)
            and _SHA256.fullmatch(value["lifecycle_revision"]) is not None)


def lifecycle_status(value):
    """Original bibliographic status; malformed envelopes cannot assert one."""
    if isinstance(value, Mapping):
        return value["status"] if _valid(value) else None
    return value if value is None or isinstance(value, str) else None


def lifecycle_review_required(value):
    """Every envelope is a hold, including malformed/untrusted shapes."""
    return isinstance(value, Mapping)


def lifecycle_revision(value):
    return value["lifecycle_revision"] if _valid(value) else None


def lifecycle_fingerprint(value):
    return {"status": lifecycle_status(value),
            "lifecycle_review_required": lifecycle_review_required(value),
            "lifecycle_revision": lifecycle_revision(value)}


def overlay_source_lifecycle(status, revision_sha256):
    value = {"status": status, "lifecycle_review_required": True,
             "lifecycle_revision": revision_sha256}
    if not _valid(value):
        raise ValueError("Invalid source lifecycle overlay")
    return value


def combined_lifecycle_revision(paper_revision=None, work_revision=None):
    """Stable shared binding to the direct and explicitly mapped Work heads."""
    for value in (paper_revision, work_revision):
        if value is not None and (not isinstance(value, str) or _SHA256.fullmatch(value) is None):
            raise ValueError("Invalid lifecycle head digest")
    if work_revision is None:
        return paper_revision
    return hashlib.sha256(json.dumps({"paper": paper_revision, "work": work_revision},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
