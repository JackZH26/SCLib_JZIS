"""JSON, locator and semantic gates shared by all provider transports."""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from .registry import normalize_quantity


def canonical(value) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


@lru_cache(maxsize=1)
def schema() -> dict:
    value = json.loads(Path(__file__).with_name("candidate.schema.json").read_text())
    Draft202012Validator.check_schema(value)
    return value


def provider_schema() -> dict:
    """Strict transport subset; omitted science constraints run after generation."""

    def convert(value):
        if isinstance(value, list):
            return [convert(v) for v in value]
        if not isinstance(value, dict):
            return value
        out = {
            k: convert(v)
            for k, v in value.items()
            if k
            not in {
                "$schema",
                "$id",
                "if",
                "then",
                "else",
                "allOf",
                "not",
                "minItems",
                "minLength",
                "minimum",
                "maximum",
                "uniqueItems",
            }
        }
        if "const" in out:
            out["enum"] = [out.pop("const")]
        if out.get("type") == "object":
            properties = out.get("properties", {})
            originally_required = set(value.get("required", []))
            for key in properties:
                if key not in originally_required and "enum" not in properties[key]:
                    properties[key] = {"anyOf": [properties[key], {"type": "null"}]}
            out["required"] = list(properties)
            out["additionalProperties"] = False
        return out

    return convert(deepcopy(schema()))


class CandidateError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(errors[:12]))


def parse_json(text: str) -> dict:
    """Reject duplicate keys, NaN, and trailing output; never return [] on failure."""

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise CandidateError(["duplicate_json_key"])
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(CandidateError(["nonfinite_json"])),
        )
    except json.JSONDecodeError as exc:
        raise CandidateError([f"invalid_json:{exc.lineno}:{exc.colno}"]) from None


def evidences(value):
    if isinstance(value, dict):
        if "block_id" in value and "quote" in value:
            yield value
        else:
            for child in value.values():
                yield from evidences(child)
    elif isinstance(value, list):
        for child in value:
            yield from evidences(child)


def source_number_spans(raw: str) -> list[tuple[float, int, int]]:
    """Read explicit decimal/scientific notation; never evaluate source code."""
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
    values, remaining = [], list(raw)
    exponent = r"(?:\^\s*\{?([-+]?\d+)\}?|([⁻⁺]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+))"
    operator = r"(?:×|x|·|\\times|\\cdot)"
    for match in re.finditer(rf"({number})\s*{operator}\s*10\s*{exponent}", raw):
        power = (match.group(2) or match.group(3)).translate(
            str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
        )
        try:
            result = (
                float(Decimal(match.group(1)) * Decimal(10) ** int(power))
                if -308 <= int(power) <= 308
                else math.inf
            )
        except (InvalidOperation, OverflowError):
            result = math.inf
        if math.isfinite(result):
            values.append((result, match.start(), match.end()))
        # A coefficient, base or exponent alone is not the reported quantity.
        remaining[match.start() : match.end()] = " " * (match.end() - match.start())
    remaining = "".join(remaining)
    for match in re.finditer(number, remaining):
        token = match.group()
        if token.startswith("-") and match.start() and remaining[match.start() - 1].isdigit():
            token = token[1:]
        value = float(token)
        if math.isfinite(value):
            values.append((value, match.start() + (len(match.group()) - len(token)), match.end()))
    return values


def source_numbers(raw: str) -> list[float]:
    return [number for number, _, _ in source_number_spans(raw)]


def bind_evidence(evidence: dict, blocks: dict) -> dict:
    block = blocks.get(evidence["block_id"])
    if block is None:
        raise CandidateError(["unknown_evidence_block"])
    quote, body = evidence["quote"], block["text"]
    start, end = evidence.get("char_start"), evidence.get("char_end")
    if start is None and end is None:
        matches = [m.start() for m in re.finditer(re.escape(quote), body)]
        if len(matches) != 1:
            raise CandidateError(["quote_missing_or_ambiguous_offset"])
        start, end = matches[0], matches[0] + len(quote)
    if type(start) is not int or type(end) is not int or end <= start or body[start:end] != quote:
        raise CandidateError(["quote_offset_mismatch"])
    if evidence.get("table_id") and evidence["table_id"] != block.get("table_id"):
        raise CandidateError(["table_locator_mismatch"])
    source_start, source_end = (
        block.get("source_start", 0) + start,
        block.get("source_start", 0) + end,
    )
    pages = sorted(
        {
            r["page"]
            for r in block.get("source_record_spans", [])
            if r.get("page") and r["source_end"] > source_start and r["source_start"] < source_end
        }
    )
    return {
        **evidence,
        "char_start": start,
        "char_end": end,
        "source_start": block.get("source_start", 0) + start,
        "source_end": block.get("source_start", 0) + end,
        "source_sha256": block["source_sha256"],
        "page": pages[0] if pages else block.get("page"),
        "source_pages": pages,
    }


