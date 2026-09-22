"""Closed ML-use intake declaration; hashes are not a permission or signature."""
from __future__ import annotations

import json
import re
from uuid import UUID

from services.research_release_manifest import canonical, digest

VERSION = "ml-use-request/1.0.0"
PURPOSE = "private_baseline_evaluation"
INPUTS = ("manifest", "task", "companion", "review_companion", "label_companion", "package", "config", "preparation")
MAX_BYTES = 96 * 1024
MAX_BINDINGS = 500


def require(value):
    if not value:
        raise ValueError("invalid_ml_use_request")


def identifier(value):
    require(type(value) is str and str(UUID(value)) == value)
    return value


def sha(value):
    require(type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None)
    return value


def validate_request(value):
    require(type(value) is dict and set(value) == {
        "version", "purpose", "dataset_id", "base_release_id", "input_pins", "feature_binding_pins"})
    require(value["version"] == VERSION and value["purpose"] == PURPOSE)
    identifier(value["dataset_id"])
    identifier(value["base_release_id"])
    pins = value["input_pins"]
    require(type(pins) is dict and set(pins) == {key + "_sha256" for key in INPUTS})
    for pin in pins.values():
        sha(pin)
    bindings = value["feature_binding_pins"]
    require(type(bindings) is list and len(bindings) <= MAX_BINDINGS)
    keys = []
    for row in bindings:
        require(type(row) is dict and set(row) == {"id", "record_sha256"})
        keys.append(identifier(row["id"]))
        sha(row["record_sha256"])
    require(keys == sorted(set(keys)))
    raw = canonical(value)
    require(len(raw) <= MAX_BYTES)
    return json.loads(raw)


def prepare_request(*, manifest, companion, input_pins):
    """Pure projection only; caller must rebuild all original pinned inputs first."""
    require(digest(manifest) == input_pins["manifest_sha256"]
            and digest(companion) == input_pins["companion_sha256"])
    return validate_request({"version": VERSION, "purpose": PURPOSE, "dataset_id": manifest["dataset_id"],
        "base_release_id": companion["base_release_id"], "input_pins": input_pins,
        "feature_binding_pins": sorted(({"id": row["id"], "record_sha256": row["record_sha256"]}
            for row in companion["bindings"]), key=lambda row: row["id"])})
