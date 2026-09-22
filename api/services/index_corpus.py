"""Resumable corpus operations; transactions stay owned by the operator.

Roots are compact manifests of <=20,000 partitions. Each partition retains the
0062 limits (1,000 members / 16 MiB snapshots). Retrieval hydrates selected IDs;
no request loads the complete corpus. Scientific admission remains independent.
"""

from __future__ import annotations

import hashlib
import struct
from datetime import datetime, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa

from models.db import Base
from models.index_generations_v1 import PROFILE
from models.retained_legacy_v1 import PARSER
from services import index_generations as generations
from services.embedding_contract import validate_embedding_provenance, validate_vector
from services.embedding_receipts import _document_encoder, _document_token_count

MAX_PARTITIONS = 20000


def formula_terms(text):
    from services.scientific_query import _formula_candidates

    require(type(text) is str and len(text.encode()) <= 1024 * 1024)
    result = set()
    for _, _, normalized in _formula_candidates(text):
        if normalized.status == "normalized":
            result.add(normalized.normalized_formula)
        require(len(result) <= 2048)
    return sorted(result)


def require(value, message="Exact bounded corpus operation required"):
    if not value:
        raise generations.IndexGenerationError(message)


def root_manifest(partitions):
    require(type(partitions) is list and 1 <= len(partitions) <= MAX_PARTITIONS)
    lines = []
    for number, part in enumerate(partitions, 1):
        require(
            set(part)
            == {"partition_id", "expected_member_count", "snapshot_bytes", "manifest_sha256"}
            and type(part["partition_id"]) is int
            and part["partition_id"] == number
            and type(part["expected_member_count"]) is int
            and 1 <= part["expected_member_count"] <= 1000
            and type(part["snapshot_bytes"]) is int
            and 1 <= part["snapshot_bytes"] <= 16 * 1024 * 1024
            and type(part["manifest_sha256"]) is str
            and generations._SHA.fullmatch(part["manifest_sha256"])
        )
        lines.append(
            f"{number}\t{part['expected_member_count']}\t{part['snapshot_bytes']}\t{part['manifest_sha256']}\n"
        )
    return hashlib.sha256("".join(lines).encode("ascii")).hexdigest()


async def is_corpus(db, generation_id):
    return bool(
        await db.scalar(
            sa.text("SELECT EXISTS(SELECT 1 FROM index_corpora WHERE generation_id=:id)"),
            {"id": UUID(str(generation_id))},
        )
    )


async def create_corpus(
    db,
    *,
    generation_id,
    resource,
    pack_sha256,
    input_manifest_sha256,
    expected_sources,
    partitions,
    logical_index="sclib-main",
):
    generations._clean(db, False)
    identifier = UUID(str(generation_id))
    resource = generations._resource(resource)
    manifest = root_manifest(partitions)
    count = sum(row["expected_member_count"] for row in partitions)
    require(
        type(expected_sources) is int
        and 1 <= expected_sources <= count <= 2000000
        and all(
            type(v) is str and generations._SHA.fullmatch(v)
            for v in (pack_sha256, input_manifest_sha256)
        )
    )
    async with db.begin_nested():
        await db.execute(sa.text("SELECT public.sclib_index_lock_v1()"))
        generation = {
            "id": identifier,
            "logical_index": generations._string(logical_index, 128),
            "profile": PROFILE,
            "resource": resource,
            "expected_member_count": count,
            "manifest_sha256": manifest,
        }
        corpus = {
            "generation_id": identifier,
            "pack_sha256": pack_sha256,
            "input_manifest_sha256": input_manifest_sha256,
            "expected_sources": expected_sources,
            "expected_partitions": len(partitions),
        }
        existing = await generations._generation(db, identifier)
        if existing is not None:
            require(
                all(existing[k] == v for k, v in generation.items()),
                "Immutable corpus identity conflict",
            )
            retained = await generations._verified_rows(
                db,
                "index_corpora",
                Base.metadata.tables["index_corpora"].c.generation_id == identifier,
            )
            require(len(retained) == 1 and all(retained[0][k] == v for k, v in corpus.items()))
            actual = await generations._verified_rows(
                db,
                "index_corpus_partitions",
                Base.metadata.tables["index_corpus_partitions"].c.generation_id == identifier,
            )
            require(
                [
                    {k: row[k] for k in partitions[0]}
                    for row in sorted(actual, key=lambda r: r["partition_id"])
                ]
                == partitions
            )
            return generations._pin(existing)
        await db.execute(Base.metadata.tables["index_generations"].insert().values(**generation))
        await db.execute(Base.metadata.tables["index_corpora"].insert().values(**corpus))
        await db.execute(
            Base.metadata.tables["index_corpus_partitions"].insert(),
            [{"generation_id": identifier, **row} for row in partitions],
        )
        return generations._pin(generation)


