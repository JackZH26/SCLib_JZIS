#!/usr/bin/env python3
"""Paired engineering and source-assisted sentinel checks, never Gold accuracy."""
import argparse
from collections import Counter
import json
from pathlib import Path

from materials_ner_pilot_quality import canonical, compare_anchors
from materials_ner_pilot_projection import content_id


def read_rows(root,label):
    return [json.loads(x) for x in (root/"runs"/label/"observations.jsonl").read_text().splitlines()]


def sentinels(rows):
    def find(paper,kind=None,value=None):
        return [r for r in rows if r["work_id"]=="arxiv:"+paper and
                (kind is None or r["result"]["quantity_kind"]==kind) and
                (value is None or r["result"]["quantity"]["value"]==value)]
    def outcome(identifier,matched,okay,rule):
        return {"id":identifier,"status":"diagnostic_pass" if okay else "needs_review",
                "rule":rule,"row_ids":[r["row_id"] for r in matched],"scientific_acceptance":False}
    checks=[]
    found=find("2301.01120","tc",4.6)
    checks.append(outcome("zero_resistance_criterion",found,bool(found) and all(r["result"].get("definition",r["protocol"])["criterion"]=="zero_resistance" for r in found),
                          "The 4.6 K passage explicitly describes zero resistivity."))
    found=find("2504.00662","tc",.3)
    checks.append(outcome("measurement_temperature_not_tc",found,not found,
                          "The 0.3 K muon spectrum is measured inside the superconducting state."))
    found=find("2504.00662",value=3.25)
    checks.append(outcome("no_gap_feature_midpoint",found,not found,
                          "The source reports a 3-3.5 K gap-feature interval, not its 3.25 K midpoint. Absence alone does not establish interval recovery."))
    found=find("2504.00662","tc",4.95)
    checks.append(outcome("experimental_fit_origin",found,bool(found) and all(r["result"]["origin"]=="model_derived" for r in found),
                          "The bulk Tc was fitted from experimental heat-capacity data."))
    found=find("2012.05654","non_detection")
    checks.append(outcome("zero_field_mode_not_negative",found,not found,
                          "The baseline negative was a zero-field muon discussion of spontaneous fields in the superconducting state."))
    found=find("2604.07807","tc",15.5)+find("2604.07807","tc",19.5)
    okay=len(found)>=2 and all(r["result"].get("definition",r["protocol"])["criterion"]=="onset" and
                             "secondary" in (r["result"]["component_raw"] or "").lower() for r in found)
    checks.append(outcome("secondary_onset_preserved_in_text",found,okay,
                          "Criterion must remain onset with secondary stage preserved; a typed stage is still required."))
    found=find("2604.07807","tc")
    checks.append(outcome("source_formula_conflict_flagged",found,any(r["sample"]["identity_resolution"]=="conflicted" for r in found),
                          "La2PrNiO7 and La2PrNi2O7 both occur in the paper. Literal source disagreement needs explicit review, not silent selection."))
    found=find("2509.22278","tc")
    expected={6.61:.007,6.63:.01,8.897:.001}
    okay=all(any(r["result"]["quantity"]["value"]==v and r["result"]["quantity"]["unit"]=="K" and
                 r["result"]["quantity"]["uncertainty"] and
                 all(abs(r["result"]["quantity"]["uncertainty"][k]-u)<1e-10 for k in ("minus","plus"))
                 for r in found) for v,u in expected.items())
    checks.append(outcome("table_parenthetical_uncertainties",found,okay,
                          "The three table Tc uncertainties must remain distinct from unspecified sensor calibration accuracy."))
    conditional=[r for r in found if (r["sample"]["label"] or "").upper() in {"HSC1","HSC3"}]
    checks.append(outcome("conditional_non_detection_representation",conditional,not conditional,
                          "If superconducting at all, Tc is below the 1.9 K measurement floor. A plain observed Tc bound is insufficient; retain conditional existence and detection context."))
    found=find("2508.05010","tc",4.655)
    checks.append(outcome("no_alloy_range_midpoint",found,not found,
                          "No per-alloy Tc may be created by averaging the abstract range."))
    return checks


def compare(root,before,after,output):
    if output.exists(): raise ValueError("paired report already exists")
    a,b=read_rows(root,before),read_rows(root,after)
    states=[json.loads((root/"runs"/label/"state.json").read_bytes()) for label in (before,after)]
    if Counter((j["work_id"],j["bundle_sha256"],j["target_locator"]) for j in states[0]["jobs"])!=Counter(
       (j["work_id"],j["bundle_sha256"],j["target_locator"]) for j in states[1]["jobs"]):
        raise ValueError("paired comparison requires identical source windows")
    reference=json.loads((root/"reference_anchors_v2.json").read_bytes())
    results=[]
    for label,rows,state in zip((before,after),(a,b),states):
        engineering=json.loads((root/"runs"/label/"engineering_report.json").read_bytes())
        if len(state["outcomes"])!=len(state["jobs"]):
            raise ValueError("paired run has unattempted windows")
        anchor_matches=compare_anchors(rows,reference)
        results.append({"label":label,"config":state["config"],"engineering":engineering,
                        "numeric_formula_hits":sum(m["numeric_formula_hit"] for m in anchor_matches),
                        "anchor_count":len(anchor_matches),"anchor_comparison":anchor_matches,
                        "sentinels":sentinels(rows),"record_count":len(rows),
                        "input_rows_digest":content_id(rows)})
    report={"schema":"materials-paired-diagnostic/1","same_source_windows":True,
            "source_window_count":len(states[0]["jobs"]),"reference_digest":content_id(reference),
            "runs":results,"independent_gold":False,"population_accuracy_estimate":False,
            "scientific_acceptance":False,"ml_training_eligible":False,
            "limitations":["Sentinels cover previously source-read errors only; no overall accuracy/recall estimate.",
                           "No-error presence checks do not establish complete recovery or absence of new errors.",
                           "Each configuration was sampled once; stochastic variance has not been estimated.",
                           "Full-paper coverage and independent expert adjudication remain pending."]}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    return [{"label":r["label"],"records":r["record_count"],"numeric_formula_hits":r["numeric_formula_hits"],
             "sentinels":{s["id"]:s["status"] for s in r["sentinels"]}} for r in results]


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--before",default="baseline")
    parser.add_argument("--after",default="iteration1")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    print(canonical(compare(args.root,args.before,args.after,args.output)))
