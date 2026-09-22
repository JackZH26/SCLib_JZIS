"""Declared synthetic pure label audits; native capture is tested separately."""
from copy import deepcopy
from decimal import Decimal
from uuid import UUID

import pytest

from services import ml_label_companion as companion
from services import ml_label_observation as labels
from services.ml_review_projection import sql_canonical
from services.ml_review_source_observation import lifecycle_record_sha, parse, pg_json, raw_sha
from services.research_release_manifest import canonical, digest
from services.research_release_spec import SPEC


def uid(number):
    return str(UUID(int=number))


def row(table, identifier, **values):
    """Only type-valid synthetic rows, not a claimed scientific gold capsule."""
    result = {}
    for key, declaration in SPEC[table]["fields"].items():
        kind = declaration["type"]
        result[key] = (None if declaration["nullable"] else {} if kind == "JSONB"
            else False if kind == "BOOLEAN" else 0 if kind in {"INTEGER", "SMALLINT", "BIGINT", "FLOAT", "DOUBLE PRECISION"}
            else uid(900) if kind == "UUID" else "2026-09-01T00:00:00Z" if kind == "DATETIME"
            else "2026-09-01" if kind == "DATE" else [] if kind.startswith("ARRAY") else "synthetic")
    result["paper_id" if table == "paper_work_map" else "id"] = identifier
    result.update(values)
    return result


def wire(table, value):
    text = sql_canonical(parse(canonical(value).decode()))
    return {"table": table, "row_id": value["paper_id" if table == "paper_work_map" else "id"],
            "row_text": text, "row_sha256": raw_sha(text)}


def fixture(*, paper=False, event=False):
    material = row("materials", "synthetic:MgB2", formula="MgB2", formula_normalized="MgB2", status="active", records=[])
    claim = row("material_claims", uid(1), material_id=material["id"], source_snapshot_id=uid(3),
                validity_status="accepted", value_kelvin=39.0)
    dataset = row("ml_dataset_snapshots", uid(2), source_snapshot_id=uid(3))
    example = row("ml_examples", uid(4), claim_id=claim["id"], dataset_snapshot_id=dataset["id"], material_id=material["id"])
    values = {("materials", material["id"]): material, ("material_claims", claim["id"]): claim,
        ("ml_dataset_snapshots", dataset["id"]): dataset, ("ml_examples", example["id"]): example,
        ("source_snapshots", uid(3)): row("source_snapshots", uid(3))}
    if event:
        claim["event_id"] = uid(5)
        values[("research_events", uid(5))] = row("research_events", uid(5), material_id=material["id"],
            state_id=uid(6), event_type="measurement", knowledge_origin="Observed", review_status="approved",
            validity_status="accepted", revision=1, decision_artifact_id=uid(7))
        values[("material_states", uid(6))] = row("material_states", uid(6), material_id=material["id"], source_artifact_id=uid(7))
        values[("evidence_artifacts", uid(7))] = row("evidence_artifacts", uid(7), kind="review")
    if paper:
        claim["paper_id"] = "synthetic:paper"
        values[("papers", claim["paper_id"])] = row("papers", claim["paper_id"], status="published")
    base = {"dataset_id": dataset["id"], "rows": [{"table": table, "row_id": key, "data": value,
        "row_sha256": digest(value)} for (table, key), value in sorted(values.items())]}
    inventory = labels.label_inventory(base)
    observation = {"version": labels.VERSION, "capture_admission": {"version": labels.EXPORT_SCOPE,
        "actor_user_id": uid(100), "actor_grant_id": uid(101)}, **labels._inventory_lists(base, inventory),
        "rows": [wire(table, value) for (table, _), value in sorted(values.items())], "lifecycle": []}
    refresh_lifecycle(observation)
    review = {"observation": {"capture_admission": {**observation["capture_admission"], "version": "ml_review_full_audit/1.0.0"},
        "source_observation": {"rows": [], "lifecycle": []}}}
    return base, observation, review


