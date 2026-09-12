"""Real offline report/replay and inert HTML checks; all supplied events are synthetic."""
from __future__ import annotations

import copy
import json
import os
import socket
import stat
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

from scripts import ml_pilot_report as report
from scripts.tests import test_ml_pilot_canary as fixtures
from scripts.tests.test_ml_pilot_canary import (
    cli,
    put,
    rewrite,
    verification,
)
from scripts.tests.test_pilot_review import review


@pytest.fixture
def case(tmp_path):
    return fixtures.case.__wrapped__(tmp_path)


class Document(HTMLParser):
    def __init__(self, payload):
        super().__init__(convert_charrefs=True)
        self.nodes, self.text = [], []
        self.feed(payload.decode())

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def arguments(case):
    built = cli.run(**case[0])
    inputs = verification(case, built)
    inputs.pop("mode"); inputs.pop("output_path")
    return {"mode": "build", "output_path": case[0]["output_path"].parent / "review.html", **inputs}


def replay(args, receipt):
    return {**args, "mode": "verify", "output_path": None, "report_path": args["output_path"],
            "expected_report_sha256": receipt["report_sha256"]}


def test_actual_report_preserves_every_event_and_revision_without_network_or_authority(case, monkeypatch):
    args = arguments(case)
    monkeypatch.setattr(socket, "socket", lambda *_a, **_k: pytest.fail("Offline report must not connect"))
    before = {key: value.read_bytes() for key, value in args.items() if key.endswith("_path") and key != "output_path"}
    receipt = report.run(**args)
    payload = args["output_path"].read_bytes(); doc = Document(payload)
    assert receipt["report_sha256"] == cli.sha(payload)
    assert receipt["report_bytes"] == len(payload)
    assert receipt["output_written"] and not receipt["report_replay_verified"]
    assert all(v is False for v in receipt["authority"].values()) and receipt["training_execution"] == "disabled"
    assert receipt["private_review_declarations_embedded"] and not receipt["source_context_bytes_embedded"]
    assert "SYNTHETIC TEST CONTEXT" not in payload.decode() and "SYNTHETIC TEST PROTOCOL" not in payload.decode()
    assert stat.S_IMODE(args["output_path"].stat().st_mode) == 0o600 and args["output_path"].stat().st_nlink == 1
    assert len([n for n, a in doc.nodes if n == "details" and a.get("id", "").startswith("event-")]) == 60
    plain = "\n".join(doc.text)
    for row in case[2]: assert row["review_id"] in plain
    for field in cli.pilot.FIELDS: assert field in plain
    for status in report.STATUSES: assert status in plain
    assert "Not recorded" in plain and "0/62 review records timed" in plain and "60/60" in plain
    assert "Records" not in receipt and "pilot_id" not in receipt
    assert report.run(**replay(args, receipt))["report_replay_verified"]
    assert {key: args[key].read_bytes() for key in before} == before


def test_all_failed_cohort_keeps_sixty_events_zero_atomic_denominator_and_no_fabricated_time(case):
    args0, selection, reviews, conclusion = case
    for row in reviews: row.update(outcome="inaccessible", results=[], active_minutes=None, active_minutes_by_field={})
    for path in args0["evidence_directory"].iterdir(): path.unlink()
    conclusion.update(recommendation="stop", rationale="SYNTHETIC inaccessible cohort: stop, not a success threshold")
    rewrite(args0, selection, reviews)
    args = arguments(case); result = report.run(**args); body = args["output_path"].read_text()
    assert body.count('id="event-') == 60
    assert "Not recorded; 0/62 review records timed" in body
    assert "0/60" in body and "<strong>stop</strong>" in body
    assert "<td>atomic_results_in_effective_reviews</td><td>0</td>" in body
    assert "<td>inaccessible</td><td>60</td><td>60</td>" in body
    assert report.run(**replay(args, result))["report_replay_verified"]


def test_group_field_timing_uses_all_revisions_and_frozen_source_classes(case):
    args0, selection, reviews, _ = case
    selection["candidates"][2].update(family="synthetic-family-B", source_class="synthetic-table-B")
    old = copy.deepcopy(reviews[2]); new = copy.deepcopy(old)
    new.update(review_id="SYNTHETIC-revision-2", revision=2, supersedes_review_id=old["review_id"],
               active_minutes=7, active_minutes_by_field={"tc_value": 3})
    new["results"][0]["tc"]["value"] = 0.08
    reviews.append(new); rewrite(args0, selection, reviews)
    args = arguments(case); report.run(**args); body = args["output_path"].read_text()
    assert "synthetic-table-B — 1 selected events" in body
    assert "5 recorded min; 2/2 review records timed" in body
    assert "2/63 review records timed" not in body  # Unrecorded fields stay explicit, never inferred timed.
    assert "SYNTHETIC-revision-2" in body and old["review_id"] in body
    assert '0.08 K' in body and '0.03' in body


