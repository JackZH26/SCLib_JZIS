#!/usr/bin/env python3
"""Reserve paper groups before NER or annotation, using frozen metadata only.

This is a sampling frame, not a reference dataset or evidence of full-paper
coverage. Known DOI/version aliases are grouped; reused specimens still need
source review before any train/test or qualification release.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))
from ingestion.materials_ner.contract import canonical, digest


def work_key(value):
    return re.sub(r"v\d+$", "", value)


def year_stratum(date):
    if not date or not re.match(r"^\d{4}-", str(date)): return "unknown_year"
    year = int(str(date)[:4])
    for boundary, label in ((2000, "before_2000"), (2010, "2000_to_2009"),
                            (2020, "2010_to_2019"), (2023, "2020_to_2022")):
        if year < boundary: return label
    return "2023_onward"


def quotas(sizes, count):
    """At least two groups per nonempty stratum; allocate the rest proportionally."""
    result = {k: min(2, n) for k, n in sizes.items()}
    if sum(result.values()) > count or sum(sizes.values()) < count:
        raise ValueError("sample_size_incompatible_with_strata")
    remaining = count - sum(result.values())
    capacity = {k: sizes[k] - result[k] for k in sizes}
    total = sum(capacity.values())
    if not remaining: return result
    ideal = {k: remaining * capacity[k] / total for k in sizes}
    for k, value in ideal.items(): result[k] += int(value)
    for k in sorted(sizes, key=lambda k: (-(ideal[k] - int(ideal[k])), k)):
        if sum(result.values()) == count: break
        if result[k] < sizes[k]: result[k] += 1
    assert sum(result.values()) == count
    return result


def build_plan(source_plan, inventory, exclusions, *, seed, count=120):
    if source_plan.get("schema") != "materials-ner-source-plan/1":
        raise ValueError("unsupported_source_plan")
    if source_plan["inventory_sha256"] != digest(inventory):
        raise ValueError("source_inventory_hash_mismatch")
    if not seed or count < 2: raise ValueError("invalid_sampling_configuration")
    rows = {p["id"]: p for p in source_plan["papers"]}
    metadata = {p["id"]: p for p in inventory["paper_plan"]}
    if len(rows) != len(source_plan["papers"]) or set(rows) != set(metadata):
        raise ValueError("source_plan_metadata_ownership_mismatch")
    parent = {k: k for k in rows}
    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]; k = parent[k]
        return k
    def union(a, b):
        a, b = find(a), find(b)
        parent[max(a,b)] = min(a,b)
    aliases = {}
    for k, row in rows.items():
        keys = [("work", work_key(k))]
        doi = (row.get("doi") or "").strip().lower()
        if doi: keys.append(("doi", doi))
        for key in keys:
            if key in aliases: union(k, aliases[key])
            else: aliases[key] = k
        related = metadata[k].get("related_paper_id")
        if related in rows: union(k, related)
        for related in row.get("alternate_work_ids", []):
            if related in rows: union(k, related)
    groups = defaultdict(list)
    for k in rows: groups[find(k)].append(k)
    excluded = {work_key(k) for k in exclusions}
    strata = defaultdict(list); excluded_groups=[]
    for members in groups.values():
        members = sorted(members)
        arxiv = [k for k in members if rows[k]["source"] == "arxiv"]
        if not arxiv: continue
        group_id = digest(members)
        touched = [k for k in members if work_key(k) in excluded]
        if touched:
            excluded_groups.append({"group_id":group_id,"members":members,"touched_work_ids":touched})
            continue
        representative = min(arxiv)
        row = rows[representative]
        if row["acquisition_status"] not in {"available_in_gcs","missing_archive"}:
            raise ValueError("unsupported_arxiv_source_state")
        date = metadata[representative].get("date_submitted")
        year = year_stratum(date)
        stratum = year + ":" + row["acquisition_status"]
        strata[stratum].append({"group_id":group_id,"known_work_aliases":members,
            "work_id":representative,"arxiv_id":row["arxiv_id"],"doi":row.get("doi"),
            "title":row["title"],"date_submitted":date,"year_stratum":year,
            "acquisition_status_at_freeze":row["acquisition_status"],
            "candidates":row["candidates"],"stratum":stratum,
            "reuse_and_version_group_review":"pending_source_review",
            "scientific_strata":"unannotated","reference_annotation":"not_started",
            "publication_version_verified":False})
    sizes = {k:len(v) for k,v in sorted(strata.items())}
    selected_counts = quotas(sizes, count)
    selected=[]; next_validation = count//2
    validation_counts={k:n//2 for k,n in selected_counts.items()}
    for k in sorted(selected_counts):
        if sum(validation_counts.values()) == next_validation: break
        if selected_counts[k] % 2: validation_counts[k] += 1
    for stratum, population in sorted(strata.items()):
        n = selected_counts[stratum]
        population.sort(key=lambda g:digest([seed,"select",g["group_id"]]))
        chosen = population[:n]
        chosen.sort(key=lambda g:digest([seed,"partition",g["group_id"]]))
        for index, group in enumerate(chosen):
            selected.append({**group,"sampling_probability":n/sizes[stratum],
                "sampling_probability_numerator":n,"sampling_probability_denominator":sizes[stratum],
                "evaluation_partition":"validation_reserved" if index<validation_counts[stratum] else "test_reserved",
                "source_content_read_for_plan":False,"ner_authorized_by_plan":False})
    return {"schema":"materials-evaluation-reservation/1","seed":seed,
        "source_plan_sha256":digest(source_plan),"source_inventory_sha256":digest(inventory),
        "excluded_work_ids_sha256":digest(sorted(exclusions)),"sampling_unit":"known_work_alias_group",
        "selection_method":"stratified SHA256 ranking without replacement; minimum two per nonempty metadata stratum",
        "population_papers":len(rows),"arxiv_papers":sum(r["source"]=="arxiv" for r in rows.values()),
        "eligible_arxiv_groups":sum(sizes.values()),"excluded_groups":excluded_groups,
        "strata":[{"stratum":k,"eligible_groups":sizes[k],"selected_groups":selected_counts[k]} for k in sizes],
        "selected_groups":selected,"partition_counts":dict(Counter(g["evaluation_partition"] for g in selected)),
        "scientific_reference_assertions":0,"independent_gold":False,"scientific_acceptance":False,
        "ml_training_eligible":False,"aps_download_allowed":False,
        "limitations":[
            "Reservation precedes annotation and source review; it is not a qualified sealed test set.",
            "Known DOI, related-paper and arXiv-version aliases are grouped; source-reported reused specimens require later connected-component adjudication.",
            "Material-family metadata is not a scientific label. Scientific strata and superconductivity relevance must be annotated from original papers.",
            "Missing archives remain in the sampling frame; acquisition failures cannot be silently replaced or counted as empty papers.",
            "Sampling probabilities apply to known work groups in this frozen corpus, not all superconductivity literature.",
            "Sources used to tune a repair must leave the reserved test partition and be replaced through a versioned sampling amendment."]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("source-plan","inventory","exclusions","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--seed",required=True);parser.add_argument("--count",type=int,default=120)
    args=parser.parse_args()
    if args.output.exists(): raise ValueError("evaluation_reservation_already_exists")
    inputs={k:getattr(args,k) for k in ("source_plan","inventory","exclusions")}
    data={k:json.loads(p.read_bytes()) for k,p in inputs.items()}
    plan=build_plan(data["source_plan"],data["inventory"],data["exclusions"]["work_ids"],seed=args.seed,count=args.count)
    plan.update(created_at=datetime.now(timezone.utc).isoformat(),
        input_files={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.values()},
        implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    args.output.mkdir(parents=True,mode=0o700)
    (args.output/"plan.json").write_text(json.dumps(plan,indent=2,ensure_ascii=False)+"\n")
    (args.output/"sampling-script.py").write_bytes(Path(__file__).read_bytes())
    print(canonical({"path":str(args.output/"plan.json"),"selected_groups":len(plan["selected_groups"]),
        "eligible_groups":plan["eligible_arxiv_groups"],"partitions":plan["partition_counts"],"scientific_reference_assertions":0}))


if __name__=="__main__": main()
