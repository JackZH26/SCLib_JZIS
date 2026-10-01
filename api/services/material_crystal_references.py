"""Bounded COD metadata references; never a selected sample or coordinate model."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx
from redis.exceptions import RedisError

from services._composition.formula_enrichment import enrich_formula
from services.material_external_references import external_query_formula
from services.rate_limit import get_redis

VERSION = "material-crystal-references/1.0.0"
ENDPOINT = "https://www.crystallography.net/cod/result"
METHODOLOGY_URL = "https://wiki.crystallography.net/cod_mysql_schema/"
MAX_REFERENCES = 20
MAX_BYTES = 512 * 1024
MAX_ROWS = 21
CACHE_TTL = 86400


class _LockSlot:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.users = 0


_locks: dict[str, _LockSlot] = {}
_ID = re.compile(r"[1-9][0-9]{6,8}")
_NUM = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


def _text(value: Any, limit: int = 200) -> str | None:
    return value.strip()[:limit] if type(value) is str and value.strip() else None


def _number(value: Any) -> float | None:
    if type(value) not in {str, int, float}:
        return None
    if type(value) is str and not _NUM.fullmatch(value.strip()):
        return None
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _quantity(row: dict, field: str, unit: str) -> dict | None:
    value = _number(row.get(field))
    if value is None:
        return None
    sigma_field = "sig" + field
    raw_sigma = row.get(sigma_field)
    sigma = _number(raw_sigma)
    if sigma is not None and sigma < 0:
        sigma = None
    return {"value": value, "unit": unit, "uncertainty": sigma,
            "raw_value": str(row[field]), "raw_uncertainty": str(raw_sigma) if raw_sigma is not None else None,
            "uncertainty_type": "standard_uncertainty" if sigma is not None else (
                "unresolved" if raw_sigma is not None else "unreported"),
            "source_field": field, "uncertainty_source_field": sigma_field}


def _cod_formula(value: Any) -> str | None:
    if type(value) is not str or not value.strip() or len(value) > 256:
        return None
    raw = value.strip()
    # COD wraps sum formulae in '- ... -'. Strip only that documented display
    # wrapper and whitespace, never isotope, charge, occupancy or dopant text.
    if raw.startswith("- ") and raw.endswith(" -"):
        raw = raw[2:-2]
    return re.sub(r"\s+", "", raw)


def hill_formula(formula: str) -> str:
    composition = enrich_formula(formula)
    if composition["composition_status"] != "exact":
        raise ValueError("Unresolved composition")
    amounts = composition["element_amounts"]
    order = sorted(amounts)
    if "C" in amounts:
        order = ["C", *(["H"] if "H" in amounts else []), *sorted(set(amounts) - {"C", "H"})]
    return " ".join(element + ("" if amounts[element] == 1 else format(amounts[element], ".15g"))
                    for element in order)


def _base(formula: str, status: str, reason: str | None = None) -> dict:
    return {"version": VERSION, "provider": "COD", "formula": formula, "query_formula": None,
            "status": status, "reason": reason, "references": [], "retrieved_at": None,
            "matches_total": None, "inspected_entries": 0, "truncated": False,
            "scientific_acceptance": False, "sample_identity_established": False,
            "phase_identity_established": False, "database_changed": False,
            "scope": "crystal_structure_references_not_selected_material_properties",
            "reference_conditions": "Conditions belong to each COD structure. Missing pressure does not establish ambient pressure; sample and phase correspondence require review.",
            "methodology_url": METHODOLOGY_URL, "source_response_sha256": None}


def project_crystal_references(formula: str, rows: list, *, retrieved_at: str,
                               source_response_sha256: str | None = None) -> dict:
    query = external_query_formula(formula)
    if query is None:
        return _base(formula, "not_applicable", "composition_requires_resolution")
    if type(rows) is not list or len(rows) > MAX_ROWS:
        return _base(formula, "unavailable", "provider_response_requires_review")
    target = enrich_formula(query)["atomic_fractions"]
    report = _base(formula, "available")
    report.update(query_formula=hill_formula(query), retrieved_at=retrieved_at,
                  matches_total=len(rows), inspected_entries=len(rows),
                  source_response_sha256=source_response_sha256)
    seen: set[str] = set()
    references = []
    for row in rows:
        if type(row) is not dict:
            continue
        identifier = row.get("file")
        if type(identifier) is not str or not _ID.fullmatch(identifier) or identifier in seen:
            continue
        status = _text(row.get("status"))
        flags = _text(row.get("flags"))
        markers = " ".join(str(row.get(key) or "") for key in ("status", "flags", "method")).lower()
        if any(marker in markers for marker in ("theoret", "comput", "simulat", "predict", "calculat", "density functional", "ab initio", "retracted", "errors")) or row.get("onhold"):
            continue
        method = _text(row.get("method"))
        if method and re.search(r"\b(?:not|no|non|without)[ -]+(?:\w+[ -]+){0,3}diffraction\b", method.lower()):
            continue
        declared, cell_content = _cod_formula(row.get("formula")), _cod_formula(row.get("calcformula"))
        d, c = enrich_formula(declared or ""), enrich_formula(cell_content or "")
        d_exact, c_exact = d["composition_status"] == "exact", c["composition_status"] == "exact"
        d_match, c_match = d_exact and d["atomic_fractions"] == target, c_exact and c["atomic_fractions"] == target
        if not d_match and not c_match:
            continue
        cell_content_present = type(row.get("calcformula")) is str and bool(row["calcformula"].strip())
        relation = "same_composition" if d_exact and c_exact and d["atomic_fractions"] == c["atomic_fractions"] else (
            "different_composition" if d_exact and c_exact else "unresolved" if cell_content_present else "not_supplied")
        match = "declared_and_cell_content_composition" if d_match and c_match else (
            "declared_composition_only_refined_differs" if d_match and c_exact else
            "declared_composition_only" if d_match else
            "cell_content_composition_only_declared_differs" if d_exact else
            "cell_content_composition_only_declared_unresolved")
        revision = str(row["svnrevision"]) if type(row.get("svnrevision")) in {str, int} else None
        revision = revision if revision and re.fullmatch(r"[1-9][0-9]{0,11}", revision) else None
        raw_doi = row.get("doi")
        doi = raw_doi.strip() if type(raw_doi) is str and len(raw_doi) <= 256 else None
        doi = doi if doi and re.fullmatch(r"10\.\d{4,9}/[^\s<>]+", doi) else None
        sg_number = _number(row.get("sgNumber"))
        year = _number(row.get("year"))
        references.append({
            "id": identifier, "url": f"https://www.crystallography.net/cod/{identifier}.html",
            "cif_url": f"https://www.crystallography.net/cod/{identifier}.cif" + (f"@{revision}" if revision else ""),
            "cif_validation_status": "external_file_not_validated", "coordinate_model_validated": False,
            "provider_has_coordinates": "has coordinates" in (flags or "").lower(),
            "declared_formula": declared, "cell_content_formula": cell_content,
            "composition_relation": relation, "match_level": match,
            "knowledge_origin": "Observed" if method and "diffraction" in method.lower() else "Unresolved",
            "origin_basis": "Reported diffraction method" if method and "diffraction" in method.lower() else "Measurement origin unresolved from metadata",
            "sample_identity_established": False, "phase_identity_established": False,
            "space_group": _text(row.get("sg")), "hall_symbol": _text(row.get("sgHall")),
            "space_group_number": int(sg_number) if sg_number is not None and sg_number.is_integer() and 1 <= sg_number <= 230 else None,
            "lattice": {key: q for key in ("a", "b", "c", "alpha", "beta", "gamma")
                        if (q := _quantity(row, key, "Å" if key in {"a", "b", "c"} else "degrees")) is not None},
            "volume": _quantity(row, "vol", "Å³"),
            "measurement_conditions": {
                "cell_temperature": _quantity(row, "celltemp", "K"),
                "diffraction_temperature": _quantity(row, "diffrtemp", "K"),
                "cell_pressure": _quantity(row, "cellpressure", "kPa"),
                "diffraction_pressure": _quantity(row, "diffrpressure", "kPa"),
            },
            "method": method, "method_status": "reported" if method else "unreported",
            "source_revision": f"svn:{revision}" if revision else None,
            "revision_status": "reported" if revision else "unreported",
            "source_updated": " ".join(x for x in (_text(row.get("date")), _text(row.get("time"))) if x) or None,
            "source_snapshot_sha256": hashlib.sha256(json.dumps(row, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest(),
            "source_status": status, "provider_flags": flags,
            "bibliography": {"doi": doi, "doi_url": f"https://doi.org/{quote(doi, safe='/')}" if doi else None,
                             "title": _text(row.get("title"), 400), "journal": _text(row.get("journal"), 300),
                             "year": int(year) if year is not None and year.is_integer() and 1000 <= year <= 9999 else None},
        })
        seen.add(identifier)
    report["references"] = sorted(references, key=lambda item: item["id"])[:MAX_REFERENCES]
    report["truncated"] = len(references) > MAX_REFERENCES
    if not references:
        report.update(status="unavailable" if rows else "no_match", reason=(
            "returned_references_require_review" if rows else "no_fixed_composition_reference_returned"))
    return report


async def _provider_rows(query: str) -> tuple[list, str]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=4.0), follow_redirects=False,
                                 headers={"Accept-Encoding": "identity", "Accept": "application/json"}) as client:
        async with client.stream("GET", ENDPOINT, params={"format": "json", "formula": query}) as response:
            response.raise_for_status()
            if "application/json" not in response.headers.get("content-type", "").lower():
                raise ValueError("Unexpected provider format")
            if response.headers.get("content-encoding", "").lower().strip() not in {"", "identity"}:
                raise ValueError("Unexpected provider compression")
            data = bytearray()
            async for chunk in response.aiter_raw():
                if len(data) + len(chunk) > MAX_BYTES:
                    raise ValueError("Provider byte limit")
                data.extend(chunk)
    def invalid_constant(_value):
        raise ValueError("Nonfinite provider value")
    rows = json.loads(data, parse_constant=invalid_constant)
    if type(rows) is not list or len(rows) > MAX_ROWS:
        raise ValueError("Provider row limit")
    return rows, hashlib.sha256(data).hexdigest()


async def fetch_material_crystal_references(formula: str, *, current_records: list[dict] | None = None) -> dict:
    query = external_query_formula(formula, current_records=current_records)
    if query is None:
        return _base(formula, "not_applicable", "composition_requires_resolution")
    key = "materials:cod:2:" + hashlib.sha256(formula.encode()).hexdigest()
    if key not in _locks and len(_locks) >= 128:
        return _base(formula, "unavailable", "reference_request_capacity")
    slot = _locks.setdefault(key, _LockSlot())
    # Count queued callers before the first await: a releasing owner must not
    # evict the shared lock while its waiter is scheduled but not resumed.
    slot.users += 1
    try:
        async with asyncio.timeout(12):
            async with slot.lock:
                redis = get_redis()
                cached = await redis.get(key)
                if cached:
                    if len(cached if type(cached) is bytes else cached.encode()) > MAX_BYTES:
                        return _base(formula, "unavailable", "provider_or_cache_unavailable")
                    value = json.loads(cached)
                    if (type(value) is dict and type(value.get("cache_version")) is int and value["cache_version"] == 1
                            and value.get("version") == VERSION and value.get("formula") == formula
                            and value.get("query_formula") == hill_formula(query) and value.get("provider") == "COD"
                            and type(value.get("rows")) is list and len(value["rows"]) <= MAX_ROWS
                            and type(value.get("retrieved_at")) is str and len(value["retrieved_at"]) <= 64
                            and type(value.get("source_response_sha256")) is str
                            and re.fullmatch(r"[0-9a-f]{64}", value["source_response_sha256"])):
                        captured = datetime.fromisoformat(value["retrieved_at"].replace("Z", "+00:00"))
                        if captured.tzinfo is not None:
                            # Reproject the bounded original metadata. Never replay a
                            # cached public object with unchecked authority, fields,
                            # composition, units or file/bibliographic links.
                            return project_crystal_references(formula, value["rows"],
                                retrieved_at=value["retrieved_at"], source_response_sha256=value["source_response_sha256"])
                    return _base(formula, "unavailable", "provider_or_cache_unavailable")
                async with redis.pipeline(transaction=True) as pipeline:
                    budget = f"materials:cod:budget:{int(time.time())}"
                    pipeline.incr(budget)
                    pipeline.expire(budget, 3)
                    used, _ = await pipeline.execute()
                if used > 2:
                    return _base(formula, "unavailable", "provider_request_budget")
                rows, digest = await _provider_rows(hill_formula(query))
                result = project_crystal_references(formula, rows, retrieved_at=datetime.now(UTC).isoformat(), source_response_sha256=digest)
                body = json.dumps(result, allow_nan=False, separators=(",", ":"))
                if result["status"] in {"available", "no_match"} and len(body.encode()) <= MAX_BYTES:
                    cache_body = json.dumps({"cache_version": 1, "version": VERSION, "provider": "COD",
                        "formula": formula, "query_formula": hill_formula(query), "rows": rows,
                        "retrieved_at": result["retrieved_at"], "source_response_sha256": digest},
                        allow_nan=False, separators=(",", ":"))
                    if len(cache_body.encode()) <= MAX_BYTES:
                        await redis.set(key, cache_body, ex=CACHE_TTL)
                return result
    except (httpx.HTTPError, RedisError, ValueError, TypeError, KeyError, TimeoutError, OverflowError, RecursionError):
        return _base(formula, "unavailable", "provider_or_cache_unavailable")
    finally:
        slot.users -= 1
        if slot.users == 0 and _locks.get(key) is slot:
            _locks.pop(key, None)
