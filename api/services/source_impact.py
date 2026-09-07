"""Bounded, read-only exact-source impact inventory; never a refresh receipt.

The declared graph is a catalogue relationship snapshot, not a scientific
dependency proof. No source text, measured values, frozen bodies, permissions,
queue entries, release notices or approval decisions are created or returned.
"""
from __future__ import annotations

from collections import defaultdict

import sqlalchemy as sa

from models.db import Base
from services.research_release_manifest import canonical, digest
from services.source_lifecycle import SourceLifecycleError, _current_event, _sha, _uuid

VERSION = "source-impact/1.0.0"
MAX_PAPERS = 1000
MAX_NODES = 2000
MAX_RELATIONS = 4000
MAX_PARENT_DEPTH = 32
MAX_DESCRIPTOR_BYTES = 1024 * 1024
SUPPORTED_SCOPES = (
    "direct_event_source_and_current_accepted_work_paper_mapping",
    "explicit_claim_paper_and_work_references",
    "exact_top_level_material_record_paper_references",
    "record_backed_material_descendant_governance_and_zero_point_timeline_candidates",
    "claim_material_context_not_record_support",
    "direct_chunk_and_hydride_paper_references",
    "active_and_inactive_timeline_paper_and_record_backed_material_references",
    "direct_ml_example_label_claim_work_and_record_backed_material_references",
    "reached_example_dataset_membership",
    "reached_object_frozen_pins_and_publication_proposal_references",
)
UNSUPPORTED_SCOPES = (
    "transitive_research_event_and_ml_feature_dependencies",
    "source_revision_capture_and_shadow_import_lineage",
    "indirect_extracted_material_mentions_in_other_sources",
    "research_samples_and_structure_lineage",
    "hydride_material_context_not_already_reached_by_supported_paths",
    "malformed_or_non_exact_json_reference_identity",
    "file_backed_rps_evidence",
    "cached_answers_and_external_vector_index_state",
    "dependencies_created_after_this_database_snapshot",
)


class SourceImpactError(ValueError):
    """The requested point-in-time inventory cannot be safely established."""


class SourceImpactLimitError(SourceImpactError):
    """A complete inventory for the declared scope exceeds safe bounds."""


def _table(name):
    return Base.metadata.tables[name]


class _Inventory:
    def __init__(self):
        self.nodes = defaultdict(set)
        self.byte_count = 0
        self.relation_count = 0

    def add(self, table, row_id, kind, via_table, via_id):
        key = (table, str(row_id))
        relation = (kind, via_table, str(via_id))
        if relation in self.nodes.get(key, ()):
            return
        if key not in self.nodes:
            if len(self.nodes) >= MAX_NODES:
                raise SourceImpactLimitError("Source impact node limit exceeded")
            self.byte_count += len(canonical({"table": table, "row_id": key[1], "relations": []}))
        self.relation_count += 1
        self.byte_count += len(canonical(dict(zip(("kind", "via_table", "via_id"), relation)))) + 1
        if self.relation_count > MAX_RELATIONS or self.byte_count > MAX_DESCRIPTOR_BYTES:
            raise SourceImpactLimitError("Source impact relationship or byte limit exceeded")
        self.nodes[key].add(relation)

    def identifiers(self, table):
        return {row_id for (name, row_id) in self.nodes if name == table}

    def document(self):
        return [{"table": table, "row_id": row_id,
                 "relations": [dict(zip(("kind", "via_table", "via_id"), relation))
                               for relation in sorted(relations)]}
                for (table, row_id), relations in sorted(self.nodes.items())]


async def _rows(db, statement, *, maximum=None):
    maximum = MAX_RELATIONS if maximum is None else maximum
    result = (await db.execute(statement.limit(maximum + 1))).all()
    if len(result) > maximum:
        raise SourceImpactLimitError("Source impact query row limit exceeded")
    return result


async def _references(db, inventory, name, field, values, kind, via_table):
    """Follow one explicitly typed FK/rebuildable reference, not a JSON guess."""
    if not values:
        return []
    table = _table(name)
    rows = await _rows(db, sa.select(table.c.id, table.c[field]).where(table.c[field].in_(sorted(values))))
    for row_id, via_id in rows:
        inventory.add(name, row_id, kind, via_table, via_id)
    return rows


