"""Source-scoped relational proposal database, separate from the work queue.

Technical validation never grants scientific acceptance. Each imported attempt
is immutable, including failures; identity and review decisions are future,
append-only actions. No legacy material/claim is overwritten here.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3

from .contract import canonical, digest, parse_extraction
from .sources import load_bundle, sha
from .store import Store

SCHEMA_VERSION = "materials-ner-proposals/1"
RELATION_SCHEMA_VERSION = "materials-ner-proposals/2"
RELATION_FORMATS = {"materials-ner-inline/3", "materials-ner-inline/2", "materials-ner-inline/1", "materials-ner-shared/9", "materials-ner-shared/10", "materials-semantic-graph/1", "materials-source-choice-graph/1", "materials-source-item-transcript/5", "materials-source-item-transcript/4", "materials-source-item-transcript/3", "materials-staged-field-revision/1", "materials-source-item-transcript/2", "materials-source-item-transcript/1", "materials-ner-shared/4", "materials-ner-shared/5", "materials-ner-shared/6", "materials-ner-shared/7", "materials-ner-shared/8", "materials-relational-edits/1", "materials-relational-edits/2", "materials-source-field-edits/1", "materials-source-field-edits/2", "materials-scoped-review/1", "materials-scoped-review/2", "materials-scoped-review/3", "materials-source-field-edits/3", "materials-source-field-edits/4"}
TABLES = ("bundles", "runs", "samples", "states", "protocols", "results", "evidence", "dependencies",
          "conditions", "sample_relations", "condition_supports")
RELATION_FORMATS.add('materials-reviewed-reader-projection/1')
RELATION_FORMATS.add('materials-reviewed-reader-projection/2')
RELATION_FORMATS.add('materials-source-projector-proposal/1')


def review_rows(extraction, validation: dict) -> dict:
    """Propagate technical defects through sample/state/protocol/dependency links."""
    groups = {name: getattr(extraction, name) for name in ("samples", "states", "protocols", "results")}
    relational = extraction.schema_version in {"materials-ner/6", "materials-ner/7", "materials-ner/8", "materials-ner/9", "materials-ner/10", "materials-ner/11", "materials-ner/12", "materials-ner/13", "materials-ner/14", "materials-ner/15"}
    if relational:
        groups.update({name: getattr(extraction, name) for name in ("sample_relations", "condition_supports")})
    issues = validation.get("issues", [])
    reasons = {}
    global_issues = [i for i in issues if not any(
        i["path"].startswith("/" + name + "/") for name in groups)]
    for name, items in groups.items():
        for index, item in enumerate(items):
            prefix = f"/{name}/{index}"
            reasons[name, item.id] = {i["code"] for i in issues if (
                i["path"] == prefix or i["path"].startswith(prefix + "/"))}
            reasons[name, item.id].update(i["code"] for i in global_issues)
    # Ownership defects propagate only along explicit source relationships.
    if relational:
        changed = True
        while changed:
            before = sum(map(len, reasons.values()))
            for relation in extraction.sample_relations:
                key = ("sample_relations", relation.id)
                owners = (relation.from_sample_id, relation.to_sample_id)
                if any(reasons["samples", identifier] for identifier in owners):
                    reasons[key].add("related_sample_has_validation_issues")
                if reasons[key]:
                    for identifier in owners:
                        reasons["samples", identifier].add("sample_relation_has_validation_issues")
            changed = before != sum(map(len, reasons.values()))
    for state in extraction.states:
        if reasons["samples", state.sample_id]:
            reasons["states", state.id].add("sample_has_validation_issues")
    for procedure in extraction.protocols:
        if reasons["protocols", procedure.id]:
            for use in getattr(procedure, "context_uses", []):
                reasons["states", use.state_id].add("condition_method_has_validation_issues")
    for result in extraction.results:
        for name, identifier in (("samples", result.sample_id), ("states", result.state_id),
                                 ("protocols", result.protocol_id)):
            if reasons[name, identifier]:
                reasons["results", result.id].add(name.rstrip("s") + "_has_validation_issues")
    # Derived labels inherit invalid inputs, including transitive dependencies.
    changed = True
    while changed:
        before = sum(map(len, reasons.values()))
        changed = False
        if relational:
            for support in extraction.condition_supports:
                key = ("condition_supports", support.id)
                result_key, state_key = ("results", support.result_id), ("states", support.state_id)
                if reasons[result_key]: reasons[key].add("supporting_result_has_validation_issues")
                if reasons[state_key]: reasons[key].add("supported_state_has_validation_issues")
                if reasons[key]:
                    reasons[result_key].add("condition_support_has_validation_issues")
                    reasons[state_key].add("condition_support_has_validation_issues")
            for result in extraction.results:
                if reasons["states", result.state_id]:
                    reasons["results", result.id].add("state_has_validation_issues")
        for result in extraction.results:
            key = ("results", result.id)
            if ("derived_input_has_validation_issues" not in reasons[key]
                    and any(edge.relation == "derived_from" and reasons["results", edge.result_id]
                            for edge in result.dependencies)):
                reasons[key].add("derived_input_has_validation_issues")
                changed = True
        changed = changed or before != sum(map(len, reasons.values()))
    return {name: [{
        "local_id": item.id, "payload": item.model_dump(),
        "review_status": "quarantined" if reasons[name, item.id] else "pending_review",
        "issues": sorted(reasons[name, item.id]),
        "normalized": {
            key: value for key, value in validation.get("normalized", {}).items()
            if key.startswith(f"/{name}/{index}/")
        },
    } for index, item in enumerate(items)] for name, items in groups.items()}


def import_packet(store: Store, job_id: str) -> dict:
    with store.connect() as db:
        found = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if found is None or not found["result_path"] or found["state"] in {"running", "queued"}:
        raise ValueError("job has no terminal receipt")
    job = dict(found)
    receipt_raw = (store.root / job["result_path"]).read_bytes()
    if sha(receipt_raw) != job["result_hash"]:
        raise ValueError("receipt hash mismatch")
    receipt = json.loads(receipt_raw)
    bundle = load_bundle(store.root / "bundles" / f'{job["bundle_hash"]}.json')
    if digest(bundle.model_dump()) != job["bundle_hash"] or bundle.work_id != job["work_id"]:
        raise ValueError("bundle identity mismatch")
    if not bundle.work_id.startswith("arxiv:"):
        raise ValueError("this campaign only admits arXiv")
    output_path = (store.root / job["result_path"]).parent / "output.json"
    raw_output = output_path.read_text() if output_path.exists() else None
    if raw_output is not None and sha(raw_output.encode()) != receipt.get("raw_output_sha256"):
        raise ValueError("raw output not hash-bound to this receipt")
    from .evidence_patch import verify_applied_patch
    from .inventory_links import verify_inventory_projection
    verify_inventory_projection(receipt,bundle)
    verify_applied_patch(receipt,bundle,raw_output)
    rows = {name: [] for name in ("samples", "states", "protocols", "results")}
    if "extraction" in receipt:
        extraction = parse_extraction(receipt["extraction"])
        if extraction.work_id != bundle.work_id:
            # Never turn a mismatched response into bound scientific entities.
            pass
        else:
            rows = review_rows(extraction, receipt["validation"])
    packet = {
        "schema": (RELATION_SCHEMA_VERSION if receipt.get("config", {}).get("output_format") in RELATION_FORMATS
                   else SCHEMA_VERSION), "run_id": job["result_hash"],
        "job_id": job_id, "work_id": job["work_id"], "bundle_hash": job["bundle_hash"],
        "bundle": bundle.model_dump(), "receipt": receipt, "raw_output": raw_output,
        "rows": rows,
        "evidence": receipt.get("validation", {}).get("resolved_evidence", []),
        "scientific_acceptance": False, "ml_training_eligible": False,
    }
    packet["packet_hash"] = digest(packet)
    return packet


def verify_packet(packet: dict):
    body = {key: value for key, value in packet.items() if key != "packet_hash"}
    if packet.get("schema") not in {SCHEMA_VERSION, RELATION_SCHEMA_VERSION} or digest(body) != packet.get("packet_hash"):
        raise ValueError("invalid proposal packet")
    relational = packet["receipt"].get("config", {}).get("output_format") in RELATION_FORMATS
    if packet["schema"] != (RELATION_SCHEMA_VERSION if relational else SCHEMA_VERSION):
        raise ValueError("proposal packet version does not match extraction workflow")
    if digest(packet["bundle"]) != packet["bundle_hash"]:
        raise ValueError("bundle hash mismatch")
    if digest(packet["receipt"]) != packet["run_id"]:
        raise ValueError("receipt hash mismatch")
    if packet["work_id"] != packet["bundle"]["work_id"] or not packet["work_id"].startswith("arxiv:"):
        raise ValueError("invalid campaign work identity")
    if packet["scientific_acceptance"] or packet["ml_training_eligible"]:
        raise ValueError("proposal cannot self-approve")
    if packet["raw_output"] is not None:
        if sha(packet["raw_output"].encode()) != packet["receipt"].get("raw_output_sha256"):
            raise ValueError("raw output mismatch")
    receipt = packet["receipt"]
    if receipt["work_id"] != packet["work_id"] or receipt["bundle_sha256"] != packet["bundle_hash"]:
        raise ValueError("receipt work binding mismatch")
    from .evidence_patch import verify_applied_patch
    from .inventory_links import verify_inventory_projection
    from .sources import Bundle
    from .reviewed_proposals import verify_receipt as verify_reviewed_receipt
    from .projector_proposals import verify_receipt as verify_projector_receipt
    verify_reviewed_receipt(receipt, Bundle.model_validate(packet['bundle']), packet['raw_output'])
    verify_projector_receipt(receipt, Bundle.model_validate(packet['bundle']), packet['raw_output'])
    verify_inventory_projection(receipt,Bundle.model_validate(packet["bundle"]))
    verify_applied_patch(receipt,Bundle.model_validate(packet["bundle"]),packet["raw_output"])
    expected = {name: [] for name in ("samples", "states", "protocols", "results")}
    if receipt.get('config', {}).get('output_format') == 'materials-source-projector-proposal/1':
        expected.update(sample_relations=[], condition_supports=[])
        if packet['job_id'] != receipt['job_id']:
            raise ValueError('proposal job identity mismatch')
    if "extraction" in receipt:
        extraction = parse_extraction(receipt["extraction"])
        if extraction.work_id == packet["work_id"]:
            from .task_features import verify_assessment
            assessment = receipt.get('training_assessment', {}).get('task_feature_assessment')
            config = receipt.get('config', {})
            workflow = config.get('workflow', '')
            expected_audit = (config.get('task_feature_version') is not None and (
                workflow == 'single_pass_v1' or workflow.startswith('inventory_v')
                or workflow.startswith('source_item_stages_v')))
            if assessment is not None or expected_audit:
                verify_assessment(assessment, extraction, Bundle.model_validate(packet['bundle']),
                                  receipt['validation'], config)
            expected = review_rows(extraction, receipt["validation"])
    if expected != packet["rows"]:
        raise ValueError("proposal row derivation mismatch")
    if packet['evidence'] != receipt.get('validation', {}).get('resolved_evidence', []):
        raise ValueError('proposal evidence derivation mismatch')


SQLITE_DDL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS bundles(
 id TEXT PRIMARY KEY, work_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL, work_id TEXT NOT NULL,
 bundle_id TEXT NOT NULL REFERENCES bundles(id), packet_hash TEXT NOT NULL,
 model TEXT NOT NULL, worker_state TEXT NOT NULL, payload TEXT NOT NULL,
 scientific_acceptance INTEGER NOT NULL DEFAULT 0 CHECK(scientific_acceptance=0),
 ml_training_eligible INTEGER NOT NULL DEFAULT 0 CHECK(ml_training_eligible=0));
CREATE TABLE IF NOT EXISTS samples(
 run_id TEXT NOT NULL REFERENCES runs(id), local_id TEXT NOT NULL,
 review_status TEXT NOT NULL CHECK(review_status IN ('pending_review','quarantined')),
 payload TEXT NOT NULL, PRIMARY KEY(run_id,local_id));
CREATE TABLE IF NOT EXISTS states(
 run_id TEXT NOT NULL, local_id TEXT NOT NULL, sample_id TEXT NOT NULL,
 review_status TEXT NOT NULL CHECK(review_status IN ('pending_review','quarantined')),
 payload TEXT NOT NULL, PRIMARY KEY(run_id,local_id),
 UNIQUE(run_id,local_id,sample_id),
 FOREIGN KEY(run_id,sample_id) REFERENCES samples(run_id,local_id));
CREATE TABLE IF NOT EXISTS protocols(
 run_id TEXT NOT NULL REFERENCES runs(id), local_id TEXT NOT NULL,
 review_status TEXT NOT NULL CHECK(review_status IN ('pending_review','quarantined')),
 payload TEXT NOT NULL, PRIMARY KEY(run_id,local_id));
CREATE TABLE IF NOT EXISTS results(
 run_id TEXT NOT NULL, local_id TEXT NOT NULL, sample_id TEXT NOT NULL,
 state_id TEXT NOT NULL, protocol_id TEXT NOT NULL, quantity_kind TEXT NOT NULL,
 review_status TEXT NOT NULL CHECK(review_status IN ('pending_review','quarantined')),
 payload TEXT NOT NULL, PRIMARY KEY(run_id,local_id),
 FOREIGN KEY(run_id,sample_id) REFERENCES samples(run_id,local_id),
 FOREIGN KEY(run_id,state_id,sample_id) REFERENCES states(run_id,local_id,sample_id),
 FOREIGN KEY(run_id,protocol_id) REFERENCES protocols(run_id,local_id));
CREATE TABLE IF NOT EXISTS evidence(
 run_id TEXT NOT NULL REFERENCES runs(id), ordinal INTEGER NOT NULL,
 path TEXT NOT NULL, block_id TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(run_id,ordinal));
CREATE TABLE IF NOT EXISTS dependencies(
 run_id TEXT NOT NULL, result_id TEXT NOT NULL, target_id TEXT NOT NULL,
 relation TEXT NOT NULL CHECK(relation IN ('derived_from','same_measurement','compares_with')),
 PRIMARY KEY(run_id,result_id,target_id,relation),
 FOREIGN KEY(run_id,result_id) REFERENCES results(run_id,local_id),
 FOREIGN KEY(run_id,target_id) REFERENCES results(run_id,local_id));
CREATE INDEX IF NOT EXISTS runs_work ON runs(work_id);
CREATE INDEX IF NOT EXISTS results_review ON results(review_status,quantity_kind);
CREATE UNIQUE INDEX IF NOT EXISTS results_state_identity ON results(run_id,local_id,state_id);
CREATE TABLE IF NOT EXISTS conditions(
 run_id TEXT NOT NULL, state_id TEXT NOT NULL, local_id TEXT NOT NULL,
 payload TEXT NOT NULL, PRIMARY KEY(run_id,state_id,local_id),
 FOREIGN KEY(run_id,state_id) REFERENCES states(run_id,local_id));
CREATE TABLE IF NOT EXISTS sample_relations(
 run_id TEXT NOT NULL, local_id TEXT NOT NULL, from_sample_id TEXT NOT NULL, to_sample_id TEXT NOT NULL,
 relation TEXT NOT NULL CHECK(relation='component_of'),
 review_status TEXT NOT NULL CHECK(review_status IN ('pending_review','quarantined')),
 payload TEXT NOT NULL, PRIMARY KEY(run_id,local_id),
 UNIQUE(run_id,from_sample_id,to_sample_id,relation), CHECK(from_sample_id<>to_sample_id),
 FOREIGN KEY(run_id,from_sample_id) REFERENCES samples(run_id,local_id),
 FOREIGN KEY(run_id,to_sample_id) REFERENCES samples(run_id,local_id));
CREATE TABLE IF NOT EXISTS condition_supports(
 run_id TEXT NOT NULL, local_id TEXT NOT NULL, result_id TEXT NOT NULL,
 state_id TEXT NOT NULL, condition_id TEXT NOT NULL, relation TEXT NOT NULL CHECK(relation='measures'),
 review_status TEXT NOT NULL CHECK(review_status IN ('pending_review','quarantined')),
 payload TEXT NOT NULL, PRIMARY KEY(run_id,local_id), UNIQUE(run_id,result_id,state_id,condition_id),
 FOREIGN KEY(run_id,result_id,state_id) REFERENCES results(run_id,local_id,state_id),
 FOREIGN KEY(run_id,state_id,condition_id) REFERENCES conditions(run_id,state_id,local_id));
"""