def refresh_lifecycle(observation):
    observation["lifecycle"] = []
    for record in observation["rows"]:
        if record["table"] not in {"papers", "works"}:
            continue
        data = parse(record["row_text"])
        kind = "paper" if record["table"] == "papers" else "work"
        fields = labels.PAPER_FIELDS if kind == "paper" else labels.WORK_FIELDS
        snapshot = {"version": "source-lifecycle-snapshot/1.0.0", "kind": kind,
                    "snapshot": {key: data[key] for key in fields}}
        text = pg_json(snapshot)
        observation["lifecycle"].append({"kind": kind, "row_id": record["row_id"], "snapshot_text": text,
            "snapshot_sha256": raw_sha(text), "event_ids": []})


def mutate(observation, table, **values):
    item = next(item for item in observation["rows"] if item["table"] == table)
    value = parse(item["row_text"])
    value.update(values)
    text = sql_canonical(value)
    item.update(row_text=text, row_sha256=raw_sha(text))
    refresh_lifecycle(observation)


def verify(base, observation, review):
    return labels.verify_label_observation(observation, base_manifest=base, review_companion=review)


def test_all_roots_include_excluded_and_zero_optional_inputs():
    base, observation, review = fixture()
    assert not any(item["table"] == "ml_example_inputs" for item in base["rows"])
    second = deepcopy(next(item for item in base["rows"] if item["table"] == "ml_examples"))
    second["row_id"] = second["data"]["id"] = uid(20)
    second["data"]["label_data"] = {"previously_excluded": True}
    second["row_sha256"] = digest(second["data"])
    base["rows"].append(second)
    base["rows"].sort(key=lambda item: (item["table"], item["row_id"]))
    inventory = labels.label_inventory(base)
    assert len(inventory["example_pins"]) == 2
    assert len(inventory["claim_pins"]) == 1
    observation.update(labels._inventory_lists(base, inventory))
    observation["rows"].append(wire("ml_examples", second["data"]))
    observation["rows"].sort(key=lambda item: (item["table"], item["row_id"]))
    assert verify(base, observation, review) == {"claim_holds": {uid(1): []}}


@pytest.mark.parametrize("with_paper,with_event", [(False, False), (True, False), (False, True), (True, True)])
def test_unchanged_currentness_is_not_positive_authority(with_paper, with_event):
    base, observation, review = fixture(paper=with_paper, event=with_event)
    assert verify(base, observation, review) == {"claim_holds": {uid(1): []}}


@pytest.mark.parametrize("field,value,code", [
    ("value_kelvin", 40, "label_scientific_content_changed"),
    ("pressure_gpa", 3, "label_scientific_content_changed"),
    ("raw_record", {"tc": 88}, "label_scientific_content_changed"),
    ("measurement_method", "invented DFPT", "label_scientific_content_changed"),
    ("validity_status", "retracted", "label_current_result_held"),
    ("validity_status", "pending", "label_scientific_content_changed"),
])
def test_changed_claim_is_held_not_substituted(field, value, code):
    base, observation, review = fixture()
    old = canonical(base)
    mutate(observation, "material_claims", **{field: value})
    assert code in verify(base, observation, review)["claim_holds"][uid(1)]
    assert canonical(base) == old


@pytest.mark.parametrize("value", [39, Decimal("39.0000")])
def test_same_sql_numeric_value_and_scale_are_not_changes(value):
    base, observation, review = fixture()
    mutate(observation, "material_claims", value_kelvin=value, updated_at="2026-09-09T10:00:00+00:00")
    assert verify(base, observation, review)["claim_holds"][uid(1)] == []


def test_timestamp_equivalence_and_operational_changes():
    base, observation, review = fixture(event=True)
    mutate(observation, "material_states", created_at="2026-09-01T08:00:00+08:00")
    mutate(observation, "materials", updated_at="2026-09-09T00:00:00Z", total_papers=8)
    assert verify(base, observation, review)["claim_holds"][uid(1)] == []


@pytest.mark.parametrize("field", ["needs_review", "disputed", "retracted"])
def test_global_material_holds_cannot_be_cleared_by_scoped_sources(field):
    base, observation, review = fixture(paper=True)
    mutate(observation, "materials", **{field: True})
    assert "label_current_material_held" in verify(base, observation, review)["claim_holds"][uid(1)]


