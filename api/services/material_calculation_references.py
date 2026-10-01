"""Bounded public NOMAD task references, separate from measured material facts.

Only an exact, source-aware fixed composition is queried. Multiple tasks and
structures remain separate; a task or repository overlap is not an experiment.
No archive coordinates, source passages, Tc or assumed conditions are exported.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

import httpx
from redis.exceptions import RedisError

from services._composition.formula_enrichment import enrich_formula
from services.material_external_references import external_query_formula
from services.rate_limit import get_redis

VERSION = "material-calculation-references/1.0.0"
ENDPOINT = "https://nomad-lab.eu/prod/v1/api/v1/entries/query"
METHODOLOGY_URL = "https://docs.nomad-lab.eu/1.4.3/howto/manage/program/api.html"
MAX_REFERENCES = 20
MAX_BYTES = 512 * 1024
MAX_LOCKS = 128
CACHE_TTL = 86400
REQUEST_SECONDS = 12
FIELDS = (
    "entry_id", "upload_id", "parser_name", "mainfile", "references",
    "results.material.chemical_formula_hill", "results.material.chemical_formula_reduced",
    "results.material.material_id", "results.material.structural_type",
    "results.material.symmetry.space_group_number", "results.material.symmetry.space_group_symbol",
    "results.material.symmetry.crystal_system", "results.method.method_name",
    "results.method.simulation.program_name",
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,64}")


@dataclass
class _LockSlot:
    lock: asyncio.Lock
    users: int = 0


_locks: dict[str, _LockSlot] = {}


class _ProviderFailure(Exception):
    pass


def _text(value: Any, limit: int = 160) -> str | None:
    if type(value) is not str or not value.strip() or len(value) > limit:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    return value.strip()


def _identifier(value: Any) -> str | None:
    return value if type(value) is str and _IDENTIFIER.fullmatch(value) else None


def _base(formula: str, status: str, reason: str | None = None, *, query: str | None = None) -> dict:
    return {
        "version": VERSION, "provider": "NOMAD", "formula": formula,
        "query_formula": query, "status": status, "reason": reason,
        "references": [], "matches_total": None, "inspected_entries": 0,
        "truncated": False, "retrieved_at": None,
        "scientific_acceptance": False, "sample_identity_established": False,
        "phase_identity_established": False,
        "scope": "computed_task_composition_references_not_selected_material_properties",
        "reference_conditions": "Temperature and pressure were not inspected in source archives; sample and phase correspondence is unestablished.",
        "methodology_url": METHODOLOGY_URL,
    }


def hill_query_formula(formula: str) -> str | None:
    """NOMAD indexes scalar Hill formulas; never substitute a parent composition."""
    parsed = enrich_formula(formula)
    if parsed["composition_status"] != "exact":
        return None
    amounts = parsed["element_amounts"]
    order = sorted(amounts)
    if "C" in amounts:
        order = ["C"] + (["H"] if "H" in amounts else []) + [el for el in order if el not in {"C", "H"}]
    parts = []
    for element in order:
        amount = Decimal(str(amounts[element]))
        value = format(amount, "f").rstrip("0").rstrip(".") if amount % 1 else str(int(amount))
        parts.append(element + ("" if amount == 1 else value))
    return "".join(parts)


def _source_references(row: dict) -> list[dict[str, str]]:
    links: set[tuple[str, str]] = set()
    # A recognizable imported task path is an origin hint only. It does not
    # make this NOMAD entry independent of a Materials Project calculation.
    mainfile = _text(row.get("mainfile"), 2048)
    if mainfile:
        match = re.search(r"(?:^|/)(mp-[a-z0-9]{1,40})(?:/|$)", mainfile)
        if match:
            links.add(("Materials Project", f"https://next-gen.materialsproject.org/materials/{match[1]}"))
    raw_links = row.get("references")
    for raw in raw_links[:32] if type(raw_links) is list else []:
        value = _text(raw, 1024)
        if not value:
            continue
        try:
            url = urlsplit(value)
            if (url.scheme not in {"http", "https"} or url.username or url.password
                    or url.port or url.query or url.fragment):
                continue
        except ValueError:
            continue
        host = (url.hostname or "").lower()
        if host in {"doi.org", "dx.doi.org"} and re.fullmatch(r"/10\.[0-9]{4,9}/[^\s<>]+", url.path):
            links.add(("DOI", "https://doi.org" + url.path))
        elif host in {"oqmd.org", "www.oqmd.org", "aflow.org", "aflowlib.org", "www.aflowlib.org"}:
            links.add(("OQMD" if "oqmd" in host else "AFLOW", "https://" + host + url.path))
        elif host == "zenodo.org" and re.fullmatch(r"/records?/[0-9]+/?", url.path):
            links.add(("Zenodo", "https://zenodo.org" + url.path))
    return [{"provider": provider, "url": url} for provider, url in sorted(links)[:8]]


def project_calculation_references(formula: str, payload: Any, *, retrieved_at: str) -> dict:
    """Validate a bounded metadata response and project only public allowlisted fields."""
    query = hill_query_formula(formula)
    if query is None:
        return _base(formula, "not_applicable", "composition_requires_resolution")
    target = enrich_formula(formula)
    result = _base(formula, "unavailable", "provider_response_requires_review", query=query)
    if type(payload) is not dict or type(payload.get("data")) is not list:
        return result
    pagination = payload.get("pagination")
    total = pagination.get("total") if type(pagination) is dict else None
    rows = payload["data"]
    if type(total) is not int or total < len(rows) or total < 0:
        return result
    result.update(matches_total=total, inspected_entries=min(len(rows), MAX_REFERENCES + 1),
                  truncated=total > MAX_REFERENCES or len(rows) > MAX_REFERENCES,
                  retrieved_at=retrieved_at)
    if not rows:
        if total == 0:
            result.update(status="no_match", reason="no_fixed_composition_task_returned")
        return result
    references = []
    seen = set()
    for row in rows[:MAX_REFERENCES + 1]:
        if type(row) is not dict:
            continue
        entry = _identifier(row.get("entry_id"))
        if entry is None or entry in seen:
            continue
        results = row.get("results") if type(row.get("results")) is dict else {}
        material = results.get("material") if type(results.get("material")) is dict else {}
        formulas = [material[key] for key in ("chemical_formula_hill", "chemical_formula_reduced")
                    if material.get(key) is not None]
        if not formulas:
            continue
        # Validate every supplied composition, including alternate spellings.
        # An exact Hill label cannot hide an unresolved/isotopic reduced label.
        if any(type(value) is not str or len(value) > 300
               or (parsed := enrich_formula(value))["composition_status"] != "exact"
               or parsed["atomic_fractions"] != target["atomic_fractions"] for value in formulas):
            continue
        symmetry = material.get("symmetry") if type(material.get("symmetry")) is dict else {}
        method = results.get("method") if type(results.get("method")) is dict else {}
        simulation = method.get("simulation") if type(method.get("simulation")) is dict else {}
        method_name, program = _text(method.get("method_name")), _text(simulation.get("program_name"))
        space_group_number = symmetry.get("space_group_number")
        seen.add(entry)
        references.append({
            "id": entry, "url": f"https://nomad-lab.eu/prod/v1/gui/search/entries/entry/id/{entry}",
            "archive_url": f"https://nomad-lab.eu/prod/v1/api/v1/entries/{entry}/archive",
            "formula": formulas[0], "material_id": _identifier(material.get("material_id")),
            "upload_id": _identifier(row.get("upload_id")),
            "method": method_name, "program": program, "parser": _text(row.get("parser_name")),
            "method_status": "reported" if method_name else "unresolved",
            "knowledge_origin": "Computed" if method_name and program else "Unresolved",
            "structural_type": _text(material.get("structural_type")),
            "space_group": _text(symmetry.get("space_group_symbol")),
            "space_group_number": space_group_number if type(space_group_number) is int and 1 <= space_group_number <= 230 else None,
            "crystal_system": _text(symmetry.get("crystal_system")),
            "source_references": _source_references(row),
            "source_snapshot_sha256": hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False,
                                                                   allow_nan=False, separators=(",", ":")).encode()).hexdigest(),
            "match_level": "fixed_composition_only", "conditions_status": "not_inspected",
            "sample_identity_established": False, "phase_identity_established": False,
        })
    result["references"] = sorted(references, key=lambda item: item["id"])[:MAX_REFERENCES]
    if references:
        result.update(status="available", reason=None)
    return result


def _valid_cache(value: Any, formula: str, query: str) -> bool:
    if (type(value) is not dict or value.get("version") != VERSION or value.get("provider") != "NOMAD"
            or value.get("formula") != formula or value.get("query_formula") != query
            or value.get("status") not in {"available", "no_match"}
            or any(value.get(key) is not False for key in ("scientific_acceptance", "sample_identity_established", "phase_identity_established"))
            or type(value.get("references")) is not list or len(value["references"]) > MAX_REFERENCES
            or set(value) != set(_base(formula, "available", query=query))
            or value.get("scope") != _base(formula, "available")["scope"]
            or value.get("reference_conditions") != _base(formula, "available")["reference_conditions"]
            or value.get("methodology_url") != METHODOLOGY_URL
            or type(value.get("matches_total")) is not int or value["matches_total"] < len(value["references"])
            or type(value.get("inspected_entries")) is not int or not 0 <= value["inspected_entries"] <= MAX_REFERENCES + 1
            or type(value.get("truncated")) is not bool or _text(value.get("retrieved_at"), 80) is None):
        return False
    rows = value["references"]
    if value["status"] == "no_match":
        return not rows and value.get("matches_total") == 0 and value.get("reason") == "no_fixed_composition_task_returned"
    if not rows:
        return False
    if value.get("reason") is not None:
        return False
    target = enrich_formula(formula)["atomic_fractions"]
    for row in rows:
        if type(row) is not dict or _identifier(row.get("id")) is None:
            return False
        entry = row["id"]
        parsed = enrich_formula(row.get("formula", ""))
        if (row.get("url") != f"https://nomad-lab.eu/prod/v1/gui/search/entries/entry/id/{entry}"
                or row.get("archive_url") != f"https://nomad-lab.eu/prod/v1/api/v1/entries/{entry}/archive"
                or parsed["composition_status"] != "exact" or parsed["atomic_fractions"] != target
                or row.get("conditions_status") != "not_inspected"
                or row.get("sample_identity_established") is not False or row.get("phase_identity_established") is not False
                or not re.fullmatch(r"[a-f0-9]{64}", str(row.get("source_snapshot_sha256", "")))):
            return False
        # The cache stores only a bounded public projection, never source text.
        if set(row) - {"id", "url", "archive_url", "formula", "material_id", "upload_id", "method", "program", "parser", "method_status", "knowledge_origin", "structural_type", "space_group", "space_group_number", "crystal_system", "source_references", "source_snapshot_sha256", "match_level", "conditions_status", "sample_identity_established", "phase_identity_established"}:
            return False
        for field in ("method", "program", "parser", "structural_type", "space_group", "crystal_system"):
            if row.get(field) is not None and _text(row[field]) is None:
                return False
        for field in ("material_id", "upload_id"):
            if row.get(field) is not None and _identifier(row[field]) is None:
                return False
        number = row.get("space_group_number")
        if number is not None and (type(number) is not int or not 1 <= number <= 230):
            return False
        if (row.get("match_level") != "fixed_composition_only"
                or row.get("method_status") != ("reported" if row.get("method") else "unresolved")
                or row.get("knowledge_origin") != ("Computed" if row.get("method") and row.get("program") else "Unresolved")):
            return False
        links = row.get("source_references")
        if type(links) is not list or len(links) > 8:
            return False
        for link in links:
            if type(link) is not dict or set(link) != {"provider", "url"}:
                return False
            # Reuse the same allowlist applied to the provider projection.
            if link.get("provider") == "Materials Project":
                if not re.fullmatch(r"https://next-gen\.materialsproject\.org/materials/mp-[a-z0-9]{1,40}", str(link.get("url", ""))):
                    return False
            elif link not in _source_references({"references": [link.get("url")]}):
                return False
    return True


async def _provider_payload(query: str) -> Any:
    body = {"owner": "public", "query": {"results.material.chemical_formula_hill": query},
            "pagination": {"page_size": MAX_REFERENCES + 1, "order_by": "entry_id", "order": "asc"},
            "required": {"include": list(FIELDS)}}
    async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_SECONDS, connect=4),
                                 follow_redirects=False, trust_env=False) as client:
        async with client.stream("POST", ENDPOINT, json=body, headers={"Accept-Encoding": "identity"}) as response:
            if response.status_code != 200:
                raise _ProviderFailure("provider_rejected_query" if response.status_code == 422 else "provider_http_unavailable")
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise _ProviderFailure("provider_unexpected_content_encoding")
            content = bytearray()
            async for chunk in response.aiter_raw():
                if len(content) + len(chunk) > MAX_BYTES:
                    raise _ProviderFailure("provider_response_too_large")
                content.extend(chunk)
            return json.loads(content)


async def fetch_material_calculation_references(
    formula: str, *, current_records: list[dict[str, Any]] | None = None,
) -> dict:
    # This guard precedes even a cache read. A bulk cached match cannot validate
    # a newly retained isotope, interface, variable composition or dopant alias.
    fixed = external_query_formula(formula, current_records=current_records)
    query = hill_query_formula(fixed) if fixed is not None else None
    if query is None:
        return _base(formula, "not_applicable", "composition_requires_resolution")
    key = "materials:nomad:1:" + hashlib.sha256(formula.encode()).hexdigest()
    if key not in _locks and len(_locks) >= MAX_LOCKS:
        return _base(formula, "unavailable", "reference_request_capacity", query=query)
    slot = _locks.setdefault(key, _LockSlot(asyncio.Lock()))
    slot.users += 1
    try:
        async with asyncio.timeout(REQUEST_SECONDS):
            async with slot.lock:
                redis = get_redis()
                cached = await redis.get(key)
                if cached and len(cached if isinstance(cached, bytes) else cached.encode()) <= MAX_BYTES:
                    try:
                        value = json.loads(cached)
                    except (ValueError, TypeError, RecursionError):
                        value = None
                    if _valid_cache(value, formula, query):
                        return value
                budget_key = f"materials:nomad:budget:{int(time.time())}"
                async with redis.pipeline(transaction=True) as pipeline:
                    pipeline.incr(budget_key)
                    pipeline.expire(budget_key, 3)
                    used, _ = await pipeline.execute()
                if type(used) is not int or used > 5:
                    return _base(formula, "unavailable", "provider_request_budget", query=query)
                payload = await _provider_payload(query)
                result = project_calculation_references(formula, payload, retrieved_at=datetime.now(UTC).isoformat())
                serialized = json.dumps(result, allow_nan=False, separators=(",", ":"))
                if result["status"] in {"available", "no_match"} and len(serialized.encode()) <= MAX_BYTES:
                    await redis.set(key, serialized, ex=CACHE_TTL)
                return result
    except _ProviderFailure as error:
        return _base(formula, "unavailable", str(error), query=query)
    except TimeoutError:
        return _base(formula, "unavailable", "provider_request_timeout", query=query)
    except (httpx.HTTPError, RedisError, ValueError, TypeError, KeyError, RecursionError):
        return _base(formula, "unavailable", "provider_or_cache_unavailable", query=query)
    finally:
        slot.users -= 1
        if slot.users == 0 and _locks.get(key) is slot:
            _locks.pop(key)
