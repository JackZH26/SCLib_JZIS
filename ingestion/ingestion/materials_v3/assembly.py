"""Source-scoped report assembly; unknowns never authorize merging samples."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

from .contract import bound_row_evidence, digest


def assemble_reports(runs: list[dict], material_links: dict[str, str]) -> dict:
    """One chosen provider run per source. Links are curator/program inputs."""
    by_capture = {}
    for run in runs:
        capture = (run["work_id"], run["source_sha256"])
        if capture in by_capture and by_capture[capture]["job_key"] != run["job_key"]:
            raise ValueError("multiple_model_interpretations_require_explicit_selection")
        by_capture[capture] = run
    materials = defaultdict(list)
    unresolved, seen = [], set()
    for run in by_capture.values():
        for block_result in run["results"]:
            normalized = {n["local_id"]: n for n in block_result["normalized"]}
            for result, occurrence in zip(
                block_result["candidate"]["results"], block_result["occurrences"], strict=True
            ):
                subject = result["subject"]
                link_key = f"{run['source_sha256']}:{subject['name_raw']}"
                material_id = material_links.get(link_key)
                if material_id is None:
                    unresolved.append(
                        {
                            "subject": subject,
                            "source_sha256": run["source_sha256"],
                            "reason": "material_identity_unresolved",
                        }
                    )
                    continue
                # Identical source-position + interpretation is a repeated extractor occurrence.
                interpretation = digest({k: v for k, v in result.items() if k != "local_id"})
                key = (run["source_sha256"], occurrence, interpretation)
                if key in seen:
                    continue
                seen.add(key)
                sample, series = result["sample"], result["series_point"]
                sample_identity = (
                    sample["label_raw"]
                    if sample and sample["label_raw"]
                    else "unknown:" + occurrence
                )
                explicit_series = series and series["series_label_raw"]
                series_id = digest(
                    {
                        "source": run["source_sha256"],
                        "material": material_id,
                        "sample": sample_identity,
                        "label": explicit_series or "unresolved:" + occurrence,
                    }
                )
                point_id = digest({"series": series_id, "occurrence": occurrence})
                event_id = digest(
                    {
                        "point": point_id,
                        "event": result["event"],
                        "conditions": result["conditions"],
                    }
                )
                inputs = block_result.get("input_blocks")
                if inputs is None:
                    inputs = [
                        next(b for b in run["blocks"] if b["block_id"] == block_result["block_id"])
                    ]
                row = {
                    "work_id": run["work_id"],
                    "paper_id": run["paper_id"],
                    "source_sha256": run["source_sha256"],
                    "sample": deepcopy(sample),
                    "series_id": series_id,
                    "point_id": point_id,
                    "event_id": event_id,
                    "series_point": deepcopy(series),
                    "occurrence_key": occurrence,
                    "event": deepcopy(result["event"]),
                    "sc_outcome": result["sc_outcome"],
                    "conditions": deepcopy(result["conditions"]),
                    "properties": deepcopy(result["properties"]),
                    "normalized": normalized[result["local_id"]],
                    "evidence": bound_row_evidence(result, inputs),
                    "review_status": "pending",
                    "coverage": run["coverage"],
                    "scientific_acceptance": False,
                }
                materials[material_id].append(row)
    output = {}
    for material_id, rows in materials.items():
        by_work = defaultdict(list)
        for row in rows:
            by_work[row["work_id"]].append(row)
        positive = []
        epc_bundles = []
        for row in rows:
            normalized_properties = row["normalized"]["properties"]
            for prop, normalized_prop in zip(row["properties"], normalized_properties, strict=True):
                if prop["property_key"] != normalized_prop["key"]:
                    raise ValueError("property_normalization_order_mismatch")
                q = normalized_prop["quantity"]
                if (
                    prop["property_key"] == "tc"
                    and row["sc_outcome"] == "positive_reported"
                    and q
                    and q["status"] == "normalized"
                    and q["relation"] == "point"
                ):
                    positive.append(
                        {
                            "event_id": row["event_id"],
                            "point_id": row["point_id"],
                            "work_id": row["work_id"],
                            "quantity": q,
                            "conditions": row["conditions"],
                            "origin": prop["knowledge_origin"],
                            "source_role": prop["source_role"],
                            "criterion": prop["qualifiers"].get("tc_definition", "unknown"),
                        }
                    )
            bundle_keys = {"electron_phonon_lambda", "omega_log", "coulomb_mu_star", "tc"}
            # Co-presence in one explicit calculation event; never maxima from different rows.
            bundle = {
                k: [p["quantity"] for p in normalized_properties if p["key"] == k]
                for k in bundle_keys
            }
            if row["event"]["event_kind"] == "calculation" and all(
                len(values) == 1 and values[0] and values[0]["status"] == "normalized"
                for values in bundle.values()
            ):
                norm = {k: values[0] for k, values in bundle.items()}
                epc_bundles.append(
                    {
                        "event_id": row["event_id"],
                        "parameters": {k: norm[k] for k in sorted(bundle_keys)},
                        "method": row["event"]["method_raw"],
                        "association_status": "source_candidate_pending_review",
                    }
                )
        selected = max(
            positive,
            key=lambda p: (p["quantity"]["value"], p["event_id"], p["criterion"]),
            default=None,
        )
        output[material_id] = {
            "material_id": material_id,
            "selected_result": selected,
            "reports": [
                {"work_id": work_id, "points": points}
                for work_id, points in sorted(by_work.items())
            ],
            "support_counts": {
                "source_ids": len({r["paper_id"] for r in rows}),
                "unique_works": len(by_work),
                "result_points": len({r["point_id"] for r in rows}),
                "independent_data_groups": None,
                "independence_status": "not_established",
                "cited_reports": sum(r["event"]["source_role"] == "cited" for r in rows),
            },
            "epc_bundles": epc_bundles,
            "preview_only": True,
            "scientific_acceptance": False,
        }
    return {
        "version": "material-report-projection/3.0",
        "materials": output,
        "unresolved_materials": unresolved,
    }
