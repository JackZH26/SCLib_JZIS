#!/usr/bin/env python3
"""Joint-field diagnostics against a disclosed, incomplete assistant source read.

Never labels selected-page hits as independent accuracy, recall or acceptance.
References and input source/row bytes are pinned in every generated report.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unicodedata


def sha(data):
    return hashlib.sha256(data).hexdigest()


def key(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or "")).lower()


def scalar(quantity, unit):
    scales = {"K": ("temperature", 1), "mK": ("temperature", .001),
              "nm": ("length", 1), "Å": ("length", .1),
              "T": ("field", 1), "mT": ("field", .001), "µT": ("field", .000001),
              "1": ("ratio", 1), "%": ("ratio", .01)}
    if quantity.get("status") != "reported" or quantity.get("relation") != "exact":
        return None
    value = quantity.get("value")
    if value is None:
        return None
    actual, expected = quantity.get("unit"), unit
    # Same explicit per-atom basis; never equate per-cell/spin/formula-unit DOS.
    dos_units={"states/(eV atom)","states/(eV·atom)","states/eV/atom"}
    if actual in dos_units and expected in dos_units:
        return value
    if actual == expected:
        return value
    if actual in scales and expected in scales and scales[actual][0] == scales[expected][0]:
        return value * scales[actual][1] / scales[expected][1]
    return None


def checks(row, reference):
    sample, state, protocol, result = (row[e] for e in ("sample", "state", "protocol", "result"))
    definition = result.get("definition", protocol)
    out = {}
    for field in ("formula", "label"):
        if field in reference:
            out[field] = key(sample["formula_raw" if field == "formula" else "label"]) == key(reference[field])
    for field in ("origin", "source_role"):
        if field in reference:
            out[field] = result.get(field) == reference[field]
    if "criterion" in reference:
        out["criterion"] = definition.get("criterion") == reference["criterion"]
    if "method_class" in reference:
        out["method_class"] = protocol.get("method_class") == reference["method_class"]
    if "approximate" in reference:
        out["approximate"] = result["quantity"].get("approximate") == reference["approximate"]
    if "method_pattern" in reference:
        out["method"] = bool(re.search(reference["method_pattern"], protocol.get("method") or "", re.I))
    if "film_thickness_nm" in reference:
        out["sample_thickness"] = any(c["kind"] == "thickness" and
            (v := scalar(c["quantity"], "nm")) is not None and
            abs(v-reference["film_thickness_nm"]) < 1e-8 for c in state["conditions"])
    if reference.get("identity_conflict"):
        formulas = {key(sample["formula_raw"])} | {key(a["formula_raw"]) for a in sample.get("additional_formula_assertions", [])}
        out["formula_conflict"] = sample["identity_resolution"] == "conflicted" and {key(f) for f in reference["identity_conflict"]} <= formulas
    if "transition_stage" in reference:
        out["transition_stage"] = any(q["kind"] == "transition_stage" and q["stage"] == reference["transition_stage"] for q in result.get("qualifiers", []))
    if "orientation_pattern" in reference:
        # The sparse proposal currently allows direction in component/method text.
        text = " ".join(str(x or "") for x in (result.get("component_raw"), protocol.get("method"), protocol.get("details_raw")))
        text += " "+" ".join(c.get("orientation_raw") or "" for c in state["conditions"])
        out["field_orientation"] = bool(re.search(reference["orientation_pattern"], text, re.I))
    for parameter in reference.get("parameters", []):
        own_definition = "definition" in result and parameter["kind"] == "resistance_fraction"
        owner = definition if own_definition else protocol
        evidence = result["evidence"] if own_definition else protocol["evidence"]
        prefix = "/definition/parameters" if own_definition else "/parameters"
        found = [(i,p) for i,p in enumerate(owner.get("parameters", [])) if p["kind"] == parameter["kind"] and
                 (v := scalar(p["quantity"], parameter["unit"])) is not None and abs(v-parameter["value"]) < 1e-8]
        out[parameter["kind"]] = bool(found)
        out[parameter["kind"]+"_evidence"] = any(any(e["field"] == f"{prefix}/{i}" for e in evidence) for i,_ in found)
    if reference.get("conditional_non_detection"):
        out["conditional_existence"] = any(q["kind"] == "conditional_existence" for q in result.get("qualifiers", []))
        out["no_numeric_tc"] = result["quantity"]["status"] == "not_applicable"
    if "conditional_bound" in reference:
        expected=reference["conditional_bound"]
        bounds=[(i,q.get("tc_bound")) for i,q in enumerate(result.get("qualifiers", [])) if q["kind"]=="conditional_existence"]
        matched=[i for i,b in bounds if b and all(b.get(k)==v for k,v in expected.items())]
        out["conditional_tc_bound"]=bool(matched)
        out["conditional_bound_evidence"]=any(any(e["field"]==f"/qualifiers/{i}/tc_bound" for e in result["evidence"]) for i in matched)
    if "window_status" in reference:
        out["window_status"]=any(q["kind"]=="non_detection" and q.get("window_status")==reference["window_status"] for q in result.get("qualifiers", []))
    if reference.get("no_reported_detection_window"):
        out["no_inferred_measurement_window"]=not any(c["role"]=="detection_window" and c["quantity"]["status"]=="reported" for c in state["conditions"])
    return out


def scoped_formula_hazards(rows, scope_checks, bundles):
    """Disclosed source-specific checks; never infer a phase from a regex.

    A formula belonging to an intergrowth/component must not be flattened into
    an alternate composition of its parent specimen. One shared sample is one
    finding even when its assertion propagates to many result rows.
    """
    hazards = []
    for check in scope_checks:
        if check["kind"] != "component_formula_not_sample_identity":
            raise ValueError("Unknown source scope check")
        bundle = bundles.get((check["work_id"], check["bundle_sha256"]))
        if bundle is None: raise ValueError("Scope check is outside the frozen reference sources")
        evidence = check["evidence"]
        block = next((b for b in bundle["blocks"] if b["id"] == evidence["block_id"]), None)
        start, end = evidence["start_char"], evidence["end_char"]
        if (block is None or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(block["text"])
                or block["text"][start:end] != evidence["quote"]
                or sha(evidence["quote"].encode()) != evidence["quote_sha256"]
                or key(check["component_formula_raw"]) not in key(evidence["quote"])):
            raise ValueError("Scope check source quote or locator mismatch")
        groups = {}
        for row in rows:
            if (row["work_id"], row["bundle_sha256"]) != (check["work_id"], check["bundle_sha256"]):
                continue
            sample = row["sample"]
            if key(sample.get("label")) != key(check["sample_label"]): continue
            formulas = [sample["formula_raw"]] + [a["formula_raw"] for a in sample.get("additional_formula_assertions", [])]
            if key(check["component_formula_raw"]) in {key(f) for f in formulas}:
                groups.setdefault(sample["id"], []).append(row["row_id"])
        for sample_id, row_ids in groups.items():
            hazards.append({"reference_check_id": check["id"], "sample_id": sample_id,
                "affected_row_ids": row_ids, "code": "component_formula_attached_to_parent_sample",
                "reason": "The cited source assigns this formula to a component or intergrowth. The proposal stores it as a formula assertion of the parent specimen. Typed component ownership requires review.",
                "source_evidence": evidence, "independently_reviewed": False})
    return hazards


def relational_context_checks(checks_to_run, graphs, bundles, job_sources):
    """Finite, source-scoped graph obligations, separate from scalar matches."""
    reports=[]
    for check in checks_to_run:
        evidence=check["evidence"]
        sources=[(source,b) for source,b in bundles.items() if any(x["id"]==evidence["block_id"] for x in b["blocks"])]
        if len(sources)!=1: raise ValueError("Relation reference source is missing or ambiguous")
        source,bundle=sources[0]
        block=next(x for x in bundle["blocks"] if x["id"]==evidence["block_id"])
        start,end=evidence["start_char"],evidence["end_char"]
        if (type(start) is not int or type(end) is not int or not 0<=start<end<=len(block["text"])
                or block["text"][start:end]!=evidence["quote"] or sha(evidence["quote"].encode())!=evidence["quote_sha256"]):
            raise ValueError("Relation reference source quote or locator mismatch")
        evaluated=[]
        for record in graphs:
            if job_sources.get(record["job_id"])!=source: continue
            graph=record.get("structured_graph")
            if not graph: continue
            samples={x["id"]:x for x in graph["samples"]}
            states={x["id"]:x for x in graph["states"]}
            protocols={x["id"]:x for x in graph["protocols"]}
            parents={s["id"] for s in samples.values() if key(s.get("label"))==key(check.get("parent_label",check.get("sample_label")))}
            details={}
            if check["kind"]=="component_membership":
                children={s["id"] for s in samples.values() if key(s["formula_raw"])==key(check["component_formula"])}
                edges=[e for e in graph.get("sample_relations",[]) if e["from_sample_id"] in children
                    and e["to_sample_id"] in parents and e["relation"]=="component_of"]
                inherited=[r["id"] for r in graph["results"] if r["sample_id"] in children and r["quantity_kind"] in check["no_inherited_kinds"]]
                details={"component_ids":sorted(children),"parent_ids":sorted(parents),"edge_ids":[e["id"] for e in edges],"unexpected_result_ids":inherited}
                passed=bool(parents and children and edges) and not inherited
            elif check["kind"]=="geometry_measurement_supports":
                method_rows=[]; owner_sets=[]
                for method in check["methods"]:
                    matches=[]
                    for result in graph["results"]:
                        if (result["sample_id"] not in parents or result["quantity_kind"]!=check["quantity_kind"]
                                or result["origin"]!="observed" or result["quantity"].get("approximate")
                                or scalar(result["quantity"],check["unit"])!=check["value"]
                                or not re.search(method,protocols[result["protocol_id"]].get("method") or "",re.I)): continue
                        for support in graph.get("condition_supports",[]):
                            if support["result_id"]!=result["id"] or support["state_id"]!=result["state_id"]: continue
                            state=states[support["state_id"]]
                            condition=next((c for c in state["conditions"] if c.get("id")==support["condition_id"]),None)
                            if (condition and state["sample_id"]==result["sample_id"] and condition["kind"]==check["quantity_kind"]
                                    and condition["role"]=="sample_geometry" and not condition["quantity"].get("approximate")
                                    and scalar(condition["quantity"],check["unit"])==check["value"]):
                                matches.append({"result_id":result["id"],"state_id":state["id"],"sample_id":result["sample_id"],"support_id":support["id"]})
                    method_rows.append({"method_pattern":method,"matches":matches})
                    owner_sets.append({(m["sample_id"],m["state_id"]) for m in matches})
                common=set.intersection(*owner_sets) if owner_sets else set()
                details={"method_results":method_rows,"common_owners":[list(x) for x in sorted(common)]}
                # Two different methods may not be discharged by the very same result.
                distinct={m["result_id"] for row in method_rows for m in row["matches"]}
                passed=bool(common) and len(distinct)>=len(check["methods"])
            elif check["kind"]=="typed_geometry_assertion":
                assertions=[("result",r["id"],r["quantity_kind"],r["quantity"]) for r in graph["results"] if r["sample_id"] in parents]
                assertions += [("condition",s["id"]+":"+str(c.get("id",i)),c["kind"],c["quantity"])
                    for s in states.values() if s["sample_id"] in parents for i,c in enumerate(s["conditions"])]
                retained=[{"owner_type":t,"id":i} for t,i,k,q in assertions if k==check["quantity_kind"]
                    and scalar(q,check["unit"])==check["value"] and q.get("approximate")==check["approximate"]]
                details={"retained":retained}; passed=bool(retained)
            elif check["kind"]=="unattributed_method":
                scoped=[r for r in graph["results"] if r["sample_id"] in parents
                    and r["quantity_kind"]==check["quantity_kind"]]
                bad=[r["id"] for r in scoped if any(re.search(pattern,protocols[r["protocol_id"]].get("method") or "",re.I)
                    for pattern in check["forbidden_method_patterns"])]
                details={"inspected_result_ids":[r["id"] for r in scoped],"unsupported_method_result_ids":bad}
                passed=not bad
            else: raise ValueError("Unknown relation reference check")
            evaluated.append({"job_id":record["job_id"],"check_satisfied":passed,**details})
        reports.append({"id":check["id"],"kind":check["kind"],"source_evidence":evidence,
            "check_satisfied":bool(evaluated) and all(e["check_satisfied"] for e in evaluated),
            "evaluated_graphs":evaluated,"independently_reviewed":False})
    return reports


def evaluate(root, label, reference_path, output):
    if output.exists():
        raise ValueError("Use a new report path; historical evaluations are immutable")
    reference_raw = reference_path.read_bytes()
    reference = json.loads(reference_raw)
    raw = (root/"runs"/label/"observations.jsonl").read_bytes()
    all_rows = [json.loads(line) for line in raw.splitlines()]
    reference_sources = {(s["work_id"], s["bundle_sha256"]) for s in reference["source_windows"]}
    rows = [row for row in all_rows if (row["work_id"], row["bundle_sha256"]) in reference_sources]
    plan = json.loads((root/"plan.json").read_bytes())
    papers = {p["work_id"]:p for p in plan["papers"]}
    bundles = {}
    for source in reference["source_windows"]:
        paper = papers[source["work_id"]]
        if sha(Path(paper["source_capture"]["local_path"]).read_bytes()) != source["capture_sha256"]:
            raise ValueError("Reference source capture changed")
        bundle = json.loads((root/"bundles"/(source["bundle_sha256"]+".json")).read_bytes())
        target = next(b for b in bundle["blocks"] if b["id"] == source["target_block_id"])
        if target["sha256"] != source["target_text_sha256"] or target["locator"] != source["locator"]:
            raise ValueError("Reference target bytes or location changed")
        bundles[source["work_id"], source["bundle_sha256"]] = bundle
    items=[]
    for ref in reference["assertions"]:
        candidates=[]
        for row in rows:
            if row["work_id"] != ref["work_id"] or row["result"]["quantity_kind"] != ref["kind"]:
                continue
            if "value" in ref:
                value=scalar(row["result"]["quantity"],ref["unit"])
                if value is None or abs(value-ref["value"]) > 1e-8:
                    continue
            test=checks(row,ref)
            candidates.append({"row_id":row["row_id"],"checks":test,
                "joint_match":all(test.values()),"technical_review_status":row["technical_review_status"]})
        items.append({"id":ref["id"],"work_id":ref["work_id"],"candidates":candidates,
            "value_or_assertion_present":bool(candidates),"joint_match":any(c["joint_match"] for c in candidates)})
    hazards=scoped_formula_hazards(rows, reference.get("scope_checks", []), bundles)
    for row in rows:
        if row["work_id"] != "arxiv:2509.22278" or row["sample"].get("label") not in {"HSC1","HSC3"}:
            continue
        if row["result"]["quantity_kind"] == "tc":
            hazards.append({"row_id":row["row_id"],"code":"conditional_existence_promoted_to_tc"})
        for condition in row["state"]["conditions"]:
            if condition["role"] == "detection_window" and condition["quantity"]["status"] == "reported":
                hazards.append({"row_id":row["row_id"],"code":"measurement_window_inferred_from_conditional_tc_bound",
                    "reason":"The supplied passage states a conditional Tc below 1.9 K. It does not explicitly report the measurement scan window; source review is required."})
    per_paper={}
    for work_id in sorted({a["work_id"] for a in items}):
        subset=[a for a in items if a["work_id"] == work_id]
        per_paper[work_id]={"selected_assertions":len(subset),"value_or_assertion_present":sum(a["value_or_assertion_present"] for a in subset),
            "joint_matches":sum(a["joint_match"] for a in subset),"unmet_ids":[a["id"] for a in subset if not a["joint_match"]]}
    relation_report=[]; graphs_hash=None
    if reference.get("relation_checks"):
        graph_raw=(root/"runs"/label/"entity_graphs.jsonl").read_bytes();graphs_hash=sha(graph_raw)
        graphs=[json.loads(line) for line in graph_raw.splitlines()]
        state=json.loads((root/"runs"/label/"state.json").read_bytes())
        job_sources={j["id"]:(j["work_id"],j["bundle_sha256"]) for j in state["jobs"]}
        relation_report=relational_context_checks(reference["relation_checks"],graphs,bundles,job_sources)
    evaluator=Path(__file__).read_bytes();evaluator_hash=sha(evaluator)
    evaluator_path=root/"evaluators"/(evaluator_hash+".py")
    evaluator_path.parent.mkdir(parents=True,exist_ok=True)
    if evaluator_path.exists() and evaluator_path.read_bytes()!=evaluator:
        raise ValueError("Evaluator snapshot changed")
    evaluator_path.write_bytes(evaluator)
    report={"schema":"materials-canary-joint-field-diagnostics/7","run":label,
        "evaluator_sha256":evaluator_hash,"evaluator_snapshot":str(evaluator_path),
        "reference_path":str(reference_path),"reference_sha256":sha(reference_raw),"observations_sha256":sha(raw),
        "input_rows":len(all_rows),"evaluated_rows":len(rows),
        "scope_excluded_rows":len(all_rows)-len(rows),
        "candidate_and_hazard_scope":"Only the reference's frozen work and source-window bundle pairs",
        "reference_scope":reference["scope"],"selected_assertions":len(items),
        "source_scope_checks":len(reference.get("scope_checks", [])),
        "relation_checks":relation_report,"relation_checks_satisfied":sum(r["check_satisfied"] for r in relation_report),
        "entity_graphs_sha256":graphs_hash,
        "joint_matches":sum(a["joint_match"] for a in items),"per_paper":per_paper,"assertions":items,
        "source_semantic_hazards":hazards,"hazard_counts":dict(Counter(h["code"] for h in hazards)),
        "independent_gold":False,"precision_or_recall_estimate":False,
        "full_paper_coverage":False,"scientific_acceptance":False,"ml_training_eligible":False,
        "expansion_gate_passed":False,
        "gate_note":"Selected assertions cannot establish completeness or independent acceptance. All hazards and source-context exclusions still require adjudication."}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    return {k:report[k] for k in ("run","selected_assertions","joint_matches","per_paper","hazard_counts","expansion_gate_passed")}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--label",required=True)
    parser.add_argument("--reference",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(evaluate(args.root,args.label,args.reference,args.output),indent=2))
