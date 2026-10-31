"""Sampling is metadata-only, reproducible, and conservatively alias-grouped."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest

path=Path(__file__).parents[1]/"materials_ner_evaluation_plan.py"
spec=importlib.util.spec_from_file_location("evaluation_plan",path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def fixture():
    papers=[]
    for i in range(40):
        papers.append({"id":f"arxiv:{i:04}","source":"arxiv","arxiv_id":str(i),
            "doi":f"10.example/{i}","title":"Synthetic metadata only","related_paper_id":None,
            "date_submitted":"2024-01-01" if i%2 else "1997-01-01"})
    inventory={"paper_plan":papers}
    rows=[dict(p,acquisition_status="available_in_gcs" if i%4<2 else "missing_archive",
               candidates=[],alternate_work_ids=[]) for i,p in enumerate(papers)]
    return {"schema":"materials-ner-source-plan/1","inventory_sha256":module.digest(inventory),"papers":rows},inventory


def test_reproducible_probabilities_and_disjoint_reservations():
    source,inventory=fixture();a=module.build_plan(source,inventory,[],seed="one",count=16)
    assert a==module.build_plan(source,inventory,[],seed="one",count=16)
    assert a["partition_counts"]=={"validation_reserved":8,"test_reserved":8}
    groups=a["selected_groups"];assert len({g["group_id"] for g in groups})==16
    assert all(g["sampling_probability"]==.4 for g in groups)
    assert not a["independent_gold"] and not a["ml_training_eligible"]
    assert all(not g["source_content_read_for_plan"] and not g["ner_authorized_by_plan"] for g in groups)
    assert {g["work_id"] for g in groups}!={g["work_id"] for g in module.build_plan(source,inventory,[],seed="two",count=16)["selected_groups"]}


def test_exclusion_propagates_through_doi_related_paper_and_version_aliases():
    source,inventory=fixture()
    source["papers"][1]["doi"]=source["papers"][0]["doi"]
    inventory["paper_plan"][2]["related_paper_id"]="arxiv:0001"
    version=deepcopy(source["papers"][2]);version["id"]+="v2";version["doi"]="10.other/version"
    source["papers"].append(version);inventory["paper_plan"].append(deepcopy(version))
    source["inventory_sha256"]=module.digest(inventory)
    plan=module.build_plan(source,inventory,["arxiv:0000"],seed="one",count=16)
    assert plan["excluded_groups"][0]["members"]==["arxiv:0000","arxiv:0001","arxiv:0002","arxiv:0002v2"]
    assert all(not set(g["known_work_aliases"]) & set(plan["excluded_groups"][0]["members"]) for g in plan["selected_groups"])


def test_stale_inventory_and_malformed_ownership_are_rejected():
    source,inventory=fixture();inventory["paper_plan"][0]["title"]="changed"
    with pytest.raises(ValueError,match="source_inventory_hash_mismatch"):
        module.build_plan(source,inventory,[],seed="one",count=16)
    source["inventory_sha256"]=module.digest(inventory);source["papers"]=source["papers"][:-1]
    with pytest.raises(ValueError,match="source_plan_metadata_ownership_mismatch"):
        module.build_plan(source,inventory,[],seed="one",count=16)


def test_small_strata_and_full_census_do_not_overallocate():
    assert module.quotas({"a":1,"b":9},4)=={"a":1,"b":3}
    assert module.quotas({"a":1,"b":9},10)=={"a":1,"b":9}
    with pytest.raises(ValueError):module.quotas({"a":4,"b":4},3)
    with pytest.raises(ValueError):module.quotas({"a":4,"b":4},9)
