"""Complete synthetic documentary preflight, not genuine reviewers or evidence."""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from services import ml_pilot_accounting as accounting
from services import ml_pilot_documents as codec
from services import ml_pilot_review_documents as documents
from services import ml_pilot_review_worker as worker

from scripts.tests.test_ml_pilot_documents import inputs


def envelope(args=None):
    args = args or inputs()
    return {
        "version": worker.VERSION,
        "parameters": {
            "participant_id": str(uuid4()),
            "participant_sha256": "a" * 64,
            "registration_sha256": "b" * 64,
        },
        **{name: value for name, value in args.items() if name.endswith("sha256")},
        **{
            name + "_base64": base64.b64encode(args[name + "_raw"]).decode()
            for name in ("selection", "reviews", "protocol", "conclusion")
        },
    }


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def revised(args, rows):
    conclusion = codec.json_value(args["conclusion_raw"])
    conclusion["review_log_sha256"] = accounting.review_hash(rows)
    args.update(
        reviews_raw=b"\n".join(accounting.canonical(r) for r in rows),
        conclusion_raw=accounting.canonical(conclusion),
        review_log_sha256=conclusion["review_log_sha256"],
    )
    for name in ("reviews", "conclusion"):
        args[name + "_file_sha256"] = documents.sha(args[name + "_raw"])


def test_complete_projection_keeps_every_review_and_only_opaque_attribution():
    args = inputs()
    value = documents.checked(documents.project(**args))
    assert value["selected_candidates"] == 60 and value["review_record_count"] == 62
    assert value["recommendation"] == "narrow"
    assert sorted(
        r["review_record_count"] for r in value["reviewer_contributions"]
    ) == [0, 2, 60]
    assert sum(r["review_record_count"] for r in value["reviewer_contributions"]) == 62
    for private in (
        "synthetic-human",
        "synthetic-paper",
        "synthetic-unopened-bundle",
        "Synthetic test rationale",
        "positive_tc",
    ):
        assert private not in json.dumps(value)
    assert value["input_pins"]["reviews_file_sha256"] != value["review_log_sha256"]


def test_superseded_failed_review_remains_in_own_attribution_digest():
    args = inputs()
    rows = codec.review_records(args["reviews_raw"])
    previous = rows[3]
    amendment = deepcopy(previous)
    amendment.update(
        review_id="SYNTHETIC-revised",
        revision=2,
        supersedes_review_id=previous["review_id"],
        outcome="inaccessible",
        results=[],
    )
    rows.append(amendment)
    revised(args, rows)
    value = documents.project(**args)
    own = next(
        r for r in value["reviewer_contributions"] if r["review_record_count"] == 61
    )
    assert own["review_records_sha256"] == accounting.review_hash(
        [r for r in rows if r["role"] == "primary"]
    )
    assert own["review_records_sha256"] != accounting.review_hash(
        [r for r in rows if r["role"] == "primary" and r is not previous]
    )


def test_all_failures_allow_honest_stop_without_creating_negative_tc_labels():
    args = inputs()
    rows = codec.review_records(args["reviews_raw"])
    for row in rows:
        row.update(outcome="inaccessible", results=[])
    revised(args, rows)
    conclusion = codec.json_value(args["conclusion_raw"])
    conclusion["recommendation"] = "stop"
    args["conclusion_raw"] = accounting.canonical(conclusion)
    args["conclusion_file_sha256"] = documents.sha(args["conclusion_raw"])
    value = documents.checked(documents.project(**args))
    assert value["selected_candidates"] == 60 and value["recommendation"] == "stop"
    assert "tc" not in value and value["review_record_count"] == 62


@pytest.mark.parametrize("name", ["selection", "reviews", "protocol", "conclusion"])
def test_each_original_file_pin_is_mandatory_and_exact(name):
    args = inputs()
    args[name + "_raw"] += b" "
    with pytest.raises(ValueError):
        documents.project(**args)
    args[name + "_file_sha256"] = None
    with pytest.raises(ValueError):
        documents.project(**args)


