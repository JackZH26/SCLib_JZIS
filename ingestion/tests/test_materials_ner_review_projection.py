"""Data-loss and source-integrity regressions for the private review export."""
import json
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from materials_ner_pilot_projection import project
from ingestion.materials_ner.sources import Bundle, Document, make_blocks, save_bundle, sha


def fixture(tmp_path, quote="Tc = 7.321 K", text="The reported Tc = 7.321 K for sample A."):
    source = tmp_path / "synthetic.txt"
    source.write_text(text)
    doc = Document(id="doc:test",source_uri="https://example.test/synthetic-v1",source_sha256=sha(source.read_bytes()),
        source_kind="original_text",role="main",publication_version="v1",version_status="verified",
        processing_permission="allowed",redistribution_permission="unresolved",coverage="partial",parser="synthetic-test/1")
    bundle = Bundle(version="materials-source-bundle/1",work_id="test:1",title="Synthetic fixture",family=None,
        source_status="unresolved",supplement_status="not_checked",documents=[doc],
        blocks=make_blocks(doc.id,[("test:1",text)]),acquisition_notes=[])
    digest,_=save_bundle(tmp_path,bundle)
    def ev(field): return {"block_id":bundle.blocks[0].id,"quote":quote,"field":field}
    row={"row_id":"job:O1","job_id":"job","work_id":"test:1","bundle_sha256":digest,
         "receipt_sha256":"a"*64,"technical_review_status":"quarantined",
         "scientific_acceptance":False,"ml_training_eligible":False,
         "sample":{"id":"s1","formula_raw":"Nb","evidence":[ev("/formula_raw")]},
         "state":{"id":"st1","sample_id":"s1","evidence":[ev("/sample_id")]},
         "protocol":{"id":"p1","method":None,"criterion":"unspecified","evidence":[]},
         "result":{"id":"O1","sample_id":"s1","state_id":"st1","protocol_id":"p1","quantity_kind":"tc",
                   "quantity":{"value":0.,"unit":"K","approximate":False,"status":"reported","uncertainty":None},
                   "evidence":[ev("/quantity"),ev("/quantity_kind")]}}
    run=tmp_path/"runs/test"
    run.mkdir(parents=True)
    (run/"observations.jsonl").write_text(json.dumps(row)+"\n")
    (tmp_path/"plan.json").write_text(json.dumps({"papers":[{"source_capture":{"local_path":str(source),"sha256":doc.source_sha256}}]}))
    return row,source


def test_shared_quotes_preserve_fields_zero_false_and_reject_promotion(tmp_path):
    row,_=fixture(tmp_path)
    output=tmp_path/"projection.sqlite3"
    report=project(tmp_path,"test",output)
    assert report["field_bindings"]==4 and report["source_spans"]==1
    assert report["reported_quote_variants"]==1
    assert report["meaningful_row_and_evidence_round_trip"]
    with sqlite3.connect(output) as db:
        payload=json.loads(db.execute("SELECT payload FROM result_proposals").fetchone()[0])
        assert payload["quantity"]["value"]==0 and payload["quantity"]["approximate"] is False
        assert payload["quantity"]["status"]=="reported"
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE result_proposals SET scientific_acceptance=1")
        assert [json.loads(r[0]) for r in db.execute("SELECT payload FROM evidence WHERE entity_type='result' ORDER BY ordinal")]==row["result"]["evidence"]
    with pytest.raises(ValueError,match="already exists"):
        project(tmp_path,"test",output)


@pytest.mark.parametrize("quote,text,status",[
    ("Tc = 7.321 K","Tc = 7.321 K. Also Tc = 7.321 K.","ambiguous_quote_locator"),
    ("Tc = 9 K","Tc = 7.321 K.","quote_not_in_locked_source"),
])
def test_unresolved_locations_do_not_invent_source_spans(tmp_path,quote,text,status):
    row,_=fixture(tmp_path,quote,text)
    output=tmp_path/"projection.sqlite3"
    report=project(tmp_path,"test",output)
    assert report["source_spans"]==0 and report["location_statuses"]=={status:4}
    with sqlite3.connect(output) as db:
        assert db.execute("SELECT count(*) FROM field_bindings WHERE span_id IS NULL").fetchone()[0]==4
        assert json.loads(db.execute("SELECT payload FROM evidence LIMIT 1").fetchone()[0])["quote"]==quote


def test_source_capture_tampering_stops_export(tmp_path):
    _,source=fixture(tmp_path)
    source.write_text("Changed after freeze")
    output=tmp_path/"projection.sqlite3"
    with pytest.raises(ValueError,match="capture integrity"):
        project(tmp_path,"test",output)
    assert not output.exists()


def test_results_cannot_be_rebound_to_a_different_samples_state(tmp_path):
    fixture(tmp_path)
    output=tmp_path/"projection.sqlite3"
    project(tmp_path,"test",output)
    with sqlite3.connect(output) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO samples VALUES('job','s2','{}')")
        db.execute("INSERT INTO states VALUES('job','st2','s2','{}')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE result_proposals SET state_id='st2'")
