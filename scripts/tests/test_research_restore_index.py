"""Offline helper boundaries; actual SQL restore is exercised by guarded worker."""
from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import research_restore_index as index


def descriptor():
    generation = "00000000-0000-4000-8000-000000000001"
    return {"version": index.VERSION, "logical_index": "restore-drill-" + UUID(generation).hex,
        "generation_id": generation, "activation_event_id": "00000000-0000-4000-8000-000000000002",
        "validation_id": "00000000-0000-4000-8000-000000000003", "paper_id": "synthetic-paper",
        "material_id": "synthetic-material", "claim_id": "00000000-0000-4000-8000-000000000004",
        **{field: "a" * 64 for field in index._HASH_FIELDS}, "member_count": 2}


def report():
    return {"version": index.REPORT_VERSION, **index._REPORT_COUNTS,
        **{field: "a" * 64 for field in index._REPORT_HASHES},
        **{field: True for field in index._REPORT_TRUE},
        **{field: False for field in index._REPORT_FALSE}}


def members():
    vector = b"\x3e\x00\x00\x00" * 768
    return [{"vector_id": "synthetic-" + str(number), "vector_bytes": vector,
        "vector_sha256": hashlib.sha256(vector).hexdigest(), "snapshot_json": {"text": "synthetic pending " + str(number)},
        "evidence_revision_id": "00000000-0000-4000-8000-00000000000" + str(number + 5),
        "receipt_id": "00000000-0000-4000-8000-00000000000" + str(number + 7)} for number in range(2)]


def test_import_is_stdlib_only_and_does_not_need_api_or_clients():
    process = subprocess.run([sys.executable, "-I", "-S", "-c", """
import importlib.util, sys
spec = importlib.util.spec_from_file_location('restore_index', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('sqlalchemy', 'models.db', 'google', 'redis', 'services'))
""", str(ROOT / "scripts/research_restore_index.py")], capture_output=True, text=True, timeout=10)
    assert process.returncode == 0, process.stderr


def test_descriptor_is_exact_detached_and_has_no_source_payload():
    original = descriptor()
    validated = index.validate_descriptor(original)
    assert validated == original and validated is not original
    validated["paper_id"] = "changed"
    assert original["paper_id"] == "synthetic-paper"
    assert len(json.dumps(original)) < index.MAX_DESCRIPTOR_BYTES


@pytest.mark.parametrize("change", [
    {"version": "other"}, {"member_count": True}, {"member_count": 3},
    {"paper_id": "secret/../../paper"}, {"material_id": "bad\nidentifier"},
    {"material_id": "x" * 101}, {"generation_id": 1},
    {"generation_id": "00000000000040008000000000000001"},
    {"logical_index": "sclib-main"}, {"pin_sha256": "A" * 64},
    {"raw_record_sha256": False}, {"source_text": "PRIVATE CANARY"},
    {"resource": {"backend": "vertex-public"}},
])
def test_descriptor_refuses_substitution_and_unknown_private_fields(change):
    with pytest.raises(index.RestoreIndexError) as error:
        index.validate_descriptor({**descriptor(), **change})
    assert "CANARY" not in str(error.value) and "secret" not in str(error.value)


def test_descriptor_missing_pin_fails_before_any_database_access():
    value = descriptor()
    del value["claim_record_sha256"]
    with pytest.raises(index.RestoreIndexError):
        asyncio.run(index.verify_index(object(), value))


def test_resource_is_fixed_disposable_namespace_not_caller_supplied():
    resource = index._resource(descriptor()["generation_id"])
    assert resource["backend"] == "disposable"
    assert resource["project"] == "synthetic-restore-rehearsal"
    assert resource["feature_norm"] == "NONE"
    assert resource["distance_measure"] == "COSINE_DISTANCE"


def test_disposable_resource_matches_actual_adapter_contract_without_network():
    # Even the disposable adapter requires SDK-shaped resource paths. Verify
    # against the real parser so orchestration doubles cannot hide a mismatch.
    process = subprocess.run([sys.executable, "-I", "-c", """
import importlib.util, sys
def audit(event, args):
    if event == 'socket.connect':
        raise AssertionError('No network in resource validation')
sys.addaudithook(audit)
sys.path.insert(0, sys.argv[1])
spec = importlib.util.spec_from_file_location('restore_index', sys.argv[2])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
from services.index_vector_adapter import _pin, PROFILE
identifier = '00000000-0000-4000-8000-000000000001'
pin = {'generation_id': identifier, 'activation_event_id': None,
       'resource': module._resource(identifier), 'profile': PROFILE, 'manifest_sha256': 'a'*64}
assert _pin(pin) == pin
""", str(ROOT / "api"), str(ROOT / "scripts/research_restore_index.py")],
        capture_output=True, text=True, timeout=10)
    assert process.returncode == 0, process.stderr


