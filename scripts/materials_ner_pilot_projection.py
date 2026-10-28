#!/usr/bin/env python3
"""Versioned private review projection with shared, source-resolved evidence.

This is an empirical storage experiment, not a canonical database migration.
Model quotations and exact source spans are separate. Ambiguous or unavailable
locations remain unresolved; no source position or scientific approval is inferred.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))
from ingestion.materials_ner.sources import load_bundle, sha
from ingestion.materials_ner.validation import pointer_exists, resolve_quote
from materials_ner_pilot_quality import build_database, canonical, compact


def content_id(value):
    return sha(canonical(value).encode())


def project(root, label, output, annotations_path=None):
    if output.exists():
        raise ValueError("projection output already exists; select a new version")
    directory = root / "runs" / label
    raw = (directory / "observations.jsonl").read_bytes()
    rows = [json.loads(line) for line in raw.splitlines()]
    review_path = annotations_path or root / "assistant_review.json"
    annotations = json.loads(review_path.read_bytes()).get("annotations", {}) if review_path.exists() else {}
    annotations = {r["row_id"]: annotations[r["row_id"]] for r in rows if r["row_id"] in annotations}
    bundles = {r["bundle_sha256"]: load_bundle(root / "bundles" / (r["bundle_sha256"] + ".json")) for r in rows}
    # Every evidence location is resolved against the exact frozen bundle.
    captures = {}
    for paper in json.loads((root / "plan.json").read_bytes())["papers"]:
        capture = paper["source_capture"]
        if sha(Path(capture["local_path"]).read_bytes()) != capture["sha256"]:
            raise ValueError("source capture integrity failure")
        captures[capture["sha256"]] = capture
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".building.sqlite3")
    base_check = build_database(temporary, rows, annotations)
    before_bytes = temporary.stat().st_size
    statuses = Counter()
    expanded_quote_bytes = 0
    with sqlite3.connect(temporary) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript("""
        CREATE TABLE source_captures(id TEXT PRIMARY KEY, payload TEXT NOT NULL CHECK(json_valid(payload)));
        CREATE TABLE source_blocks(id TEXT PRIMARY KEY, capture_id TEXT NOT NULL REFERENCES source_captures(id), payload TEXT NOT NULL CHECK(json_valid(payload)));
        CREATE TABLE run_blocks(run_id TEXT NOT NULL REFERENCES runs(id), block_id TEXT NOT NULL, source_block_id TEXT NOT NULL REFERENCES source_blocks(id), PRIMARY KEY(run_id,block_id));
        CREATE TABLE reported_quotes(id TEXT PRIMARY KEY, quote TEXT NOT NULL);
        CREATE TABLE source_spans(id TEXT PRIMARY KEY, block_ref TEXT NOT NULL REFERENCES source_blocks(id), start_char INTEGER NOT NULL CHECK(start_char>=0), end_char INTEGER NOT NULL CHECK(end_char>start_char), quote TEXT NOT NULL, quote_sha256 TEXT NOT NULL, UNIQUE(block_ref,start_char,end_char));
        CREATE TABLE field_bindings(row_id TEXT NOT NULL REFERENCES result_proposals(row_id), entity_type TEXT NOT NULL CHECK(entity_type IN ('sample','state','protocol','result')), ordinal INTEGER NOT NULL CHECK(ordinal>=0), field_path TEXT NOT NULL CHECK(substr(field_path,1,1)='/'), original_block_id TEXT NOT NULL, reported_quote_id TEXT NOT NULL REFERENCES reported_quotes(id), span_id TEXT REFERENCES source_spans(id), location_status TEXT NOT NULL, field_present INTEGER NOT NULL CHECK(field_present IN (0,1)), PRIMARY KEY(row_id,entity_type,ordinal), CHECK((location_status='resolved')=(span_id IS NOT NULL)));
        CREATE TABLE row_context(row_id TEXT PRIMARY KEY REFERENCES result_proposals(row_id), payload TEXT NOT NULL CHECK(json_valid(payload)));
        CREATE TABLE projection_manifest(id TEXT PRIMARY KEY, payload TEXT NOT NULL CHECK(json_valid(payload)));
        """)
        for row in rows:
            bundle = bundles[row["bundle_sha256"]]
            if bundle.work_id != row["work_id"]:
                raise ValueError("row/source work mismatch")
            documents = {d.id: d for d in bundle.documents}
            blocks = {b.id: b for b in bundle.blocks}
            block_refs = {}
            for block in bundle.blocks:
                doc = documents[block.document_id]
                capture = captures.get(doc.source_sha256)
                if not capture:
                    raise ValueError("missing source capture closure")
                db.execute("INSERT OR IGNORE INTO source_captures VALUES(?,?)", (doc.source_sha256, canonical(capture)))
                meta = {"source_sha256":doc.source_sha256, "source_uri":doc.source_uri,
                        "publication_version":doc.publication_version, "version_status":doc.version_status,
                        "parser":doc.parser, "locator":block.locator, "text_sha256":block.sha256}
                block_ref = content_id(meta)
                block_refs[block.id] = block_ref
                db.execute("INSERT OR IGNORE INTO source_blocks VALUES(?,?,?)", (block_ref, doc.source_sha256, canonical(meta)))
                db.execute("INSERT OR IGNORE INTO run_blocks VALUES(?,?,?)", (row["job_id"], block.id, block_ref))
            context = {k:v for k,v in compact(row).items() if k not in {"sample","state","protocol","result"}}
            db.execute("INSERT INTO row_context VALUES(?,?)", (row["row_id"],canonical(context)))
            for entity in ("sample","state","protocol","result"):
                for ordinal, evidence in enumerate(row[entity]["evidence"]):
                    quote = evidence["quote"]
                    quote_id = sha(quote.encode())
                    expanded_quote_bytes += len(quote.encode())
                    db.execute("INSERT OR IGNORE INTO reported_quotes VALUES(?,?)", (quote_id,quote))
                    block = blocks.get(evidence["block_id"])
                    span_id = None
                    status = "source_block_unavailable"
                    if block:
                        try:
                            start, end = resolve_quote(block.text, quote)
                        except ValueError as error:
                            status = str(error)
                        else:
                            exact_quote = block.text[start:end]
                            span_id = content_id([block_refs[block.id],start,end])
                            db.execute("INSERT OR IGNORE INTO source_spans VALUES(?,?,?,?,?,?)", (
                                span_id,block_refs[block.id],start,end,exact_quote,sha(exact_quote.encode())))
                            status = "resolved"
                    statuses[status] += 1
                    db.execute("INSERT INTO field_bindings VALUES(?,?,?,?,?,?,?,?,?)", (
                        row["row_id"],entity,ordinal,evidence["field"],evidence["block_id"],quote_id,
                        span_id,status,int(pointer_exists(row[entity],evidence["field"]))))
        # Compatibility view reconstructs the original three-field evidence item.
        db.execute("DROP TABLE evidence")
        db.execute("""CREATE VIEW evidence AS SELECT b.row_id,b.entity_type,b.ordinal,
            json_object('block_id',b.original_block_id,'field',b.field_path,'quote',q.quote) payload
            FROM field_bindings b JOIN reported_quotes q ON q.id=b.reported_quote_id""")
        for row in rows:
            rebuilt = json.loads(db.execute("SELECT payload FROM row_context WHERE row_id=?", (row["row_id"],)).fetchone()[0])
            for entity, table in (("sample","samples"),("state","states"),("protocol","protocols"),("result","result_proposals")):
                if entity == "result":
                    payload = db.execute("SELECT payload FROM result_proposals WHERE row_id=?", (row["row_id"],)).fetchone()[0]
                else:
                    payload = db.execute(f"SELECT payload FROM {table} WHERE run_id=? AND id=?", (row["job_id"],row[entity]["id"])).fetchone()[0]
                body = json.loads(payload)
                ev = [json.loads(x[0]) for x in db.execute("SELECT payload FROM evidence WHERE row_id=? AND entity_type=? ORDER BY ordinal", (row["row_id"],entity))]
                if ev:
                    body["evidence"] = ev
                rebuilt[entity] = body
            if rebuilt != compact(row):
                raise ValueError("lossless meaningful-row reconstruction failed")
        binding_count = db.execute("SELECT count(*) FROM field_bindings").fetchone()[0]
        spans = db.execute("SELECT count(*) FROM source_spans").fetchone()[0]
        unique_quotes, stored_quote_bytes = db.execute("SELECT count(*),coalesce(sum(length(cast(quote as blob))),0) FROM reported_quotes").fetchone()
        exact_span_bytes = db.execute("SELECT coalesce(sum(length(cast(quote as blob))),0) FROM source_spans").fetchone()[0]
        fk = db.execute("PRAGMA foreign_key_check").fetchall()
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if fk or integrity != "ok":
            raise ValueError("shared-evidence database integrity failure")
        report = {"schema":"materials-shared-evidence-projection/2.2", "run_label":label,
                  "field_binding_statistics_scope":"Main sample/state/protocol/result fields; linked auxiliary procedure declarations and their evidence are preserved separately in row_context and the original entity graph.",
                  "projection_code_sha256":sha(Path(__file__).read_bytes()),
                  "relational_projection_code_sha256":sha(Path(__file__).with_name("materials_ner_pilot_quality.py").read_bytes()),
                  "input_observations_sha256":sha(raw), "source_bundles":sorted(bundles),
                  "field_review_sha256":sha(review_path.read_bytes()) if review_path.exists() else None,
                  "field_review_rows":len(annotations),
                  "source_capture_hashes_verified":len(captures), "results":len(rows),
                  "field_bindings":binding_count, "source_spans":spans,
                  "reported_quote_variants":unique_quotes, "location_statuses":dict(statuses),
                  "expanded_quote_bytes":expanded_quote_bytes, "stored_reported_quote_bytes":stored_quote_bytes,
                  "stored_exact_span_bytes":exact_span_bytes,
                  "quote_bytes_fraction_saved":1-(stored_quote_bytes+exact_span_bytes)/expanded_quote_bytes if expanded_quote_bytes else 0,
                  "foreign_key_violations":len(fk), "integrity_check":integrity,
                  "meaningful_row_and_evidence_round_trip":True, "source_offsets_are_unicode_codepoints":True,
                  "base_projection_checks":base_check, "prior_database_bytes":before_bytes,
                  "scientific_acceptance":False, "ml_training_eligible":False,
                  "canonical_migration":False, "canonical_identity_resolved":False}
        db.execute("INSERT INTO projection_manifest VALUES(?,?)", ("manifest",canonical(report)))
        db.commit()
        db.execute("VACUUM")
    report["database_bytes"] = temporary.stat().st_size
    report["database_sha256"] = sha(temporary.read_bytes())
    temporary.replace(output)
    output.with_suffix(".report.json").write_text(json.dumps(report,indent=2)+"\n")
    return report


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--label",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--annotations",type=Path)
    args=parser.parse_args()
    print(canonical(project(args.root,args.label,args.output,args.annotations)))
