"""Private candidate previews from stored interpretations; no catalogue activation."""

from __future__ import annotations

from copy import deepcopy
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa

from models.db import MATERIALS_V3_TABLES as T
from models.db import Material, Paper, PaperWorkMap
from services.material_reports_v3 import _hash
from services.material_source_scope import current_visibility_allows_view
from services.material_visibility_adapter import material_view
from services.materials_v3_import import _insert_once, sha
from services.source_lifecycle import resolve_paper_lifecycle
from services.source_visibility import source_visibility


def _quantity(q):
    if q is None or q.get("status") != "normalized":
        return {
            "status": "unreported" if q is None else "unresolved",
            "relation": "unknown",
            "value": None,
            "lower": None,
            "upper": None,
            "unit": "",
            "raw_value": q.get("raw") if q else None,
            "reason": q.get("reason") if q else None,
        }
    return {
        "status": "parsed",
        **{k: q[k] for k in ("relation", "value", "lower", "upper", "unit")},
        "approximate": q.get("raw", {}).get("approximate", False),
        "raw_value": q.get("raw"),
    }


def candidate_points(candidate, capture, run, paper):
    raw, validation = candidate["payload"], candidate["validation"]
    normalized = validation["normalized"]
    if normalized["local_id"] != raw["local_id"]:
        raise ValueError("candidate_normalization_identity_mismatch")
    paired = list(zip(raw["properties"], normalized["properties"], strict=True))
    if any(p["property_key"] != n["key"] for p, n in paired):
        raise ValueError("candidate_normalization_property_mismatch")
    paired_conditions = list(zip(raw["conditions"], normalized["conditions"], strict=True))
    if any(c["key"] != n["key"] for c, n in paired_conditions):
        raise ValueError("candidate_normalization_condition_mismatch")
    conditions = {c["key"]: n["quantity"] for c, n in paired_conditions}
    tc = [(i, p, n) for i, (p, n) in enumerate(paired) if p["property_key"] == "tc"] or [
        (0, None, None)
    ]
    sample, series = raw["sample"], raw["series_point"]
    sample_label = sample["label_raw"] if sample else None
    series_id = (
        _hash(
            {
                "source": str(capture["id"]),
                "sample": sample_label,
                "label": series["series_label_raw"],
            }
        )
        if sample_label and series and series["series_label_raw"]
        else None
    )
    result = []
    for index, prop, norm in tc:
        origin = prop["knowledge_origin"] if prop else raw["event"]["knowledge_origin"]
        pressure_role = {
            "Observed": "measurement_pressure",
            "Computed": "calculation_pressure",
        }.get(origin, "unknown")
        proof = validation.get("bound_evidence", [])
        source_evidence = prop["evidence"] if prop else raw["outcome_evidence"]
        bound = next(
            (
                e
                for e in proof
                if any(
                    e["block_id"] == s["block_id"] and e["quote"] == s["quote"]
                    for s in source_evidence
                )
            ),
            None,
        )
        locator = {
            k: bound[k]
            for k in ("block_id", "page", "source_start", "source_end", "table_id")
            if bound and bound.get(k) is not None
        }
        result.append(
            {
                "point_id": str(candidate["id"]) + ":" + str(index),
                "event_id": None,
                "physical_point_id": str(candidate["occurrence_id"]),
                "work_id": str(capture["work_id"]) if capture["work_id"] else None,
                "paper_id": capture["paper_id"],
                "title": paper["title"] if paper else None,
                "year": (paper["date_published"] or paper["date_submitted"]).year
                if paper and (paper["date_published"] or paper["date_submitted"])
                else None,
                "sample_label": sample_label,
                "sample_form": sample["form_raw"] if sample else None,
                "series_id": series_id,
                "path_direction": series["path_direction"] if series else "unknown",
                "point_label": series["point_label_raw"] if series else None,
                "replicate_label": series["replicate_label_raw"] if series else None,
                "sc_outcome": raw["sc_outcome"],
                "tc": _quantity(norm["quantity"] if norm else None),
                "pressure": _quantity(conditions.get(pressure_role)),
                "pressure_role": pressure_role,
                "pressure_semantics": next(
                    (c["status"] for c in raw["conditions"] if c["key"] == pressure_role),
                    "not_reported",
                ),
                "conditions": [
                    {
                        "key": c["key"],
                        "status": c["status"],
                        "quantity": _quantity(n["quantity"]),
                        "value_raw": c["qualitative"]["raw_text"] if c["qualitative"] else None,
                    }
                    for c, n in paired_conditions
                ],
                "tc_definition": prop["qualifiers"].get("tc_definition", "unknown")
                if prop
                else "unknown",
                "method": raw["event"]["method_raw"],
                "knowledge_origin": origin,
                "source_role": prop["source_role"] if prop else raw["event"]["source_role"],
                "minimum_test_temperature": _quantity(conditions.get("minimum_test_temperature")),
                "source_locator": locator,
                "properties": [
                    {
                        "key": p["property_key"],
                        "quantity": _quantity(n["quantity"]),
                        "unit": (n["quantity"] or {}).get("unit") or "",
                        "knowledge_origin": p["knowledge_origin"],
                        "source_role": p["source_role"],
                        "qualifiers": p["qualifiers"],
                        "value_raw": p["qualitative"]["raw_text"] if p["qualitative"] else None,
                    }
                    for p, n in paired
                    if p["property_key"] != "tc"
                ],
                "identity_status": "explicit_preview_binding",
                "review_status": "pending",
                "candidate_id": str(candidate["id"]),
                "source_sha256": capture["source_sha256"],
                "config_sha256": run["config_sha256"],
            }
        )
    return result


