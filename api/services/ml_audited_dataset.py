"""Mandatory identity-audit wrapper around unchanged private v4 datasets.

The additional gate reports captured identities and leakage constraints, never
scientific independence, source rights, reviewer authentication or permission
to train. Old dataset/task/source bytes and their checksum rules stay intact.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from importlib.resources import files

from services.ml_dataset_builder import AUTHORITY
from services.ml_dataset_builder_v4 import build_task_dataset_v4
from services.research_release_manifest import canonical as base_canonical
from services.research_release_manifest import digest as base_digest

VERSION = "ml-identity-audited-dataset/1.0.0"
AUDIT_VERSION = "ml-identity-audit/1.0.0"
AUDIT_POLICY_VERSION = "captured-typed-identity/1.0.0"
MAX_BYTES = 32 * 1024 * 1024
MAX_NODES = 400_000
MAX_DEPTH = 64
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ESCAPES = re.compile(r'["\\\x00-\x1f]')
_SOURCE_MODULES = ("ml_audited_dataset", "ml_identity_audit")
_PACKAGE_FIELDS = {
    "version",
    "base_dataset",
    "base_dataset_sha256",
    "identity_audit",
    "identity_audit_sha256",
    "audit_policy_version",
    "audit_implementation",
    "audit_implementation_sha256",
    "gate",
    "authority",
}
_BASE_FIELDS = {
    "version",
    "task",
    "authority",
    "compiler",
    "input_pins",
    "review_observation",
    "label_observation",
    "candidates",
    "rows",
    "views",
    "cohorts",
    "coverage",
    "dependency_manifest",
    "split_report",
    "comparisons",
    "gate",
    "data_card",
}
_AUDIT_FIELDS = {
    "version",
    "policy_version",
    "input_pins",
    "completeness",
    "limits",
    "nodes",
    "components",
    "join_witnesses",
    "examples",
    "counts",
    "relationship_components",
    "checks",
    "gate",
    "authority",
    "independent_support_count",
}
_CHECK_CODES = {
    "component_crossings": "component_partition_crossing",
    "identity_crossings": "identity_partition_crossing",
    "cohort_violations": "cohort_membership_violation",
    "view_violations": "view_assignment_violation",
    "comparison_violations": "comparison_membership_violation",
    "assignment_violations": "assignment_policy_violation",
}
_COMPANION_PINS = (
    "review_companion_sha256",
    "review_observation_sha256",
    "label_companion_sha256",
    "label_observation_sha256",
)


class MlAuditedDatasetError(ValueError):
    """Static bounded failure; no raw inputs, paths or scientific text echoed."""


def _require(condition, code="ml_audited_dataset_invalid"):
    if not condition:
        raise MlAuditedDatasetError(code)


def _hash(value):
    _require(type(value) is str and _HASH.fullmatch(value), "ml_audited_hash_invalid")
    return value


def _string_size(value):
    """Exact ensure_ascii=False JSON string size, without a huge escape copy."""
    _require(len(value) <= MAX_BYTES, "ml_audited_byte_limit")
    total = 2
    for offset in range(0, len(value), 32768):
        chunk = value[offset : offset + 32768]
        total += len(chunk.encode("utf-8"))
        total += sum(
            1 if match.group() in '"\\\b\t\n\f\r' else 5 for match in _ESCAPES.finditer(chunk)
        )
        _require(total <= MAX_BYTES, "ml_audited_byte_limit")
    return total


def _bounded_tree(value):
    pending, active, scheduled, size = [(value, 0, False)], set(), 1, 0
    while pending:
        item, depth, leaving = pending.pop()
        if leaving:
            active.remove(id(item))
            continue
        _require(depth <= MAX_DEPTH and scheduled <= MAX_NODES, "ml_audited_json_limit")
        if type(item) in {dict, list}:
            _require(id(item) not in active, "ml_audited_json_cycle")
            active.add(id(item))
            children = 2 * len(item) if type(item) is dict else len(item)
            scheduled += children
            _require(scheduled <= MAX_NODES, "ml_audited_json_limit")
            size += 2 + max(0, len(item) - 1) + (len(item) if type(item) is dict else 0)
            pending.append((item, depth, True))
            if type(item) is dict:
                _require(all(type(key) is str for key in item), "ml_audited_json_type")
                pending.extend((part, depth + 1, False) for pair in item.items() for part in pair)
            else:
                pending.extend((part, depth + 1, False) for part in item)
        elif type(item) is str:
            size += _string_size(item)
        elif item is None:
            size += 4
        elif type(item) is bool:
            size += 4 if item else 5
        elif type(item) is int:
            _require(item.bit_length() <= MAX_BYTES * 4, "ml_audited_byte_limit")
            size += len(str(item))
        elif type(item) is float:
            _require(math.isfinite(item), "ml_audited_nonfinite")
            size += len(repr(item))
        else:
            raise MlAuditedDatasetError("ml_audited_json_type")
        _require(size <= MAX_BYTES, "ml_audited_byte_limit")


def canonical(value):
    """Version-owned cumulative limits; byte encoding matches old canonical JSON."""
    try:
        _bounded_tree(value)
        result = json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        _require(len(result) <= MAX_BYTES, "ml_audited_byte_limit")
        return result
    except MlAuditedDatasetError:
        raise
    except (ValueError, TypeError, RecursionError, UnicodeError, OverflowError):
        raise MlAuditedDatasetError("ml_audited_json_invalid") from None


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _preparse(payload):
    """Bound token allocation before json.loads builds a potentially large tree."""
    depth = nodes = 0
    in_string = escaped = atom = False
    for byte in payload:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                in_string = False
            continue
        if byte == 34:
            nodes += 1
            in_string, atom = True, False
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
        _require(0 <= depth <= MAX_DEPTH + 1 and nodes <= MAX_NODES, "ml_audited_json_limit")


def loads(payload):
    """Strict canonical UTF-8 JSON with duplicate, finite and pre-parse bounds."""
    try:
        _require(type(payload) is bytes and 0 < len(payload) <= MAX_BYTES, "ml_audited_byte_limit")
        _preparse(payload)

        def pairs(items):
            result = {}
            for key, value in items:
                _require(key not in result, "ml_audited_duplicate_key")
                result[key] = value
            return result

        def constant(_value):
            raise MlAuditedDatasetError("ml_audited_nonfinite")

        value = json.loads(
            payload.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant
        )
        _require(canonical(value) == payload, "ml_audited_canonical_required")
        return value
    except MlAuditedDatasetError:
        raise
    except (ValueError, TypeError, RecursionError, UnicodeError, OverflowError):
        raise MlAuditedDatasetError("ml_audited_json_invalid") from None


def _authority(value):
    _require(
        type(value) is dict
        and set(value) == set(AUTHORITY)
        and all(flag is False for flag in value.values()),
        "ml_audited_authority_invalid",
    )


def _gate(value, expected_codes):
    _require(
        type(value) is dict and set(value) == {"status", "reason_codes"}, "ml_audited_gate_invalid"
    )
    _require(
        type(value["status"]) is str
        and value["status"] == ("no_go" if expected_codes else "pass")
        and type(value["reason_codes"]) is list
        and value["reason_codes"] == sorted(expected_codes),
        "ml_audited_gate_invalid",
    )


def _base_contract(base, expected_pins, dataset_id):
    _require(
        type(base) is dict
        and set(base) == _BASE_FIELDS
        and base["version"] == "ml-task-dataset/4.0.0",
        "ml_audited_base_invalid",
    )
    _authority(base["authority"])
    pins = base["input_pins"]
    _require(
        type(pins) is dict
        and set(pins)
        == {
            "manifest_sha256",
            "companion_sha256",
            "task_sha256",
            "dataset_id",
            *_COMPANION_PINS,
        },
        "ml_audited_base_pins_invalid",
    )
    for name, expected in expected_pins.items():
        _require(pins[name] == _hash(expected), "ml_audited_base_pins_invalid")
    for name in _COMPANION_PINS:
        _hash(pins[name])
    _require(
        type(dataset_id) is str and pins["dataset_id"] == dataset_id, "ml_audited_base_pins_invalid"
    )
    for name in ("review", "label"):
        observation = base[name + "_observation"]
        _require(
            type(observation) is dict
            and observation.get("observation_sha256") == pins[name + "_observation_sha256"],
            "ml_audited_base_pins_invalid",
        )
        _authority(observation.get("authority"))
    task = base["task"]
    _require(
        type(task) is dict
        and base_digest(task) == expected_pins["task_sha256"]
        and type(task.get("physical_features")) is list
        and type(task.get("structure_features")) is list,
        "ml_audited_base_task_invalid",
    )
    expected_views = {"C@B"}
    if task["physical_features"]:
        expected_views.update({"C@P", "CP@P"})
    if task["structure_features"]:
        expected_views.update({"C@S", "CS@S"})
    if task["physical_features"] and task["structure_features"]:
        expected_views.update({"C@PS", "CP@PS", "CS@PS", "CPS@PS"})
    views = base["views"]
    _require(type(views) is dict and set(views) == expected_views, "ml_audited_base_gate_invalid")
    no_go = []
    for name, view in views.items():
        _require(
            type(view) is dict and type(view.get("gate")) is dict, "ml_audited_base_gate_invalid"
        )
        gate = view["gate"]
        _require(
            set(gate) == {"status", "reason_codes"} and type(gate["reason_codes"]) is list,
            "ml_audited_base_gate_invalid",
        )
        codes = gate["reason_codes"]
        _require(
            all(
                type(code) is str
                and code
                in {
                    "nonempty_train_validation_test_required",
                    "no_training_features",
                    "no_added_features_observed_in_train",
                }
                for code in codes
            )
            and len(codes) == len(set(codes)),
            "ml_audited_base_gate_invalid",
        )
        # Frozen v4 view reasons preserve append order, not lexical ordering.
        _require(
            type(gate["status"]) is str and gate["status"] == ("no_go" if codes else "pass"),
            "ml_audited_base_gate_invalid",
        )
        if gate["status"] == "no_go":
            no_go.append(name)
    gate = base["gate"]
    _require(
        type(gate) is dict
        and set(gate) == {"status", "reason_codes", "no_go_views"}
        and gate["no_go_views"] == sorted(no_go),
        "ml_audited_base_gate_invalid",
    )
    _gate(
        {key: gate[key] for key in ("status", "reason_codes")},
        ["required_comparison_view_no_go"] if no_go else [],
    )


def _identity_core():
    from services import ml_identity_audit

    return ml_identity_audit


def _audit_contract(audit, *, base_hash, expected_pins, core):
    _require(
        type(audit) is dict
        and set(audit) == _AUDIT_FIELDS
        and audit["version"] == AUDIT_VERSION
        and audit["policy_version"] == AUDIT_POLICY_VERSION,
        "ml_audited_child_contract_invalid",
    )
    _authority(audit["authority"])
    _require(audit["independent_support_count"] is None, "ml_audited_independence_invalid")
    expected = {
        "base_dataset_sha256": base_hash,
        **{
            key: expected_pins[key]
            for key in ("manifest_sha256", "companion_sha256", "task_sha256")
        },
    }
    _require(
        type(audit["input_pins"]) is dict and audit["input_pins"] == expected,
        "ml_audited_child_pins_invalid",
    )
    _require(
        type(audit["completeness"]) is dict
        and canonical(audit["completeness"])
        == canonical(
            {
                "scope": "complete_captured_grouping_declarations",
                "uncaptured_relationships_known": False,
                "replication_registry_available": False,
            }
        ),
        "ml_audited_completeness_invalid",
    )
    _require(
        type(audit["limits"]) is dict
        and all(type(value) is int and value > 0 for value in audit["limits"].values())
        and canonical(audit["limits"]) == canonical(core.LIMITS),
        "ml_audited_child_limits_invalid",
    )
    for name in ("nodes", "components", "join_witnesses", "examples"):
        _require(type(audit[name]) is list, "ml_audited_child_contract_invalid")
    _require(
        type(audit["counts"]) is list
        and len(audit["counts"]) == 16
        and type(audit["relationship_components"]) is dict
        and set(audit["relationship_components"])
        == {
            "material_series",
            "sample_trajectory",
            "structure_near_duplicate",
        },
        "ml_audited_child_contract_invalid",
    )
    count_keys = set()
    for row in audit["counts"]:
        _require(
            type(row) is dict
            and set(row)
            == {"cohort", "partition", "rows", "components", "direct_label", "full_components"}
            and type(row["cohort"]) is str
            and row["cohort"] in {"B", "P", "S", "PS"}
            and type(row["partition"]) is str
            and row["partition"] in {"all", "train", "validation", "test"}
            and all(type(row[key]) is int and row[key] >= 0 for key in ("rows", "components")),
            "ml_audited_counts_invalid",
        )
        key = row["cohort"], row["partition"]
        _require(key not in count_keys, "ml_audited_counts_invalid")
        count_keys.add(key)
        for section, fields in (
            ("direct_label", {"identity_counts", "missing_identity_counts"}),
            ("full_components", {"identity_counts"}),
        ):
            item = row[section]
            _require(type(item) is dict and set(item) == fields, "ml_audited_counts_invalid")
            for values in item.values():
                _require(
                    type(values) is dict
                    and all(
                        type(name) is str and type(value) is int and value >= 0
                        for name, value in values.items()
                    ),
                    "ml_audited_counts_invalid",
                )
    checks = audit["checks"]
    _require(
        type(checks) is dict
        and set(checks) == set(_CHECK_CODES)
        and all(type(value) is list for value in checks.values()),
        "ml_audited_checks_invalid",
    )
    _gate(audit["gate"], [_CHECK_CODES[key] for key, items in checks.items() if items])


def _implementation():
    result = {}
    for module in _SOURCE_MODULES:
        payload = files("services").joinpath(module + ".py").read_bytes()
        _require(0 < len(payload) <= 1024 * 1024, "ml_audited_implementation_unavailable")
        result["services." + module] = hashlib.sha256(payload).hexdigest()
    return result


def build_audited_task_dataset(
    manifest,
    *,
    artifact_bytes,
    expected_manifest_sha256,
    companion,
    expected_companion_sha256,
    review_companion,
    expected_review_companion_sha256,
    label_companion,
    expected_label_companion_sha256,
    task,
    expected_task_sha256,
):
    """Build unchanged v4, then gate and detach the complete bounded audit package."""
    try:
        expected = {
            "manifest_sha256": expected_manifest_sha256,
            "companion_sha256": expected_companion_sha256,
            "task_sha256": expected_task_sha256,
            "review_companion_sha256": expected_review_companion_sha256,
            "label_companion_sha256": expected_label_companion_sha256,
        }
        for value in expected.values():
            _hash(value)
        implementation = _implementation()
        base = build_task_dataset_v4(
            manifest,
            artifact_bytes=artifact_bytes,
            expected_manifest_sha256=expected_manifest_sha256,
            companion=companion,
            expected_companion_sha256=expected_companion_sha256,
            review_companion=review_companion,
            expected_review_companion_sha256=expected_review_companion_sha256,
            label_companion=label_companion,
            expected_label_companion_sha256=expected_label_companion_sha256,
            task=task,
            expected_task_sha256=expected_task_sha256,
        )
        _base_contract(base, expected, manifest["dataset_id"])
        base_bytes = base_canonical(base)
        _require(len(base_bytes) <= MAX_BYTES, "ml_audited_byte_limit")
        base_hash = hashlib.sha256(base_bytes).hexdigest()
        # Child receives a private copy: it must not rewrite the already sealed
        # dataset to make its audit pass or mutate the returned original object.
        child_base = json.loads(base_bytes)
        core = _identity_core()
        audit = core.build_identity_audit(
            child_base,
            manifest=manifest,
            artifact_bytes=dict(artifact_bytes),
            companion=companion,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_companion_sha256=expected_companion_sha256,
        )
        _require(base_canonical(child_base) == base_bytes, "ml_audited_child_rewrote_base")
        _require(
            base_digest(manifest) == expected_manifest_sha256
            and base_digest(companion) == expected_companion_sha256,
            "ml_audited_input_changed",
        )
        _audit_contract(audit, base_hash=base_hash, expected_pins=expected, core=core)
        audit_bytes = core.canonical_audit(audit)
        _require(
            type(audit_bytes) is bytes and audit_bytes == canonical(audit),
            "ml_audited_child_encoding_invalid",
        )
        audit_hash = core.digest_audit(audit)
        _require(
            _hash(audit_hash) == hashlib.sha256(audit_bytes).hexdigest(),
            "ml_audited_child_hash_invalid",
        )
        _require(_implementation() == implementation, "ml_audited_implementation_changed")
        codes = []
        if base["gate"]["status"] != "pass":
            codes.append("base_dataset_no_go")
        if audit["gate"]["status"] != "pass":
            codes.append("identity_audit_no_go")
        package = {
            "version": VERSION,
            "base_dataset": json.loads(base_bytes),
            "base_dataset_sha256": base_hash,
            "identity_audit": json.loads(audit_bytes),
            "identity_audit_sha256": audit_hash,
            "audit_policy_version": AUDIT_POLICY_VERSION,
            "audit_implementation": implementation,
            "audit_implementation_sha256": digest(implementation),
            "gate": {"status": "no_go" if codes else "pass", "reason_codes": sorted(codes)},
            "authority": dict(AUTHORITY),
        }
        return json.loads(canonical(package))
    except MlAuditedDatasetError:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RecursionError,
        UnicodeError,
        OverflowError,
        OSError,
        ImportError,
        RuntimeError,
    ):
        raise MlAuditedDatasetError("ml_audited_build_failed") from None


def verify_audited_task_dataset(package, *, expected_package_sha256, **inputs):
    """An outer checksum alone never substitutes for rebuilding both layers."""
    try:
        _require(
            type(package) is dict and set(package) == _PACKAGE_FIELDS, "ml_audited_package_invalid"
        )
        payload = canonical(package)
        _require(
            hashlib.sha256(payload).hexdigest() == _hash(expected_package_sha256),
            "ml_audited_package_pin_mismatch",
        )
        rebuilt = build_audited_task_dataset(**inputs)
        _require(payload == canonical(rebuilt), "ml_audited_recomputation_mismatch")
        return {
            "version": VERSION,
            "package_sha256": expected_package_sha256,
            "base_dataset_sha256": rebuilt["base_dataset_sha256"],
            "identity_audit_sha256": rebuilt["identity_audit_sha256"],
            "audit_policy_version": AUDIT_POLICY_VERSION,
            "audit_implementation_sha256": rebuilt["audit_implementation_sha256"],
            "integrity_verified": True,
            "technical_gate": rebuilt["gate"]["status"],
            "gate_reason_codes": rebuilt["gate"]["reason_codes"],
            **{key: rebuilt["base_dataset"]["input_pins"][key] for key in _COMPANION_PINS},
            **AUTHORITY,
        }
    except MlAuditedDatasetError:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RecursionError,
        UnicodeError,
        OverflowError,
        OSError,
        ImportError,
        RuntimeError,
    ):
        raise MlAuditedDatasetError("ml_audited_verification_failed") from None


__all__ = [
    "VERSION",
    "AUDIT_VERSION",
    "AUDIT_POLICY_VERSION",
    "MAX_BYTES",
    "MAX_NODES",
    "MAX_DEPTH",
    "MlAuditedDatasetError",
    "canonical",
    "digest",
    "loads",
    "build_audited_task_dataset",
    "verify_audited_task_dataset",
]
