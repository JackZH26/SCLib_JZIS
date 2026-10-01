"""Calculated, composition-matched references kept outside sample properties.

An external composition match does not establish phase, state, sample identity,
superconductivity or a usable ML row. No canonical material data is written.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from redis.exceptions import RedisError

from services._composition.formula_enrichment import enrich_formula, enrich_material_composition
from services.materials_project import MaterialsProjectClient
from services.rate_limit import get_redis

VERSION = "material-external-references/1.0.0"
FIELDS = ("material_id", "formula_pretty", "symmetry", "structure", "density",
          "volume", "nsites", "band_gap", "is_metal", "energy_above_hull",
          "formation_energy_per_atom", "is_stable", "origins", "last_updated")
MAX_CANDIDATES = 20
MAX_BYTES = 512 * 1024
CACHE_TTL = 86400
_locks: dict[str, asyncio.Lock] = {}


def _number(value: Any) -> float | None:
    return float(value) if type(value) in {int, float} and math.isfinite(value) else None


def _text(value: Any, limit=160) -> str | None:
    return value[:limit] if type(value) is str and value.strip() else None


def _base(formula, status, reason=None):
    return {"version": VERSION, "provider": "Materials Project", "formula": formula,
            "status": status, "reason": reason, "candidates": [], "truncated": False,
            "scientific_acceptance": False, "sample_identity_established": False,
            "retrieved_at": None,
            "scope": "calculated_composition_references_not_selected_material_properties",
            "reference_conditions": "MP standard thermodynamic references use 0 K and 0 atm; correspondence to the reported sample and pressure is unestablished.",
            "methodology_url": "https://docs.materialsproject.org/methodology/materials-methodology/thermodynamic-stability/phase-diagrams-pds"}


def external_query_formula(formula: str, *, current_records: list[dict[str, Any]] | None = None) -> str | None:
    # A normalized catalogue alias must not erase a source's occupancy,
    # isotope, charge, interface or dopant notation. Only the current eligible
    # source partition may supply this guard.
    parsed = enrich_material_composition({"formula": formula, "records": current_records or []})
    # Isotopes, interfaces, aliases and variable compositions remain unresolved.
    # Do not drop a dopant or use a parent composition as a surrogate.
    if parsed["composition_status"] != "exact":
        return None
    for record in current_records or []:
        if type(record) is not dict:
            return None
        extraction = record.get("raw_extraction")
        extraction = extraction if type(extraction) is dict else {}
        # Prefer the retained original spelling over a grouping/display alias.
        # Absent source spellings permit a composition-only catalogue lookup;
        # an explicit unresolved or conflicting spelling cannot be stripped.
        source_formula = next((value for value in (
            record.get("formula_raw"), extraction.get("formula_raw"),
            extraction.get("formula"), record.get("formula"),
        ) if value is not None and value != ""), None)
        if source_formula is None:
            continue
        source = enrich_formula(source_formula)
        if (source["composition_status"] != "exact"
                or source["atomic_fractions"] != parsed["atomic_fractions"]):
            return None
    return parsed["formula_reduced"]


def project_external_references(formula: str, rows: list, *, retrieved_at: str) -> dict:
    target = enrich_formula(formula)
    result = _base(formula, "available")
    result["retrieved_at"] = retrieved_at
    if target["composition_status"] != "exact":
        return _base(formula, "not_applicable", "composition_requires_resolution")
    result["truncated"] = len(rows) > MAX_CANDIDATES
    candidates = []
    seen = set()
    for row in rows[:MAX_CANDIDATES]:
        if type(row) is not dict or row.get("deprecated") is True:
            continue
        identifier = row.get("material_id")
        if type(identifier) is not str or not re.fullmatch(r"mp-[a-z0-9]{1,40}", identifier) or identifier in seen:
            continue
        composition = enrich_formula(row.get("formula_pretty", ""))
        if (composition["composition_status"] != "exact"
                or composition["atomic_fractions"] != target["atomic_fractions"]):
            continue
        seen.add(identifier)
        symmetry = row.get("symmetry") if type(row.get("symmetry")) is dict else {}
        structure = row.get("structure") if type(row.get("structure")) is dict else {}
        lattice = structure.get("lattice") if type(structure.get("lattice")) is dict else {}
        origins = []
        for origin in row.get("origins", []) if type(row.get("origins")) is list else []:
            if type(origin) is dict and _text(origin.get("name")) and _text(origin.get("task_id")):
                origins.append({"property": _text(origin["name"]), "task_id": _text(origin["task_id"]),
                                "last_updated": _text(origin.get("last_updated"))})
        # Only allowlisted public metadata; no coordinates, private keys or Tc.
        candidates.append({
            "id": identifier, "url": f"https://next-gen.materialsproject.org/materials/{identifier}",
            "formula": row["formula_pretty"], "match_level": "fixed_composition_only",
            "knowledge_origin": "Computed", "sample_identity_established": False,
            "phase_identity_established": False, "last_updated": _text(row.get("last_updated")),
            "source_snapshot_sha256": hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest(),
            "space_group": _text(symmetry.get("symbol")), "space_group_number": _number(symmetry.get("number")),
            "crystal_system": _text(symmetry.get("crystal_system")),
            "lattice": {key: value for key in ("a", "b", "c", "alpha", "beta", "gamma")
                        if (value := _number(lattice.get(key))) is not None},
            "density_g_cm3": _number(row.get("density")), "volume_angstrom3": _number(row.get("volume")),
            "nsites": _number(row.get("nsites")), "band_gap_ev": _number(row.get("band_gap")),
            "is_metal": row.get("is_metal") if type(row.get("is_metal")) is bool else None,
            "energy_above_hull_ev_atom": _number(row.get("energy_above_hull")),
            "formation_energy_ev_atom": _number(row.get("formation_energy_per_atom")),
            "is_stable": row.get("is_stable") if type(row.get("is_stable")) is bool else None,
            "origins": origins[:20], "functional": "Not resolved from summary; inspect source tasks",
        })
    # Display every returned polymorph; never nominate the lowest-energy phase
    # as the measured/high-pressure material. Deterministic ID order only.
    result["candidates"] = sorted(candidates, key=lambda item: item["id"])
    if not candidates:
        result["status"] = "unavailable" if rows else "no_match"
        result["reason"] = "returned_references_require_review" if rows else "no_fixed_composition_reference_returned"
    return result


async def fetch_external_references(
    formula: str, *, api_key: str, current_records: list[dict[str, Any]] | None = None,
) -> dict:
    # Run source-aware identity resolution before even reading a formula-keyed
    # cache: an old bulk lookup cannot validate a newly retained isotope.
    query = external_query_formula(formula, current_records=current_records)
    if query is None:
        return _base(formula, "not_applicable", "composition_requires_resolution")
    if not api_key:
        return _base(formula, "unavailable", "provider_not_configured")
    key = "materials:external:1:" + hashlib.sha256(formula.encode()).hexdigest()
    # Bound lock inventory even when callers submit many different formulae.
    if key not in _locks and len(_locks) >= 128:
        return _base(formula, "unavailable", "reference_request_capacity")
    lock = _locks.setdefault(key, asyncio.Lock())
    try:
        async with lock:
            redis = get_redis()
            cached = await redis.get(key)
            if cached and len(cached.encode()) <= MAX_BYTES:
                value = json.loads(cached)
                if (type(value) is dict and value.get("version") == VERSION and value.get("formula") == formula
                        and value.get("scientific_acceptance") is False and value.get("sample_identity_established") is False
                        and value.get("status") in {"available", "no_match"}):
                    return value
            budget_key = f"materials:external:budget:{int(time.time())}"
            async with redis.pipeline(transaction=True) as pipeline:
                pipeline.incr(budget_key)
                pipeline.expire(budget_key, 3)
                used, _ = await pipeline.execute()
            if used > 5:
                return _base(formula, "unavailable", "provider_request_budget")
            async with MaterialsProjectClient(api_key, timeout=httpx.Timeout(12.0, connect=4.0)) as client:
                rows = await client.search_by_formula(query, fields=FIELDS, limit=MAX_CANDIDATES + 1, strict=True)
            result = project_external_references(formula, rows, retrieved_at=datetime.now(UTC).isoformat())
            body = json.dumps(result, allow_nan=False, separators=(",", ":"))
            if result["status"] in {"available", "no_match"} and len(body.encode()) <= MAX_BYTES:
                await redis.set(key, body, ex=CACHE_TTL)
            return result
    except (httpx.HTTPError, RedisError, ValueError, TypeError, KeyError):
        # Errors never turn into scientific absence; credentials and upstream
        # exception objects are deliberately not included in public output.
        return _base(formula, "unavailable", "provider_or_cache_unavailable")
    finally:
        if not lock.locked():
            _locks.pop(key, None)