async def prepare_members(db, *, generation_id, items):
    """Read exact current receipts in a bounded private planning transaction."""
    generations._clean(db, False)
    identifier = UUID(str(generation_id))
    require(type(items) is list and 1 <= len(items) <= 1000)
    inputs = {}
    for item in items:
        require(type(item) is dict and set(item) == {"chunk_id", "receipt_id", "vector"})
        key = generations._string(item["chunk_id"], 200)
        require(key not in inputs)
        vector = validate_vector(item["vector"])
        inputs[key] = dict(
            receipt_id=UUID(str(item["receipt_id"])),
            vector=vector,
            vector_bytes=struct.pack(">768f", *vector),
        )
    joins = """FROM chunks c JOIN papers p ON p.id=c.paper_id JOIN chunk_evidence_current link ON link.chunk_id=c.id
        JOIN rag_evidence_revisions e ON e.id=link.evidence_revision_id
        JOIN embedding_completion_receipts r ON r.chunk_key=c.id AND r.evidence_revision_id=e.id
        WHERE c.id IN :chunks AND r.id IN :receipts AND e.chunk_kind='retained_legacy_snapshot'"""
    parameters = {"chunks": list(inputs), "receipts": [v["receipt_id"] for v in inputs.values()]}

    def bounded(statement):
        return sa.text(statement + joins).bindparams(
            sa.bindparam("chunks", expanding=True), sa.bindparam("receipts", expanding=True)
        )

    count, size = (
        await db.execute(
            bounded(
                "SELECT count(*),COALESCE(sum(octet_length(to_jsonb(c)::text)+"
                "octet_length(public.sclib_index_paper_snapshot_v1(to_jsonb(p))::text)),0) "
            ),
            parameters,
        )
    ).one()
    require(
        count == len(inputs) and size <= generations.MAX_SNAPSHOT_BYTES,
        "Corpus planning snapshot budget exceeded",
    )
    rows = (
        (
            await db.execute(
                bounded("""SELECT c.id AS chunk_key,c.paper_id,to_jsonb(c) AS snapshot_json,
        public.sclib_index_paper_snapshot_v1(to_jsonb(p)) AS paper_snapshot_json,
        public.sclib_index_hash_v1(jsonb_build_object('chunk',to_jsonb(c),'paper',public.sclib_index_paper_snapshot_v1(to_jsonb(p)))) AS snapshot_sha256,
        e.id AS evidence_revision_id,e.record_sha256 AS evidence_record_sha256,e.source_snapshot_sha256,
        e.rendering_version AS chunker_version,r.id AS receipt_id,r.record_sha256 AS receipt_record_sha256,
        r.content_sha256,r.vector_sha256,r.metadata_json,
        octet_length(to_jsonb(c)::text)+octet_length(public.sclib_index_paper_snapshot_v1(to_jsonb(p))::text) AS snapshot_bytes
        """),
                parameters,
            )
        )
        .mappings()
        .all()
    )
    require(len(rows) == count and sum(row["snapshot_bytes"] for row in rows) == size)
    encoder = _document_encoder()
    members = []
    for row in rows:
        member = dict(row)
        value = inputs[member["chunk_key"]]
        require(member["receipt_id"] == value["receipt_id"])
        metadata = member.pop("metadata_json")
        validate_embedding_provenance(
            metadata,
            text=member["snapshot_json"]["text"],
            vector=value["vector"],
            expected_task="RETRIEVAL_DOCUMENT",
        )
        require(
            metadata["local_count"]
            == _document_token_count(member["snapshot_json"]["text"], encoder)
        )
        member.update(generation_id=identifier, parser_version=PARSER)
        members.append(member)
    hashes = await generations._hashes(db, members)
    for member, digest in zip(members, hashes, strict=True):
        member.update(
            chunk_revision_sha256=digest,
            vector_id=generations.vector_id_for(identifier, digest),
            vector_bytes=inputs[member["chunk_key"]]["vector_bytes"],
        )
    return sorted(members, key=lambda row: row["vector_id"])


