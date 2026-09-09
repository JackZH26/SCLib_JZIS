"""Explicitly admitted, read-only full-audit capture for private ML replay.

This is an internal service, not an HTTP export capability. The trusted caller
owns a bounded stable transaction and supplies the authenticated actor. No old
capsule, producer manifest, role, decision or scientific row is modified.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from services.ml_review_source_observation import (
    MAX_BYTES,
    ReviewSourceError,
    account,
    capture_source_observation,
    equal,
    parse,
    read_rows,
)
from services.research_access import active_grant, require_research_admin
from services.research_release_manifest import canonical, digest, verify_manifest
from services.scientific_result_subject import (
    capture_result_subject,
    identifier,
    require_read_session,
)

EXPORT_SCOPE = "ml_review_full_audit/1.0.0"
MAX_SECONDS = 10
MAX_AUDIT_ROWS = 4000
MAX_REQUESTS = 200
MAX_REVIEWED = 200


class MlReviewCaptureError(ValueError):
    """Static capture failure; no partial or unauthorised audit result."""


class MlReviewCaptureUnavailable(MlReviewCaptureError):
    """The entire current snapshot could not be observed."""


def require(condition, reason="ml_review_capture_unavailable"):
    if not condition:
        raise MlReviewCaptureError(reason)


async def _audit(db, property_ids, admission, budget):
    initial = await read_rows(db, "scientific_result_decisions", property_ids,
        column="property_id", byte_budget=budget)
    target_rows = [parse(row["row_text"]) for row in initial]
    reviewed = {row["property_id"] for row in target_rows}
    require(len(reviewed) <= MAX_REVIEWED, "ml_review_reviewed_property_limit")
    heads = {key: {"extraction_fidelity": None, "scientific_result": None} for key in property_ids}
    predecessors = {row["predecessor_id"] for row in target_rows if row["predecessor_id"]}
    for row in target_rows:
        if row["id"] not in predecessors:
            require(row["scope"] in heads[row["property_id"]] and heads[row["property_id"]][row["scope"]] is None,
                    "ml_review_multiple_heads")
            heads[row["property_id"]][row["scope"]] = row["id"]
    found = {(row["table"], row["row_id"]): row for row in initial}
    pending = {("users", admission["actor_user_id"]), ("research_role_grants", admission["actor_grant_id"])}
    processed = set()
    while pending or found.keys() - processed:
        if pending:
            groups = defaultdict(set)
            for table, row_id in pending - found.keys():
                groups[table].add(row_id)
            for table, ids in sorted(groups.items()):
                rows = await read_rows(db, table, ids, byte_budget=budget,
                    limit=MAX_REQUESTS if table == "scientific_adjudication_requests" else MAX_AUDIT_ROWS)
                require({row["row_id"] for row in rows} == ids, "ml_review_audit_dependency_missing")
                found.update({(row["table"], row["row_id"]): row for row in rows})
            pending = set()
        for key in sorted(found.keys() - processed):
            table, row_id = key
            row = parse(found[key]["row_text"])
            processed.add(key)
            if table == "scientific_result_decisions":
                pending.update({("scientific_adjudication_requests", row["request_id"]),
                    ("scientific_result_subjects", row["subject_id"]), ("users", row["actor_user_id"]),
                    ("research_role_grants", row["actor_grant_id"])})
                pending.update((table, row[field]) for field in ("predecessor_id", "resolves_decision_id", "extraction_decision_id") if row[field])
            elif table == "scientific_adjudication_requests":
                require(sum(ref[0] == table for ref in found) <= MAX_REQUESTS, "ml_review_request_limit")
                siblings = await read_rows(db, "scientific_result_decisions", [row_id],
                    column="request_id", byte_budget=budget, limit=20)
                require(len(siblings) == row["item_count"], "ml_review_incomplete_request")
                for sibling in siblings:
                    ref = sibling["table"], sibling["row_id"]
                    require(ref not in found or sibling == found[ref])
                    found[ref] = sibling
                pending.update({("users", row["actor_user_id"]), ("research_role_grants", row["actor_grant_id"])})
            elif table == "research_role_grants":
                pending.update({("users", row["user_id"]), ("users", row["granted_by"])})
                revocations = await read_rows(db, "research_role_revocations", [row_id],
                    column="grant_id", byte_budget=budget, limit=1)
                found.update({(item["table"], item["row_id"]): item for item in revocations})
            elif table == "research_role_revocations":
                pending.update({("users", row["revoked_by"]), ("research_role_grants", row["grant_id"])})
        pending -= found.keys()
        require(len(found) + len(pending) <= MAX_AUDIT_ROWS, "ml_review_audit_row_limit")
    return [found[key] for key in sorted(found)], heads


async def capture_ml_review_companion(db, *, actor_user_id, expected_actor_grant_id,
        export_scope, base_manifest, expected_base_manifest_sha256, source_companion,
        expected_source_companion_sha256, artifact_bytes):
    """Capture complete declared inputs in the caller's current stable snapshot.

    Admin AND exact current curator AND explicit full-audit export scope are
    required. Ordinary reviewer/curator/admin flags alone confer no export.
    A successfully captured object still authenticates nothing when taken
    offline, and cannot license public disclosure or scientific training.
    """
    from services.ml_feature_companion import (
        _release,
        decode_companion_artifacts,
        verify_feature_companion,
    )
    from services.ml_feature_review_companion import (
        assemble_ml_review_companion,
        review_feature_inventory,
    )

    require(export_scope == EXPORT_SCOPE and type(export_scope) is str, "ml_review_export_scope_required")
    actor, grant_id = identifier(actor_user_id), identifier(expected_actor_grant_id)
    require(not (db.new or db.dirty or db.deleted), "ml_review_clean_session_required")
    started = time.monotonic()
    try:
        async with asyncio.timeout(MAX_SECONDS):
            with db.no_autoflush:
                await require_read_session(db)
                await require_research_admin(db, actor)
                await active_grant(db, actor, role="curator", grant_id=grant_id)
                # Validation is pure; current source holds are captured below,
                # never substituted into the immutable historical companion.
                verify_feature_companion(source_companion, base_manifest=base_manifest,
                    expected_base_manifest_sha256=expected_base_manifest_sha256,
                    expected_companion_sha256=expected_source_companion_sha256)
                verify_manifest(base_manifest, artifact_bytes=artifact_bytes,
                    expected_manifest_sha256=expected_base_manifest_sha256)
                retained_bytes = decode_companion_artifacts(source_companion)
                require(all(retained_bytes.get(key) == value for key, value in artifact_bytes.items()),
                    "ml_review_base_artifact_bytes_mismatch")
                inventory = review_feature_inventory(base_manifest, artifact_bytes)
                release = await _release(db, base_hash=expected_base_manifest_sha256)
                require(release["manifest"] == base_manifest and str(release["id"]) == source_companion["base_release_id"],
                        "ml_review_exact_base_required")
                budget = {"bytes": 0}
                bindings = await read_rows(db, "ml_feature_source_bindings", [str(release["id"])],
                    column="base_release_id", byte_budget=budget, limit=500)
                actual_bindings = [parse(row["row_text"]) for row in bindings]
                # SQL NUMERIC/float encodings are not reused as a new digest:
                # each immutable binding's own exact record pin is compared.
                expected = source_companion["bindings"]
                expected_bindings = parse(canonical(expected).decode())
                def normalized_binding(row):
                    result = dict(row)
                    stamp = datetime.fromisoformat(result["created_at"])
                    require(stamp.tzinfo is not None, "ml_review_binding_timestamp_invalid")
                    result["created_at"] = stamp.astimezone(timezone.utc).isoformat(timespec="microseconds")
                    return result
                require(equal([normalized_binding(row) for row in actual_bindings],
                              [normalized_binding(row) for row in expected_bindings]), "ml_review_binding_inventory_changed")
                admission = {"version": EXPORT_SCOPE, "actor_user_id": str(actor), "actor_grant_id": str(grant_id)}
                property_ids = sorted(inventory["property_pins"])
                audit_rows, heads = await _audit(db, property_ids, admission, budget)
                properties = []
                for property_id in property_ids:
                    current = None
                    if any(heads[property_id].values()):
                        current = await capture_result_subject(db, property_id)
                        account(budget, len(current.text.encode("utf-8")) + 256)
                    properties.append({"property_id": property_id,
                        "frozen_row_sha256": inventory["property_pins"][property_id]["row_sha256"],
                        "current_subject_text": current.text if current else None,
                        "current_subject_sha256": current.sha256 if current else None,
                        "heads": heads[property_id]})
                inputs = [{"input_id": input_id, "frozen_row_sha256": pin["row_sha256"],
                    "binding_ids": sorted(row["id"] for row in expected if row["example_input_id"] == input_id)}
                    for input_id, pin in sorted(inventory["input_pins"].items())]
                source = await capture_source_observation(db, base_manifest=base_manifest,
                    source_companion=source_companion, property_ids=property_ids, byte_budget=budget)
                observation = {"version": "ml-review-observation/1.0.0", "capture_admission": admission,
                    "properties": properties, "inputs": inputs, "audit_rows": audit_rows, "source_observation": source}
                result = assemble_ml_review_companion(base_manifest=base_manifest,
                    expected_base_manifest_sha256=expected_base_manifest_sha256,
                    source_companion=source_companion, expected_source_companion_sha256=expected_source_companion_sha256,
                    observation=observation)
                require(len(canonical(result)) <= MAX_BYTES, "ml_review_capture_byte_limit")
                require(result["observation_sha256"] == digest(observation))
                require(time.monotonic() - started < MAX_SECONDS, "ml_review_capture_deadline")
                return result
    except (TimeoutError, SQLAlchemyError) as exc:
        raise MlReviewCaptureUnavailable("ml_review_capture_unavailable") from exc
    except ReviewSourceError as exc:
        raise MlReviewCaptureError(str(exc)) from None


async def recheck_ml_review_companion(db, *, review_companion, expected_review_companion_sha256, **capture_args):
    """Compare against one newly captured caller-owned snapshot, not live rights.

    The old independently pinned artifact is never overwritten. A later call
    requires a new stable transaction to observe revocations committed later.
    This does not confer scientific, training or public-export authority.
    """
    from services.ml_feature_review_companion import verify_ml_review_companion
    verify_ml_review_companion(review_companion,
        **{key: capture_args[key] for key in ("base_manifest", "expected_base_manifest_sha256",
                                             "source_companion", "expected_source_companion_sha256")},
        expected_review_companion_sha256=expected_review_companion_sha256)
    current = await capture_ml_review_companion(db, **capture_args)
    require(current["observation_sha256"] == review_companion["observation_sha256"], "ml_review_observation_changed")
    return {"version": "ml-review-recheck/1.0.0", "observation_sha256": current["observation_sha256"],
            "authority": dict(current["authority"])}
