"""RG02 wire/delivery adversaries. Synthetic fixtures, no model or network."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from services import claim_support, rag
from services.rag_evidence_contract import VERSION, validate_evidence_descriptor
from services.source_visibility import source_visibility

TEXT = "H3S has an observed Tc of 100 K at 2 GPa. PRIVATE_EXCERPT_SENTINEL"
CLAIM = "H3S has an observed Tc of 100 K at 2 GPa [1]."


def descriptor(*, body=TEXT, kind="derived_fact", **changes):
    values = {
        "version": VERSION, "chunk_kind": kind,
        "evidence_revision_id": "11111111-1111-4111-8111-111111111111",
        "evidence_record_sha256": "a" * 64,
        "content_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "parent_result_revision_id": "22222222-2222-4222-8222-222222222222" if kind == "derived_fact" else None,
        "parent_result_sha256": "b" * 64 if kind == "derived_fact" else None,
        "extraction_version": "synthetic-extraction/1" if kind == "derived_fact" else None,
        "rendering_version": "synthetic-rendering/1" if kind == "derived_fact" else None,
        "source_capture_id": "33333333-3333-4333-8333-333333333333", "source_locator": {"page": 1},
        "root_status": "unresolved", "permission_status": "unresolved", "currentness": "current",
        "warning_codes": ["original_root_unresolved"], "support_eligible": False,
        "independent_evidence": False, "scientific_acceptance": False,
    }
    if kind == "legacy_unknown":
        values.update(evidence_revision_id=None, evidence_record_sha256=None,
                      source_capture_id=None, source_locator={}, currentness="unresolved")
    return {**values, **changes}


def source(*, body=TEXT, evidence=None, **changes):
    return rag.RagSourceInput(**{
        "index": 1, "paper_id": "synthetic:rg02-delivery", "title": "Synthetic fixture",
        "authors_short": "Synthetic", "year": 2026, "section": "Results", "text": body,
        "source_visibility": source_visibility("published"), "visibility_resolved": True,
        "evidence_provenance": descriptor(body=body) if evidence is None else evidence,
        **changes,
    })


def assert_no_positive_support(sources, answer=CLAIM):
    result = claim_support.assess_answer(answer, sources)
    assert result["status"] != "supported"
    assert result["coverage"]["supported_claims"] == 0
    assert all(claim["status"] != "supported" for claim in result["claims"])
    return result


@pytest.mark.parametrize("changes", [
    {"permission_status": "restricted"}, {"currentness": "stale"},
    {"content_sha256": "f" * 64}, {"version": "unknown/99"},
    {"support_eligible": True}, {"scientific_acceptance": True},
    {"root_status": "resolved"}, {"private_note": "UNTRUSTED_DESCRIPTOR_SENTINEL"},
])
def test_restricted_stale_mismatched_and_invalid_descriptors_hide_excerpt(changes):
    selected = source(evidence=descriptor(**changes))
    prompt_sources = json.loads(rag._format_sources([selected]))
    assert prompt_sources[0]["excerpt"] == ""
    assert "PRIVATE_EXCERPT_SENTINEL" not in rag.build_user_prompt("Synthetic query?", [selected])
    assert "UNTRUSTED_DESCRIPTOR_SENTINEL" not in rag.build_user_prompt("Synthetic query?", [selected])
    fallback = rag.extractive_fallback([selected])
    assert fallback.answer_mode == "abstention" and "PRIVATE_EXCERPT_SENTINEL" not in fallback.answer
    assert_no_positive_support([selected])


@pytest.mark.parametrize("malformed", [False, 0, [], "", None])
def test_falsy_malformed_descriptor_cannot_downgrade_to_legacy_text_policy(malformed):
    selected = source(evidence={})
    selected.evidence_provenance = malformed
    assert json.loads(rag._format_sources([selected]))[0]["excerpt"] == ""
    assert "PRIVATE_EXCERPT_SENTINEL" not in rag.extractive_fallback([selected]).answer
    assert_no_positive_support([selected])


@pytest.mark.parametrize("changes", [
    {"permission_status": "restricted"}, {"currentness": "stale"}, {"content_sha256": "f" * 64},
])
def test_withheld_excerpt_cannot_leak_its_extracted_material_content_to_prompt(changes):
    selected = source(evidence=descriptor(**changes), material_evidence=[{
        "formula": "WITHHELD_EXTRACTED_MATERIAL_SENTINEL",
        "source_quote": "WITHHELD_RAW_QUOTE_SENTINEL", "evidence_text": "WITHHELD_RAW_QUOTE_SENTINEL",
    }])
    prompt = rag.build_user_prompt("Synthetic query?", [selected])
    assert "WITHHELD_EXTRACTED_MATERIAL_SENTINEL" not in prompt
    assert "WITHHELD_RAW_QUOTE_SENTINEL" not in prompt
    assert json.loads(rag._format_sources([selected]))[0]["material_evidence"] == []


@pytest.mark.parametrize("kind", ["original_passage", "abstract", "derived_fact", "legacy_unknown"])
def test_unresolved_typed_root_can_navigate_but_never_support_or_approve(kind):
    evidence = validate_evidence_descriptor(descriptor(kind=kind))
    selected = source(evidence=evidence)
    before = deepcopy(evidence)
    assert json.loads(rag._format_sources([selected]))[0]["evidence_provenance"] == evidence
    report = assert_no_positive_support([selected])
    assert all(claim["evidence"] == [] for claim in report["claims"])
    assert selected.evidence_provenance == before
    assert evidence["support_eligible"] is evidence["independent_evidence"] is evidence["scientific_acceptance"] is False


def test_derived_self_reference_never_confirms_its_parent_extraction():
    parent = "22222222-2222-4222-8222-222222222222"
    selected = source(evidence=descriptor(parent_result_revision_id=parent))
    report = assert_no_positive_support([selected])
    assert "derived_evidence_root_unresolved" in report["claims"][0]["reason_codes"]
    assert selected.evidence_provenance["parent_result_revision_id"] == parent


def test_repeated_derivations_and_secondary_paper_do_not_add_independent_support():
    first = source()
    second = source(index=2, paper_id="synthetic:secondary-paper", evidence=descriptor(
        evidence_revision_id="44444444-4444-4444-8444-444444444444",
    ))
    # A shared capture/parent is a declared dependency, never a second experiment.
    assert first.evidence_provenance["source_capture_id"] == second.evidence_provenance["source_capture_id"]
    assert first.evidence_provenance["parent_result_revision_id"] == second.evidence_provenance["parent_result_revision_id"]
    report = assert_no_positive_support([first, second], CLAIM.replace("[1]", "[1,2]"))
    assert report["coverage"]["supported_claims"] == 0
    assert all(not selected.evidence_provenance["independent_evidence"] for selected in (first, second))


@pytest.mark.parametrize("field,value", [
    ("permission_status", "restricted"), ("currentness", "stale"),
    ("content_sha256", "f" * 64), ("rendering_version", "synthetic-rendering/2"),
    ("parent_result_revision_id", "44444444-4444-4444-8444-444444444444"),
    ("parent_result_sha256", "c" * 64),
    ("source_capture_id", "44444444-4444-4444-8444-444444444444"),
    ("source_locator", {"page": 2}),
])
def test_checked_result_fingerprint_binds_all_evidence_provenance(field, value):
    selected = source()
    result = rag.extractive_fallback([selected])
    sealed = result._validation_fingerprint
    assert sealed == rag._result_fingerprint(result, [selected])
    selected.evidence_provenance = {**selected.evidence_provenance, field: value}
    assert sealed != rag._result_fingerprint(result, [selected])
    if field in {"permission_status", "currentness", "content_sha256"}:
        changed = rag.finalize_result(result, [selected])
        assert changed.answer_mode == "abstention"
        assert "PRIVATE_EXCERPT_SENTINEL" not in changed.answer
        assert changed.scientific_support_status != "supported"


@pytest.mark.parametrize("kind,label", [
    ("derived_fact", "Derived fact (not original source text)"),
    ("legacy_unknown", "Unverified indexed text"),
])
def test_typed_derived_and_legacy_fallbacks_do_not_claim_original_prose(kind, label):
    selected = source(evidence=descriptor(kind=kind))
    fallback = rag.extractive_fallback([selected])
    assert label in fallback.answer and "Source excerpt [1]" not in fallback.answer
    assert fallback.scientific_support_status == "not_checked"


@pytest.mark.parametrize("section", ["Facts", "derived_facts", "AI-extracted Facts", "Derived", "Generated summary"])
def test_legacy_section_derived_fallback_is_never_labelled_original_source(section):
    selected = source(evidence={}, section=section)
    fallback = rag.extractive_fallback([selected])
    assert "Source excerpt [1]" not in fallback.answer
    assert_no_positive_support([selected])


def test_legacy_fact_header_cannot_hide_derived_origin_when_section_is_missing():
    selected = source(evidence={}, section=None, body="Title: Synthetic fixture\nSection: Facts\n\n" + TEXT)
    fallback = rag.extractive_fallback([selected])
    assert "Source excerpt [1]" not in fallback.answer
    assert_no_positive_support([selected])