async def save_candidate_snapshot(db, *, run_ids, material_bindings, dry_run=True):
    """Explicit source interpretation and material bindings; caller owns commit."""
    if not 1 <= len(run_ids) <= 50 or len(material_bindings) > 1000:
        raise ValueError("candidate_snapshot_inventory_limit")
    identifiers = {UUID(str(i)) for i in run_ids}
    runs = (
        (
            await db.execute(
                sa.select(T["ner_extraction_runs"]).where(
                    T["ner_extraction_runs"].c.id.in_(identifiers)
                )
            )
        )
        .mappings()
        .all()
    )
    if len(runs) != len(identifiers) or len({r["capture_id"] for r in runs}) != len(runs):
        raise ValueError("candidate_snapshot_requires_one_interpretation_per_capture")
    candidates_table = T["ner_candidates"]
    count, bytes_total = (
        await db.execute(
            sa.select(
                sa.func.count(),
                sa.func.coalesce(
                    sa.func.sum(
                        sa.func.octet_length(
                            sa.cast(sa.func.to_jsonb(candidates_table.table_valued()), sa.Text)
                        )
                    ),
                    0,
                ),
            ).where(candidates_table.c.run_id.in_(identifiers))
        )
    ).one()
    if count > 1000 or bytes_total > 8 * 1024**2:
        raise ValueError("candidate_snapshot_byte_or_row_limit")
    candidates = (
        (
            await db.execute(
                sa.select(candidates_table).where(candidates_table.c.run_id.in_(identifiers))
            )
        )
        .mappings()
        .all()
    )
    if set(material_bindings) - {str(c["id"]) for c in candidates}:
        raise ValueError("candidate_snapshot_unknown_material_binding")
    captures = (
        (
            await db.execute(
                sa.select(T["ner_source_captures"]).where(
                    T["ner_source_captures"].c.id.in_({r["capture_id"] for r in runs})
                )
            )
        )
        .mappings()
        .all()
    )
    captures = {c["id"]: c for c in captures}
    paper_ids = {c["paper_id"] for c in captures.values() if c["paper_id"]}
    papers = {
        p["id"]: p
        for p in (await db.execute(sa.select(Paper.__table__).where(Paper.id.in_(paper_ids))))
        .mappings()
        .all()
    }
    materials = set(material_bindings.values())
    if (
        set((await db.execute(sa.select(Material.id).where(Material.id.in_(materials)))).scalars())
        != materials
    ):
        raise ValueError("candidate_snapshot_existing_material_required")
    run_map, projections = {r["id"]: r for r in runs}, {}
    for candidate in candidates:
        material = material_bindings.get(str(candidate["id"]))
        if not material:
            continue
        capture = captures[candidate["capture_id"]]
        points = candidate_points(
            candidate, capture, run_map[candidate["run_id"]], papers.get(capture["paper_id"])
        )
        projections.setdefault(material, []).extend(points)
    manifest = {
        "version": "materials-candidate-snapshot/1",
        "run_ids": sorted(map(str, identifiers)),
        "material_bindings": material_bindings,
        "scientific_acceptance": False,
        "public_activation": False,
        "unbound_candidates": count - len(material_bindings),
    }
    manifest_hash = sha(manifest)
    identifier = uuid5(NAMESPACE_URL, "urn:sclib:materials-preview:" + manifest_hash)
    transaction = await db.begin_nested()
    try:
        await _insert_once(
            db,
            "material_projection_snapshots",
            {
                "id": identifier,
                "schema_version": "material-reports/3.0",
                "manifest_sha256": manifest_hash,
                "manifest": manifest,
            },
            ["manifest_sha256"],
        )
        for material, points in sorted(projections.items()):
            projection = {
                "version": "material-reports/3.0",
                "material_id": material,
                "points": points,
                "coverage": {
                    "status": "candidate_run_scope_pending_review",
                    "no_claim_found_allowed": False,
                },
            }
            await _insert_once(
                db,
                "material_projection_members",
                {
                    "snapshot_id": identifier,
                    "material_id": material,
                    "projection": projection,
                    "record_sha256": sha(projection),
                },
                ["snapshot_id", "material_id"],
            )
        if dry_run:
            await transaction.rollback()
        else:
            await transaction.commit()
    except BaseException:
        if transaction.is_active:
            await transaction.rollback()
        raise
    return {
        "snapshot_id": str(identifier),
        "manifest_sha256": manifest_hash,
        "materials": len(projections),
        "dry_run": dry_run,
        "catalogue_changed": False,
        "scientific_acceptance": False,
    }


