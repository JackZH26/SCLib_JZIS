#!/usr/bin/env python3
"""Replay an ML08 canary and render a private, inert human-review report.

No network, database, authentication, scientific approval or model training.
The report includes private supplied declarations, not original context bytes.
"""
from __future__ import annotations

import html
import json
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import ml_pilot_canary as canary

VERSION = "ml08-private-review-report/1.0.0"
MAX_REPORT_BYTES = 32 * 1024 * 1024
STATUSES = ("reported", "not_reported", "not_accessible", "not_extracted", "ambiguous", "conflicted", "not_applicable")
CSS = """
:root{color-scheme:light;font:16px/1.55 system-ui,sans-serif;color:#182735;background:#f3f6f8}
*{box-sizing:border-box}body{margin:0}main{max-width:1440px;margin:auto;padding:24px}
h1,h2,h3{line-height:1.25}h1{font-size:2rem}h2{margin-top:2rem}p,li,td,th,summary{overflow-wrap:anywhere}
.notice{border-left:5px solid #835a0b;background:#fff3d5;padding:16px}.meta{color:#445665}
section{background:white;border:1px solid #d0dae1;border-radius:8px;padding:20px;margin:18px 0}
.scroll{overflow:auto;max-width:100%;margin:12px 0}table{border-collapse:collapse;width:100%;font-size:.9rem}
caption{text-align:left;font-weight:650;padding:8px 0}th,td{text-align:left;vertical-align:top;border:1px solid #d0dae1;padding:8px;min-width:128px}
th:first-child,td:first-child{min-width:180px}th:last-child,td:last-child{min-width:240px}
th{background:#eaf0f4}details{margin:12px 0;border:1px solid #d0dae1;padding:12px;border-radius:6px}
summary{cursor:pointer;font-weight:650}summary:focus-visible,.scroll:focus-visible{outline:3px solid #1967a1;outline-offset:3px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.82rem;background:#f3f6f8;padding:12px}
.small{font-size:.87rem}.badge{font-weight:650;color:#6d4200}a{color:#145e8c}
@media(max-width:600px){main{padding:12px}section{padding:12px}h1{font-size:1.55rem}}
@media print{body{background:white}main{max-width:none;padding:0}section{break-inside:auto}.scroll{overflow:visible}
 table{font-size:8pt;table-layout:fixed}th,td,th:first-child,td:first-child,th:last-child,td:last-child{min-width:0;padding:3px}h2,h3{break-after:avoid}}
"""


def text(value):
    return html.escape("Not recorded" if value is None else str(value), quote=True)


def raw(value):
    return "<pre>" + text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)) + "</pre>"


def table(title, headers, rows):
    # Every dynamic cell is escaped here, never interpolated as markup or a URL.
    return ('<div class="scroll" tabindex="0" role="region" aria-label="' + text(title) + '"><table><caption>'
        + text(title) + "</caption><thead><tr>" + "".join('<th scope="col">' + text(h) + "</th>" for h in headers)
        + "</tr></thead><tbody>" + "".join("<tr>" + "".join("<td>" + text(v) + "</td>" for v in row)
            + "</tr>" for row in rows) + "</tbody></table></div>")


def quantity(value):
    if value is None:
        return "Not recorded"
    relation = value["relation"]
    if relation == "interval":
        number = f'[{value["lower"]}, {value["upper"]}]'
    elif relation == "exact":
        number = str(value["value"])
    elif relation in {"lt", "le"}:
        number = ("< " if relation == "lt" else "≤ ") + str(value["upper"])
    else:
        number = ("> " if relation == "gt" else "≥ ") + str(value["lower"])
    return (("approximately " if value["approximate"] else "") + number + " " + value["unit"]
        + ("; uncertainty " + str(value["uncertainty"]) + " " + value["unit"] if value["uncertainty"] is not None else ""))


def timing(minutes, recorded, total):
    return (str(minutes) + " recorded min" if recorded else "Not recorded") + f"; {recorded}/{total} review records timed"