@pytest.mark.parametrize("relation,expected", [("exact", "0.03 K"), ("lt", "&lt; 0.03 K"), ("le", "≤ 0.03 K"),
    ("gt", "&gt; 0.03 K"), ("ge", "≥ 0.03 K"), ("interval", "[0.01, 0.05] K")])
def test_normalized_quantity_relations_are_never_replaced_by_points(case, relation, expected):
    args0, selection, reviews, _ = case
    q = reviews[2]["results"][0]["tc"]
    q.update(relation=relation, value=0.03 if relation == "exact" else None,
             lower=0.03 if relation in {"gt", "ge"} else 0.01 if relation == "interval" else None,
             upper=0.03 if relation in {"lt", "le"} else 0.05 if relation == "interval" else None)
    rewrite(args0, selection, reviews)
    args = arguments(case); report.run(**args)
    assert "approximately " + expected + "; uncertainty 0.001 K" in args["output_path"].read_text()


def test_nontransition_and_unknown_pressure_remain_explicit(case):
    args0, selection, reviews, _ = case
    row = reviews[2]["results"][0]
    row.update(observation="not_detected", tc=None, tested_temperature_min_k=0.03)
    row["fields"]["tc_value"] = "not_applicable"; row["missingness_reasons"]["tc_value"] = "SYNTHETIC measured window"
    rewrite(args0, selection, reviews)
    args = arguments(case); report.run(**args); body = args["output_path"].read_text()
    assert "<td>not_detected</td><td>Not applicable (not detected)</td><td>0.03</td>" in body
    assert "<td>unknown</td><td>Not recorded</td>" in body


def test_duplicate_results_keep_event_associations_separate(case):
    args0, selection, reviews, _ = case
    reviews[3]["results"] = copy.deepcopy(reviews[2]["results"])
    rewrite(args0, selection, reviews); args = arguments(case); report.run(**args)
    body = args["output_path"].read_text()
    assert "<td>event_result_associations</td><td>60</td>" in body
    assert "<td>atomic_results_in_effective_reviews</td><td>59</td>" in body
    assert "<td>independent_work_count</td><td>Not recorded</td>" in body


@pytest.mark.parametrize("origin", ["Observed", "Computed", "Inferred"])
def test_result_origins_remain_separate_recorded_assertions_not_a_mixed_target(case, origin):
    args0, selection, reviews, _ = case
    reviews[2]["results"][0]["origin"] = origin
    rewrite(args0, selection, reviews); args = arguments(case); receipt = report.run(**args)
    assert "<td>" + origin + "</td><td>positive_tc</td>" in args["output_path"].read_text()
    assert not receipt["authority"]["ml_training_approved"]


def test_explicit_zero_time_is_distinct_from_unrecorded_time(case):
    args0, selection, reviews, _ = case
    for row in reviews: row.update(active_minutes=None, active_minutes_by_field={})
    reviews[2].update(active_minutes=0, active_minutes_by_field={"tc_value": 0})
    rewrite(args0, selection, reviews); args = arguments(case); report.run(**args)
    body = args["output_path"].read_text()
    assert "0 recorded min; 1/62 review records timed" in body
    assert "Not recorded; 0/62 review records timed" in body


def test_renderer_byte_ceiling_refuses_output_without_truncation(case, monkeypatch):
    args = arguments(case)
    monkeypatch.setattr(report, "MAX_REPORT_BYTES", 100)
    with pytest.raises(ValueError, match="pilot_report_byte_limit"): report.run(**args)
    assert not args["output_path"].exists()


