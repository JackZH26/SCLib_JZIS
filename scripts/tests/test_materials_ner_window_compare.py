from copy import deepcopy
import json

import pytest

from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.sources import sha
from materials_ner_window_compare import (
    block_projection, covered_characters, literal_occurrences,
    possible_repeated_occurrences, project_evidence, result_coordinates,
)


def fixture():
    document = dict(id="D", source_uri="https://arxiv.org/src/examplev1", source_sha256="a"*64,
                    source_kind="original_tex", role="main", publication_version="v1", version_status="verified",
                    processing_permission="allowed", redistribution_permission="unresolved")
    blocks = [dict(id=f"B{i}", document_id="D", locator=f"pdf_page:{i}", text=text, sha256=sha(text.encode()))
              for i, text in enumerate(["Introduction. Tc = 40 K and onset = 40 K.", "Other sample: Tc = 40 K."])]
    parent = dict(work_id="P", documents=[document], blocks=blocks, acquisition_notes=[])
    start, end = 14, len(blocks[0]["text"])
    selected = blocks[0]["text"][start:end]
    child = dict(work_id="P", documents=[deepcopy(document)], blocks=[dict(
        id="W", document_id="D", locator=f"target:pdf_page:0:chars[{start}:{end}]", text=selected, sha256=sha(selected.encode()))],
        acquisition_notes=["SOURCE_WINDOW " + json.dumps(dict(parent_bundle_sha256=digest(parent),
            source_block_id="B0", source_block_sha256=blocks[0]["sha256"], start_char=start, end_char=end))])
    return parent, child


def evidence(block, start, end):
    return dict(block_id=block["id"], block_sha256=block["sha256"], document_id=block["document_id"],
                locator=block["locator"], start_char=start, end_char=end,
                quote_sha256=sha(block["text"][start:end].encode()), path="/results/0/quantity")


def test_whole_and_window_have_identical_original_coordinates():
    parent, window = fixture()
    whole = project_evidence(parent, parent, evidence(parent["blocks"][0], 14, 26))
    split = project_evidence(parent, window, evidence(window["blocks"][0], 0, 12))
    assert {k:v for k,v in whole.items() if k!="input_role"} == {k:v for k,v in split.items() if k!="input_role"}


@pytest.mark.parametrize("role", ["context-0", "context-previous-page", "context-next-page", "context-document", "revision-context"])
def test_context_same_number_on_other_page_keeps_other_identity(role):
    parent, window = fixture()
    block = deepcopy(parent["blocks"][1])
    block.update(id="C", locator=f"{role}:pdf_page:1:chars[0:{len(block['text'])}]")
    window["blocks"].append(block)
    mapped = project_evidence(parent, window, evidence(block, 0, len(block["text"])))
    assert mapped["block_id"] == "B1" and mapped["start_char"] == 0


@pytest.mark.parametrize("mutation", ["source_hash", "version", "document", "bytes", "parent", "slice", "target_range"])
def test_rejects_source_and_window_identity_drift(mutation):
    parent, window = fixture()
    if mutation=="source_hash": window["documents"][0]["source_sha256"]="b"*64
    elif mutation=="version": window["documents"][0]["publication_version"]="v2"
    elif mutation=="document": window["blocks"][0]["document_id"]="other"
    elif mutation=="bytes": window["blocks"][0]["text"]="modified"
    elif mutation=="parent": parent["work_id"]="different"
    elif mutation=="slice": window["blocks"][0]["locator"]="target:pdf_page:0:chars[0:25]"
    else:
        note=json.loads(window["acquisition_notes"][0].removeprefix("SOURCE_WINDOW "))
        note["end_char"]+=1
        window["acquisition_notes"][0]="SOURCE_WINDOW "+json.dumps(note)
    with pytest.raises(ValueError): block_projection(parent,window,"W")


@pytest.mark.parametrize("key,value", [("quote_sha256","b"*64),("end_char",1000),("start_char",-1),
                                      ("document_id","other"),("block_sha256","c"*64)])
def test_rejects_unverified_evidence(key,value):
    parent,window=fixture(); loc=evidence(window["blocks"][0],0,12); loc[key]=value
    with pytest.raises(ValueError): project_evidence(parent,window,loc)


def test_repeated_literals_stay_ambiguous_and_missing_values_unresolved():
    parent,window=fixture(); block=window["blocks"][0]
    packet=dict(bundle=window, rows={"results":[{"payload":{"quantity":{"raw":"40 K"}}}]},
                receipt={"validation":{"resolved_evidence":[evidence(block,0,len(block["text"]))]}})
    result=result_coordinates(parent,packet,0)
    assert result["anchor_status"]=="ambiguous" and len(result["literal_anchors"])==2
    packet["rows"]["results"][0]["payload"]["quantity"]["raw"]="41 K"
    assert result_coordinates(parent,packet,0)["anchor_status"]=="unresolved"


@pytest.mark.parametrize("text,raw,count", [("8.8 \\pm 0.2 K","8.8 \\pm 0.2",1),
    ("8.8 ± 0.2 K","8.8 \\pm 0.2",0),("140 K, 40 K, 40.1 K","40",1),
    ("40\n K","40 K",1),("39–41 K","40 K",0),("< 40 K","<40 K",1)])
def test_literal_matching_does_not_infer_or_rewrite_numeric_semantics(text,raw,count):
    assert len(literal_occurrences(text,raw))==count


def test_same_occurrence_with_different_criteria_is_flagged_without_merging():
    anchor=dict(document_id="D",block_id="B",block_sha256="a",start_char=10,end_char=14)
    records=[dict(record_id=str(i),work_id="P",criterion=c,coordinates=dict(anchor_status="unique",literal_anchors=[anchor]))
             for i,c in enumerate(["onset","midpoint"])]
    group=possible_repeated_occurrences(records)[0]
    assert group["record_ids"]==["0","1"] and not group["automatically_merged"]
    records[1]["coordinates"]={"anchor_status":"ambiguous","literal_anchors":[anchor,anchor]}
    assert possible_repeated_occurrences(records)==[]


def test_coverage_unions_overlap_but_keeps_pages_separate():
    assert covered_characters([("B",0,10),("B",5,15),("C",0,10)])==25
    with pytest.raises(ValueError): covered_characters([("B",10,9)])


def test_non_detection_retains_qualitative_field_evidence_without_numeric_zero():
    parent,_=fixture(); block=parent["blocks"][0]
    loc=evidence(block,0,len(block["text"]));loc["path"]="/results/0/quantity_kind"
    result=dict(quantity_kind="non_detection",quantity={"raw":None,"value":None},
                qualifiers=[{"kind":"non_detection","raw":"Introduction."}])
    packet=dict(bundle=parent,rows={"results":[{"payload":result}]},
                receipt={"validation":{"resolved_evidence":[loc]}})
    output=result_coordinates(parent,packet,0)
    assert output["anchor_status"]=="unique"
    assert output["field_evidence"][0]["field_path"]=="/results/0/quantity_kind"
    assert result["quantity"]["value"] is None
