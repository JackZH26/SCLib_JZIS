"""Versioned projection of redundant reverse links, never scientific assertions.

Item source references remain fallible model proposals. This projection makes
their reverse index consistent only after the primary source checks pass. It
does not move a value, change a subject, or resolve a source-role disagreement.
Historical raw responses remain in the receipt and in their stage artifacts.
"""
from copy import deepcopy

from .contract import digest
from .inventory import Inventory, validate_inventory
from .sources import sha

PROJECTION_VERSION = "materials-inventory-link-projection/1"
BOOKKEEPING_ISSUES = frozenset({
    "inventory_disposition_item_mismatch",
    "inventory_item_without_target_disposition",
    "inventory_disposition_shape",
})


def assertions(inventory):
    """Everything except the redundant span-to-item lists must stay identical."""
    payload = deepcopy(inventory.model_dump())
    for disposition in payload["span_dispositions"]:
        disposition.pop("item_ids")
    return payload


def project_links(inventory, bundle):
    before = validate_inventory(inventory, bundle)
    blockers = [i for i in before["issues"] if i["code"] not in BOOKKEEPING_ISSUES]
    candidate = inventory.model_copy(deep=True)
    edits = []
    for index, disposition in enumerate(candidate.span_dispositions):
        expected = [item.id for item in inventory.items
                    if disposition.span_id in item.source_span_ids]
        path = f"/span_dispositions/{index}"
        # Never upgrade context/unread to a result span or erase a claimed
        # result span just because its primary item links are absent.
        if bool(expected) != (disposition.role == "result_assertions"):
            blockers.append({"code": "inventory_primary_source_role_conflict", "path": path})
        if disposition.role != "result_assertions" and disposition.item_ids:
            blockers.append({"code": "inventory_non_result_links_conflict", "path": path})
        if disposition.item_ids != expected:
            edits.append({"path": path + "/item_ids", "before": disposition.item_ids[:],
                          "after": expected[:]})
            disposition.item_ids = expected
    if not blockers:
        blockers.extend(validate_inventory(candidate, bundle)["issues"])
    if assertions(candidate) != assertions(inventory):
        raise ValueError("inventory_projection_changed_assertions")
    selected = inventory if blockers else candidate
    proof = {
        "schema": PROJECTION_VERSION,
        "source_inventory_sha256": digest(inventory.model_dump()),
        "selected_inventory_sha256": digest(selected.model_dump()),
        "assertions_sha256": digest(assertions(inventory)),
        "action": "rejected" if blockers else "projected" if edits else "unchanged",
        "edits": [] if blockers else edits,
        "blockers": blockers,
        "scientific_assertions_unchanged": True,
        "scientific_acceptance": False,
    }
    return selected, proof


def verify_inventory_projection(receipt, bundle):
    """Replay self-contained inventory receipts, including rejected projections."""
    if receipt['config'].get('workflow') in {'inventory_v14', 'inventory_v15', 'inventory_v16', 'inventory_v17'}:
        from .typed_inventory_v3 import verify_read
        return verify_read(receipt, bundle)
    if receipt['config'].get('workflow') == 'inventory_v13':
        from .typed_inventory_v2 import verify_read
        return verify_read(receipt, bundle)
    version = receipt["config"].get("inventory_link_projection_version")
    if version is None:
        return  # Historical attempts did not perform this projection.
    if version != PROJECTION_VERSION:
        raise ValueError("unsupported_inventory_projection_version")
    if "inventory" not in receipt:
        return  # Provider/JSON failure before a parsed inventory existed.
    reads = receipt.get("inventory_reads", [])
    if not reads:
        raise ValueError("inventory_projection_history_missing")
    stages = {s["name"]: s for s in receipt.get("stages", [])}
    selected = None
    for read in reads:
        stage = stages.get(read["stage"])
        raw = read.get("raw_output")
        if (stage is None or not isinstance(raw, str)
                or sha(raw.encode()) != stage.get("raw_output_sha256")):
            raise ValueError("inventory_projection_raw_hash_mismatch")
        selected, proof = project_links(Inventory.model_validate_json(raw), bundle)
        if proof != read.get("link_projection"):
            raise ValueError("inventory_projection_proof_mismatch")
    if selected.model_dump() != receipt["inventory"]:
        raise ValueError("inventory_projection_selection_mismatch")
