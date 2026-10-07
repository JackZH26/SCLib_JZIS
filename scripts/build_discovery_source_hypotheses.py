#!/usr/bin/env python3
"""Project the pinned screened catalogue into an unscored public dataset.

No scientific calculation, scoring, source download, or frozen-source mutation.
Source paths are operator CLI arguments and never enter the public projection.
"""
import argparse
import hashlib
import json
import math
import pathlib
import re

INDEX_SHA = "591c01a4b3b91a808698a07ef6cb1436749467483dfd2e33a0b3f4b4e8b0829b"
ELIGIBILITY_SHA = "0e3a11c37594feafc6d9cdab398112c8980955777257ccb049779a6ccb526f3a"
CATALOGUE_SHA = "851ee6814b5201cb337ef566c3f00acde928849a1298908d1b1c680cba3ceae1"
FILENAME = "source-computed-candidates-2026-10-07.json"
CRITERIA = ("identity", "quantitative_route_response", "pairing_relevance",
            "ambient_feasibility", "competition_and_coherence", "novelty", "decision")
PRIVATE_KEYS = {"local_path", "remote_path", "remote_directory", "working_directory",
                "account", "email", "user", "hostname", "host_id", "invocation", "InvocationID",
                "invocation_id", "unit_name", "service", "runtime", "resource", "resources", "token",
                "resource_envelope", "cpu_seconds", "wall_seconds", "MemoryPeak", "MemoryMax",
                "budget", "available_budget", "native_cost", "private_resource", "within_route_priority"}
