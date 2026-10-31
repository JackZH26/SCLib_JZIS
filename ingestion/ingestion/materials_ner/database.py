"""Sync immutable proposal packets to the existing private Postgres database."""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess

from .contract import canonical
from .proposals import ProposalDatabase, import_packet
from .sources import private_write
from .store import Store


def bridge(ssh_host: str, request: dict) -> dict:
    repo = Path(__file__).resolve().parents[3]
    schema = (repo / "api/models/materials_ner_proposals_v1.py").read_text()
    source = (repo / "scripts/materials_ner_db_bridge.py").read_text()
    # Each source is compiled separately so its __future__ imports remain valid.
    command = f"exec(compile({schema!r},'<frozen-schema>','exec')); exec(compile({source!r},'<proposal-bridge>','exec'))"
    remote = shlex.join(["docker", "exec", "-i", "sclib-api", "python", "-c", command])
    response = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                               ssh_host, remote], input=canonical(request).encode(),
                              capture_output=True, timeout=180)
    if response.returncode:
        try:
            failure = json.loads(response.stdout)
        except ValueError:
            failure = {}
        # Class and SQLSTATE only, never credential-bearing connection text.
        raise ValueError("proposal database bridge failed: "
                         f"{failure.get('error_class', 'transport_failure')} "
                         f"{failure.get('sqlstate')}; no confirmed commit")
    result = json.loads(response.stdout)
    if not result.get("ok"):
        raise ValueError("proposal database operation not confirmed")
    return result


def ingest_job(store: Store, job_id: str, *, database_ssh_host: str | None = None):
    """Import locally unless a separate, explicit database destination is supplied.

    A source transport host must never grant database write authority. Batch
    runners call this function without a remote destination, including on resume.
    The keyword-only remote option belongs to the explicit database operator path.
    """
    packet = import_packet(store, job_id)
    database = ProposalDatabase(store.root)
    local = database.ingest(packet)
    result = {"local": local, "remote": None,
              "packet_hash": packet["packet_hash"],
              "local_destination": str(database.path.resolve()),
              "candidate_results": len(packet["rows"]["results"]),
              "pending_review_results": sum(row["review_status"] == "pending_review"
                                            for row in packet["rows"]["results"]),
              "quarantined_results": sum(row["review_status"] == "quarantined"
                                         for row in packet["rows"]["results"])}
    if database_ssh_host:
        result["remote"] = bridge(database_ssh_host, {"action": "ingest", "packet": packet})
        if (result["remote"].get("packet_hash") != packet["packet_hash"]
                or not result["remote"].get("readback_verified")):
            raise ValueError("remote packet not verified")
    # Local replay must not overwrite a historical remote-import receipt.
    receipt_lane = "imports" if database_ssh_host else "local-imports"
    private_write(store.root / receipt_lane / f'{packet["run_id"]}.json', canonical(result).encode())
    return result
