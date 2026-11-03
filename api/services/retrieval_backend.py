"""Builder-only bounded projection construction/readback, never activation.

The caller supplies its already scoped DB session and owns the outer commit.
No credentials, provider client, public write route or live pointer is created.
"""
from __future__ import annotations

import re
from contextlib import asynccontextmanager
from uuid import UUID

import sqlalchemy as sa

from models.db import Base
from models.retrieval_backend_v2 import TABLE_ORDER, authority_sql
from models.retrieval_policy_v3 import POLICY,POLICY_SHA256,SUPPORTED_POLICIES
from services.pgvector_query import ProjectionSpec
from services.pgvector_wire import MAX_BYTES, content_projection_copy


class RetrievalBackendError(ValueError):
    """The explicit builder operation cannot establish its exact bindings."""


def _table(name):
    if name not in TABLE_ORDER:
        raise RetrievalBackendError("Unknown backend history relation")
    return Base.metadata.tables[name]


async def _existing(db, name, keys):
    table = _table(name)
    predicates = [table.c[key] == value for key, value in keys.items()]
    result = (await db.execute(sa.select(table).where(*predicates))).mappings().one_or_none()
    if result is not None:
        valid = await db.scalar(sa.select(table.c.record_sha256 ==
            sa.func.sclib_retrieval_record_hash_v2(sa.func.to_jsonb(table.table_valued()))).where(*predicates))
        if valid is not True:
            raise RetrievalBackendError("Backend history integrity mismatch")
        return dict(result)
    return None


async def _put(db, name, keys, values):
    prior = await _existing(db, name, keys)
    if prior is not None:
        if any(prior[key] != value for key, value in values.items()):
            raise RetrievalBackendError("Immutable backend identity conflict")
        return prior, False
    await db.execute(_table(name).insert().values(**keys, **values))
    return await _existing(db, name, keys), True


@asynccontextmanager
async def _phase(db, dry_run, settings=None):
    if type(dry_run) is not bool or db.new or db.dirty or db.deleted:
        raise RetrievalBackendError("Flush caller changes and choose explicit preview/apply mode")
    transaction = await db.begin_nested()
    operation = {"changed": False}
    try:
        previous = {}
        for key, value in (settings or {}).items():
            previous[key] = await db.scalar(sa.text("SELECT current_setting(:key)"), {"key": key})
            await db.execute(sa.text("SELECT set_config(:key,:value,true)"), {"key": key, "value": value})
        yield operation
        if dry_run or not operation["changed"]:
            await transaction.rollback()
        else:
            for key, value in previous.items():
                await db.execute(sa.text("SELECT set_config(:key,:value,true)"), {"key": key, "value": value})
            await transaction.commit()
    except BaseException:
        if transaction.is_active:
            await transaction.rollback()
        raise


async def _build(db, identifier):
    row = await _existing(db, TABLE_ORDER[0], {"id": identifier})
    if row is None:
        raise RetrievalBackendError("Explicit backend build unavailable")
    spec = ProjectionSpec(str(identifier), str(row["content_id"]), row["content_manifest_sha256"])
    return row, spec


async def _fence(db, identifier):
    await db.execute(sa.text("SELECT public.sclib_retrieval_build_fence_v2(:id)"), {"id": identifier})


async def stage_build(db, *, build_id, content_id, image_digest, implementation_revision, dry_run=True,policy_version='v3'):
    """Record declared artifact identity; external signature proof is separate."""
    if (type(image_digest) is not str or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_digest)
            or type(implementation_revision) is not str or not re.fullmatch(r"[a-f0-9]{40}", implementation_revision)):
        raise RetrievalBackendError("Explicit immutable image and implementation identities are required")
    identifier = UUID(str(build_id))
    if type(policy_version) is not str or policy_version not in {'v2','v3'}:
        raise RetrievalBackendError('An explicit supported query policy is required')
    policy,policy_sha=SUPPORTED_POLICIES[0 if policy_version=='v2' else 1]
    async with _phase(db, dry_run) as operation:
        row, operation["changed"] = await _put(db, TABLE_ORDER[0], {"id": identifier}, {
            "content_id": UUID(str(content_id)), "policy": policy, "policy_artifact_sha256": policy_sha,
            "image_digest": image_digest, "implementation_revision": implementation_revision})
    return {"build_id": str(identifier), "content_id": str(row["content_id"]),
            "record_sha256": row["record_sha256"], "expected_member_count": row["expected_member_count"],
            "dry_run": dry_run, "committed": False, "active_pointer_changed": False}


