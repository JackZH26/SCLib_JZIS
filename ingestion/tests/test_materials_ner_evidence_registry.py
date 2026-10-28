"""Source binding and dimensional regressions; these are not scientific Gold."""
from copy import deepcopy
import json
from math import pi
from pathlib import Path
import runpy

import jsonschema
import pytest

from ingestion.materials_ner.contract import Evidence, Extraction, Quantity, Result, digest
from ingestion.materials_ner.evidence import selected_quotes, source_catalog, source_spans
from ingestion.materials_ner.quantities import UNITS, normalize, quantity_source_issues
from ingestion.materials_ner.sources import make_blocks, save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction
from ingestion.materials_ner.wire import CompactExtraction, output_schema
from ingestion.materials_ner.worker import configuration, run_one
from test_materials_ner_pipeline import FakeProvider, compact_fixture, example, quantity


def errors(kind, value, unit, raw, **kwargs):
    q = Quantity.model_validate(quantity(value, unit, raw, **kwargs))
    return quantity_source_issues(kind, q, [Evidence(
        block_id="synthetic", quote="SYNTHETIC fixture: " + raw, field="/q")], "/q")


@pytest.mark.parametrize("text", ["SYNTHETIC " * 900, "A & 1 \\\\\n" * 300,
                                  "x" * 1900, "same\nsame\n", ""])
def test_span_partition_has_exact_byte_equivalent_coverage(text):
    offsets = list(source_spans(text))
    assert "".join(text[a:b] for a, b in offsets) == text
    assert all(0 <= a < b <= len(text) for a, b in offsets)


def test_catalog_is_bound_to_source_and_never_joins_over_an_unselected_gap():
    bundle, _ = example()
    bundle.blocks = make_blocks(bundle.documents[0].id, [("synthetic", "word " * 700)])
    catalog = source_catalog(bundle)
    assert catalog["bundle_sha256"] == digest(bundle.model_dump())
    assert len(selected_quotes(catalog, ["S1", "S2"])) == 1
    assert len(selected_quotes(catalog, ["S1", "S3"])) == 2
    with pytest.raises(ValueError, match="duplicate_source_span"):
        selected_quotes(catalog, ["S1", "S1"])
    broken = bundle.model_copy(deep=True)
    broken.blocks[0].text = "tampered"
    with pytest.raises(ValueError, match="integrity"):
        source_catalog(broken)


@pytest.mark.parametrize("mutation", ["span", "alias", "work", "quote"])
def test_effective_provider_schema_refuses_fabricated_source_references(mutation):
    bundle, raw = example()
    compact = compact_fixture(raw)
    if mutation == "span":
        compact["observations"][0]["result"]["evidence"][0]["span_ids"] = ["S999"]
    elif mutation == "alias":
        compact["processed_block_ids"] = ["B999"]
    elif mutation == "work":
        compact["work_id"] = "synthetic:wrong"
    else:
        compact["observations"][0]["result"]["evidence"][0]["quote"] = "invented text"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(compact, output_schema(bundle))


def test_span_binding_does_not_waive_numeric_or_null_field_validation():
    bundle, raw = example()
    compact = compact_fixture(raw)
    result = compact["observations"][0]["result"]
    result["quantity"]["value"] = 999.0
    compact["observations"][0]["protocol"]["evidence"][0]["fields"].append("/details_raw")
    report = validate_extraction(CompactExtraction.model_validate(compact).expand(bundle), bundle)
    codes = {i["code"] for i in report["issues"]}
    assert {"numeric_value_disagrees_with_raw", "evidence_field_not_present"} <= codes


def test_context_span_cannot_supply_a_target_result():
    bundle, raw = example()
    bundle.blocks[0].locator = "context-intro:synthetic"
    bundle.acquisition_notes.append("SOURCE_WINDOW synthetic")
    compact = compact_fixture(raw, bundle)
    report = validate_extraction(CompactExtraction.model_validate(compact).expand(bundle), bundle)
    assert "observation_only_in_window_context" in {i["code"] for i in report["issues"]}


def test_empty_quantitative_target_is_reviewed_but_context_numbers_are_not_results():
    bundle, raw = example()
    raw.update(outcome="empty", empty_reason="Synthetic empty response", samples=[], states=[], protocols=[], results=[])
    report = validate_extraction(Extraction.model_validate(raw), bundle)
    assert "empty_quantitative_target_requires_review" in {i["code"] for i in report["issues"]}
    bundle.blocks = make_blocks(bundle.documents[0].id, [
        ("target:synthetic", "SYNTHETIC qualitative conclusion without numerical results."),
        ("context-intro:synthetic", "SYNTHETIC cited 83% component at 39 K.")])
    bundle.acquisition_notes.append("SOURCE_WINDOW synthetic")
    raw["processed_block_ids"] = [b.id for b in bundle.blocks]
    assert validate_extraction(Extraction.model_validate(raw), bundle)["valid"]
    bundle.blocks = make_blocks(bundle.documents[0].id, [("target:synthetic", "SYNTHETIC [21] Author, Journal 12, 345 (2009).")])
    raw["processed_block_ids"] = [b.id for b in bundle.blocks]
    assert validate_extraction(Extraction.model_validate(raw), bundle)["valid"]


