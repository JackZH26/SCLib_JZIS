"""Capture a rich synthetic canary for browser presentation, not account admission."""

from __future__ import annotations

import base64
import copy
import io
import json
from pathlib import Path

from services import ml_pilot_accounting as accounting
from services import ml_pilot_canary as canary
from services import ml_pilot_evidence_worker as worker

from scripts.tests.test_ml_pilot_evidence_worker import assemble, frame
from scripts.tests.test_pilot_review import complete_fixture, review


def rich_fixture():
    selected, rows, conclusion = complete_fixture()
    protocol = (
        b"SYNTHETIC browser quality fixture protocol; no real scientific approval."
    )
    context = b"SYNTHETIC byte fixture only; no scientific content or source licence."
    selected["protocol_sha256"] = canary.sha(protocol)
    selected["strata"] = [
        {"id": key, "definition": "SYNTHETIC descriptive group"}
        for key in ("test-a", "test-b")
    ]
    for i, candidate in enumerate(selected["candidates"]):
        candidate.update(
            family="synthetic-family-a" if i < 20 else "synthetic-family-b",
            source_class="synthetic-text" if i % 2 == 0 else "synthetic-table",
            stratum_id="test-a" if i % 3 == 0 else "test-b",
        )
    selected["selection_sha256"] = accounting.selection_hash(selected)
    statuses = [
        "conflicted",
        "not_reported",
        "not_accessible",
        "not_extracted",
        "ambiguous",
        "not_applicable",
        "reported",
    ]
    for i, row in enumerate(rows):
        row["selection_sha256"] = selected["selection_sha256"]
        row.update(active_minutes=None, active_minutes_by_field={})
        for result in row["results"]:
            result["source"]["context_sha256"] = canary.sha(context)
        if row["role"] == "primary":
            status = statuses[i % len(statuses)]
            result = row["results"][0]
            result["fields"]["structure_identity"] = status
            if status == "reported":
                result["structure_id"] = "synthetic-structure-" + str(i)
                result["missingness_reasons"].pop("structure_identity")
            else:
                result["missingness_reasons"]["structure_identity"] = (
                    "SYNTHETIC " + status
                )
    # Keep all outcomes in the original denominator. Add no fake atomic failures.
    for i in range(10, 60):
        rows[i].update(
            outcome=["inaccessible", "irrecoverable", "no_relevant_result"][i % 3],
            results=[],
        )
    # One atomic result is associated with two events, not two independent results.
    rows[8]["results"] = copy.deepcopy(rows[1]["results"])
    # A typed observed non-transition is retained without a zero-Tc label.
    negative = rows[4]["results"][0]
    negative.update(observation="not_detected", tc=None, tested_temperature_min_k=0.03)
    negative["fields"]["tc_value"] = "not_applicable"
    negative["missingness_reasons"]["tc_value"] = (
        "SYNTHETIC tested non-transition; not Tc zero"
    )
    # Error-bearing pending result requires a separate comparison and arbitration.
    pending = rows[3]["results"][0]
    pending.update(
        decision="pending",
        errors=[
            {"kind": kind, "field": "structure_identity", "code": "synthetic_error"}
            for kind in ("source", "normalization", "state_association", "extraction")
        ],
    )
    rows[3].update(outcome="unresolved", requires_second_review=True)
    for row in rows[60:]:
        index = int(row["candidate_id"].rsplit("-", 1)[1])
        row["results"] = copy.deepcopy(rows[index]["results"])
    # Additional conflicted structure is still explicitly compared, not removed.
    for i in (3, 7):
        second = review(selected, i, "secondary", rows[i])
        second.update(
            results=copy.deepcopy(rows[i]["results"]),
            outcome=rows[i]["outcome"],
            active_minutes=None,
            active_minutes_by_field={},
        )
        rows.append(second)
    # The pending result remains unresolved after arbitration, with its errors.
    second = next(
        row
        for row in rows
        if row["role"] == "secondary" and row["candidate_id"] == rows[3]["candidate_id"]
    )
    second.update(comparison="disagreement", disagreement_codes=["synthetic_dispute"])
    arbitration = review(selected, 3, "arbitration")
    arbitration.update(
        outcome="unresolved",
        comparison="unresolved",
        disagreement_codes=["synthetic_dispute"],
        compares_review_ids=[rows[3]["review_id"], second["review_id"]],
        results=copy.deepcopy(rows[3]["results"]),
        active_minutes=None,
        active_minutes_by_field={},
    )
    rows.append(arbitration)
    # Superseded failure effort remains part of all-revision timing.
    old = rows[20]
    old.update(active_minutes=2.5, active_minutes_by_field={"source_locator": 1.25})
    amendment = copy.deepcopy(old)
    amendment.update(
        review_id="SYNTHETIC-amended-failure",
        revision=2,
        supersedes_review_id=old["review_id"],
        active_minutes=0.0,
        active_minutes_by_field={"source_locator": 0.0, "method": 0.0},
    )
    rows.append(amendment)
    conclusion.update(
        selection_sha256=selected["selection_sha256"],
        review_log_sha256=accounting.review_hash(rows),
        rationale="SYNTHETIC <script>window.PRIVATE_CANARY=1</script> https://example.invalid/not-a-link",
        field_actions=[
            {
                "field": field,
                "action": ("keep", "narrow", "defer")[i % 3],
                "reason": 'SYNTHETIC <img src="https://example.invalid/private" onerror="bad()">'
                if i == 0
                else "SYNTHETIC field-specific limitation",
            }
            for i, field in enumerate(accounting.FIELDS)
        ],
    )
    raw = {
        "selection": accounting.canonical(selected),
        "protocol": protocol,
        "reviews": b"\n".join(accounting.canonical(row) for row in rows),
        "conclusion": accounting.canonical(conclusion),
    }
    args = {
        **{key + "_raw": value for key, value in raw.items()},
        **{key + "_file_sha256": canary.sha(value) for key, value in raw.items()},
        "selection_sha256": selected["selection_sha256"],
        "review_log_sha256": conclusion["review_log_sha256"],
    }
    return assemble(
        args,
        {
            "participant_id": "00000000-0000-4000-8000-000000000076",
            "participant_sha256": "a" * 64,
            "registration_sha256": "b" * 64,
        },
        {canary.sha(context): context},
    )