def require_ingest_enabled(path):
    """Preparation-only namespaces may be initialized, but cannot import rows."""
    path = Path(path)
    for root in {path.parent.resolve(), path.resolve().parent}:
        if any((p / 'STAGING_PREPARATION.json').exists() for p in (root, *root.parents)):
            raise ValueError('staging_preparation_only')


class ProposalDatabase:
    def __init__(self, root: Path):
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.path = root / "proposals.sqlite3"
        with self.connect() as db:
            db.executescript(SQLITE_DDL)
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def ingest(self, packet: dict):
        # Preparation-only namespaces may be initialized and inspected, but no
        # packet (including direct callers and nested/symlink paths) may enter.
        require_ingest_enabled(self.path)
        verify_packet(packet)
        identifier = packet["run_id"]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT packet_hash FROM runs WHERE id=?", (identifier,)).fetchone()
            if previous:
                if previous[0] != packet["packet_hash"]:
                    raise ValueError("immutable proposal collision")
                return {"run_id": identifier, "inserted": False}
            db.execute("INSERT OR IGNORE INTO bundles VALUES(?,?,?)",
                       (packet["bundle_hash"], packet["work_id"], canonical(packet["bundle"])))
            db.execute("""INSERT INTO runs
                (id,job_id,work_id,bundle_id,packet_hash,model,worker_state,payload) VALUES(?,?,?,?,?,?,?,?)""",
                       (identifier, packet["job_id"], packet["work_id"], packet["bundle_hash"],
                        packet["packet_hash"], packet["receipt"]["config"]["model"],
                        packet["receipt"]["state"], canonical(packet)))
            for name in ("samples", "states", "protocols", "results"):
                for row in packet["rows"][name]:
                    payload = row["payload"]
                    columns = ["run_id", "local_id", "review_status", "payload"]
                    values = [identifier, row["local_id"], row["review_status"], canonical(row)]
                    for column in (["sample_id"] if name == "states" else
                                   ["sample_id", "state_id", "protocol_id", "quantity_kind"]
                                   if name == "results" else []):
                        columns.append(column)
                        values.append(payload[column])
                    db.execute(f"INSERT INTO {name} ({','.join(columns)}) VALUES({','.join('?' for _ in values)})",
                               values)
            if packet["schema"] == RELATION_SCHEMA_VERSION:
                for state in packet["rows"]["states"]:
                    for condition in state["payload"]["conditions"]:
                        db.execute("INSERT INTO conditions VALUES(?,?,?,?)",
                            (identifier, state["local_id"], condition["id"], canonical(condition)))
                for name, fields in (("sample_relations", ["from_sample_id", "to_sample_id", "relation"]),
                                     ("condition_supports", ["result_id", "state_id", "condition_id", "relation"])):
                    for row in packet["rows"].get(name, []):
                        columns = ["run_id", "local_id", "review_status", "payload"] + fields
                        values = [identifier, row["local_id"], row["review_status"], canonical(row)] + [row["payload"][f] for f in fields]
                        db.execute(f"INSERT INTO {name} ({','.join(columns)}) VALUES({','.join('?' for _ in values)})", values)
            for ordinal, evidence in enumerate(packet["evidence"]):
                db.execute("INSERT INTO evidence VALUES(?,?,?,?,?)",
                           (identifier, ordinal, evidence["path"], evidence["block_id"], canonical(evidence)))
            for result in packet["rows"]["results"]:
                for edge in result["payload"]["dependencies"]:
                    db.execute("INSERT OR IGNORE INTO dependencies VALUES(?,?,?,?)",
                               (identifier, result["local_id"], edge["result_id"], edge["relation"]))
        return {"run_id": identifier, "inserted": True}

    def summary(self):
        with self.connect() as db:
            counts = {name: db.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in TABLES}
            works = db.execute("SELECT count(DISTINCT work_id) FROM runs").fetchone()[0]
            states = dict(db.execute("SELECT review_status,count(*) FROM results GROUP BY review_status"))
        return {"schema": RELATION_SCHEMA_VERSION, "database": str(self.path), "tables": counts,
                "works": works, "result_review_states": states,
                "scientific_acceptance": False, "ml_training_eligible": False}