def test_prompt_explicitly_marks_every_target_span_and_places_targets_last():
    from ingestion.materials_ner.prompt import render
    bundle, _ = example()
    bundle.blocks = make_blocks(bundle.documents[0].id, [
        ("target:synthetic", "SYNTHETIC target with 83% and 17% admixture."),
        ("context-intro:synthetic", "SYNTHETIC model context.")])
    bundle.acquisition_notes.append("SOURCE_WINDOW synthetic")
    prompt = render(bundle)
    assert prompt.index("BEGIN_CONTEXT_BLOCK") < prompt.index("BEGIN_TARGET_BLOCK")
    assert '"target_span_ids":["S1"]' in prompt
    assert "BEGIN_TARGET_SPAN S1 BLOCK B1" in prompt
    assert "SYNTHETIC target with 83% and 17% admixture." in prompt


def test_worker_freezes_catalog_and_schema_hash_and_quarantines_unknown_span(tmp_path):
    bundle, raw = example()
    store = Store(tmp_path)
    bundle_hash, _ = save_bundle(tmp_path, bundle)
    identifier = store.enqueue(work_id=bundle.work_id, bundle_hash=bundle_hash, config=configuration())
    compact = compact_fixture(raw)
    compact["observations"][0]["sample"]["evidence"][0]["span_ids"] = ["S999"]
    result = run_one(store, job_id=identifier, provider_override=FakeProvider(compact))
    assert result["state"] == "quarantined" and result["error_code"] == "output_source_binding_invalid"
    receipt_path = next(tmp_path.glob("attempts/*/*/receipt.json"))
    receipt = json.loads(receipt_path.read_text())
    assert receipt["source_catalog_sha256"] == digest(json.loads(
        receipt_path.with_name("source-catalog.json").read_text()))
    assert receipt["effective_schema_sha256"] == digest(output_schema(bundle))


def test_generation_schema_prevents_numeric_non_detection():
    bundle, raw = example()
    compact = compact_fixture(raw)
    result = compact["observations"][0]["result"]
    result["quantity_kind"] = "non_detection"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(compact, output_schema(bundle))
    result["quantity"].update(status="not_applicable", value=None, relation=None, unit=None, raw=None)
    jsonschema.validate(compact, output_schema(bundle))


def test_only_unstarted_jobs_can_be_superseded_without_fabricating_attempts(tmp_path):
    store = Store(tmp_path)
    first = store.enqueue(work_id="synthetic:one", bundle_hash="0" * 64, config={})
    second = store.enqueue(work_id="synthetic:two", bundle_hash="1" * 64, config={})
    store.claim(job_id=first)
    with pytest.raises(ValueError, match="unstarted"):
        store.supersede_unstarted([second, first], "a" * 64)
    assert next(j for j in store.results() if j["id"] == second)["state"] == "queued"
    assert store.supersede_unstarted([second], "a" * 64) == 1
    assert store.claim(job_id=second) is None
    assert store.summary()["attempts"] == 1


@pytest.mark.parametrize(("kind", "value", "unit", "raw", "kwargs"), [
    ("debye_temperature", 250.0, "K", "250 K", {}),
    ("hc2", 5.68, "T", r"5.68\pm 0.12$~T", {"uncertainty": {
        "kind": "reported_unspecified", "minus": .12, "plus": .12, "level": None, "raw": r"\pm 0.12"}}),
    ("penetration_depth", 1100.0, "Å", r"1100 \AA", {}),
    ("sommerfeld_coefficient_molar", 7.08, "mJ/(mol K^2)", r"7.08 mJ/(mol K$^2$)", {}),
    ("lattice_heat_capacity_beta_molar", 3.52, "mJ/(mol K^4)", r"3.52 mJ mol$^{-1}$ K$^{-4}$", {}),
    ("heat_capacity_jump_over_tc_molar", 6.07, "mJ/mol K^2", "6.07", {}),
    ("normalized_heat_capacity_jump", .85, "1", "0.85", {}),
    ("lattice_strain", .0015, "1", r"1.5\times10^{-3}", {}),
    ("relative_debye_temperature_change", .3, "%", r"0.3\%", {}),
    ("pairing_component_fraction", 83.0, "%", "83%", {}),
    ("quality_factor", 346000.0, "1", r"3.46\cdot10^5", {}),
    ("tc", 6.5, "K", "∼6.5 K", {"approximate": True}),
    ("tc", 3.0, "K", r"$\sim$3 K", {"approximate": True}),
    ("tc", 1.5, "K", "nearly 1.5~K", {"approximate": True}),
    ("lattice_strain", .0015, "1", r"1.5 \times 10^{ - 3}", {}),
    ("sommerfeld_coefficient_molar", 7.08, "mJ/(mol K^2)", r"7.08\frac{mJ}{mol K^2}", {}),
    ("magnetic_flux_density", .1, "μT", r"0.1~$\muup$T", {}),
    ("surface_resistance", None, "mΩ", "10–20 mΩ", {"relation": "interval", "lower": 10.0, "upper": 20.0}),
    ("hc2_field_strength", 390.0, "kOe", "390 kOe", {}),
    ("tc_field_strength_slope", .05, "K/kOe", "0.05 K/kOe", {}),
    ("hc2_flux_density_slope", -2.5, "T/K", "-2.5 Tesla/Kelvin", {}),
])
def test_source_unit_numbers_tex_bounds_and_uncertainty(kind, value, unit, raw, kwargs):
    assert errors(kind, value, unit, raw, **kwargs) == []
    assert normalize(kind, Quantity.model_validate(quantity(value, unit, raw, **kwargs)))["normalized"]