def partition_plan(members, partition_id):
    return {
        "partition_id": partition_id,
        "expected_member_count": len(members),
        "snapshot_bytes": sum(row["snapshot_bytes"] for row in members),
        "manifest_sha256": generations.manifest_sha256(members),
    }


async def partition_members(db, *, generation_id, partition_id):
    require(type(partition_id) is int and 1 <= partition_id <= MAX_PARTITIONS)
    ids = (
        (
            await db.execute(
                sa.text("""SELECT m.vector_id FROM index_corpus_member_routes route
        JOIN index_generation_members m ON m.generation_id=route.generation_id AND m.chunk_key=route.chunk_key
        WHERE route.generation_id=:id AND route.partition_id=:part ORDER BY m.vector_id LIMIT 1001"""),
                {"id": UUID(str(generation_id)), "part": partition_id},
            )
        )
        .scalars()
        .all()
    )
    require(len(ids) <= 1000)
    return await generations.load_generation_members(
        db, generation_id=generation_id, vector_ids=ids
    )


async def stage_partition(db, *, generation_id, partition_id, items):
    generations._clean(db, False)
    identifier = UUID(str(generation_id))
    require(type(partition_id) is int and 1 <= partition_id <= MAX_PARTITIONS)
    table = Base.metadata.tables["index_corpus_partitions"]
    async with db.begin_nested():
        await db.execute(sa.text("SELECT public.sclib_index_lock_v1()"))
        plans = await generations._verified_rows(
            db,
            table.name,
            table.c.generation_id == identifier,
            table.c.partition_id == partition_id,
        )
        require(len(plans) == 1)
        members = await prepare_members(db, generation_id=identifier, items=items)
        plan = partition_plan(members, partition_id)
        require(
            all(plans[0][key] == value for key, value in plan.items()),
            "Corpus partition differs from immutable plan",
        )
        existing = await partition_members(db, generation_id=identifier, partition_id=partition_id)
        if existing:
            require(
                generations.manifest_sha256(existing) == plan["manifest_sha256"]
                and len(existing) == len(members)
            )
            require(
                all(
                    all(
                        old[key] == value
                        for key, value in generations._public_member(new).items()
                        if key != "snapshot_bytes"
                    )
                    for old, new in zip(existing, members, strict=True)
                ),
                "Immutable partition replay conflict",
            )
        else:
            # Immutable contiguous slots bind each actual member's bytes to a
            # checked prefix budget. The seal independently rechecks the total.
            routes, cumulative = [], 0
            for ordinal, member in enumerate(members, 1):
                cumulative += member["snapshot_bytes"]
                routes.append(
                    {
                        "generation_id": identifier,
                        "chunk_key": member["chunk_key"],
                        "partition_id": partition_id,
                        "ordinal": ordinal,
                        "snapshot_bytes": member["snapshot_bytes"],
                        "cumulative_snapshot_bytes": cumulative,
                    }
                )
            await db.execute(Base.metadata.tables["index_corpus_member_routes"].insert(), routes)
            await db.execute(
                Base.metadata.tables["index_generation_members"].insert(),
                [
                    {key: value for key, value in row.items() if key != "snapshot_bytes"}
                    for row in members
                ],
            )
            await db.execute(
                Base.metadata.tables["index_corpus_formula_terms"].insert(),
                [
                    {
                        "generation_id": identifier,
                        "partition_id": partition_id,
                        "vector_id": row["vector_id"],
                        "content_sha256": row["content_sha256"],
                        "terms": formula_terms(row["snapshot_json"]["text"]),
                        "producer_version": "sclib-formula-navigation/1.0.0",
                    }
                    for row in members
                ],
            )
        seals = Base.metadata.tables["index_corpus_seals"]
        sealed = await db.scalar(
            sa.select(seals.c.manifest_sha256).where(
                seals.c.generation_id == identifier, seals.c.partition_id == partition_id
            )
        )
        if sealed is None:
            await db.execute(
                seals.insert().values(
                    generation_id=identifier,
                    partition_id=partition_id,
                    manifest_sha256=plan["manifest_sha256"],
                )
            )
        else:
            require(sealed == plan["manifest_sha256"])
        return plan