@pytest.mark.parametrize(
    "kind",
    [
        "missing_conclusion",
        "missing_primary",
        "missing_secondary",
        "false_agreement",
        "foreign_alias",
        "unknown_candidate",
        "incomplete_actions",
    ],
)
def test_incomplete_or_inconsistent_scientific_documentary_packet_is_not_signoff_ready(
    kind,
):
    args = inputs()
    rows = codec.review_records(args["reviews_raw"])
    if kind == "missing_conclusion":
        args.update(conclusion_raw=None, conclusion_file_sha256=None)
    elif kind == "incomplete_actions":
        conclusion = codec.json_value(args["conclusion_raw"])
        conclusion["field_actions"].pop()
        args["conclusion_raw"] = accounting.canonical(conclusion)
        args["conclusion_file_sha256"] = documents.sha(args["conclusion_raw"])
    else:
        if kind == "missing_primary":
            rows.pop(3)
        if kind == "missing_secondary":
            rows.pop()
        if kind == "false_agreement":
            rows[-1]["results"][0]["tc"]["value"] = 19
        if kind == "foreign_alias":
            rows[3]["reviewer_id"] = "undeclared"
        if kind == "unknown_candidate":
            rows[3]["candidate_id"] = "undeclared"
        revised(args, rows)
    with pytest.raises(ValueError):
        documents.project(**args)


@pytest.mark.parametrize(
    "kind",
    [
        "extra",
        "count",
        "bool",
        "missing_pin",
        "unknown_role",
        "reordered",
        "duplicate_alias",
        "missing_alias",
        "conclusion_time",
        "review_time",
        "unsorted_times",
        "omitted_times",
        "empty_digest",
        "author",
    ],
)
def test_internal_projection_refuses_malformed_or_inconsistent_child_output(kind):
    value = documents.project(**inputs())
    first = next(r for r in value["reviewer_contributions"] if r["review_record_count"])
    if kind == "extra":
        value["scientific_acceptance"] = True
    if kind == "count":
        value["review_record_count"] += 1
    if kind == "bool":
        value["selected_candidates"] = True
    if kind == "missing_pin":
        del value["input_pins"]["reviews_file_sha256"]
    if kind == "unknown_role":
        first["roles"] = ["admin"]
    if kind == "reordered":
        value["reviewer_contributions"].reverse()
    if kind == "duplicate_alias":
        value["reviewer_contributions"][1] = value["reviewer_contributions"][0]
    if kind == "missing_alias":
        value["reviewer_contributions"].pop()
    if kind == "conclusion_time":
        value["conclusion_completed_at"] = "2026-09-01T00:00:00.000000+00:00"
    if kind == "review_time":
        first["declared_completion_instants"] = ["2026-09-03T08:00:00+08:00"]
    if kind == "unsorted_times":
        first["declared_completion_instants"] *= 2
    if kind == "omitted_times":
        first["declared_completion_instants"] = []
    if kind == "empty_digest":
        next(
            r for r in value["reviewer_contributions"] if not r["review_record_count"]
        )["review_records_sha256"] = "c" * 64
    if kind == "author":
        value["conclusion_author_alias_sha256"] = "c" * 64
    with pytest.raises((ValueError, TypeError)):
        documents.checked(value)


def test_normalized_timezones_preserve_microseconds_and_original_file_pins():
    args = inputs()
    rows = codec.review_records(args["reviews_raw"])
    rows[3]["completed_at"] = "2026-09-03T08:00:00.000001+08:00"
    revised(args, rows)
    value = documents.checked(documents.project(**args))
    assert any(
        "2026-09-03T00:00:00.000001+00:00" in r["declared_completion_instants"]
        for r in value["reviewer_contributions"]
    )
    assert value["input_pins"]["reviews_file_sha256"] == documents.sha(
        args["reviews_raw"]
    )


@pytest.mark.parametrize(
    "kind",
    [
        "extra",
        "key",
        "version",
        "base64",
        "pin",
        "duplicate",
        "invalid_utf8",
        "too_many_nodes",
    ],
)
def test_upload_is_closed_bounded_and_cannot_supply_its_own_projection(kind):
    value = envelope()
    if kind == "extra":
        value["document_check"] = documents.project(**inputs())
    if kind == "key":
        value["parameters"]["request_key"] = "not-a-write"
    if kind == "version":
        value["version"] = "future"
    if kind == "base64":
        value["reviews_base64"] += " "
    if kind == "pin":
        value["conclusion_file_sha256"] = "c" * 64
    raw = encoded(value)
    if kind == "duplicate":
        raw = raw.replace(b"{", b'{"version":"duplicate",', 1)
    if kind == "invalid_utf8":
        raw = b"\xff"
    if kind == "too_many_nodes":
        raw = b"[" + b"0," * 400001 + b"0]"
    with pytest.raises((ValueError, UnicodeError)):
        worker.prepare(raw)