@pytest.mark.parametrize("changes", [
    {"status": "pending"}, {"status": "needs_review"}, {"status": "under_review"}, {"status": "unknown"},
    {"status": "refuted"}, {"status": "provenance_quarantined"},
    {"review_reason": "  provenance_quarantine_nims"},
    {"records": [{"provenance_status": "quarantined"}]},
    {"records": [{"review_reason": "provenance_quarantine_source"}]},
    {"records": ["malformed"]},
])
def test_persistent_material_hold_without_boolean_flags(changes):
    base, observation, review = fixture()
    mutate(observation, "materials", **changes)
    assert "label_current_material_held" in verify(base, observation, review)["claim_holds"][uid(1)]


def test_family_holdout_taxonomy_change_requires_review():
    base, observation, review = fixture()
    mutate(observation, "materials", family="changed taxonomy")
    assert "label_scientific_content_changed" in verify(base, observation, review)["claim_holds"][uid(1)]


def test_new_positive_qc_is_not_authority_and_is_inventory_change():
    base, observation, review = fixture()
    observation["rows"].append(wire("claim_qc", row("claim_qc", uid(30), claim_id=uid(1), review_status="approved", is_gold=True)))
    observation["rows"].sort(key=lambda item: (item["table"], item["row_id"]))
    holds = verify(base, observation, review)["claim_holds"][uid(1)]
    assert "label_dependency_inventory_changed" in holds
    assert "label_review_state_changed" in holds


def test_event_decision_artifact_is_required_even_without_optional_inputs():
    base, observation, review = fixture(event=True)
    observation["rows"] = [item for item in observation["rows"] if item["table"] != "evidence_artifacts"]
    with pytest.raises(labels.MlLabelObservationError, match="missing_dependency|composite"):
        verify(base, observation, review)


def test_new_successor_is_negative_audit_only():
    base, observation, review = fixture(event=True)
    event = parse(next(item["row_text"] for item in observation["rows"] if item["table"] == "research_events"))
    event.update(id=uid(8), supersedes_id=uid(5), revision=2)
    observation["rows"].append(wire("research_events", event))
    observation["rows"].sort(key=lambda item: (item["table"], item["row_id"]))
    assert "label_event_superseded" in verify(base, observation, review)["claim_holds"][uid(1)]


def test_current_revision_superseding_historical_parent_is_not_held():
    base, observation, review = fixture(event=True)
    original = next(item for item in base["rows"] if item["table"] == "research_events")
    parent = deepcopy(original)
    parent["row_id"] = parent["data"]["id"] = uid(8)
    parent["row_sha256"] = digest(parent["data"])
    original["data"].update(supersedes_id=uid(8), revision=2)
    original["row_sha256"] = digest(original["data"])
    base["rows"].append(parent)
    base["rows"].sort(key=lambda item: (item["table"], item["row_id"]))
    mutate(observation, "research_events", supersedes_id=uid(8), revision=2)
    observation["rows"].append(wire("research_events", parent["data"]))
    observation["rows"].sort(key=lambda item: (item["table"], item["row_id"]))
    assert verify(base, observation, review)["claim_holds"][uid(1)] == []
    newer = deepcopy(original["data"])
    newer.update(id=uid(9), supersedes_id=uid(5), revision=3)
    observation["rows"].append(wire("research_events", newer))
    observation["rows"].sort(key=lambda item: (item["table"], item["row_id"]))
    assert "label_event_superseded" in verify(base, observation, review)["claim_holds"][uid(1)]


@pytest.mark.parametrize("status", ["retracted", "corrected", "withdrawn"])
def test_current_source_negative_without_history_is_held(status):
    base, observation, review = fixture(paper=True)
    mutate(observation, "papers", status=status)
    assert "label_current_source_held" in verify(base, observation, review)["claim_holds"][uid(1)]


