#!/usr/bin/env python3
"""Audit frozen text and prepare a separately frozen HTML representation probe.

The probe changes the source representation and coverage, not the model prompt.
Only shared source assertions can be compared; whole-run yields are not paired.
No labels or prior model values are supplied to the extraction model.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))
from ingestion.materials_ner.sources import Bundle, Document, load_bundle, make_blocks, private_write, save_bundle, sha
from ingestion.materials_ner.windows import make_windows
from materials_ner_empirical_pilot import ArxivArticleText, write_json


def control_counts(text):
    return dict(Counter(f"U+{ord(c):04X}" for c in text if ord(c)<32 and c not in "\n\r\t"))


def prepare(root, baseline, previous):
    if (root / "plan.json").exists():
        raise ValueError("representation probe already frozen")
    oldplan = json.loads((baseline / "plan.json").read_bytes())
    audit=[]
    for paper in oldplan["papers"]:
        bundle=load_bundle(baseline / "bundles" / (paper["parent_bundle_sha256"]+".json"))
        audit.append({"work_id":paper["work_id"],"bundle_sha256":paper["parent_bundle_sha256"],
                      "parser":sorted({d.parser for d in bundle.documents}),
                      "blocks":[{"locator":b.locator,"text_sha256":b.sha256,"control_characters":control_counts(b.text),
                                 "replacement_characters":b.text.count("\ufffd")} for b in bundle.blocks],
                      "layout_order_verified":False,"figure_coverage_verified":False,
                      "interpretation":"Control characters trigger source inspection; absence does not prove good layout or complete extraction."})
    receipts=[]
    for name in ("capture_manifest.json","supplemental_capture_manifest.json"):
        receipts.extend(json.loads((previous/name).read_bytes())["receipts"])
    papers=[]
    for aid in ("2509.22278","2604.07807"):
        url=f"https://arxiv.org/html/{aid}v1"
        receipt=next(r for r in receipts if r["url"]==url)
        raw=(previous/receipt["path"]).read_bytes()
        if sha(raw)!=receipt["sha256"] or receipt["resolved_url"]!=url:
            raise ValueError("source capture/version mismatch")
        source=root/"sources"/f"{aid}v1.html"
        private_write(source,raw)
        parser=ArxivArticleText();parser.feed(raw.decode("utf-8"));body="".join(parser.parts)
        if not body.strip() or control_counts(body):
            raise ValueError("HTML projection needs source repair before extraction")
        docid="doc:"+sha(raw)[:20]
        document=Document(id=docid,source_uri=url,source_sha256=sha(raw),source_kind="original_text",role="main",
            publication_version="v1",version_status="verified",processing_permission="allowed",
            redistribution_permission="unresolved",coverage="partial",parser="pilot-arxiv-html-text/1:stdlib-math-alttext")
        bundle=Bundle(version="materials-source-bundle/1",work_id=f"arxiv:{aid}",title=f"arXiv {aid}v1",family=None,
            source_status="unresolved",supplement_status="not_checked",documents=[document],
            blocks=make_blocks(docid,[("html_article:0",body)]),acquisition_notes=[
                "Representation probe: HTML main article text; figures and supplementary coverage remain unverified.",
                "All article windows selected; shared reference assertions only are comparable with selected PDF pages.",
                "Private source processing authorized; redistribution unresolved."])
        parent_hash,_=save_bundle(root,bundle)
        selected=[]
        for row in make_windows(root,bundle,max_chars=10000)["windows"]:
            window=load_bundle(root/"bundles"/(row["bundle_sha256"]+".json"))
            target=next(b for b in window.blocks if b.locator.startswith("target:"))
            # Preserve the same pilot context rule to avoid a prompt intervention.
            if bundle.blocks[0].id!=row["source_block_id"]:
                context=bundle.blocks[0].model_copy(deep=True)
                context.id+=":pilot-context";context.ordinal=len(window.blocks)
                context.locator="context-identity:"+bundle.blocks[0].locator
                window.blocks.append(context)
            whash,_=save_bundle(root,window)
            selected.append(dict(row,bundle_sha256=whash,page=None,target_locator=target.locator))
        capture=dict(receipt,local_path=str(source),inherited_from=str(previous))
        papers.append({"work_id":bundle.work_id,"version":"v1","split":"development_representation_probe",
                       "source_capture":capture,"parent_bundle_sha256":parent_hash,"available_text_blocks":1,
                       "selected_pages":"html_all","total_text_characters":len(body),
                       "target_characters":sum(r["end_char"]-r["start_char"] for r in selected),
                       "windows":selected,"full_paper_coverage":False})
        private_write(root/"source_text"/f"{aid}v1.txt",body.encode())
    reference=json.loads((baseline/"reference_anchors_v2.json").read_bytes())
    work_ids={p["work_id"] for p in papers}
    reference["anchors"]=[a for a in reference["anchors"] if a["work_id"] in work_ids]
    reference["negative_checks"]=[a for a in reference["negative_checks"] if a["work_id"] in work_ids]
    reference["subset_of_reference_sha256"]=sha((baseline/"reference_anchors_v2.json").read_bytes())
    write_json(root/"reference_anchors.json",reference)
    write_json(root/"source_quality.json",{"schema":"materials-source-quality-diagnostic/1","papers":audit,
        "automatic_rejection":False,"full_paper_coverage":False})
    plan={"schema":"materials-empirical-pilot/1","created_at":datetime.now(timezone.utc).isoformat(),
          "papers":papers,"model":"gpt-6-luna","purpose":"source-representation error diagnosis",
          "baseline_root":str(baseline),"baseline_plan_sha256":sha((baseline/"plan.json").read_bytes()),
          "source_projection_script_sha256":sha(Path(__file__).with_name("materials_ner_empirical_pilot.py").read_bytes()),
          "source_scope":"HTML article text versus selected PDF pages; comparison restricted to common assertions",
          "independent_gold":False,"population_accuracy_estimate":False,"scientific_acceptance":False,
          "ml_training_eligible":False}
    write_json(root/"plan.json",plan)
    return {"papers":len(papers),"windows":sum(len(p["windows"]) for p in papers),
            "reference_assertions":len(reference["anchors"]),"model_called":False}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--baseline",type=Path,required=True)
    parser.add_argument("--previous",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.root,args.baseline,args.previous)))