async def _materials(db, inventory, paper_ids, claims):
    materials = _table("materials")
    roots = set()
    if paper_ids:
        papers = sa.values(sa.column("paper_id", sa.String(100)), name="selected_sources").data(
            [(identifier,) for identifier in sorted(paper_ids)])
        # Exact typed containment is supported by the 0057 JSONB GIN index.
        matches = materials.c.records.op("@>")(
            sa.func.jsonb_build_array(sa.func.jsonb_build_object("paper_id", papers.c.paper_id)))
        rows = await _rows(db, sa.select(materials.c.id, papers.c.paper_id).select_from(
            papers.join(materials, matches)))
        for material_id, paper_id in rows:
            roots.add(material_id)
            inventory.add("materials", material_id, "record_source", "papers", paper_id)
    if claims:
        table = _table("material_claims")
        for claim_id, material_id in await _rows(db, sa.select(table.c.id, table.c.material_id).where(
                table.c.id.in_([_uuid(value) for value in sorted(claims)]))):
            inventory.add("materials", material_id, "claim_material_context", "material_claims", claim_id)

    # Readers inherit ancestor governance. Invert those exact edges, including
    # children with no records or existing Timeline point. Context-only claim
    # materials are not promoted into record-backed scientific support.
    descendants, frontier, parent_of = set(roots), set(roots), {}
    for depth in range(MAX_PARENT_DEPTH + 1):
        if not frontier:
            break
        rows = await _rows(db, sa.select(materials.c.id, materials.c.parent_material_id).where(
            materials.c.parent_material_id.in_(sorted(frontier))))
        if rows and depth == MAX_PARENT_DEPTH:
            raise SourceImpactLimitError("Source impact material ancestry depth exceeded")
        next_frontier = set()
        for child, parent in rows:
            parent_of[child] = parent
            cursor, visited = child, set()
            while cursor in parent_of:
                if cursor in visited:
                    raise SourceImpactError("Source impact material ancestry cycle")
                visited.add(cursor)
                cursor = parent_of[cursor]
            inventory.add("materials", child, "inherited_parent_governance", "materials", parent)
            if child not in descendants:
                descendants.add(child)
                next_frontier.add(child)
        frontier = next_frontier
    # Overlapping record roots must not disguise an over-deep chain as many
    # short breadth-first paths. Validate the reached graph independently of
    # root selection and database row ordering, as public ancestry reads do.
    for origin in parent_of:
        cursor, visited = origin, set()
        while cursor in parent_of:
            if cursor in visited:
                raise SourceImpactError("Source impact material ancestry cycle")
            if len(visited) >= MAX_PARENT_DEPTH:
                raise SourceImpactLimitError("Source impact material ancestry depth exceeded")
            visited.add(cursor)
            cursor = parent_of[cursor]
    return descendants


async def _frozen_references(db, inventory):
    """Return historical references only; never load immutable row bodies."""
    pins = _table("research_release_pins")
    candidates = sa.values(sa.column("table_name", sa.String(100)), sa.column("row_id", sa.String(200)),
                           name="impact_objects").data(sorted(inventory.nodes))
    rows = await _rows(db, sa.select(pins.c.release_id, pins.c.table_name, pins.c.row_id).select_from(
        candidates.join(pins, sa.and_(pins.c.table_name == candidates.c.table_name,
                                    pins.c.row_id == candidates.c.row_id))))
    releases = set()
    for release_id, name, identifier in rows:
        releases.add(release_id)
        inventory.add("research_releases", release_id, "historical_frozen_reference", name, identifier)
    await _references(db, inventory, "research_publication_proposals", "release_id", releases,
                      "historical_publication_proposal", "research_releases")