PRIVATE_TEXT = re.compile(r"(?:/Users/|/opt/|/home/|/var/|/tmp/|[A-Za-z]:\\|jack@|ssh://)")
RISK_LABELS = {
    "technetium": "Technetium follow-up practicality",
    "hydrogen_anharmonicity": "Hydrogen zero-point / anharmonic response",
    "magnetic_model": "Spin-model sensitivity",
    "metastable_phase": "Phase / ordering competition",
    "residual_force_stress": "Residual force / stress sensitivity",
    "sampling_method": "Sampling / method sensitivity",
}
ATTENTION_TAGS = {"含Tc，实用性需评估": "technetium", "H零点与非谐修正": "hydrogen_anharmonicity",
                  "自旋模型需核对": "magnetic_model"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pinned(path, expected_sha, maximum):
    require(path.is_file() and path.stat().st_size <= maximum, "Input file bound failed")
    body = path.read_bytes()
    require(hashlib.sha256(body).hexdigest() == expected_sha, "Frozen input SHA mismatch")
    return json.loads(body), len(body)


def public_evidence(value):
    """Keep scientific values and record/hash provenance, omit private custody."""
    if isinstance(value, dict):
        return {key: public_evidence(child) for key, child in value.items()
                if key not in PRIVATE_KEYS
                and not (key == "path" and isinstance(child, str) and PRIVATE_TEXT.search(child))
                and not (key == "unit" and isinstance(child, str) and child.endswith(".service"))
                and not re.search(r"(?:cgroup|systemd|credential|auth_token|access_token|refresh_token|api_key|password|ssh_|CPUQuota|MemAvailable)", key, re.I)}
    if isinstance(value, list):
        return [public_evidence(child) for child in value]
    if isinstance(value, str):
        # Private location strings are never republished as evidence links.
        if PRIVATE_TEXT.search(value):
            return "[private custody location omitted]"
        return value
    if isinstance(value, float):
        require(math.isfinite(value), "Nonfinite source evidence")
    require(value is None or isinstance(value, (str, int, float, bool)), "Unsupported source value")
    return value


def prototype_summary(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("motif"), str):
        return value["motif"]
    records = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
    symmetry = [row for row in records if isinstance(row, dict) and row.get("status") == "completed"
                and row.get("mode") == "color_aware" and row.get("SG_number") is not None]
    if symmetry:
        numbers = sorted({row["SG_number"] for row in symmetry})
        return "Source symmetry observation: space group " + ", ".join(map(str, numbers)) + ". Ordered-site evidence is retained; space group alone is not a prototype certificate."
    return "Exact source geometry association retained; no named prototype is assigned here."


def risk_tags(row):
    tags = {ATTENTION_TAGS[tag] for tag in row["research_attention_tags"]}
    text = row["primary_risk"].lower()
    if re.search(r"metastab|compet|disorder|ordering|phase conversion|decompos", text):
        tags.add("metastable_phase")
    if re.search(r"force|stress|bfgs|strain", text):
        tags.add("residual_force_stress")
    if re.search(r"sampling|grid|cutoff|ecut|version|pp |pseudopot|numerical|q/k|k/q", text):
        tags.add("sampling_method")
    return sorted(tags)


def project(index, eligibility):
    require(index["count"] == index["distinct_compositions"] == 103 and len(index["rows"]) == 103, "Expected 103 distinct groups")
    require(eligibility["source_index_pin"]["sha256"] == INDEX_SHA, "Eligibility index binding mismatch")
    require(eligibility["recommended_unscored_compositions"] == 103 and eligibility["formal_RPS_ready_compositions"] == 0, "Release scope mismatch")
    require(eligibility["source_dataset"]["doi"] == "10.24435/materialscloud:qv-bq", "Dataset source mismatch")
    candidates = []
    for row in index["rows"]:
        require(row["route"] == "geometry_construction" and row["support_grade"] == 3, "Unexpected route or support level")
        for name in ("formal_RPS", "experimental_superconductivity", "room_temperature_support",
                     "quantified_physical_bandwidth", "quantified_mobile_carrier_density", "whole_BZ_stability", "global_thermodynamic_stability"):
            require(row[name] is None, "A frozen unknown field acquired a scientific claim")
        require(set(row["seven_criteria"]) == set(CRITERIA), "Seven-criterion shape mismatch")
        criteria = dict(row["seven_criteria"])
        if row["material"] == "Nb2HfTa":
            require("Nb2TiMo" in criteria["novelty"], "Expected frozen precedent wording not found")
            criteria["novelty"] = "New to the reviewed catalogue as an exact ordered Nb2HfTa geometry-route hypothesis. Known experimental HfNbTa has a different composition and is not an identity match. Published source predictions are acknowledged; worldwide first discovery is not claimed."
        tc = row["source_computed_Eliashberg_mu0p1"]
        require(tc["mu_star"] == 0.1 and tc["experimental"] is False and tc["new_native_calculation"] is False and tc["sigma_binding"] is None, "Source Tc scope mismatch")
        for name in ("target_K", "control_K", "delta_K"):
            require(isinstance(tc[name], (int, float)) and math.isfinite(tc[name]), "Missing source Tc value")
        require(abs(tc["target_K"] - tc["control_K"] - tc["delta_K"]) < 1e-9, "Source Tc contrast mismatch")
        evidence_pins = [{"artifact": pathlib.PurePath(pin["path"]).name, "bytes": pin["bytes"],
                          "sha256": pin["sha256"], "availability": "digest_reference"} for pin in row["evidence_refs"]]
        candidates.append({
            "id": "source-hypothesis:" + row["source_state"], "formula": row["material"],
            "reduced_formula": row["material"], "composition": row["reduced_composition"],
            "canonical_composition_key": row["canonical_composition_key"], "elements": sorted(row["reduced_composition"]),
            "source_state": row["source_state"], "control_state": row["control_state"],
            "source_directory": row["directory_key"], "control_directory": row["control_directory_key"],
            "status": "unscored_research_hypothesis", "route": "geometry_construction", "route_submechanism": row["route_submechanism"],
            "prototype": prototype_summary(row["prototype"]), "prototype_evidence": public_evidence(row["prototype"]),
            "support_grade": 3, "support_scale_max": 4,
            "support_meaning": "Preliminary screened support within the stated source model. This ordinal level is not a probability, formal RPS score or human scientific review.",
            "source_tc": {"target_K": tc["target_K"], "control_K": tc["control_K"], "delta_K": tc["delta_K"],
                          "unit": "K", "method": "Eliashberg", "mu_star": 0.1, "experimental": False, "sigma_binding": None},
            "lambda_difference": {"all10": row["lambda_target_minus_control_all10"], "range": row["lambda_target_minus_control_range"], "convention": "target_minus_control", "unit": "dimensionless"},
            "omega_log_ratio_all10": row["weighted_omega_log_ratio_all10"],
            "risk_summary": row["primary_risk"], "ambient_scope": row["ambient_scope"],
            "route_response": row["route_response"], "next_action": row["next_falsifiable_decision"],
            "seven_criteria": criteria, "risk_tags": risk_tags(row),
            "countercontrols": public_evidence(row["frozen_countercontrols"] or []),
            "physical_summary": public_evidence(row["source_physical_summary"]), "evidence_pins": evidence_pins,
            "newness_scope": row["newness_scope"], "formal_RPS": None, "rank": None, "success_probability": None,
            "human_scientific_review": None, "experimental_superconductivity": None, "room_temperature_support": None,
            "quantified_physical_bandwidth": None, "quantified_mobile_carrier_density": None,
            "whole_BZ_stability": None, "global_thermodynamic_stability": None,
        })
    require(len({row["canonical_composition_key"] for row in candidates}) == 103, "Composition duplicate")
    candidates.sort(key=lambda row: row["formula"])
    source = dict(eligibility["source_dataset"])
    source["license_url"] = "https://creativecommons.org/licenses/by/4.0/"
    source["attribution"] = "Source data: Tiago F. T. Cerqueira, Antonio Sanna and Miguel A. L. Marques, Sampling the materials space for conventional superconducting compounds, Materials Cloud 2023.163 v1, DOI 10.24435/materialscloud:qv-bq, CC BY 4.0. This catalogue is a derived projection with additional source-state screening commentary."
    return {
        "schema_version": "source-computed-hypothesis-catalogue/1.0.0", "version": "2026-10-07-source103-v1", "published_on": "2026-10-07",
        "publication_status": "public_unscored_research_hypotheses", "default_sort": "formula",
        "download_url": "/research-hypotheses/" + FILENAME,
        "scope": "Previously private source-model screening is now published as unscored source-computed material-design hypotheses. Historical private-screening wording is retained as context. These predictions are new to this reviewed catalogue only; experimental confirmation, worldwide first discovery, formal RPS and human scientific review are not claimed.",
        "source_tc_scope": "Source isotropic Eliashberg Tc in K at mu*=0.1 is a model result, not experimental Tc. It is a separate source product and is not associated with an individual Gaussian width or a numerical uncertainty interval.",
        "pairing_response_scope": "Retained ten-width lambda contrasts and independent source Tc products support bounded source-model comparisons. Chemical, mass, volume, sampling, spin and SOC effects can co-change; no universal causal or error-bound interpretation is assigned.",
        "risk_tag_scope": "Attention labels support browsing. Element labels are not measured magnetic ground states, rejection criteria or calibrated potential scores; no label does not mean no risk.",
        "evidence_scope": "Public record IDs, archive directory locators, scientific summaries and artifact digests are retained. Digest-only references are not represented as public downloads. Full source data are available from the cited Materials Cloud record; exact per-material URLs are not invented.",
        "counts": {"composition_groups": 103, "formal_RPS_scored": 0, "human_reviewed": 0, "experimental_confirmed": 0, "room_temperature_supported": 0},
        "pathway_status": {"geometry_construction": 103, "quantified_physical_bandwidth": 0, "quantified_mobile_carrier_density": 0},
        "dataset_source": source, "risk_tag_labels": RISK_LABELS,
        "projection_provenance": {"source_index_sha256": INDEX_SHA, "frozen_catalogue_sha256": CATALOGUE_SHA, "publication_eligibility_sha256": ELIGIBILITY_SHA,
                                  "frozen_sources_changed": False, "new_scientific_calculations": 0,
                                  "public_wording_corrections": [{"formula": "Nb2HfTa", "field": "seven_criteria.novelty", "reason": "Replace the unrelated Nb2TiMo precedent with the different-composition HfNbTa precedent; numerical and frozen source records unchanged."}]},
        "candidates": candidates,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=pathlib.Path, required=True)
    parser.add_argument("--eligibility", type=pathlib.Path, required=True)
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    args = parser.parse_args()
    index, _ = pinned(args.index, INDEX_SHA, 4 * 1024 * 1024)
    eligibility, _ = pinned(args.eligibility, ELIGIBILITY_SHA, 1024 * 1024)
    result = project(index, eligibility)
    body = (json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf8")
    require(len(body) <= 8 * 1024 * 1024 and not PRIVATE_TEXT.search(body.decode("utf8")), "Public projection privacy/size bound failed")
    require(not re.search(r"[\u3400-\u9fff]", body.decode("utf8")), "Public website copy must default to English")
    detail_files = []
    detail_records = []
    for row in result["candidates"]:
        detail = {"schema_version": "source-computed-hypothesis-detail/1.0.0", "catalogue_version": result["version"],
                  **{key: result[key] for key in ("dataset_source", "scope", "source_tc_scope", "pairing_response_scope", "risk_tag_scope")}, "candidate": row}
        detail_body = (json.dumps(detail, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf8")
        relative = "details/" + row["source_state"] + ".json"
        detail_files.append((relative, detail_body))
        detail_records.append({"id": row["id"], "source_state": row["source_state"], "file": relative,
                               "bytes": len(detail_body), "sha256": hashlib.sha256(detail_body).hexdigest()})
    manifest = {"schema_version": "source-computed-hypothesis-detail-manifest/1.0.0", "catalogue_version": result["version"],
                "catalogue_sha256": hashlib.sha256(body).hexdigest(), "details": detail_records}
    manifest_body = (json.dumps(manifest, indent=2) + "\n").encode("utf8")
    pins = {"schema_version": "source-computed-hypothesis-public-pins/1.0.0", "data_file": FILENAME,
            "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            "source_index_sha256": INDEX_SHA, "frozen_catalogue_sha256": CATALOGUE_SHA, "publication_eligibility_sha256": ELIGIBILITY_SHA,
            "detail_manifest_file": "source-computed-candidates-2026-10-07.details.json", "detail_manifest_bytes": len(manifest_body),
            "detail_manifest_sha256": hashlib.sha256(manifest_body).hexdigest()}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in [(FILENAME, body), (FILENAME.replace(".json", ".pins.json"), (json.dumps(pins, indent=2) + "\n").encode()),
                              (pins["detail_manifest_file"], manifest_body), *detail_files]:
        path = args.output_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            require(path.read_bytes() == content, "Refusing to replace a different public projection")
        else:
            with path.open("xb") as handle:
                handle.write(content)
    print(json.dumps({"composition_groups": 103, "bytes": len(body), "sha256": pins["sha256"], "formal_RPS_scored": 0}))


if __name__ == "__main__":
    main()
