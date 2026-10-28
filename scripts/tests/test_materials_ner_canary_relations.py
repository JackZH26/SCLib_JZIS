"""Finite graph checks never imply independent scientific acceptance."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest

SPEC=importlib.util.spec_from_file_location("canary_relations",Path(__file__).parents[1]/"materials_ner_canary_gate.py")
module=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(module)


def fixture():
    source=("synthetic:source","frozen"); quote="Synthetic Film A has MgO inclusions. XRR and TEM each report 8 nm. Film B is about 5 nm with unspecified method."
    evidence={"block_id":"b1","start_char":0,"end_char":len(quote),"quote":quote,"quote_sha256":module.sha(quote.encode())}
    checks=[
        {"id":"component","kind":"component_membership","parent_label":"A","component_formula":"MgO","no_inherited_kinds":["tc"],"evidence":evidence},
        {"id":"methods","kind":"geometry_measurement_supports","sample_label":"A","quantity_kind":"thickness","value":8,"unit":"nm","methods":["XRR","TEM"],"evidence":evidence},
        {"id":"approximate","kind":"typed_geometry_assertion","sample_label":"B","quantity_kind":"thickness","value":5,"unit":"nm","approximate":True,"evidence":evidence},
        {"id":"attribution","kind":"unattributed_method","sample_label":"B","quantity_kind":"thickness","forbidden_method_patterns":["XRR","TEM"],"evidence":evidence}]
    def q(v,approx=False): return {"status":"reported","relation":"exact","value":v,"unit":"nm","approximate":approx}
    graph={"samples":[{"id":"A","label":"A","formula_raw":"MgB2"},{"id":"B","label":"B","formula_raw":"MgB2"},{"id":"C","label":"component","formula_raw":"MgO"}],
        "states":[{"id":"SA","sample_id":"A","conditions":[{"id":"ca","kind":"thickness","role":"sample_geometry","quantity":q(8)}]},
                  {"id":"SB","sample_id":"B","conditions":[{"id":"cb","kind":"thickness","role":"sample_geometry","quantity":q(5,True)}]}],
        "protocols":[{"id":"PX","method":"XRR"},{"id":"PT","method":"TEM"}],
        "results":[{"id":"R1","sample_id":"A","state_id":"SA","protocol_id":"PX","quantity_kind":"thickness","quantity":q(8),"origin":"observed"},
                   {"id":"R2","sample_id":"A","state_id":"SA","protocol_id":"PT","quantity_kind":"thickness","quantity":q(8),"origin":"observed"}],
        "sample_relations":[{"id":"component","from_sample_id":"C","to_sample_id":"A","relation":"component_of"}],
        "condition_supports":[{"id":"s1","result_id":"R1","state_id":"SA","condition_id":"ca"},{"id":"s2","result_id":"R2","state_id":"SA","condition_id":"ca"}]}
    return checks,[{"job_id":"j1","structured_graph":graph}],{source:{"blocks":[{"id":"b1","text":quote}]}},{"j1":source}


def test_all_four_graph_obligations_are_distinct_from_approval():
    report=module.relational_context_checks(*fixture())
    assert len(report)==4 and all(r["check_satisfied"] for r in report)
    assert all(r["independently_reviewed"] is False for r in report)


@pytest.mark.parametrize("mutation,index",[("orphan",0),("inherit",0),("missing_support",1),
    ("wrong_condition",1),("fitted",1),("approximation_lost",2),("borrowed_method",3)])
def test_wrong_scientific_relationship_is_not_hidden_by_matching_numbers(mutation,index):
    args=fixture(); graph=args[1][0]["structured_graph"]
    if mutation=="orphan": graph["sample_relations"]=[]
    if mutation=="inherit": graph["results"].append(dict(graph["results"][0],id="bad-tc",sample_id="C",quantity_kind="tc"))
    if mutation=="missing_support": graph["condition_supports"].pop()
    if mutation=="wrong_condition": graph["condition_supports"][0]["condition_id"]="cb"
    if mutation=="fitted": graph["results"][0]["quantity_kind"]="superconducting_layer_thickness"
    if mutation=="approximation_lost": graph["states"][1]["conditions"][0]["quantity"]["approximate"]=False
    if mutation=="borrowed_method": graph["results"].append(dict(graph["results"][0],id="bad-method",sample_id="B",state_id="SB"))
    assert not module.relational_context_checks(*args)[index]["check_satisfied"]


@pytest.mark.parametrize("mutation",["quote","hash","offset","missing","ambiguous","kind"])
def test_unverified_reference_cannot_produce_a_relation_judgment(mutation):
    checks,graphs,bundles,jobs=fixture()
    if mutation=="quote": checks[0]["evidence"]["quote"]="invented"
    if mutation=="hash": checks[0]["evidence"]["quote_sha256"]="0"*64
    if mutation=="offset": checks[0]["evidence"]["start_char"]=-1
    if mutation=="missing": bundles={}
    if mutation=="ambiguous": bundles["other","bundle"]=deepcopy(next(iter(bundles.values())))
    if mutation=="kind": checks[0]["kind"]="not_implemented"
    with pytest.raises(ValueError): module.relational_context_checks(checks,graphs,bundles,jobs)


def test_wrong_source_and_empty_graph_cannot_discharge_positive_obligations():
    checks,graphs,bundles,jobs=fixture();jobs["j1"]=("another","source")
    assert not any(r["check_satisfied"] for r in module.relational_context_checks(checks,graphs,bundles,jobs))
    checks,graphs,bundles,jobs=fixture();graphs[0]["structured_graph"]=None
    assert not any(r["check_satisfied"] for r in module.relational_context_checks(checks,graphs,bundles,jobs))
