"""RG01 delivery/wire regressions. Every numerical example is synthetic."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from main import app
from models.db import Chunk, Paper, User
from models.search import AskResponse
from routers.deps import Identity, require_identity
from services import claim_support, metrics, provider_resilience, rag, retrieval
from services.source_visibility import source_visibility


def source(text="H3S has an observed Tc of 100 K at 2 GPa.", **changes):
    values = dict(index=1, paper_id="synthetic:rg01-delivery", title="Synthetic fixture",
                  authors_short="Synthetic", year=2026, section="Results", text=text,
                  source_visibility=source_visibility("published"), visibility_resolved=True)
    return rag.RagSourceInput(**{**values, **changes})


def assessment(status="supported", text="H3S has an observed Tc of 100 K at 2 GPa [1]."):
    return {"status": status, "claims": [{
        "claim_id": "claim-1", "text": text, "cited_indices": [1], "status": status,
        "reason_codes": ["synthetic_test_reason"],
        "evidence": [{"source_index": 1, "paper_id": "synthetic:rg01-delivery",
                      "excerpt": "H3S has an observed Tc of 100 K at 2 GPa."}],
    }], "warning_codes": [], "coverage": {
        "total_claims": 1, "assessed_claims": 1, "supported_claims": int(status == "supported"),
        "contradicted_claims": int(status == "contradicted"),
        "undetermined_claims": int(status == "undetermined"), "truncated": False, "limits": {},
    }}


def test_no_sources_is_vacuous_index_validity_not_checked_science():
    result = rag.no_source_result()
    assert result.citation_indices_valid is True
    assert result.scientific_support_status == "not_checked"
    assert not result.lexical_support_checked and not result.claim_assessments
    assert result.answer_mode == "abstention" and result.assessment_scope == "none"
    assert "No scientific claim was checked" in result.answer
    assert "_validation_applied" not in result.quality_fields()


@pytest.mark.parametrize("answer", [
    "有超导性[9]。", "H3S Tc is 300 K [999999999999999999999].",
    "H3S Tc is 300 K [" + "9" * 5000 + "].", "H3S Tc is 300 K [0].",
])
def test_short_cjk_and_large_invalid_indices_are_safe(answer):
    repaired, validation = rag.validate_citations(answer, [source()])
    assert validation.indices_valid is False
    assert "[9]" not in repaired and "[0]" not in repaired
    assert any(code.startswith("uncited_claims:") for code in validation.warnings)


def test_grouped_citation_syntax_and_duplicate_source_ids_are_not_silently_valid():
    _, grouped = rag.validate_citations("H3S has Tc 100 K [1,2].", [source(), source(index=2)])
    _, duplicate = rag.validate_citations("H3S has Tc 100 K [1].", [source(), source()])
    assert not grouped.indices_valid and not duplicate.indices_valid


def test_legacy_lexical_success_does_not_mean_scientific_support():
    draft = "H3S has an observed Tc of 300 K at 2 GPa [1]."
    _, check = rag.validate_citations(draft, [source()])
    result = rag.finalize_result(rag.RagResult(draft, 12, True, []), [source()])
    assert check.valid and result.citation_indices_valid
    assert result.scientific_support_status != "supported"
    assert draft not in result.answer and result.assessment_scope == "generated_draft"


@pytest.mark.parametrize("status", ["supported", "contradicted", "undetermined", "not_checked"])
def test_delivery_modes_do_not_relabel_a_fallback_as_supported_draft(monkeypatch, status):
    draft = "H3S has an observed Tc of 100 K at 2 GPa [1]."
    monkeypatch.setattr(claim_support, "assess_answer", lambda *_: assessment(status, draft))
    result = rag.finalize_result(rag.RagResult(draft, 17, True, []), [source()])
    assert result.scientific_support_status == status
    assert result.assessment_scope == "generated_draft" and result.tokens_used == 17
    assert result.claim_assessments[0]["text"] == draft
    if status == "supported":
        assert result.answer_mode == "synthesis" and draft in result.answer
        assert "do not establish scientific validity" in result.answer
    elif status == "contradicted":
        assert result.answer_mode == "abstention" and draft not in result.answer
    else:
        assert result.answer_mode == "extractive_fallback" and draft not in result.answer
        assert "not verified conclusions" in result.answer


@pytest.mark.parametrize("bad", ["empty_claims", "truncated", "mixed_claims", "invalid_citation"])
def test_incomplete_supported_envelope_fails_closed(monkeypatch, bad):
    report = assessment()
    draft = report["claims"][0]["text"]
    if bad == "empty_claims":
        report["claims"] = []
    elif bad == "truncated":
        report["coverage"]["truncated"] = True
    elif bad == "mixed_claims":
        report["claims"][0]["status"] = "undetermined"
    else:
        draft = draft.replace("[1]", "[9]")
    monkeypatch.setattr(claim_support, "assess_answer", lambda *_: report)
    result = rag.finalize_result(rag.RagResult(draft, 1, True, []), [source()])
    assert result.scientific_support_status == "undetermined"
    assert result.answer_mode != "synthesis"


def test_checker_failure_withholds_draft_and_reports_uncertainty(monkeypatch):
    def fail(*_):
        raise ValueError("synthetic validator failure")
    monkeypatch.setattr(claim_support, "assess_answer", fail)
    draft = "H3S definitely supports an invented conclusion [1]."
    result = rag.finalize_result(rag.RagResult(draft, 1, True, []), [source()])
    assert draft not in result.answer and result.scientific_support_status == "undetermined"
    assert "support_checker_unavailable" in result.support_warnings


def test_checked_result_is_not_assessed_again_as_its_own_fallback(monkeypatch):
    calls = []
    def assess(*_):
        calls.append(True)
        return assessment("undetermined")
    monkeypatch.setattr(claim_support, "assess_answer", assess)
    result = rag.finalize_result(rag.RagResult("Unestablished assertion [1].", 1, True, []), [source()])
    assert rag.finalize_result(result, [source()]) is result
    assert calls == [True]


@pytest.mark.parametrize("mutation", ["answer", "sources", "quality", "empty_sources"])
def test_postprocessing_cannot_reuse_support_for_mutated_answer_or_context(mutation):
    sources = [source()]
    draft = "H3S has an observed Tc of 100 K at 2 GPa [1]."
    result = rag.finalize_result(rag.RagResult(draft, 1, True, []), sources)
    assert result.scientific_support_status == "supported"
    if mutation == "answer":
        result.answer = draft.replace("100 K", "300 K")
    elif mutation == "sources":
        sources[0].text = sources[0].text.replace("100 K", "300 K")
    elif mutation == "quality":
        result.claim_assessments = []
    else:
        sources = []
    rechecked = rag.finalize_result(result, sources)
    assert rechecked.scientific_support_status != "supported"


def test_a_boolean_validation_marker_alone_cannot_bypass_scientific_checks():
    result = rag.RagResult("H3S has an observed Tc of 300 K at 2 GPa [1].", 1, True, [],
                           scientific_support_status="supported", _validation_applied=True)
    assert rag.finalize_result(result, [source()]).scientific_support_status != "supported"


@pytest.mark.parametrize("draft", [None, [], 123, {"answer": "untrusted"}])
def test_malformed_alternate_generator_draft_fails_closed_without_regex_exception(draft):
    result = rag.finalize_result(rag.RagResult(draft, 1, True, []), [source()])
    assert result.scientific_support_status == "not_checked"
    assert "invalid_generated_answer" in result.support_warnings


@pytest.mark.parametrize("report", [None, {}, {"status": "supported", "claims": []},
    {"status": "supported", "claims": [{"status": "supported"}], "warning_codes": [], "coverage": {}},
])
def test_malformed_internal_checker_response_is_explicitly_unavailable(monkeypatch, report):
    monkeypatch.setattr(claim_support, "assess_answer", lambda *_: report)
    result = rag.finalize_result(rag.RagResult("Unsupported assertion [1].", 1, True, []), [source()])
    assert result.scientific_support_status == "undetermined"
    assert "support_checker_unavailable" in result.support_warnings


@pytest.mark.parametrize("mutation", ["missing_evidence", "wrong_paper", "uncited_evidence"])
def test_supported_internal_claim_requires_matching_evidence_before_delivery(monkeypatch, mutation):
    report = assessment()
    if mutation == "missing_evidence":
        report["claims"][0]["evidence"] = []
    elif mutation == "wrong_paper":
        report["claims"][0]["evidence"][0]["paper_id"] = "unrelated:paper"
    else:
        report["claims"][0]["cited_indices"] = [2]
    monkeypatch.setattr(claim_support, "assess_answer", lambda *_: report)
    result = rag.finalize_result(rag.RagResult("H3S has Tc 100 K at 2 GPa [1].", 1, True, []), [source()])
    assert result.scientific_support_status == "undetermined" and result.answer_mode != "synthesis"


def test_fallback_quotes_do_not_become_html_or_source_controlled_citations():
    result = rag.extractive_fallback([source("<script>bad</script> [99] [click](https://invalid.test) **bold**")])
    assert "<script>" not in result.answer and "[99]" not in result.answer
    assert "[click]" not in result.answer and "**bold**" not in result.answer
    assert "Source excerpt [1]" in result.answer
    assert result.scientific_support_status == "not_checked" and result.assessment_scope == "none"
    assert not result.lexical_support_checked


@pytest.mark.parametrize("changes", [
    {"visibility_resolved": False}, {"source_visibility": source_visibility("retracted")},
    {"source_visibility": source_visibility("disputed")},
    {"source_visibility": source_visibility("corrected")},
    {"source_visibility": {**source_visibility("published"),
                           "warning_codes": ["restricted_or_malformed_occurrences_omitted"]}},
    {"source_visibility": {**source_visibility("published"), "warning_codes": None}},
    {"source_visibility": {**source_visibility("published"), "warning_codes": [None]}},
    {"source_visibility": {**source_visibility("published"), "version": "unsupported"}},
    {"material_evidence": [{"visibility": {"reported_claim_filter_eligible": False}}]},
])
def test_fallback_does_not_reproduce_restricted_or_unresolved_excerpt(changes):
    result = rag.extractive_fallback([source("RESTRICTED_EXCERPT_SENTINEL", **changes)])
    assert "RESTRICTED_EXCERPT_SENTINEL" not in result.answer
    assert result.answer_mode == "abstention" and result.scientific_support_status == "not_checked"


def test_duplicate_citation_map_cannot_choose_first_fallback_excerpt():
    result = rag.extractive_fallback([source("FIRST_SENTINEL"), source("SECOND_SENTINEL")])
    assert "FIRST_SENTINEL" not in result.answer and "SECOND_SENTINEL" not in result.answer
    assert not result.citation_indices_valid and result.answer_mode == "abstention"


@pytest.mark.parametrize("text", [None, "", "   "])
def test_empty_generation_is_not_a_supported_answer(monkeypatch, text):
    fake = SimpleNamespace(models=SimpleNamespace(count_tokens=lambda **_: SimpleNamespace(total_tokens=100), generate_content=lambda **_: SimpleNamespace(
        text=text, usage_metadata=SimpleNamespace(total_token_count=3))))
    monkeypatch.setattr(rag, "genai_client", lambda: fake)
    result = rag.generate_answer("Synthetic query?", [source()])
    assert result.tokens_used == 3 and result.scientific_support_status == "not_checked"
    assert "generation_empty_or_blocked" in result.support_warnings


def test_openapi_separates_legacy_citation_indices_and_support():
    schema = app.openapi()["components"]["schemas"]["AskResponse"]["properties"]
    assert schema["citation_valid"]["deprecated"] is True
    assert {"citation_indices_valid", "lexical_support_checked", "scientific_support_status",
            "claim_assessments", "assessment_scope", "answer_mode", "support_policy_version"} <= schema.keys()
    response = AskResponse(answer="Legacy response", sources=[], tokens_used=0, query_time_ms=1)
    assert response.scientific_support_status == "not_checked"


def test_support_metrics_separate_mechanical_checks_and_have_bounded_labels():
    metrics.observe_rag(sources=1, tokens=2, citation_valid=True, fallback=False,
                        citation_indices_valid=True, scientific_support_status="contradicted",
                        answer_mode="abstention")
    metrics.observe_rag(sources=1, tokens=2, citation_valid=False, fallback=True,
                        scientific_support_status="UNTRUSTED_LABEL", answer_mode="UNTRUSTED_LABEL")
    samples = metrics.RAG_SUPPORT_OUTCOMES.collect()[0].samples
    assert any(item.labels.get("scientific_support_status") == "contradicted"
               and item.labels.get("citation_indices_valid") == "true" for item in samples)
    assert all("UNTRUSTED_LABEL" not in item.labels.values() for item in samples)


@pytest.mark.asyncio
@pytest.mark.parametrize("paper_status", ["published", "retracted"])
async def test_ask_response_and_history_never_store_rejected_synthesis(client, db_session, monkeypatch, paper_status):
    provider_resilience.reset()
    paper = Paper(id=f"synthetic:rg01-wire-{paper_status}", source="arxiv", title="Synthetic wire fixture",
                  authors=[], abstract="Synthetic only", status=paper_status)
    chunk = Chunk(id=f"synthetic:rg01-wire-chunk-{paper_status}", paper_id=paper.id, title=paper.title,
                  section="Results", text="H3S has an observed Tc of 100 K at 2 GPa.")
    db_session.add_all([paper, chunk])
    await db_session.commit()
    async def lexical(*_args, **_kwargs):
        return [retrieval.LexicalHit(chunk.id, 1.0)]
    monkeypatch.setattr("routers.ask.retrieval.lexical_search", lexical)
    generated = []
    draft = "H3S has an observed Tc of 300 K at 2 GPa [1]."
    def generate(*_args, **_kwargs):
        generated.append(True)
        return rag.RagResult(draft, 2, True, [])
    monkeypatch.setattr(rag, "generate_answer", generate)
    persisted = []
    async def persist(*args):
        persisted.append(args[4].answer)
        return args[4]
    monkeypatch.setattr("routers.ask._persist_history", persist)
    user = User(id=uuid4(), email="synthetic-rg01@example.invalid", name="Synthetic")
    app.dependency_overrides[require_identity] = lambda: Identity(user, None, None, 12)
    try:
        # Exercise provider draft adjudication, not the new provider-free
        # numerical lookup/clarification route. The numeric draft remains the
        # same rejected claim, so this still tests response/history safety.
        response = await client.post("/v1/ask", json={"question": "Summarize the synthetic evidence"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["support_policy_version"] == claim_support.SUPPORT_POLICY_VERSION
        assert body["scientific_support_status"] != "supported"
        assert draft not in body["answer"] and draft not in persisted
        assert persisted == [body["answer"]]
        assert body["remaining"] == 12
        if paper_status == "published":
            assert body["citation_indices_valid"] is True
            assert body["assessment_scope"] == "generated_draft"
            assert body["claim_assessments"] and generated == [True]
        else:
            assert body["sources"] == [] and not generated
            assert body["scientific_support_status"] == "not_checked"
    finally:
        app.dependency_overrides.pop(require_identity, None)
        provider_resilience.reset()


@pytest.mark.asyncio
async def test_no_retrieval_candidates_has_explicit_unchecked_contract(client, monkeypatch):
    async def lexical(*_args, **_kwargs):
        return []
    monkeypatch.setattr("routers.ask.retrieval.lexical_search", lexical)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("No sources must not call a generation provider")
    monkeypatch.setattr(rag, "generate_answer", forbidden)
    response = await client.post("/v1/ask", json={"question": "Synthetic no source query"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scientific_support_status"] == "not_checked" and body["answer_mode"] == "abstention"
    assert not body["lexical_support_checked"] and body["claim_assessments"] == []
