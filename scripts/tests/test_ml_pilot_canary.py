"""Native offline canary/IO tests; synthetic events and reviewer declarations only."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "ml_pilot_canary_cli", Path(__file__).resolve().parents[1] / "ml_pilot_canary.py"
)
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)
from scripts.tests.test_pilot_review import complete_fixture, review


def put(path, value):
    raw = (
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode()
        + b"\n"
    )
    path.write_bytes(raw)
    return cli.sha(raw)


@pytest.fixture
def case(tmp_path):
    root = tmp_path.resolve()
    contexts, output = root / "contexts", root / "output"
    contexts.mkdir()
    output.mkdir()
    selection, reviews, conclusion = complete_fixture()
    protocol = b"SYNTHETIC TEST PROTOCOL; not a human approval.\n"
    context = b"SYNTHETIC TEST CONTEXT; not scientific evidence.\n"
    (root / "protocol.md").write_bytes(protocol)
    pin = cli.sha(context)
    (contexts / (pin + ".bin")).write_bytes(context)
    selection["protocol_sha256"] = cli.sha(protocol)
    selection["selection_sha256"] = cli.pilot.selection_hash(selection)
    for row in reviews:
        row["selection_sha256"] = selection["selection_sha256"]
        for result in row["results"]:
            result["source"]["context_sha256"] = pin
    args = {
        "mode": "build",
        "selection_path": root / "selection.json",
        "reviews_path": root / "reviews.jsonl",
        "protocol_path": root / "protocol.md",
        "expected_protocol_sha256": cli.sha(protocol),
        "evidence_directory": contexts,
        "output_path": output / "canary.json",
    }
    rewrite(args, selection, reviews)
    return args, selection, reviews, conclusion


def rewrite(args, selection, reviews):
    selection["selection_sha256"] = cli.pilot.selection_hash(selection)
    for row in reviews:
        row["selection_sha256"] = selection["selection_sha256"]
    args["expected_selection_file_sha256"] = put(args["selection_path"], selection)
    raw = (
        b"\n"
        + b"\n".join(json.dumps(row, ensure_ascii=False).encode() for row in reviews)
        + b"\n\n"
    )
    args["reviews_path"].write_bytes(raw)
    args["expected_reviews_file_sha256"] = cli.sha(raw)
    args["expected_selection_sha256"] = selection["selection_sha256"]
    args["expected_review_log_sha256"] = cli.pilot.review_hash(reviews)


def verification(case, report):
    args, selection, reviews, conclusion = case
    conclusion = copy.deepcopy(conclusion)
    conclusion.update(
        selection_sha256=selection["selection_sha256"],
        review_log_sha256=cli.pilot.review_hash(reviews),
        canary_bundle_sha256=report["canary_sha256"],
    )
    path = args["selection_path"].parent / "conclusion.json"
    return {
        **args,
        "mode": "verify",
        "output_path": None,
        "bundle_path": args["output_path"],
        "expected_bundle_sha256": report["canary_sha256"],
        "conclusion_path": path,
        "expected_conclusion_sha256": put(path, conclusion),
    }


def test_native_compile_and_exact_replay_bind_full_ledger_and_bytes_without_authority(
    case, monkeypatch
):
    args, selection, reviews, _ = case
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *_a, **_k: pytest.fail("No network or database connection allowed"),
    )
    before = {
        key: args[key].read_bytes()
        for key in ("selection_path", "reviews_path", "protocol_path")
    }
    report = cli.run(**args)
    raw = args["output_path"].read_bytes()
    bundle = json.loads(raw)
    assert report["canary_sha256"] == cli.sha(raw)
    assert (
        bundle["selection"] == selection
        and bundle["reviews_including_superseded"] == reviews
    )
    assert (
        len(bundle["event_accounting"]) == 60
        and len(bundle["reviews_including_superseded"]) == 62
    )
    assert bundle["accounting"]["counts"]["selected_candidates"] == 60
    assert bundle["accounting"]["counts"]["independent_work_count"] is None
    assert (
        report["context_file_count"] == 1 and bundle["context_bytes_embedded"] is False
    )
    assert (
        bundle["accounting_component"]
        == "services.ml_pilot_accounting_documentary_only"
    )
    assert (
        bundle["context_integrity_scope"]
        == "enclosing_canary_hashes_explicit_supplied_bytes_not_content_support_or_permission"
    )
    assert b"SYNTHETIC TEST CONTEXT" not in raw
    assert all(value is False for value in bundle["authority"].values())
    assert (
        bundle["training_execution"] == "disabled"
        and not bundle["accounting"]["scientific_acceptance"]
    )
    assert cli.canonical(bundle) == raw
    assert (
        stat.S_IMODE(args["output_path"].stat().st_mode) == 0o600
        and args["output_path"].stat().st_nlink == 1
    )
    verified = cli.run(**verification(case, report))
    assert (
        verified["canary_replay_verified"]
        and verified["conclusion_documentary_gate_verified"]
    )
    assert not verified["output_written"] and all(
        value is False for value in verified["authority"].values()
    )
    assert {key: args[key].read_bytes() for key in before} == before
    assert not any(
        key in report
        for key in (
            "selection",
            "reviews",
            "event_accounting",
            "accounting",
            "path",
            "pilot_id",
        )
    )


@pytest.mark.parametrize(
    "reason",
    [
        "missing_primary",
        "missing_secondary",
        "false_agreement",
        "stale_secondary",
        "unresolved_without_arbitration",
        "replaced_candidate",
    ],
)
def test_incomplete_or_unanchored_review_never_emits_a_canary(case, reason):
    args, selection, reviews, _ = case
    original = args["expected_selection_sha256"]
    if reason == "missing_primary":
        reviews.pop(30)
    if reason == "missing_secondary":
        reviews.pop()
    if reason == "false_agreement":
        reviews[60]["results"][0]["tc"]["value"] = 9
    if reason == "stale_secondary":
        new = copy.deepcopy(reviews[0])
        new.update(
            review_id="synthetic-new",
            revision=2,
            supersedes_review_id=reviews[0]["review_id"],
        )
        reviews.append(new)
    if reason == "unresolved_without_arbitration":
        reviews[60].update(
            comparison="disagreement", disagreement_codes=["synthetic-conflict"]
        )
    if reason == "replaced_candidate":
        selection["candidates"][0]["source_reference"] = "changed-source"
    rewrite(args, selection, reviews)
    if reason == "replaced_candidate":
        args["expected_selection_sha256"] = original
    with pytest.raises(ValueError):
        cli.run(**args)
    assert not args["output_path"].exists()


@pytest.mark.parametrize(
    "pin",
    [
        "expected_selection_file_sha256",
        "expected_reviews_file_sha256",
        "expected_protocol_sha256",
        "expected_selection_sha256",
        "expected_review_log_sha256",
    ],
)
def test_independent_raw_and_logical_pins_fail_before_evidence_access(
    case, monkeypatch, pin
):
    args, *_ = case
    args[pin] = "e" * 64
    monkeypatch.setattr(
        cli,
        "capture_evidence",
        lambda *_: pytest.fail("Do not open context on mismatched input anchors"),
    )
    with pytest.raises(ValueError):
        cli.run(**args)
    assert not args["output_path"].exists()


def test_all_failed_events_stay_in_denominator_and_stop_is_a_valid_documentary_conclusion(
    case,
):
    args, selection, reviews, conclusion = case
    for row in reviews:
        row.update(outcome="inaccessible", results=[])
    for path in args["evidence_directory"].iterdir():
        path.unlink()
    rewrite(args, selection, reviews)
    conclusion["recommendation"] = "stop"
    report = cli.run(**args)
    bundle = json.loads(args["output_path"].read_bytes())
    assert len(bundle["event_accounting"]) == 60 and all(
        not e["result_ids"] for e in bundle["event_accounting"]
    )
    assert bundle["accounting"]["event_outcomes"] == {"inaccessible": 60}
    assert bundle["accounting"]["atomic_field_missingness"]["denominator"] == 0
    assert report["context_file_count"] == 0
    assert cli.run(**verification(case, report))["canary_replay_verified"]


def test_superseded_results_and_new_context_bytes_are_both_preserved(case):
    args, selection, reviews, _ = case
    original = copy.deepcopy(reviews[2])
    newer = copy.deepcopy(original)
    raw = b"SYNTHETIC revised context, not scientific approval"
    pin = cli.sha(raw)
    (args["evidence_directory"] / (pin + ".bin")).write_bytes(raw)
    newer.update(
        review_id="synthetic-new",
        revision=2,
        supersedes_review_id=original["review_id"],
    )
    newer["results"][0]["source"].update(
        revision="synthetic-revision-2", context_sha256=pin
    )
    newer["results"][0]["tc"]["value"] = 0.05
    reviews.append(newer)
    rewrite(args, selection, reviews)
    report = cli.run(**args)
    bundle = json.loads(args["output_path"].read_bytes())
    assert bundle["reviews_including_superseded"][2] == original
    assert bundle["event_accounting"][2]["effective_review_id"] == "synthetic-new"
    assert report["context_file_count"] == 2
    assert bundle["accounting"]["curation_time"]["review_record_denominator"] == 63


@pytest.mark.parametrize(
    "name",
    [
        "missing",
        "extra",
        "changed",
        "symlink",
        "hardlink",
        "fifo",
        "directory",
        "oversized",
        "root_symlink",
    ],
)
def test_evidence_inventory_refuses_missing_changed_or_unsafe_leaves(case, name):
    args, *_ = case
    root = args["evidence_directory"]
    file = next(root.iterdir())
    if name in {"missing", "symlink", "fifo", "directory", "oversized"}:
        file.unlink()
    if name == "extra":
        (root / "UNAUTHORIZED.txt").write_text("PRIVATE_CANARY")
    if name == "changed":
        file.write_bytes(b"changed")
    if name == "symlink":
        file.symlink_to(args["protocol_path"])
    if name == "hardlink":
        os.link(file, root.parent / "alias.bin")
    if name == "fifo":
        os.mkfifo(file)
    if name == "directory":
        file.mkdir()
    if name == "oversized":
        with file.open("wb") as handle:
            handle.truncate(cli.MAX_CONTEXT_BYTES + 1)
    if name == "root_symlink":
        alias = root.parent / "context-alias"
        alias.symlink_to(root, target_is_directory=True)
        args["evidence_directory"] = alias
    with pytest.raises((ValueError, OSError)):
        cli.run(**args)
    assert not args["output_path"].exists()


@pytest.mark.parametrize(
    "kind",
    ["context", "selection", "reviews", "protocol", "implementation", "in_memory"],
)
def test_rereads_inputs_and_code_after_compile_before_any_output(
    case, monkeypatch, kind
):
    args, *_ = case
    original = cli.compile_canary

    def changed(*values, **kwargs):
        value = original(*values, **kwargs)
        if kind == "context":
            next(args["evidence_directory"].iterdir()).write_bytes(b"changed")
        elif kind in {"selection", "reviews", "protocol"}:
            args[kind + "_path"].write_bytes(b"changed")
        elif kind == "in_memory":
            values[0]["pilot_id"] = "MUTATED"
        elif kind == "implementation":
            monkeypatch.setattr(cli, "implementation", dict)
        return value

    monkeypatch.setattr(cli, "compile_canary", changed)
    with pytest.raises(ValueError):
        cli.run(**args)
    assert not args["output_path"].exists()


@pytest.mark.parametrize(
    "kind",
    [
        "conclusion_pin",
        "wrong_canary",
        "old_log",
        "missing_fields",
        "forged_bundle",
        "old_code",
    ],
)
def test_verification_rebuilds_contents_and_binds_final_conclusion(case, kind):
    args, *_ = case
    report = cli.run(**args)
    verification_args = verification(case, report)
    if kind == "conclusion_pin":
        verification_args["expected_conclusion_sha256"] = "e" * 64
    elif kind in {"wrong_canary", "old_log", "missing_fields"}:
        conclusion = json.loads(verification_args["conclusion_path"].read_bytes())
        if kind == "wrong_canary":
            conclusion["canary_bundle_sha256"] = "e" * 64
        if kind == "old_log":
            conclusion["review_log_sha256"] = "e" * 64
        if kind == "missing_fields":
            conclusion["field_actions"].pop()
        verification_args["expected_conclusion_sha256"] = put(
            verification_args["conclusion_path"], conclusion
        )
    else:
        bundle = json.loads(args["output_path"].read_bytes())
        if kind == "forged_bundle":
            bundle["event_accounting"].pop()
        if kind == "old_code":
            bundle["implementation"]["files"]["ml_pilot_canary.py"] = "e" * 64
        raw = cli.canonical(bundle)
        args["output_path"].write_bytes(raw)
        verification_args["expected_bundle_sha256"] = cli.sha(raw)
    before = args["output_path"].read_bytes()
    with pytest.raises(ValueError):
        cli.run(**verification_args)
    assert args["output_path"].read_bytes() == before


def test_never_overwrites_a_file_or_writes_inside_closed_evidence_inventory(case):
    args, *_ = case
    args["output_path"].write_text("USER_FILE")
    with pytest.raises(FileExistsError):
        cli.run(**args)
    assert args["output_path"].read_text() == "USER_FILE"
    with pytest.raises(ValueError):
        cli.run(**{**args, "output_path": args["evidence_directory"] / "canary.json"})
    assert not (args["evidence_directory"] / "canary.json").exists()


def cli_args(args):
    result = [args["mode"]]
    for name, value in args.items():
        if name == "mode" or value is None:
            continue
        flag = name.removeprefix("expected_").removesuffix("_path").replace("_", "-")
        result.extend(["--" + flag, str(value)])
    return result


def test_real_cli_build_verify_and_no_sensitive_stdout(case):
    args, *_ = case
    command = [sys.executable, str(Path(cli.__file__))]
    completed = subprocess.run(
        [*command, *cli_args(args)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    verify = subprocess.run(
        [*command, *cli_args(verification(case, report))],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert verify.returncode == 0, verify.stderr
    assert json.loads(verify.stdout)["canary_replay_verified"]
    for token in (
        "SYNTHETIC-event",
        "synthetic-human",
        "synthetic-paper",
        str(args["selection_path"]),
        "0.03",
    ):
        assert (
            token
            not in completed.stdout + completed.stderr + verify.stdout + verify.stderr
        )


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":1e999}',
        b'{"x":"\\ud800"}',
        b"[" * 100 + b"]" * 100,
    ],
)
def test_untrusted_json_rejected_without_echoing_private_input(case, raw):
    args, *_ = case
    args["selection_path"].write_bytes(raw)
    args["expected_selection_file_sha256"] = cli.sha(raw)
    with pytest.raises((ValueError, UnicodeError)):
        cli.run(**args)
    assert not args["output_path"].exists()


def test_cli_errors_and_uncertain_output_never_echo_arguments_or_claim_rollback(
    case, monkeypatch, capsys
):
    args, *_ = case
    assert cli.main(["--PRIVATE_CANARY"]) == 2
    assert "PRIVATE_CANARY" not in capsys.readouterr().err

    def unknown(*_a, **_k):
        raise cli.OutputStateUnknown()

    monkeypatch.setattr(cli, "write_new_package", unknown)
    assert cli.main(cli_args(args)) == 2
    report = json.loads(capsys.readouterr().err)
    assert (
        report["output_written"] is None and report["status"] == "output_state_unknown"
    )


def test_unresolved_arbitration_retains_pending_results_and_complete_accounting(case):
    args, selection, reviews, _ = case
    reviews[60].update(
        comparison="disagreement", disagreement_codes=["synthetic-state-conflict"]
    )
    reviews[60]["results"][0]["decision"] = "pending"
    arb = review(selection, role="arbitration")
    arb.update(
        comparison="unresolved",
        disagreement_codes=["synthetic-state-conflict"],
        compares_review_ids=[reviews[0]["review_id"], reviews[60]["review_id"]],
    )
    arb["results"] = copy.deepcopy(reviews[60]["results"])
    reviews.append(arb)
    rewrite(args, selection, reviews)
    report = cli.run(**args)
    bundle = json.loads(args["output_path"].read_bytes())
    assert bundle["event_accounting"][0]["effective_review_id"] == arb["review_id"]
    assert bundle["accounting"]["atomic_result_decisions"]["pending"] == 1
    assert bundle["accounting"]["agreement_counts"]["unresolved"] == 1
    assert cli.run(**verification(case, report))["canary_replay_verified"]


@pytest.mark.parametrize("kind", ["bounded_tc", "not_detected", "repeated_result"])
def test_no_label_coercion_or_false_independence_in_canary(case, kind):
    args, selection, reviews, _ = case
    item = reviews[2]["results"][0]
    if kind == "bounded_tc":
        item["tc"].update(relation="lt", value=None, upper=0.03)
    if kind == "not_detected":
        item.update(observation="not_detected", tc=None, tested_temperature_min_k=0.03)
        item["fields"]["tc_value"] = "not_applicable"
        item["missingness_reasons"]["tc_value"] = "Not Tc=0"
    if kind == "repeated_result":
        reviews[3]["results"] = copy.deepcopy(reviews[2]["results"])
    rewrite(args, selection, reviews)
    cli.run(**args)
    bundle = json.loads(args["output_path"].read_bytes())
    assert bundle["reviews_including_superseded"][2]["results"][0] == item
    assert bundle["accounting"]["counts"]["selected_candidates"] == 60
    assert bundle["accounting"]["counts"]["independent_work_count"] is None
    assert bundle["accounting"]["counts"]["atomic_results_in_effective_reviews"] == (
        59 if kind == "repeated_result" else 60
    )


@pytest.mark.parametrize(
    "kind",
    [
        "selection_symlink",
        "protocol_fifo",
        "reviews_hardlink",
        "output_symlink",
        "output_parent_symlink",
        "traversal",
        "byte_cap",
    ],
)
def test_explicit_input_output_paths_remain_bounded_and_unaliased(
    case, monkeypatch, kind
):
    args, *_ = case
    if kind == "selection_symlink":
        path = args["selection_path"]
        original = path.with_suffix(".original")
        path.rename(original)
        path.symlink_to(original)
    if kind == "protocol_fifo":
        args["protocol_path"].unlink()
        os.mkfifo(args["protocol_path"])
    if kind == "reviews_hardlink":
        os.link(args["reviews_path"], args["reviews_path"].with_suffix(".alias"))
    if kind == "output_symlink":
        args["output_path"].symlink_to(args["protocol_path"])
    if kind == "output_parent_symlink":
        original = args["output_path"].parent
        alias = original.with_name("output-alias")
        alias.symlink_to(original, target_is_directory=True)
        args["output_path"] = alias / "canary.json"
    if kind == "traversal":
        args["selection_path"] = (
            args["selection_path"].parent
            / ".."
            / args["selection_path"].parent.name
            / "selection.json"
        )
    if kind == "byte_cap":
        monkeypatch.setattr(cli, "MAX_EVIDENCE_BYTES", 1)
    with pytest.raises((ValueError, OSError)):
        cli.run(**args)


def test_source_references_are_not_network_or_filesystem_read_instructions(
    case, monkeypatch
):
    args, selection, reviews, _ = case
    selection["candidates"][2]["source_reference"] = (
        "https://private.invalid/DO_NOT_FETCH"
    )
    reviews[2]["results"][0]["source"]["context_reference"] = "/PRIVATE_DO_NOT_OPEN"
    rewrite(args, selection, reviews)
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *_a, **_k: pytest.fail(
            "Source reference must never cause network access"
        ),
    )
    assert cli.run(**args)["context_file_count"] == 1


def test_read_only_verification_needs_no_synthetic_hash_resealing_and_preserves_raw_file_hashes(
    case,
):
    args, *_ = case
    report = cli.run(**args)
    verification_args = verification(case, report)
    raw = args["selection_path"].read_bytes()
    args["selection_path"].write_bytes(raw + b"\n")
    with pytest.raises(ValueError):
        cli.run(**verification_args)
    verification_args["expected_selection_file_sha256"] = cli.sha(raw + b"\n")
    # Even a re-pinned formatting-only input change needs a newly built canary:
    # its original raw-file pin is distinct from its unchanged logical anchor.
    with pytest.raises(ValueError, match="replay_mismatch"):
        cli.run(**verification_args)


def test_empty_asserted_approved_protocol_is_not_a_documentary_artifact(case):
    args, selection, reviews, _ = case
    args["protocol_path"].write_bytes(b"")
    args["expected_protocol_sha256"] = selection["protocol_sha256"] = cli.sha(b"")
    rewrite(args, selection, reviews)
    with pytest.raises(ValueError):
        cli.run(**args)
    assert not args["output_path"].exists()