async def create_projection(db, *, build_id, dry_run=True):
    identifier = UUID(str(build_id))
    async with _phase(db, dry_run) as operation:
        _, spec = await _build(db, identifier)
        await _fence(db, identifier)
        if await db.scalar(sa.text("SELECT to_regclass(:name) IS NOT NULL"), {"name": spec.table}):
            return {"build_id": str(identifier), "existing": True, "dry_run": dry_run, "committed": False}
        if await db.scalar(sa.text("SELECT to_regnamespace('retrieval_projection') IS NOT NULL")) is not True:
            raise RetrievalBackendError("The migration-owned private projection schema is required")
        await db.execute(sa.text(f"CREATE TABLE {spec.table} (vector_id text PRIMARY KEY,paper_id text NOT NULL,"
            "year integer,content_sha256 text NOT NULL,vector_sha256 text NOT NULL,"
            "chunk_revision_sha256 text NOT NULL,embedding vector(768) NOT NULL)"))
        # The vector alone exceeds the default TOAST target. Protect all
        # bounded candidate fields too, or PostgreSQL externalizes their small
        # IDs/hashes while trying to shrink the row. Set before binary COPY.
        columns = ('vector_id', 'paper_id', 'content_sha256', 'vector_sha256',
                   'chunk_revision_sha256', 'embedding')
        await db.execute(sa.text(f"ALTER TABLE {spec.table} " + ','.join(
            f'ALTER COLUMN {name} SET STORAGE PLAIN' for name in columns)))
        await db.execute(sa.text(f"CREATE INDEX year_b_{identifier.hex} ON {spec.table}(year)"))
        for name, events in (("retrieval_projection_write_v2", "INSERT OR UPDATE OR DELETE"),
                             ("retrieval_projection_truncate_v2", "TRUNCATE")):
            await db.execute(sa.text(f"CREATE TRIGGER {name} BEFORE {events} ON {spec.table} "
                f"FOR EACH STATEMENT EXECUTE FUNCTION public.sclib_retrieval_projection_write_v2('{identifier}')"))
        operation["changed"] = True
    return {"build_id": str(identifier), "existing": False, "dry_run": dry_run, "committed": False}


async def _partition_observation(db, spec, content_id, partition_id):
    source = authority_sql().replace("$1", ":content") + " AND m.partition_id=:partition"
    sql = ("SELECT count(a.vector_id) AS source_count,count(p.vector_id) AS present_count,"
        "count(*) FILTER(WHERE p.vector_id IS NOT NULL AND (NOT a.intact OR p.paper_id IS DISTINCT FROM a.paper_id "
        "OR p.year IS DISTINCT FROM a.year OR p.content_sha256 IS DISTINCT FROM a.content_sha256 "
        "OR p.vector_sha256 IS DISTINCT FROM a.vector_sha256 OR p.chunk_revision_sha256 IS DISTINCT FROM a.chunk_revision_sha256 "
        "OR substring(vector_send(p.embedding) FROM 5) IS DISTINCT FROM a.vector_bytes)) AS mismatches "
        f"FROM ({source}) a LEFT JOIN {spec.table} p USING(vector_id)")
    return (await db.execute(sa.text(sql), {"content": content_id, "partition": partition_id})).mappings().one()


