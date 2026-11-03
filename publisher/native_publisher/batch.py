"""Bounded, restartable native batch preparation; never quality or activation.

Short claim/plan operations belong to the caller's transaction. Materialization
commits each <=1000-member partition separately. The retained SQL records, not
a cursor file, determine whether an interrupted partition can be replayed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from uuid import UUID, uuid5

import sqlalchemy as sa

from services import retrieval_backend as backend, retrieval_content as content
from services import retrieval_publication_queue as queue

NAMESPACE = UUID("76098bf4-f0eb-4e55-83b9-28a71e195bf2")


class NativeBatchError(ValueError):
    pass


@dataclass(frozen=True)
class JobClaim:
    job_id: str
    publication_id: str
    paper_id: str
    job_sha256: str
    claim_id: str
    claim_sha256: str


@dataclass(frozen=True)
class BatchPlan:
    batch_id: str
    logical_index: str
    base_content_id: str
    base_record_sha256: str
    base_seal_sha256: str
    content_id: str
    content_record_sha256: str
    worker_id: str
    jobs: tuple[JobClaim, ...]

    def to_dict(self):
        return {"version": "native-batch-plan/1.0.0", **asdict(self)}

    @classmethod
    def from_dict(cls, body):
        if type(body) is not dict or body.get("version") != "native-batch-plan/1.0.0":
            raise NativeBatchError("Closed versioned batch plan required")
        values = {key: value for key, value in body.items() if key != "version"}
        values["jobs"] = tuple(JobClaim(**row) for row in values["jobs"])
        return cls(**values)


async def latest_pending_jobs(db, *, logical_index, limit=100):
    """Choose only the latest retained publication of each paper, skip leases.

    Older jobs are retained. They are not silently called published or removed;
    an explicit supersession operation can later reference the actual successor.
    """
    if (type(limit) is not int or not 1 <= limit <= 100 or type(logical_index) is not str
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,160}", logical_index)):
        raise NativeBatchError("Explicit bounded batch selection required")
    return [str(row) for row in (await db.execute(sa.text("""
      SELECT j.id FROM retrieval_publication_jobs_v2 j
      JOIN retrieval_publication_job_fences_v2 f ON f.job_id=j.id
      WHERE j.logical_index=:logical AND NOT EXISTS(
        SELECT 1 FROM retrieval_publication_jobs_v2 newer WHERE newer.logical_index=j.logical_index
          AND newer.paper_id=j.paper_id AND newer.sequence_number>j.sequence_number)
      AND NOT EXISTS(SELECT 1 FROM retrieval_publication_results_v2 r
        WHERE r.job_id=j.id AND r.outcome IN ('published','superseded'))
      AND NOT EXISTS(SELECT 1 FROM retrieval_publication_claims_v2 c WHERE c.job_id=j.id
        AND c.lease_until>clock_timestamp() AND NOT EXISTS(
          SELECT 1 FROM retrieval_publication_results_v2 r WHERE r.claim_id=c.id))
      ORDER BY j.sequence_number LIMIT :limit FOR UPDATE OF f SKIP LOCKED
    """), {"logical": logical_index, "limit": limit})).scalars()]


async def claim_and_plan(db, *, batch_id, logical_index, base_content_id, job_ids,
                         worker_id, lease_seconds=7200, dry_run=True):
    if (type(job_ids) is not list or not 1 <= len(job_ids) <= 100
            or len(set(job_ids)) != len(job_ids)):
        raise NativeBatchError("A batch requires 1..100 distinct queued publications")
    batch, base = UUID(str(batch_id)), UUID(str(base_content_id))
    jobs = []
    async with backend._phase(db, dry_run) as operation:
        source = await content._existing(db, "retrieval_contents_v2", {"id": base})
        seal = await content._existing(db, "retrieval_content_seals_v2", {"content_id": base})
        if source is None or seal is None or source["logical_index"] != logical_index:
            raise NativeBatchError("An intact sealed base in the same logical index is required")
        for identifier in sorted(UUID(str(value)) for value in job_ids):
            job = await queue._existing(db, "retrieval_publication_jobs_v2", {"id": identifier})
            if job is None or job["logical_index"] != logical_index:
                raise NativeBatchError("An intact job in the same logical index is required")
            if await db.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM retrieval_publication_jobs_v2 "
                    "WHERE logical_index=:logical AND paper_id=:paper AND sequence_number>:sequence)"),
                    {"logical": logical_index, "paper": job["paper_id"], "sequence": job["sequence_number"]}):
                raise NativeBatchError("Select the actual latest publication for this paper")
            claim = await queue.claim_job(db, job_id=str(identifier),
                claim_id=str(uuid5(NAMESPACE, str(batch) + ":" + str(identifier))),
                worker_id=worker_id, lease_seconds=lease_seconds, dry_run=False)
            if claim["currently_usable"] is not True:
                raise NativeBatchError("An unexpired current claim is required; use a new batch after retry/expiry")
            jobs.append(JobClaim(str(identifier), str(job["publication_id"]), job["paper_id"],
                job["record_sha256"], claim["claim_id"], claim["record_sha256"]))
        if len({job.paper_id for job in jobs}) != len(jobs):
            raise NativeBatchError("Choose one complete latest publication per paper")
        planned = await content.stage_native_content(db, base_content_id=str(base),
            publication_ids=[job.publication_id for job in jobs], dry_run=False)
        body = await content._existing(db, "retrieval_contents_v2", {"id": UUID(planned["content_id"])})
        plan = BatchPlan(str(batch), logical_index, str(base), source["record_sha256"], seal["record_sha256"],
            planned["content_id"], body["record_sha256"], worker_id, tuple(jobs))
        operation["changed"] = True
    return plan


async def verify_plan(db, plan, *, usable=True):
    if type(plan) is not BatchPlan or not 1 <= len(plan.jobs) <= 100 or len({j.paper_id for j in plan.jobs}) != len(plan.jobs):
        raise NativeBatchError("An exact bounded batch plan is required")
    if any(str(uuid5(NAMESPACE, str(UUID(plan.batch_id)) + ":" + job.job_id)) != job.claim_id for job in plan.jobs):
        raise NativeBatchError("Claims must belong to this exact batch identity")
    base = await content._existing(db, "retrieval_contents_v2", {"id": UUID(plan.base_content_id)})
    seal = await content._existing(db, "retrieval_content_seals_v2", {"content_id": UUID(plan.base_content_id)})
    target = await content._existing(db, "retrieval_contents_v2", {"id": UUID(plan.content_id)})
    if (base is None or seal is None or target is None
            or base["record_sha256"] != plan.base_record_sha256 or seal["record_sha256"] != plan.base_seal_sha256
            or target["record_sha256"] != plan.content_record_sha256
            or str(target["base_content_id"]) != plan.base_content_id or target["logical_index"] != plan.logical_index):
        raise NativeBatchError("Retained immutable batch content no longer matches")
    changes = (await db.execute(sa.text("SELECT paper_id,publication_id,"
        "record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(change)) AS intact "
        "FROM retrieval_content_changes_v2 change WHERE content_id=:id"),
        {"id": UUID(plan.content_id)})).all()
    if (any(row.intact is not True for row in changes)
            or {(row.paper_id, str(row.publication_id)) for row in changes} != {(j.paper_id, j.publication_id) for j in plan.jobs}):
        raise NativeBatchError("The plan must account for every intact content change")
    rows = (await db.execute(sa.text("""
      SELECT j.id AS job_id,j.publication_id,j.paper_id,j.logical_index,j.record_sha256 AS job_sha,
        c.id AS claim_id,c.record_sha256 AS claim_sha,c.worker_id,
        j.record_sha256=public.sclib_publication_queue_hash_v2(to_jsonb(j))
          AND c.record_sha256=public.sclib_publication_queue_hash_v2(to_jsonb(c))
          AND p.record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(p))
          AND s.record_sha256=public.sclib_retrieval_record_hash_v2(to_jsonb(s))
          AND j.publication_seal_record_sha256=s.record_sha256
          AND j.publication_manifest_sha256=s.manifest_sha256 AND j.member_count=s.member_count
          AND p.paper_id=j.paper_id AND p.expected_member_count=s.member_count AS intact,
        c.lease_until>clock_timestamp() AND NOT EXISTS(
          SELECT 1 FROM retrieval_publication_claims_v2 newer WHERE newer.job_id=j.id AND newer.attempt_number>c.attempt_number)
          AND NOT EXISTS(SELECT 1 FROM retrieval_publication_results_v2 r WHERE r.claim_id=c.id) AS current,
        EXISTS(SELECT 1 FROM retrieval_publication_jobs_v2 newer WHERE newer.logical_index=j.logical_index
          AND newer.paper_id=j.paper_id AND newer.sequence_number>j.sequence_number) AS newer_publication
      FROM retrieval_publication_jobs_v2 j JOIN retrieval_publication_claims_v2 c ON c.job_id=j.id
      JOIN retrieval_publications_v2 p ON p.id=j.publication_id
      JOIN retrieval_publication_seals_v2 s ON s.publication_id=p.id
      WHERE j.id IN :jobs AND c.id IN :claims
    """).bindparams(sa.bindparam("jobs", expanding=True), sa.bindparam("claims", expanding=True)),
        {"jobs": [UUID(j.job_id) for j in plan.jobs], "claims": [UUID(j.claim_id) for j in plan.jobs]})).mappings().all()
    retained = {str(row["job_id"]): row for row in rows}
    if len(rows) != len(plan.jobs) or len(retained) != len(plan.jobs):
        raise NativeBatchError("Complete exact retained batch job/claim inventory required")
    for job in plan.jobs:
        row = retained.get(job.job_id)
        if (row is None or row["intact"] is not True or row["job_sha"] != job.job_sha256
                or row["paper_id"] != job.paper_id or str(row["publication_id"]) != job.publication_id
                or row["logical_index"] != plan.logical_index or str(row["claim_id"]) != job.claim_id
                or row["claim_sha"] != job.claim_sha256 or row["worker_id"] != plan.worker_id):
            raise NativeBatchError("An intact exact retained job, publication and claim are required")
        if usable and (row["current"] is not True or row["newer_publication"]):
            raise NativeBatchError("A claim expired, finished or was superseded; stop before long work")
    return target


async def materialize_content(plan, *, session_factory, progress=None):
    """Durable bounded partition replay. Caller must commit the plan first."""
    cursor = ""
    partition = total = 0
    async with session_factory() as db:
        target = await verify_plan(db, plan)
        await db.rollback()
        while True:
            await verify_plan(db, plan)
            page = await content.source_reference_page(db, content_id=plan.content_id, after=cursor)
            if not page:
                await db.rollback()
                break
            await content.append_content_partition(db, content_id=plan.content_id,
                partition_id=partition, references=page, dry_run=False)
            await db.commit()
            cursor = page[-1]["vector_id"]
            partition += 1
            total += len(page)
            if progress:
                progress({"phase": "content", "members": total, "partitions": partition})
        if total != target["expected_member_count"]:
            raise NativeBatchError("Complete batch content enumeration required")
        await verify_plan(db, plan)
        sealed = await content.seal_content(db, content_id=plan.content_id, dry_run=False)
        await db.commit()
    return {"content_id": plan.content_id, "members": total, "partitions": partition,
        "manifest_sha256": sealed["manifest_sha256"], "activated": False}


async def prepare_projection(plan, *, build_id, image_digest, implementation_revision,
                             session_factory, phase="projection", validation_id=None, progress=None,
                             host_graph_budget=False):
    """Prepare/copy any bounded corpus; long graph work needs a host guard.

    Corpus graph/seal/readback phases require the separately health/resource
    guarded host runner to opt in explicitly. This command never promotes a
    build or attests quality. Each long phase checks the current lease again
    before commit; superseded or expired work cannot report completion.
    """
    if phase not in {"projection", "copy-vectors", "small-graph", "small-validate", "graph", "seal-projection", "validate"}:
        raise NativeBatchError("Explicit batch projection phase required")
    if type(host_graph_budget) is not bool or phase in {"graph", "seal-projection", "validate"} and not host_graph_budget:
        raise NativeBatchError("Separately guarded host graph budget required for corpus phases")
    async with session_factory() as db:
        target = await verify_plan(db, plan)
        build = await backend.stage_build(db, build_id=build_id, content_id=plan.content_id,
            image_digest=image_digest, implementation_revision=implementation_revision, dry_run=True)
        if phase == "projection":
            await backend.stage_build(db, build_id=build_id, content_id=plan.content_id,
                image_digest=image_digest, implementation_revision=implementation_revision, dry_run=False)
            result = await backend.create_projection(db, build_id=build_id, dry_run=False)
            await db.commit()
        else:
            retained, _ = await backend._build(db, UUID(build_id))
            if retained["record_sha256"] != build["record_sha256"]:
                raise NativeBatchError("Exact retained build identity required")
            if phase == "copy-vectors":
                parts = (await db.execute(sa.text("SELECT partition_id,member_count FROM retrieval_content_partitions_v2 "
                    "WHERE content_id=:id ORDER BY partition_id"), {"id": UUID(plan.content_id)})).all()
                if ([row.partition_id for row in parts] != list(range(len(parts)))
                        or sum(row.member_count for row in parts) != target["expected_member_count"]):
                    raise NativeBatchError("Complete contiguous sealed partitions required")
                await db.rollback()
                total = 0
                for part in parts:
                    await verify_plan(db, plan)
                    copied = await backend.copy_partition(db, build_id=build_id, partition_id=part.partition_id, dry_run=False)
                    await db.commit()
                    total += copied["members"]
                    if progress:
                        progress({"phase": phase, "members": total, "partitions": part.partition_id + 1})
                if total != target["expected_member_count"]:
                    raise NativeBatchError("Complete projection copy required")
                result = {"members": total, "partitions": len(parts)}
            elif phase in {"graph", "seal-projection", "validate"}:
                if phase == "graph":
                    result = await backend.build_corpus_projection_graph(db,build_id=build_id,
                        expected_members=target['expected_member_count'],host_graph_budget=host_graph_budget)
                elif phase == "seal-projection":
                    result = await backend.seal_projection(db,build_id=build_id,dry_run=False)
                else:
                    if validation_id is None:
                        raise NativeBatchError("Explicit validation identity required")
                    result = await backend.validate_projection(db,build_id=build_id,validation_id=validation_id,dry_run=False)
                await verify_plan(db,plan)
                await db.commit()
            else:
                if target["expected_member_count"] > 1000:
                    raise NativeBatchError("Corpus graph/readback requires the separately guarded host runner")
                if phase == "small-graph":
                    sealed = await backend._existing(db, "retrieval_projection_seals_v2", {"build_id": UUID(build_id)})
                    if sealed is None:
                        await backend.build_small_projection_graph(db, build_id=build_id, dry_run=False)
                    else:
                        _, spec = await backend._build(db, UUID(build_id))
                        present = await db.scalar(sa.text("SELECT to_regclass(:table)::oid=:table_oid AND EXISTS("
                            "SELECT 1 FROM pg_index WHERE indexrelid=:index_oid AND indrelid=:table_oid AND indisvalid AND indisready)"),
                            {"table": spec.table, "table_oid": sealed["table_oid"], "index_oid": sealed["index_oid"]})
                        if present is not True:
                            raise NativeBatchError("Retained graph seal no longer matches actual physical objects")
                    result = await backend.seal_projection(db, build_id=build_id, dry_run=False)
                else:
                    if validation_id is None:
                        raise NativeBatchError("Explicit validation identity required")
                    result = await backend.validate_projection(db, build_id=build_id, validation_id=validation_id, dry_run=False)
                await db.commit()
    return {"phase": phase, "build_id": str(build_id), "result": result,
        "activation_performed": False, "quality_acceptance_created": False}


async def supersede_pending(db, *, logical_index, worker_id, limit=100, dry_run=True):
    """Retain an explicit real successor for old unleased work; never publish."""
    results = []
    async with backend._phase(db, dry_run) as operation:
        jobs = await queue.pending_jobs(db, logical_index=logical_index, limit=limit)
        from uuid import uuid4
        for job in jobs:
            newer = await db.scalar(sa.text("SELECT id FROM retrieval_publication_jobs_v2 "
                "WHERE logical_index=:logical AND paper_id=:paper AND sequence_number>:sequence "
                "ORDER BY sequence_number DESC LIMIT 1"),
                {"logical": logical_index, "paper": job["paper_id"], "sequence": job["sequence_number"]})
            if newer is None:
                continue
            claim = await queue.claim_job(db, job_id=str(job["id"]), claim_id=str(uuid4()),
                worker_id=worker_id, dry_run=False)
            results.append(await queue.record_result(db, claim_id=claim["claim_id"], outcome="superseded",
                successor_job_id=str(newer), dry_run=False))
        operation["changed"] = bool(results)
    return {"results": results, "dry_run": dry_run, "committed": False, "activation_performed": False}


async def finish_batch(db, plan, *, activation_event_id, dry_run=True):
    """Observe actual publication only; never create acceptance or activation."""
    async with backend._phase(db, dry_run) as operation:
        await verify_plan(db, plan, usable=False)
        outcomes = [await queue.record_result(db, claim_id=job.claim_id, outcome="published",
            activation_event_id=activation_event_id, dry_run=False) for job in plan.jobs]
        operation["changed"] = True
    return {"results": outcomes, "dry_run": dry_run, "committed": False, "activation_performed": False}


async def retry_batch(db, plan, *, error_code="operator_retry", dry_run=True):
    async with backend._phase(db, dry_run) as operation:
        await verify_plan(db, plan, usable=False)
        outcomes = [await queue.record_result(db, claim_id=job.claim_id, outcome="retry",
            error_code=error_code, dry_run=False) for job in plan.jobs]
        operation["changed"] = True
    return {"results": outcomes, "dry_run": dry_run, "committed": False, "activation_performed": False}
