"""Actual ingestion-to-generation fixtures; import only behind API test guard."""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ingestion"))

from ingestion.chunk.chunker import count_tokens  # noqa: E402
from ingestion.embedding_contract import (  # noqa: E402
    LOCAL_DOCUMENT_COUNT_METHOD,
    LOCAL_DOCUMENT_INPUT_LIMIT,
    LOCAL_DOCUMENT_REQUEST_LIMIT,
    validate_embedding_response,
)
from ingestion.generation_candidates import prepare_generation_items  # noqa: E402
from ingestion.index import indexer  # noqa: E402
from ingestion.models import ApsArticleMeta, Chunk  # noqa: E402

from models.db import get_session_factory  # noqa: E402
from services import index_generations, index_vector_adapter  # noqa: E402
from services.rag_evidence import CURRENT_FACT_RENDERER_VERSION  # noqa: E402

RESOURCE = {
    "backend": "disposable", "project": "sclib-fixture", "location": "test-region",
    "index_resource": "projects/sclib-fixture/locations/test-region/indexes/fixture-index",
    "endpoint_resource": "projects/sclib-fixture/locations/test-region/indexEndpoints/fixture-endpoint",
    "deployed_index_id": "fixture-deployment", "distance_measure": "COSINE_DISTANCE", "feature_norm": "NONE",
}


def corpus(*, count=5, meta=None, label="old", parser_version="synthetic-parser/1"):
    if meta is None:
        meta = ApsArticleMeta(doi="10.0000/IndexGeneration." + uuid4().hex,
                              title="Synthetic superconductivity generation", authors=["Synthetic Fixture"], abstract="Synthetic abstract.")
    record = {"formula": "Nb", "result_status": "not_detected", "minimum_temperature_k": "1 K",
              "knowledge_origin": "Observed", "source_role": "primary", "extractor_version": "synthetic/1"}
    chunks = []
    for index in range(count):
        value = f"Synthetic superconductivity {label} snapshot {index}: no transition detected down to 1 K."
        count_value = count_tokens(value)
        vector, metadata = validate_embedding_response([value], SimpleNamespace(embeddings=[SimpleNamespace(
            values=[0.125 + index / 1000] * 768,
            statistics=SimpleNamespace(truncated=False, token_count=float(count_value)))]),
            model="text-embedding-005", dimension=768, task_type="RETRIEVAL_DOCUMENT", local_counts=[count_value],
            local_count_method=LOCAL_DOCUMENT_COUNT_METHOD, local_input_limit=LOCAL_DOCUMENT_INPUT_LIMIT,
            local_request_limit=LOCAL_DOCUMENT_REQUEST_LIMIT)[0]
        chunks.append(Chunk(id=f"{meta.paper_id}_fact_{index:03d}", paper_id=meta.paper_id, chunk_index=index,
            section="Facts", text=value, token_count=count_value, embedding=vector, embedding_provenance=metadata,
            materials_mentioned=[deepcopy(record)], parser_version=parser_version,
            evidence_candidate={"version": "rag-evidence/1.0.0", "chunk_kind": "derived_fact", "parent_record": deepcopy(record),
                "extraction_version": "synthetic/1", "rendering_version": CURRENT_FACT_RENDERER_VERSION}))
    return meta, record, chunks


async def write_generation(monkeypatch, *, logical_index, count=5, meta=None, label="old",
                           parser_version="synthetic-parser/1", resource=None, generation_id=None,
                           fail_after_stage=False):
    """Real Paper/Chunk/0060/0061/0062 in one SQL transaction; no cloud calls."""
    resource = deepcopy(RESOURCE if resource is None else resource)
    identifier = str(uuid4()) if generation_id is None else generation_id
    meta, record, chunks = corpus(count=count, meta=meta, label=label, parser_version=parser_version)
    monkeypatch.setattr(indexer, "_session_factory", get_session_factory)
    monkeypatch.setattr(indexer, "_index", lambda: (_ for _ in ()).throw(AssertionError("Unexpected cloud IO")))
    result = {}

    async def stager(session, selected):
        items = await prepare_generation_items(session, selected)
        result.update(await index_generations.stage_generation(session, generation_id=identifier,
            items=items, resource=resource, logical_index=logical_index, dry_run=False))
        if fail_after_stage:
            raise RuntimeError("Synthetic interrupted SQL generation staging")

    await indexer.upsert_aps_paper_with_chunks(meta, chunks, [record], generation_stager=stager)
    return meta, chunks, result


async def publish_and_activate(db, pin, *, expected_event_id=None, action="promote"):
    members = await index_generations.load_generation_members(db, generation_id=pin["generation_id"])
    publication = index_vector_adapter.publish(pin, members)
    observation = index_vector_adapter.observe(pin, members)
    validation = await index_generations.record_validation(db, generation_id=pin["generation_id"], observation=observation, dry_run=False)
    assert validation["outcome"] == "validated"
    result = await index_generations.activate_generation(db, generation_id=pin["generation_id"],
        validation_id=validation["validation_id"], expected_event_id=expected_event_id,
        idempotency_key=uuid4().hex, action=action, dry_run=False)
    await db.commit()
    return result, publication, validation