def test_actual_owned_child_matches_local_complete_projection():
    raw = encoded(envelope())
    result = asyncio.run(worker.check_in_worker(raw))
    assert result == worker.prepare(raw)
    assert result["input_sha256"] == documents.sha(raw)
    assert result["document_check"]["review_record_count"] == 62
    assert set(result) == {
        "version",
        "parameters",
        "input_sha256",
        "document_check",
        "implementation",
    }


def test_actual_four_eight_mib_documents_are_not_silently_truncated():
    args = inputs()
    for name in ("selection", "reviews", "protocol", "conclusion"):
        # Opaque protocol must be pinned in the selection before padding it.
        args[name + "_raw"] = args[name + "_raw"].ljust(codec.MAX_BYTES, b" ")
    selected = codec.json_value(args["selection_raw"])
    selected["protocol_sha256"] = documents.sha(args["protocol_raw"])
    selected["selection_sha256"] = accounting.selection_hash(selected)
    args["selection_raw"] = accounting.canonical(selected).ljust(codec.MAX_BYTES, b" ")
    args["selection_sha256"] = selected["selection_sha256"]
    rows = codec.review_records(args["reviews_raw"])
    for row in rows:
        row["selection_sha256"] = selected["selection_sha256"]
    conclusion = codec.json_value(args["conclusion_raw"])
    conclusion["selection_sha256"] = selected["selection_sha256"]
    args["conclusion_raw"] = accounting.canonical(conclusion)
    revised(args, rows)
    for name in ("selection", "reviews", "protocol", "conclusion"):
        args[name + "_raw"] = args[name + "_raw"].ljust(codec.MAX_BYTES, b" ")
        args[name + "_file_sha256"] = documents.sha(args[name + "_raw"])
    raw = encoded(envelope(args))
    assert 4 * codec.MAX_BYTES < len(raw) <= documents.MAX_ENVELOPE_BYTES
    result = asyncio.run(worker.check_in_worker(raw))
    assert result["document_check"]["input_pins"] == {
        name + "_file_sha256": args[name + "_file_sha256"]
        for name in ("selection", "reviews", "protocol", "conclusion")
    }


@pytest.mark.parametrize(
    "mode", ["cancel", "cancel_during_spawn", "timeout", "output_limit"]
)
def test_real_owned_review_child_is_reaped_on_interruption_or_output_overflow(
    monkeypatch, mode
):
    create = asyncio.create_subprocess_exec
    processes = []

    async def scenario():
        spawned, release = asyncio.Event(), asyncio.Event()

        async def adversarial(*args, **kwargs):
            program = (
                f"import sys;sys.stdin.buffer.read();sys.stdout.buffer.write(b'x'*{worker.MAX_OUTPUT_BYTES + 1});sys.stdout.flush()"
                if mode == "output_limit"
                else "import time;time.sleep(30)"
            )
            assert kwargs["env"] == {"LANG": "C.UTF-8", "PYTHONHASHSEED": "0"}
            process = await create(*args[:-1], program, **kwargs)
            processes.append(process)
            spawned.set()
            if mode == "cancel_during_spawn":
                await release.wait()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", adversarial)
        if mode == "timeout":
            monkeypatch.setattr(worker, "WALL_SECONDS", 0.1)
        task = asyncio.create_task(worker.check_in_worker(b"{}"))
        await asyncio.wait_for(spawned.wait(), 5)
        if mode.startswith("cancel"):
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises((TimeoutError, ExceptionGroup)):
                await asyncio.wait_for(task, 5)
        assert len(processes) == 1 and processes[0].returncode is not None

    asyncio.run(scenario())


def test_installed_review_probe_refuses_development_interpreter_and_repository_fallback():
    root = Path(__file__).resolve().parents[2]
    probe = str(root / "scripts/probe_ml_pilot_review_install.py")
    ordinary = subprocess.run(
        [sys.executable, probe], capture_output=True, check=False, timeout=15
    )
    assert ordinary.returncode != 0 and b"requires_isolated_python" in ordinary.stderr
    isolated = subprocess.run(
        [sys.executable, "-I", probe], capture_output=True, check=False, timeout=15
    )
    assert (
        isolated.returncode != 0 and b"repository_fallback_forbidden" in isolated.stderr
    )
    workflow = (root / ".github/workflows/test.yml").read_text()
    assert (
        '"$RUNNER_TEMP/sclib-ml08-installed/bin/python" -I ../scripts/probe_ml_pilot_review_install.py'
        in workflow
    )