def test_unresolved_arbitration_retains_both_claims_errors_and_pending_result(case):
    args0, selection, reviews, _ = case
    reviews[60].update(comparison="disagreement", disagreement_codes=["SYNTHETIC-state-dispute"])
    reviews[60]["results"][0]["tc"]["value"] = 0.1
    arb = review(selection, 0, "arbitration")
    arb.update(compares_review_ids=[reviews[0]["review_id"], reviews[60]["review_id"]], comparison="unresolved",
               disagreement_codes=["SYNTHETIC-state-dispute"], outcome="unresolved")
    arb["results"][0]["decision"] = "pending"
    arb["results"][0]["source"] = copy.deepcopy(reviews[0]["results"][0]["source"])
    arb["results"][0]["errors"] = [{"kind": "state_association", "field": "sample_state", "code": "SYNTHETIC-unresolved-state"}]
    reviews.append(arb); rewrite(args0, selection, reviews)
    args = arguments(case); report.run(**args); body = args["output_path"].read_text()
    assert "SYNTHETIC-state-dispute" in body and "SYNTHETIC-arbitration-0-v1" in body
    assert "SYNTHETIC-unresolved-state" in body and "0.1" in body
    assert "<td>pending</td><td>1</td>" in body and "<td>unresolved</td><td>1</td><td>60</td>" in body


def test_every_supplied_string_is_inert_text_not_markup_link_script_or_css(case):
    args0, selection, reviews, conclusion = case
    hostile = '</pre></style><script>window.PWNED=1</script><img src="https://invalid.test/leak"><a href="file:///private">bad</a>'
    selection["pilot_id"] = "SYNTHETIC TEST ONLY " + hostile
    selection["candidates"][2]["source_reference"] = hostile
    reviews[2]["outcome_reason"] = hostile
    reviews[2]["results"][0]["source"]["context_reference"] = "javascript:alert(1)"
    conclusion["rationale"] = hostile
    rewrite(args0, selection, reviews); args = arguments(case); report.run(**args)
    payload = args["output_path"].read_bytes(); doc = Document(payload)
    assert hostile in "\n".join(doc.text)
    assert all(tag not in {"script", "img", "iframe", "object", "embed", "form", "input", "link"} for tag, _ in doc.nodes)
    assert all(not any(k.lower().startswith("on") or k in {"src", "srcdoc", "style"} for k in attrs) for _, attrs in doc.nodes)
    assert [(tag, attrs["href"]) for tag, attrs in doc.nodes if "href" in attrs] == [
        ("a", "#summary"), ("a", "#fields"), ("a", "#events"), ("a", "#provenance")]
    assert ("html", {"lang": "en"}) in doc.nodes
    assert any(attrs.get("http-equiv") == "Content-Security-Policy" and "default-src 'none'" in attrs["content"] for _, attrs in doc.nodes)


@pytest.mark.parametrize("kind", ["canary_pin", "conclusion_pin", "context", "protocol", "conclusion_not_bound", "resealed_canary"])
def test_bad_inputs_never_produce_report(case, kind):
    args = arguments(case)
    if kind == "canary_pin": args["expected_bundle_sha256"] = "e" * 64
    if kind == "conclusion_pin": args["expected_conclusion_sha256"] = "e" * 64
    if kind == "context": next(args["evidence_directory"].iterdir()).write_bytes(b"changed")
    if kind == "protocol": args["protocol_path"].write_bytes(b"changed")
    if kind == "conclusion_not_bound":
        value = json.loads(args["conclusion_path"].read_bytes()); value["canary_bundle_sha256"] = "e" * 64
        args["expected_conclusion_sha256"] = put(args["conclusion_path"], value)
    if kind == "resealed_canary":
        value = json.loads(args["bundle_path"].read_bytes()); value["accounting"]["counts"]["selected_candidates"] = 59
        payload = cli.canonical(value); args["bundle_path"].write_bytes(payload)
        args["expected_bundle_sha256"] = cli.sha(payload)
        conclusion = json.loads(args["conclusion_path"].read_bytes())
        conclusion["canary_bundle_sha256"] = args["expected_bundle_sha256"]
        args["expected_conclusion_sha256"] = put(args["conclusion_path"], conclusion)
    with pytest.raises((ValueError, OSError)): report.run(**args)
    assert not args["output_path"].exists()


def test_reformatted_canary_cannot_redefine_the_canonical_file_pin(case):
    args = arguments(case)
    value = json.loads(args["bundle_path"].read_bytes())
    args["expected_bundle_sha256"] = put(args["bundle_path"], value)
    conclusion = json.loads(args["conclusion_path"].read_bytes())
    conclusion["canary_bundle_sha256"] = args["expected_bundle_sha256"]
    args["expected_conclusion_sha256"] = put(args["conclusion_path"], conclusion)
    with pytest.raises(ValueError, match="ml_audited_canonical_required"): report.run(**args)
    assert not args["output_path"].exists()


