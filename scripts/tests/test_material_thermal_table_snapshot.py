"""Checks on the actual retained Table II facts, not scientific gold labels."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.build_material_thermal_table import CAPTURE, NAME, ROOT, build, project_capture, serialized, sha256


def capture():
    return json.loads(CAPTURE.read_text(encoding="utf-8"))


def test_actual_four_readings_reproduce_the_published_metadata():
    snapshot = project_capture(capture())
    assert [(r["formula_as_printed"], r["raw_value"], r["raw_unit"]) for r in snapshot["readings"]] == [
        ("Mo5P1.1B1.9", "3.16", "mJ/mol-at./K2"), ("Mo5P1.1B1.9", "492", "K"),
        ("Mo5PB2", "3.07", "mJ/mol-at./K2"), ("Mo5PB2", "501", "K"),
    ]
    data = serialized(snapshot)
    assert (ROOT / "frontend/public/research-pilots" / NAME).read_bytes() == data
    assert sha256(data) == "461a1212c58e97c46eb734deaa38870753e65c89c9709442b312a091586e6891"
    assert (ROOT / "frontend/public/research-pilots" / (NAME + ".sha256")).read_text() == f"{sha256(data)}  {NAME}\n"


def test_original_cell_unit_header_and_caption_pins_replay_from_actual_text():
    source = capture()
    snapshot = project_capture(source)
    for reading in snapshot["readings"]:
        pins = reading["spans_in_table_text"]
        for name, pin in pins.items():
            token = source["text"][pin["char_start"]:pin["char_end"]]
            assert sha256(token.encode()) == pin["text_sha256"]
            if name == "value":
                assert token == reading["raw_value"]
            if name == "composition":
                assert token == reading["formula_as_printed"]
            if name == "unit":
                assert token.rstrip() == reading["raw_unit"]
        assert pins["unit"]["char_end"] < pins["value"]["char_start"]
        assert reading["raw_uncertainty"] is None
        assert reading["normalization"] == "none"
    assert snapshot["scope"]["independent_experiment_count"] is None
    assert snapshot["scope"]["table_I_sample_association"] == "unestablished"
    assert not any(snapshot["authority"].values())
    assert not any(key in serialized(snapshot).decode() for key in (
        '"evidence_text"', '"retained_result_id"', '"material_id"', '"source-study:', '/Users/', '/private/tmp/',
    ))


@pytest.mark.parametrize("change", ["header", "row", "span", "url", "authority"])
def test_changed_capture_does_not_publish_reassigned_or_unverified_readings(change):
    source = deepcopy(capture())
    if change == "header":
        source["table"]["headers"][1] = "Mo5P1.07B1.93"
    elif change == "row":
        source["table"]["rows"][1]["cells"][1]["text"] = "3.16(1)"
    elif change == "span":
        source["table"]["rows"][1]["cells"][1]["char_start"] = 185
    elif change == "url":
        source["source_url"] = "https://example.org/not-the-paper"
    else:
        source["publication_revision_verified"] = True
    with pytest.raises(ValueError, match="inspected snapshot"):
        project_capture(source)


def test_builder_rejects_bytes_without_original_text_and_pdf_pins():
    with pytest.raises(ValueError, match="Original text or PDF"):
        build(capture(), b"unverified full text", b"%PDF-unverified")
