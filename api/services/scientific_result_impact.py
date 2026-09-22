"""Bounded private catalogue references, not scientific dependency or refresh proof.

Only typed SQL identities are traversed. Event-level references also include
other results from that event; they must not be read as property-specific
causality. Historical capsule/distribution membership confers no current rights
or scientific approval. The authenticated caller owns the stable transaction
and its rollback, and must install a finite <=10s statement timeout first.
"""
from __future__ import annotations

import asyncio
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from models.db import Base
from services.research_release_manifest import canonical

VERSION = "scientific-result-impact/1.0.0"
MAX_QUERY_ROWS = 1000
MAX_NODES = 2000
MAX_RELATIONS = 4000
MAX_BYTES = 1024 * 1024
MAX_SECONDS = 10
TABLES = (
    "event_properties", "research_events", "ml_example_inputs", "ml_examples", "ml_dataset_snapshots",
    "snapshot_event_memberships", "source_snapshots", "event_evidence", "research_release_pins",
    "research_releases", "research_publication_proposals", "research_distribution_dependencies",
    "research_distribution_packages",
)
SCOPE = (
    "exact_target_property_event_pair",
    "direct_ml_input_property_and_event_references",
    "owning_ml_examples_and_dataset_snapshots",
    "direct_event_snapshot_memberships",
    "one_hop_derives_from_input_event_references",
    "reached_row_frozen_pins_and_release_references",
    "exact_release_publication_proposal_references",
    "exact_distribution_dependency_and_capsule_release_references",
)
UNSUPPORTED_SCOPES = (
    "transitive_event_and_feature_dependencies",
    "property_specific_causality_of_event_context_or_sibling_results",
    "label_claims_not_reached_through_explicit_ml_inputs",
    "unregistered_json_text_formula_or_sample_name_matches",
    "file_backed_releases_cached_answers_and_external_vector_state",
    "scientific_validity_refresh_completion_or_current_distribution_authorization",
    "dependencies_created_after_this_database_snapshot",
)


class ScientificResultImpactError(ValueError):
    """A static, private, fail-closed inspection error."""


class ScientificResultImpactLimitError(ScientificResultImpactError):
    """No partial list may be presented as complete for the declared scope."""


class ScientificResultImpactUnavailable(ScientificResultImpactError):
    """A transient SQL/deadline failure, not invalid user input."""


def _uuid(value):
    if isinstance(value, UUID):
        # asyncpg's native UUID is a UUID subclass; preserve its exact identity.
        return UUID(str(value))
    if type(value) is str:
        try:
            parsed = UUID(value)
        except ValueError:
            pass
        else:
            if str(parsed) == value:
                return parsed
    raise ScientificResultImpactError("scientific_result_impact_invalid_identity")


def _table(name):
    return Base.metadata.tables[name]


class _Inventory:
    def __init__(self):
        self.items = set()
        self.nodes = set()
        self.item_bytes = 0

    def add(self, table, row_id, relation, via_table, via_id):
        item = (table, str(row_id), relation, via_table, str(via_id))
        if item in self.items:
            return
        node = item[:2]
        if len(self.items) >= MAX_RELATIONS or (node not in self.nodes and len(self.nodes) >= MAX_NODES):
            raise ScientificResultImpactLimitError("scientific_result_impact_graph_limit")
        item_bytes = len(canonical(dict(zip(("table", "row_id", "relation", "via_table", "via_id"), item))))
        if self.item_bytes + item_bytes + 1 > MAX_BYTES:
            raise ScientificResultImpactLimitError("scientific_result_impact_byte_limit")
        self.items.add(item)
        self.nodes.add(node)
        self.item_bytes += item_bytes + 1

    def ids(self, table):
        return {identifier for name, identifier in self.nodes if name == table}

    def document(self):
        result = {"version": VERSION, "scope": list(SCOPE), "unsupported_scopes": list(UNSUPPORTED_SCOPES),
                  "complete_for_scope": True,
                  "counts": {**{name: len(self.ids(name)) for name in TABLES},
                             "total_nodes": len(self.nodes), "total_relations": len(self.items)},
                  "items": [dict(zip(("table", "row_id", "relation", "via_table", "via_id"), item))
                            for item in sorted(self.items)]}
        if len(canonical(result)) > MAX_BYTES:
            raise ScientificResultImpactLimitError("scientific_result_impact_byte_limit")
        return result


async def _rows(db, statement):
    # LIMIT bounds returned narrow identity tuples, not scan effort. The caller's
    # statement deadline and the whole-operation deadline bound execution time.
    rows = (await db.execute(statement.limit(MAX_QUERY_ROWS + 1))).all()
    if len(rows) > MAX_QUERY_ROWS:
        raise ScientificResultImpactLimitError("scientific_result_impact_query_limit")
    return rows


def _objects(inventory):
    return sa.values(sa.column("table_name", sa.String(100)), sa.column("row_id", sa.String(200)),
                     name="scientific_impact_objects").data(sorted(inventory.nodes))