async def formula_candidates(db, pin, wanted, *, limit, year_min=None, year_max=None):
    """GIN candidate navigation, followed by exact retained-text verification."""
    require(type(wanted) is set and 1 <= len(wanted) <= 32 and type(limit) is int)
    rows = (
        await db.execute(
            sa.text("""SELECT nav.vector_id,
        (SELECT count(*) FROM unnest(nav.terms) term WHERE term=ANY(CAST(:wanted AS text[]))) AS matches
        FROM index_corpus_formula_terms nav JOIN index_generation_members member
          ON member.generation_id=nav.generation_id AND member.vector_id=nav.vector_id
        WHERE nav.generation_id=:generation AND nav.terms && CAST(:wanted AS text[])
          AND nav.content_sha256=member.content_sha256
          AND nav.record_sha256=public.sclib_index_record_hash_v1(to_jsonb(nav))
          AND (CAST(:year_min AS integer) IS NULL OR (member.snapshot_json->>'year')::integer>=:year_min)
          AND (CAST(:year_max AS integer) IS NULL OR (member.snapshot_json->>'year')::integer<=:year_max)
        ORDER BY matches DESC,nav.vector_id LIMIT :limit"""),
            {
                "generation": UUID(pin["generation_id"]),
                "wanted": sorted(wanted),
                "limit": min(max(limit, 1), 300),
                "year_min": year_min,
                "year_max": year_max,
            },
        )
    ).all()
    return [row.vector_id for row in rows]


async def record_partition_observation(db, *, generation_id, partition_id, observation):
    require(type(observation) is dict)
    identifier = uuid4()
    table = Base.metadata.tables["index_corpus_observations"]
    async with db.begin_nested():
        row = (
            (
                await db.execute(
                    table.insert()
                    .values(
                        id=identifier,
                        generation_id=UUID(str(generation_id)),
                        partition_id=partition_id,
                        observation=observation,
                    )
                    .returning(table)
                )
            )
            .mappings()
            .one()
        )
        return {
            "id": str(identifier),
            "partition_id": partition_id,
            "outcome": row["outcome"],
            "manifest_sha256": row["observed_manifest_sha256"],
        }


async def validate_corpus(db, *, generation_id, observation_ids, started_at):
    pin = await generations.load_generation(db, generation_id=generation_id)
    require(
        pin is not None
        and type(observation_ids) is list
        and 1 <= len(observation_ids) <= MAX_PARTITIONS
        and len(set(observation_ids)) == len(observation_ids)
    )
    observation = {
        "version": "sclib-corpus-observation/1.0.0",
        "observation_id": str(uuid4()),
        "observed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "started_at": started_at,
        "resource": pin["resource"],
        "profile": pin["profile"],
        "adapter_version": "sclib-corpus-vector-adapter/1.0.0",
        "partition_observation_ids": [str(UUID(value)) for value in observation_ids],
        "full_inventory_observed": False,
    }
    identifier = uuid4()
    table = Base.metadata.tables["index_generation_validations"]
    async with db.begin_nested():
        row = (
            (
                await db.execute(
                    table.insert()
                    .values(
                        id=identifier,
                        generation_id=UUID(str(generation_id)),
                        observation=observation,
                    )
                    .returning(table)
                )
            )
            .mappings()
            .one()
        )
        return {
            "validation_id": str(identifier),
            "outcome": row["outcome"],
            "manifest_sha256": row["observed_manifest_sha256"],
        }
