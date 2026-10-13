"""Source-reference transport and row quarantine preserve scientific gates."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from test_materials_v3 import fixture
from ingestion.materials_v3.contract import CandidateError, evidences, validate_candidate
from ingestion.materials_v3.wire import VERSION, validate_response, wire_schema


def compact_fixture():
    value, block = fixture()
    value["schema_version"] = VERSION
    row = value["results"][0]
    row["series_point"]["step_index_raw"] = None
    for node in (row["subject"], row["sample"], row["series_point"], row["event"]):
        role = node["evidence"][0]["role"]
        node["evidence"] = [{"ref": "R0", "role": role}]
    row["outcome_evidence"] = [{"ref": "R0", "role": "outcome"}]
    for item in row["conditions"] + row["properties"]:
        item["evidence"] = [{"ref": "R0", "role": "condition" if "key" in item else "value"}]
        q = item["quantity"]
        q["numbers"] = [q.pop("value")]
        q.pop("lower")
        q.pop("upper")
        if "qualifiers" in item:
            item["qualifiers"] = [{"key": k, "value": v} for k, v in item["qualifiers"].items()]
    return value, {**block, "block_role": "target"}


def test_wire_supplies_literal_source_quotes_and_keeps_all_tc_criteria():
    value, block = compact_fixture()
    original = deepcopy(value)
    Draft202012Validator(wire_schema()).validate(value)
    validated, errors = validate_response(value, [block])
    assert not errors and not validated["partial"] and value == original
    row = validated["candidate"]["results"][0]
    assert [p["quantity"]["value"] for p in row["properties"]] == [240, 232]
    assert [p["qualifiers"]["tc_definition"] for p in row["properties"]] == [
        "onset",
        "zero_resistance",
    ]
    assert all(e["quote"] == block["text"] for e in evidences(row))
    assert all(e["source_start"] == 0 for e in validated["bound_evidence"])
    assert validated["scientific_acceptance"] is False
    validate_candidate(validated["candidate"], [block], model_output=True)


def test_reference_does_not_allow_invented_method_or_numeric_value():
    for field in ("method", "number", "unit", "qualifier"):
        value, block = compact_fixture()
        row = value["results"][0]
        if field == "method":
            row["event"]["method_raw"] = "Imaginary spectroscopy"
        elif field == "number":
            row["properties"][0]["quantity"]["numbers"] = [777]
        elif field == "unit":
            row["properties"][0]["quantity"]["raw_unit"] = "mK"
        else:
            row["properties"][0]["qualifiers"].append({"key": "criterion_raw", "value": "invented"})
        validated, errors = validate_response(value, [block])
        assert errors and not validated["candidate"]["results"]
        assert validated["rejected_results"][0]["local_id"] == "r1"


def test_one_bad_record_no_longer_discards_another_fully_valid_record():
    value, block = compact_fixture()
    bad = deepcopy(value["results"][0])
    bad["local_id"] = "bad"
    bad["conditions"][0]["quantity"]["numbers"] = [999]
    value["results"].append(bad)
    validated, errors = validate_response(value, [block])
    assert errors and validated["partial"]
    assert [r["local_id"] for r in validated["candidate"]["results"]] == ["r1"]
    assert [r["local_id"] for r in validated["rejected_results"]] == ["bad"]
    # The bad pressure is never silently stripped into an "unknown pressure" row.
    assert validated["candidate"]["results"][0]["conditions"][0]["quantity"]["value"] == 150


@pytest.mark.parametrize("bad_ref", ["R999", "R0; approved=true"])
def test_unknown_source_ref_is_quarantined(bad_ref):
    value, block = compact_fixture()
    value["results"][0]["subject"]["evidence"][0]["ref"] = bad_ref
    validated, errors = validate_response(value, [block])
    assert errors and not validated["candidate"]["results"]
    assert any("unknown_source_reference" in error for error in errors)


def test_context_only_result_remains_rejected():
    value, block = compact_fixture()
    context = {**block, "block_role": "context"}
    target = {**block, "block_id": "b-empty", "block_role": "target", "text": "No claims here."}
    # R0 is the new target; R1 is the old claim-containing context.
    for e in value["results"][0]["subject"]["evidence"]:
        e["ref"] = "R1"

    def refs(node):
        if isinstance(node, dict):
            if "ref" in node:
                node["ref"] = "R1"
            for v in node.values():
                refs(v)
        elif isinstance(node, list):
            for v in node:
                refs(v)

    refs(value)
    validated, errors = validate_response(value, [target, context])
    assert any("result_is_context_only" in e for e in errors)
    assert not validated["candidate"]["results"]


def test_interval_requires_two_explicit_values_and_keeps_bounds():
    value, block = compact_fixture()
    block["text"] += " The Tc interval is 230–250 K."
    p = value["results"][0]["properties"][0]
    p["quantity"].update(raw_text="230–250 K", numbers=[230, 250], relation="interval")
    p["evidence"] = [{"ref": "R1", "role": "value"}]
    p["qualifiers"] = [{"key": "tc_definition", "value": "unknown"}]
    validated, errors = validate_response(value, [block])
    assert not errors
    q = validated["candidate"]["results"][0]["properties"][0]["quantity"]
    assert q["value"] is None and q["lower"] == 230 and q["upper"] == 250
    p["quantity"]["numbers"] = [230]
    validated, errors = validate_response(value, [block])
    assert any("number_count_mismatch" in e for e in errors)
    assert not validated["candidate"]["results"]


def test_partial_cross_record_relation_is_not_silently_dropped():
    value, block = compact_fixture()
    bad = deepcopy(value["results"][0])
    bad["local_id"] = "bad"
    bad["event"]["method_raw"] = "Invented"
    value["results"].append(bad)
    value["unresolved_links"] = [
        {
            "raw_text": "LaH10",
            "reason": "series_pairing_ambiguous",
            "candidate_local_ids": ["r1", "bad"],
            "evidence": [{"ref": "R0", "role": "relation"}],
        }
    ]
    with pytest.raises(CandidateError, match="cross_row_links_require_atomic"):
        validate_response(value, [block])


def test_duplicate_ids_and_authority_fields_are_rejected_before_row_isolation():
    value, block = compact_fixture()
    value["results"].append(deepcopy(value["results"][0]))
    with pytest.raises(CandidateError, match="duplicate"):
        validate_response(value, [block])
    value, block = compact_fixture()
    value["scientific_acceptance"] = True
    with pytest.raises(CandidateError, match="additionalProperties"):
        validate_response(value, [block])


def test_pipeline_keeps_partial_rows_but_never_marks_failed_block_complete(tmp_path):
    import json
    from test_materials_v3 import document
    from ingestion.materials_v3.ledger import Ledger
    from ingestion.materials_v3.pipeline import Budget, Pipeline
    from ingestion.materials_v3.providers import MODEL, REVISION, ProviderConfig, Response

    value, block = compact_fixture()
    bad = deepcopy(value["results"][0])
    bad["local_id"] = "bad"
    bad["conditions"][0]["quantity"]["numbers"] = [999]
    value["results"].append(bad)

    class Provider:
        config = ProviderConfig("local_mlx", MODEL, REVISION)
        calls = 0

        def generate(self, messages):
            self.calls += 1
            return Response(json.dumps(value))

    provider = Provider()
    ledger = Ledger(tmp_path / "ledger.sqlite")
    pipe = Pipeline(provider, ledger, budget=Budget(syntax_repairs=0))
    doc = document(tmp_path, block["text"])
    out = pipe.run(doc, paper_id="synthetic:p", work_id="synthetic:w")
    assert provider.calls == 1 and not out["coverage"]["machine_text_complete"]
    assert set(out["terminal"].values()) == {"validation_failed"}
    assert out["results"][0]["partial"]
    assert len(out["results"][0]["candidate"]["results"]) == 1
    assert len(out["results"][0]["rejected_results"]) == 1
    assert len(out["results"][0]["occurrences"]) == 1
    assert out["input_frames"]
    receipt = out["attempts"][0]["receipt"]
    assert receipt["model_contract_version"] == VERSION
    assert len(receipt["prompt_sha256"]) == len(receipt["input_frame_sha256"]) == 64
    assert pipe.run(doc, paper_id="synthetic:p", work_id="synthetic:w") == out
    assert provider.calls == 1
    ledger.close()


def test_no_false_ambient_criterion_or_uncertainty_is_silently_fixed():
    for field in ("ambient", "criterion", "uncertainty"):
        value, block = compact_fixture()
        row = value["results"][0]
        if field == "ambient":
            row["conditions"][0].update(
                status="explicit_ambient",
                quantity=None,
                qualitative={"raw_text": "loading", "value_raw": "loading"},
            )
        elif field == "criterion":
            block["text"] = block["text"].replace("onset ", "")
        else:
            row["properties"][0]["quantity"]["uncertainty_raw"] = "±7"
        result, errors = validate_response(value, [block])
        assert errors and not result["candidate"]["results"]


def test_nonfinite_json_overflow_and_unicode_minus():
    from ingestion.materials_v3.contract import parse_json, source_numbers

    with pytest.raises(CandidateError, match="nonfinite_json"):
        parse_json('{"value":1e999}')
    assert source_numbers("−0.02") == [-0.02]


def test_mention_cues_do_not_call_arpes_temperature_a_tc():
    from ingestion.materials_v3.mentions import tc_mentions

    text = "Tc(11B)=37.5 K and Tc(10B)=38.5 K. ARPES T=15 K."
    cues = tc_mentions([{"block_id": "b", "block_role": "target", "text": text}])
    assert [r["raw_mention"] for r in cues] == ["Tc(11B)=37.5 K", "Tc(10B)=38.5 K"]
    assert all(r["status"] == "lexical_source_cue_not_gold" for r in cues)


def test_unused_representation_slots_are_program_supplied_nulls():
    value, block = compact_fixture()
    for item in value["results"][0]["conditions"] + value["results"][0]["properties"]:
        item.pop("qualitative")
    result, errors = validate_response(value, [block])
    assert not errors and not result["partial"]
    row = result["candidate"]["results"][0]
    assert all(i["qualitative"] is None for i in row["conditions"] + row["properties"])
    # A historical wire response is replayed without pretending its protocol changed.
    value["schema_version"] = "materials-ner-wire/1.0"
    replay, errors = validate_response(value, [block])
    assert not errors and replay["transport"]["schema_version"] == "materials-ner-wire/1.0"


@pytest.mark.parametrize("mode", ["missing_both", "supplied_both"])
def test_optional_slots_do_not_allow_reported_items_without_one_representation(mode):
    value, block = compact_fixture()
    item = value["results"][0]["properties"][0]
    if mode == "missing_both":
        item.pop("quantity")
        item.pop("qualitative")
    else:
        item["qualitative"] = {"raw_text": "onset", "value_raw": "onset"}
    result, errors = validate_response(value, [block])
    assert errors and not result["candidate"]["results"]
    assert any("reported_value_" in e for e in errors)


def test_repair_feedback_lists_allowed_roles_and_the_actual_unexpected_field():
    value, block = compact_fixture()
    value["results"][0]["event"]["evidence"][0]["role"] = "event"
    value["results"][0]["unresolved_links"] = []
    result, errors = validate_response(value, [block])
    assert not result["candidate"]["results"]
    assert any("event/evidence/0/role:enum:allowed=subject,value" in e for e in errors)
    assert any("additionalProperties:unexpected=unresolved_links" in e for e in errors)


def test_tc_feedback_lists_the_controlled_criteria_without_relabeling_bad_output():
    value, block = compact_fixture()
    value["results"][0]["properties"][0]["qualifiers"][0]["value"] = "transition_temperature"
    result, errors = validate_response(value, [block])
    assert not result["candidate"]["results"]
    assert any("tc_definition:enum:allowed=onset,zero_resistance" in e for e in errors)
    assert any("unknown" in e for e in errors)


def test_tc_cannot_fill_a_measurement_temperature_setting_without_separate_proof():
    value, block = compact_fixture()
    row = value["results"][0]
    condition = deepcopy(row["conditions"][0])
    condition.update(key="measurement_temperature")
    condition["quantity"].update(raw_text="240 K", raw_unit="K", numbers=[240])
    row["conditions"].append(condition)
    result, errors = validate_response(value, [block])
    assert any("tc_value_is_not_a_reported_measurement_setting" in e for e in errors)
    assert not result["candidate"]["results"]
    # An independently stated setting at the same temperature remains allowable.
    block["text"] += " Measurements were taken at 240 K."
    condition["evidence"] = [{"ref": "R1", "role": "condition"}]
    result, errors = validate_response(value, [block])
    assert not errors and len(result["candidate"]["results"]) == 1