def test_capture_real_kernel_accounting_for_rich_presentation_cases(tmp_path):
    meta, originals, contexts = rich_fixture()
    value = worker.checked(worker.prepare(io.BytesIO(frame(meta, originals, contexts))))
    bundle = canary.loads(originals["canary"])
    a = bundle["accounting"]
    assert (
        a["counts"]["selected_candidates"] == 60
        and a["counts"]["atomic_results_in_effective_reviews"] == 9
    )
    assert (
        a["counts"]["event_result_associations"] == 10
        and a["counts"]["review_records_including_superseded"] == 66
    )
    assert a["curation_time"]["recorded_active_minutes_all_revisions"] == 2.5
    assert a["curation_time"]["records_with_timing"] == 2
    assert set(a["atomic_field_missingness"]["counts"]["structure_identity"]) == {
        "reported",
        "not_reported",
        "not_accessible",
        "not_extracted",
        "ambiguous",
        "conflicted",
        "not_applicable",
    }
    assert a["atomic_result_decisions"] == {"accepted": 8, "pending": 1}
    assert (
        a["curation_time_by_field"]["method"]["recorded_minutes"] == 0
        and a["curation_time_by_field"]["method"]["records_with_timing"] == 1
    )
    root = Path(__file__).resolve().parents[2]
    fixture = {
        "fixture_notice": "Real pure-kernel reconstruction of SYNTHETIC data only; no authenticated HTTP, accounts, source rights or scientific acceptance.",
        "canary_base64": base64.b64encode(originals["canary"]).decode(),
        "conclusion_base64": base64.b64encode(originals["conclusion"]).decode(),
        "document_projection": value["document_check"],
        "canary_check": value["canary_check"],
        "canary_implementation": bundle["implementation"],
        "capture_test_sha256": canary.sha(
            (root / "scripts/tests/test_ml_pilot_quality_fixture.py").read_bytes()
        ),
    }
    (tmp_path / "ml-pilot-quality-synthetic.json").write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2) + "\n"
    )