def details(title, value):
    return "<details><summary>" + text(title) + "</summary>" + raw(value) + "</details>"


def render(bundle, conclusion, *, renderer_sha256, conclusion_file_sha256):
    """Rendering seam; only run() establishes independently pinned byte replay."""
    selection, reviews = bundle["selection"], bundle["reviews_including_superseded"]
    accounting = canary.pilot.validate(selection, reviews, conclusion, bundle["selection_sha256"])
    canary.require(not accounting["errors"] and accounting["ready_for_final_human_signoff"], "pilot_report_incomplete")
    indices = canary.event_index(selection, reviews)
    canary.require(indices == bundle["event_accounting"], "pilot_report_event_index_changed")
    by_id = {row["review_id"]: row for row in reviews}
    candidates = {row["candidate_id"]: row for row in selection["candidates"]}
    counts = accounting["counts"]
    out = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="referrer" content="no-referrer">',
        '<meta name="robots" content="noindex,nofollow,noarchive">',
        ('<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; '
        'base-uri \'none\'; form-action \'none\'; object-src \'none\'">'),
        "<title>ML08 private pilot review report</title><style>" + CSS + "</style></head><body><main>",
        "<h1>ML08 private pilot review report</h1>",
        ('<p class="notice"><strong>Private documentary review — not scientific acceptance.</strong> '
        'Contains supplied review declarations and potentially sensitive locators/pseudonyms. '
        'Do not publish or redistribute without separate authorization. Source context bytes are not embedded. '
        'If text was pasted into review fields, that text remains in this private report.</p>'),
        ("<p>Canary replay checks exact local bytes and accounting, not event existence, human identity, reviewer independence, "
        "current source permissions or scientific truth. No model training or execution is authorized. "
        "Sixty candidate events assess workflow feasibility, not cross-family ML sample-size sufficiency.</p>"),
        ("<p>Record content below is untrusted supplied data, never executable instructions or automatically followed links. "
        "The report contains no scripts or external assets. Collapsed sections are already in the file; "
        "they are not redaction. Expand needed sections before printing.</p>"),
        ('<nav aria-label="Report sections"><a href="#summary">Accounting</a> · '
         '<a href="#fields">Field recovery and effort</a> · <a href="#events">All selected events</a> · '
         '<a href="#provenance">Provenance and conclusion</a></nav>'),
        '<section id="provenance"><h2>Exact provenance and recorded conclusion</h2>',
        table("Replay bindings", ["Binding", "Value"], [
            ["Report format", VERSION], ["Renderer source SHA-256", renderer_sha256],
            ["Canary SHA-256", canary.digest(bundle)], ["Conclusion file SHA-256", conclusion_file_sha256],
            ["Selection SHA-256 (logical)", bundle["selection_sha256"]],
            ["Review log SHA-256 (logical)", bundle["review_log_sha256"]],
            *[[name, value] for name, value in bundle["input_pins"].items()]]),
        "<p>Pilot: " + text(selection["pilot_id"]) + ". Recorded recommendation: <strong>"
        + text(conclusion["recommendation"]) + "</strong> — supplied by the declared reviewer, not generated or approved here.</p>",
        "<p>" + text(conclusion["rationale"]) + "</p>",
        details("Complete recorded conclusion and field actions", conclusion),
        details("Frozen selection, strata, roster and independence declarations", selection),
        details("Selected implementation observation (not full runtime attestation)", bundle["implementation"]), "</section>",
        '<section id="summary"><h2>Accounting and review outcomes</h2>',
        table("Separate units — never independent material counts", ["Unit", "Count"], [
            *[[key, value] for key, value in counts.items()],
            *[["Reported distinct " + key, value] for key, value in accounting["reported_identity_counts"].items()]]),
        table("Event outcomes — all selected events remain in the denominator", ["Outcome", "Events", "Denominator"],
            [[key, accounting["event_outcomes"].get(key, 0), counts["selected_candidates"]]
             for key in ("recovered", "inaccessible", "irrecoverable", "no_relevant_result", "unresolved")]),
        table("Distinct effective atomic results — declared review decisions", ["Decision", "Results"],
            [[key, accounting["atomic_result_decisions"].get(key, 0)] for key in ("accepted", "pending", "rejected")]),
        ("<p>Accepted means a supplied human review assertion, not automatic scientific validation. "
        "Recovery includes reported fields on pending/rejected results and is not extraction accuracy. "
        "Secondary assessments are not extra observations. Shared result IDs deduplicate atomic statistics, "
        "not candidate-event associations. Distinct work/state IDs do not establish independent support.</p>"),
        details("Comparison/arbitration counts (latest records, not independent events)", accounting["agreement_counts"]),
        details("Effective atomic-result errors, separate from missingness", accounting["error_counts_separate_from_missingness"]), "</section>",
        '<section id="fields"><h2>Field recovery, missingness and curation effort</h2>',
        ("<p>Candidate recovery is events with any reported result / all selected events. Atomic missingness uses "
        "distinct effective result IDs; inaccessible events do not acquire invented atomic rows. "
        "Timing includes every revision. Only recorded time is summed; missing time is not zero and partial totals are not total effort.</p>"),
        table("All review revisions: active curation time", ["Recorded effort"], [[timing(
            accounting["curation_time"]["recorded_active_minutes_all_revisions"],
            accounting["curation_time"]["records_with_timing"], len(reviews))]]),
        table("Priority fields: different denominators remain explicit", ["Field", "Candidate recovery", "Atomic denominator",
              *STATUSES, "Field effort across all revisions"], [
            [field, str(accounting["candidate_field_recovery"][field]["candidates_with_any_reported_result"]) + "/"
                + str(counts["selected_candidates"]), accounting["atomic_field_missingness"]["denominator"],
             *[accounting["atomic_field_missingness"]["counts"][field].get(status, 0) for status in STATUSES],
             timing(accounting["curation_time_by_field"][field]["recorded_minutes"],
                    accounting["curation_time_by_field"][field]["records_with_timing"], len(reviews))]
            for field in canary.pilot.FIELDS]), "</section>"]
    for dimension, groups in accounting["time_and_denominators_by_group"].items():
        out += ["<section><h2>Selection groups: " + text(dimension) + "</h2>",
            ("<p>Groups follow the frozen selection, not a formula-based reassignment. Group rows are descriptive, "
            "not independent samples, accuracy comparisons or evidence that a material family is ML-ready.</p>")]
        for label, group in sorted(groups.items()):
            selected = {cid for cid, candidate in candidates.items() if candidate[dimension] == label}
            group_reviews = [row for row in reviews if row["candidate_id"] in selected]
            out += ["<details><summary>" + text(label) + " — " + str(group["selected_candidates"]) + " selected events</summary>",
                details("Group outcomes and denominators", group),
                table("Field recovery and timed effort in " + label, ["Field", "Any reported / selected events", "Recorded field effort"], [
                    [field, str(group["candidates_with_any_reported_field"][field]) + "/" + str(group["selected_candidates"]),
                     timing(sum(row["active_minutes_by_field"].get(field) or 0 for row in group_reviews),
                        sum(row["active_minutes_by_field"].get(field) is not None for row in group_reviews), len(group_reviews))]
                    for field in canary.pilot.FIELDS]), "</details>"]
        out.append("</section>")
    out += ['<section id="events"><h2>Complete selected-event register</h2>',
        ("<p>Original selection order; no ranking, replacement or failure filtering. The full review history below "
        "retains secondary and superseded values, timing, missingness reasons and error details.</p>"),
        table("Every selected candidate event", ["Candidate", "Family", "Source class", "Stratum", "Outcome", "Effective review", "Result associations"],
            [[entry["candidate_id"], candidates[entry["candidate_id"]]["family"], candidates[entry["candidate_id"]]["source_class"],
              candidates[entry["candidate_id"]]["stratum_id"], entry["outcome"], entry["effective_review_id"], len(entry["result_ids"])] for entry in indices])]
    for index, entry in enumerate(indices):
        cid, effective = entry["candidate_id"], by_id[entry["effective_review_id"]]
        out += ['<details id="event-' + str(index) + '"><summary>' + text(cid) + " — " + text(entry["outcome"]) + "</summary>",
            details("Frozen source event and selection rationale", candidates[cid]), details("Effective review selection", entry),
            "<p>Effective outcome reason: " + text(effective["outcome_reason"]) + "</p>",
            table("Effective atomic-result associations", ["Result", "Declared decision", "Origin", "Observation", "Tc", "Tested minimum (K)",
                "Criterion", "Pressure state", "Pressure", "Method", "State interpretation"],
                [[row["result_id"], row["decision"], row["origin"], row["observation"],
                  "Not applicable (not detected)" if row["observation"] == "not_detected" else quantity(row["tc"]),
                  row["tested_temperature_min_k"], row["tc_criterion"], row["pressure_state"], quantity(row["pressure"]),
                  row["method"], row["state_interpretation"]] for row in effective["results"]]),
            ("<p>Not detected is an observation within a tested temperature window, never Tc = 0. "
            "Unknown pressure is never ambient. Bounds, approximation and uncertainty are retained without point substitution. "
            "Normalized units below do not replace original source expressions.</p>")]
        for row in reviews:
            if row["candidate_id"] == cid:
                label = "Effective" if row["review_id"] == effective["review_id"] else "Retained comparison/history (not an extra observation)"
                out.append(details(label + ": " + row["role"] + " / " + row["review_id"], row))
        out.append("</details>")
    out += ["</section><section><h2>Verification limits and audit details</h2>",
        details("Documentary accounting component (its warnings describe that validator, not enclosing byte replay)", accounting),
        details("Verified context inventory — bytes omitted, references never followed", bundle["context_inventory"]),
        details("Authority flags — all false", bundle["authority"]),
        ("<p>No automatic go/narrow/stop, field prioritization, accuracy, confidence interval or independence estimate is inferred. "
        "The recorded conclusion must be assessed by authorized humans. This report is not a dataset, a public release, "
        "a signed scientific approval or an execution credential.</p></section></main></body></html>")]
    payload = "\n".join(out).encode("utf-8")
    canary.require(0 < len(payload) <= MAX_REPORT_BYTES, "pilot_report_byte_limit")
    return payload


