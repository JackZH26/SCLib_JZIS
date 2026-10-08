#!/usr/bin/env python3
"""Derive public research dossiers without altering the frozen source catalogue.

No calculations, literature-search completeness inference, or new physical values.
The client-safe rubric evaluates these observations independently of old support 3/4.
"""
import argparse
import hashlib
import json
from pathlib import Path

SOURCE_NAME = "source-computed-candidates-2026-10-07.json"
SOURCE_SHA = "4a9089bc569f99ad7f5f469280814fb22bfcc86252b1fb7c1e1be446f8bcac98"
VERSION = "2026-10-08-evidence103-v1"
PRIMARY = "https://arxiv.org/html/2307.10728v1"


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def comparisons(row):
    """Only explicit target-oriented quantities; do not classify prose or element tags."""
    result = []
    for index, control in enumerate(row["countercontrols"]):
        interval = control.get("lambda_target_minus_other_range")
        units = "dimensionless"
        delta = control.get("independent_source_Eli_Tc_delta_K", control.get("source_Eli_gain_target_minus_other_K"))
        reference = control.get("control", control.get("other_state", control.get("control_directory")))
        if interval is None and control.get("target_relative_lambda_gain_percent_range") is not None:
            interval = control["target_relative_lambda_gain_percent_range"]
            units = "percent"
            tc = control.get("separate_source_Eli_mu01_target_control")
            if tc and len(tc) == 2:
                delta = tc[0][1] - tc[1][1]
        if interval is None and control.get("lambda_target_minus_control_all10") is not None:
            interval = [min(control["lambda_target_minus_control_all10"]), max(control["lambda_target_minus_control_all10"])]
            delta = control.get("separate_Eli_target_minus_control_K")
            reference = control.get("control_directory")
        if interval is None and control.get("lambda_B_minus_A_range") is not None:
            a, b = control.get("fixed_A", ""), control.get("fixed_B", "")
            if row["source_state"] in str(b):
                interval = control["lambda_B_minus_A_range"]
                delta = control.get("source_Eliashberg_delta_B_minus_A_K")
                reference = a
            elif row["source_state"] in str(a):
                low, high = control["lambda_B_minus_A_range"]
                interval = [-high, -low]
                value = control.get("source_Eliashberg_delta_B_minus_A_K")
                delta = -value if isinstance(value, (int, float)) else None
                reference = b
        if not isinstance(interval, list) or len(interval) != 2 or not isinstance(delta, (int, float)):
            continue
        low, high = interval
        if high < 0 and delta < 0:
            direction = "joint_adverse"
            scope = "This frozen alternative has both higher coupling and higher source-model Tc than the target; the selected-control advantage does not extend to every alternative."
        elif high < 0 and delta > 0 or low > 0 and delta < 0:
            direction = "discordant"
            scope = "Coupling and separate source-model Tc move in opposite directions against this alternative; a monotonic coupling-to-Tc explanation is insufficient."
        else:
            continue
        result.append({"comparison_origin": "frozen_countercontrol", "countercontrol_index": index, "control_reference": reference or "Frozen alternative", "direction": direction,
                       "lambda_target_minus_control_range": interval, "lambda_unit": units,
                       "source_tc_target_minus_control_K": delta, "scope": scope,
                       "causal_geometry_effect": None})
    # Selected comparisons are equally capable of limiting a monotonic explanation.
    # Do not duplicate a selected pair already retained among frozen countercontrols.
    interval, delta = row["lambda_difference"]["range"], row["source_tc"]["delta_K"]
    if interval and (interval[1] < 0 < delta or interval[0] > 0 > delta) and not any(
            row["control_state"] in item["control_reference"] for item in result):
        result.insert(0, {"comparison_origin": "selected_source_control", "countercontrol_index": None,
                          "control_reference": row["control_directory"] or row["control_state"], "direction": "discordant",
                          "lambda_target_minus_control_range": interval, "lambda_unit": "dimensionless",
                          "source_tc_target_minus_control_K": delta,
                          "scope": "Coupling and separate source-model Tc move in opposite directions against the selected source control; a monotonic coupling-to-Tc explanation is insufficient.",
                          "causal_geometry_effect": None})
    return result


