"""Closed curator declarations, never inferred scores or scientific authority.

A scientific-cell basis refers to the one selected representative's complete
cell, whose result/evidence references are already bound by the selection hash.
It is not permission to introduce external citations or another action's data.
"""
from __future__ import annotations

import re

CATEGORIES = {"evidence_gap", "execution_constraint", "scientific_hypothesis", "recorded_policy_reason"}
MAX_BASIS_REFS = 8
_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = "\t\n\r \u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"


class DiscoveryMainBarrierError(ValueError):
    """A static failure which never includes submitted source text."""


def require(value):
    if not value:
        raise DiscoveryMainBarrierError("discovery_main_barrier_rejected")


def _object(value, fields):
    require(type(value) is dict and set(value) == set(fields))


def _text(value, maximum):
    require(type(value) is str and 0 < len(value) <= maximum
            and bool(value.strip(_WHITESPACE)) and _CONTROLS.search(value) is None)


def validate_shape(value, *, property_keys):
    """Validate detached JSON synchronously before any database await."""
    require(type(value) is dict)
    if value.get("status") == "not_declared":
        _object(value, {"status"})
        return
    _object(value, {"status", "category", "statement", "rationale", "basis_refs"})
    require(value["status"] == "declared" and type(value["category"]) is str
            and value["category"] in CATEGORIES)
    _text(value["statement"], 500)
    _text(value["rationale"], 2000)
    refs = value["basis_refs"]
    require(type(refs) is list and 1 <= len(refs) <= MAX_BASIS_REFS)
    identities = []
    for ref in refs:
        require(type(ref) is dict and type(ref.get("kind")) is str)
        if ref["kind"] == "scientific_cell":
            _object(ref, {"kind", "property_key"})
            require(type(ref["property_key"]) is str and ref["property_key"] in property_keys)
            key = ref["property_key"]
        else:
            _object(ref, {"kind", "code"})
            require(ref["kind"] in {"assessment_reason", "execution_constraint"})
            # Frozen RPS reasons may include a colon and a case-sensitive
            # dependency identifier; they are not distribution reason codes.
            _text(ref["code"], 200)
            key = ref["code"]
        identities.append(ref["kind"] + ":" + key)
    require(identities == sorted(set(identities)))


def validate_context(value, *, result, cells):
    """Apply category-specific meaning to the exact compiled row, not priors."""
    if value["status"] == "not_declared":
        return
    by_key = {cell["property_key"]: cell for cell in cells}
    require(len(by_key) == len(cells))
    category = value["category"]
    for ref in value["basis_refs"]:
        kind = ref["kind"]
        if category == "recorded_policy_reason":
            require(kind == "assessment_reason" and ref["code"] in result["reason_codes"])
        elif category == "execution_constraint":
            require(kind == "execution_constraint" and ref["code"] in result["execution_constraint_reasons"])
        else:
            require(kind == "scientific_cell" and ref["property_key"] in by_key)
            cell = by_key[ref["property_key"]]
            if category == "evidence_gap":
                require(cell["availability"] in {"unknown", "not_computed", "conflicted"})
            else:
                require(category == "scientific_hypothesis"
                        and cell["availability"] in {"reported", "conflicted"}
                        and any(item["quantity"]["relation"] != "unreported"
                                for item in cell["observations"]))
