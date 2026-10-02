"""Bounded synthetic original literals, not material or science approval."""

import base64
from copy import deepcopy
from hashlib import sha256

import pytest

from services import material_literal_field_contract as profile
from services import source_expression_contract_v2 as frozen
from services import source_expression_contract_v2_1 as contract
from services.research_release_manifest import canonical, digest


def span(source, token, start=0):
    index = source.index(token, start)
    return {"start": index, "end": index + len(token), "sha256": sha256(token.encode()).hexdigest()}


LITERALS = {
    "hc1_source_value": (r"H_{c1}", r"≈ 12.0 ± 0.5", r"\mathrm{mT}", "± 0.5"),
    "gap_energy_source_value": ("gap energy", "4.2(3)", "meV", "(3)"),
    "gap_ratio_source_value": ("gap ratio", "> 3.53", None, None),
    "electronic_specific_heat_coefficient_source_value": (
        r"\gamma", "7.4", r"\mathrm{mJ\,mol^{-1}K^{-2}}", None
    ),
    "debye_temperature_source_value": ("Debye temperature", "~ 270", "K", None),
    "isotope_effect_exponent": ("isotope exponent", "0.35 ± 0.04", None, "± 0.04"),
    "dtc_dp_source_value": ("dTc/dP", "−1.2", "K/GPa", None),
    "maximum_applied_pressure_source_value": ("maximum pressure", "50.8", "GPa", None),
    "meissner_fraction_percent": ("Meissner fraction", "≥ 85", "%", None),
    "transition_width_source_value": ("transition width", "< 1.5", "K", None),
    "minimum_temperature_k": ("minimum measurement temperature", "0.050", "K", None),
    "t_cdw_k": ("CDW temperature", "≈ 120", "K", None),
    "t_afm_k": ("AFM temperature", "24 ± 2", "K", "± 2"),
    "t_sdw_k": ("SDW temperature", "139", "K", None),
}


def synthetic_literal_package(field="gap_energy_source_value"):
    cue, amount, unit, uncertainty = LITERALS[field]
    source = f"Synthetic NbN has {cue} = {amount}" + (f" {unit}" if unit else "") + "."
    entry = {
        "field_id": field,
        "profile": contract.PROFILE,
        "field_role": contract.FIELDS[field],
        "subject": {"formula_spans": [span(source, "NbN")], "sample_label_spans": []},
        "window": {"id": "synthetic-literal-window", "label_spans": [span(source, source)]},
        "source_role": "source_reported",
        "knowledge_origin": "unknown",
        "origin_basis": {"statement": None, "spans": []},
        "model_spans": [],
        "value_spans": [span(source, amount)],
        "unit_spans": [span(source, unit)] if unit else [],
        "cue_spans": [span(source, cue)],
        "uncertainty_spans": [span(source, uncertainty)] if uncertainty else [],
        "qualifiers": [],
        "conditions": [],
        "locator": {key: None for key in contract.LOCATOR_KEYS},
        "predecessor": None,
    }
    return {
        "version": contract.VERSION,
        "profile": contract.PROFILE,
        "source": {
            "source_id": "synthetic:literal-fields",
            "url": "https://example.com/synthetic-literal-fields",
            "kind": "primary_paper",
            "content_kind": "plain_text",
            "revision": None,
            "revision_status": "unresolved",
            "original_parent_sha256": None,
            "parent_hash_status": "unresolved",
            "rights_status": "unresolved",
            "currentness": "unresolved",
            "captured_at": "2026-10-02T00:00:00+00:00",
        },
        "source_text_base64": base64.b64encode(source.encode()).decode(),
        "source_content_sha256": sha256(source.encode()).hexdigest(),
        "expressions": [entry],
    }


