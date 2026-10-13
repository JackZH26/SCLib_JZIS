"""Turn source-grounded runs into blinded atomic comparison inputs."""

from __future__ import annotations

from copy import deepcopy

from .contract import bind_evidence, digest, evidences, source_number_spans
from .statistics import run_statistics
from .manifest import source_captures


def semantic_quantity(quantity):
    if quantity and quantity["status"] == "normalized":
        return {
            **{k: quantity[k] for k in ("relation", "value", "lower", "upper", "unit")},
            **{k: quantity["raw"].get(k) for k in ("approximate", "uncertainty_raw")},
        }
    return None


def _value_positions(prop, inputs):
    lookup = {b["block_id"]: b for b in inputs}
    raw = (prop.get("quantity") or prop.get("qualitative") or {}).get("raw_text")
    positions = set()
    for evidence in prop["evidence"]:
        bound = bind_evidence(evidence, lookup)
        if raw and evidence["quote"].count(raw) == 1:
            start = bound["source_start"] + evidence["quote"].index(raw)
            q = prop.get("quantity") or {}
            values = {q.get(k) for k in ("value", "lower", "upper")} - {None}
            spans = [(lo, hi) for number, lo, hi in source_number_spans(raw) if number in values]
            for lo, hi in spans or [(0, len(raw))]:
                positions.add((bound["source_sha256"], start + lo, start + hi))
    if not positions:
        positions = {
            (e["source_sha256"], e["source_start"], e["source_end"])
            for e in (bind_evidence(e, lookup) for e in prop["evidence"])
        }
    return [list(p) for p in sorted(positions)]


def atomic_claims(run):
    """Point scoring uses an atomic source anchor; UI series retain physical points."""
    claims = []
    blocks = {b["block_id"]: b for b in run["blocks"]}
    for output in run["results"]:
        normalized = {n["local_id"]: n for n in output["normalized"]}
        inputs = output.get("input_blocks", [blocks[output["block_id"]]])
        for row in output["candidate"]["results"]:
            properties = row["properties"]
            normalized_properties = normalized[row["local_id"]]["properties"]
            if not properties and row["sc_outcome"] in {"not_detected", "inconclusive"}:
                properties = [
                    {
                        "property_key": "superconductivity_outcome",
                        "quantity": None,
                        "qualitative": {"raw_text": row["sc_outcome"]},
                        "qualifiers": {},
                        "knowledge_origin": row["event"]["knowledge_origin"],
                        "source_role": row["event"]["source_role"],
                        "evidence": row["outcome_evidence"],
                    }
                ]
                normalized_properties = [{"quantity": None}]
            for prop, normalized_prop in zip(properties, normalized_properties, strict=True):
                quantity = normalized_prop["quantity"]
                if semantic_quantity(quantity) is not None:
                    value = semantic_quantity(quantity)
                else:
                    value = {
                        "unresolved_raw": deepcopy(prop.get("quantity") or prop.get("qualitative"))
                    }
                point = _value_positions(prop, inputs)
                state = [
                    {
                        "key": c["key"],
                        "status": c["status"],
                        "quantity": semantic_quantity(nc["quantity"]),
                        "unresolved_raw": deepcopy(c["quantity"])
                        if c["quantity"] and semantic_quantity(nc["quantity"]) is None
                        else None,
                        "qualitative": c["qualitative"],
                    }
                    for c, nc in zip(
                        row["conditions"], normalized[row["local_id"]]["conditions"], strict=True
                    )
                ]
                state.sort(key=digest)
                claims.append(
                    {
                        "anchor_id": digest(point),
                        "material": row["subject"]["name_raw"],
                        "sample": deepcopy(
                            row["sample"]
                            and {
                                k: row["sample"][k]
                                for k in ("label_raw", "form_raw", "preparation_raw")
                            }
                        ),
                        "state": state,
                        "point": point,
                        "property": prop["property_key"],
                        "criterion": prop["qualifiers"].get("tc_definition", "unknown"),
                        "quantity": value,
                        "method": row["event"]["method_raw"],
                        "knowledge_origin": prop["knowledge_origin"],
                        "source_role": prop["source_role"],
                        "evidence": deepcopy(list(evidences(prop))),
                        "sc_outcome": row["sc_outcome"],
                    }
                )
    return claims


def comparison_package(runs, manifest, provider):
    expected = {p["work_id"]: p for p in manifest["papers"]}
    captures = {work: source_captures(p) for work, p in expected.items()}
    claims, coverage, configurations, statistics, configuration = {}, {}, set(), {}, None
    seen = set()
    for run in runs:
        work = run["work_id"]
        identity = (work, run["input_sha256"])
        if work not in expected or identity in seen:
            raise ValueError("comparison_work_missing_from_manifest_or_capture_duplicated")
        if run["config"]["provider"]["provider"] != provider:
            raise ValueError("comparison_provider_mismatch")
        paper = expected[work]
        source = next(
            (c for c in captures[work] if c["content_manifest_sha256"] == run["input_sha256"]), None
        )
        if (
            run["paper_id"] != paper["paper_id"]
            or source is None
            or run["source_sha256"] != source["source_sha256"]
        ):
            raise ValueError("comparison_source_manifest_mismatch")
        seen.add(identity)
        configurations.add(digest(run["config"]))
        configuration = run["config"]
        claims.setdefault(work, []).extend(atomic_claims(run))
        coverage.setdefault(work, {"captures": {}})["captures"][run["input_sha256"]] = run[
            "coverage"
        ]
        statistics.setdefault(work, {})[run["input_sha256"]] = run_statistics(run)
    if len(configurations) != 1:
        raise ValueError("comparison_requires_one_frozen_configuration")
    for work, value in coverage.items():
        required = {c["content_manifest_sha256"] for c in captures[work]}
        missing = required - value["captures"].keys()
        scope_confirmed = expected[work].get("supplement_status") in {
            "included",
            "confirmed_absent",
        }
        value.update(
            missing_captures=sorted(missing),
            source_scope_confirmed=scope_confirmed,
            machine_text_complete=not missing
            and all(c["machine_text_complete"] for c in value["captures"].values()),
            end_to_end_complete=not missing
            and scope_confirmed
            and all(c["end_to_end_complete"] for c in value["captures"].values()),
        )
    return {
        "version": "materials-ner-comparison-input/1",
        "provider": provider,
        "manifest_sha256": manifest["manifest_sha256"],
        "config_sha256": configurations.pop(),
        "configuration": configuration,
        "claims_by_work": claims,
        "coverage_by_work": coverage,
        "statistics_by_work_and_capture": statistics,
        "missing_works": sorted(set(expected) - claims.keys()),
        "scientific_acceptance": False,
    }
