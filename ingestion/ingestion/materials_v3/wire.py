"""Small model contract; literal evidence and null storage fields come from code.

The source reference catalogue is deterministic and source-bound. It supplies no
material/value association, source role or scientific decision on the model's behalf.
"""

from copy import deepcopy
from functools import lru_cache

from jsonschema import Draft202012Validator

from .contract import CandidateError, digest, schema, validate_candidate
from .locators import source_spans

VERSION = "materials-ner-wire/1.0"


@lru_cache(maxsize=1)
def wire_schema():
    value = deepcopy(schema())
    value.pop("$id", None)
    value["title"] = "Source-reference NER model response"
    value["properties"]["schema_version"] = {"const": VERSION}
    defs = value["$defs"]
    defs["evidence"] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "ref": {"type": "string", "minLength": 1},
            "role": schema()["$defs"]["evidence"]["properties"]["role"],
        },
        "required": ["ref", "role"],
    }
    # Relations remain explicit. Numbers are source values, not converted SI values.
    defs["quantity"] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            **{
                k: deepcopy(schema()["$defs"]["quantity"]["properties"][k])
                for k in ("raw_text", "raw_unit", "relation", "approximate", "uncertainty_raw")
            },
            "numbers": {"type": "array", "items": {"type": "number"}, "minItems": 1, "maxItems": 2},
        },
        "required": ["raw_text", "raw_unit", "relation", "numbers", "approximate"],
    }
    defs["qualifiers"] = {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "key": {"enum": list(schema()["$defs"]["qualifiers"]["properties"])},
                "value": {"type": ["string", "number", "boolean", "null"]},
            },
            "required": ["key", "value"],
        },
    }
    # Omitted optional raw labels mean unreported, never invented source facts.
    for name, required in {
        "subject": ["name_raw", "identity_kind", "evidence"],
        "sample": ["evidence"],
        "seriesPoint": ["scan_variables", "path_direction", "evidence"],
        "event": ["event_kind", "knowledge_origin", "source_role", "evidence"],
    }.items():
        defs[name]["required"] = required
    # Storage constraints referencing the former representations run after expansion.
    for name in ("condition", "property", "result"):
        defs[name].pop("allOf", None)
    Draft202012Validator.check_schema(value)
    return value


def source_catalog(blocks):
    rows, lookup = [], {}
    for block in blocks:
        for span in source_spans(block):
            ref = f"R{len(rows)}"
            row = {
                "ref": ref,
                "block_role": block.get("block_role", "target"),
                "text": block["text"][span["start"] : span["end"]],
                "source_group": block["block_id"],
                "kind": block.get("kind", "text"),
            }
            rows.append(row)
            lookup[ref] = {
                "block_id": block["block_id"],
                "quote": row["text"],
                "quote_start_span_id": span["id"],
                "char_start": None,
                "char_end": None,
                **({"table_id": block["table_id"]} if block.get("table_id") else {}),
            }
    return rows, lookup


def _schema_messages(validator, value, prefix="wire"):
    def details(error):
        if error.validator == "required" and isinstance(error.instance, dict):
            for key in error.validator_value:
                if key not in error.instance:
                    yield f"{prefix}:{'/'.join(map(str, [*error.absolute_path, key]))}:required"
            return
        if error.validator == "anyOf" and error.context and isinstance(error.instance, dict):
            for child in error.context:
                if not (child.validator == "type" and child.absolute_path == error.absolute_path):
                    yield from details(child)
            return
        yield f"{prefix}:{'/'.join(map(str, error.absolute_path))}:{error.validator}"

    return list(dict.fromkeys(m for e in validator.iter_errors(value) for m in details(e)))


