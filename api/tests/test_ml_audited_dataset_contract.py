"""Service-double defensive wrapper tests, not captured scientific evidence.

Actual SQL -> frozen v4 -> real audit -> offline CLI coverage lives separately
in test_ml_identity_audit_sql. These deliberately small unit documents exercise
the new wrapper's boundaries without replacing any frozen production globals.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from decimal import Decimal
from importlib.resources import files
from types import SimpleNamespace

import pytest

from models.ml_task_v4 import default_task_v4
from services import ml_audited_dataset as wrapper
from services import ml_identity_audit as core
from services.ml_dataset_builder import AUTHORITY
from services.research_release_manifest import canonical as old_canonical
from services.research_release_manifest import digest as old_digest


def unit_documents(*, physical=False, structure=False):
    """Non-scientific service doubles; no claim that these are valid capsules."""
    task = default_task_v4()
    task["physical_features"] = [{"unit_double": True}] if physical else []
    task["structure_features"] = ["unit_double"] if structure else []
    inputs = {
        "manifest": {"dataset_id": "synthetic-contract-unit-only"},
        "artifact_bytes": {"synthetic-unit": b"not-source-evidence"},
        "companion": {"unit_double": "source"},
        "review_companion": {"unit_double": "review"},
        "label_companion": {"unit_double": "label"},
        "task": task,
    }
    for key in ("manifest", "companion", "review_companion", "label_companion", "task"):
        inputs["expected_" + key + "_sha256"] = old_digest(inputs[key])
    pins = {
        key.removeprefix("expected_"): value
        for key, value in inputs.items()
        if key.startswith("expected_")
    }
    pins.update(
        dataset_id=inputs["manifest"]["dataset_id"],
        review_observation_sha256="a" * 64,
        label_observation_sha256="b" * 64,
    )
    names = ["C@B"]
    if physical:
        names += ["C@P", "CP@P"]
    if structure:
        names += ["C@S", "CS@S"]
    if physical and structure:
        names += ["C@PS", "CP@PS", "CS@PS", "CPS@PS"]
    base = {
        "version": "ml-task-dataset/4.0.0",
        "task": deepcopy(task),
        "authority": dict(AUTHORITY),
        "compiler": {"unit_double": True},
        "input_pins": pins,
        "review_observation": {
            "observation_sha256": pins["review_observation_sha256"],
            "authority": dict(AUTHORITY),
        },
        "label_observation": {
            "observation_sha256": pins["label_observation_sha256"],
            "authority": dict(AUTHORITY),
        },
        "candidates": [],
        "rows": [],
        "views": {name: {"gate": {"status": "pass", "reason_codes": []}} for name in names},
        "cohorts": {},
        "coverage": {},
        "dependency_manifest": {},
        "split_report": {},
        "comparisons": [],
        "gate": {"status": "pass", "reason_codes": [], "no_go_views": []},
        "data_card": {"unit_double": "not scientific evidence"},
    }
    return inputs, base


def unit_audit(base, inputs):
    return {
        "version": core.VERSION,
        "policy_version": core.POLICY_VERSION,
        "input_pins": {
            "base_dataset_sha256": old_digest(base),
            **{
                key: base["input_pins"][key]
                for key in ("manifest_sha256", "companion_sha256", "task_sha256")
            },
        },
        "completeness": {
            "scope": "complete_captured_grouping_declarations",
            "uncaptured_relationships_known": False,
            "replication_registry_available": False,
        },
        "limits": dict(core.LIMITS),
        "nodes": [],
        "components": [],
        "join_witnesses": [],
        "examples": [],
        "counts": [
            {
                "cohort": cohort,
                "partition": partition,
                "rows": 0,
                "components": 0,
                "direct_label": {"identity_counts": {}, "missing_identity_counts": {}},
                "full_components": {"identity_counts": {}},
            }
            for cohort in ("B", "P", "S", "PS")
            for partition in ("all", "train", "validation", "test")
        ],
        "relationship_components": {
            key: {} for key in ("material_series", "sample_trajectory", "structure_near_duplicate")
        },
        "checks": {key: [] for key in core.CHECK_CODES},
        "gate": {"status": "pass", "reason_codes": []},
        "authority": dict(AUTHORITY),
        "independent_support_count": None,
    }


@pytest.fixture
def doubles(monkeypatch):
    inputs, base = unit_documents()
    state = SimpleNamespace(inputs=inputs, base=base, audits=[], calls=[], mutate=None)

    def build_base(manifest, **kwargs):
        state.calls.append((manifest, kwargs))
        return deepcopy(state.base)

    def audit_child(child, **kwargs):
        value = unit_audit(child, state.inputs)
        if state.mutate is not None:
            state.mutate(child, value, kwargs)
        state.audits.append(value)
        return value

    state.core = SimpleNamespace(
        LIMITS=dict(core.LIMITS),
        build_identity_audit=audit_child,
        canonical_audit=core.canonical_audit,
        digest_audit=core.digest_audit,
    )
    # Patch only names belonging to the NEW wrapper, never the old builder.
    monkeypatch.setattr(wrapper, "build_task_dataset_v4", build_base)
    monkeypatch.setattr(wrapper, "_identity_core", lambda: state.core)
    monkeypatch.setattr(
        wrapper,
        "_implementation",
        lambda: {
            "services.ml_audited_dataset": "c" * 64,
            "services.ml_identity_audit": "d" * 64,
        },
    )
    return state


@pytest.mark.parametrize(
    "physical,structure,count",
    [(False, False, 1), (True, False, 3), (False, True, 3), (True, True, 9)],
)
def test_conditional_views_preserve_complete_original_base(doubles, physical, structure, count):
    doubles.inputs, doubles.base = unit_documents(physical=physical, structure=structure)
    package = wrapper.build_audited_task_dataset(**doubles.inputs)
    assert len(package["base_dataset"]["views"]) == count
    assert old_canonical(package["base_dataset"]) == old_canonical(doubles.base)
    assert package["base_dataset_sha256"] == old_digest(doubles.base)
    assert package["identity_audit_sha256"] == core.digest_audit(package["identity_audit"])
    assert package["audit_implementation_sha256"] == wrapper.digest(package["audit_implementation"])
    assert package["gate"] == {"status": "pass", "reason_codes": []}
    assert package["authority"] == AUTHORITY
    assert set(doubles.calls[0][1]) == set(doubles.inputs) - {"manifest"}


def test_receipt_rebuilds_and_pins_both_observations(doubles):
    package = wrapper.build_audited_task_dataset(**doubles.inputs)
    receipt = wrapper.verify_audited_task_dataset(
        package, expected_package_sha256=wrapper.digest(package), **doubles.inputs
    )
    assert len(doubles.calls) == 2
    assert receipt["integrity_verified"] is True
    assert receipt["technical_gate"] == "pass"
    for key in wrapper._COMPANION_PINS:
        assert receipt[key] == doubles.base["input_pins"][key]
    for key in AUTHORITY:
        assert receipt[key] is False
    assert receipt["base_dataset_sha256"] == old_digest(doubles.base)
    assert receipt["identity_audit_sha256"] == core.digest_audit(package["identity_audit"])


def test_detached_result_and_child_artifact_mapping(doubles):
    before = deepcopy(doubles.inputs)
    doubles.mutate = lambda child, audit, kwargs: kwargs["artifact_bytes"].clear()
    package = wrapper.build_audited_task_dataset(**doubles.inputs)
    package["base_dataset"]["data_card"]["unit_double"] = "changed"
    package["identity_audit"]["counts"].clear()
    assert doubles.inputs == before
    assert doubles.base["data_card"]["unit_double"] == "not scientific evidence"
    assert len(doubles.audits[0]["counts"]) == 16


@pytest.mark.parametrize("base_failed,audit_failed", [(True, False), (False, True), (True, True)])
def test_aggregate_no_go_is_mandatory_and_preserves_negative_report(
    doubles, base_failed, audit_failed
):
    if base_failed:
        doubles.base["views"]["C@B"]["gate"] = {
            "status": "no_go",
            "reason_codes": ["no_training_features"],
        }
        doubles.base["gate"] = {
            "status": "no_go",
            "reason_codes": ["required_comparison_view_no_go"],
            "no_go_views": ["C@B"],
        }
    if audit_failed:

        def fail(child, audit, kwargs):
            audit["checks"]["component_crossings"] = [
                {
                    "component_sha256": "a" * 64,
                    "partitions": ["train", "test"],
                    "example_ids": ["unit-a", "unit-b"],
                }
            ]
            audit["gate"] = {"status": "no_go", "reason_codes": ["component_partition_crossing"]}

        doubles.mutate = fail
    package = wrapper.build_audited_task_dataset(**doubles.inputs)
    expected = (["base_dataset_no_go"] if base_failed else []) + (
        ["identity_audit_no_go"] if audit_failed else []
    )
    assert package["gate"] == {"status": "no_go", "reason_codes": expected}
    assert package["authority"] == AUTHORITY


def set_path(value, path, replacement):
    parent = value
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = replacement


@pytest.mark.parametrize(
    "path,replacement",
    [
        (("version",), "future"),
        (("extra",), False),
        (("authority", "scientific_acceptance"), True),
        (("authority", "public_release"), 0),
        (("authority", "invented"), False),
        (("input_pins", "task_sha256"), "0" * 64),
        (("independent_support_count",), 0),
        (("independent_support_count",), 3),
        (("completeness", "uncaptured_relationships_known"), 0),
        (("completeness", "replication_registry_available"), True),
        (("completeness", "scope"), "all_real_world_relationships"),
        (("limits", "nodes"), True),
        (("limits", "nodes"), 30000),
        (("nodes",), {}),
        (("examples",), None),
        (("counts",), {}),
        (("counts",), []),
        (("counts", 0, "rows"), True),
        (("counts", 0, "components"), -1),
        (("counts", 0, "partition"), "validation_test"),
        (("counts", 0, "direct_label", "identity_counts", "claim"), False),
        (("relationship_components", "invented_independence"), []),
        (("checks", "identity_crossings"), None),
        (("checks", "invented"), []),
        (("gate", "status"), True),
        (("gate", "status"), "no_go"),
        (("gate", "reason_codes"), ["scientific_approval"]),
        (("gate", "reason_codes"), ["identity_partition_crossing"]),
        (("checks", "identity_crossings"), [{"unit_double": True}]),
    ],
)
def test_malformed_child_closed_contract_cannot_pass(doubles, path, replacement):
    doubles.mutate = lambda child, audit, kwargs: set_path(audit, path, replacement)
    with pytest.raises(wrapper.MlAuditedDatasetError):
        wrapper.build_audited_task_dataset(**doubles.inputs)


@pytest.mark.parametrize(
    "path,replacement",
    [
        (("version",), "ml-task-dataset/3.0.0"),
        (("extra",), 1),
        (("authority", "scientific_acceptance"), 0),
        (("task", "task_id"), "substituted"),
        (("input_pins", "dataset_id"), "wrong"),
        (("input_pins", "manifest_sha256"), "0" * 64),
        (("review_observation", "observation_sha256"), "0" * 64),
        (("label_observation", "authority", "ml_training_approved"), True),
        (("views",), {}),
        (("views", "CP@P"), {"gate": {"status": "pass", "reason_codes": []}}),
        (("views", "C@B", "gate", "status"), "no_go"),
        (("views", "C@B", "gate", "reason_codes"), ["unrecognized"]),
        (("gate", "no_go_views"), ["C@B"]),
        (("gate", "status"), False),
    ],
)
def test_malformed_base_gate_pins_and_authority_reject(doubles, path, replacement):
    set_path(doubles.base, path, replacement)
    with pytest.raises(wrapper.MlAuditedDatasetError):
        wrapper.build_audited_task_dataset(**doubles.inputs)


def test_child_cannot_rewrite_sealed_base(doubles):
    doubles.mutate = lambda child, audit, kwargs: child["rows"].append({"unit_double": "changed"})
    with pytest.raises(wrapper.MlAuditedDatasetError, match="child_rewrote_base"):
        wrapper.build_audited_task_dataset(**doubles.inputs)


@pytest.mark.parametrize("key", ["manifest", "companion"])
def test_child_input_mutation_refused(doubles, key):
    doubles.mutate = lambda child, audit, kwargs: kwargs[key].update(substituted=True)
    with pytest.raises(wrapper.MlAuditedDatasetError, match="input_changed"):
        wrapper.build_audited_task_dataset(**doubles.inputs)


@pytest.mark.parametrize("encoding,hashing", [(True, False), (False, True)])
def test_child_serializer_and_digest_cannot_substitute_evidence(doubles, encoding, hashing):
    if encoding:
        doubles.core.canonical_audit = lambda value: b"{}"
    if hashing:
        doubles.core.digest_audit = lambda value: "0" * 64
    with pytest.raises(wrapper.MlAuditedDatasetError):
        wrapper.build_audited_task_dataset(**doubles.inputs)


@pytest.mark.parametrize(
    "path,replacement",
    [
        (("base_dataset", "rows"), [{"unit_double": "invented"}]),
        (("base_dataset", "data_card", "unit_double"), "changed"),
        (("identity_audit", "counts", 0, "rows"), 42),
        (("identity_audit", "gate", "status"), "no_go"),
        (("audit_implementation", "services.ml_identity_audit"), "0" * 64),
        (("audit_policy_version",), "substituted"),
        (("authority", "scientific_acceptance"), True),
        (("gate", "status"), "no_go"),
    ],
)
def test_resealed_tamper_fails_full_recomputation(doubles, path, replacement):
    package = wrapper.build_audited_task_dataset(**doubles.inputs)
    set_path(package, path, replacement)
    package["base_dataset_sha256"] = old_digest(package["base_dataset"])
    package["identity_audit"]["input_pins"]["base_dataset_sha256"] = package["base_dataset_sha256"]
    package["identity_audit_sha256"] = core.digest_audit(package["identity_audit"])
    package["audit_implementation_sha256"] = wrapper.digest(package["audit_implementation"])
    with pytest.raises(wrapper.MlAuditedDatasetError, match="recomputation_mismatch"):
        wrapper.verify_audited_task_dataset(
            package, expected_package_sha256=wrapper.digest(package), **doubles.inputs
        )


def test_wrong_outer_pin_fails_before_rebuild(doubles):
    package = wrapper.build_audited_task_dataset(**doubles.inputs)
    with pytest.raises(wrapper.MlAuditedDatasetError, match="pin_mismatch"):
        wrapper.verify_audited_task_dataset(
            package, expected_package_sha256="0" * 64, **doubles.inputs
        )
    assert len(doubles.calls) == 1


def test_changing_implementation_rejected(doubles, monkeypatch):
    values = iter(
        [{"services.ml_audited_dataset": "a" * 64}, {"services.ml_audited_dataset": "b" * 64}]
    )
    monkeypatch.setattr(wrapper, "_implementation", lambda: next(values))
    with pytest.raises(wrapper.MlAuditedDatasetError, match="implementation_changed"):
        wrapper.build_audited_task_dataset(**doubles.inputs)


def test_actual_source_inventory_pins_only_new_modules():
    actual = wrapper._implementation()
    assert set(actual) == {"services.ml_audited_dataset", "services.ml_identity_audit"}
    for name, checksum in actual.items():
        assert (
            checksum
            == hashlib.sha256(
                files("services").joinpath(name.split(".")[-1] + ".py").read_bytes()
            ).hexdigest()
        )


@pytest.mark.parametrize("error", [ValueError, TypeError, OSError, RuntimeError])
def test_child_failure_is_static_not_private_text(doubles, error):
    def fail(*args, **kwargs):
        raise error("SECRET private source /user/private/path token=abc")

    doubles.core.build_identity_audit = fail
    with pytest.raises(wrapper.MlAuditedDatasetError) as caught:
        wrapper.build_audited_task_dataset(**doubles.inputs)
    assert str(caught.value) == "ml_audited_build_failed"


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        0,
        -100,
        -0.0,
        1e-20,
        {"文": 'é\\"\n\t\b\f\r\x01', "a": [1, 0.25, None]},
        [[], {}],
    ],
)
def test_canonical_exact_old_encoding_and_roundtrip(value):
    raw = wrapper.canonical(value)
    assert raw == old_canonical(value)
    assert wrapper.loads(raw) == value
    assert wrapper.digest(value) == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), -float("inf"), Decimal("1"), b"x", (1,), {1: "x"}, "\ud800"],
)
def test_non_json_and_nonfinite_refusal(value):
    with pytest.raises(wrapper.MlAuditedDatasetError):
        wrapper.canonical(value)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":2}',
        b'{"a":1,"\\u0061":2}',
        b"NaN",
        b"Infinity",
        b"-Infinity",
        b"1e999",
        b"{}{}",
        b'{"a": 1}',
        b"\xef\xbb\xbf{}",
        b'"\xff"',
        b'"\\ud800"',
        b"[",
        b"",
        b"\n{}",
    ],
)
def test_loads_duplicate_nonfinite_noncanonical_and_invalid_utf8(raw):
    with pytest.raises(wrapper.MlAuditedDatasetError):
        wrapper.loads(raw)


def test_string_escape_size_exact_before_allocation(monkeypatch):
    value = {"文": '\x01\n\t\r\\"é'}
    raw = old_canonical(value)
    monkeypatch.setattr(wrapper, "MAX_BYTES", len(raw))
    assert wrapper.canonical(value) == raw
    monkeypatch.setattr(wrapper, "MAX_BYTES", len(raw) - 1)
    with pytest.raises(wrapper.MlAuditedDatasetError, match="byte_limit"):
        wrapper.canonical(value)


def test_cumulative_size_not_only_individual_strings(monkeypatch):
    monkeypatch.setattr(wrapper, "MAX_BYTES", 100)
    with pytest.raises(wrapper.MlAuditedDatasetError, match="byte_limit"):
        wrapper.canonical(["x" * 45, {"a": "y" * 45}])


def test_cycle_refusal_and_repeated_noncyclic_aliases():
    shared = ["x"]
    assert wrapper.canonical([shared, shared]) == b'[["x"],["x"]]'
    shared.append(shared)
    with pytest.raises(wrapper.MlAuditedDatasetError, match="cycle"):
        wrapper.canonical(shared)


def test_cumulative_node_limit_applies_to_keys_and_values(monkeypatch):
    monkeypatch.setattr(wrapper, "MAX_NODES", 5)
    assert wrapper.canonical({"a": 1, "b": 2}) == b'{"a":1,"b":2}'
    with pytest.raises(wrapper.MlAuditedDatasetError, match="json_limit"):
        wrapper.canonical({"a": 1, "b": [2]})
    with pytest.raises(wrapper.MlAuditedDatasetError, match="json_limit"):
        wrapper.loads(b'{"a":1,"b":[2]}')


def test_depth_limit_before_and_after_parse(monkeypatch):
    monkeypatch.setattr(wrapper, "MAX_DEPTH", 3)
    assert wrapper.loads(b"[[[0]]]") == [[[0]]]
    for value in ([[[[0]]]],):
        with pytest.raises(wrapper.MlAuditedDatasetError, match="json_limit"):
            wrapper.canonical(value)
    with pytest.raises(wrapper.MlAuditedDatasetError, match="json_limit"):
        wrapper.loads(b"[[[[0]]]]")


def test_outer_owned_bounds_accept_more_than_old_eight_mib():
    value = {"unit_double": "x" * (8 * 1024 * 1024)}
    raw = wrapper.canonical(value)
    assert 8 * 1024 * 1024 < len(raw) < wrapper.MAX_BYTES
    assert wrapper.loads(raw) == value


def test_subclass_not_silently_coerced():
    class Hidden(dict):
        pass

    with pytest.raises(wrapper.MlAuditedDatasetError, match="json_type"):
        wrapper.canonical(Hidden(a=1))


def test_loads_requires_bytes_not_arbitrary_path_or_text():
    for value in ("{}", bytearray(b"{}"), "/secret/path"):
        with pytest.raises(wrapper.MlAuditedDatasetError):
            wrapper.loads(value)