async def inspect_source_impact(db, *, event_id, expected_event_sha256):
    """Inspect a current exact event in a dedicated stable read transaction.

    Authentication belongs to the trusted caller. A SERIALIZABLE session is
    accepted for local controlled inspection; the HTTP caller uses READ ONLY
    REPEATABLE READ. This function neither starts/commits a transaction nor
    mutates session settings, guard epochs, queue state or catalogue objects.
    """
    try:
        event_id, expected_event_sha256 = _uuid(event_id), _sha(expected_event_sha256)
    except SourceLifecycleError as exc:
        raise SourceImpactError(str(exc)) from exc
    if db.new or db.dirty or db.deleted:
        raise SourceImpactError("A dedicated clean source-impact read session is required")
    with db.no_autoflush:
        isolation = (await db.execute(sa.text("SHOW transaction_isolation"))).scalar_one()
        if isolation not in {"repeatable read", "serializable"}:
            raise SourceImpactError("Source impact requires REPEATABLE READ or SERIALIZABLE")
        observed_at = (await db.execute(sa.text("SELECT transaction_timestamp()"))).scalar_one().isoformat()
        try:
            event, _status = await _current_event(db, event_id, expected_event_sha256)
        except SourceLifecycleError as exc:
            raise SourceImpactError(str(exc)) from exc
        inventory = _Inventory()
        paper_ids, work_ids = set(), set()
        if event["paper_id"] is not None:
            paper_ids.add(event["paper_id"])
            inventory.add("papers", event["paper_id"], "direct_source", "source_lifecycle_events", event["id"])
        else:
            work_ids.add(event["work_id"])
            inventory.add("works", event["work_id"], "direct_source", "source_lifecycle_events", event["id"])
            mapping = _table("paper_work_map")
            rows = await _rows(db, sa.select(mapping.c.paper_id, mapping.c.work_id).where(
                mapping.c.work_id == event["work_id"], mapping.c.review_status == "accepted"), maximum=MAX_PAPERS)
            for paper_id, work_id in rows:
                paper_ids.add(paper_id)
                inventory.add("paper_work_map", paper_id, "accepted_work_mapping", "works", work_id)
                inventory.add("papers", paper_id, "accepted_work_source", "paper_work_map", paper_id)

        await _references(db, inventory, "material_claims", "paper_id", paper_ids, "explicit_claim_paper", "papers")
        await _references(db, inventory, "material_claims", "work_id", work_ids, "explicit_claim_work", "works")
        claims = inventory.identifiers("material_claims")
        material_ids = await _materials(db, inventory, paper_ids, claims)
        await _references(db, inventory, "chunks", "paper_id", paper_ids, "direct_chunk_source", "papers")
        await _references(db, inventory, "hydride_tc_parameters", "paper_id", paper_ids,
                          "direct_hydride_source", "papers")
        await _references(db, inventory, "timeline_projection_points", "paper_id", paper_ids,
                          "existing_timeline_source", "papers")
        await _references(db, inventory, "timeline_projection_points", "material_id", material_ids,
                          "existing_timeline_material", "materials")
        await _references(db, inventory, "ml_examples", "claim_id", {_uuid(value) for value in claims},
                          "example_label_claim", "material_claims")
        await _references(db, inventory, "ml_examples", "work_id", work_ids, "example_explicit_work", "works")
        await _references(db, inventory, "ml_examples", "material_id", material_ids,
                          "example_material_governance", "materials")
        examples = inventory.identifiers("ml_examples")
        if examples:
            table = _table("ml_examples")
            rows = await _rows(db, sa.select(table.c.id, table.c.dataset_snapshot_id).where(
                table.c.id.in_([_uuid(value) for value in sorted(examples)])))
            for example_id, dataset_id in rows:
                inventory.add("ml_dataset_snapshots", dataset_id, "dataset_example_membership", "ml_examples", example_id)
        await _frozen_references(db, inventory)

        nodes = inventory.document()
        counts = {name: len(inventory.identifiers(name)) for name in sorted({item["table"] for item in nodes})}
        body = {"version": VERSION,
            "event": {"id": str(event["id"]), "record_sha256": event["record_sha256"],
                      "source_snapshot_sha256": event["snapshot_sha256"], "revision": event["revision"],
                      "source_kind": "paper" if event["paper_id"] is not None else "work",
                      "source_id": str(event["paper_id"] if event["paper_id"] is not None else event["work_id"])},
            "nodes": nodes, "counts": counts, "node_count": len(nodes),
            "timeline_candidate_material_ids": sorted(material_ids),
            "complete_for_declared_scope": True, "propagation_complete": False,
            "scientific_acceptance": False, "ml_training_approved": False, "source_reinstatement": False,
            "supported_scopes": list(SUPPORTED_SCOPES),
            "unsupported_scopes": list(UNSUPPORTED_SCOPES),
            "next_actions": [{"domain": domain, "status": "not_scheduled"} for domain in (
                "material_and_timeline_projection_review", "retrieval_context_review",
                "prospective_ml_membership_review", "frozen_reference_review")],
            "limits": {"papers": MAX_PAPERS, "nodes": MAX_NODES, "relations": MAX_RELATIONS,
                       "parent_depth": MAX_PARENT_DEPTH, "descriptor_bytes": MAX_DESCRIPTOR_BYTES}}
        result = {**body, "inventory_sha256": digest(body), "observation": {
            "observed_at": observed_at, "transaction_isolation": isolation,
            "currentness": "current_in_database_snapshot", "persisted": False,
            "refresh_scheduled": False, "graph_binding": "relationships_only_not_scientific_row_hashes"}}
        if len(canonical(result)) > MAX_DESCRIPTOR_BYTES:
            raise SourceImpactLimitError("Source impact document byte limit exceeded")
        return result