def expand_row(row, refs):
    row = deepcopy(row)

    def visit(node):
        if isinstance(node, list):
            return [visit(n) for n in node]
        if not isinstance(node, dict):
            return node
        if "ref" in node:
            if node["ref"] not in refs:
                raise CandidateError([f"unknown_source_reference:{node['ref']}"])
            return {**deepcopy(refs[node["ref"]]), "role": node["role"]}
        if "numbers" in node:
            numbers = node.pop("numbers")
            interval = node["relation"] == "interval"
            if len(numbers) != (2 if interval else 1):
                raise CandidateError(["quantity_relation_number_count_mismatch"])
            node.update(
                value=None if interval else numbers[0],
                lower=numbers[0] if interval else None,
                upper=numbers[1] if interval else None,
            )
            node.setdefault("uncertainty_raw", None)
        if isinstance(node.get("qualifiers"), list):
            items = node["qualifiers"]
            if len({q["key"] for q in items}) != len(items):
                raise CandidateError(["duplicate_qualifier_key"])
            node["qualifiers"] = {q["key"]: q["value"] for q in items}
        return {k: visit(v) for k, v in node.items()}

    row = visit(row)
    for name, fields in {
        "subject": ("formula_raw",),
        "sample": ("label_raw", "form_raw", "preparation_raw"),
        "series_point": (
            "series_label_raw",
            "point_label_raw",
            "step_index_raw",
            "replicate_label_raw",
        ),
        "event": ("method_raw", "calculation_settings_raw", "cited_source_raw"),
    }.items():
        if row.get(name):
            for field in fields:
                row[name].setdefault(field, None)
    return row


def validate_response(value, blocks):
    """Return completely validated rows and explicit quarantine; no field dropping.

    Invalid parent identity, condition, method or one property quarantines its
    entire row. Cross-row unresolved links keep the response atomic on failure.
    A partial response never becomes complete-source or scientific acceptance.
    """
    is_wire = value.get("schema_version") == VERSION if isinstance(value, dict) else False
    original = deepcopy(value)
    _, refs = source_catalog(blocks)
    model_schema = wire_schema() if is_wire else None
    if is_wire:
        root = deepcopy(model_schema)
        root["properties"]["results"]["items"] = {}
        errors = _schema_messages(Draft202012Validator(root), value)
        if errors:
            raise CandidateError(errors)
        validator = Draft202012Validator({"$defs": model_schema["$defs"], "$ref": "#/$defs/result"})
    else:
        # Preserve historical transport support, with the full modern model gate.
        try:
            return validate_candidate(value, blocks, model_output=True), []
        except CandidateError:
            root = deepcopy(schema())
            root["properties"]["results"]["items"] = {}
            errors = _schema_messages(Draft202012Validator(root), value, "schema")
            if errors:
                raise CandidateError(errors) from None
            validator = None
    ids = [r.get("local_id") for r in value["results"] if isinstance(r, dict)]
    if (
        len(ids) != len(value["results"])
        or any(not isinstance(local_id, str) or not local_id for local_id in ids)
        or len(set(ids)) != len(ids)
    ):
        raise CandidateError(["duplicate_or_missing_local_id"])
    accepted, rejected, errors = [], [], []
    for i, row in enumerate(value["results"]):
        try:
            if validator:
                wire_errors = _schema_messages(validator, row)
                if wire_errors:
                    raise CandidateError(wire_errors)
            expanded = expand_row(row, refs) if is_wire else row
            candidate = {
                "schema_version": "materials-ner-candidate/3.0",
                "results": [expanded],
                "unresolved_links": [],
            }
            validate_candidate(candidate, blocks, model_output=True)
            accepted.append(expanded)
        except CandidateError as exc:
            row_errors = [f"row:{i}:{message}" for message in exc.errors]
            errors.extend(row_errors)
            rejected.append(
                {"result_index": i, "local_id": row.get("local_id"), "errors": row_errors}
            )
    links = value["unresolved_links"]
    if is_wire:
        links = expand_row({"unresolved_links": links}, refs)["unresolved_links"]
    if rejected and links:
        raise CandidateError([*errors, "cross_row_links_require_atomic_response"])
    candidate = {
        "schema_version": "materials-ner-candidate/3.0",
        "results": accepted,
        "unresolved_links": links,
    }
    validated = validate_candidate(candidate, blocks, model_output=True)
    validated.update(
        rejected_results=rejected,
        partial=bool(rejected),
        transport={
            "schema_version": original.get("schema_version"),
            "raw_output_sha256": digest(original),
            "source_catalog_sha256": digest(refs),
            "source_quotes_assigned_by_program": is_wire,
        },
    )
    return validated, errors
