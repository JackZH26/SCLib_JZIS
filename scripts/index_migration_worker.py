"""Capability-only, fixed synthetic SQL/index migration measurement.

No pytest fixtures, arbitrary targets, provider clients or production credentials
are accepted. The parent alone starts/stops services and publishes the report.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import time
from collections import Counter
from contextlib import asynccontextmanager, contextmanager
from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from index_migration_protocol import (
    AUTHORITY,
    CHECKS,
    PHASES,
    QUERY_IDS,
    VERSION,
    canonical,
    digest,
    require,
    validate_migration_report,
)

REPO = Path(__file__).resolve().parents[1]
PAPERS = ["arxiv:2609.00011", "arxiv:2609.00012"]
QUERIES = ["Summarize this explicitly synthetic corpus.", "Compare the synthetic material passages.",
           "What limitations are recorded in these synthetic sources?"]


def _ms(start):
    return round((time.perf_counter() - start) * 1000, 6)


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _resource(run_id):
    return {"backend": "disposable", "project": "sclib-fixture", "location": "test-region",
            "index_resource": "projects/sclib-fixture/locations/test-region/indexes/migration-" + run_id,
            "endpoint_resource": "projects/sclib-fixture/locations/test-region/indexEndpoints/migration-" + run_id,
            "deployed_index_id": "migration-" + run_id, "distance_measure": "COSINE_DISTANCE", "feature_norm": "NONE"}


@asynccontextmanager
async def _session(factory, *, readonly=False):
    import sqlalchemy as sa
    async with factory() as db:
        async with db.begin():
            await db.execute(sa.text("SET TRANSACTION ISOLATION LEVEL " +
                                    ("REPEATABLE READ, READ ONLY" if readonly else "SERIALIZABLE")))
            await db.execute(sa.text("SET LOCAL TimeZone='UTC'"))
            await db.execute(sa.text("SET LOCAL statement_timeout='10000ms'"))
            yield db


@contextmanager
def _ingestion_runtime(factory):
    """Scoped known-runtime wiring, never inherited ingestion/cloud settings."""
    import ingestion.generation_candidates as candidates
    from ingestion.chunk import chunker
    from ingestion.generation_candidates import (
        get_settings as original_candidates_settings,
    )
    from ingestion.index import indexer

    original_factory = indexer._session_factory
    original_chunk_settings = chunker.get_settings
    settings = SimpleNamespace(chunk_size_tokens=512, chunk_overlap_tokens=64)
    indexer._session_factory = lambda: factory
    chunker.get_settings = lambda: settings
    candidates.get_settings = lambda: settings
    try:
        yield
    finally:
        indexer._session_factory = original_factory
        chunker.get_settings = original_chunk_settings
        candidates.get_settings = original_candidates_settings


async def _ingest(specs):
    from ingestion.chunk.chunker import chunk_paper
    from ingestion.embedding_contract import (
        LOCAL_DOCUMENT_COUNT_METHOD,
        LOCAL_DOCUMENT_INPUT_LIMIT,
        LOCAL_DOCUMENT_REQUEST_LIMIT,
        validate_embedding_response,
    )
    from ingestion.index.indexer import upsert_paper_with_chunks
    from ingestion.models import PaperMetadata, ParsedPaper, Section

    chunks = []
    for spec in specs:
        meta = PaperMetadata(arxiv_id=spec["arxiv_id"], title=spec["title"], authors=spec["authors"],
            abstract=spec["abstract"], date_submitted=date.fromisoformat(spec["date_submitted"]),
            categories=["cond-mat.supr-con"], primary_category="cond-mat.supr-con")
        require(meta.paper_id == spec["paper_id"])
        parsed = ParsedPaper(meta=meta, sections=[Section(**value) for value in spec["sections"]],
                             parser_version=spec["parser_version"])
        selected = chunk_paper(parsed)
        require(len(selected) == len(spec["sections"]))
        for number, chunk in enumerate(selected):
            # This explicit synthetic completion exercises the real strict
            # receipt validator. Provider tokens below are fixture observations,
            # never measured billing or embedding quality.
            vector, metadata = validate_embedding_response([chunk.text], {"embeddings": [{
                "values": [0.125 + number / 1024] * 768,
                "statistics": {"truncated": False, "token_count": float(chunk.token_count)},
            }]}, model="text-embedding-005", dimension=768, task_type="RETRIEVAL_DOCUMENT",
                local_counts=[chunk.token_count], local_count_method=LOCAL_DOCUMENT_COUNT_METHOD,
                local_input_limit=LOCAL_DOCUMENT_INPUT_LIMIT, local_request_limit=LOCAL_DOCUMENT_REQUEST_LIMIT)[0]
            chunk.embedding, chunk.embedding_provenance = vector, metadata
        await upsert_paper_with_chunks(parsed, selected, deepcopy(spec["raw_records"]))
        chunks.extend(selected)
    return chunks


async def _stage(factory, chunks, *, resource, logical_index):
    from ingestion.generation_candidates import prepare_generation_items
    from services.index_generations import stage_generation
    async with _session(factory) as db:
        items = await prepare_generation_items(db, chunks)
        return await stage_generation(db, generation_id=str(uuid4()), items=items,
                                      resource=resource, logical_index=logical_index, dry_run=False)


async def _members(factory, pin):
    from services.index_generations import load_generation_members
    async with _session(factory, readonly=True) as db:
        return await load_generation_members(db, generation_id=pin["generation_id"])


async def _active(factory, logical_index):
    from services.index_generations import load_active_generation
    async with _session(factory, readonly=True) as db:
        return await load_active_generation(db, logical_index=logical_index)


async def _activate(factory, pin, members, *, logical_index, predecessor, action, key):
    from services import index_generations as generations
    from services import index_vector_adapter as adapter
    if action == "rollback":
        prior = adapter.observe(pin, members)
        require(prior["full_inventory_observed"] is True and len(prior["vectors"]) == len(members) == 7
                and generations.manifest_sha256(prior["vectors"]) == pin["manifest_sha256"])
        plan = adapter.repair_plan(pin, members, prior)
        require(not plan["missing_ids"] and not plan["hash_mismatch_ids"] and not plan["observed_orphan_ids"]
                and plan["declared_members_complete"] is True)
    publication = adapter.publish(pin, members)
    observation = adapter.observe(pin, members)
    require(publication["acknowledged_count"] + publication["already_present_count"] == len(members))
    if action == "rollback":
        require(publication["acknowledged_count"] == 0 and publication["already_present_count"] == 7)
    async with _session(factory) as db:
        validation = await generations.record_validation(db, generation_id=pin["generation_id"],
                                                         observation=observation, dry_run=False)
        require(validation["outcome"] == "validated")
        await generations.activate_generation(db, generation_id=pin["generation_id"],
            validation_id=validation["validation_id"], expected_event_id=predecessor,
            idempotency_key=key, action=action, dry_run=False)
    # The returned pin comes from a fresh SQL pointer read, not a predicted ID.
    return await _active(factory, logical_index)


async def _activation_snapshot(factory, logical_index):
    import sqlalchemy as sa
    observed = {}
    async with _session(factory, readonly=True) as db:
        for table in ("index_activation_events", "index_active_pointer", "index_generation_epoch",
                      "research_integrity_epoch", "source_lifecycle_epoch"):
            condition = "WHERE logical_index=:logical" if table in {"index_activation_events", "index_active_pointer"} else ""
            rows = list((await db.execute(sa.text(f"SELECT to_jsonb(t)::text FROM {table} t {condition} "
                "ORDER BY to_jsonb(t)::text COLLATE \"C\""), {"logical": logical_index})).scalars())
            require(len(rows) <= 20 and sum(len(row.encode()) for row in rows) <= 65536)
            observed[table] = rows
    return digest(observed), len(observed["index_activation_events"])


async def _promote_with_transaction_probes(factory, pin, members, *, logical_index, predecessor):
    from services import index_generations as generations
    from services import index_vector_adapter as adapter
    publication = adapter.publish(pin, members)
    async with _session(factory) as db:
        validation = await generations.record_validation(db, generation_id=pin["generation_id"],
            observation=adapter.observe(pin, members), dry_run=False)
        require(validation["outcome"] == "validated")
    args = {"generation_id": pin["generation_id"], "validation_id": validation["validation_id"],
            "expected_event_id": predecessor, "idempotency_key": logical_index + ":after",
            "action": "promote", "dry_run": False}
    observations = {}
    before_sha, before_count = await _activation_snapshot(factory, logical_index)
    async with _session(factory) as db:
        await generations.activate_generation(db, **args)
        # The service's internal savepoint succeeds; the caller then rolls back.
        await db.rollback()
    after_sha, after_count = await _activation_snapshot(factory, logical_index)
    require(before_sha == after_sha and before_count == after_count)
    observations["outer_rollback"] = {"before_sha256": before_sha, "after_sha256": after_sha,
        "before_event_count": before_count, "after_event_count": after_count}
    async with _session(factory) as db:
        await generations.activate_generation(db, **args)
    before_sha, before_count = await _activation_snapshot(factory, logical_index)
    async with _session(factory) as db:
        await generations.activate_generation(db, **args)
    after_sha, after_count = await _activation_snapshot(factory, logical_index)
    require(before_sha == after_sha and before_count == after_count)
    observations["idempotent_replay"] = {"before_sha256": before_sha, "after_sha256": after_sha,
        "before_event_count": before_count, "after_event_count": after_count}
    return await _active(factory, logical_index), observations, publication


@contextmanager
def _forbid_providers():
    from ingestion.index import indexer
    from services import genai_client, index_vector_adapter
    counter = {"attempts": 0}
    def forbidden(*_args, **_kwargs):
        counter["attempts"] += 1
        raise RuntimeError("index_migration_provider_forbidden")
    targets = [(genai_client, "client"), (genai_client, "embedding_client"), (index_vector_adapter, "_embed"),
               (index_vector_adapter, "_public_clients"), (index_vector_adapter, "_public_match_client"),
               (indexer, "_index")]
    originals = [(module, name, getattr(module, name)) for module, name in targets]
    for module, name in targets:
        setattr(module, name, forbidden)
    try:
        yield counter
    finally:
        for module, name, value in originals:
            setattr(module, name, value)


async def _query(factory, pin, members):
    from services import index_retrieval as retrieval
    from services.index_vector_adapter import query
    expected = sorted(member["vector_id"] for member in members)
    samples, summary = [], None
    for identifier, question in zip(QUERY_IDS, QUERIES, strict=True):
        start = time.perf_counter()
        hits = query(pin, question, top_k=20)
        async with _session(factory, readonly=True) as db:
            verified = await retrieval.verified_vector_hits(db, pin, hits)
            ids = [identifier for identifier, _ in verified]
            hydrated = await retrieval.hydrate(db, pin, ids)
            descriptors = await retrieval.resolve_evidence(db, list(hydrated.values()))
            require(sorted(ids) == expected == sorted(hydrated))
            observed = []
            for vector_id in sorted(hydrated):
                chunk = hydrated[vector_id]
                require(chunk.paper_id in PAPERS and chunk.member["generation_id"] == pin["generation_id"])
                descriptor = descriptors[vector_id]
                require(descriptor["chunk_kind"] == "original_passage" and descriptor["currentness"] == "current")
                observed.append({"vector_id": vector_id, "paper_id": chunk.paper_id,
                    "content_sha256": _sha(chunk.text.encode("utf-8")), "evidence": descriptor,
                    "member_sha256": chunk.member["record_sha256"], "parser_version": chunk.member["parser_version"]})
        captured = digest(observed)
        require(summary is None or captured == summary)
        summary = captured
        samples.append({"query_id": identifier, "latency_ms": _ms(start), "hit_count": len(hits),
                        "hydrated_count": len(hydrated)})
    return {"generation_id": pin["generation_id"], "activation_event_id": pin["activation_event_id"],
            "hit_ids": expected, "hydration_sha256": summary, "samples": samples}


async def _save_answer(factory, pin, members):
    import sqlalchemy as sa
    from models.db import Base
    from models.evidence_packing import PackingCandidate
    from models.index_read import generation_read_metadata
    from models.search import AskRequest, AskResponse, AskSource
    from services import (
        answer_evidence,
        evidence_packing,
        index_retrieval,
        retrieval_currentness,
    )
    from services.authors import short as authors_short

    # One actual selected passage from each measured source paper. This is a
    # service/SQL receipt measurement, not an HTTP or LLM answer-quality test.
    selected_ids = [min(member["vector_id"] for member in members if member["paper_id"] == paper) for paper in PAPERS]
    async with _session(factory, readonly=True) as db:
        by_id = await index_retrieval.hydrate(db, pin, selected_ids)
        chunks = [by_id[identifier] for identifier in selected_ids]
        evidence = await index_retrieval.resolve_evidence(db, chunks)
    candidates = [PackingCandidate(chunk_id=chunk.id, paper_id=chunk.paper_id,
        source_snapshot_sha256=chunk.member["source_snapshot_sha256"], content_sha256=chunk.member["content_sha256"],
        chunk_kind="original_passage") for chunk in chunks]
    # This fixed evidence plan is not a provider-token/byte-budget measurement.
    plan = evidence_packing.pack_evidence(candidates,
        cost=lambda ids: len(canonical({"question": QUERIES[0], "sources": [by_id[i].text for i in ids]})),
        byte_budget=262144, max_chunks=2)
    chunks = [by_id[item.chunk_id] for item in plan.selected]
    require(len(chunks) == 2 and {chunk.paper_id for chunk in chunks} == set(PAPERS))
    sources, pins = [], []
    for item, chunk in zip(plan.selected, chunks, strict=True):
        paper = index_retrieval.attribution(chunk)
        snippet = " ".join(chunk.text.split())
        if len(snippet) > 280:
            snippet = snippet[:279].rstrip() + "…"
        sources.append(AskSource(index=item.position, paper_id=paper.id, arxiv_id=paper.arxiv_id,
            title=paper.title, authors_short=authors_short(paper.authors), year=paper.date_submitted.year,
            section=chunk.section, snippet=snippet, evidence_provenance=evidence[chunk.id], packing_info=item))
        pins.append(retrieval_currentness.selection_pin(chunk, material_evidence=[], source_review={}, evidence=evidence[chunk.id]))
    request = AskRequest(question=QUERIES[0], max_sources=2, language="en")
    response = AskResponse(answer="Synthetic retained passages [1] [2]; no scientific assessment was performed.",
        sources=sources, tokens_used=0, query_time_ms=0, retrieval_generation=generation_read_metadata(pin),
        evidence_packing=evidence_packing.public_summary(plan))
    captured = answer_evidence.capture_inputs(request=request, generation_pin=pin, sources=tuple(sources),
        chunks=tuple(chunks), selection_pins=tuple(pins))
    prepared = answer_evidence.finish_capture(captured, response)
    require({item["paper_id"] for item in prepared.document["bindings"]["items"]} == set(PAPERS)
            and len(prepared.document["bindings"]["items"]) == 2)
    identifier, user = uuid4(), uuid4()
    async with _session(factory) as db:
        await db.execute(Base.metadata.tables["users"].insert().values(id=user,
            email="index-migration-" + user.hex + "@example.test", name="Synthetic receipt owner",
            is_active=True, email_verified=True))
        fields = await answer_evidence.receipt_fields(db, prepared)
        await db.execute(Base.metadata.tables["ask_history"].insert().values(id=identifier, user_id=user,
            question=request.question, answer=response.answer, sources=[source.model_dump(mode="json") for source in sources],
            tokens_used=0, latency_ms=0, language="en", evidence_receipt_version=answer_evidence.VERSION))
        for key in ("generation_id", "activation_event_id"):
            fields[key] = UUID(fields[key]) if fields[key] else None
        await db.execute(sa.insert(Base.metadata.tables["answer_evidence_receipts"]).values(history_id=identifier, **fields))
    return identifier


async def _freeze_release(factory, specs, run_id):
    from models.db import Base
    from services import research_freeze as freeze
    from services.research_release_manifest import (
        REVIEW_VERSION,
        processing_review_payload,
    )

    artifacts = {}
    async with _session(factory) as db:
        async def add(table, **values):
            target = Base.metadata.tables[table]
            return dict((await db.execute(target.insert().values(**values).returning(target))).mappings().one())
        async def artifact(kind, body, schema="index-migration-synthetic/1", metadata=None):
            payload = canonical(body)
            artifacts[_sha(payload)] = payload
            return (await add("evidence_artifacts", kind=kind, schema_version=schema,
                source="synthetic-index-migration", source_version=VERSION, record_sha256=digest(body),
                bytes_sha256=_sha(payload), hash_status="verified", access="restricted", metadata=metadata or {"synthetic": True}))["id"]
        policies = [await artifact("policy", {"synthetic": True, "role": role}) for role in ("task", "features")]
        snapshot = (await add("source_snapshots", dataset_version="migration-" + run_id,
            schema_version="index-migration-synthetic/1", material_count=2, paper_count=2))["id"]
        dataset = (await add("ml_dataset_snapshots", source_snapshot_id=snapshot, name="Synthetic migration dependency capsule",
            version=run_id, label_policy_version="index-migration-synthetic/1", feature_schema_version="index-migration-synthetic/1",
            split_ruleset_version="index-migration-synthetic/1", row_count=2))["id"]
        roots = []
        for number, spec in enumerate(specs):
            raw = spec["raw_records"][0]
            material = "index-migration-material:" + run_id + ":" + str(number)
            await add("materials", id=material, formula=raw["formula"], formula_normalized=raw["formula"],
                      records=[{"paper_id": spec["paper_id"], "synthetic": True}], total_papers=1)
            source = await artifact("literature_locator", {"synthetic": True, "paper_id": spec["paper_id"],
                "raw_record": raw, "source_section": spec["sections"][0]})
            state = (await add("material_states", material_id=material, resolution="source_scoped",
                condition_schema_version="index-migration-synthetic/1", pressure_status="not_reported", temperature_role="unknown",
                conditions={"synthetic": True}, context_sha256=digest({"synthetic": True, "material": material}),
                source_artifact_id=source))["id"]
            event = (await add("research_events", material_id=material, state_id=state, event_type="measurement",
                knowledge_origin="Observed", record_sha256=digest({"synthetic": True, "event": material})))["id"]
            await add("event_evidence", event_id=event, link_type="source", artifact_id=source, locator={"section": 0})
            claim = (await add("material_claims", material_id=material, paper_id=spec["paper_id"], source_snapshot_id=snapshot,
                event_id=event, result_key="synthetic-migration-result", interpretation_revision=1, source_record_hash=digest(raw),
                value_relation="exact", value_kelvin=39 if number == 0 else 9.2, result_status="observed",
                source_kind="prose", extractor_version="index-migration-synthetic/1", raw_record=raw))["id"]
            membership = (await add("snapshot_event_memberships", snapshot_id=snapshot, event_id=event, event_revision=1,
                source_occurrence_key="synthetic-migration:" + str(number), locator={"section": 0},
                source_record_sha256=digest(raw), result_manifest_sha256=digest({"synthetic": True, "claim": str(claim)})))["id"]
            roots.append({"table": "snapshot_event_memberships", "row_id": str(membership)})
            await add("ml_examples", dataset_snapshot_id=dataset, example_key="synthetic-" + str(number), claim_id=claim,
                material_id=material, split="train", task_type="tc_regression", label_data={"synthetic_pending": True},
                work_group="unresolved:" + spec["paper_id"], material_group=material, duplicate_group=spec["paper_id"],
                assignment_hash=digest({"synthetic": True, "example": number}))
        args = {"dataset_id": dataset, "policy_artifact_ids": policies, "source_roots": roots, "artifact_bytes": artifacts}
        preview = await freeze.preview_research_release(db, **args)
        document = processing_review_payload(preview["manifest"])
        review = await artifact("review", document, REVIEW_VERSION, {"shadow_freeze_review": document})
        release = await freeze.freeze_research_release(db, **args, review_artifact_id=review, dry_run=False)
        require({row["row_id"] for row in release["manifest"]["rows"] if row["table"] == "papers"} == set(PAPERS))
    return release, artifacts


async def _retention(factory, history_id, release, artifacts):
    import sqlalchemy as sa
    from models.db import Base
    from services.answer_evidence import verify_historical
    from services.research_freeze import inspect_research_release
    async with _session(factory, readonly=True) as db:
        receipt = Base.metadata.tables["answer_evidence_receipts"]
        stored = dict((await db.execute(sa.select(receipt).where(receipt.c.history_id == history_id))).mappings().one())
        verified = await verify_historical(db, stored)
        inspection = await inspect_research_release(db, release_id=release["release_id"],
            expected_manifest_sha256=release["manifest_sha256"], artifact_bytes=artifacts)
        rows = {}
        for table, condition, parameter in (("ask_history", "id", history_id),
                ("answer_evidence_receipts", "history_id", history_id),
                ("research_releases", "id", UUID(release["release_id"])),
                ("research_release_pins", "release_id", UUID(release["release_id"]))):
            rows[table] = list((await db.execute(sa.text(f"SELECT to_jsonb(t)::text FROM {table} t "
                f"WHERE {condition}=:id ORDER BY to_jsonb(t)::text COLLATE \"C\""), {"id": parameter})).scalars())
            require(1 <= len(rows[table]) <= 1000 and sum(len(text.encode()) for text in rows[table]) <= 8 * 1024 * 1024)
    return {"answer_receipt_sha256": verified["record_sha256"], "answer_row_sha256": digest(
        rows["ask_history"] + rows["answer_evidence_receipts"]), "release_manifest_sha256": inspection["manifest_sha256"],
        "release_row_sha256": digest(rows["research_releases"]), "release_pins_sha256": digest(rows["research_release_pins"]),
        "release_pin_count": len(rows["research_release_pins"]), "artifact_inventory_sha256": digest(
            [{"sha256": key, "size_bytes": len(payload)} for key, payload in sorted(artifacts.items())]),
        "measured_paper_pin_count": len([row for row in inspection["manifest"]["rows"] if row["table"] == "papers"]),
        "answer_generation_id": verified["bindings"]["generation_id"],
        "answer_activation_event_id": verified["bindings"]["activation_event_id"]}


def _generation_summary(pin, members, chunks):
    inventory = [{key: member[key] for key in ("vector_id", "content_sha256", "vector_sha256", "record_sha256",
                                               "evidence_revision_id", "evidence_record_sha256", "parser_version")}
                 for member in sorted(members, key=lambda item: item["vector_id"])]
    return {**{key: pin[key] for key in ("generation_id", "activation_event_id", "manifest_sha256")},
        "member_inventory_sha256": digest(inventory), "member_count": len(members),
        "paper_counts": dict(Counter(member["paper_id"] for member in members)),
        "vector_bytes": sum(len(member["vector_bytes"]) for member in members),
        "local_document_tokens": sum(chunk.token_count for chunk in chunks)}


async def measure_migration(capability):
    """Run only on the exact already-migrated parent-owned disposable database."""
    from test_safety import validate_test_environment
    current = validate_test_environment(database_url=capability.database_url, redis_url=capability.redis_url)
    require(current.run_id == capability.run_id and current.manifest["root"] == capability.manifest["root"])
    sys.path.insert(0, str(REPO / "ingestion"))
    import sqlalchemy as sa
    from research_restore_worker import _engine
    from sqlalchemy.ext.asyncio import async_sessionmaker
    engine = await _engine(capability)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with _session(factory, readonly=True) as db:
            for table in ("papers", "index_generations", "research_releases", "ask_history"):
                require(await db.scalar(sa.text(f"SELECT count(*) FROM {table}")) == 0)
            schema = (await db.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one()
        return await _measure_fixture(factory, capability.run_id, schema)
    finally:
        await engine.dispose()


async def _measure_fixture(factory, run_id, schema_revision):
    """Internal implementation; only entrypoint performs capability/empty-DB admission.

    Native tests call this below their existing guarded schema setup. This does
    not create a CLI/API option for a caller-specified database or corpus.
    """
    import sqlalchemy as sa
    from index_migration_corpus import migration_specs
    from services import index_generations as generations
    from services import index_vector_adapter as adapter

    specs = migration_specs()
    require(specs["chunk_size_tokens"] == 512 and specs["chunk_overlap_tokens"] == 64)
    logical = "migration-" + run_id
    resource = _resource(run_id)
    transport = adapter.register_disposable(resource)
    timings, queries, retained = {}, {}, {}
    provider_guard = _forbid_providers()
    provider_counter = provider_guard.__enter__()
    try:
        async with _session(factory, readonly=True) as db:
            require(await db.scalar(sa.text("SELECT count(*) FROM papers WHERE id IN (:a,:b)"),
                {"a": PAPERS[0], "b": PAPERS[1]}) == 0)
        with _ingestion_runtime(factory):
            started = time.perf_counter()
            before_chunks = await _ingest(specs["before"])
            timings["ingest_before"] = _ms(started)
            started = time.perf_counter()
            before = await _stage(factory, before_chunks, resource=resource, logical_index=logical)
            timings["stage_before"] = _ms(started)
            before_members = await _members(factory, before)
            require(len(before_members) == 7 and await _active(factory, logical) is None)
            started = time.perf_counter()
            before = await _activate(factory, before, before_members, logical_index=logical,
                                     predecessor=None, action="promote", key=logical + ":before")
            timings["publish_before"] = _ms(started)
            queries["before"] = await _query(factory, before, before_members)
            started = time.perf_counter()
            history = await _save_answer(factory, before, before_members)
            release, artifacts = await _freeze_release(factory, specs["before"], run_id)
            retained["before"] = await _retention(factory, history, release, artifacts)
            timings["retain_history"] = _ms(started)
            started = time.perf_counter()
            after_chunks = await _ingest(specs["after"])
            timings["ingest_after"] = _ms(started)
            started = time.perf_counter()
            after = await _stage(factory, after_chunks, resource=resource, logical_index=logical)
            timings["stage_after"] = _ms(started)
        after_members = await _members(factory, after)
        require(len(after_members) == 5 and await _active(factory, logical) == before)
        started = time.perf_counter()
        # Interrupt the actual publish call after its first real transport write.
        # Readback, reconciliation and recovery still use the original adapter.
        original_upsert = transport.upsert
        def interrupted_upsert(points, deadline):
            original_upsert(points[:1], deadline)
            raise RuntimeError("synthetic_partial_publication")
        publication_failed = False
        transport.upsert = interrupted_upsert
        try:
            adapter.publish(after, after_members)
        except adapter.IndexVectorError:
            publication_failed = True
        finally:
            transport.upsert = original_upsert
        require(publication_failed)
        observation = adapter.observe(after, after_members)
        repair_before = digest(transport.points)
        sql_before, _ = await _activation_snapshot(factory, logical)
        repair = adapter.repair_plan(after, after_members, observation)
        sql_after, _ = await _activation_snapshot(factory, logical)
        repair_after = digest(transport.points)
        require(repair_before == repair_after and sql_before == sql_after and len(repair["missing_ids"]) == 4
                and not repair["hash_mismatch_ids"] and not repair["observed_orphan_ids"]
                and not repair["delete_candidate_ids"] and repair["dry_run"] is True
                and repair["upsert_candidate_ids"] == repair["pending_known_ids"] == repair["missing_ids"]
                and repair["promotion_ready"] is False and repair["declared_members_complete"] is False)
        async with _session(factory) as db:
            rejected = await generations.record_validation(db, generation_id=after["generation_id"], observation=observation, dry_run=False)
        require(rejected["outcome"] == "rejected")
        refused = False
        async with _session(factory) as db:
            try:
                await generations.activate_generation(db, generation_id=after["generation_id"], validation_id=rejected["validation_id"],
                    expected_event_id=before["activation_event_id"], idempotency_key=logical + ":partial", dry_run=False)
            except sa.exc.DBAPIError as error:
                require(getattr(error.orig, "sqlstate", None) == "23514")
                refused = True
        active = await _active(factory, logical)
        require(refused and active == before)
        partial = {"expected_count": len(after_members), "observed_count": len(observation["vectors"]),
            "missing_count": len(set(member["vector_id"] for member in after_members) -
                                 {row["vector_id"] for row in observation["vectors"]}),
            "validation_outcome": rejected["outcome"], "activation_refused": refused,
            "publication_failed": publication_failed, "repair_plan_sha256": digest(repair),
            "repair_before_sha256": digest({"transport": repair_before, "sql": sql_before}),
            "repair_after_sha256": digest({"transport": repair_after, "sql": sql_after}),
            "active_generation_id": active["generation_id"], "active_event_id": active["activation_event_id"]}
        timings["partial_publication"] = _ms(started)
        started = time.perf_counter()
        after, activation_checks, recovery = await _promote_with_transaction_probes(factory, after, after_members,
            logical_index=logical, predecessor=before["activation_event_id"])
        partial.update(recovery_acknowledged_count=recovery["acknowledged_count"],
                       recovery_already_present_count=recovery["already_present_count"])
        timings["publish_after"] = _ms(started)
        queries["after"] = await _query(factory, after, after_members)
        retained["after"] = await _retention(factory, history, release, artifacts)
        old_members = await _members(factory, before)
        old = {member["chunk_key"]: member for member in old_members}
        new = {member["chunk_key"]: member for member in after_members}
        removed = set(old) - set(new)
        changed = [key for key in old.keys() & new.keys() if old[key]["content_sha256"] != new[key]["content_sha256"]
                   and old[key]["chunk_revision_sha256"] != new[key]["chunk_revision_sha256"]]
        require(PAPERS[1] + "_chunk_000" in changed)
        async with _session(factory, readonly=True) as db:
            actual = list((await db.execute(sa.text("SELECT id,text FROM chunks WHERE paper_id IN (:a,:b) ORDER BY id"),
                                           {"a": PAPERS[0], "b": PAPERS[1]})).mappings())
        require({row["id"] for row in actual} == set(new) and not (removed & {row["id"] for row in actual}))
        replacement = {"removed_current_chunk_count": len(removed), "changed_same_position_count": len(changed),
            "retained_old_member_count": len(old_members), "current_chunk_count": len(actual),
            "current_chunk_inventory_sha256": digest([{ "chunk_id": row["id"], "content_sha256": _sha(row["text"].encode())} for row in actual])}
        started = time.perf_counter()
        rollback = await _activate(factory, before, before_members, logical_index=logical, predecessor=after["activation_event_id"],
                                   action="rollback", key=logical + ":rollback")
        timings["rollback"] = _ms(started)
        queries["rollback"] = await _query(factory, rollback, before_members)
        retained["rollback"] = await _retention(factory, history, release, artifacts)
        require(all(retained[phase] == retained["before"] for phase in PHASES))
        require(provider_counter["attempts"] == 0)
        return validate_migration_report({"version": VERSION, "run_id": run_id, "schema_revision": schema_revision, "logical_index": logical,
            "query_order": "synthetic_vector_id_order", "generations": {
                "before": _generation_summary(before, before_members, before_chunks),
                "after": _generation_summary(after, after_members, after_chunks)},
            "partial_publication": partial, "activation_checks": activation_checks,
            "queries": queries, "retention": retained, "replacement": replacement,
            "timings_ms": timings, "checks": CHECKS, "authority": AUTHORITY,
            "embedding": {"synthetic": True, "provider_calls": provider_counter["attempts"],
                          "provider_attempts": provider_counter["attempts"], "provider_tokens": None,
                          "provider_cost_usd": None, "production_embedding_quality_measured": False}})
    finally:
        provider_guard.__exit__(None, None, None)
        adapter._DISPOSABLE.pop(adapter._canonical(resource), None)


class SafeParser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError("index_migration_worker_arguments")


def main(argv=None):
    try:
        parser = SafeParser(description=__doc__, allow_abbrev=False)
        parser.add_argument("--stage", choices=("migrate", "measure"), required=True)
        args = parser.parse_args(argv)
        from test_safety import validate_test_environment
        initial = validate_test_environment()
        allowed = {("127.0.0.1", initial.manifest[name]["port"]) for name in ("postgres", "redis")}
        def network_guard(event, arguments):
            if event == "socket.getaddrinfo":
                require(tuple(arguments[:2]) in allowed)
            elif event == "socket.connect":
                address = arguments[1]
                require(isinstance(address, tuple) and tuple(address[:2]) in allowed)
        # Install before tokenizer/application imports, including DNS lookup.
        sys.addaudithook(network_guard)
        from research_restore_worker import _expected_revision, _migrate, _runtime
        capability = _runtime()
        from index_migration_contract import write_stage
        measurement = None
        if args.stage == "migrate":
            _migrate(capability)
        else:
            from index_migration_corpus import measure_chunking
            corpus = measure_chunking()
            measurement = {"corpus": corpus, "migration": asyncio.run(measure_migration(capability))}
        document = {"version": "index-migration-stage/1.0.0", "stage": args.stage, "run_id": capability.run_id,
            "status": "passed", "schema_revision": _expected_revision(), "measurement": measurement}
        write_stage(Path(capability.manifest["root"]), document)
        return 0
    except Exception:
        print("index_migration_worker_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
