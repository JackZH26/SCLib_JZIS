"""Real disposable SQL capture -> offline evaluation; no real scientific gold.

0060 lineage, 0061 embedding receipts and 0062 immutable generations are written
through the actual ingestion services. Only synthetic SDK responses and the
enumerable disposable vector adapter are used. The portable evaluator verifies
the captured objects but does not authenticate live SQL, people or permissions.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa

from models.db import get_session_factory
from models.evidence_packing import PackingCandidate
from models.index_read import generation_read_metadata
from services import index_generations, index_retrieval, index_vector_adapter, rag
from services.evidence_packing import describe_selection
from services.rag_evidence_contract import input_record_sha256
from services.rag_input_budget import build_request
from services.scientific_evaluation import (
    ScientificEvaluationError,
    compare_package,
    validate_package,
)
from tests import index_generation_fixtures as generations
from tests.scientific_evaluation_fixtures import MODEL, make_package, reseal


@pytest_asyncio.fixture
async def sql_capture(monkeypatch):
    """Capture complete actual frozen membership, never current positional IDs."""
    logical = "eval-capture-" + uuid4().hex
    original_corpus = generations.corpus

    def mixed_corpus(**kwargs):
        meta, record, chunks = original_corpus(**kwargs)
        for index, chunk in enumerate(chunks[:2]):
            chunk.section = "Methods" if index == 0 else "Results"
            chunk.evidence_candidate = {"version": "rag-evidence/1.0.0", "chunk_kind": "original_passage",
                "rendering_version": "synthetic-original-chunker/1",
                "source_locator": {"section": chunk.section, "char_start": 0, "char_end": len(chunk.text)}}
        return meta, record, chunks

    monkeypatch.setattr(generations, "corpus", mixed_corpus)
    index_vector_adapter.register_disposable(generations.RESOURCE)
    try:
        meta, chunks, staged = await generations.write_generation(monkeypatch, logical_index=logical, count=5)
        async with get_session_factory()() as db:
            await generations.publish_and_activate(db, staged)
            pin = await index_generations.load_active_generation(db, logical_index=logical)
            members = await index_generations.load_generation_members(db, generation_id=pin["generation_id"])
            members.sort(key=lambda item: item["snapshot_json"]["chunk_index"])
            hydrated = await index_retrieval.hydrate(db, pin, [member["vector_id"] for member in members])
            descriptors = await index_retrieval.resolve_evidence(db, list(hydrated.values()))
            derived = members[2]
            descriptor = descriptors[derived["vector_id"]]
            parent = (await db.execute(sa.text("""SELECT to_jsonb(x) AS row,
                record_sha256=public.sclib_rag_evidence_record_hash_v1(to_jsonb(x)) AS intact
                FROM rag_extraction_revisions x WHERE id=:id"""),
                {"id": UUID(descriptor["parent_result_revision_id"])})).mappings().one()
            receipts = await db.scalar(sa.text("""SELECT count(*) FROM embedding_completion_receipts
                WHERE id IN (SELECT receipt_id FROM index_generation_members WHERE generation_id=:id)"""),
                {"id": UUID(pin["generation_id"])})
        sources = [{"id": f"frozen-{index}", "paper_id": member["paper_id"], "vector_id": member["vector_id"],
            "vector_sha256": member["vector_sha256"], "source_snapshot_sha256": member["source_snapshot_sha256"],
            "text": member["snapshot_json"]["text"], "evidence_provenance": descriptors[member["vector_id"]],
            "root_id": None, "work_id": None, "capture_sha256": None} for index, member in enumerate(members)]
        result = {"id": "result-a", "binding": {"paper_id": derived["paper_id"], "vector_id": derived["vector_id"],
            **{field: pin[field] for field in ("generation_id", "activation_event_id", "manifest_sha256")},
            **{field: descriptor[field] for field in ("content_sha256", "evidence_revision_id", "evidence_record_sha256",
                "parent_result_revision_id", "parent_result_sha256")}},
            "raw_record": deepcopy(derived["snapshot_json"]["materials_mentioned"][0]),
            "input_record_sha256": parent["row"]["input_record_sha256"]}
        package = make_package()
        package["corpus"] = {"id": "actual-disposable-sql-capture", "generation": generation_read_metadata(pin).model_dump(),
            "index_profile": pin["profile"], "index_resource": pin["resource"], "sources": sources, "results": [result]}
        package["cases"] = package["cases"][:2]
        aliases = {"a-methods": "frozen-0", "a-results": "frozen-1", "a-derived": "frozen-2"}
        for case in package["cases"]:
            for claim in case["expected"]["claims"]:
                claim["evidence_alternatives"] = [[aliases[identifier] for identifier in bundle] for bundle in claim["evidence_alternatives"]]
            for condition in case["expected"]["conditions"]:
                condition["source_ids"] = [aliases[identifier] for identifier in condition["source_ids"]]
                condition["raw_expectation"] = "Synthetic no detection down to 1 K; pressure unreported, not ambient."
        case_ids = {case["id"] for case in package["cases"]}
        package["case_reviews"] = [review for review in package["case_reviews"] if review["case_id"] in case_ids]
        for run in package["runs"]:
            run["observations"] = [observation for observation in run["observations"] if observation["case_id"] in case_ids]
            for observation in run["observations"]:
                for field in ("retrieved_source_ids", "selected_source_ids"):
                    observation[field] = [aliases[identifier] for identifier in observation[field]]
                for review in observation["judgments"]:
                    for claim in review["labels"]["claims"]:
                        claim["source_ids"] = [aliases[identifier] for identifier in claim["source_ids"]]
        package = reseal(package)
        yield {"package": package, "pin": pin, "members": members, "parent": parent, "receipts": receipts,
               "logical": logical, "meta": meta, "chunks": chunks}
    finally:
        index_vector_adapter.clear_disposable()


@pytest.mark.asyncio
async def test_actual_0060_0061_0062_capture_passes_without_inventing_source_roots(sql_capture):
    value = sql_capture["package"]
    result = value["corpus"]["results"][0]
    assert sql_capture["receipts"] == len(value["corpus"]["sources"]) == 5
    assert sql_capture["parent"]["intact"] is True
    assert result["input_record_sha256"] == input_record_sha256(result["raw_record"])
    assert result["raw_record"]["result_status"] == "not_detected"
    assert result["raw_record"]["minimum_temperature_k"] == "1 K"
    assert result["binding"]["parent_result_revision_id"] == sql_capture["parent"]["row"]["id"]
    assert result["binding"]["parent_result_sha256"] == sql_capture["parent"]["row"]["record_sha256"]
    assert value["corpus"]["generation"]["manifest_sha256"] == sql_capture["pin"]["manifest_sha256"]
    assert all(source["root_id"] is None and source["capture_sha256"] is None for source in value["corpus"]["sources"])
    audit = compare_package(value)
    assert audit["status"] == "structurally_consistent"
    assert audit["counts"]["sources"] == 5 and audit["counts"]["results"] == 1
    assert audit["catalogue_bindings_authenticated"] is audit["scientific_acceptance"] is False
    assert audit["split_audit"]["cases_with_missing_root_links"] == 2
    roots = audit["comparison"]["arms"]["run-candidate"]["splits"]["all"]["metrics"]["declared_root_recall_at_1"]
    assert roots["missing"] == 1 and roots["value"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation,reason", [("omitted_member", "incomplete_generation_manifest"),
    ("vector_hash", "incomplete_generation_manifest"), ("text", "source_content_mismatch"),
    ("raw_record", "raw_record_mismatch"), ("rehash_raw_record", "raw_parent_identity_mismatch"),
    ("parent_uuid", "raw_parent_identity_mismatch"), ("parent_hash", "result_evidence_mismatch")])
async def test_actual_capture_tampering_cannot_keep_original_frozen_bindings(sql_capture, mutation, reason):
    value = deepcopy(sql_capture["package"])
    result = value["corpus"]["results"][0]
    if mutation == "omitted_member":
        value["corpus"]["sources"].pop()
    elif mutation == "vector_hash":
        value["corpus"]["sources"][0]["vector_sha256"] = "0" * 64
    elif mutation == "text":
        value["corpus"]["sources"][0]["text"] += " Changed after capture."
    elif mutation in {"raw_record", "rehash_raw_record"}:
        result["raw_record"]["minimum_temperature_k"] = "0.1 K"
        if mutation == "rehash_raw_record":
            result["input_record_sha256"] = input_record_sha256(result["raw_record"])
    elif mutation == "parent_uuid":
        result["binding"]["parent_result_revision_id"] = str(uuid4())
        value["corpus"]["sources"][2]["evidence_provenance"]["parent_result_revision_id"] = result["binding"]["parent_result_revision_id"]
    else:
        result["binding"]["parent_result_sha256"] = "0" * 64
    with pytest.raises(ScientificEvaluationError, match=reason):
        validate_package(value)


@pytest.mark.asyncio
async def test_actual_retained_generation_capture_stays_valid_after_mutable_chunks_replace(sql_capture, monkeypatch):
    original = deepcopy(sql_capture["package"])
    await generations.write_generation(monkeypatch, logical_index=sql_capture["logical"],
        meta=sql_capture["meta"], count=3, label="later mutable replacement")
    async with get_session_factory()() as db:
        members = await index_generations.load_generation_members(db, generation_id=sql_capture["pin"]["generation_id"])
        hydrated = await index_retrieval.hydrate(db, sql_capture["pin"], [member["vector_id"] for member in members])
    assert len(members) == len(hydrated) == 5
    assert all("later mutable replacement" not in chunk.text for chunk in hydrated.values())
    assert validate_package(original)["status"] == "structurally_consistent"
    assert original == sql_capture["package"]


def _attach_actual_prompt(value, *, packing=False):
    """Build through the actual RAG input code, without creating an SDK client."""
    value = deepcopy(value)
    case = value["cases"][0]
    sources = {source["id"]: source for source in value["corpus"]["sources"]}
    for run in value["runs"]:
        observation = run["observations"][0]
        selected = [sources[identifier] for identifier in observation["selected_source_ids"]]
        packed = describe_selection([PackingCandidate(chunk_id=source["vector_id"], paper_id=source["paper_id"],
            source_snapshot_sha256=source["source_snapshot_sha256"], content_sha256=source["evidence_provenance"]["content_sha256"],
            chunk_kind=source["evidence_provenance"]["chunk_kind"], accepted_work_id=source["work_id"],
            role_hint="methods" if index == 0 else "results") for index, source in enumerate(selected)],
            [source["vector_id"] for source in selected]) if packing else [None] * len(selected)
        inputs = [rag.RagSourceInput(index=index, paper_id=sources[identifier]["paper_id"], title="Synthetic SQL capture",
            authors_short="Synthetic Fixture", year=None, section="Methods", text=sources[identifier]["text"],
            evidence_provenance=sources[identifier]["evidence_provenance"],
            source_snapshot_sha256=sources[identifier]["source_snapshot_sha256"], packing_info=packed[index - 1])
            for index, identifier in enumerate(observation["selected_source_ids"], 1)]
        prepared = build_request(model=MODEL, contents=rag.build_user_prompt(case["query"], inputs),
            system_instruction=rag.SYSTEM_PROMPT.format(language=case["language"]))
        observation["request_payload"] = json.loads(prepared._payload_json)
        observation["request_sha256"] = prepared.request_sha256
    return reseal(value)


@pytest.mark.asyncio
async def test_real_rag_request_builder_binds_sql_captured_source_text_and_question(sql_capture):
    value = _attach_actual_prompt(sql_capture["package"])
    audit = compare_package(value)
    assert audit["counts"]["retained_request_payloads"] == 2
    for run in value["runs"]:
        observation = run["observations"][0]
        assert observation["request_sha256"] == hashlib.sha256(
            json.dumps(observation["request_payload"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    assert audit["execution_authenticated"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation,reason", [("question", "request_question_mismatch"), ("model", "request_model_mismatch"),
    ("source_text", "request_source_content_mismatch"), ("extra_config", "unsupported_request_profile")])
async def test_retained_request_rehash_does_not_hide_mismatched_actual_inputs(sql_capture, mutation, reason):
    value = _attach_actual_prompt(sql_capture["package"])
    run = value["runs"][1]
    payload = run["observations"][0]["request_payload"]
    if mutation == "model":
        payload["model"] = "gemini-other"
    elif mutation == "extra_config":
        payload["generation_config"]["temperature"] = 0.9
    else:
        prompt = payload["contents"][0]["parts"][0]["text"]
        target = value["cases"][0]["query"] if mutation == "question" else value["corpus"]["sources"][0]["text"]
        payload["contents"][0]["parts"][0]["text"] = prompt.replace(target, "Different unbound input", 1)
    value = reseal(value)
    with pytest.raises(ScientificEvaluationError, match=reason):
        validate_package(value)


@pytest.mark.asyncio
async def test_review_artifact_ids_cannot_be_reused_across_distinct_runs(sql_capture):
    value = deepcopy(sql_capture["package"])
    value["runs"][1]["observations"][0]["judgments"][0]["id"] = value["runs"][0]["observations"][0]["judgments"][0]["id"]
    with pytest.raises(ScientificEvaluationError, match="duplicate_global_review_id"):
        validate_package(reseal(value))


def _edit_first_prompt_entry(value, mutate):
    value = deepcopy(value)
    payload = value["runs"][1]["observations"][0]["request_payload"]
    prompt = payload["contents"][0]["parts"][0]["text"]
    start, end = "<untrusted_sources_json>\n", "\n</untrusted_sources_json>\n\n<user_question>\n"
    source_json, suffix = prompt[len(start):].split(end, 1)
    entries = json.loads(source_json)
    mutate(entries[0])
    payload["contents"][0]["parts"][0]["text"] = start + json.dumps(entries, ensure_ascii=False) + end + suffix
    return reseal(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value,reason", [("scientific_acceptance", True, "unsupported_request_source_profile"),
    ("year", True, "invalid_request_source_metadata"), ("material_evidence", {"approved": True}, "invalid_request_source_metadata")])
async def test_resealed_request_cannot_smuggle_extra_authority_or_malformed_source_metadata(sql_capture, field, value, reason):
    package = _edit_first_prompt_entry(_attach_actual_prompt(sql_capture["package"]), lambda entry: entry.update({field: value}))
    with pytest.raises(ScientificEvaluationError, match=reason):
        validate_package(package)


@pytest.mark.asyncio
@pytest.mark.parametrize("declared_work", [False, True])
async def test_actual_packing_request_is_bound_without_authenticating_declared_work(sql_capture, declared_work):
    package = deepcopy(sql_capture["package"])
    if declared_work:
        # This is an explicit fixture declaration, not an accepted SQL mapping.
        # Passing portable consistency must still leave catalogue authority false.
        for source in package["corpus"]["sources"]:
            source["work_id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    package = _attach_actual_prompt(package, packing=True)
    audit = compare_package(package)
    assert audit["counts"]["retained_request_payloads"] == 2
    assert audit["catalogue_bindings_authenticated"] is audit["source_roots_authenticated"] is False
    assert audit["scientific_acceptance"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value,reason", [
    ("scientific_acceptance", True, "invalid_retained_request"),
    ("scientific_acceptance", 0, "invalid_retained_request"),
    ("position", True, "invalid_retained_request"),
    ("position", 2, "request_packing_source_mismatch"),
    ("chunk_id", "unbound-chunk", "request_packing_source_mismatch"),
    ("source_snapshot_sha256", "0" * 64, "request_packing_source_mismatch"),
    ("source_group_id", "src:" + "0" * 64, "request_packing_group_mismatch"),
    ("diversity_group_id", "div:" + "0" * 64, "request_packing_group_mismatch"),
    ("group_basis", "accepted_work_mapping", "request_packing_group_mismatch"),
])
async def test_rehashed_packing_metadata_cannot_change_identity_or_claim_authority(sql_capture, field, value, reason):
    package = _edit_first_prompt_entry(_attach_actual_prompt(sql_capture["package"], packing=True),
        lambda entry: entry["packing_info"].update({field: value}))
    with pytest.raises(ScientificEvaluationError, match=reason):
        validate_package(package)


@pytest.mark.asyncio
async def test_changed_declared_work_cannot_keep_an_old_packing_group(sql_capture):
    package = deepcopy(sql_capture["package"])
    for source in package["corpus"]["sources"]:
        source["work_id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    package = _attach_actual_prompt(package, packing=True)
    for source in package["corpus"]["sources"]:
        source["work_id"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    with pytest.raises(ScientificEvaluationError, match="request_packing_group_mismatch"):
        validate_package(reseal(package))
