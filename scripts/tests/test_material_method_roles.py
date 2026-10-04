"""Method roles and local Tc attribution, using synthetic grammar fixtures only."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))
from services import material_enrichment as enrich  # noqa: E402


def candidates(text):
    material = {"id": "mat:ysch10", "formula": "YScH10"}
    record = {"paper_id": "paper:synthetic", "tc_kelvin": 116}
    source = {"id": "source:synthetic", "paper_id": record["paper_id"], "text": text,
              "kind": "original_passage", "source_revision": "synthetic-method/v1",
              "source_status": "active", "content_sha256": enrich.text_digest(text),
              "locator": {"section": "Synthetic method regression"}}
    return enrich.extract_source_candidates(material, record, source)


@pytest.mark.parametrize("method,label", [("Eliashberg", "eliashberg"), ("Allen-Dynes", "allen_dynes")])
def test_explicit_tc_solver_has_separate_calculation_role_and_exact_source_span(method, label):
    text = f"Predicted YScH10 has Tc = 116 K obtained from the {method} equation."
    rows = candidates(text)
    tc = next(row for row in rows if row["field"] == "tc_kelvin")
    solver = next(row for row in rows if row["field"] == "calculation_method")
    assert not any(row["field"] == "measurement_method" for row in rows)
    assert tc["subject"]["measurement_method"] is None
    assert tc["subject"]["calculation_method"] == label
    assert solver["subject"]["field_role"] == "tc_calculation_method"
    span = solver["source"]["span"]
    assert text[span["char_start"]:span["char_end"]] == method
    handoff = enrich.pending_tc_records([tc])[0]
    assert handoff["record"]["measurement_method"] is None
    assert handoff["record"]["calculation_method"] == label
    assert handoff["record"]["knowledge_origin"] == "Computed"
    assert all(handoff[key] is False for key in enrich.AUTHORITY)
    for row in rows:
        enrich.validate_candidate_identity(row)


@pytest.mark.parametrize("text", [
    "YScH10 has Tc = 116 K, and DFT was used to optimize the structure.",
    "DFT predicts Tc = 116 K for YScH10.",
    "YScH10 has Tc = 116 K, and Eliashberg calculations describe the electron-phonon spectrum.",
    "YScH10 has Tc = 116 K, while the Eliashberg equation was used for another quantity.",
    "YScH10 has Tc = 116 K; Eliashberg equations were used in this study.",
    "YScH10 has Tc = 116 K not obtained from the Eliashberg equation.",
    "YScH10 has no Eliashberg equation used to predict Tc = 116 K.",
    "We did not use Eliashberg to predict Tc = 116 K for YScH10.",
    "No Eliashberg equation was used to calculate Tc = 116 K for YScH10.",
    "YScH10 has Tc = 116 K obtained from either Eliashberg or Allen-Dynes equations.",
    "YScH10 has Tc = 116 K, whereas MgB2 has Tc = 39 K obtained from Eliashberg equations.",
])
def test_generic_structure_epc_foreign_negated_and_ambiguous_methods_cannot_fill_tc_solver(text):
    rows = candidates(text)
    assert not any(row["field"] == "calculation_method" for row in rows)
    assert not any(row["field"] == "measurement_method" and row["value"] in {"dft", "eliashberg", "allen_dynes"} for row in rows)
    for tc in (row for row in rows if row["field"] == "tc_kelvin"):
        assert tc["subject"].get("calculation_method") is None


def test_xrd_is_a_source_measurement_hint_and_cannot_become_tc_measurement():
    rows = candidates("YScH10 has Tc = 116 K, and x-ray diffraction characterizes its crystal structure.")
    method = next(row for row in rows if row["field"] == "measurement_method")
    assert method["value"] == "x_ray_diffraction"
    assert method["subject"]["field_role"] == "source_measurement_method"
    tc = next(row for row in rows if row["field"] == "tc_kelvin")
    assert tc["subject"]["measurement_method"] is None
    assert enrich.pending_tc_records([tc])[0]["record"]["measurement_method"] is None


def test_experimental_resistivity_role_is_preserved_and_mixed_origin_is_unresolved():
    for suffix, origin in [("", "Observed"), (", and DFT describes its electronic structure", "Unknown")]:
        rows = candidates("YScH10 has measured Tc = 116 K from resistivity" + suffix + ".")
        tc = next(row for row in rows if row["field"] == "tc_kelvin")
        assert tc["subject"]["measurement_method"] == "resistivity"
        assert tc["subject"].get("calculation_method") is None
        assert tc["subject"]["knowledge_origin"] == origin


@pytest.mark.parametrize("text", [
    "Computed YScH10 has Tc = 116 K, and susceptibility measurements characterize normal-state magnetism.",
    "Resistivity of YScH10 was measured at 300 K, and Tc = 116 K was predicted.",
    "YScH10 has Tc = 116 K, whereas susceptibility was measured for MgB2.",
])
def test_measurement_inventory_for_another_property_or_subject_does_not_fill_tc_method(text):
    rows = candidates(text)
    for tc in (row for row in rows if row["field"] == "tc_kelvin"):
        assert tc["subject"]["measurement_method"] is None


@pytest.mark.parametrize("method,label", [("Resistivity", "resistivity"), ("Susceptibility", "susceptibility"), ("Specific heat", "specific_heat")])
def test_explicit_measurement_relation_before_tc_keeps_the_experimental_method(method, label):
    rows = candidates(f"{method} of YScH10 shows Tc = 116 K.")
    tc = next(row for row in rows if row["field"] == "tc_kelvin")
    assert tc["subject"]["measurement_method"] == label


@pytest.mark.parametrize("record,measurement,calculation", [
    ({"calculation_method": "Eliashberg"}, False, True),
    ({"measurement_method": "resistivity"}, True, False),
    ({"measurement_method": "Eliashberg"}, False, False),
    ({"method": "Eliashberg"}, False, True),
    ({"method": "four-probe resistivity"}, True, False),
    ({"method": "unspecified protocol"}, False, False),
])
def test_retained_coverage_does_not_fill_one_method_role_with_another(record, measurement, calculation):
    assert enrich._present(record, "measurement_method") is measurement
    assert enrich._present(record, "calculation_method") is calculation


def test_calculation_method_has_a_separate_recovery_route():
    assert enrich.FIELD_ROUTES["calculation_method"] == ["source_fulltext_and_supplement", "nomad_state_matched_calculation"]


def test_retained_value_search_hit_cannot_borrow_a_foreign_or_anaphoric_method():
    material = {"id": "mat:ysch10", "formula": "YScH10"}
    record = {"paper_id": "paper:synthetic", "tc_kelvin": 116}
    for text in ["The sample has Tc = 116 K obtained from the Eliashberg equation.",
                 "MgB2 has Tc = 116 K obtained from the Eliashberg equation.",
                 "The sample has Tc = 116 K, and XRD characterizes its structure."]:
        source = {"id": "source:synthetic", "paper_id": record["paper_id"], "text": text,
                  "kind": "original_passage", "source_revision": "synthetic-method/v1",
                  "source_status": "active", "content_sha256": enrich.text_digest(text),
                  "locator": {"section": "Synthetic unresolved subject"}}
        tc = enrich.extract_retained_quantity_matches(material, record, source)[0]
        assert tc["subject"]["identity_basis"] == "retained_quantity_source_scoped_search_hit"
        assert tc["subject"]["measurement_method"] is None
        assert tc["subject"].get("calculation_method") is None
        assert "material_identifier_not_local" in tc["reason_codes"]
        handoff = enrich.pending_tc_records([tc])[0]["record"]
        assert handoff["measurement_method"] is None
        assert handoff["calculation_method"] is None
