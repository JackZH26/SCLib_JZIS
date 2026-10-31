"""Exact private storage projection shared by ingestion and future review reads.

Projection is lossless for both proposal contracts. It is not scientific
validation, canonical material assignment or permission to expose source text.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import text

INSERT_ORDER = ("bundles", "runs", "samples", "states", "protocols", "results",
                "conditions", "sample_relations", "condition_supports", "evidence", "dependencies")
COLUMNS = {
    "bundles": ("id", "work_id", "payload"),
    "runs": ("id", "job_id", "work_id", "bundle_id", "packet_hash", "model", "worker_state", "payload",
             "scientific_acceptance", "ml_training_eligible"),
    "samples": ("run_id", "local_id", "review_status", "payload"),
    "states": ("run_id", "local_id", "review_status", "payload", "sample_id"),
    "protocols": ("run_id", "local_id", "review_status", "payload"),
    "results": ("run_id", "local_id", "review_status", "payload", "sample_id", "state_id", "protocol_id", "quantity_kind"),
    "conditions": ("run_id", "state_id", "local_id", "payload"),
    "sample_relations": ("run_id", "local_id", "review_status", "payload", "from_sample_id", "to_sample_id", "relation"),
    "condition_supports": ("run_id", "local_id", "review_status", "payload", "result_id", "state_id", "condition_id", "relation"),
    "evidence": ("run_id", "ordinal", "path", "block_id", "payload"),
    "dependencies": ("run_id", "result_id", "target_id", "relation"),
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def projected_rows(packet):
    """Caller must verify the full extraction receipt before accepting a packet."""
    if packet["schema"] not in {"materials-ner-proposals/1", "materials-ner-proposals/2"}:
        raise ValueError("unknown proposal contract")
    if packet["scientific_acceptance"] or packet["ml_training_eligible"]:
        raise ValueError("proposal cannot self-approve")
    receipt = packet["receipt"]
    if packet["job_id"] != receipt["job_id"]:
        raise ValueError("proposal job binding mismatch")
    if packet["evidence"] != receipt.get("validation", {}).get("resolved_evidence", []):
        raise ValueError("proposal evidence projection mismatch")
    run = packet["run_id"]
    rows = {name: [] for name in INSERT_ORDER}
    rows["bundles"] = [dict(id=packet["bundle_hash"], work_id=packet["work_id"], payload=packet["bundle"])]
    rows["runs"] = [dict(id=run, job_id=packet["job_id"], work_id=packet["work_id"],
        bundle_id=packet["bundle_hash"], packet_hash=packet["packet_hash"], model=receipt["config"]["model"],
        worker_state=receipt["state"], payload=packet, scientific_acceptance=False, ml_training_eligible=False)]
    for name in ("samples", "states", "protocols", "results", "sample_relations", "condition_supports"):
        for item in packet["rows"].get(name, []):
            row = dict(run_id=run, local_id=item["local_id"], review_status=item["review_status"], payload=item)
            row.update({key: item["payload"][key] for key in COLUMNS[name][4:]})
            rows[name].append(row)
    if packet["schema"] == "materials-ner-proposals/2":
        for state in packet["rows"]["states"]:
            rows["conditions"].extend(dict(run_id=run, state_id=state["local_id"], local_id=c["id"], payload=c)
                                      for c in state["payload"]["conditions"])
    for ordinal, evidence in enumerate(packet["evidence"]):
        rows["evidence"].append(dict(run_id=run, ordinal=ordinal, path=evidence["path"],
                                     block_id=evidence["block_id"], payload=evidence))
    for result in packet["rows"]["results"]:
        for edge in result["payload"]["dependencies"]:
            row = dict(run_id=run, result_id=result["local_id"], target_id=edge["result_id"], relation=edge["relation"])
            if row not in rows["dependencies"]:
                rows["dependencies"].append(row)
    return rows


async def stored_rows(connection, packet):
    """Read every indexed and payload field, including relational absence."""
    result = {}
    for name in INSERT_ORDER:
        owner = "id" if name in {"bundles", "runs"} else "run_id"
        key = packet["bundle_hash"] if name == "bundles" else packet["run_id"]
        query = text(f"SELECT {','.join(COLUMNS[name])} FROM materials_ner_v1.{name} WHERE {owner}=:key")
        result[name] = [dict(row) for row in (await connection.execute(query, {"key": key})).mappings()]
    return result


def ordered(rows):
    return {name: sorted(items, key=canonical) for name, items in rows.items()}


async def verify_readback(connection, packet):
    expected, observed = ordered(projected_rows(packet)), ordered(await stored_rows(connection, packet))
    if expected != observed:
        names = [name for name in INSERT_ORDER if expected[name] != observed[name]]
        raise ValueError("proposal relational readback mismatch: " + ",".join(names))
    return dict(tables={name: len(rows) for name, rows in expected.items()}, rows_sha256=digest(expected))