def synthetic_all_literal_fields_package():
    """One synthetic capture with fourteen distinct original local windows."""
    package = synthetic_literal_package()
    text_parts, entries, offset = [], [], 0
    for field in LITERALS:
        single = synthetic_literal_package(field)
        original = base64.b64decode(single["source_text_base64"]).decode()
        entry = single["expressions"][0]
        entry["window"]["id"] = "synthetic-literal-window-" + field
        selections = [
            entry["subject"]["formula_spans"], entry["window"]["label_spans"],
            entry["value_spans"], entry["unit_spans"], entry["cue_spans"],
            entry["uncertainty_spans"],
        ]
        for group in selections:
            for selection in group:
                selection["start"] += offset
                selection["end"] += offset
        text_parts.append(original)
        entries.append(entry)
        offset += len(original) + 1
    source = "\n".join(text_parts)
    package.update(
        source_text_base64=base64.b64encode(source.encode()).decode(),
        source_content_sha256=sha256(source.encode()).hexdigest(),
        expressions=entries,
    )
    return package


@pytest.mark.parametrize("field", tuple(LITERALS))
def test_all_fourteen_original_literals_keep_roles_text_hashes_and_no_quantity(field):
    package = synthetic_literal_package(field)
    prepared = contract.compile_package(package)
    projection = prepared.projections[0]
    value = projection["value"]
    cue, amount, unit, uncertainty = LITERALS[field]
    assert projection["field_id"] == field
    assert projection["profile"] == profile.VERSION
    assert projection["field_role"] == value["role"] == profile.FIELDS[field]
    assert value["raw_amount"] == amount
    assert value["raw_unit"] == unit
    assert value["raw_uncertainty"] == uncertainty
    assert value["raw_value"] == amount + (f" {unit}" if unit else "")
    assert value["field_cue"] == cue
    assert value["status"] == "raw_literal"
    assert value["normalization"] == "none" and value["quantity"] is None
    for name in ("value_span", "unit_span", "cue_span", "uncertainty_span"):
        selection = value[name]
        if selection is not None:
            original = prepared.source_text[selection["char_start"]:selection["char_end"]]
            assert sha256(original.encode()).hexdigest() == selection["text_sha256"]
    assert projection["conditions"] == []
    assert projection["selected_result_association"] == "unestablished"
    assert projection["canonical_promotions"] == 0
    for key in ("scientific_acceptance", "sample_identity_established", "phase_identity_established",
                "field_interpretation_reviewed", "public_content_release", "ml_training_approved"):
        assert projection[key] is False
    assert set(prepared.package) == contract.PACKAGE_KEYS - {"source_text_base64"}
    assert prepared.package_sha256 == digest(prepared.package)


def test_one_capture_keeps_all_fourteen_distinct_local_windows():
    package = synthetic_all_literal_fields_package()
    prepared = contract.compile_package(package)
    assert len(prepared.projections) == 14
    assert {p["field_id"] for p in prepared.projections} == set(profile.FIELDS)
    assert len({p["expression_key"] for p in prepared.projections}) == 14
    for projection, entry in zip(prepared.projections, package["expressions"], strict=True):
        selection = entry["window"]["label_spans"][0]
        assert projection["window"]["raw_label"] == prepared.source_text[selection["start"]:selection["end"]]
    package["expressions"][-1]["profile"] = "material-literal-field/2.0.0"
    with pytest.raises(contract.SourceExpressionContractError, match="profile_role"):
        contract.compile_package(package)


def test_registry_is_separate_from_frozen_numeric_registry():
    assert len(contract.FIELDS) == 14
    assert not set(contract.FIELDS) & set(frozen.FIELDS)
    assert contract.REGISTRY_SHA256 == digest({
        "version": profile.VERSION, "fields": profile.FIELDS, "roles": list(profile.FIELD_ROLES)
    })
    assert contract.SourceExpressionContractError is frozen.SourceExpressionContractError
    with pytest.raises(frozen.SourceExpressionContractError):
        frozen.compile_package(synthetic_literal_package())


