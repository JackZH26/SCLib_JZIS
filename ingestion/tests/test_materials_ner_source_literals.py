"""Source copies remain distinct from normalized scientific vocabulary."""
from copy import deepcopy

from ingestion.materials_ner.contract import Evidence
from ingestion.materials_ner.validation import validate_extraction
from ingestion.materials_ner.validation_v6 import validate_raw_literals
from ingestion.materials_ner.wire_v8 import RelationalExtraction
from test_materials_ner_relations import fixture


def sample_assertion():
    bundle,_,raw=fixture()
    sample=raw["samples"][0]
    sample["additional_formula_assertions"]=[{"formula_raw":"MgB2","basis":"nominal",
        "context_raw":"Sample A\n was nominal MgB2"}]
    sample["evidence"][0]["fields"].append("/additional_formula_assertions/0")
    return bundle,RelationalExtraction.model_validate(raw).expand(bundle)


def test_literal_formula_context_allows_layout_whitespace_but_not_prose_rewriting():
    bundle,extraction=sample_assertion()
    assert validate_extraction(extraction,bundle)["valid"]
    extraction.samples[0].additional_formula_assertions[0].context_raw="the nominal composition of Sample A"
    report=validate_extraction(extraction,bundle)
    assert {"code":"source_literal_not_in_field_evidence",
            "path":"/samples/0/additional_formula_assertions/0/context_raw"} in report["issues"]
    assert not report["scientific_acceptance"]


def test_formula_occurring_elsewhere_in_the_source_is_not_enough_for_its_bound_quote():
    bundle,extraction=sample_assertion()
    sample=extraction.samples[0]
    sample.evidence=[e for e in sample.evidence if e.field!="/formula_raw"]
    sample.evidence.append(Evidence(block_id=bundle.blocks[0].id,quote="SYNTHETIC FIXTURE.",field="/formula_raw"))
    assert "MgB2" in bundle.blocks[0].text
    assert {"code":"source_literal_not_in_field_evidence","path":"/samples/0/formula_raw"} in validate_extraction(extraction,bundle)["issues"]


def test_nested_assertion_cannot_borrow_sibling_evidence():
    _,extraction=sample_assertion();sample=extraction.samples[0]
    sample.additional_formula_assertions.append(deepcopy(sample.additional_formula_assertions[0]))
    sample.evidence=[e for e in sample.evidence if e.field!="/additional_formula_assertions/0"]
    sample.evidence.append(sample.evidence[0].model_copy(update={"field":"/additional_formula_assertions/1"}))
    issues=[];validate_raw_literals(extraction,lambda code,path:issues.append((code,path)))
    assert ("source_literal_evidence_missing","/samples/0/additional_formula_assertions/0/context_raw") in issues
    assert not any(path.startswith("/samples/0/additional_formula_assertions/1/") for _,path in issues)


def test_optional_raw_field_requires_its_own_assertion_binding_and_null_requires_none():
    bundle,extraction=sample_assertion();protocol=extraction.protocols[0]
    protocol.details_raw="four-probe resistivity measurement"
    assert {"code":"source_literal_evidence_missing","path":"/protocols/0/details_raw"} in validate_extraction(extraction,bundle)["issues"]
    protocol.evidence.append(Evidence(block_id=bundle.blocks[0].id,quote=bundle.blocks[0].text,field="/details_raw"))
    assert validate_extraction(extraction,bundle)["valid"]
    protocol.details_raw=None
    protocol.evidence=[e for e in protocol.evidence if e.field!="/details_raw"]
    protocol.method="electrical transport"  # Normalized method vocabulary is not a raw quote.
    assert validate_extraction(extraction,bundle)["valid"]


def test_source_hyphenation_is_not_silently_normalized_in_a_raw_field():
    bundle,extraction=sample_assertion();protocol=extraction.protocols[0]
    protocol.details_raw="four probe resistivity measurement"
    protocol.evidence.append(Evidence(block_id=bundle.blocks[0].id,quote=bundle.blocks[0].text,field="/details_raw"))
    assert {"code":"source_literal_not_in_field_evidence","path":"/protocols/0/details_raw"} in validate_extraction(extraction,bundle)["issues"]
