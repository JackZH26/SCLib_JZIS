"""Closed private primary-fragment intake; faithful transcription, not science.

The retained UTF-8 fragment is verified independently of the declared parent.
Nothing fetches URLs, executes XML, establishes a sample or grants source rights.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from services.research_release_manifest import canonical, digest

VERSION = "source-expression-package/2.0.0"
MAX_TEXT_BYTES = 131072
MAX_EXPRESSIONS = 20
MAX_PACKAGE_BYTES = 131072
MAX_PROJECTION_BYTES = 32768
NUMBER = r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?"
QUANTITY_RE = re.compile(rf"^(~|≈)?\s*({NUMBER})(?:\s*(?:±|\+/-)\s*({NUMBER}))?\s*([^0-9\s].*)?$")
UNIT_MAPS = {
    "K": {"K": 1.0, "mK": 0.001},
    "GPa": {"GPa": 1.0, "MPa": 0.001, "kPa": 0.000001, "Pa": 0.000000001},
    "T": {"T": 1.0, "mT": 0.001},
    "nm": {"nm": 1.0, "Å": 0.1, "angstrom": 0.1},
    "angstrom": {"angstrom": 1.0, "Å": 1.0, "nm": 10.0},
    "1": {"1": 1.0, "dimensionless": 1.0},
}
FIELDS = {
    "tc_kelvin": "K",
    "pressure_gpa": "GPa",
    "measurement_temperature_k": "K",
    "magnetic_field_t": "T",
    "hc2_tesla": "T",
    "lambda_london_nm": "nm",
    "lambda_eph": "1",
    "omega_log_k": "K",
    "mu_star": "1",
    "lattice_a": "angstrom",
    "lattice_b": "angstrom",
    "lattice_c": "angstrom",
    "method_statement": None,
    "sample_form_statement": None,
    "structure_statement": None,
    "classification_statement": None,
}
ROLES = ("source_reported", "source_fitted", "source_model_estimate", "source_proposed")
CONDITION_FIELDS = (
    "pressure_gpa",
    "measurement_temperature_k",
    "magnetic_field_t",
    "method_statement",
    "criterion_statement",
    "window_statement",
)
CONDITION_ROLES = ("reported_result_condition", "study_extent", "synthesis_condition", "fit_window")
SOURCE_KEYS = {
    "source_id",
    "url",
    "kind",
    "content_kind",
    "revision",
    "revision_status",
    "original_parent_sha256",
    "parent_hash_status",
    "rights_status",
    "currentness",
    "captured_at",
}
EXPRESSION_KEYS = {
    "field_id",
    "subject",
    "window",
    "source_role",
    "knowledge_origin",
    "origin_basis",
    "model_spans",
    "value_spans",
    "unit_spans",
    "conditions",
    "locator",
    "predecessor",
}
LOCATOR_KEYS = {"page", "slide", "table", "row", "column", "section", "member"}
REGISTRY_SHA256 = digest(
    {
        "version": VERSION,
        "fields": FIELDS,
        "units": UNIT_MAPS,
        "roles": list(ROLES),
        "condition_fields": list(CONDITION_FIELDS),
        "condition_roles": list(CONDITION_ROLES),
    }
)


class SourceExpressionContractError(ValueError):
    """Static rejection code; no private source data in errors."""


def require(ok, code):
    if not ok:
        raise SourceExpressionContractError(code)


def closed(value, keys):
    require(type(value) is dict and set(value) == set(keys), "closed_object_required")


def text(value, limit=160, *, nullable=False):
    if nullable and value is None:
        return value
    require(
        type(value) is str
        and 0 < len(value) <= limit
        and value == value.strip()
        and not any(ord(c) < 32 for c in value),
        "bounded_text_required",
    )
    return value


def sha(value):
    require(type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value), "sha256_required")
    return value


def source_metadata(source):
    closed(source, SOURCE_KEYS)
    require(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}", text(source["source_id"])),
        "source_identity_required",
    )
    raw_url = text(source["url"], 2048)
    url = urlsplit(raw_url)
    require(
        url.scheme == "https"
        and url.hostname
        and "." in url.hostname
        and not url.username
        and not url.password
        and url.port in {None, 443}
        and not url.fragment,
        "public_https_metadata_required",
    )
    require(
        re.fullmatch(r"https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(:443)?(/[^\s#]*)?", raw_url),
        "public_https_metadata_required",
    )
    require(
        type(source["kind"]) is str
        and type(source["content_kind"]) is str
        and source["kind"]
        in {"primary_paper", "conference_presentation", "supplement", "crystal_reference"}
        and source["content_kind"] in {"plain_text", "xml_text"},
        "closed_source_kind_required",
    )
    for value_key, status_key in (
        ("revision", "revision_status"),
        ("original_parent_sha256", "parent_hash_status"),
    ):
        require(
            type(source[status_key]) is str
            and source[status_key] in {"declared", "unresolved"}
            and (source[value_key] is None) == (source[status_key] == "unresolved"),
            "declared_source_scope_required",
        )
    text(source["revision"], nullable=True)
    if source["original_parent_sha256"] is not None:
        sha(source["original_parent_sha256"])
    require(
        type(source["rights_status"]) is str
        and type(source["currentness"]) is str
        and source["rights_status"] in {"unresolved", "declared_private_inspection", "restricted"}
        and source["currentness"] in {"unresolved", "declared_current", "historical"},
        "declared_rights_currentness_required",
    )
    raw_stamp = text(source["captured_at"], 40)
    require(
        re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[-+][0-9]{2}:[0-9]{2})",
            raw_stamp,
        ),
        "timezone_timestamp_required",
    )
    stamp = datetime.fromisoformat(raw_stamp.replace("Z", "+00:00"))
    require(stamp.tzinfo is not None, "timezone_timestamp_required")


def spans(source_text, values, *, optional=False, limit=2048):
    require(
        type(values) is list and (0 if optional else 1) <= len(values) <= 8,
        "bounded_spans_required",
    )
    parts = []
    previous_end = -1
    for span in values:
        closed(span, {"start", "end", "sha256"})
        start, end = span["start"], span["end"]
        require(
            type(start) is int
            and type(end) is int
            and 0 <= start < end <= len(source_text)
            and end - start <= limit
            and start >= previous_end,
            "exact_ordered_character_span_required",
        )
        previous_end = end
        part = source_text[start:end]
        require(
            hashlib.sha256(part.encode("utf-8")).hexdigest() == sha(span["sha256"]),
            "span_content_hash_mismatch",
        )
        parts.append(part)
    joined = "".join(parts)
    require(len(joined) <= limit, "bounded_joined_span_required")
    return joined


def complete_token(source_text, selection, content_kind, *, unit=False):
    """Narrow adjacent printed-token check, never an XML or scientific parser."""
    start, end = selection["start"], selection["end"]
    left, right = source_text[max(0, start - 160) : start], source_text[end : end + 160]
    if content_kind == "xml_text":
        # Only bounded adjacent text-run tags may connect printed token parts.
        # Paragraph/cell/other tags are boundaries, not inferred associations.
        for side in ("left", "right"):
            context = left if side == "left" else right
            for _ in range(16):
                match = (
                    re.search(r"</?([A-Za-z_][A-Za-z0-9_.:-]*)[^<>]*>$", context)
                    if side == "left"
                    else re.match(r"</?([A-Za-z_][A-Za-z0-9_.:-]*)[^<>]*>", context)
                )
                if not match:
                    break
                if match[1].split(":")[-1] not in {"t", "r", "rPr"}:
                    context = ""
                    break
                context = context[: match.start()] if side == "left" else context[match.end() :]
            if side == "left":
                left = context
            else:
                right = context
    prior, following = left[-1:] or "", right[:1] or ""
    if unit:

        def unit_char(char):
            return bool(
                char
                and (char.isalpha() or char in ".*/^·_-" or ord(char) > 127 and not char.isspace())
            )

        # A number immediately before a letter unit is normal (e.g. 66K).
        return not (
            unit_char(prior)
            or unit_char(following)
            or following.isdigit()
            or selection["end"] > selection["start"]
            and source_text[start].isdigit()
            and prior.isdigit()
        )
    return not (
        prior
        and (prior.isalnum() or prior in ".+-−±" or ord(prior) > 127 and not prior.isspace())
        or re.search(r"(?:[+\-−<>≤≥~≈±≲≳]|[<>]=)\s*$", left)
        or following
        and (
            following.isalnum()
            or following in "+-−/*^·"
            or ord(following) > 127
            and not following.isspace()
            or following == "."
            and source_text[end - 1].isdigit()
        )
        or re.match(r"\s*(?:±|\+/-|\([0-9]+(?:\.[0-9]+)?\))", right)
        or re.match(r"\s*[×·*]\s*10(?:\s*\^|[⁰¹²³⁴⁵⁶⁷⁸⁹])", right)
        or following == ","
        and len(right) > 1
        and right[1].isdigit()
        or prior == ","
        and len(left) > 1
        and left[-2].isdigit()
    )


def quantity(raw, explicit_unit, field, *, value_complete=True, unit_complete=True):
    """Small versioned scalar grammar; no unit or physical-state inference."""
    target = FIELDS[field]
    result = {
        "raw_value": raw,
        "raw_unit": explicit_unit or None,
        "value": None,
        "unit": None,
        "uncertainty": None,
        "uncertainty_interpretation": None,
        "approximate": False,
        "relation": "unresolved",
        "status": "value_requires_review",
        "unit_basis": "unresolved",
    }
    if not value_complete:
        return result
    match = QUANTITY_RE.fullmatch(raw.strip().replace("−", "-"))
    if not match:
        return result
    inline = (match[4] or "").strip()
    unit = inline or explicit_unit or ""
    result["raw_unit"] = explicit_unit or inline or None
    result["approximate"] = bool(match[1])
    if not unit:
        result["status"] = "unit_not_supplied"
        return result
    units = UNIT_MAPS[target]
    if (
        not unit_complete
        or unit not in units
        or inline
        and explicit_unit
        and (explicit_unit not in units or units[inline] != units[explicit_unit])
    ):
        result["status"] = "unit_requires_review"
        return result
    try:
        value = float(match[2]) * units[unit]
        uncertainty = None if match[3] is None else float(match[3]) * units[unit]
        if (
            not math.isfinite(value)
            or uncertainty is not None
            and (not math.isfinite(uncertainty) or uncertainty < 0)
        ):
            return result
        # A nonzero printed number that underflows must not become a reported zero.
        if value == 0 and Decimal(match[2]) != 0 or uncertainty == 0 and Decimal(match[3]) != 0:
            return result
    except (OverflowError, ValueError, InvalidOperation):
        return result
    result.update(
        value=value,
        unit=target,
        uncertainty=uncertainty,
        uncertainty_interpretation=None if uncertainty is None else "unspecified",
        relation="exact",
        status="parsed",
        unit_basis="source_printed",
    )
    return result


def project(source, source_text, request):
    closed(request, EXPRESSION_KEYS)
    field = request["field_id"]
    require(
        type(field) is str
        and type(request["knowledge_origin"]) is str
        and field in FIELDS
        and request["source_role"] in ROLES
        and request["knowledge_origin"] in {"Observed", "Computed", "unknown"},
        "closed_field_role_required",
    )
    closed(request["subject"], {"formula_spans", "sample_label_spans"})
    subject = {
        "formula": spans(source_text, request["subject"]["formula_spans"], limit=200),
        "sample_label": spans(
            source_text, request["subject"]["sample_label_spans"], optional=True, limit=200
        )
        or None,
        "formula_scope": "retained_formula_span"
        if len(request["subject"]["formula_spans"]) == 1
        else "declared_formula_span_assembly",
    }
    closed(request["window"], {"id", "label_spans"})
    window = {
        "id": text(request["window"]["id"]),
        "raw_label": spans(source_text, request["window"]["label_spans"], optional=True, limit=500)
        or None,
    }
    model = spans(source_text, request["model_spans"], optional=True, limit=500) or None
    closed(request["origin_basis"], {"statement", "spans"})
    text(request["origin_basis"]["statement"], 500, nullable=True)
    basis = {
        "statement": request["origin_basis"]["statement"],
        "retained_text": spans(
            source_text, request["origin_basis"]["spans"], optional=True, limit=1000
        )
        or None,
        "verification": "declared_inspection_basis",
    }
    require(
        type(request["value_spans"]) is list
        and len(request["value_spans"]) == 1
        and type(request["unit_spans"]) is list
        and len(request["unit_spans"]) <= 1,
        "contiguous_value_and_unit_required",
    )
    raw = spans(source_text, request["value_spans"], limit=1200)
    unit = spans(source_text, request["unit_spans"], optional=True, limit=40) or None
    value = (
        quantity(
            raw,
            unit,
            field,
            value_complete=complete_token(
                source_text, request["value_spans"][0], source["content_kind"]
            ),
            unit_complete=not request["unit_spans"]
            or complete_token(
                source_text, request["unit_spans"][0], source["content_kind"], unit=True
            ),
        )
        if FIELDS[field]
        else {"raw_value": raw, "status": "source_statement"}
    )
    require(
        FIELDS[field] is not None or not request["unit_spans"], "statement_has_no_quantity_unit"
    )
    require(
        type(request["conditions"]) is list and len(request["conditions"]) <= 8,
        "bounded_conditions_required",
    )
    conditions = []
    for item in request["conditions"]:
        closed(item, {"field_id", "role", "value_spans", "unit_spans"})
        require(
            type(item["value_spans"]) is list
            and len(item["value_spans"]) == 1
            and type(item["unit_spans"]) is list
            and len(item["unit_spans"]) <= 1,
            "contiguous_value_and_unit_required",
        )
        require(
            item["field_id"] in CONDITION_FIELDS and item["role"] in CONDITION_ROLES,
            "closed_condition_required",
        )
        condition_raw = spans(source_text, item["value_spans"], limit=1200)
        condition_unit = spans(source_text, item["unit_spans"], optional=True, limit=40) or None
        numeric = FIELDS.get(item["field_id"]) is not None
        require(numeric or not item["unit_spans"], "statement_has_no_quantity_unit")
        conditions.append(
            {
                "field_id": item["field_id"],
                "role": item["role"],
                "value": quantity(
                    condition_raw,
                    condition_unit,
                    item["field_id"],
                    value_complete=complete_token(
                        source_text, item["value_spans"][0], source["content_kind"]
                    ),
                    unit_complete=not item["unit_spans"]
                    or complete_token(
                        source_text, item["unit_spans"][0], source["content_kind"], unit=True
                    ),
                )
                if numeric
                else {"raw_value": condition_raw, "status": "source_statement"},
            }
        )
    closed(request["locator"], LOCATOR_KEYS)
    for key, val in request["locator"].items():
        if key in {"page", "slide", "row", "column"}:
            require(
                val is None or type(val) is int and 1 <= val <= 100000,
                "bounded_numeric_locator_required",
            )
        else:
            text(val, 200, nullable=True)
    parent = request["predecessor"]
    if parent is not None:
        closed(parent, {"revision_id", "record_sha256", "revision_number"})
        from services.source_property_pending import identifier

        identifier(parent["revision_id"])
        sha(parent["record_sha256"])
        require(
            type(parent["revision_number"]) is int and 1 <= parent["revision_number"] <= 10000,
            "bounded_revision_required",
        )
    identity = {
        "source_id": source["source_id"],
        "field_id": field,
        "subject": subject,
        "window": window,
        "source_role": request["source_role"],
        "model": model,
    }
    return {
        **identity,
        "expression_key": digest(identity),
        "knowledge_origin": request["knowledge_origin"],
        "origin_basis": basis,
        "value": value,
        "conditions": conditions,
        "locator": request["locator"],
        "status": "pending",
        "selected_result_association": "unestablished",
        "sample_identity_established": False,
        "phase_identity_established": False,
        "scientific_acceptance": False,
        "canonical_promotions": 0,
        "missingness_scope": "not_supplied_in_retained_expression_is_not_source_absence",
    }


@dataclass(frozen=True)
class PreparedPackage:
    source_text: str
    package: dict
    package_sha256: str
    projections: list[dict]


def compile_package(package):
    closed(
        package, {"version", "source", "source_text_base64", "source_content_sha256", "expressions"}
    )
    require(package["version"] == VERSION, "supported_package_version_required")
    source_metadata(package["source"])
    encoded = package["source_text_base64"]
    require(
        type(encoded) is str and len(encoded) <= 4 * ((MAX_TEXT_BYTES + 2) // 3),
        "bounded_source_bytes_required",
    )
    try:
        raw = base64.b64decode(encoded, validate=True)
        source_text = raw.decode("utf-8")
    except (ValueError, binascii.Error, UnicodeError):
        raise SourceExpressionContractError("canonical_utf8_base64_required") from None
    require(
        base64.b64encode(raw).decode("ascii") == encoded
        and 1 <= len(raw) <= MAX_TEXT_BYTES
        and "\x00" not in source_text,
        "canonical_utf8_base64_required",
    )
    require(
        hashlib.sha256(raw).hexdigest() == sha(package["source_content_sha256"]),
        "source_content_hash_mismatch",
    )
    require(
        type(package["expressions"]) is list
        and 1 <= len(package["expressions"]) <= MAX_EXPRESSIONS,
        "bounded_expressions_required",
    )
    projections = [
        project(package["source"], source_text, value) for value in package["expressions"]
    ]
    require(
        all(len(canonical(p)) <= MAX_PROJECTION_BYTES for p in projections),
        "bounded_projection_bytes_required",
    )
    require(
        len({p["expression_key"] for p in projections}) == len(projections),
        "distinct_expression_identity_required",
    )
    retained = {key: val for key, val in package.items() if key != "source_text_base64"}
    require(len(canonical(retained)) <= MAX_PACKAGE_BYTES, "bounded_package_bytes_required")
    return PreparedPackage(source_text, retained, digest(retained), projections)