@pytest.mark.parametrize("kind", ["context", "conclusion", "bundle", "renderer", "oversized"])
def test_changes_during_render_are_detected_before_creation(case, monkeypatch, kind):
    args = arguments(case); original = report.render
    def changed(*values, **kwargs):
        payload = original(*values, **kwargs)
        if kind == "context": next(args["evidence_directory"].iterdir()).write_bytes(b"changed")
        if kind in {"conclusion", "bundle"}: args[kind + "_path"].write_bytes(b"changed")
        if kind == "renderer": monkeypatch.setattr(report, "__file__", str(args["protocol_path"]))
        if kind == "oversized": payload = b"x" * (report.MAX_REPORT_BYTES + 1)
        return payload
    monkeypatch.setattr(report, "render", changed)
    with pytest.raises((ValueError, OSError)): report.run(**args)
    assert not args["output_path"].exists()


@pytest.mark.parametrize("kind", ["existing", "symlink", "parent_symlink", "in_evidence", "traversal", "fifo", "directory"])
def test_exclusive_output_does_not_overwrite_or_modify_closed_evidence(case, kind):
    args = arguments(case); target = args["output_path"]
    if kind == "existing": target.write_bytes(b"USER_DATA")
    if kind == "symlink": target.symlink_to(args["protocol_path"])
    if kind == "parent_symlink":
        alias = target.parent.parent / "alias"; alias.symlink_to(target.parent, target_is_directory=True); args["output_path"] = alias / "review.html"
    if kind == "in_evidence": args["output_path"] = args["evidence_directory"] / "review.html"
    if kind == "traversal": args["output_path"] = target.parent / ".." / "review.html"
    if kind == "fifo": os.mkfifo(target)
    if kind == "directory": target.mkdir()
    before = {p.name: p.read_bytes() for p in args["evidence_directory"].iterdir()}
    with pytest.raises((ValueError, OSError)): report.run(**args)
    assert {p.name: p.read_bytes() for p in args["evidence_directory"].iterdir()} == before
    if kind == "existing": assert target.read_bytes() == b"USER_DATA"


def test_resealed_changed_report_is_not_an_exact_replay(case):
    args = arguments(case); receipt = report.run(**args); raw = args["output_path"].read_bytes()
    args["output_path"].write_bytes(raw.replace(b"60/60", b"59/60"))
    with pytest.raises(ValueError): report.run(**replay(args, receipt))
    receipt["report_sha256"] = cli.sha(args["output_path"].read_bytes())
    with pytest.raises(ValueError): report.run(**replay(args, receipt))


def test_post_create_failure_reports_unknown_without_deleting_user_or_partial_bytes(case, monkeypatch, capsys):
    args = arguments(case)
    original = os.write
    def broken(fd, value):
        original(fd, value[:20]); raise OSError("PRIVATE_DIAGNOSTIC")
    monkeypatch.setattr(os, "write", broken)
    with pytest.raises(cli.OutputStateUnknown): report.run(**args)
    assert args["output_path"].read_bytes() and stat.S_IMODE(args["output_path"].stat().st_mode) == 0o600
    assert "PRIVATE_DIAGNOSTIC" not in str(capsys.readouterr())


def test_actual_cli_build_and_verify_print_only_private_safe_receipts(case):
    args = arguments(case)
    def call(values):
        command = [sys.executable, str(Path(report.__file__)), values["mode"]]
        for key, value in values.items():
            if key == "mode" or value is None: continue
            command += ["--" + key.removeprefix("expected_").removesuffix("_path").replace("_", "-"), str(value)]
        return subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    built = call(args); assert built.returncode == 0, built.stderr
    receipt = json.loads(built.stdout)
    verified = call(replay(args, receipt)); assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["report_replay_verified"]
    assert "SYNTHETIC" not in built.stdout + built.stderr + verified.stdout + verified.stderr


def test_cli_arguments_and_unknown_output_use_static_private_errors(monkeypatch, capsys):
    assert report.main(["PRIVATE_DO_NOT_ECHO"]) == 2
    assert "PRIVATE_DO_NOT_ECHO" not in str(capsys.readouterr())
    def failed(**_): raise cli.OutputStateUnknown("PRIVATE_DO_NOT_ECHO")
    monkeypatch.setattr(report, "run", failed)
    options = ["build"]
    for name in ("selection", "reviews", "protocol", "evidence-directory", "selection-file-sha256", "selection-sha256", "reviews-file-sha256",
                 "review-log-sha256", "protocol-sha256", "bundle", "bundle-sha256", "conclusion", "conclusion-sha256"):
        options += ["--" + name, "PRIVATE_DO_NOT_ECHO"]
    assert report.main(options) == 2
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err)["output_written"] is None and "PRIVATE_DO_NOT_ECHO" not in output.err
