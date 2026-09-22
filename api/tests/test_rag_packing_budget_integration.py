"""RAG assembly/seal integration with offline full-request provider counting."""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import pytest

from models.evidence_packing import EvidencePackingSummary, PackingCandidate
from models.rag_input_budget import RagInputBudgetReport
from services import evidence_packing, rag
from tests.test_rag_evidence_delivery import descriptor
from tests.test_rag_support_contract import source


def packing_for(sources, question="Question?", language="auto"):
    sources[0].source_snapshot_sha256 = "1" * 64
    candidate = PackingCandidate(chunk_id="synthetic:chunk", paper_id=sources[0].paper_id,
        source_snapshot_sha256="1" * 64, content_sha256="2" * 64, chunk_kind="original_passage", role_hint="results")
    sources[0].packing_info = evidence_packing.describe_selection([candidate], [candidate.chunk_id])[0]
    return EvidencePackingSummary(status="packed", candidate_count=1, selected_count=1,
        source_group_count=1, diversity_group_count=1, payload_bytes=rag.measure_input_bytes(question, sources, language=language),
        byte_budget=262144)


def fake_client(monkeypatch, *, count=100, text="", tokens=3, count_action=None, generate_action=None):
    calls = []
    def count_tokens(**kwargs):
        calls.append(("count", copy.deepcopy(kwargs)))
        if count_action:
            count_action()
        return SimpleNamespace(total_tokens=count)
    def generate_content(**kwargs):
        calls.append(("generate", copy.deepcopy(kwargs)))
        if generate_action:
            generate_action()
        return SimpleNamespace(text=text, usage_metadata=SimpleNamespace(total_token_count=tokens))
    monkeypatch.setattr(rag, "genai_client", lambda: SimpleNamespace(models=SimpleNamespace(
        count_tokens=count_tokens, generate_content=generate_content)))
    return calls


def test_exact_question_source_whitespace_and_citation_packing_metadata_are_counted_and_sent(monkeypatch):
    question, text = "  Question Ω?\n", " \nSource Ω with a negative result; do not omit conditions.\n "
    sources = [source(text)]
    packing = packing_for(sources, question, language="zh")
    prepared = rag.prepare_request(question, sources, language="zh")
    assert prepared.payload_bytes == rag.measure_input_bytes(question, sources, language="zh") == packing.payload_bytes
    calls = fake_client(monkeypatch)
    result = rag.generate_answer(question, sources, language="zh", evidence_packing=packing)
    counted, generated = [row[1] for row in calls]
    assert counted["contents"] == generated["contents"]
    prompt = counted["contents"][0]["parts"][0]["text"]
    assert f"<user_question>\n{question}\n</user_question>" in prompt
    source_json = prompt.split("<untrusted_sources_json>\n", 1)[1].split("\n</untrusted_sources_json>", 1)[0]
    item, = json.loads(source_json)
    assert item["excerpt"] == text
    assert item["packing_info"] == sources[0].packing_info.model_dump()
    system = counted["config"].system_instruction.parts[0].text
    assert "language preference is: zh" in system
    assert "retained paper/catalogue snapshots" in system and "not\na raw PDF hash" in system
    assert result.input_budget.request_sha256 == prepared.request_sha256
    assert result.input_budget.payload_bytes == packing.payload_bytes
    assert result.evidence_packing == packing
    assert result.tokens_used == 3 and result.assessment_scope == "none"
    assert result._validation_fingerprint == rag._result_fingerprint(result, sources)


def test_complete_packing_trial_above_1mib_is_measured_not_clipped_or_sent(monkeypatch):
    calls = fake_client(monkeypatch)
    sources = [source("exact complete source " * 70000)]
    assert rag.measure_input_bytes("Question?", sources) > 1024 * 1024
    result = rag.generate_answer("Question?", sources)
    assert calls == [] and result.input_budget.status == "rejected"
    assert "rag_input_byte_limit_exceeded" in result.support_warnings
    assert result.tokens_used == 0 and result.input_budget.generation_started is False


def test_count_rejection_keeps_packing_and_unknown_usage_before_first_fallback_seal(monkeypatch):
    sources = [source()]
    packing = packing_for(sources)
    calls = fake_client(monkeypatch, count=20000)
    result = rag.generate_answer("Question?", sources, evidence_packing=packing)
    assert [row[0] for row in calls] == ["count"]
    assert result.evidence_packing == packing and result.input_budget.status == "rejected"
    assert result.input_budget.input_tokens == 20000 and result.tokens_used is None
    assert result._validation_fingerprint == rag._result_fingerprint(result, sources)
    monkeypatch.setattr(rag.claim_support, "assess_answer", lambda *args: (_ for _ in ()).throw(AssertionError("Do not reassess a sealed fallback")))
    assert rag.finalize_result(result, sources, evidence_packing=packing) is result