def publish(path, payload, evidence_directory):
    """Exclusive private creation; any post-create error leaves an unknown output.

    Never overwrite or unlink an existing leaf. This is not atomic publication:
    consumers must verify the final hash before reading a concurrently created file.
    """
    path = Path(path)
    canary.require(path.suffix == ".html" and 0 < len(payload) <= MAX_REPORT_BYTES, "pilot_report_output_invalid")
    directory = canary._directory_fd(path.parent)
    descriptor, created = None, False
    try:
        forbidden = canary._directory_fd(Path(evidence_directory))
        try:
            parent, excluded = os.fstat(directory), os.fstat(forbidden)
            canary.require((parent.st_dev, parent.st_ino) != (excluded.st_dev, excluded.st_ino), "pilot_report_inside_evidence")
        finally:
            os.close(forbidden)
        descriptor = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        created = True
        original = os.fstat(descriptor)
        os.fchmod(descriptor, 0o600)
        remaining = memoryview(payload)
        while remaining:
            size = os.write(descriptor, remaining)
            canary.require(size > 0, "pilot_report_write_failed")
            remaining = remaining[size:]
        os.fsync(descriptor)
        os.fsync(directory)
        reopened = canary._directory_fd(path.parent)
        try:
            current = os.fstat(reopened)
            canary.require((current.st_dev, current.st_ino) == (parent.st_dev, parent.st_ino), "pilot_report_parent_changed")
        finally:
            os.close(reopened)
        _, signature = canary.read_raw(path, canary.sha(payload), MAX_REPORT_BYTES)
        canary.require(signature[:2] == (original.st_dev, original.st_ino) and stat.S_IMODE(signature[2]) == 0o600,
                       "pilot_report_output_changed")
    except Exception:
        if created:
            raise canary.OutputStateUnknown("output_state_unknown") from None
        raise
    finally:
        try:
            if descriptor is not None:
                os.close(descriptor)
        except OSError:
            if created:
                raise canary.OutputStateUnknown("output_state_unknown") from None
            raise
        finally:
            try:
                os.close(directory)
            except OSError:
                if created:
                    raise canary.OutputStateUnknown("output_state_unknown") from None
                raise


