"""Database-owned, bounded inputs for RPS distribution registration.

No provider/path fetching. Caller-supplied row dictionaries are never used as
database authority; only exact targets from the validated binding plan are read.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from uuid import UUID

import sqlalchemy as sa

from models.db import Base
from services import research_distribution_contract as contract
from services import research_release_manifest as capsule
from services.research_freeze import _stored, _verify_pins
from services.research_release_spec import SPEC


def require(value, message="distribution_input_unavailable"):
    if not value:
        raise contract.ResearchDistributionError(message)


def capture_bytes(values):
    require(type(values) is dict and len(values) <= contract.MAX_DEPENDENCIES)
    result = {}
    total = 0
    for key, value in values.items():
        contract._hash(key)
        require(type(value) is bytes and len(value) <= capsule.LIMITS["file_bytes"])
        total += len(value)
        require(total <= contract.MAX_BYTES and hashlib.sha256(value).hexdigest() == key)
        result[key] = value
    return result


def capture_inputs(*, release, bindings, public_bundle, artifact_bytes, capsule_artifact_bytes):
    """Privately capture every mutable caller container before the first await."""
    documents = json.loads(contract._bounded({"release": release, "bindings": bindings, "public_bundle": public_bundle}))
    require(type(capsule_artifact_bytes) is dict and len(capsule_artifact_bytes) <= contract.MAX_CAPSULES)
    captured = {}
    combined = capture_bytes(artifact_bytes)
    documents["artifact_bytes"] = dict(combined)
    for sha, values in capsule_artifact_bytes.items():
        contract._hash(sha)
        captured[sha] = capture_bytes(values)
        combined.update(captured[sha])
    require(sum(map(len, combined.values())) <= contract.MAX_BYTES)
    documents["capsule_artifact_bytes"] = captured
    return documents


async def fetch_rows(db, table_name, identifiers, *, column=None, budget=None):
    """Batch indexed keys; preflight expanded sizes before receiving full JSON."""
    require(table_name in SPEC and len(identifiers) <= contract.MAX_DEPENDENCIES)
    if not identifiers:
        return []
    table = Base.metadata.tables[table_name]
    primary = "paper_id" if table_name == "paper_work_map" else "id"
    key = table.c[column or primary]
    keys = sorted(set(identifiers))
    budget = budget if budget is not None else {}
    result = []
    body = sa.func.to_jsonb(table.table_valued())
    for start in range(0, len(keys), 1000):
        batch = keys[start:start + 1000]
        values = [UUID(value) for value in batch] if isinstance(key.type, sa.UUID) else batch
        condition = key.in_(values)
        sizes = (await db.execute(sa.select(table.c[primary], sa.func.octet_length(sa.cast(body, sa.Text)))
                                 .where(condition).limit(contract.MAX_DEPENDENCIES + 1))).all()
        require(len(sizes) <= contract.MAX_DEPENDENCIES)
        for identifier, size in sizes:
            require(size <= capsule.LIMITS["file_bytes"])
            budget[(table_name, str(identifier))] = size
        require(len(budget) <= contract.MAX_DEPENDENCIES and sum(budget.values()) <= contract.MAX_BYTES)
        data = (await db.execute(sa.select(body).where(condition).limit(contract.MAX_DEPENDENCIES + 1))).scalars().all()
        require(len(data) == len(sizes))
        result.extend({"table": table_name, "row_id": str(item[primary]), "data": item,
                       "row_sha256": capsule.digest(item)} for item in data)
    return result


async def load_live_closure(db, roots):
    pending = {(row["table"], row["row_id"]) for row in roots}
    found, budget = {}, {}
    while pending:
        require(len(found) + len(pending) <= contract.MAX_DEPENDENCIES)
        grouped = defaultdict(set)
        for table_name, identifier in pending:
            grouped[table_name].add(identifier)
        current = []
        for table_name, identifiers in sorted(grouped.items()):
            rows = await fetch_rows(db, table_name, identifiers, budget=budget)
            require({row["row_id"] for row in rows} == identifiers)
            current.extend(rows)
        # The paper's accepted Work mapping is an owned identity relationship,
        # not an arbitrary row list supplied by the request.
        papers = {row["row_id"] for row in current if row["table"] == "papers"}
        current.extend(await fetch_rows(db, "paper_work_map", papers, column="paper_id", budget=budget))
        pending = set()
        for row in current:
            key = row["table"], row["row_id"]
            if key in found:
                require(found[key] == row)
            found[key] = row
            pending.update(capsule.dependencies(row["table"], row["data"]))
        pending -= found.keys()
    return [found[key] for key in sorted(found)]


async def load_capsules(db, expected, payloads):
    require(set(expected) == set(payloads))
    table = Base.metadata.tables["research_releases"]
    result = {}
    for sha in expected:
        ids = (await db.execute(sa.select(table.c.id).where(table.c.manifest_sha256 == sha).limit(2))).scalars().all()
        require(len(ids) == 1, "distribution_capsule_ambiguous_or_missing")
        stored = await _stored(db, "research_releases", ids[0])
        await _verify_pins(db, stored)
        result[sha] = {"manifest": stored["manifest"], "artifact_bytes": payloads[sha]}
    return result


async def build_inventory(db, *, expected_release_sha256, expected_bindings_sha256,
                          expected_public_bundle_sha256, **inputs):
    arguments = {key: inputs[key] for key in ("release", "bindings", "public_bundle")}
    arguments.update(expected_release_sha256=expected_release_sha256,
                     expected_bindings_sha256=expected_bindings_sha256,
                     expected_public_bundle_sha256=expected_public_bundle_sha256)
    plan = contract.distribution_loading_plan(**arguments)
    rows = await load_live_closure(db, plan["live_row_roots"])
    capsules = await load_capsules(db, plan["capsule_manifest_sha256s"], inputs["capsule_artifact_bytes"])
    return contract.verify_distribution_bindings(**arguments, rows=rows,
        artifact_bytes=inputs["artifact_bytes"], capsules=capsules)
