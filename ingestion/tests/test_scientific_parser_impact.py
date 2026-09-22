"""Parser version invalidation and raw-loss reporting are offline only."""

import importlib.util
from pathlib import Path

from ingestion.extract.formula_enrichment import enrich_formula
from ingestion.extract.material_ner import normalize_material_records

_PATH = Path(__file__).resolve().parents[2] / "scripts/audit_scientific_parser_impact.py"
_SPEC = importlib.util.spec_from_file_location("scientific_parser_impact", _PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
build_impact_report = _MODULE.build_impact_report


def test_dry_run_flags_old_exact_features_and_irrecoverable_legacy_units():
    stale = enrich_formula("MgB2")
    stale.pop("composition_status")
    stale["parser_version"] = "1.0.3"
    material = {
        "id": "mat:mgb2",
        "formula": "MgB2",
        "composition_status": "exact",
        "composition_data": stale,
        "records": [{"tc_kelvin": 1, "pressure_gpa": 20}],
    }
    report = build_impact_report([material])
    row = report["materials"][0]
    assert row["invalidate_cached_features"]
    assert not row["composition_cache_current"]
    assert all(q["requires_source_recheck"] for q in row["quantities"])
    assert all(
        q["reason"] == "legacy_raw_unit_and_relation_unverifiable" for q in row["quantities"]
    )
    assert report["mode"] == "offline_dry_run"
    assert report == build_impact_report([material])


def test_preserved_units_are_reparsed_and_isotope_sources_guard_catalog_identity():
    record = normalize_material_records(
        [{"formula": "La₂Cu¹⁸O₄", "tc_kelvin": "1e-3 K", "pressure_gpa": "20 kbar"}],
        paper_type="experimental",
    )[0]
    report = build_impact_report(
        [{"id": "mat:example", "formula": "La2Cu18O4", "records": [record]}]
    )
    row = report["materials"][0]
    assert row["proposed_composition"]["composition_status"] == "invalid"
    values = {q["field"]: q for q in row["quantities"]}
    assert values["pressure_gpa"]["proposed_scalar"] == 2
    assert values["tc_kelvin"]["proposed_scalar"] == 0.001
    assert not values["pressure_gpa"]["requires_source_recheck"]