def test_declared_origin_model_and_qualifiers_do_not_change_literal_roles_or_authority():
    package = synthetic_literal_package()
    entry = package["expressions"][0]
    source = base64.b64decode(package["source_text_base64"]).decode()
    entry.update(source_role="source_fitted", knowledge_origin="Computed",
                 model_spans=[span(source, "Synthetic")], qualifiers=list(contract.QUALIFIERS))
    entry["origin_basis"] = {"statement": "Synthetic declared fit", "spans": [span(source, "Synthetic")]}
    projection = contract.compile_package(package).projections[0]
    assert projection["knowledge_origin"] == "Computed"
    assert projection["source_role"] == "source_fitted"
    assert projection["model"] == "Synthetic"
    assert projection["origin_basis"]["verification"] == "declared_inspection_basis"
    assert projection["value"]["qualifiers"] == list(contract.QUALIFIERS)
    assert projection["field_role"] == "reported_property"
    assert projection["field_interpretation_reviewed"] is False


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(profile="material-literal-field/9.0.0"),
    lambda p: p.update(version=frozen.VERSION),
    lambda p: p.update(scientific_acceptance=True),
    lambda p: p.update(source_content_sha256="a" * 64),
    lambda p: p["expressions"][0].update(profile="other/1.0.0"),
    lambda p: p["expressions"][0].update(field_id="hc2_tesla"),
    lambda p: p["expressions"][0].update(field_role="study_extent"),
    lambda p: p["expressions"][0].update(conditions=[{"field_id": "pressure_gpa"}]),
    lambda p: p["expressions"][0].update(qualifiers=["reviewed"]),
    lambda p: p["expressions"][0].update(qualifiers=[contract.QUALIFIERS[0]] * 2),
    lambda p: p["expressions"][0].update(uncertainty_spans=p["expressions"][0]["cue_spans"]),
    lambda p: p["expressions"][0].update(cue_spans=p["expressions"][0]["unit_spans"]),
    lambda p: p["expressions"][0].update(unit_spans=p["expressions"][0]["cue_spans"]),
    lambda p: p["expressions"][0]["window"].update(label_spans=[]),
    lambda p: p["expressions"][0]["window"].update(label_spans=p["expressions"][0]["value_spans"]),
    lambda p: p["expressions"][0]["value_spans"][0].update(sha256="b" * 64),
    lambda p: p["expressions"][0]["value_spans"][0].update(start=True),
    lambda p: p["expressions"][0].update(value_spans=p["expressions"][0]["value_spans"] * 2),
    lambda p: p["expressions"][0]["subject"].update(formula_spans=p["expressions"][0]["subject"]["formula_spans"] * 2),
])
def test_mixed_profile_tamper_role_window_and_span_rejected(mutate):
    package = synthetic_literal_package()
    mutate(package)
    with pytest.raises(contract.SourceExpressionContractError):
        contract.compile_package(package)


def test_profile_roles_cannot_be_relabelled_as_tc_result_conditions():
    for field in ("maximum_applied_pressure_source_value", "minimum_temperature_k",
                  "t_cdw_k", "t_afm_k", "t_sdw_k"):
        package = synthetic_literal_package(field)
        package["expressions"][0]["field_role"] = "reported_result_condition"
        with pytest.raises(contract.SourceExpressionContractError, match="profile_role"):
            contract.compile_package(package)


def test_qualifier_and_value_changes_do_not_claim_new_expression_identity():
    package = synthetic_literal_package()
    entry = package["expressions"][0]
    first = contract.compile_package(package).projections[0]
    entry["qualifiers"] = [contract.QUALIFIERS[0]]
    second = contract.compile_package(package).projections[0]
    assert first["expression_key"] == second["expression_key"]
    assert digest(first) != digest(second)
    package["expressions"].append(deepcopy(entry))
    with pytest.raises(contract.SourceExpressionContractError, match="distinct_expression"):
        contract.compile_package(package)


@pytest.mark.parametrize("field", ("maximum_applied_pressure_source_value", "minimum_temperature_k"))
def test_scope_fields_are_raw_independent_properties_without_conditions(field):
    projection = contract.compile_package(synthetic_literal_package(field)).projections[0]
    assert projection["conditions"] == []
    assert projection["field_role"] == profile.FIELDS[field]
    assert projection["value"]["quantity"] is None


def _retained_source(package, source):
    package["source_text_base64"] = base64.b64encode(source.encode()).decode()
    package["source_content_sha256"] = sha256(source.encode()).hexdigest()