def build(public):
    body = (public / SOURCE_NAME).read_bytes()
    assert hashlib.sha256(body).hexdigest() == SOURCE_SHA, "Frozen source changed; review before creating a new dossier version."
    source = json.loads(body)
    manifest = json.loads((public / SOURCE_NAME.replace(".json", ".details.json")).read_text())
    pins = {row["source_state"]: row for row in manifest["details"]}
    output = public / "evidence-cards" / VERSION
    output.mkdir(parents=True, exist_ok=True)
    entries = []
    for row in source["candidates"]:
        counterevidence = comparisons(row)
        card = {
            "schema_version": "discovery-evidence-card/1.0.0", "version": VERSION,
            "id": row["id"], "source_state": row["source_state"], "formula": row["formula"],
            "source_catalogue_sha256": SOURCE_SHA, "source_detail_sha256": pins[row["source_state"]]["sha256"],
            "evidence_level": "E1", "evidence_basis": "Published source theory. Source auditing and comparisons are not independent recalculation or experimental validation.",
            "prior": {"category": "published_theoretical_proposal", "exact_experimental_status": "unresolved",
                      "search_completeness": "unknown", "summary": row["newness_scope"],
                      "case_context": row["seven_criteria"]["novelty"],
                      "sources": [{"title": source["dataset_source"]["title"], "url": source["dataset_source"]["url"], "doi": source["dataset_source"]["doi"]},
                                  {"title": "Primary source study: conventional superconducting compounds", "url": PRIMARY}],
                      "claim_boundary": "Every listed state already has a published source prediction. Related compositions or phases are not experimental confirmation of this exact state. This dossier does not establish global novelty or an exhaustive literature search."},
            "bottleneck": {"summary": row["risk_summary"], "ambient_scope": row["ambient_scope"],
                           "attention_tags": row["risk_tags"], "counterevidence": counterevidence,
                           "unknowns": ["Independent reproduction", "Global phase competition", "Coherence under the intended conditions", "Experimental superconductivity in this exact state", "Direct support for approximately 300 K at ambient pressure"]},
            "proposed_contribution": {"status": "proposed_not_completed", "intervention": row["route_response"],
                                      "target_state": row["source_state"], "selected_control": row["control_state"],
                                      "next_action": row["next_action"],
                                      "falsifier": "Reproduce the stated target and control with matched pseudopotential family, functional, cutoff, sampling and relevant spin/SOC treatment. Loss or reversal of the claimed response, instability of the target, or an unresolved competing phase changes the decision; ambiguous outcomes remain unresolved.",
                                      "new_state_inheritance": "A child structure or modification needs its own calculation and identity. It does not inherit source Tc or experimental status."},
            "support_observations": {"source_pairing_quantified": True, "geometry_causality_quantified": False,
                                     "bandwidth_quantified": False, "carrier_density_quantified": False,
                                     "stability_for_target_quantified": False, "coherence_quantified": False,
                                     "competition_quantified": False, "ambient_300K_direct_support": None,
                                     "evidence_level": "E1", "counterevidence": counterevidence},
        }
        card_body = encoded(card)
        file = output / f"{row['source_state']}.json"
        file.write_bytes(card_body)
        entries.append({"id": row["id"], "source_state": row["source_state"], "formula": row["formula"],
                        "source_detail_sha256": pins[row["source_state"]]["sha256"],
                        "observations": card["support_observations"],
                        "detail": {"url": f"/research-hypotheses/evidence-cards/{VERSION}/{file.name}",
                                   "bytes": len(card_body), "sha256": hashlib.sha256(card_body).hexdigest()}})
    assert len(entries) == 103 and len({r["id"] for r in entries}) == 103
    catalogue = {"schema_version": "discovery-evidence-card-index/1.0.0", "version": VERSION,
                 "rubric_version": "discovery-provisional-support/1.0.0", "source_catalogue_sha256": SOURCE_SHA,
                 "scope": "Provisional research support and dossiers. No new calculation, independent review, experimental confirmation, formal RPS assessment, or global novelty claim.", "candidates": entries}
    data_body = encoded(catalogue)
    filename = f"{VERSION}.json"
    (public / filename).write_bytes(data_body)
    (public / f"{VERSION}.pins.json").write_bytes(encoded({"data_file": filename, "bytes": len(data_body), "sha256": hashlib.sha256(data_body).hexdigest(), "source_catalogue_sha256": SOURCE_SHA}))
    print(f"Generated {len(entries)} evidence cards; frozen source SHA-256 unchanged.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--public", type=Path, default=Path(__file__).resolve().parents[1] / "frontend/public/research-hypotheses")
    build(parser.parse_args().public)