async def copy_partition(db, *, build_id, partition_id, dry_run=True):
    """Atomically copy one <=1000-row/4MiB partition, preserving every f32 bit.

    Actual rows are the durable resume state. Complete exact replay rolls back
    even its fence epoch. Conflicting/partial replay is refused; no prior import
    receipt is treated as proof that changed physical rows still match.
    """
    if type(partition_id) is not int or partition_id < 0:
        raise RetrievalBackendError("An explicit bounded source partition is required")
    identifier = UUID(str(build_id))
    async with _phase(db, dry_run, {"bytea_output": "hex"}) as operation:
        build, spec = await _build(db, identifier)
        await _fence(db, identifier)
        if await _existing(db, TABLE_ORDER[2], {"build_id": identifier}) is not None:
            raise RetrievalBackendError("A sealed projection cannot import source rows")
        part = (await db.execute(sa.text("SELECT member_count FROM retrieval_content_partitions_v2 "
            "WHERE content_id=:content AND partition_id=:partition"),
            {"content": build["content_id"], "partition": partition_id})).mappings().one_or_none()
        if part is None or not 1 <= part["member_count"] <= 1000:
            raise RetrievalBackendError("An actual sealed source partition is required")
        before = await _partition_observation(db, spec, build["content_id"], partition_id)
        if before["source_count"] != part["member_count"]:
            raise RetrievalBackendError("Source partition inventory mismatch")
        if before["present_count"]:
            if before["present_count"] != part["member_count"] or before["mismatches"]:
                raise RetrievalBackendError("Conflicting or partial projection replay")
            return {"build_id": str(identifier), "partition_id": partition_id, "members": part["member_count"],
                    "replayed": True, "dry_run": dry_run, "committed": False}
        connection = await db.connection()
        raw = await connection.get_raw_connection()
        driver = raw.driver_connection
        payload = bytearray()
        async def collect(data):
            if len(payload) + len(data) > MAX_BYTES:
                raise RetrievalBackendError("Source COPY byte budget exhausted")
            payload.extend(data)
        source = authority_sql() + " AND m.partition_id=$2"
        query = ("SELECT vector_id,paper_id,content_sha256,vector_sha256,chunk_revision_sha256,vector_bytes,intact,year "
                 f'FROM ({source}) source ORDER BY vector_id COLLATE "C"')
        await driver.copy_from_query(query, build["content_id"], partition_id, output=collect, format="binary", timeout=30)
        converted, inventory = content_projection_copy(bytes(payload))
        if len(inventory) != part["member_count"]:
            raise RetrievalBackendError("Source COPY did not enumerate the complete partition")
        await driver.copy_to_table("b_" + identifier.hex, schema_name="retrieval_projection",
            columns=("vector_id", "paper_id", "content_sha256", "vector_sha256", "chunk_revision_sha256", "embedding", "year"),
            source=memoryview(converted), format="binary", timeout=30)
        after = await _partition_observation(db, spec, build["content_id"], partition_id)
        if after["present_count"] != part["member_count"] or after["mismatches"]:
            raise RetrievalBackendError("Actual binary projection readback did not match its source partition")
        operation["changed"] = True
    return {"build_id": str(identifier), "partition_id": partition_id, "members": part["member_count"],
            "replayed": False, "dry_run": dry_run, "committed": False}


async def build_small_projection_graph(db, *, build_id, dry_run=True):
    """Small staging/smoke graph only; corpus builds need the host budget tool."""
    identifier = UUID(str(build_id))
    async with _phase(db, dry_run, {"maintenance_work_mem": "64MB", "max_parallel_maintenance_workers": "0"}) as operation:
        build, spec = await _build(db, identifier)
        if build["expected_member_count"] > 1000:
            raise RetrievalBackendError("Corpus graph construction requires the separately budgeted host builder")
        await _fence(db, identifier)
        if await _existing(db, TABLE_ORDER[2], {"build_id": identifier}) is not None:
            raise RetrievalBackendError("A sealed graph cannot be rebuilt")
        graph = "retrieval_projection.hnsw_b_" + identifier.hex
        if await db.scalar(sa.text("SELECT to_regclass(:name) IS NOT NULL"), {"name": graph}):
            return {"build_id": str(identifier), "existing": True, "dry_run": dry_run, "committed": False}
        count = await db.scalar(sa.text(f"SELECT count(*) FROM {spec.table}"))
        if count != build["expected_member_count"]:
            raise RetrievalBackendError("Complete projection inventory required before graph construction")
        await db.execute(sa.text(f"CREATE INDEX hnsw_b_{identifier.hex} ON {spec.table} "
                                 "USING hnsw(embedding vector_cosine_ops) WITH(m=32,ef_construction=200)"))
        await db.execute(sa.text(f"ANALYZE {spec.table}"))
        operation["changed"] = True
    return {"build_id": str(identifier), "existing": False, "dry_run": dry_run, "committed": False}


