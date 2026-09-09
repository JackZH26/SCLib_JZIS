"""Separately pinned, negative-only label observations for a frozen ML base."""
from __future__ import annotations

import json

from services.ml_feature_review_companion import AUTHORITY, verify_ml_review_companion
from services.ml_label_observation import (
    EXPORT_SCOPE,
    LABEL_HOLD_CODES,
    MAX_BYTES,
    MAX_DEPTH,
    MAX_NODES,
    MAX_ROWS,
    bounded,
    label_inventory,
    verify_label_observation,
)
from services.research_release_manifest import digest

VERSION = "ml-label-companion/1.0.0"
__all__ = ["VERSION", "EXPORT_SCOPE", "LABEL_HOLD_CODES", "MAX_BYTES", "MAX_DEPTH", "MAX_NODES",
           "MAX_ROWS", "MlLabelCompanionError", "assemble_ml_label_companion", "verify_ml_label_companion"]
_TOP = {"version", "base_release_id", "base_manifest_sha256", "source_companion_sha256",
        "review_companion_sha256", "observation", "observation_sha256", "authority", "companion_sha256"}


class MlLabelCompanionError(ValueError):
    """Static bounded failure, never a source, SQL or private-review message."""


def require(condition, code="ml_label_companion_invalid"):
    if not condition:
        raise MlLabelCompanionError(code)


def verify_ml_label_companion(label_companion, *, base_manifest, expected_base_manifest_sha256,
                              source_companion, expected_source_companion_sha256,
                              review_companion, expected_review_companion_sha256,
                              expected_label_companion_sha256):
    """Revalidate all four independent pins; empty holds do not approve labels."""
    try:
        from services.ml_label_observation import _hash
        value = json.loads(bounded(label_companion))
        require(set(value) == _TOP and value["version"] == VERSION)
        for expected in (expected_base_manifest_sha256, expected_source_companion_sha256,
                         expected_review_companion_sha256, expected_label_companion_sha256):
            _hash(expected)
        require(digest(value) == expected_label_companion_sha256, "ml_label_companion_pin_mismatch")
        require(value["companion_sha256"] == digest({key: item for key, item in value.items() if key != "companion_sha256"}), "ml_label_internal_hash_mismatch")
        require(value["base_manifest_sha256"] == expected_base_manifest_sha256
                and value["source_companion_sha256"] == expected_source_companion_sha256
                and value["review_companion_sha256"] == expected_review_companion_sha256,
                "ml_label_input_pin_mismatch")
        require(type(value["authority"]) is dict and set(value["authority"]) == set(AUTHORITY)
                and all(item is False for item in value["authority"].values()), "ml_label_authority_invalid")
        require(value["base_release_id"] == source_companion["base_release_id"] == review_companion["base_release_id"])
        verify_ml_review_companion(review_companion, base_manifest=base_manifest,
            expected_base_manifest_sha256=expected_base_manifest_sha256, source_companion=source_companion,
            expected_source_companion_sha256=expected_source_companion_sha256,
            expected_review_companion_sha256=expected_review_companion_sha256)
        require(value["observation_sha256"] == digest(value["observation"]), "ml_label_observation_hash_mismatch")
        result = verify_label_observation(value["observation"], base_manifest=base_manifest, review_companion=review_companion)
        return {"version": VERSION, "base_manifest_sha256": expected_base_manifest_sha256,
            "source_companion_sha256": expected_source_companion_sha256,
            "review_companion_sha256": expected_review_companion_sha256,
            "label_companion_sha256": expected_label_companion_sha256,
            "observation_sha256": value["observation_sha256"], **label_inventory(base_manifest), **result,
            "observation_semantics": "captured_not_live", "authority": dict(AUTHORITY)}
    except MlLabelCompanionError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, UnicodeError, OverflowError):
        raise MlLabelCompanionError("ml_label_companion_invalid") from None


def assemble_ml_label_companion(*, base_manifest, expected_base_manifest_sha256, source_companion,
                                expected_source_companion_sha256, review_companion,
                                expected_review_companion_sha256, observation):
    """Seal a private declared capture, then replay the complete verifier."""
    try:
        detached = json.loads(bounded(observation))
        value = {"version": VERSION, "base_release_id": source_companion["base_release_id"],
            "base_manifest_sha256": expected_base_manifest_sha256,
            "source_companion_sha256": expected_source_companion_sha256,
            "review_companion_sha256": expected_review_companion_sha256,
            "observation": detached, "observation_sha256": digest(detached), "authority": dict(AUTHORITY)}
        value["companion_sha256"] = digest(value)
        verify_ml_label_companion(value, base_manifest=base_manifest,
            expected_base_manifest_sha256=expected_base_manifest_sha256, source_companion=source_companion,
            expected_source_companion_sha256=expected_source_companion_sha256, review_companion=review_companion,
            expected_review_companion_sha256=expected_review_companion_sha256,
            expected_label_companion_sha256=digest(value))
        return value
    except MlLabelCompanionError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, UnicodeError, OverflowError):
        raise MlLabelCompanionError("ml_label_companion_invalid") from None