def test_count_failure_and_generation_failure_preserve_context_but_not_private_error(monkeypatch):
    def broken():
        raise RuntimeError("PRIVATE SOURCE OR CREDENTIAL")
    for phase in ("count", "generate"):
        sources = [source()]
        packing = packing_for(sources)
        calls = fake_client(monkeypatch, count_action=broken if phase == "count" else None,
                            generate_action=broken if phase == "generate" else None)
        with pytest.raises(rag.RagProviderFailure) as caught:
            rag.generate_answer("Question?", sources, evidence_packing=packing)
        result = caught.value.result
        assert len(calls) == (1 if phase == "count" else 2)
        assert result.input_budget.status == "unavailable" and result.tokens_used is None
        assert result.input_budget.generation_started is (phase == "generate")
        assert result.evidence_packing == packing and "PRIVATE" not in str(result.quality_fields()) + result.answer
        assert result._validation_fingerprint == rag._result_fingerprint(result, sources)
        assert "PRIVATE" not in str(caught.value) and caught.value.__suppress_context__


def test_client_construction_failure_is_carried_to_breaker_with_sealed_safe_result(monkeypatch):
    def broken():
        raise RuntimeError("PRIVATE CLIENT AUTHENTICATION FAILURE")
    monkeypatch.setattr(rag, "genai_client", broken)
    sources = [source()]
    packing = packing_for(sources)
    with pytest.raises(rag.RagProviderFailure) as caught:
        rag.generate_answer("Question?", sources, evidence_packing=packing)
    result = caught.value.result
    assert result.evidence_packing == packing and result.input_budget.status == "unavailable"
    assert result.input_budget.generation_started is False and result.tokens_used is None
    assert result.input_budget.request_sha256 == rag.prepare_request("Question?", sources).request_sha256
    assert "rag_input_client_unavailable" in result.support_warnings
    assert "PRIVATE" not in str(caught.value) + result.answer + str(result.quality_fields())
    assert result._validation_fingerprint == rag._result_fingerprint(result, sources)


@pytest.mark.parametrize("count", [None, True, 0, "100"])
def test_invalid_provider_count_is_failure_not_normal_fallback_health_success(monkeypatch, count):
    calls = fake_client(monkeypatch, count=count)
    with pytest.raises(rag.RagProviderFailure) as caught:
        rag.generate_answer("Question?", [source()])
    assert [row[0] for row in calls] == ["count"]
    assert "rag_input_count_invalid" in caught.value.result.support_warnings


def test_provider_health_distinguishes_count_success_from_local_rejection_or_no_dispatch(monkeypatch):
    fake_client(monkeypatch, count=20000)
    rejected = rag.generate_answer("Question?", [source()])
    assert rejected.input_budget.status == "rejected" and rag.provider_status(rejected) == "success"
    local = rag.generate_answer("Question?", [source("x" * 300000)])
    assert local.input_budget.status == "rejected" and rag.provider_status(local) == "not_requested"
    stop = Event()
    stop.set()
    cancelled = rag.generate_answer("Question?", [source()], stop_event=stop)
    assert rag.provider_status(cancelled) == "not_requested"
    assert rag.provider_status(rag.no_source_result()) == "not_requested"
    assert rag.provider_status(rag.RagResult("Alternate", None, False, [])) == "not_requested"
    assert rag.provider_status(SimpleNamespace(input_budget={"input_tokens": 100})) == "not_requested"


def test_count_completion_after_cancel_does_not_generate_and_keeps_sealed_report(monkeypatch):
    stop = Event()
    calls = fake_client(monkeypatch, count_action=stop.set)
    with pytest.raises(rag.RagProviderFailure) as caught:
        rag.generate_answer("Question?", [source()], stop_event=stop)
    result = caught.value.result
    assert len(calls) == 1 and result.input_budget.generation_started is False
    assert result.input_budget.status == "unavailable" and "rag_input_cancelled" in result.support_warnings


