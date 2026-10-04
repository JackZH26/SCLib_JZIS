"""Opt-in private literal-field intake; never normalizes printed amounts.

The frozen 2.0 parsed-number contract remains separate. This profile retains
one local source window and independently hashed character selections. It
establishes neither field interpretation nor a material/sample association.
"""

from __future__ import annotations

import base64
import binascii
import hashlib

from services import source_expression_contract_v2 as frozen
from services.material_literal_field_contract import (
    FIELDS,
    PROFILE,
    QUALIFIERS,
)
from services.material_literal_field_contract import REGISTRY_SHA256 as REGISTRY_SHA256
from services.research_release_manifest import canonical, digest

VERSION = "source-expression-package/2.1.0"
MAX_TEXT_BYTES = frozen.MAX_TEXT_BYTES
MAX_EXPRESSIONS = frozen.MAX_EXPRESSIONS
MAX_PACKAGE_BYTES = frozen.MAX_PACKAGE_BYTES
MAX_PROJECTION_BYTES = frozen.MAX_PROJECTION_BYTES
MAX_WINDOW_CHARACTERS = 4096
MAX_VALUE_CHARACTERS = 1200
MAX_UNIT_CHARACTERS = 120
MAX_CUE_CHARACTERS = 200
MAX_UNCERTAINTY_CHARACTERS = 200
MAX_TOKEN_GAP = 128
ROLES = frozen.ROLES
SOURCE_KEYS = frozen.SOURCE_KEYS
LOCATOR_KEYS = frozen.LOCATOR_KEYS
EXPRESSION_KEYS = frozen.EXPRESSION_KEYS | {
    "profile", "field_role", "cue_spans", "uncertainty_spans", "qualifiers"
}
PACKAGE_KEYS = {
    "version", "profile", "source", "source_text_base64",
    "source_content_sha256", "expressions",
}
SourceExpressionContractError = frozen.SourceExpressionContractError
PreparedPackage = frozen.PreparedPackage
require = frozen.require
closed = frozen.closed
text = frozen.text
sha = frozen.sha
spans = frozen.spans
source_metadata = frozen.source_metadata


def _selection(source_text, selections, *, limit, optional=False):
    require(
        type(selections) is list and len(selections) in ((0, 1) if optional else (1,)),
        "contiguous_literal_span_required",
    )
    return spans(source_text, selections, optional=optional, limit=limit)


def _span_projection(selection):
    if selection is None:
        return None
    return {
        "char_start": selection["start"],
        "char_end": selection["end"],
        "text_sha256": selection["sha256"],
    }


def _inside(selection, window):
    return window["start"] <= selection["start"] < selection["end"] <= window["end"]


