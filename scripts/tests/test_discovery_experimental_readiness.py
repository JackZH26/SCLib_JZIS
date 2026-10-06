"""Real frozen-source replay plus counterexamples to accidental scientific admission."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import discovery_experimental_readiness as readiness  # noqa: E402


@pytest.fixture(scope="module")
def actual_sources():
    return readiness.load_sources(ROOT)


@pytest.fixture(scope="module")
def actual_summary(actual_sources):
    return readiness.build_summary(actual_sources)


def test_exact_frozen_source_inventory_and_criterion_counts(actual_summary):
    assert actual_summary["source_inventory"] == {
        "oxide_metallic": {"rows": 33458, "distinct_nonempty_reference_codes": 7254},
        "organic": {"rows": 568, "distinct_nonempty_reference_codes": 335},
    }
    # Nonempty expressions / positive lexical values / positive with explicit K /
    # positive K with a recognized source method code. These are not label counts.
    expected = {
        "oxide_metallic:tc": (26358, 26268, 19925, 333),
        "oxide_metallic:t1": (4051, 4034, 2316, 30),
        "oxide_metallic:t2": (17117, 17077, 13122, 112),
        "oxide_metallic:t3": (4606, 4587, 3175, 54),
        "oxide_metallic:tcsus": (5624, 5599, 4542, 63),
        "oxide_metallic:tcn": (4641, 4158, 3439, 6),
        "organic:tc": (517, 516, 0, 0),
        "organic:tcmax": (83, 83, 0, 0),
        "organic:tcn": (23, 16, 0, 0),
    }
    assert set(actual_summary["channels"]) == set(expected)
    fields = ("expressions", "positive_numeric_lexemes", "positive_with_explicit_kelvin",
              "positive_kelvin_and_recognized_method_code")
    for name, counts in expected.items():
        channel = actual_summary["channels"][name]
        assert tuple(channel[key] for key in fields) == counts
        assert channel["not_reported_rows"] + channel["expressions"] == channel["source_rows"]
        assert channel["reason_counts"]["source_use_permission_decision_not_supplied"] == counts[0]
        assert channel["reason_counts"]["primary_experimental_origin_not_adjudicated"] == counts[0]
    assert actual_summary["training_eligible_label_count"] is None
    assert actual_summary["independent_experiment_count"] is None
    assert actual_summary["model_score"] is None
    assert actual_summary["resource_budget"] is None
    assert not any(actual_summary["authority"].values())


def test_every_real_reading_retains_source_identity_without_promotion(actual_sources):
    seen, row_channels = set(), {}
    total = 0
    for reading in readiness.iter_readings(actual_sources):
        key = (reading["source_table"], reading["row_id"], reading["source_field"])
        assert key not in seen
        seen.add(key)
        row_channels.setdefault(key[:2], set()).add(key[2])
        assert readiness.HEX.fullmatch(reading["row_sha256"])
        assert 3 <= reading["line_start"] <= reading["line_end"]
        assert reading["knowledge_origin"] == "source_reference_not_adjudicated"
        assert reading["label_value_kelvin"] is None
        assert reading["training_eligible"] is False
        assert reading["family"] is None
        assert reading["independent_experiment_id"] is None
        assert reading["pressure_context"]["explicit_ambient"] is False
        if reading["source_field"] == "tcn":
            assert reading["expression_role"] == "measurement_lower_temperature_not_tc"
            assert "nontransition_temperature_limit_not_tc_or_zero_label" in reading["reason_codes"]
        total += 1
    assert total == 63020
    # The expressions are disjoint by field, but source-row cohorts demonstrably overlap.
    assert any({"tc", "t1", "t2", "t3"} <= fields for fields in row_channels.values())
    assert len(row_channels) < total


@pytest.mark.parametrize("field,criterion", [
    ("tc", "recommended_tc_criterion_unspecified"),
    ("t1", "zero_resistance"), ("t2", "resistive_midpoint"),
    ("t3", "resistive_r100"), ("tcsus", "susceptibility_criterion_unspecified"),
])
def test_source_channels_do_not_borrow_other_tc_criteria(field, criterion):
    row = {field: "12", "utc": "K", "tcmeth": "3", "pmax": "8"}
    result = readiness.expression_readiness("oxide_metallic", field, row)
    assert result["criterion"] == criterion
    assert result["pressure_context"]["raw_value"] is None
    assert "maximum_applied_pressure_is_not_tc_pressure" in result["reason_codes"]
    assert "pressure_not_bound_unknown_not_ambient" in result["reason_codes"]
    assert not result["training_eligible"]


@pytest.mark.parametrize("raw", ["0", "-1", "<2", "2(1)", "1–2", "NaN", "Infinity", "1e9999", "1e999999999"])
def test_nonpositive_bound_uncertainty_or_nonfinite_is_not_a_point_label(raw):
    result = readiness.expression_readiness("oxide_metallic", "tc", {"tc": raw, "utc": "K"})
    assert result["numeric_status"] != "positive_numeric_lexeme"
    assert result["label_value_kelvin"] is None
    assert not result["training_eligible"]


@pytest.mark.parametrize("raw", ["0", "0.3", "<2"])
def test_nontransition_lower_temperature_cannot_become_zero_or_tc(raw):
    result = readiness.expression_readiness("oxide_metallic", "tcn", {"tcn": raw, "utc": "K"})
    assert result["raw_value"] == raw
    assert result["expression_role"] == "measurement_lower_temperature_not_tc"
    assert result["label_value_kelvin"] is None
    assert "nontransition_temperature_limit_not_tc_or_zero_label" in result["reason_codes"]


@pytest.mark.parametrize("pressure", ["", "0", "1.2", "<1"])
def test_organic_tc_never_invents_kelvin_or_ambient(pressure):
    result = readiness.expression_readiness("organic", "tc", {"tc": "9.5", "pcrit": pressure, "tcmeth": "2"})
    assert result["raw_unit"] is None
    assert result["pressure_context"]["explicit_ambient"] is False
    assert "temperature_unit_not_supplied" in result["reason_codes"]
    assert result["pressure_context"]["source_field"] == "pcrit"
    if pressure:
        assert result["pressure_context"]["raw_unit"] == "GPa"
        assert "pressure_source_state_association_unreviewed" in result["reason_codes"]
    else:
        assert "pressure_not_bound_unknown_not_ambient" in result["reason_codes"]


def test_organic_tcmax_has_own_pressure_context_without_unit_borrowing():
    result = readiness.expression_readiness("organic", "tcmax", {"tcmax": "12", "pcrit": "1", "pmax": "3"})
    assert result["pressure_context"]["source_field"] == "pmax"
    assert result["pressure_context"]["raw_value"] == "3"
    assert result["pressure_context"]["raw_unit"] is None
    assert "pressure_unit_not_supplied" in result["reason_codes"]


def test_unrecognized_codes_and_unit_case_remain_pending():
    result = readiness.expression_readiness("oxide_metallic", "tc", {"tc": "10", "utc": "k", "tcmeth": "M"})
    assert result["method_status"] == result["unit_status"] == "requires_review"
    assert "measurement_method_code_requires_review" in result["reason_codes"]
    assert "temperature_unit_requires_review" in result["reason_codes"]


def test_replay_rejects_changed_frozen_source_before_use(tmp_path):
    relative, _, _ = readiness.PINS["organic"]
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    source = (ROOT / relative).read_bytes()
    target.write_bytes(source.replace(b'9.5', b'9.6', 1))
    with pytest.raises(readiness.ReadinessError, match="frozen_input_pin_mismatch"):
        readiness.read_pinned(tmp_path, "organic")


@pytest.mark.parametrize("raw", [b'{"rows": [], "rows": []}', b'{"value": NaN}', b'\xff'])
def test_ambiguous_json_is_rejected(raw):
    with pytest.raises(readiness.ReadinessError):
        readiness.decode(raw)


def test_new_output_is_private_and_cannot_replace_a_frozen_file(tmp_path):
    output = tmp_path / "report.json"
    readiness.write_new(output, b"{}\n")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        readiness.write_new(output, b"changed")
    assert output.read_bytes() == b"{}\n"


def test_public_aggregate_matches_exact_replay(actual_summary):
    raw = (ROOT / readiness.OUTPUT).read_bytes()
    assert raw == readiness.serialize(actual_summary)
    assert json.loads(raw)["adapter_sha256"] == hashlib.sha256(Path(readiness.__file__).read_bytes()).hexdigest()
    assert len(raw) < 20000