def bound_row_evidence(row: dict, blocks: list[dict]) -> list[dict]:
    """Bind only this result's evidence, never every result in its source block."""
    lookup = {b["block_id"]: b for b in blocks}
    unique = {}
    for evidence in evidences(row):
        bound = bind_evidence(evidence, lookup)
        unique[digest(bound)] = bound
    return list(unique.values())


def validate_candidate(value: dict, blocks: list[dict]) -> dict:
    errors = [
        f"schema:{'/'.join(map(str, e.path))}:{e.validator}"
        for e in Draft202012Validator(schema()).iter_errors(value)
    ]
    if errors:
        raise CandidateError(errors)
    lookup = {b["block_id"]: b for b in blocks}
    if len(lookup) != len(blocks):
        raise CandidateError(["duplicate_input_block"])
    ids = [r["local_id"] for r in value["results"]]
    if len(set(ids)) != len(ids):
        errors.append("duplicate_local_id")
    output = deepcopy(value)
    # Bound evidence is kept outside the model contract, preserving original output.
    proof = []
    for evidence in evidences(value):
        try:
            proof.append(bind_evidence(evidence, lookup))
        except CandidateError as exc:
            errors.extend(exc.errors)
    normalized = []
    for link in value["unresolved_links"]:
        if any(local_id not in ids for local_id in link["candidate_local_ids"]):
            errors.append("unresolved_link_unknown_local_id")
    for row in value["results"]:
        for node, fields in (
            (row["subject"], ("name_raw", "formula_raw")),
            (row["sample"], ("label_raw", "form_raw", "preparation_raw")),
            (row["series_point"], ("series_label_raw", "point_label_raw", "replicate_label_raw")),
            (row["event"], ("method_raw", "calculation_settings_raw", "cited_source_raw")),
        ):
            if node:
                quotes = "\n".join(e["quote"] for e in node["evidence"])
                if any(
                    node.get(field) is not None and node[field] not in quotes for field in fields
                ):
                    errors.append("raw_subject_sample_series_or_method_not_in_evidence")
        targets = {b["block_id"] for b in blocks if b.get("block_role") == "target"}
        anchors = row["outcome_evidence"] + [
            e for p in row["properties"] for e in p["evidence"] if e["role"] == "value"
        ]
        if targets and not any(e["block_id"] in targets for e in anchors):
            errors.append("result_is_context_only")
        nr = {"local_id": row["local_id"], "conditions": [], "properties": []}
        condition_keys = [c["key"] for c in row["conditions"]]
        if len(set(condition_keys)) != len(condition_keys):
            errors.append("multiple_values_for_condition_need_separate_points")
        for condition in row["conditions"]:
            if condition["status"] == "explicit_ambient" and condition["key"] not in {
                "measurement_pressure",
                "synthesis_pressure",
                "calculation_pressure",
                "structural_pressure",
            }:
                errors.append("ambient_is_pressure_only")
        for item, is_condition in [(c, True) for c in row["conditions"]] + [
            (p, False) for p in row["properties"]
        ]:
            key = item["key"] if is_condition else item["property_key"]
            quantity = item["quantity"]
            joined = "\n".join(e["quote"] for e in item["evidence"])
            if item["qualitative"] and item["qualitative"]["raw_text"] not in joined:
                errors.append("raw_qualitative_not_in_evidence")
            if any(
                raw is not None and raw not in joined
                for key, raw in item.get("qualifiers", {}).items()
                if key.endswith("_raw")
            ):
                errors.append("raw_qualifier_not_in_evidence")
            if quantity is not None:
                numbers = [
                    quantity[k] for k in ("value", "lower", "upper") if quantity[k] is not None
                ]
                if any(isinstance(n, bool) or not math.isfinite(n) for n in numbers):
                    errors.append("invalid_numeric_value")
                if quantity["relation"] == "interval" and quantity["lower"] > quantity["upper"]:
                    errors.append("reversed_interval")
                if key not in {
                    "formation_energy_per_atom",
                    "phonon_min_frequency",
                    "strain",
                } and any(n < 0 for n in numbers):
                    errors.append("negative_physical_quantity")
                if (
                    is_condition
                    and item["status"] == "explicit_ambient"
                    and numbers
                    and any(n != 0 for n in numbers)
                ):
                    errors.append("ambient_numeric_pressure_conflict")
                if any(n not in source_numbers(quantity["raw_text"]) for n in numbers):
                    errors.append("quantity_not_in_raw_text")
                joined = " ".join(e["quote"] for e in item["evidence"])
                if quantity["raw_text"] not in joined:
                    errors.append("raw_quantity_not_in_evidence")
                unit = quantity["raw_unit"]
                if (
                    unit
                    and unit not in joined
                    and not (unit == "1" and key in {"electron_phonon_lambda", "coulomb_mu_star"})
                ):
                    errors.append("raw_unit_not_in_evidence")
                value_quotes = [
                    e["quote"] for e in item["evidence"] if e["role"] in {"value", "condition"}
                ]
                if value_quotes and not any(
                    quote.count(quantity["raw_text"]) == 1 for quote in value_quotes
                ):
                    errors.append("raw_quantity_not_unique_in_evidence")
                nq = normalize_quantity(
                    key, quantity, condition=is_condition, qualifiers=item.get("qualifiers")
                )
            else:
                nq = None
            nr["conditions" if is_condition else "properties"].append({"key": key, "quantity": nq})
        if row["sc_outcome"] == "not_detected":
            tc = [p for p in row["properties"] if p["property_key"] == "tc" and p["quantity"]]
            if any(p["quantity"]["relation"] in {"point", "interval", "gt", "ge"} for p in tc):
                errors.append("negative_outcome_has_positive_tc")
        if (
            row["event"]["event_kind"] == "calculation"
            and row["event"]["knowledge_origin"] == "Observed"
        ):
            errors.append("calculation_cannot_be_observed")
        normalized.append(nr)
    # A link can remain unresolved but must name an existing local result when supplied.
    if errors:
        raise CandidateError(sorted(set(errors)))
    return {
        "candidate": output,
        "bound_evidence": proof,
        "normalized": normalized,
        "candidate_sha256": digest(output),
        "scientific_acceptance": False,
    }