def run(*, mode, output_path=None, report_path=None, expected_report_sha256=None, **inputs):
    canary.require(mode in {"build", "verify"}, "pilot_report_mode_invalid")
    canary.require((output_path is not None and report_path is None and expected_report_sha256 is None) if mode == "build"
                   else (output_path is None and report_path is not None and type(expected_report_sha256) is str
                         and canary.HASH.fullmatch(expected_report_sha256)), "pilot_report_paths_invalid")
    canary.require("mode" not in inputs and "output_path" not in inputs, "pilot_report_inputs_invalid")
    source = Path(__file__).read_bytes()
    captured = canary.read_package(inputs["bundle_path"], inputs["expected_bundle_sha256"])
    final = canary.read_raw(inputs["conclusion_path"], inputs["expected_conclusion_sha256"])
    canary.run(mode="verify", **inputs)
    conclusion = canary.json_value(final[0])
    # Keep the bound document unchanged when validating it; the file pin is display metadata.
    payload = render(captured[0], conclusion, renderer_sha256=canary.sha(source),
                     conclusion_file_sha256=inputs["expected_conclusion_sha256"])
    canary.require(canary.read_package(inputs["bundle_path"], inputs["expected_bundle_sha256"]) == captured
                   and canary.read_raw(inputs["conclusion_path"], inputs["expected_conclusion_sha256"]) == final,
                   "pilot_report_inputs_changed")
    canary.require(Path(__file__).read_bytes() == source, "pilot_report_renderer_changed")
    # Reconstruct again after rendering; context/code/ledger changes cannot be masked by a derived report.
    canary.run(mode="verify", **inputs)
    canary.require(Path(__file__).read_bytes() == source, "pilot_report_renderer_changed")
    if mode == "verify":
        canary.require(canary.read_raw(report_path, expected_report_sha256, MAX_REPORT_BYTES)[0] == payload,
                       "pilot_report_replay_mismatch")
    else:
        publish(output_path, payload, inputs["evidence_directory"])
    return {"version": VERSION, "report_sha256": canary.sha(payload), "report_bytes": len(payload),
        "canary_sha256": inputs["expected_bundle_sha256"], "conclusion_file_sha256": inputs["expected_conclusion_sha256"],
        "output_written": mode == "build", "report_replay_verified": mode == "verify",
        "source_context_bytes_embedded": False, "private_review_declarations_embedded": True,
        "authority": dict(canary.AUTHORITY), "training_execution": "disabled"}


def main(argv=None):
    parser = canary.SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("mode", choices=["build", "verify"])
    for name in ("selection", "reviews", "protocol", "evidence-directory", "selection-file-sha256", "selection-sha256",
                 "reviews-file-sha256", "review-log-sha256", "protocol-sha256", "bundle", "bundle-sha256", "conclusion", "conclusion-sha256"):
        parser.add_argument("--" + name, required=True)
    for name in ("output", "report", "report-sha256"):
        parser.add_argument("--" + name)
    try:
        args = vars(parser.parse_args(argv))
        arguments = {("expected_" + key if key.endswith("_sha256") else key + "_path"
            if key in {"selection", "reviews", "protocol", "bundle", "conclusion", "output", "report"} else key): value
            for key, value in args.items()}
        receipt = run(**arguments)
    except canary.OutputStateUnknown:
        print('{"status":"output_state_unknown","output_written":null,"scientific_acceptance":false}', file=sys.stderr)
        return 2
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RecursionError, OverflowError):
        print('{"status":"invalid","output_written":false,"scientific_acceptance":false}', file=sys.stderr)
        return 2
    print(canary.canonical(receipt).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
