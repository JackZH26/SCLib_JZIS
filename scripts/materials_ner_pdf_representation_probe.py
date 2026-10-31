#!/usr/bin/env python3
"""Freeze a PDF reading-order experiment without altering old captures/attempts.

This changes the source representation, not the original paper/version. Results
must be compared by source assertions; counts are not a precision/recall metric.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import sys

from pypdf import PdfReader

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"ingestion"))
from ingestion.materials_ner.contract import canonical,digest
from ingestion.materials_ner.sources import load_bundle,make_blocks,private_write,save_bundle,sha
from ingestion.materials_ner.windows import make_windows


def control_counts(text):
    return dict(Counter(f"U+{ord(c):04X}" for c in text if ord(c)<32 and c not in "\n\r\t"))


def prepare(root,baseline,selection_path):
    if root.exists():raise ValueError("new representation root must not exist")
    original=json.loads((baseline/"plan.json").read_bytes())
    selection=json.loads(selection_path.read_bytes())
    wanted=set(selection["bundle_sha256"])
    planned={w["bundle_sha256"] for p in original["papers"] for w in p["windows"]}
    if not wanted or not wanted<=planned:raise ValueError("selection not in frozen plan")
    papers=[];audit=[]
    for paper in original["papers"]:
        selected=[w for w in paper["windows"] if w["bundle_sha256"] in wanted]
        if not selected:continue
        if any(not isinstance(w["page"],int) for w in selected):raise ValueError("PDF pages required")
        pages={w["page"] for w in selected}
        capture=dict(paper["source_capture"])
        source=Path(capture["local_path"]);raw=source.read_bytes()
        if sha(raw)!=capture["sha256"] or not raw.startswith(b"%PDF"):raise ValueError("capture integrity failed")
        frozen=root/"sources"/source.name;private_write(frozen,raw)
        capture.update(local_path=str(frozen),inherited_from=str(source))
        old=load_bundle(baseline/"bundles"/(paper["parent_bundle_sha256"]+".json"))
        bundle=old.model_copy(deep=True)
        if len(bundle.documents)!=1:raise ValueError("probe requires one main PDF")
        doc=bundle.documents[0]
        doc.parser=f"pypdf-plain/{importlib.metadata.version('pypdf')}:reading-order-probe/1"
        doc.coverage="partial"
        reader=PdfReader(frozen)
        segments=[(f"pdf_page:{i}",p.extract_text(extraction_mode="plain")) for i,p in enumerate(reader.pages,1)]
        bundle.blocks=make_blocks(doc.id,segments)
        bundle.acquisition_notes.extend([
            "Representation experiment: original PDF hash/version unchanged; pypdf plain reading order replaces layout text.",
            "No hand-corrected values, labels or reference answers are supplied to extraction.",
            "Figures, full reading order, text glyphs and supplements still require source review."])
        parent_hash,_=save_bundle(root,bundle)
        windows=make_windows(root,bundle,max_chars=10000)
        chosen=[]
        for w in windows["windows"]:
            window=load_bundle(root/"bundles"/(w["bundle_sha256"]+".json"))
            target=next(b for b in window.blocks if b.locator.startswith("target:"))
            page=int(target.locator.split("pdf_page:")[1].split(":")[0])
            if page not in pages:continue
            first=bundle.blocks[0]
            if first.id!=w["source_block_id"]:
                context=first.model_copy(deep=True)
                context.id+=":pilot-context";context.ordinal=len(window.blocks)
                context.locator="context-identity:"+first.locator
                window.blocks.append(context)
            bundle_hash,_=save_bundle(root,window)
            chosen.append(dict(w,bundle_sha256=bundle_hash,page=page,target_locator=target.locator))
        private_write(root/"source_text"/(source.stem+".txt"),"\n\n".join(
            f"=== {b.locator} ===\n{b.text}" for b in bundle.blocks).encode())
        for page in sorted(pages):
            before=next(b for b in old.blocks if b.locator==f"pdf_page:{page}")
            after=next(b for b in bundle.blocks if b.locator==before.locator)
            audit.append({"work_id":paper["work_id"],"page":page,"source_sha256":sha(raw),
                "old_text_sha256":before.sha256,"new_text_sha256":after.sha256,
                "old_characters":len(before.text),"new_characters":len(after.text),
                "old_control_characters":control_counts(before.text),"new_control_characters":control_counts(after.text),
                "semantic_equivalence_verified":False,"complete_figure_coverage":False})
        papers.append({**paper,"split":"development_regression","original_plan_split":paper["split"],
            "source_capture":capture,"parent_bundle_sha256":parent_hash,"selected_pages":sorted(pages),
            "available_text_blocks":len(bundle.blocks),"windows":chosen,
            "total_text_characters":sum(len(b.text) for b in bundle.blocks),
            "target_characters":sum(w["end_char"]-w["start_char"] for w in chosen),"full_paper_coverage":False})
    plan={"schema":"materials-pdf-representation-probe/1","created_at":datetime.now(timezone.utc).isoformat(),
        "papers":papers,"model":"gpt-6-luna","original_plan_sha256":digest(original),
        "selection_sha256":digest(selection),"representation_code_sha256":sha(Path(__file__).read_bytes()),
        "source_scope":"Same original PDF versions and selected pages; different text representation and span boundaries",
        "evaluation_role":"development_regression","independent_gold":False,
        "scientific_acceptance":False,"ml_training_eligible":False}
    private_write(root/"plan.json",canonical(plan).encode())
    private_write(root/"representation_audit.json",canonical({"pages":audit,"scientific_acceptance":False}).encode())
    return {"papers":len(papers),"windows":sum(len(p["windows"]) for p in papers),"model_called":False}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--baseline",type=Path,required=True)
    parser.add_argument("--selection",type=Path,required=True)
    args=parser.parse_args()
    print(canonical(prepare(args.root,args.baseline,args.selection)))