def project(source, source_text, request):
    closed(request, EXPRESSION_KEYS)
    field = request["field_id"]
    require(
        request["profile"] == PROFILE
        and type(field) is str
        and field in FIELDS
        and request["field_role"] == FIELDS[field]
        and type(request["source_role"]) is str
        and request["source_role"] in ROLES
        and type(request["knowledge_origin"]) is str
        and request["knowledge_origin"] in {"Observed", "Computed", "unknown"},
        "closed_literal_field_profile_role_required",
    )
    require(type(request["conditions"]) is list and not request["conditions"],
            "literal_conditions_must_be_empty")
    qualifiers = request["qualifiers"]
    require(
        type(qualifiers) is list
        and len(qualifiers) <= len(QUALIFIERS)
        and all(type(value) is str and value in QUALIFIERS for value in qualifiers)
        and len(set(qualifiers)) == len(qualifiers),
        "closed_literal_qualifiers_required",
    )
    closed(request["window"], {"id", "label_spans"})
    raw_window = _selection(source_text, request["window"]["label_spans"],
                            limit=MAX_WINDOW_CHARACTERS)
    window_selection = request["window"]["label_spans"][0]
    window = {"id": text(request["window"]["id"]), "raw_label": raw_window}
    closed(request["subject"], {"formula_spans", "sample_label_spans"})
    formula = _selection(source_text, request["subject"]["formula_spans"], limit=200)
    subject = {
        "formula": formula,
        "sample_label": spans(source_text, request["subject"]["sample_label_spans"],
                              optional=True, limit=200) or None,
        "formula_scope": "retained_formula_span",
    }
    raw_amount = _selection(source_text, request["value_spans"], limit=MAX_VALUE_CHARACTERS)
    printed_unit = _selection(source_text, request["unit_spans"],
                              optional=True, limit=MAX_UNIT_CHARACTERS)
    cue = _selection(source_text, request["cue_spans"], limit=MAX_CUE_CHARACTERS)
    uncertainty = _selection(source_text, request["uncertainty_spans"],
                             optional=True, limit=MAX_UNCERTAINTY_CHARACTERS)
    value_selection = request["value_spans"][0]
    unit_selection = request["unit_spans"][0] if request["unit_spans"] else None
    cue_selection = request["cue_spans"][0]
    uncertainty_selection = (request["uncertainty_spans"][0]
                             if request["uncertainty_spans"] else None)
    for selection in (
        request["subject"]["formula_spans"][0], value_selection,
        unit_selection, cue_selection, uncertainty_selection,
    ):
        require(selection is None or _inside(selection, window_selection),
                "literal_selection_outside_window")
    require(
        cue_selection["end"] <= value_selection["start"]
        and value_selection["start"] - cue_selection["end"] <= MAX_TOKEN_GAP,
        "literal_cue_before_amount_required",
    )
    require(
        unit_selection is None
        or value_selection["end"] <= unit_selection["start"]
        and unit_selection["start"] - value_selection["end"] <= MAX_TOKEN_GAP,
        "literal_unit_after_amount_required",
    )
    require(
        uncertainty_selection is None or _inside(uncertainty_selection, value_selection),
        "literal_uncertainty_inside_amount_required",
    )
    end = unit_selection["end"] if unit_selection else value_selection["end"]
    value = {
        "status": "raw_literal",
        "raw_value": source_text[value_selection["start"]:end].strip(),
        "raw_amount": raw_amount,
        "raw_unit": printed_unit.strip() if unit_selection else None,
        "raw_uncertainty": uncertainty if uncertainty_selection else None,
        "quantity": None,
        "normalization": "none",
        "field_cue": cue,
        "role": FIELDS[field],
        "qualifiers": list(qualifiers),
        "value_span": _span_projection(value_selection),
        "unit_span": _span_projection(unit_selection),
        "cue_span": _span_projection(cue_selection),
        "uncertainty_span": _span_projection(uncertainty_selection),
    }
    model = spans(source_text, request["model_spans"], optional=True, limit=500) or None
    closed(request["origin_basis"], {"statement", "spans"})
    text(request["origin_basis"]["statement"], 500, nullable=True)
    basis = {
        "statement": request["origin_basis"]["statement"],
        "retained_text": spans(source_text, request["origin_basis"]["spans"],
                               optional=True, limit=1000) or None,
        "verification": "declared_inspection_basis",
    }
    closed(request["locator"], LOCATOR_KEYS)
    for key, val in request["locator"].items():
        if key in {"page", "slide", "row", "column"}:
            require(val is None or type(val) is int and 1 <= val <= 100000,
                    "bounded_numeric_locator_required")
        else:
            text(val, 200, nullable=True)
    parent = request["predecessor"]
    if parent is not None:
        closed(parent, {"revision_id", "record_sha256", "revision_number"})
        from services.source_property_pending import identifier

        identifier(parent["revision_id"])
        sha(parent["record_sha256"])
        require(type(parent["revision_number"]) is int and 1 <= parent["revision_number"] <= 10000,
                "bounded_revision_required")
    identity = {
        "source_id": source["source_id"], "field_id": field,
        "profile": PROFILE, "field_role": FIELDS[field], "subject": subject,
        "window": window, "source_role": request["source_role"], "model": model,
    }
    return {
        **identity,
        "expression_key": digest(identity),
        "knowledge_origin": request["knowledge_origin"],
        "origin_basis": basis,
        "value": value,
        "conditions": [],
        "locator": request["locator"],
        "status": "pending",
        "selected_result_association": "unestablished",
        "sample_identity_established": False,
        "phase_identity_established": False,
        "field_interpretation_reviewed": False,
        "scientific_acceptance": False,
        "canonical_promotions": 0,
        "public_content_release": False,
        "ml_training_approved": False,
        "missingness_scope": "not_supplied_in_retained_expression_is_not_source_absence",
    }


def compile_package(package):
    closed(package, PACKAGE_KEYS)
    require(package["version"] == VERSION and package["profile"] == PROFILE,
            "supported_literal_package_profile_required")
    source_metadata(package["source"])
    encoded = package["source_text_base64"]
    require(type(encoded) is str and len(encoded) <= 4 * ((MAX_TEXT_BYTES + 2) // 3),
            "bounded_source_bytes_required")
    try:
        raw = base64.b64decode(encoded, validate=True)
        source_text = raw.decode("utf-8")
    except (ValueError, binascii.Error, UnicodeError):
        raise SourceExpressionContractError("canonical_utf8_base64_required") from None
    require(
        base64.b64encode(raw).decode("ascii") == encoded
        and 1 <= len(raw) <= MAX_TEXT_BYTES and "\x00" not in source_text,
        "canonical_utf8_base64_required",
    )
    require(hashlib.sha256(raw).hexdigest() == sha(package["source_content_sha256"]),
            "source_content_hash_mismatch")
    require(type(package["expressions"]) is list
            and 1 <= len(package["expressions"]) <= MAX_EXPRESSIONS,
            "bounded_expressions_required")
    projections = [project(package["source"], source_text, entry)
                   for entry in package["expressions"]]
    require(all(len(canonical(projection)) <= MAX_PROJECTION_BYTES for projection in projections),
            "bounded_projection_bytes_required")
    require(len({projection["expression_key"] for projection in projections}) == len(projections),
            "distinct_expression_identity_required")
    retained = {key: value for key, value in package.items() if key != "source_text_base64"}
    require(len(canonical(retained)) <= MAX_PACKAGE_BYTES, "bounded_package_bytes_required")
    return PreparedPackage(source_text, retained, digest(retained), projections)