def test_post_count_deadline_failure_is_not_mistaken_for_predispatch_neutral_status(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(rag.rag_input_budget.time, "monotonic", lambda: now[0])
    calls = fake_client(monkeypatch, count_action=lambda: now.__setitem__(0, 1000.0))
    with pytest.raises(rag.RagProviderFailure) as caught:
        rag.generate_answer("Question?", [source()])
    assert len(calls) == 1
    assert caught.value.result.input_budget.input_tokens is None
    assert caught.value.result.input_budget.generation_started is False
    assert "rag_input_deadline_exceeded" in caught.value.result.support_warnings


def test_valid_alternate_sealed_fallback_gets_caller_context_without_reassessment_or_mutation(monkeypatch):
    sources = [source()]
    packing = packing_for(sources)
    original = rag.extractive_fallback(sources)
    original_fingerprint = original._validation_fingerprint
    monkeypatch.setattr(rag.claim_support, "assess_answer", lambda *args: (_ for _ in ()).throw(AssertionError("Fallback prose is not a generated draft")))
    updated = rag.finalize_result(original, sources, evidence_packing=packing,
                                  input_budget=RagInputBudgetReport(status="unavailable"))
    assert updated is not original and updated.answer == original.answer
    assert updated.assessment_scope == "none" and not updated.claim_assessments
    assert updated.evidence_packing == packing and updated.input_budget.generation_started is None
    assert original.evidence_packing.status == "not_requested" and original._validation_fingerprint == original_fingerprint
    assert updated._validation_fingerprint == rag._result_fingerprint(updated, sources)


@pytest.mark.parametrize("alternate", [None, "untrusted model result", SimpleNamespace(answer="Unverified answer")])
def test_invalid_alternate_cannot_erase_authoritative_context(alternate):
    sources = [source()]
    packing = packing_for(sources)
    budget = RagInputBudgetReport(status="unavailable")
    result = rag.finalize_result(alternate, sources, evidence_packing=packing, input_budget=budget)
    assert result.evidence_packing == packing and result.input_budget == budget
    assert "invalid_generated_answer" in result.support_warnings and result.tokens_used is None


def test_context_and_per_citation_metadata_are_part_of_seal():
    sources = [source()]
    packing = packing_for(sources)
    result = rag.extractive_fallback(sources, evidence_packing=packing)
    digest = result._validation_fingerprint
    assert rag._result_fingerprint(replace(result, input_budget=RagInputBudgetReport(status="unavailable")), sources) != digest
    sources[0].packing_info = replace(sources[0], packing_info=None).packing_info
    assert rag._result_fingerprint(result, sources) != digest


def test_empty_fallback_context_is_sealed_without_postseal_warning_mutation():
    budget = RagInputBudgetReport(status="unavailable")
    result = rag.extractive_fallback([], reason="synthetic_failure", input_budget=budget, tokens_used=None)
    assert result.input_budget == budget and result.tokens_used is None
    assert result._validation_fingerprint == rag._result_fingerprint(result, [])


def test_invalid_or_mismatched_packing_prevents_provider_work(monkeypatch):
    calls = fake_client(monkeypatch)
    sources = [source()]
    packing = packing_for(sources)
    invalid = packing.model_copy(update={"payload_bytes": packing.payload_bytes - 1})
    result = rag.generate_answer("Question?", sources, evidence_packing=invalid)
    assert not calls and "packing_payload_mismatch" in result.support_warnings
    result = rag.generate_answer("Question?", sources, evidence_packing={"scientific_acceptance": True})
    assert not calls and result.evidence_packing.status == "unavailable"


@pytest.mark.parametrize("fault", ["paper", "snapshot", "source_group", "unmapped_diversity", "position"])
def test_packing_binding_checks_actual_paper_catalogue_snapshot_and_citation(monkeypatch, fault):
    calls = fake_client(monkeypatch)
    sources = [source()]
    packing = packing_for(sources)
    if fault == "paper":
        sources[0].paper_id = "other:paper"
    elif fault == "snapshot":
        sources[0].source_snapshot_sha256 = "3" * 64
    elif fault == "position":
        sources[0].index = 2
    else:
        key = "source_group_id" if fault == "source_group" else "diversity_group_id"
        prefix = "src:" if fault == "source_group" else "div:"
        sources[0].packing_info = sources[0].packing_info.model_copy(update={key: prefix + "3" * 64})
    result = rag.generate_answer("Question?", sources, evidence_packing=packing)
    assert not calls and result.input_budget.status == "unavailable"
    assert "rag_input_preparation_unavailable" in result.support_warnings


def test_invalid_alternate_contexts_do_not_break_quality_fields_or_get_trusted():
    result = rag.RagResult("Alternate", None, False, [], evidence_packing={"scientific_acceptance": True},
                           input_budget={"scientific_acceptance": True})
    fields = result.quality_fields()
    assert fields["evidence_packing"]["status"] == fields["input_budget"]["status"] == "unavailable"
    assert not fields["evidence_packing"]["scientific_acceptance"] and not fields["input_budget"]["scientific_acceptance"]


def test_packing_rejects_content_hash_mismatch_before_count_and_withholds_old_text(monkeypatch):
    calls = fake_client(monkeypatch)
    sources = [source("Actual retained original text")]
    sources[0].evidence_provenance = descriptor(body=sources[0].text, kind="original_passage")
    packing = packing_for(sources)
    sources[0].text = "ALTERED_PRIVATE_SOURCE"
    result = rag.generate_answer("Question?", sources, evidence_packing=packing)
    assert not calls and result.input_budget.status == "unavailable"
    assert "ALTERED_PRIVATE_SOURCE" not in result.answer


@pytest.mark.parametrize("usage", [None, True, -1, "3", 3.5])
def test_malformed_or_missing_usage_is_unknown_never_coerced_to_zero(monkeypatch, usage):
    fake_client(monkeypatch, tokens=usage)
    result = rag.generate_answer("Question?", [source()])
    assert result.tokens_used is None and result.input_budget.status == "counted"