@pytest.mark.parametrize("isolation,read_only,zone,budget", [
    ("read committed", "on", "UTC", True),
    ("repeatable read", "off", "UTC", True),
    ("repeatable read", "on", "localtime", True),
    ("repeatable read", "on", "UTC", False),
    ("repeatable read", "on", "UTC", 1),
])
def test_restore_requires_read_only_snapshot_utc_and_real_bounded_deadline(isolation, read_only, zone, budget):
    db = SimpleNamespace(new=(), dirty=(), deleted=(),
                         scalar=AsyncMock(side_effect=[isolation, read_only, zone, budget]))
    with pytest.raises(index.RestoreIndexError):
        asyncio.run(index._session(db, readonly=True))


def test_read_only_session_admission_never_sets_transaction_or_commits():
    db = SimpleNamespace(new=(), dirty=(), deleted=(),
                         scalar=AsyncMock(side_effect=["repeatable read", "on", "UTC", True]))
    asyncio.run(index._session(db, readonly=True))
    assert db.scalar.await_count == 4


@pytest.mark.parametrize("state", ["new", "dirty", "deleted"])
def test_dirty_session_rejected_before_sql(state):
    db = SimpleNamespace(new=(), dirty=(), deleted=(), scalar=AsyncMock())
    setattr(db, state, (object(),))
    with pytest.raises(index.RestoreIndexError):
        asyncio.run(index._session(db, readonly=True))
    db.scalar.assert_not_awaited()


def test_report_requires_all_measured_checks_and_no_authority():
    value = report()
    assert index.validate_report(value) == value
    assert index.validate_report(value) is not value


@pytest.mark.parametrize("key,value", [
    ("member_count", True), ("initial_index_count", 1), ("replay_upsert_count", 2),
    ("vector_bytes", 0), ("orphan_count", None), ("missing_count", 1),
    ("database_unchanged", False), ("full_inventory_observed", 1),
    ("scientific_acceptance", True), ("provider_io_performed", True),
    ("external_production_vector_restore_verified", True),
    ("member_manifest_sha256", "short"), ("source_text", "PRIVATE CANARY"),
])
def test_report_cannot_launder_partial_recovery_or_unknown_into_success(key, value):
    with pytest.raises(index.RestoreIndexError):
        index.validate_report({**report(), key: value})


def test_inventory_binds_vectors_revisions_receipts_and_full_snapshots_order_independently():
    original = members()
    expected = index.member_inventory_sha256(original)
    assert expected == index.member_inventory_sha256(list(reversed(original)))
    assert type(original[0]["vector_bytes"]) is bytes
    for key, value in [("evidence_revision_id", "different"), ("receipt_id", "different"),
                       ("snapshot_json", {"text": "different source wording"})]:
        changed = deepcopy(original)
        changed[0][key] = value
        assert index.member_inventory_sha256(changed) != expected


@pytest.mark.parametrize("mutation", ["partial", "extra", "duplicate", "vector", "size", "nonfinite"])
def test_inventory_refuses_partial_duplicate_corrupt_or_oversized_input(mutation):
    value = members()
    if mutation == "partial":
        value.pop()
    elif mutation == "extra":
        value.append(deepcopy(value[0]))
    elif mutation == "duplicate":
        value[1] = deepcopy(value[0])
    elif mutation == "vector":
        value[0]["vector_bytes"] = b"\x00" * 3072
    elif mutation == "size":
        value[0]["snapshot_json"]["text"] = "x" * (256 * 1024)
    else:
        value[0]["snapshot_json"]["bad"] = float("nan")
    with pytest.raises(index.RestoreIndexError):
        index.member_inventory_sha256(value)


