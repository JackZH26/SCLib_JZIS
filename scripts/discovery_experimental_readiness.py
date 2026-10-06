"""Replay frozen MDR source expressions into a readiness queue; never fit or admit labels."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
VERSION = "discovery-experimental-readiness/1.0.0"
OUTPUT = "frontend/public/research-pilots/discovery-experimental-readiness-2026-10-06.json"
PINS = {
    "oxide": ("api/services/resources/supercon_mdr_240322_oxide_metadata.json.gz", 2973460,
              "d1fce28506d68732744858570f6e4ee2a8dfef94630c8b3b48d703b95443707c"),
    "manifest": ("api/services/resources/supercon_mdr_240322_manifest.json", 2683,
                 "32a418e39916952c5731ff5f1a9839bd7f7977d183eb242c0c5e213111e1645d"),
    "organic": ("frontend/public/research-pilots/materials-mdr-organic-240322.json", None,
                "5da57e0959d1ea0c081460dbf24a62b2eacfcb0d179ad1bfcbc272bdfd2ea3bd"),
    "organic_source": ("frontend/public/research-pilots/240322_MDR_Organic.txt", 263372,
                       "d116848a90d01e48356ed6cf0bb69035fa863a3a559deac1ef188025bdb3b423"),
}
OXIDE_SOURCE_SHA = "f599ef0040c18521e386f758ee826fe269f67ef369c1a007656035d03ccdfdf6"
OXIDE_DECOMPRESSED_SHA = "a1b7865bd42f7b2a3145d2fdce6b46cd7ef5b400644ff221e59fe5b30ddcffcf"
MAX_INPUT_BYTES = 4_000_000
MAX_DECOMPRESSED_BYTES = 20_000_000
MAX_RECORDS_BYTES = 256 * 1024 * 1024
HEX = re.compile(r"[0-9a-f]{64}\Z")
NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
# These are distinct source-column semantics, not pooled endpoint labels.
CHANNELS = {
    "oxide_metallic": {
        "tc": "recommended_tc_criterion_unspecified",
        "t1": "zero_resistance",
        "t2": "resistive_midpoint",
        "t3": "resistive_r100",
        "tcsus": "susceptibility_criterion_unspecified",
        "tcn": "nontransition_measurement_lower_temperature",
    },
    "organic": {
        "tc": "tc_at_pcrit_or_atmospheric_criterion_unspecified",
        "tcmax": "maximum_tc_under_pressure_criterion_unspecified",
        "tcn": "nontransition_measurement_lower_temperature",
    },
}
COMMON_REASONS = (
    "primary_experimental_origin_not_adjudicated",
    "primary_source_revision_and_occurrence_review_missing",
    "source_publication_currentness_not_checked",
    "sample_state_and_work_identity_unreviewed",
    "source_use_permission_decision_not_supplied",
    "scientific_label_admission_not_supplied",
    "magnetic_field_and_measurement_window_not_bound",
)
METHODS = {str(i) for i in range(1, 15)}
AUTHORITY = {"observed_origin_promoted": False, "scientific_acceptance": False,
             "ml_training_approved": False, "training_executed": False,
             "source_use_permission_granted": False, "canonical_properties_modified": False}


class ReadinessError(ValueError):
    """Bounded error codes; never echo source contents or supplied paths."""


def require(condition, code):
    if not condition:
        raise ReadinessError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def serialize(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _bad_number(_):
    raise ReadinessError("nonfinite_json_number")


def decode(raw):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_bad_number)
    except (ValueError, UnicodeError, RecursionError):
        raise ReadinessError("invalid_json") from None


def read_pinned(root, key):
    relative, size, expected = PINS[key]
    path = root / relative
    require(path.is_file() and path.stat().st_size <= MAX_INPUT_BYTES, "input_missing_or_size_limit")
    raw = path.read_bytes()
    require(len(raw) <= MAX_INPUT_BYTES and (size is None or len(raw) == size)
            and sha(raw) == expected, "frozen_input_pin_mismatch")
    return raw


def load_sources(root=ROOT):
    """Only the two checked-in captures; caller cannot substitute another version."""
    raw = {key: read_pinned(root, key) for key in PINS}
    manifest, organic = decode(raw["manifest"]), decode(raw["organic"])
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw["oxide"])) as stream:
            body = stream.read(MAX_DECOMPRESSED_BYTES + 1)
    except (OSError, EOFError):
        raise ReadinessError("invalid_gzip") from None
    require(len(body) <= MAX_DECOMPRESSED_BYTES and sha(body) == OXIDE_DECOMPRESSED_SHA,
            "decompressed_input_pin_mismatch")
    oxide = decode(body)
    require(oxide["columns"] == manifest["projected_columns"]
            and oxide["source_sha256"] == manifest["source_sha256"] == OXIDE_SOURCE_SHA,
            "oxide_manifest_mismatch")
    organic_lines = raw["organic_source"].splitlines(keepends=True)
    reader = csv.reader(io.StringIO(raw["organic_source"].decode("utf-8"), newline=""), delimiter="\t")
    labels, columns = next(reader), next(reader)
    require(labels == organic["source_labels"] and columns == organic["columns"], "organic_header_mismatch")
    source_rows = [values for values in reader if any(values)]
    require(source_rows == [row["values"] for row in organic["rows"]], "organic_cells_mismatch")
    result = {}
    for table, data, values_key, expected_rows in (
        ("oxide_metallic", oxide, "v", 33458), ("organic", organic, "values", 568)
    ):
        require(len(data["rows"]) == expected_rows, "source_row_count_mismatch")
        require(len(data["columns"]) == len(set(data["columns"]))
                and set(CHANNELS[table]) <= set(data["columns"]), "source_columns_invalid")
        rows, seen = [], set()
        for item in data["rows"]:
            values = item[values_key]
            require(len(values) == len(data["columns"]) and all(type(x) is str for x in values), "source_row_shape_invalid")
            row = dict(zip(data["columns"], values))
            identifier = item["n"] if table == "oxide_metallic" else item["id"]
            digest = item["h"] if table == "oxide_metallic" else item["sha256"]
            start, end = (item["l"], item["e"]) if table == "oxide_metallic" else (item["line_start"], item["line_end"])
            require(identifier == row["num"] and identifier not in seen and HEX.fullmatch(digest)
                    and type(start) is int and type(end) is int and 3 <= start <= end,
                    "source_identity_invalid")
            seen.add(identifier)
            if table == "organic":
                require(end <= len(organic_lines) and sha(b"".join(organic_lines[start - 1:end])) == digest,
                        "organic_physical_line_pin_mismatch")
            rows.append({"values": row, "row_id": identifier, "row_sha256": digest,
                         "line_start": start, "line_end": end})
        result[table] = rows
    return result


def numeric_status(raw):
    require(type(raw) is str and len(raw) <= 512, "numeric_lexeme_invalid")
    if not raw:
        return "not_reported"
    if not NUMBER.fullmatch(raw):
        return "nonpoint_or_unparsed"
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return "nonpoint_or_unparsed"
    if not value.is_finite() or value.copy_abs() > Decimal("1e12"):
        return "nonpoint_or_unparsed"
    return "positive_numeric_lexeme" if value > 0 else "nonpositive_numeric_lexeme"


def expression_readiness(table, field, row):
    """A raw source-column reading; even a complete lexical reading is not a label."""
    require(table in CHANNELS and field in CHANNELS[table] and type(row) is dict, "unsupported_channel")
    require(all(type(value) is str for value in row.values()), "source_values_must_be_strings")
    raw = row.get(field, "")
    status = numeric_status(raw)
    require(status != "not_reported", "empty_expression")
    lower_limit = field == "tcn"
    unit = row.get("utc", "") if table == "oxide_metallic" else ""
    method = row.get("tcmeth", "")
    reasons = list(COMMON_REASONS)
    if status != "positive_numeric_lexeme":
        reasons.append("tc_expression_nonpoint_or_nonpositive_not_negative_label")
    if unit != "K":
        reasons.append("temperature_unit_not_supplied" if not unit else "temperature_unit_requires_review")
    if method not in METHODS:
        reasons.append("measurement_method_not_supplied" if not method else "measurement_method_code_requires_review")
    if field in {"tc", "tcmax", "tcsus"}:
        reasons.append("tc_criterion_not_resolved_by_source_column")
    pressure_field = "pcrit" if table == "organic" and field == "tc" else "pmax" if table == "organic" and field == "tcmax" else None
    pressure = row.get(pressure_field, "") if pressure_field else ""
    pressure_unit = "GPa" if pressure_field == "pcrit" else None
    pressure_status = "not_bound_to_expression"
    if pressure_field and pressure:
        # Header relationship is preserved; no source-scoped reading becomes an admitted state.
        pressure_status = "reported_header_context_requires_state_review"
        if pressure_field == "pmax":
            reasons.append("pressure_unit_not_supplied")
        if numeric_status(pressure) not in {"positive_numeric_lexeme", "nonpositive_numeric_lexeme"} or (
            NUMBER.fullmatch(pressure) and Decimal(pressure) < 0
        ):
            reasons.append("pressure_expression_requires_review")
        reasons.append("pressure_source_state_association_unreviewed")
    else:
        reasons.append("pressure_not_bound_unknown_not_ambient")
    if table == "oxide_metallic" and row.get("pmax"):
        reasons.append("maximum_applied_pressure_is_not_tc_pressure")
    if lower_limit:
        reasons.append("nontransition_temperature_limit_not_tc_or_zero_label")
    return {
        "channel_id": table + ":" + field, "source_field": field,
        "criterion": CHANNELS[table][field],
        "expression_role": "measurement_lower_temperature_not_tc" if lower_limit else "reported_tc_expression",
        "raw_value": raw, "raw_unit": unit or None, "numeric_status": status,
        "unit_status": "reported_kelvin" if unit == "K" else "missing" if not unit else "requires_review",
        "method_raw": method or None,
        "method_status": "recognized_source_code" if method in METHODS else "missing" if not method else "requires_review",
        "pressure_context": {"source_field": pressure_field, "raw_value": pressure or None,
                             "raw_unit": pressure_unit, "status": pressure_status, "explicit_ambient": False},
        "knowledge_origin": "source_reference_not_adjudicated", "label_value_kelvin": None,
        "training_eligible": False, "reason_codes": sorted(set(reasons)),
    }


def iter_readings(sources):
    for table, rows in sources.items():
        for record in rows:
            row = record["values"]
            for field in CHANNELS[table]:
                if not row.get(field):
                    continue
                reading = expression_readiness(table, field, row)
                yield {**reading, "source_table": table,
                       "source_sha256": OXIDE_SOURCE_SHA if table == "oxide_metallic" else PINS["organic_source"][2],
                       **{key: record[key] for key in ("row_id", "row_sha256", "line_start", "line_end")},
                       "reference_code": row["refno"] or None,
                       "raw_composition_or_name": row.get("element") if table == "oxide_metallic" else row.get("fullname"),
                       "sample_identifier_raw": row.get("sample") or None,
                       "isotope_element_raw": row.get("isoel") or None,
                       "family": None, "independent_experiment_id": None}


def build_summary(sources):
    channels = {}
    for table, fields in CHANNELS.items():
        for field, criterion in fields.items():
            channels[table + ":" + field] = {
                "source_table": table, "source_field": field, "criterion": criterion,
                "expression_role": "measurement_lower_temperature_not_tc" if field == "tcn" else "reported_tc_expression",
                "source_rows": len(sources[table]), "expressions": 0,
                "positive_numeric_lexemes": 0, "positive_with_explicit_kelvin": 0,
                "positive_kelvin_and_recognized_method_code": 0,
                "recognized_method_code_expressions": 0,
                "reason_counts": Counter(),
            }
    for reading in iter_readings(sources):
        channel = channels[reading["channel_id"]]
        channel["expressions"] += 1
        positive = reading["numeric_status"] == "positive_numeric_lexeme"
        kelvin = reading["unit_status"] == "reported_kelvin"
        method = reading["method_status"] == "recognized_source_code"
        channel["positive_numeric_lexemes"] += int(positive)
        channel["positive_with_explicit_kelvin"] += int(positive and kelvin)
        channel["positive_kelvin_and_recognized_method_code"] += int(positive and kelvin and method)
        channel["recognized_method_code_expressions"] += int(method)
        channel["reason_counts"].update(reading["reason_codes"])
    for channel in channels.values():
        channel["not_reported_rows"] = channel["source_rows"] - channel["expressions"]
        channel["reason_counts"] = dict(sorted(channel["reason_counts"].items()))
    return {
        "version": VERSION, "dataset_version": "240322",
        "adapter_sha256": sha(Path(__file__).read_bytes()),
        "input_pins": {key: {"path": value[0], "sha256": value[2]} for key, value in PINS.items()},
        "source_license": {"recorded_license": "CC BY 4.0",
                           "attribution": "MDR SuperCon Datasheet Ver.240322, National Institute for Materials Science (NIMS)",
                           "dataset_doi": "https://doi.org/10.48505/nims.4487",
                           "project_ml_use_permission_decision": "not_supplied"},
        "source_inventory": {table: {"rows": len(rows),
            "distinct_nonempty_reference_codes": len({row["values"]["refno"] for row in rows if row["values"]["refno"]})}
            for table, rows in sources.items()},
        "channels": channels,
        "counting_scope": "Source expressions partitioned by table and field; row cohorts overlap across channels. Counts are not independent experiments or admitted labels.",
        "source_families_reviewed": False, "independent_experiment_count": None,
        "training_eligible_labels_established": False, "training_eligible_label_count": None,
        "readiness": "source_review_required", "model_score": None, "model_uncertainty": None,
        "resource_budget": None, "authority": dict(AUTHORITY),
        "next_actions": [
            "Review exact source versions, expression locators, sample/state identity and publication status.",
            "Choose one Tc criterion and retain explicit pressure, field and measurement-window evidence.",
            "Review source-use permissions and scientific labels through the existing admission workflow.",
            "Freeze work/sample/structure groups and family holdouts before preprocessing or fitting.",
        ],
    }


def write_new(path, data):
    """Explicit outputs only; never overwrite a frozen source or an older report."""
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def write_readings(path, sources):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        total = 0
        with os.fdopen(fd, "wb") as stream:
            for reading in iter_readings(sources):
                raw = (json.dumps(reading, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()
                total += len(raw)
                require(total <= MAX_RECORDS_BYTES, "record_output_size_limit")
                stream.write(raw)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Local checkout containing the exact pinned inputs")
    parser.add_argument("--output", type=Path, help="Create a new aggregate JSON (existing files are protected)")
    parser.add_argument("--records-output", type=Path, help="Optional private JSONL of source-bound readings; never training labels")
    parser.add_argument("--check", action="store_true", help="Compare the aggregate with the checked-in version; no writes")
    args = parser.parse_args(argv)
    if args.check and (args.output or args.records_output):
        parser.error("--check cannot write outputs")
    try:
        sources = load_sources(args.root)
        summary = serialize(build_summary(sources))
        if args.check:
            require((args.root / OUTPUT).read_bytes() == summary, "aggregate_replay_mismatch")
        if args.output:
            write_new(args.output, summary)
        if args.records_output:
            write_readings(args.records_output, sources)
        print(json.dumps({"version": VERSION, "summary_sha256": sha(summary),
                          "source_rows": {table: len(rows) for table, rows in sources.items()},
                          "replay_checked": args.check, "training_executed": False}))
        return 0
    except (ReadinessError, OSError, KeyError, TypeError) as error:
        code = str(error) if isinstance(error, ReadinessError) else "local_input_or_output_unavailable"
        print(json.dumps({"status": "failed", "reason_code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