def lifecycle_fixture():
    base, observation, review = fixture(paper=True)
    snapshot = observation["lifecycle"][0]
    event = {"id": uid(80), "paper_id": "synthetic:paper", "work_id": None, "revision": 1,
        "predecessor_id": None, "old_snapshot_sha256": "a" * 64, "snapshot_sha256": snapshot["snapshot_sha256"],
        "prior_status": "retracted", "observed_status": "published", "event_kind": "lifecycle_change",
        "record_sha256": "0" * 64, "created_at": "2026-09-01T00:00:00Z"}
    event["record_sha256"] = lifecycle_record_sha(event)
    observation["rows"].append(wire("source_lifecycle_events", event))
    observation["rows"].sort(key=lambda item: (item["table"], item["row_id"]))
    snapshot["event_ids"] = [event["id"]]
    return base, observation, review


def test_restored_published_status_does_not_erase_negative_history():
    base, observation, review = lifecycle_fixture()
    assert "label_current_source_held" in verify(base, observation, review)["claim_holds"][uid(1)]


@pytest.mark.parametrize("field,value", [
    ("old_snapshot_sha256", True), ("old_snapshot_sha256", "not-a-hash"),
    ("prior_status", False), ("observed_status", "x" * 21),
    ("created_at", False), ("created_at", "2026-09-01T00:00:00"),
])
def test_lifecycle_scalars_cannot_be_resealed_as_valid(field, value):
    base, observation, review = lifecycle_fixture()
    item = next(item for item in observation["rows"] if item["table"] == "source_lifecycle_events")
    event = parse(item["row_text"])
    event[field] = value
    event["record_sha256"] = lifecycle_record_sha(event)
    item.update(wire("source_lifecycle_events", event))
    with pytest.raises(labels.MlLabelObservationError):
        verify(base, observation, review)


def test_lifecycle_timestamp_equivalent_offset_remains_valid():
    base, observation, review = lifecycle_fixture()
    item = next(item for item in observation["rows"] if item["table"] == "source_lifecycle_events")
    event = parse(item["row_text"])
    event["created_at"] = "2026-09-01T08:00:00+08:00"
    item.update(wire("source_lifecycle_events", event))
    assert "label_current_source_held" in verify(base, observation, review)["claim_holds"][uid(1)]


@pytest.mark.parametrize("part", ["row", "lifecycle", "actor", "grant"])
def test_review_overlap_and_admission_must_be_same_snapshot(part):
    base, observation, review = fixture(paper=True)
    if part in {"actor", "grant"}:
        review["observation"]["capture_admission"]["actor_user_id" if part == "actor" else "actor_grant_id"] = uid(999)
    elif part == "row":
        review["observation"]["source_observation"]["rows"] = deepcopy(observation["rows"])
        mutate(observation, "papers", doi="10.1/changed")
    else:
        review["observation"]["source_observation"]["lifecycle"] = deepcopy(observation["lifecycle"])
        review["observation"]["source_observation"]["lifecycle"][0]["snapshot_sha256"] = "f" * 64
    with pytest.raises(labels.MlLabelObservationError, match="mismatch"):
        verify(base, observation, review)


@pytest.mark.parametrize("change", ["extra", "version", "missing_claim", "missing_example", "duplicate", "bad_row_hash", "bool_float", "surplus", "bad_admission"])
def test_malformed_or_incomplete_observation_rejected(change):
    base, observation, review = fixture()
    if change == "extra": observation["private"] = "must not echo"
    elif change == "version": observation["version"] = "future"
    elif change == "missing_claim": observation["claims"] = []
    elif change == "missing_example": observation["examples"] = []
    elif change == "duplicate": observation["rows"].append(deepcopy(observation["rows"][0]))
    elif change == "bad_row_hash": observation["rows"][0]["row_sha256"] = "f" * 64
    elif change == "bool_float": mutate(observation, "material_claims", value_kelvin=True)
    elif change == "bad_admission": observation["capture_admission"]["actor_grant_id"] = None
    elif change == "surplus":
        observation["rows"].append(wire("materials", row("materials", "unrelated", status="active")))
        observation["rows"].sort(key=lambda item: (item["table"], item["row_id"]))
    with pytest.raises(labels.MlLabelObservationError) as error:
        verify(base, observation, review)
    assert "must not echo" not in str(error.value)