@pytest.mark.parametrize(("kind", "value", "unit", "raw"), [
    ("relative_debye_temperature_change", .3, "1", r"0.3\%"),
    ("pairing_component_fraction", .83, "%", "83%"),
    ("pairing_component_fraction", 83.0, "1", "83%"),
    ("tc", .05, "K", "0.05 K/kOe"),
    ("hc2", 39.0, "T", "390 kOe"),
    ("lattice_heat_capacity_beta_molar", 2.3, "mJ/(mol K^4)", "2.30 mJ/(mol K^2)"),
    ("nmr_relaxation_power_law_exponent", 3.0, "1", "T^3"),
    ("heat_capacity_fraction", .01, "1", "0.01 C_P"),
])
def test_unit_coercion_scaling_laws_and_preconverted_percentages_are_rejected(kind, value, unit, raw):
    assert errors(kind, value, unit, raw)


def test_h_and_b_have_distinct_conversion_dimensions():
    h = normalize("hc2_field_strength", Quantity.model_validate(quantity(1.0, "Oe", "1 Oe")))["normalized"]
    b = normalize("hc2", Quantity.model_validate(quantity(1.0, "G", "1 G")))["normalized"]
    assert h["unit"] == "A/m" and h["value"] == pytest.approx(1000 / (4 * pi))
    assert b["unit"] == "T" and b["value"] == .0001
    with pytest.raises(ValueError, match="unregistered_unit"):
        normalize("hc2", Quantity.model_validate(quantity(1.0, "Oe", "1 Oe")))
    with pytest.raises(ValueError, match="unregistered_unit"):
        normalize("lattice_heat_capacity_beta_molar", Quantity.model_validate(
            quantity(2.30, "mJ/(mol K^2)", "2.30 mJ/(mol K^2)")))


def test_registered_result_kinds_all_have_a_registry_entry():
    kinds = set(Result.model_fields["quantity_kind"].annotation.__args__)
    assert kinds - {"unmapped", "non_detection"} <= UNITS.keys()


def test_gap_ratio_requires_component_definition_and_bound_evidence():
    bundle, raw = example()
    raw["results"][0].update(quantity_kind="gap_amplitude_ratio", quantity=quantity(39.0, "1", "39"))
    report = validate_extraction(Extraction.model_validate(raw), bundle)
    assert "quantity_component_definition_missing" in {i["code"] for i in report["issues"]}
    second = deepcopy(raw)
    second["results"][0]["component_raw"] = "a-axis / b-axis"
    report = validate_extraction(Extraction.model_validate(second), bundle)
    assert {"code": "field_evidence_missing", "path": "/results/0/component_raw"} in report["issues"]


def test_manager_holds_pdf_wrapper_but_accepts_resolved_body_and_regular_figures():
    script = Path(__file__).resolve().parents[2] / "scripts/materials_ner_arxiv_campaign.py"
    readiness = runpy.run_path(str(script))["source_readiness"]
    bundle, _ = example()
    bundle.blocks = make_blocks(bundle.documents[0].id, [("synthetic:wrapper", r"\includepdf[pages=-]{main.pdf}")])
    assert not readiness(bundle)["ready"]
    bundle.blocks = make_blocks(bundle.documents[0].id, [("pdf_page:1", "SYNTHETIC resolved PDF body with Tc = 39 K.")])
    assert readiness(bundle)["ready"]
    bundle.blocks = make_blocks(bundle.documents[0].id, [("synthetic:tex", r"SYNTHETIC Tc=39 K; \includegraphics{fig.pdf}")])
    assert readiness(bundle)["ready"]