async def _collect(db, property_id, event_id):
    props, events = _table("event_properties"), _table("research_events")
    if not await _rows(db, sa.select(props.c.id).select_from(props.join(events, events.c.id == props.c.event_id))
                       .where(props.c.id == property_id, props.c.event_id == event_id)):
        raise ScientificResultImpactError("scientific_result_impact_target_mismatch_or_missing")
    inventory = _Inventory()
    inventory.add("research_events", event_id, "target_event", "research_events", event_id)
    inventory.add("event_properties", property_id, "target_property", "research_events", event_id)

    inputs, examples, datasets = (_table(name) for name in ("ml_example_inputs", "ml_examples", "ml_dataset_snapshots"))
    rows = await _rows(db, sa.select(inputs.c.id, inputs.c.input_property_id, inputs.c.input_event_id,
        examples.c.id, datasets.c.id).select_from(inputs.join(examples, examples.c.id == inputs.c.example_id)
        .join(datasets, datasets.c.id == examples.c.dataset_snapshot_id)).where(inputs.c.input_event_id == event_id))
    # The required property+event composite FK and input-shape constraint make
    # every property reference an event reference too. A single event predicate
    # is exact here and needs only one reverse input index, not an unindexed OR.
    for input_id, input_property, input_event, example_id, dataset_id in rows:
        if input_property == property_id:
            inventory.add("ml_example_inputs", input_id, "input_property_reference", "event_properties", property_id)
        if input_event == event_id:
            inventory.add("ml_example_inputs", input_id, "input_event_reference", "research_events", event_id)
        inventory.add("ml_examples", example_id, "input_owner", "ml_example_inputs", input_id)
        inventory.add("ml_dataset_snapshots", dataset_id, "example_dataset_membership", "ml_examples", example_id)

    members = _table("snapshot_event_memberships")
    for member_id, snapshot_id in await _rows(db, sa.select(members.c.id, members.c.snapshot_id).where(members.c.event_id == event_id)):
        inventory.add("snapshot_event_memberships", member_id, "event_membership", "research_events", event_id)
        inventory.add("source_snapshots", snapshot_id, "membership_snapshot", "snapshot_event_memberships", member_id)

    evidence = _table("event_evidence")
    for edge_id, output_event, input_property in await _rows(db, sa.select(evidence.c.id, evidence.c.event_id,
            evidence.c.input_property_id).where(evidence.c.input_event_id == event_id, evidence.c.link_type == "derives_from")):
        inventory.add("event_evidence", edge_id, "derives_from_input_event", "research_events", event_id)
        if input_property == property_id:
            inventory.add("event_evidence", edge_id, "derives_from_input_property", "event_properties", property_id)
        inventory.add("research_events", output_event, "one_hop_derivation_output", "event_evidence", edge_id)

    pins, selected = _table("research_release_pins"), _objects(inventory)
    for pin_id, release_id, table_name, row_id in await _rows(db, sa.select(pins.c.id, pins.c.release_id,
            pins.c.table_name, pins.c.row_id).select_from(pins.join(selected,
                sa.and_(pins.c.table_name == selected.c.table_name, pins.c.row_id == selected.c.row_id)))):
        inventory.add("research_release_pins", pin_id, "historical_exact_row_pin", table_name, row_id)
        inventory.add("research_releases", release_id, "historical_pin_release", "research_release_pins", pin_id)

    release_ids = {_uuid(identifier) for identifier in inventory.ids("research_releases")}
    if release_ids:
        proposals = _table("research_publication_proposals")
        for proposal_id, release_id in await _rows(db, sa.select(proposals.c.id, proposals.c.release_id)
                                                 .where(proposals.c.release_id.in_(sorted(release_ids)))):
            inventory.add("research_publication_proposals", proposal_id, "historical_release_proposal", "research_releases", release_id)

    dependencies, selected = _table("research_distribution_dependencies"), _objects(inventory)
    for dependency_id, package_id, table_name, row_id in await _rows(db, sa.select(dependencies.c.id,
            dependencies.c.package_id, dependencies.c.table_name, dependencies.c.row_id).select_from(dependencies.join(selected,
                sa.and_(dependencies.c.table_name == selected.c.table_name, dependencies.c.row_id == selected.c.row_id)))):
        inventory.add("research_distribution_dependencies", dependency_id, "historical_exact_row_dependency", table_name, row_id)
        inventory.add("research_distribution_packages", package_id, "historical_dependency_package", "research_distribution_dependencies", dependency_id)
    if release_ids:
        columns = [dependencies.c[f"capsule_release_{index}"] for index in range(8)]
        rows = await _rows(db, sa.select(dependencies.c.id, dependencies.c.package_id, *columns)
                          .where(sa.or_(*(column.in_(sorted(release_ids)) for column in columns))))
        for dependency_id, package_id, *capsules in rows:
            for release_id in set(capsules) & release_ids:
                inventory.add("research_distribution_dependencies", dependency_id, "historical_capsule_reference", "research_releases", release_id)
            inventory.add("research_distribution_packages", package_id, "historical_dependency_package", "research_distribution_dependencies", dependency_id)
    return inventory.document()


async def inspect_result_impact(db, *, property_id: UUID, event_id: UUID):
    """Return only complete declared-scope identities, with no hidden transaction.

    No settings, rows, locks/epochs, notices, permission or approval are changed.
    Failures require the caller to roll back its own transaction. Authentication
    and the meaning of a pending/accepted result remain the caller's concern.
    """
    property_id, event_id = _uuid(property_id), _uuid(event_id)
    if db.new or db.dirty or db.deleted:
        raise ScientificResultImpactError("scientific_result_impact_clean_session_required")
    try:
        async with asyncio.timeout(MAX_SECONDS):
            with db.no_autoflush:
                isolation = (await db.execute(sa.text("SHOW transaction_isolation"))).scalar_one()
                if isolation not in {"repeatable read", "serializable"}:
                    raise ScientificResultImpactError("scientific_result_impact_stable_snapshot_required")
                timeout = (await db.execute(sa.text("SELECT setting::bigint FROM pg_settings WHERE name='statement_timeout'"))).scalar_one()
                if not 0 < timeout <= MAX_SECONDS * 1000:
                    raise ScientificResultImpactError("scientific_result_impact_statement_deadline_required")
                return await _collect(db, property_id, event_id)
    except (TimeoutError, SQLAlchemyError) as exc:
        raise ScientificResultImpactUnavailable("scientific_result_impact_database_unavailable") from exc
