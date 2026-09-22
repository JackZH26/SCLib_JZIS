"""Synthetic document transport checks; never a real pilot or identity grant."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from services import ml_pilot_accounting as accounting
from services import ml_pilot_documents as documents

from scripts import validate_pilot_review as cli
from scripts.tests.test_pilot_review import complete_fixture

ROOT = Path(__file__).resolve().parents[2]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inputs():
    selection, reviews, conclusion = complete_fixture()
    protocol = b"Synthetic protocol bytes; not protocol approval."
    selection["protocol_sha256"] = sha(protocol)
    selection["selection_sha256"] = accounting.selection_hash(selection)
    for review in reviews:
        review["selection_sha256"] = selection["selection_sha256"]
    conclusion.update(selection_sha256=selection["selection_sha256"], review_log_sha256=accounting.review_hash(reviews))
    raw = {"selection": accounting.canonical(selection), "reviews": b"\n".join(accounting.canonical(r) for r in reviews),
           "protocol": protocol, "conclusion": accounting.canonical(conclusion)}
    return {**{k + "_raw": v for k, v in raw.items()}, **{k + "_file_sha256": sha(v) for k, v in raw.items()},
            "selection_sha256": selection["selection_sha256"], "review_log_sha256": accounting.review_hash(reviews)}


def test_cli_and_installed_service_share_one_accounting_kernel_and_exact_schema():
    assert cli.validate is accounting.validate and cli.selection_hash is accounting.selection_hash
    assert cli.json_value is documents.json_value and cli.review_records is documents.review_records
    assert accounting.SCHEMA_PATH.read_bytes() == (ROOT / "docs/pilot/ML08_Pilot.schema.json").read_bytes()
    source = (ROOT / "scripts/validate_pilot_review.py").read_text()
    assert "def validate(" not in source and "def _result_errors(" not in source


def test_complete_documentary_package_does_not_authenticate_or_register_anything():
    args = inputs()
    expected = accounting.validate(documents.json_value(args["selection_raw"]), documents.review_records(args["reviews_raw"]),
                                   documents.json_value(args["conclusion_raw"]), args["selection_sha256"])
    result = documents.inspect_documents(**args)
    assert result["accounting"] == expected and expected["ready_for_final_human_signoff"]
    assert result["accounting"]["counts"]["selected_candidates"] == 60
    assert not any(result["authority"].values()) and result["training_execution"] == "disabled"
    assert not any(result[k] for k in ("context_bytes_checked", "canary_replay_verified", "registration_recorded"))
    assert result["input_pins"]["reviews_file_sha256"] != result["review_log_sha256"]


@pytest.mark.parametrize("name", ["selection", "reviews", "protocol", "conclusion"])
def test_raw_bytes_cannot_change_under_retained_anchors(name):
    args = inputs(); args[name + "_raw"] += b" "
    with pytest.raises(documents.PilotDocumentError, match="bytes_mismatch"):
        documents.inspect_documents(**args)


@pytest.mark.parametrize("name", ["selection_sha256", "review_log_sha256"])
def test_logical_anchors_cannot_be_inferred_or_replaced(name):
    args = inputs(); args[name] = "e" * 64
    with pytest.raises(documents.PilotDocumentError, match="logical_anchor_mismatch"):
        documents.inspect_documents(**args)
    args[name] = None
    with pytest.raises(documents.PilotDocumentError, match="logical_anchor_required"):
        documents.inspect_documents(**args)


@pytest.mark.parametrize("name", ["selection_raw", "reviews_raw", "protocol_raw", "conclusion_raw"])
def test_actual_eight_mib_per_document_limit_rejects_before_decoding(name):
    args = inputs(); args[name] = b" " * (8 * 1024 * 1024 + 1)
    args[name.replace("_raw", "_file_sha256")] = sha(args[name])
    with pytest.raises(documents.PilotDocumentError, match="byte_limit"):
        documents.inspect_documents(**args)


@pytest.mark.parametrize("raw", [b'{"duplicate":1,"duplicate":2}', b'{"n":1e999}', b'{"n":NaN}', b'"\\ud800"',
    b"[" * 66 + b"0" + b"]" * 66, b"\xff", b"true false"])
def test_bounded_json_refuses_ambiguous_nonfinite_surrogate_deep_or_invalid_bytes(raw):
    with pytest.raises(documents.PilotDocumentError, match="json_invalid"):
        documents.json_value(raw)


def test_protocol_pin_must_match_selection_even_if_uploads_are_self_consistent():
    args = inputs(); args["protocol_raw"] = b"Different synthetic protocol"
    args["protocol_file_sha256"] = sha(args["protocol_raw"])
    with pytest.raises(documents.PilotDocumentError, match="protocol_mismatch"):
        documents.inspect_documents(**args)


@pytest.mark.parametrize("missing", ["conclusion_raw", "conclusion_file_sha256"])
def test_conclusion_bytes_and_pin_must_be_present_together(missing):
    args = inputs(); args[missing] = None
    with pytest.raises(documents.PilotDocumentError, match="conclusion_pair_required"):
        documents.inspect_documents(**args)


def test_no_reviews_or_conclusion_is_not_completed_science_and_denominator_is_retained():
    args = inputs(); args.update(reviews_raw=b"", reviews_file_sha256=sha(b""), review_log_sha256=accounting.review_hash([]),
                                  conclusion_raw=None, conclusion_file_sha256=None)
    value = documents.inspect_documents(**args)
    assert value["accounting"]["counts"]["unreviewed_candidates"] == 60
    assert not value["accounting"]["ready_for_final_human_signoff"]


def test_review_limit_and_jsonl_object_boundary():
    with pytest.raises(documents.PilotDocumentError, match="review_limit"):
        documents.review_records(b"{}\n" * (accounting.MAX_REVIEWS + 1))
    with pytest.raises(documents.PilotDocumentError, match="review_object_required"):
        documents.review_records(b"null\n")
    text = "Unmodified source separators: \u2028 \u2029 \r\n and 数据"
    row = {"source": text}
    assert documents.review_records(b"\n " + accounting.canonical(row) + b"\r\n") == [row]


def test_jsonl_total_node_budget_is_checked_before_record_parsing(monkeypatch):
    def forbidden(_raw):
        raise AssertionError("record parser reached before cumulative allocation guard")
    monkeypatch.setattr(documents, "json_value", forbidden)
    # Under 8 MiB, individually small records, but over the true total-node cap.
    row = b'{"values":[' + b"0," * 999 + b"0]}\n"
    with pytest.raises(documents.PilotDocumentError, match="json_invalid"):
        documents.review_records(row * 401)


def test_wheel_probe_refuses_normal_repository_python_without_isolation():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/probe_ml_pilot_install.py")],
        capture_output=True, text=True, check=False, timeout=15)
    assert result.returncode != 0 and "requires_isolated_python" in result.stderr


def test_ci_installs_real_wheel_into_separate_dependency_free_environment():
    workflow = (ROOT / ".github/workflows/test.yml").read_text()
    api = workflow.split("\n  api-tests:", 1)[1].split("\n  migration-tests:", 1)[0]
    required = ('uv build --wheel --out-dir "$RUNNER_TEMP/sclib-ml08-wheel" .',
                '.venv/bin/python -m venv "$RUNNER_TEMP/sclib-ml08-installed"',
                '"$RUNNER_TEMP/sclib-ml08-installed/bin/python" -m pip install --no-index --no-deps',
                '"$RUNNER_TEMP/sclib-ml08-installed/bin/python" -I ../scripts/probe_ml_pilot_install.py',
                '"$RUNNER_TEMP/sclib-ml08-installed/bin/python" -I ../scripts/probe_ml_pilot_registration_install.py',
                "Verify all offline script contracts")
    assert [api.index(step) for step in required] == sorted(api.index(step) for step in required)


def test_reports_do_not_share_mutable_warning_or_authority_state():
    args = inputs(); before = documents.inspect_documents(**args)
    mutated = documents.inspect_documents(**args)
    mutated["accounting"]["warnings"].append("Synthetic contamination")
    mutated["authority"]["scientific_acceptance"] = True
    assert documents.inspect_documents(**args) == before


def test_cli_keeps_literal_unicode_line_separators_inside_jsonl(tmp_path):
    args = inputs(); reviews = documents.review_records(args["reviews_raw"])
    reviews[0]["outcome_reason"] = "Synthetic literal \u2028 source separator \u2029 preserved"
    selection_file, reviews_file = tmp_path / "selection.json", tmp_path / "reviews.jsonl"
    selection_file.write_bytes(args["selection_raw"])
    reviews_file.write_bytes(b"\n".join(accounting.canonical(r) for r in reviews))
    result = subprocess.run([sys.executable, str(ROOT / "scripts/validate_pilot_review.py"), str(selection_file), str(reviews_file),
        "--expected-selection-sha256", args["selection_sha256"], "--require", "ready"], capture_output=True, text=True, check=False, timeout=15)
    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["review_log_sha256"] == accounting.review_hash(reviews)


def test_unknown_field_or_scientific_conflict_is_a_diagnostic_not_a_grant():
    args = inputs(); selection = documents.json_value(args["selection_raw"])
    selection["private_unknown_field"] = "Do not echo this source-like text"
    selection["selection_sha256"] = accounting.selection_hash(selection)
    args.update(selection_raw=accounting.canonical(selection), selection_sha256=selection["selection_sha256"])
    args["selection_file_sha256"] = sha(args["selection_raw"])
    value = documents.inspect_documents(**args)
    assert value["accounting"]["status"] == "invalid" and value["accounting"]["errors"]
    assert "Do not echo" not in json.dumps(value)
    assert not any(value["authority"].values())