async def seal_projection(db, *, build_id, dry_run=True):
    identifier = UUID(str(build_id))
    async with _phase(db, dry_run) as operation:
        row, operation["changed"] = await _put(db, TABLE_ORDER[2], {"build_id": identifier}, {})
    return {"build_id": str(identifier), "record_sha256": row["record_sha256"],
            "table_oid": row["table_oid"], "index_oid": row["index_oid"], "dry_run": dry_run, "committed": False}


async def build_corpus_projection_graph(db, *, build_id, expected_members, host_graph_budget=False):
    """Shared builder primitive; the caller separately enforces host budgets.

    No source generation is invented for native content. The exact immutable
    build/content count is checked before DDL. Graph, seal, validation and
    quality/activation remain distinct phases with fresh caller admission.
    """
    if host_graph_budget is not True or type(host_graph_budget) is not bool:
        raise RetrievalBackendError('Separately guarded host graph budget required')
    if type(expected_members) is not int or not 1 <= expected_members <= 5000000:
        raise RetrievalBackendError('A bounded complete content member count is required')
    identifier = UUID(str(build_id))
    build, spec = await _build(db, identifier)
    if build['expected_member_count'] != expected_members:
        raise RetrievalBackendError('Exact immutable graph/content count required')
    async with _phase(db, False, {'maintenance_work_mem': '6GB',
            'max_parallel_maintenance_workers': '5', 'statement_timeout': '0', 'lock_timeout': '5s',
            'application_name': 'sclib_corpus_graph_' + identifier.hex}) as operation:
        await _fence(db, identifier)
        sealed = await _existing(db, 'retrieval_projection_seals_v2', {'build_id': identifier})
        if sealed is not None:
            present = await db.scalar(sa.text('SELECT to_regclass(:table)::oid=:table_oid AND EXISTS('
                'SELECT 1 FROM pg_index WHERE indexrelid=:index_oid AND indrelid=:table_oid AND indisvalid AND indisready)'),
                {'table': spec.table, 'table_oid': sealed['table_oid'], 'index_oid': sealed['index_oid']})
            if present is not True:
                raise RetrievalBackendError('Sealed graph physical identity changed')
            return {'graph': 'sealed_no_rebuild', 'build_id': str(identifier)}
        name = 'hnsw_b_' + identifier.hex
        if await db.scalar(sa.text('SELECT to_regclass(:name) IS NOT NULL'), {'name': 'retrieval_projection.' + name}):
            return {'graph': 'existing_unsealed_requires_seal_validation', 'build_id': str(identifier)}
        count = await db.scalar(sa.text(f'SELECT count(*) FROM {spec.table}'))
        toast = await db.scalar(sa.text('SELECT CASE WHEN reltoastrelid=0 THEN 0 ELSE pg_relation_size(reltoastrelid) END '
            'FROM pg_class WHERE oid=to_regclass(:name)'), {'name': spec.table})
        if count != expected_members or toast != 0:
            raise RetrievalBackendError('Complete inline projection required before graph')
        await db.execute(sa.text(f'CREATE INDEX {name} ON {spec.table} USING hnsw '
            '(embedding vector_cosine_ops) WITH(m=32,ef_construction=200)'))
        await db.execute(sa.text(f'ANALYZE {spec.table}'))
        operation['changed'] = True
    return {'graph': 'constructed_not_accepted', 'build_id': str(identifier), 'members': count}


async def validate_projection(db, *, build_id, validation_id, dry_run=True):
    identifier = UUID(str(build_id))
    async with _phase(db, dry_run) as operation:
        row, operation["changed"] = await _put(db, TABLE_ORDER[3], {"id": UUID(str(validation_id))}, {"build_id": identifier})
    return {"build_id": str(identifier), "validation_id": str(row["id"]), "outcome": row["outcome"],
            **{key: row[key] for key in ("source_member_count", "projection_member_count", "missing_count",
                "extra_count", "mismatch_count", "content_manifest_intact", "record_sha256")},
            "dry_run": dry_run, "committed": False, "active_pointer_changed": False}