@pytest.fixture
def restored(monkeypatch):
    """Pure orchestration doubles. No DB connection or production client."""
    value = descriptor()
    pin = {"generation_id": value["generation_id"], "activation_event_id": value["activation_event_id"],
        "resource": index._resource(value["generation_id"]), "manifest_sha256": value["member_manifest_sha256"]}
    value["pin_sha256"] = index._digest(pin)
    retained = members()
    value["member_inventory_sha256"] = index.member_inventory_sha256(retained)
    raw = {"synthetic": True}
    value["raw_record_sha256"] = index._digest(raw)
    services = ModuleType("services")
    generations = ModuleType("services.index_generations")
    generations.load_active_generation = AsyncMock(return_value=pin)
    generations.load_generation_members = AsyncMock(return_value=retained)
    generations.manifest_sha256 = lambda rows: value["member_manifest_sha256"]
    vectors = ModuleType("services.index_vector_adapter")
    class Disposable:
        def __init__(self):
            self.points = {}
    vectors.DisposableIndex = Disposable
    adapters = []
    def register(resource, adapter):
        assert resource["backend"] == "disposable"
        adapters.append(adapter)
        return adapter
    vectors.register_disposable = register
    def publish(pin, rows):
        adapter = adapters[-1]
        previous = len(adapter.points)
        adapter.points.update({row["vector_id"]: row for row in rows})
        return {"acknowledged_count": len(rows) - previous, "already_present_count": previous}
    vectors.publish = publish
    vectors.observe = lambda pin, rows: {"vectors": sorted(adapters[-1].points), "full_inventory_observed": True}
    vectors.repair_plan = lambda *args: {"missing_ids": [], "hash_mismatch_ids": [], "observed_orphan_ids": [],
                                        "declared_members_complete": True}
    services.index_vector_adapter = vectors
    monkeypatch.setitem(sys.modules, "services", services)
    monkeypatch.setitem(sys.modules, "services.index_generations", generations)
    monkeypatch.setitem(sys.modules, "services.index_vector_adapter", vectors)
    monkeypatch.setattr(index, "_session", AsyncMock())
    ledger = AsyncMock(return_value={"synthetic_record_sha256": "a" * 64})
    monkeypatch.setattr(index, "_ledger", ledger)
    monkeypatch.setattr(index, "_claim", AsyncMock(return_value=(raw, value["claim_record_sha256"])))
    monkeypatch.setattr(index, "_hydration_sha256", AsyncMock(return_value=value["hydration_sha256"]))
    db = SimpleNamespace(scalar=AsyncMock(return_value=True))
    return SimpleNamespace(descriptor=value, pin=pin, retained=retained, vectors=vectors, generations=generations,
                           adapters=adapters, db=db, ledger=ledger)


def test_restore_reuses_retained_members_and_never_stages_or_commits(restored):
    first = asyncio.run(index.verify_index(restored.db, restored.descriptor))
    assert first["initial_upsert_count"] == 2 and first["replay_upsert_count"] == 0
    assert first["database_unchanged"] is True
    assert restored.ledger.await_count == 2
    assert restored.adapters[0].points["synthetic-0"] is restored.retained[0]
    second = asyncio.run(index.verify_index(restored.db, restored.descriptor))
    assert second == first and len(restored.adapters) == 2
    assert restored.adapters[0] is not restored.adapters[1]
    # No stage/activation/commit functions exist on these doubles: calling any
    # would fail, rather than merely count a mocked write as a successful test.


@pytest.mark.parametrize("failure", ["cloud", "different_activation", "partial", "claim", "ledger", "readback"])
def test_restore_refuses_wrong_identity_incomplete_inventory_and_mutation(restored, monkeypatch, failure):
    if failure == "cloud":
        restored.pin["resource"]["backend"] = "vertex-public"
        restored.descriptor["pin_sha256"] = index._digest(restored.pin)
    elif failure == "different_activation":
        restored.pin["activation_event_id"] = descriptor()["claim_id"]
        restored.descriptor["pin_sha256"] = index._digest(restored.pin)
    elif failure == "partial":
        restored.retained.pop()
    elif failure == "claim":
        monkeypatch.setattr(index, "_claim", AsyncMock(return_value=({"synthetic": True}, "b" * 64)))
    elif failure == "ledger":
        restored.ledger.side_effect = [{"epoch": 1}, {"epoch": 2}]
    else:
        counter = iter([{"vectors": [1], "full_inventory_observed": True},
                        {"vectors": [2], "full_inventory_observed": True}])
        restored.vectors.observe = lambda *args: next(counter)
    with pytest.raises(index.RestoreIndexError):
        asyncio.run(index.verify_index(restored.db, restored.descriptor))
    if failure in {"cloud", "different_activation", "partial", "claim"}:
        assert not restored.adapters  # Refusal precedes any target adapter.
