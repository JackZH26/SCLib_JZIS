#!/usr/bin/env python3
"""Inspect an empirical pilot without promoting proposals or inventing Gold.

Produces a compact, foreign-key-checked SQLite review dataset, JSONL and HTML.
Numeric anchor hits are diagnostic candidate retrieval, never precision/recall.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import re
import sqlite3
import statistics
import unicodedata


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def compact(value):
    """Omit optional empty content, preserving explicit statuses, false and zero."""
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items() if v is not None and v != [] and v != {}}
    if isinstance(value, list):
        return [compact(v) for v in value]
    return value


def definition_for(row):
    return row["result"].get("definition", row["protocol"])


def formula_key(value):
    # Presentation-only matching, not composition normalization or identity.
    text = unicodedata.normalize("NFKC", value)
    text = re.sub(r"\\(?:mathrm|text|rm|operatorname)", "", text)
    return re.sub(r"[\s${}_\\-]", "", text)


def method_class(value):
    text = (value or "").lower()
    if "anisotropic" in text:
        return "anisotropic_Migdal_Eliashberg"
    if "isotropic" in text:
        return "isotropic_Migdal_Eliashberg"
    if "allen" in text or "dynes" in text:
        return "Allen-Dynes"
    if "resist" in text or "transport" in text:
        return "resistivity"
    if any(w in text for w in ("magnet", "susceptibility", "squid")):
        return "magnetization"
    if "specific heat" in text or "heat capacity" in text:
        return "specific_heat"
    return None


def same_source_value(quantity, anchor):
    # Explicit unit families only. This is diagnostic value matching, never
    # evidence that two observations share a sample, state, or derivation.
    scales = {"K":("temperature",1),"mK":("temperature",.001),
              "Å":("length",.1),"nm":("length",1),"1":("dimensionless",1)}
    actual_unit, expected_unit = quantity["unit"], anchor.get("unit","K")
    actual, expected = scales.get(actual_unit), scales.get(expected_unit)
    if actual and expected and actual[0]==expected[0]:
        return abs(quantity["value"]*actual[1]-anchor["value"]*expected[1])<1e-8
    return actual_unit==expected_unit and abs(quantity["value"]-anchor["value"])<1e-8


def compare_anchors(rows, reference):
    out = []
    for anchor in reference["anchors"]:
        candidates = []
        for row in rows:
            r, sample = row["result"], row["sample"]
            q = r["quantity"]
            if row["work_id"] != anchor["work_id"] or r["quantity_kind"] != anchor["kind"]:
                continue
            # This family-only alias is disclosed; it does NOT resolve delta or
            # establish a usable composition for ML.
            key, expected = formula_key(sample["formula_raw"]), formula_key(anchor["formula"])
            formula_match = key == expected or (expected == "La2PrNi2O7" and key.startswith(expected))
            if not formula_match or q["relation"] != "exact" or q["value"] is None:
                continue
            if not same_source_value(q,anchor):
                continue
            factor = {"K": 1, "mK": .001}.get(q["unit"],1)
            reported_method=row["protocol"].get("method_class","unspecified")
            if reported_method=="unspecified" or anchor["method"] not in {"resistivity","magnetization","specific_heat"}:
                reported_method=method_class(row["protocol"]["method"])
            fields = {"method": None if anchor["method"] is None else reported_method == anchor["method"]}
            for k, actual in [("criterion", definition_for(row)["criterion"]), ("origin", r["origin"])]:
                if k in anchor:
                    fields[k] = actual == anchor[k]
            if "uncertainty" in anchor:
                u = q["uncertainty"]
                fields["uncertainty"] = u is not None and all(abs(u[k] * factor - anchor["uncertainty"]) < 1e-10 for k in ("minus", "plus"))
            if "sample_label" in anchor:
                fields["sample_label"] = anchor["sample_label"].lower() in (sample["label"] or "").lower()
            if "transition_stage" in anchor:
                fields["transition_stage"]=any(qf.get("kind")=="transition_stage" and qf.get("stage")==anchor["transition_stage"] for qf in r.get("qualifiers",[]))
            if "mu_star" in anchor:
                fields["mu_star_value"]=any(p["kind"]=="coulomb_pseudopotential" and p["quantity"]["value"]==anchor["mu_star"] for p in row["protocol"].get("parameters",[]))
            if "pressure_gpa" in anchor:
                fields["pressure"] = any(c["kind"] == "pressure" and c["role"] == "measurement"
                                         and c["quantity"]["unit"] == "GPa" and c["quantity"]["value"] is not None
                                         and abs(c["quantity"]["value"] - anchor["pressure_gpa"]) < 1e-8
                                         for c in row["state"]["conditions"])
            candidates.append({"row_id": row["row_id"], "technical_review_status": row["technical_review_status"],
                               "checks": fields, "joint_scientific_acceptance": False})
        out.append({"anchor_id": anchor["id"], "work_id": anchor["work_id"], "value": anchor["value"],
                    "formula": anchor["formula"], "method": anchor["method"], "candidates": candidates,
                    "numeric_formula_hit": bool(candidates)})
    return out


def build_database(path, rows, annotations):
    temp = path.with_suffix(".building.sqlite3")
    temp.unlink(missing_ok=True)
    with sqlite3.connect(temp) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript("""
        CREATE TABLE runs(id TEXT PRIMARY KEY, work_id TEXT NOT NULL, bundle_sha256 TEXT NOT NULL, receipt_sha256 TEXT NOT NULL);
        CREATE TABLE samples(run_id TEXT NOT NULL REFERENCES runs(id), id TEXT NOT NULL, payload TEXT NOT NULL CHECK(json_valid(payload)), PRIMARY KEY(run_id,id));
        CREATE TABLE states(run_id TEXT NOT NULL, id TEXT NOT NULL, sample_id TEXT NOT NULL, payload TEXT NOT NULL CHECK(json_valid(payload)), PRIMARY KEY(run_id,id), UNIQUE(run_id,id,sample_id), FOREIGN KEY(run_id,sample_id) REFERENCES samples(run_id,id));
        CREATE TABLE protocols(run_id TEXT NOT NULL REFERENCES runs(id), id TEXT NOT NULL, payload TEXT NOT NULL CHECK(json_valid(payload)), PRIMARY KEY(run_id,id));
        CREATE TABLE result_proposals(row_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, id TEXT NOT NULL, sample_id TEXT NOT NULL, state_id TEXT NOT NULL, protocol_id TEXT NOT NULL, kind TEXT NOT NULL, technical_status TEXT NOT NULL, payload TEXT NOT NULL CHECK(json_valid(payload)), scientific_acceptance INTEGER NOT NULL DEFAULT 0 CHECK(scientific_acceptance=0), ml_training_eligible INTEGER NOT NULL DEFAULT 0 CHECK(ml_training_eligible=0), FOREIGN KEY(run_id,sample_id) REFERENCES samples(run_id,id), FOREIGN KEY(run_id,state_id,sample_id) REFERENCES states(run_id,id,sample_id), FOREIGN KEY(run_id,protocol_id) REFERENCES protocols(run_id,id));
        CREATE TABLE evidence(row_id TEXT NOT NULL REFERENCES result_proposals(row_id), entity_type TEXT NOT NULL, ordinal INTEGER NOT NULL, payload TEXT NOT NULL CHECK(json_valid(payload)), PRIMARY KEY(row_id,entity_type,ordinal));
        CREATE TABLE review_annotations(row_id TEXT NOT NULL REFERENCES result_proposals(row_id), ordinal INTEGER NOT NULL, payload TEXT NOT NULL CHECK(json_valid(payload)), PRIMARY KEY(row_id,ordinal));
        CREATE VIEW materials_review AS SELECT r.row_id, u.work_id, json_extract(s.payload,'$.formula_raw') formula_as_written, r.kind, json_extract(r.payload,'$.quantity.value') value, json_extract(r.payload,'$.quantity.unit') unit, json_extract(p.payload,'$.method') method, COALESCE(json_extract(r.payload,'$.definition.criterion'),json_extract(p.payload,'$.criterion')) criterion, r.technical_status, r.scientific_acceptance, r.ml_training_eligible FROM result_proposals r JOIN runs u ON u.id=r.run_id JOIN samples s ON s.run_id=r.run_id AND s.id=r.sample_id JOIN protocols p ON p.run_id=r.run_id AND p.id=r.protocol_id;
        """)
        for row in rows:
            run, r = row["job_id"], row["result"]
            db.execute("INSERT OR IGNORE INTO runs VALUES(?,?,?,?)", (run, row["work_id"], row["bundle_sha256"], row["receipt_sha256"]))
            for name in ("sample", "state", "protocol"):
                obj = row[name]
                payload = {k: v for k, v in compact(obj).items() if k != "evidence"}
                if name == "state":
                    db.execute("INSERT OR IGNORE INTO states VALUES(?,?,?,?)", (run,obj["id"],obj["sample_id"],canonical(payload)))
                else:
                    db.execute(f"INSERT OR IGNORE INTO {name}s VALUES(?,?,?)", (run,obj["id"],canonical(payload)))
            payload = {k: v for k, v in compact(r).items() if k != "evidence"}
            db.execute("INSERT INTO result_proposals VALUES(?,?,?,?,?,?,?,?,?,0,0)",
                       (row["row_id"],run,r["id"],r["sample_id"],r["state_id"],r["protocol_id"],r["quantity_kind"],row["technical_review_status"],canonical(payload)))
            for name in ("sample", "state", "protocol", "result"):
                for i, evidence in enumerate(row[name]["evidence"]):
                    db.execute("INSERT INTO evidence VALUES(?,?,?,?)", (row["row_id"],name,i,canonical(evidence)))
            for i, annotation in enumerate(annotations.get(row["row_id"], [])):
                db.execute("INSERT INTO review_annotations VALUES(?,?,?)", (row["row_id"],i,canonical(annotation)))
        fk = db.execute("PRAGMA foreign_key_check").fetchall()
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        join_count = db.execute("SELECT count(*) FROM materials_review").fetchone()[0]
        # Reconstruct every meaningful value and evidence item from relational
        # storage. Original null/default shape remains in immutable raw output.
        for row in rows:
            rebuilt = {}
            for name, table in (("sample","samples"),("state","states"),("protocol","protocols"),("result","result_proposals")):
                if name == "result":
                    payload = db.execute("SELECT payload FROM result_proposals WHERE row_id=?", (row["row_id"],)).fetchone()[0]
                else:
                    payload = db.execute(f"SELECT payload FROM {table} WHERE run_id=? AND id=?", (row["job_id"],row[name]["id"])).fetchone()[0]
                obj = json.loads(payload)
                ev = [json.loads(x[0]) for x in db.execute("SELECT payload FROM evidence WHERE row_id=? AND entity_type=? ORDER BY ordinal", (row["row_id"],name))]
                if ev:
                    obj["evidence"] = ev
                if compact(row[name]) != obj:
                    raise ValueError("meaningful-value round trip failed")
            if row["scientific_acceptance"] or row["ml_training_eligible"]:
                raise ValueError("pilot cannot be scientifically promoted")
        if fk or integrity != "ok" or join_count != len(rows):
            raise ValueError("prototype database integrity failure")
    temp.replace(path)
    return {"foreign_key_violations":len(fk),"integrity_check":integrity,"joined_results":join_count,
            "meaningful_value_and_evidence_round_trip":True,"canonical_identity_resolved":False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--output", type=Path, help="New versioned report directory; existing reports are not overwritten")
    args = parser.parse_args()
    directory = args.root / "runs" / args.label
    output = args.output or directory
    if args.output and (output / "quality_report.json").exists():
        raise ValueError("versioned quality report already exists")
    output.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in (directory / "observations.jsonl").read_text().splitlines()]
    reference_path = args.reference or args.root / "reference_anchors.json"
    reference_raw = reference_path.read_bytes()
    reference = json.loads(reference_raw)
    plan = json.loads((args.root / "plan.json").read_bytes())
    sources = {p["work_id"]:p["source_capture"]["url"] for p in plan["papers"]}
    review_path = args.annotations or args.root / "assistant_review.json"
    annotations = json.loads(review_path.read_text()).get("annotations", {}) if review_path.exists() else {}
    # A review file may cover several runs; only use exact row IDs for this run.
    annotations = {r["row_id"]: annotations[r["row_id"]] for r in rows if r["row_id"] in annotations}
    hits = compare_anchors(rows, reference)
    engineering = json.loads((directory / "engineering_report.json").read_text())
    gates = Counter()
    collisions = {}
    optional = Counter()
    for row in rows:
        r, sample, pr = row["result"], row["sample"], row["protocol"]
        if row["technical_review_status"] == "quarantined": gates["technical_quarantine"] += 1
        if not pr["method"]: gates["method_unresolved"] += 1
        if definition_for(row)["criterion"] == "unspecified": gates["criterion_unspecified"] += 1
        if not any(c["kind"] == "pressure" and c["role"] in {"measurement", "simulation"} for c in row["state"]["conditions"]):
            gates["pressure_no_structured_assertion"] += 1
        if r["origin"] == "unknown": gates["origin_unknown"] += 1
        if r["source_role"] == "unknown": gates["source_role_unknown"] += 1
        if sample["composition_basis"] == "unresolved": gates["composition_basis_unresolved"] += 1
        for objname in ("sample","state","protocol","result"):
            for key,val in row[objname].items():
                if val is not None and val != [] and val != {}:
                    optional[objname+"."+key] += 1
        key = canonical([row["work_id"],formula_key(sample["formula_raw"]),r["quantity_kind"],r["quantity"]["relation"],r["quantity"]["value"],r["quantity"]["lower"],r["quantity"]["upper"],r["quantity"]["unit"]])
        collisions.setdefault(key,[]).append(row["row_id"])
    compact_rows = [compact(row) for row in rows]
    original_bytes = sum(len(canonical(row).encode()) for row in rows)
    compact_bytes = sum(len(canonical(row).encode()) for row in compact_rows)
    (output / "compact_observations.jsonl").write_text("".join(canonical(row)+"\n" for row in compact_rows))
    dbcheck = build_database(output / "review_dataset.sqlite3", rows, annotations)
    durations=[]
    for job in json.loads((directory / "state.json").read_text())["jobs"]:
        for receipt in (args.root / "attempts" / job["id"]).glob("*/receipt.json"):
            d=json.loads(receipt.read_text()); durations.append(d["elapsed_seconds"])
    bypaper={}
    for aid in engineering["papers"]:
        ah=[a for a in hits if a["work_id"]==aid]
        bypaper[aid]={"numeric_formula_hits":sum(a["numeric_formula_hit"] for a in ah),"anchors":len(ah)}
    report={"schema":"materials-pilot-quality/3","engineering":engineering,
            "reference_scope":"Incomplete assistant-read anchors; not Gold; not full-paper recall",
            "reference_path":str(reference_path),"reference_sha256":hashlib.sha256(reference_raw).hexdigest(),
            "reference_version":reference["schema"],
            "input_observations_sha256":hashlib.sha256((directory / "observations.jsonl").read_bytes()).hexdigest(),
            "numeric_formula_hits":sum(a["numeric_formula_hit"] for a in hits),"anchors":len(hits),
            "per_paper_anchor_hits":bypaper,"anchor_comparison":hits,"unresolved_or_restricted_counts":dict(gates),
            "field_occurrence_counts":dict(optional),"collision_groups":[v for v in collisions.values() if len(v)>1],
            "collision_policy":"Signals only; no automatic scientific deduplication",
            "compact_projection":{"original_bytes":original_bytes,"compact_bytes":compact_bytes,
                                  "fraction_saved":1-compact_bytes/original_bytes if original_bytes else 0,
                                  "null_empty_optional_content_omitted":True,"explicit_status_zero_false_preserved":True},
            "database_checks":dbcheck,"reviewed_rows":len(annotations),
            "assistant_review_counts":dict(Counter(a["decision"] for aa in annotations.values() for a in aa)),
            "window_latency_seconds":{"median":statistics.median(durations) if durations else None,"maximum":max(durations,default=None)},
            "scientific_acceptance":False,"ml_training_eligible":False,"independent_gold":False}
    (output / "quality_report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    esc=lambda v:html.escape(str(v if v is not None else "Unknown"))
    cards=[]
    for row in rows:
        r, s, pr = row["result"], row["sample"], row["protocol"]
        q=r["quantity"]
        display=q["raw"] or q["status"]
        aid=row["work_id"].split(":",1)[1]
        annotations_text="; ".join(a["reason"] for a in annotations.get(row["row_id"],[])) or "Scientific review pending"
        evidence_groups={}
        for entity in ("sample","state","protocol","result"):
            for e in row[entity]["evidence"]:
                evidence_groups.setdefault((e["block_id"],e["quote"]),[]).append(entity+e["field"])
        for index, context_procedure in enumerate(row.get("context_procedures", [])):
            for e in context_procedure["procedure"]["evidence"]:
                evidence_groups.setdefault((e["block_id"],e["quote"]),[]).append(f"context_procedures/{index}/procedure"+e["field"])
        ev="".join("<li><b>"+esc(", ".join(dict.fromkeys(fields)))+"</b><pre>"+esc(quote)+
            "</pre><small>"+esc(block)+"</small></li>" for (block,quote),fields in evidence_groups.items())
        qualifiers="; ".join(qf["kind"]+": "+str(qf.get("stage",qf.get("condition",qf.get("role",qf.get("observable",""))))) for qf in r.get("qualifiers",[]))
        detail={name:compact({k:v for k,v in row[name].items() if k!="evidence"}) for name in ("sample","state","protocol","result")}
        if row.get("context_procedures"):
            detail["condition_measurement_methods"] = compact(row["context_procedures"])
        cards.append(f'<tr><td><a href="{esc(sources[row["work_id"]])}">{esc(aid)}</a><br>{esc(row["target_locator"])}</td><td>{esc(s["formula_raw"])}<br>{esc(s["label"])}<br><small>{esc(s["identity_resolution"])}</small></td><td>{esc(r["quantity_kind"])}<br><b>{esc(display)}</b><br>{esc(qualifiers)}</td><td>{esc(pr["method"])}<br>{esc(pr.get("method_class","unspecified"))}<br>{esc(definition_for(row)["criterion"])}</td><td>{esc(r["origin"])} / {esc(r["source_role"])}</td><td>{esc(row["technical_review_status"])}<br>{esc(annotations_text)}</td><td><details><summary>Field-bound source evidence ({len(evidence_groups)} passages)</summary><ul>{ev}</ul></details><details><summary>Sample, conditions, protocol and result</summary><pre>{esc(json.dumps(detail,indent=2,ensure_ascii=False))}</pre><small>{esc(row["row_id"])}</small></details></td></tr>')
    document='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Materials empirical review</title><style>body{font:15px/1.5 system-ui;margin:32px;color:#192c3b;background:#f5f7fa}h1{margin-bottom:6px}.notice{background:#fff4d6;border-left:4px solid #bc8300;padding:16px}table{width:100%;border-collapse:collapse;background:white}th,td{padding:10px;vertical-align:top;text-align:left;border-bottom:1px solid #dde3e8}th{position:sticky;top:0;background:#e6edf4}td:first-child{min-width:150px;font-size:12px}details{max-width:430px}pre{white-space:pre-wrap}input{padding:10px;width:420px;margin:18px 0}li{word-break:break-word}a{color:#175c9c}</style>'''
    document+=f'<h1>Materials empirical review · {esc(args.label)}</h1><p>{len(rows)} source-linked proposals · {len(engineering["papers"])} papers · {report["numeric_formula_hits"]}/{len(hits)} numeric/formula anchor hits</p><div class="notice">Private review dataset. Selected source windows only. Technical validation and numeric anchor agreement do not establish scientific correctness. All records remain excluded from qualified ML training. No canonical material identities are asserted.</div><input id="q" placeholder="Filter by paper, formula, method, or review issue"><table><thead><tr><th>Paper / target</th><th>Sample</th><th>Reported result</th><th>Method / criterion</th><th>Origin / role</th><th>Review</th><th>Evidence and conditions</th></tr></thead><tbody>'+"".join(cards)+'</tbody></table><script>document.getElementById("q").addEventListener("input",e=>{const q=e.target.value.toLowerCase();document.querySelectorAll("tbody tr").forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q))})</script></html>'
    (output / "review.html").write_text(document)
    print(canonical({k:report[k] for k in ("numeric_formula_hits","anchors","unresolved_or_restricted_counts","database_checks","compact_projection","reviewed_rows")}))


if __name__ == "__main__":
    main()