async def read_candidate_snapshot(db, snapshot_id, material_id, *, offset=0, limit=50):
    context = await material_view(db, await db.get(Material, material_id))
    if context is None or not current_visibility_allows_view(
        context.visibility, include_archive=False
    ):
        return None
    table = T["material_projection_members"]
    condition = (table.c.snapshot_id == snapshot_id) & (table.c.material_id == material_id)
    size = (
        await db.execute(
            sa.select(sa.func.octet_length(sa.cast(table.c.projection, sa.Text))).where(condition)
        )
    ).scalar_one_or_none()
    if size is None or size > 8 * 1024**2:
        return None
    member = (await db.execute(sa.select(table).where(condition))).mappings().one()
    if sha(member["projection"]) != member["record_sha256"]:
        raise ValueError("candidate_snapshot_projection_hash_mismatch")
    rows = deepcopy(member["projection"]["points"])
    statuses = await resolve_paper_lifecycle(db, {p["paper_id"] for p in rows if p["paper_id"]})
    rows = [
        p
        for p in rows
        if p["paper_id"] in statuses
        and source_visibility(statuses[p["paper_id"]])["reported_claim_filter_eligible"]
    ]
    mappings = dict(
        (
            await db.execute(
                sa.select(PaperWorkMap.paper_id, PaperWorkMap.work_id).where(
                    PaperWorkMap.paper_id.in_({p["paper_id"] for p in rows}),
                    PaperWorkMap.review_status == "accepted",
                )
            )
        ).all()
    )
    for point in rows:
        current = mappings.get(point["paper_id"])
        point["work_id"] = (
            str(current)
            if current and (point["work_id"] is None or str(current) == point["work_id"])
            else None
        )
    groups = {}
    for point in rows[offset : offset + limit]:
        group = point["work_id"] or "unresolved-source:" + point["paper_id"]
        groups.setdefault(group, []).append(point)
    return {
        "version": "material-reports/3.0",
        "material_id": material_id,
        "display_formula": context.material.formula,
        "snapshot_id": str(snapshot_id),
        "projection_kind": "private_ner_candidate_preview",
        "total_points": len(rows),
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < len(rows),
        "report_groups": [
            {"group_id": group, "work_id": points[0]["work_id"], "points": points}
            for group, points in groups.items()
        ],
        "support_counts": {
            "source_ids": len({p["paper_id"] for p in rows}),
            "verified_unique_works": len({p["work_id"] for p in rows if p["work_id"]}),
            "work_identity_unknown_sources": len({p["paper_id"] for p in rows if not p["work_id"]}),
            "result_points": len({p["physical_point_id"] for p in rows}),
            "independent_data_groups": None,
            "cited_report_points": sum(p["source_role"] == "cited" for p in rows),
        },
        "coverage": member["projection"]["coverage"],
        "scientific_acceptance": False,
        "projection_sha256": _hash(rows),
    }