@pytest.mark.parametrize("change", ["depth", "nodes", "bytes", "nan", "surrogate", "nul"])
def test_preallocation_resource_and_scalar_bounds(change):
    value = {}
    if change == "depth":
        for _ in range(labels.MAX_DEPTH + 2): value = [value]
    elif change == "nodes": value = [None] * (labels.MAX_NODES + 1)
    elif change == "bytes": value = "x" * (labels.MAX_BYTES + 1)
    elif change == "nan": value = float("nan")
    elif change == "surrogate": value = "\ud800"
    elif change == "nul": value = "\x00"
    with pytest.raises((ValueError, UnicodeError)):
        labels.bounded(value)


def test_shared_row_budget_is_cumulative_and_strict():
    budget = {"bytes": 0, "rows": labels.MAX_ROWS - 1}
    labels._row_budget(budget, 1)
    with pytest.raises(labels.MlLabelObservationError, match="row_limit"):
        labels._row_budget(budget, 1)
    for invalid in (True, -1, None):
        with pytest.raises(labels.MlLabelObservationError):
            labels._row_budget({"rows": invalid}, 0)


def test_decoded_sql_body_nodes_share_one_budget():
    # Each body is below the old per-row parser ceiling; their combined trees
    # exceed this new observation's budget even though the strings are small.
    first = wire("materials", row("materials", "first", records=[{}] * 105000))
    second = wire("materials", row("materials", "second", records=[{}] * 105000))
    assert len(first["row_text"]) + len(second["row_text"]) < labels.MAX_BYTES
    with pytest.raises(labels.MlLabelObservationError, match="node_limit"):
        labels._decode_rows([first, second])


def envelope_fixture(monkeypatch):
    """Wrapper unit only: independent old verifier is separately native-tested."""
    base, observation, review = fixture()
    source = {"base_release_id": uid(200)}
    review["base_release_id"] = source["base_release_id"]
    calls = []
    monkeypatch.setattr(companion, "verify_ml_review_companion", lambda *args, **kwargs: calls.append((args, kwargs)))
    args = {"base_manifest": base, "expected_base_manifest_sha256": digest(base), "source_companion": source,
        "expected_source_companion_sha256": digest(source), "review_companion": review,
        "expected_review_companion_sha256": digest(review)}
    value = companion.assemble_ml_label_companion(**args, observation=observation)
    return value, args, calls


def reseal(value):
    value["observation_sha256"] = digest(value["observation"])
    value["companion_sha256"] = digest({key: item for key, item in value.items() if key != "companion_sha256"})


def test_wrapper_calls_independent_review_verification_and_returns_detached_receipt(monkeypatch):
    value, args, calls = envelope_fixture(monkeypatch)
    receipt = companion.verify_ml_label_companion(value, **args, expected_label_companion_sha256=digest(value))
    assert len(calls) == 2
    assert calls[-1][0] == (args["review_companion"],)
    assert calls[-1][1] == {key: value for key, value in args.items() if key != "review_companion"}
    assert receipt["claim_holds"] == {uid(1): []}
    assert all(flag is False for flag in receipt["authority"].values())
    assert receipt["observation_semantics"] == "captured_not_live"
    receipt["authority"]["scientific_acceptance"] = True
    assert value["authority"]["scientific_acceptance"] is False


@pytest.mark.parametrize("key", list(companion.AUTHORITY))
@pytest.mark.parametrize("flag", [True, 0, None])
def test_resealed_authority_cannot_be_forged(monkeypatch, key, flag):
    value, args, _ = envelope_fixture(monkeypatch)
    value["authority"][key] = flag
    reseal(value)
    with pytest.raises(companion.MlLabelCompanionError, match="authority"):
        companion.verify_ml_label_companion(value, **args, expected_label_companion_sha256=digest(value))


@pytest.mark.parametrize("key", ["expected_base_manifest_sha256", "expected_source_companion_sha256", "expected_review_companion_sha256", "expected_label_companion_sha256"])
def test_every_independent_pin_is_required(monkeypatch, key):
    value, args, _ = envelope_fixture(monkeypatch)
    args["expected_label_companion_sha256"] = digest(value)
    args[key] = "f" * 64
    with pytest.raises(companion.MlLabelCompanionError):
        companion.verify_ml_label_companion(value, **args)
