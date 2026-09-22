"""Pure, deterministic hard-parity checks for an offline claim plan.

This module intentionally checks only facts that can be compared exactly
before a database load. Timeline and material-headline parity remain deferred:
their legacy projections depend on fields/policies not yet represented by the
typed claim columns.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from ingestion.claims.mapper import map_record_to_claim, source_record_identity
from ingestion.claims.outcomes import negative_outcome_issues
from ingestion.claims.work_identity import plan_work_identities
from ingestion.extract.formula_enrichment import enrich_material_composition
from ingestion.extract.scientific_values import record_quantity
from ingestion.pressure_semantics import classify_pressure

PARITY_SCHEMA_VERSION = "sclib-typed-claim-shadow-parity/v1"
_TC_FIELDS = ("value_kelvin", "tc_kelvin", "tc")
_DISTRIBUTION_FIELDS = (
    "property_type",
    "evidence_role",
    "result_status",
    "value_relation",
    "pressure_state",
    "validity_status",
)
_NUMERIC_FIELDS = (
    "value_kelvin",
    "value_lower_kelvin",
    "value_upper_kelvin",
    "pressure_gpa",
    "minimum_temperature_k",
    "magnetic_field_t",
    "extraction_confidence",
    "relation_confidence",
)
_EXISTING_REVIEW_STATUSES = {"accepted", "pending", "rejected"}
_EXISTING_MATCH_METHODS = {
    "exact_doi",
    "related_paper",
    "exact_arxiv",
    "metadata",
    "manual",
    "singleton",
}
_EXISTING_RELATION_TYPES = {
    "canonical_version",
    "preprint",
    "published_version",
    "supplement",
    "correction",
    "unknown",
}


class _Issues:
    """Count hard failures while retaining deterministic bounded samples."""

    def __init__(self, sample_limit: int) -> None:
        self.sample_limit = sample_limit
        self.counts: Counter[str] = Counter()
        self.samples: dict[str, set[str]] = defaultdict(set)

    def add(self, code: str, sample: str, count: int = 1) -> None:
        if count <= 0:
            return
        self.counts[code] += count
        samples = self.samples[code]
        samples.add(sample)
        if len(samples) > self.sample_limit:
            samples.remove(max(samples))

    def render(self) -> list[dict[str, Any]]:
        return [
            {
                "code": code,
                "count": self.counts[code],
                "samples": sorted(self.samples[code]),
            }
            for code in sorted(self.counts)
            if self.counts[code]
        ]


def build_shadow_parity_report(
    material_rows: Iterable[Mapping[str, Any]],
    paper_rows: Iterable[Mapping[str, Any]],
    plan: Mapping[str, Any],
    *,
    existing_paper_work: Iterable[Mapping[str, Any]] = (),
    sample_limit: int = 20,
) -> dict[str, Any]:
    """Audit planner inputs/output without I/O or mutation."""
    if sample_limit < 1:
        raise ValueError("sample_limit must be positive")

    materials = list(material_rows)
    papers = list(paper_rows)
    existing_mapping_rows = list(existing_paper_work)
    claims = list(plan.get("claims") or [])
    compositions = list(plan.get("compositions") or [])
    works = list(plan.get("works") or [])
    mapping_rows = list(plan.get("paper_work_map") or [])
    failures = list(plan.get("failures") or [])
    warnings = list(plan.get("warnings") or [])
    summary = plan.get("summary") or {}
    issues = _Issues(sample_limit)

    source = _source_inventory(materials, issues)
    _verify_compositions(materials, compositions, issues)
    paper_by_id = _paper_index(papers, issues)
    work_by_id, paper_work = _work_index(mapping_rows, works, paper_by_id, issues)
    _replay_work_identity(
        papers,
        existing_mapping_rows,
        works,
        mapping_rows,
        issues,
    )
    for paper_id in sorted(paper_by_id.keys() - paper_work.keys()):
        issues.add("source_paper_without_work_mapping", f"paper:{paper_id}")
    mapped_work_ids = set(paper_work.values())
    for work_id in sorted(work_by_id.keys() - mapped_work_ids):
        issues.add("orphan_work_without_paper_mapping", f"work:{work_id}")

    if not materials:
        issues.add("empty_material_snapshot", "materials:0")
    if source["input_records"] == 0:
        issues.add("empty_source_record_snapshot", "source_records:0")

    snapshot_id = _id(summary.get("source_snapshot_id"))
    if not _is_uuid(snapshot_id):
        issues.add("invalid_source_snapshot_id", f"snapshot:{snapshot_id}")

    summary_input = _summary_count(summary, "input_records", issues)
    summary_claims = _summary_count(summary, "unique_claims", issues)
    summary_exact_duplicates = _summary_count(summary, "exact_duplicate_records", issues)
    # The planner's historical "exact duplicate" name denotes identical
    # canonical source identity, not byte-identical observation envelopes.
    # Raw occurrence accounting remains a separate, full-payload inventory.
    source_exact_duplicates = sum(
        max(count - 1, 0) for count in source["source_identities"].values()
    )
    _compare_count(
        issues,
        "exact_duplicate_count_mismatch",
        source_exact_duplicates,
        summary_exact_duplicates,
    )
    summary_materials = _summary_count(summary, "materials", issues)
    summary_papers = _summary_count(summary, "papers", issues)

    _compare_count(
        issues,
        "source_record_count_mismatch",
        source["input_records"],
        summary_input,
    )
    _compare_count(issues, "claim_count_mismatch", len(claims), summary_claims)
    _compare_count(issues, "material_count_mismatch", len(materials), summary_materials)
    _compare_count(issues, "paper_count_mismatch", len(papers), summary_papers)

    record_failures = sum(isinstance(row, Mapping) and "record_ordinal" in row for row in failures)
    accounted = len(claims) + source_exact_duplicates + record_failures
    unaccounted = summary_input - accounted
    if unaccounted:
        issues.add(
            "record_accounting_mismatch",
            (
                f"input:{summary_input}|claims:{len(claims)}|"
                f"duplicates:{source_exact_duplicates}|failures:{record_failures}"
            ),
            abs(unaccounted),
        )
    for failure in failures:
        issues.add("plan_failures_present", _failure_key(failure))

    distributions = {field: Counter() for field in _DISTRIBUTION_FIELDS}
    mapper_warnings: Counter[str] = Counter()
    planner_warnings = Counter(_value(row.get("code")) for row in warnings)
    claim_ids: set[str] = set()
    source_hashes: set[tuple[str, str]] = set()

    metrics = Counter(
        finite_tc=0,
        preserved_tc=0,
        negative_source_tc=0,
        missing_pressure=0,
        manufactured_pressure=0,
        finite_pressure=0,
        preserved_pressure=0,
        negative_source_pressure=0,
        ambiguous_zero=0,
        negative_claims=0,
        negative_missing_tmin=0,
        retracted_work_claims=0,
        raw_record_matches=0,
    )

    for ordinal, claim in enumerate(claims):
        key = _claim_key(claim, ordinal)
        for field, counter in distributions.items():
            counter[_value(claim.get(field))] += 1
        metadata = claim.get("extraction_metadata")
        if not isinstance(metadata, Mapping):
            issues.add("claim_extraction_metadata_not_object", key)
        else:
            raw_warnings = metadata.get("warnings", [])
            if isinstance(raw_warnings, Sequence) and not isinstance(raw_warnings, str):
                mapper_warnings.update(_value(item) for item in raw_warnings)
            elif raw_warnings not in (None, []):
                issues.add("claim_warnings_not_array", key)

        claim_id = _id(claim.get("id"))
        if not _is_uuid(claim_id):
            issues.add("claim_invalid_id", key)
        elif claim_id in claim_ids:
            issues.add("claim_duplicate_id", key)
        claim_ids.add(claim_id)

        material_id = _id(claim.get("material_id"))
        if material_id not in source["material_ids"]:
            issues.add("claim_unknown_material", key)
        if _id(claim.get("source_snapshot_id")) != snapshot_id:
            issues.add("claim_snapshot_mismatch", key)

        source_hash = _id(claim.get("source_record_hash"))
        if not _is_sha256(source_hash):
            issues.add("claim_invalid_source_hash", key)
        hash_key = (material_id, source_hash)
        if hash_key in source_hashes:
            issues.add("claim_duplicate_material_source_hash", key)
        source_hashes.add(hash_key)

        raw_record = claim.get("raw_record")
        if not isinstance(raw_record, Mapping):
            issues.add("claim_raw_record_not_object", key)
            raw_record = {}
        else:
            raw_key = (material_id, _canonical_json(raw_record))
            if source["records"][raw_key] <= 0:
                issues.add("claim_raw_record_not_in_source", key)
            else:
                source["records"][raw_key] -= 1
                metrics["raw_record_matches"] += 1

        paper_id = _id(claim.get("paper_id"))
        work_id = _id(claim.get("work_id"))
        raw_paper_id = _id(raw_record.get("paper_id"))
        if raw_paper_id != paper_id:
            issues.add("claim_paper_not_preserved_from_source", key)
        if paper_id:
            if paper_id not in paper_by_id:
                issues.add("claim_unknown_paper", key)
            if paper_work.get(paper_id) != work_id:
                issues.add("claim_paper_work_mismatch", key)
        elif work_id:
            issues.add("claim_work_without_paper", key)
        if work_id and work_id not in work_by_id:
            issues.add("claim_unknown_work", key)

        source_locator = claim.get("source_locator")
        if not isinstance(source_locator, Mapping):
            issues.add("claim_source_locator_not_object", key)
            source_locator = {}
        expected_source_hash, expected_claim_id = source_record_identity(
            material_id=material_id,
            paper_id=paper_id or None,
            raw_record=raw_record,
            source_locator=source_locator,
        )
        if source_hash != expected_source_hash:
            issues.add("claim_source_hash_mismatch", key)
        if claim_id != str(expected_claim_id):
            issues.add("claim_deterministic_id_mismatch", key)

        try:
            expected_claim = map_record_to_claim(
                raw_record,
                material_id=material_id,
                material_formula=source["formula_by_id"].get(material_id),
                paper=paper_by_id.get(paper_id),
                work_id=paper_work.get(paper_id),
                source_snapshot_id=snapshot_id,
            )
            if expected_claim["chunk_id"] is not None:
                expected_claim["chunk_id"] = None
            if _canonical_json(expected_claim) != _canonical_json(claim):
                issues.add("claim_mapper_replay_mismatch", key)
        except (AssertionError, TypeError, ValueError) as exc:
            issues.add("claim_mapper_replay_failed", f"{key}|error:{type(exc).__name__}")

        paper = paper_by_id.get(paper_id, {})
        source_retracted = (
            raw_record.get("retracted") is True
            or _slug(raw_record.get("validity_status")) == "retracted"
            or _slug(_first(paper, "status", "publication_status")) == "retracted"
        )
        claim_retracted = _slug(claim.get("validity_status")) == "retracted"
        if source_retracted != claim_retracted:
            issues.add("retraction_propagation_mismatch", key)
        if _slug(work_by_id.get(work_id, {}).get("publication_status")) == "retracted":
            metrics["retracted_work_claims"] += 1

        for field in _NUMERIC_FIELDS:
            value = claim.get(field)
            if value is None:
                continue
            number = _finite(value)
            if number is None:
                issues.add("typed_numeric_not_finite", f"{key}|field:{field}")
            elif number < 0:
                issues.add("typed_numeric_negative", f"{key}|field:{field}")

        if not _valid_tc_shape(claim):
            issues.add("typed_tc_shape_invalid", key)
        # Raw-record identity/membership above checks lossless preservation.
        # Compare physical quantities after dimensional normalization: 1800 mK
        # and 1.8 K must not be called different values. A malformed quantity is
        # retained as raw/proposal evidence, never forced into a valid scalar.
        raw_tc = _finite(_first(raw_record, *_TC_FIELDS))
        if raw_tc is not None and raw_tc < 0:
            metrics["negative_source_tc"] += 1
        tc_proposal = record_quantity(raw_record, "tc_kelvin", "value_kelvin", "tc")
        normalized_tc = _finite(tc_proposal.get("value"))
        if tc_proposal.get("status") == "parsed" and normalized_tc is not None and normalized_tc >= 0:
            metrics["finite_tc"] += 1
            if _preserves_tc(claim, normalized_tc):
                metrics["preserved_tc"] += 1
            else:
                issues.add("finite_source_tc_not_preserved", key)

        pressure_assessment = classify_pressure(raw_record)
        raw_pressure_value = pressure_assessment.raw_value
        typed_pressure = _finite(claim.get("pressure_gpa"))
        pressure_state = _slug(claim.get("pressure_state"))
        normalized_pressure = _finite(pressure_assessment.pressure_gpa)
        if (raw_pressure_value in (None, "") and normalized_pressure is None
                and pressure_assessment.relation == "unreported"):
            metrics["missing_pressure"] += 1
            if typed_pressure is not None or pressure_state in {
                "reported",
                "explicit_ambient",
            }:
                metrics["manufactured_pressure"] += 1
                issues.add("missing_pressure_was_manufactured", key)
        if normalized_pressure is not None:
            if normalized_pressure >= 0:
                metrics["finite_pressure"] += 1
                if typed_pressure is not None and math.isclose(
                    normalized_pressure,
                    typed_pressure,
                    rel_tol=0,
                    abs_tol=1e-12,
                ):
                    metrics["preserved_pressure"] += 1
                else:
                    issues.add("finite_source_pressure_not_preserved", key)
            else:
                metrics["negative_source_pressure"] += 1
                if typed_pressure is not None:
                    issues.add("negative_source_pressure_not_discarded", key)
        if not _valid_pressure_shape(claim):
            issues.add("typed_pressure_shape_invalid", key)
        if pressure_state == "ambiguous" and typed_pressure == 0:
            metrics["ambiguous_zero"] += 1

        if _slug(claim.get("result_status")) == "not_detected":
            metrics["negative_claims"] += 1
            if not _explicit_negative(raw_record):
                issues.add("implicit_negative_claim", key)
            negative_issues = negative_outcome_issues(claim)
            if set(negative_issues) & {
                "negative_result_property_mismatch", "negative_result_conflicts_with_tc_relation",
                "negative_result_invalid_value_shape",
            }:
                issues.add("negative_claim_shape_invalid", key)
            if negative_issues and _slug(claim.get("validity_status")) == "accepted":
                issues.add("accepted_negative_not_qualified", key)
            if claim.get("minimum_temperature_k") is None:
                metrics["negative_missing_tmin"] += 1
                if _slug(claim.get("validity_status")) == "accepted":
                    issues.add("accepted_negative_missing_tmin", key)

    remaining_source_records = sum(source["records"].values())
    if not failures and remaining_source_records != source_exact_duplicates:
        issues.add(
            "unconsumed_source_records",
            (f"remaining:{remaining_source_records}|expected_duplicates:{source_exact_duplicates}"),
            abs(remaining_source_records - source_exact_duplicates) or 1,
        )

    gate_failures = issues.render()
    return {
        "schema_version": PARITY_SCHEMA_VERSION,
        "source_snapshot_id": snapshot_id,
        "counts": {
            "material_rows": len(materials),
            "paper_rows": len(papers),
            "work_rows": len(works),
            "paper_work_rows": len(mapping_rows),
            "existing_paper_work_rows": len(existing_mapping_rows),
            "source_records": source["input_records"],
            "source_object_records": source["object_records"],
            "claims": len(claims),
            "compositions": len(compositions),
            "exact_duplicate_records": source_exact_duplicates,
            "plan_failures": len(failures),
            "plan_warnings": len(warnings),
        },
        "reconciliation": {
            "independent_input_records": source["input_records"],
            "planner_input_records": summary_input,
            "unique_claims": len(claims),
            "exact_duplicate_records": source_exact_duplicates,
            "record_failures": record_failures,
            "accounted_records": accounted,
            "unaccounted_records": unaccounted,
            "claim_raw_record_matches": metrics["raw_record_matches"],
            "unconsumed_source_records": remaining_source_records,
        },
        "source_occurrence_inventory": source["occurrence_inventory"],
        "lineage": {
            "claim_snapshot_mismatches": issues.counts["claim_snapshot_mismatch"],
            "claim_unknown_materials": issues.counts["claim_unknown_material"],
            "claim_unknown_papers": issues.counts["claim_unknown_paper"],
            "claim_paper_work_mismatches": (
                issues.counts["claim_paper_work_mismatch"]
                + issues.counts["claim_work_without_paper"]
                + issues.counts["claim_unknown_work"]
            ),
            "claim_identity_mismatches": (
                issues.counts["claim_source_hash_mismatch"]
                + issues.counts["claim_deterministic_id_mismatch"]
                + issues.counts["claim_mapper_replay_mismatch"]
                + issues.counts["claim_mapper_replay_failed"]
            ),
            "work_identity_replay_mismatches": (
                issues.counts["work_identity_replay_mismatch"]
                + issues.counts["work_identity_replay_failed"]
                + issues.counts["existing_paper_work_invalid"]
            ),
            "retraction_propagation_mismatches": issues.counts["retraction_propagation_mismatch"],
            "claims_on_retracted_works": metrics["retracted_work_claims"],
        },
        "hard_semantics": {
            "tc": {
                "finite_nonnegative_source_values": metrics["finite_tc"],
                "preserved_values": metrics["preserved_tc"],
                "preservation_mismatches": issues.counts["finite_source_tc_not_preserved"],
                "negative_source_values": metrics["negative_source_tc"],
                "invalid_typed_shapes": issues.counts["typed_tc_shape_invalid"],
            },
            "pressure": {
                "missing_source_values": metrics["missing_pressure"],
                "manufactured_values": metrics["manufactured_pressure"],
                "finite_nonnegative_source_values": metrics["finite_pressure"],
                "preserved_finite_nonnegative_values": metrics["preserved_pressure"],
                "negative_source_values": metrics["negative_source_pressure"],
                "preservation_mismatches": issues.counts["finite_source_pressure_not_preserved"],
                "ambiguous_zero_values": metrics["ambiguous_zero"],
                "invalid_typed_shapes": issues.counts["typed_pressure_shape_invalid"],
            },
            "negative_results": {
                "claims": metrics["negative_claims"],
                "implicit_claims": issues.counts["implicit_negative_claim"],
                "missing_minimum_temperature": metrics["negative_missing_tmin"],
                "accepted_missing_minimum_temperature": issues.counts[
                    "accepted_negative_missing_tmin"
                ],
            },
            "typed_numeric_nonfinite": issues.counts["typed_numeric_not_finite"],
            "typed_numeric_negative": issues.counts["typed_numeric_negative"],
        },
        "distributions": {
            **{field: _sorted(counter) for field, counter in distributions.items()},
            "mapper_warnings": _sorted(mapper_warnings),
            "planner_warnings": _sorted(planner_warnings),
        },
        "deferred_parity": {
            "timeline": {
                "status": "deferred",
                "reasons": [
                    "legacy_timeline_evidence_policy_differs_from_typed_claims",
                    "measurement_year_is_not_a_typed_claim_column",
                    "timeline_point_deduplication_is_a_projection_policy",
                ],
            },
            "material_headlines": {
                "status": "deferred",
                "reasons": [
                    "ambient_and_interface_tc_regime_is_not_a_typed_claim_column",
                    "legacy_manual_override_context_is_not_part_of_the_plan",
                    "paper_vs_work_corroboration_policy_is_not_frozen",
                ],
            },
        },
        "gate_failures": gate_failures,
        "gate_status": "pass" if not gate_failures else "fail",
    }


def _source_inventory(materials: Sequence[Mapping[str, Any]], issues: _Issues) -> dict[str, Any]:
    material_ids: set[str] = set()
    formula_by_id: dict[str, str | None] = {}
    records: Counter[tuple[str, str]] = Counter()
    source_identities: Counter[str] = Counter()
    occurrences: list[tuple[str, int, Any]] = []
    input_records = object_records = 0
    for material in materials:
        material_id = _id(material.get("id"))
        if not material_id or material_id in material_ids:
            issues.add("source_material_id_invalid_or_duplicate", f"material:{material_id}")
            continue
        material_ids.add(material_id)
        formula_value = _first(material, "formula", "formula_normalized")
        formula_by_id[material_id] = (
            str(formula_value).strip() if formula_value not in (None, "") else None
        )
        raw_records: Any = material.get("records") or []
        if isinstance(raw_records, str):
            try:
                raw_records = json.loads(raw_records)
            except json.JSONDecodeError:
                issues.add("source_records_invalid_json", f"material:{material_id}")
                continue
        if not isinstance(raw_records, list):
            issues.add("source_records_not_array", f"material:{material_id}")
            continue
        input_records += len(raw_records)
        for ordinal, record in enumerate(raw_records):
            # Retain every input ordinal in the digest, including a malformed
            # record that independently fails the gate. This is an inventory
            # of source-export input, not a claim that deduplicated claims
            # themselves contain every original observation payload.
            occurrences.append((material_id, ordinal, record))
            if not isinstance(record, Mapping):
                issues.add("source_record_not_object", f"material:{material_id}|record:{ordinal}")
                continue
            object_records += 1
            records[(material_id, _canonical_json(record))] += 1
            # Use the public mapper's exclusion contract without copying its
            # reserved-key list. Fixed outer paper/locator arguments only
            # establish an equivalence key: the original paper and locator
            # fields inside raw_record remain identity-bearing. This key is
            # never emitted as a claim hash. The claim loop separately checks
            # each actual mapper ID, locator, and complete raw representative.
            equivalence_hash, _ = source_record_identity(
                material_id=material_id, paper_id=None,
                raw_record=record, source_locator={},
            )
            source_identities[equivalence_hash] += 1
    occurrence_digest = hashlib.sha256()
    for material_id, ordinal, record in sorted(occurrences, key=lambda row: (row[0], row[1])):
        occurrence_digest.update(_canonical_json({
            "material_id": material_id, "record_ordinal": ordinal, "raw_record": record,
        }).encode("utf-8") + b"\n")
    return {
        "material_ids": material_ids,
        "formula_by_id": formula_by_id,
        "records": records,
        "source_identities": source_identities,
        "input_records": input_records,
        "object_records": object_records,
        "occurrence_inventory": {
            "schema_version": "sclib-source-occurrence-inventory/v1",
            "scope": "source_export_input_not_unique_claim_payloads",
            "hash_basis": "canonical_jsonl_sorted_by_material_id_and_record_ordinal",
            "sha256": occurrence_digest.hexdigest(),
            "raw_occurrences": len(occurrences),
            "unique_source_identities": len(source_identities),
            "exact_raw_duplicate_records": sum(max(count - 1, 0) for count in records.values()),
        },
    }


def _paper_index(
    papers: Sequence[Mapping[str, Any]], issues: _Issues
) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for ordinal, paper in enumerate(papers):
        paper_id = _id(_first(paper, "id", "paper_id"))
        if not paper_id or paper_id in indexed:
            issues.add("source_paper_id_invalid_or_duplicate", f"paper_row:{ordinal}|id:{paper_id}")
        else:
            indexed[paper_id] = paper
    return indexed


def _verify_compositions(
    materials: Sequence[Mapping[str, Any]],
    compositions: Sequence[Mapping[str, Any]],
    issues: _Issues,
) -> None:
    actual_by_material: dict[str, Mapping[str, Any]] = {}
    for ordinal, row in enumerate(compositions):
        material_id = _id(row.get("material_id"))
        if not material_id or material_id in actual_by_material:
            issues.add(
                "composition_material_id_invalid_or_duplicate",
                f"composition:{ordinal}|material:{material_id}",
            )
            continue
        actual_by_material[material_id] = row

    expected_material_ids: set[str] = set()
    for ordinal, material in enumerate(materials):
        material_id = _id(material.get("id"))
        if not material_id or material_id in expected_material_ids:
            continue
        expected_material_ids.add(material_id)
        enrichment = enrich_material_composition(material)
        expected = {
            "material_id": material_id,
            "composition_status": enrichment.pop("composition_status"),
            "composition_data": enrichment,
        }
        actual = actual_by_material.get(material_id)
        if actual is None:
            issues.add("composition_missing_for_material", f"material:{material_id}")
        elif _canonical_json(expected) != _canonical_json(actual):
            issues.add("composition_enrichment_mismatch", f"material:{material_id}")

    for material_id in sorted(actual_by_material.keys() - expected_material_ids):
        issues.add("composition_unknown_material", f"material:{material_id}")


def _work_index(
    mappings: Sequence[Mapping[str, Any]],
    works: Sequence[Mapping[str, Any]],
    papers: Mapping[str, Mapping[str, Any]],
    issues: _Issues,
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str]]:
    work_by_id: dict[str, Mapping[str, Any]] = {}
    for ordinal, work in enumerate(works):
        work_id = _id(work.get("id"))
        if not _is_uuid(work_id) or work_id in work_by_id:
            issues.add("work_id_invalid_or_duplicate", f"work_row:{ordinal}|id:{work_id}")
        else:
            work_by_id[work_id] = work
    paper_work: dict[str, str] = {}
    for ordinal, mapping in enumerate(mappings):
        paper_id = _id(mapping.get("paper_id"))
        work_id = _id(mapping.get("work_id"))
        key = f"paper_work:{ordinal}|paper:{paper_id}|work:{work_id}"
        if paper_id not in papers:
            issues.add("paper_work_unknown_paper", key)
        if work_id not in work_by_id:
            issues.add("paper_work_unknown_work", key)
        if not paper_id or paper_id in paper_work:
            issues.add("paper_work_duplicate_or_missing_paper", key)
        else:
            paper_work[paper_id] = work_id
    return work_by_id, paper_work


def _replay_work_identity(
    papers: Sequence[Mapping[str, Any]],
    existing_mappings: Sequence[Mapping[str, Any]],
    actual_works: Sequence[Mapping[str, Any]],
    actual_mappings: Sequence[Mapping[str, Any]],
    issues: _Issues,
) -> None:
    """Re-run identity resolution without trusting any planned identity row.

    Only accepted persisted mappings are identity edges.  Pending and rejected
    rows describe adjudication of an old pair and therefore cannot influence
    the independently resolved component graph.
    """
    existing_by_paper: dict[str, dict[str, Any]] = {}
    accepted_work_ids: dict[str, str] = {}
    for ordinal, row in enumerate(existing_mappings):
        if not isinstance(row, Mapping):
            issues.add(
                "existing_paper_work_invalid",
                f"existing_paper_work:{ordinal}|reason:not_object",
            )
            continue
        paper_id = _id(row.get("paper_id"))
        raw_work_id = _id(row.get("work_id"))
        review_status = _slug(row.get("review_status"))
        key = f"existing_paper_work:{ordinal}|paper:{paper_id or '<missing>'}"
        if not paper_id or paper_id in existing_by_paper:
            issues.add("existing_paper_work_invalid", f"{key}|reason:paper_id")
            continue
        try:
            work_id = str(uuid.UUID(raw_work_id))
        except (AttributeError, TypeError, ValueError):
            issues.add("existing_paper_work_invalid", f"{key}|reason:work_id")
            continue
        if review_status not in _EXISTING_REVIEW_STATUSES:
            issues.add("existing_paper_work_invalid", f"{key}|reason:review_status")
            continue
        match_method = row.get("match_method")
        if match_method is not None and (
            not isinstance(match_method, str) or match_method not in _EXISTING_MATCH_METHODS
        ):
            issues.add("existing_paper_work_invalid", f"{key}|reason:match_method")
            continue
        relation_type = row.get("relation_type")
        if relation_type is not None and (
            not isinstance(relation_type, str) or relation_type not in _EXISTING_RELATION_TYPES
        ):
            issues.add("existing_paper_work_invalid", f"{key}|reason:relation_type")
            continue
        normalized = dict(row)
        normalized.update(
            {
                "paper_id": paper_id,
                "work_id": work_id,
                "review_status": review_status,
            }
        )
        existing_by_paper[paper_id] = normalized
        if review_status == "accepted":
            accepted_work_ids[paper_id] = work_id

    try:
        expected_plan = plan_work_identities(
            papers,
            existing_work_ids=accepted_work_ids,
        )
    except (TypeError, ValueError) as exc:
        issues.add(
            "work_identity_replay_failed",
            f"error:{type(exc).__name__}|message:{str(exc)[:160]}",
        )
        return

    # Mirror only the planner's persisted-adjudication overlay.  Crucially,
    # non-accepted rows do not get copied onto the newly proposed pair.
    for mapping in expected_plan["paper_work_map"]:
        existing = existing_by_paper.get(mapping["paper_id"])
        if existing is None or existing["review_status"] != "accepted":
            continue
        mapping["review_status"] = "accepted"
        if existing.get("match_method") is not None:
            mapping["match_method"] = existing["match_method"]
        if existing.get("relation_type") is not None:
            mapping["relation_type"] = existing["relation_type"]

    _compare_identity_rows(
        expected_plan["works"],
        actual_works,
        key_field="id",
        label="work",
        issues=issues,
    )
    _compare_identity_rows(
        expected_plan["paper_work_map"],
        actual_mappings,
        key_field="paper_id",
        label="paper_work",
        issues=issues,
    )


def _compare_identity_rows(
    expected_rows: Sequence[Mapping[str, Any]],
    actual_rows: Sequence[Mapping[str, Any]],
    *,
    key_field: str,
    label: str,
    issues: _Issues,
) -> None:
    expected = {_id(row.get(key_field)): row for row in expected_rows}
    actual: dict[str, Mapping[str, Any]] = {}
    for ordinal, row in enumerate(actual_rows):
        if not isinstance(row, Mapping):
            issues.add(
                "work_identity_replay_mismatch",
                f"{label}_row:{ordinal}|reason:not_object",
            )
            continue
        key = _id(row.get(key_field))
        if not key or key in actual:
            issues.add(
                "work_identity_replay_mismatch",
                f"{label}_row:{ordinal}|{key_field}:{key or '<missing>'}|reason:duplicate_or_missing_key",
            )
            continue
        actual[key] = row

    for key in sorted(expected.keys() | actual.keys()):
        expected_row = expected.get(key)
        actual_row = actual.get(key)
        if expected_row is None:
            issues.add(
                "work_identity_replay_mismatch",
                f"{label}:{key}|reason:unexpected_row",
            )
            continue
        if actual_row is None:
            issues.add(
                "work_identity_replay_mismatch",
                f"{label}:{key}|reason:missing_row",
            )
            continue
        for field in sorted(expected_row.keys() | actual_row.keys(), key=str):
            expected_present = field in expected_row
            actual_present = field in actual_row
            expected_value = expected_row.get(field)
            actual_value = actual_row.get(field)
            if expected_present == actual_present and _canonical_json(
                expected_value
            ) == _canonical_json(actual_value):
                continue
            issues.add(
                "work_identity_replay_mismatch",
                (
                    f"{label}:{key}|field:{field}|"
                    f"expected:{_identity_sample(expected_value, expected_present)}|"
                    f"actual:{_identity_sample(actual_value, actual_present)}"
                ),
            )


def _identity_sample(value: Any, present: bool) -> str:
    if not present:
        return "<missing>"
    rendered = _canonical_json(value)
    return rendered if len(rendered) <= 160 else f"{rendered[:157]}..."


def _summary_count(summary: Mapping[str, Any], field: str, issues: _Issues) -> int:
    value = summary.get(field)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    issues.add("plan_summary_invalid_count", f"summary.{field}:{value}")
    return 0


def _compare_count(issues: _Issues, code: str, expected: int, actual: int) -> None:
    if expected != actual:
        issues.add(code, f"expected:{expected}|actual:{actual}", abs(expected - actual) or 1)


def _valid_tc_shape(claim: Mapping[str, Any]) -> bool:
    relation = _slug(claim.get("value_relation"))
    value = claim.get("value_kelvin")
    lower = claim.get("value_lower_kelvin")
    upper = claim.get("value_upper_kelvin")
    return {
        "exact": value is not None and lower is None and upper is None,
        "interval": value is None and lower is not None and upper is not None,
        "lt": value is None and lower is None and upper is not None,
        "le": value is None and lower is None and upper is not None,
        "gt": value is None and lower is not None and upper is None,
        "ge": value is None and lower is not None and upper is None,
        "unreported": value is None and lower is None and upper is None,
    }.get(relation, False)


def _preserves_tc(claim: Mapping[str, Any], source: float) -> bool:
    relation = _slug(claim.get("value_relation"))
    fields = {
        "exact": ("value_kelvin",),
        "interval": ("value_lower_kelvin", "value_upper_kelvin"),
        "lt": ("value_upper_kelvin",),
        "le": ("value_upper_kelvin",),
        "gt": ("value_lower_kelvin",),
        "ge": ("value_lower_kelvin",),
    }.get(relation, ())
    return any(
        (value := _finite(claim.get(field))) is not None
        and math.isclose(value, source, rel_tol=0, abs_tol=1e-12)
        for field in fields
    )


def _valid_pressure_shape(claim: Mapping[str, Any]) -> bool:
    state = _slug(claim.get("pressure_state"))
    raw = claim.get("pressure_gpa")
    value = _finite(raw)
    if raw is not None and value is None or value is not None and value < 0:
        return False
    return {
        "explicit_ambient": value == 0,
        "reported": value is not None and value >= 0,
        "not_reported": raw is None,
        # V1 preserves a finite conflicting value alongside ambiguous status;
        # source metadata/replay keep the conflict. V2 states use NULL instead.
        "ambiguous": raw is None or value is not None and value >= 0,
    }.get(state, False)


def _explicit_negative(record: Mapping[str, Any]) -> bool:
    result = _slug(_first(record, "result_status", "outcome_state", "outcome"))
    if result in {
        "not_observed",
        "notdetected",
        "no_transition",
        "no_superconductivity",
        "non_superconducting",
        "negative",
        "not_detected",
    }:
        return True
    if record.get("no_transition") is True or record.get("not_detected") is True:
        return True
    return any(
        field in record and record.get(field) is False
        for field in (
            "superconductivity_observed",
            "transition_observed",
            "is_superconducting",
        )
    )


def _finite(value: Any) -> float | None:
    if not isinstance(value, (int, float, Decimal)) or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first(row: Mapping[str, Any], *fields: str) -> Any:
    for field in fields:
        if field in row and row[field] is not None:
            return row[field]
    return None


def _id(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _is_uuid(value: str) -> bool:
    try:
        import uuid

        return str(uuid.UUID(value)) == value.lower()
    except (AttributeError, ValueError):
        return False


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value)


def _slug(value: Any) -> str:
    text = str(value or "").strip().lower().replace("μ", "mu")
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _value(value: Any) -> str:
    return str(value) if value not in (None, "") else "<null>"


def _claim_key(claim: Mapping[str, Any], ordinal: int) -> str:
    return (
        f"claim:{_id(claim.get('id')) or ordinal}|material:{_id(claim.get('material_id'))}|"
        f"paper:{_id(claim.get('paper_id')) or '<none>'}|"
        f"hash:{_id(claim.get('source_record_hash')) or '<missing>'}"
    )


def _failure_key(failure: Any) -> str:
    if not isinstance(failure, Mapping):
        return f"failure:{failure!r}"
    return (
        f"code:{_value(failure.get('code'))}|material:{_value(failure.get('material_id'))}|"
        f"record:{_value(failure.get('record_ordinal'))}"
    )


def _sorted(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return str(value) if not math.isfinite(value) else 0.0 if value == 0 else value
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat() if value.tzinfo is not None else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    return str(value)


build_parity_report = build_shadow_parity_report