@pytest.mark.parametrize("gap", (128, 129))
def test_cue_to_amount_gap_is_finite(gap):
    package = synthetic_literal_package()
    entry = package["expressions"][0]
    source = "NbN gap energy" + " " * gap + "4.2(3) meV."
    _retained_source(package, source)
    entry["subject"]["formula_spans"] = [span(source, "NbN")]
    entry["window"]["label_spans"] = [span(source, source)]
    entry["cue_spans"] = [span(source, "gap energy")]
    entry["value_spans"] = [span(source, "4.2(3)")]
    entry["unit_spans"] = [span(source, "meV")]
    entry["uncertainty_spans"] = [span(source, "(3)")]
    if gap == 128:
        assert contract.compile_package(package).projections[0]["value"]["raw_value"] == "4.2(3) meV"
    else:
        with pytest.raises(contract.SourceExpressionContractError, match="cue_before"):
            contract.compile_package(package)


@pytest.mark.parametrize("gap", (128, 129))
def test_amount_to_unit_gap_is_finite_and_retains_printed_spacing(gap):
    package = synthetic_literal_package()
    entry = package["expressions"][0]
    source = "NbN gap energy 4.2(3)" + " " * gap + "meV."
    _retained_source(package, source)
    entry["subject"]["formula_spans"] = [span(source, "NbN")]
    entry["window"]["label_spans"] = [span(source, source)]
    entry["cue_spans"] = [span(source, "gap energy")]
    entry["value_spans"] = [span(source, "4.2(3)")]
    entry["unit_spans"] = [span(source, "meV")]
    entry["uncertainty_spans"] = [span(source, "(3)")]
    if gap == 128:
        assert contract.compile_package(package).projections[0]["value"]["raw_value"] == "4.2(3)" + " " * gap + "meV"
    else:
        with pytest.raises(contract.SourceExpressionContractError, match="unit_after"):
            contract.compile_package(package)


@pytest.mark.parametrize("length", (4096, 4097))
def test_local_window_limit_is_characters_and_never_assembled(length):
    package = synthetic_literal_package()
    source = base64.b64decode(package["source_text_base64"]).decode()
    source += "界" * (length - len(source))
    _retained_source(package, source)
    package["expressions"][0]["window"]["label_spans"] = [span(source, source)]
    if length == 4096:
        assert len(contract.compile_package(package).projections[0]["window"]["raw_label"]) == 4096
    else:
        with pytest.raises(contract.SourceExpressionContractError, match="character_span"):
            contract.compile_package(package)
    package["expressions"][0]["window"]["label_spans"] = [span(source, source[:2000]), span(source, source[2000:], 2000)]
    with pytest.raises(contract.SourceExpressionContractError, match="contiguous_literal"):
        contract.compile_package(package)


@pytest.mark.parametrize("name", ("MAX_PACKAGE_BYTES", "MAX_PROJECTION_BYTES"))
def test_canonical_byte_limits_are_enforced_before_sql(monkeypatch, name):
    package = synthetic_literal_package()
    prepared = contract.compile_package(package)
    payload = prepared.package if name == "MAX_PACKAGE_BYTES" else prepared.projections[0]
    size = len(canonical(payload))
    monkeypatch.setattr(contract, name, size)
    contract.compile_package(package)
    monkeypatch.setattr(contract, name, size - 1)
    with pytest.raises(contract.SourceExpressionContractError, match="bounded_.*bytes"):
        contract.compile_package(package)


def test_frozen_numeric_20_contract_retains_its_original_parsed_behavior():
    from tests.test_source_expression_contract_v2 import synthetic_package

    package = synthetic_package()
    projection = frozen.compile_package(package).projections[0]
    assert package["version"] == "source-expression-package/2.0.0"
    assert projection["value"]["value"] == 94.5
    assert projection["value"]["unit"] == "K"
    assert projection["conditions"][0]["value"]["value"] == 200
    assert "profile" not in projection and "field_role" not in projection
    with pytest.raises(contract.SourceExpressionContractError):
        contract.compile_package(package)