def occurrence_positions(result: dict, blocks: list[dict]) -> list:
    """Position identity excludes model, local id and interpreted numeric values."""
    lookup = {b["block_id"]: b for b in blocks}
    # Exact raw-value source spans distinguish two points in the same sentence.
    # Numeric interpretation and the provider are absent from this identity.
    properties = [p for p in result["properties"] if p["property_key"] == "tc"] or result[
        "properties"
    ]
    positions = set()
    for prop in properties:
        raw = (
            prop["quantity"]["raw_text"]
            if prop["quantity"]
            else prop["qualitative"]["raw_text"]
            if prop["qualitative"]
            else None
        )
        for evidence in prop["evidence"]:
            if not raw or evidence["role"] not in {"value", "outcome"}:
                continue
            bound = bind_evidence(evidence, lookup)
            matches = [m.start() for m in re.finditer(re.escape(raw), evidence["quote"])]
            if len(matches) != 1:
                continue
            block = lookup[evidence["block_id"]]
            anchor = bound["char_start"] + matches[0]
            global_anchor = block.get("source_start", 0) + anchor
            positions.add((bound["source_sha256"], global_anchor, global_anchor + len(raw)))
    if not positions:
        bound = [
            bind_evidence(e, lookup)
            for e in result["subject"]["evidence"] + result["outcome_evidence"]
        ]
        positions = {(e["source_sha256"], e["source_start"], e["source_end"]) for e in bound}
    return [list(p) for p in sorted(positions)]


def occurrence_key(result: dict, blocks: list[dict]) -> str:
    return digest(occurrence_positions(result, blocks))
