"""Explicit private label audit capture in one caller-owned read-only snapshot.

This new protocol does not rewrite a frozen capsule, source/review companion,
producer manifest or ML v1/v2/v3 implementation. Full audit admission is distinct
from scientific acceptance, public disclosure and permission to train a model.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from services.ml_review_capture import EXPORT_SCOPE as REVIEW_EXPORT_SCOPE
from services.ml_review_capture import MlReviewCaptureError, _audit
from services.ml_review_source_observation import (
    ReviewSourceError,
    account,
    capture_source_observation,
    equal,
    parse,
    read_rows,
)
from services.research_access import active_grant, require_research_admin
from services.research_release_manifest import canonical, verify_manifest
from services.scientific_result_subject import (
    ScientificSubjectError,
    capture_result_subject,
    identifier,
    require_read_session,
)

EXPORT_SCOPE = "ml_label_full_audit/1.0.0"
MAX_BYTES = 16 * 1024 * 1024
MAX_ROWS = 4000
MAX_SECONDS = 20
STATEMENT_TIMEOUT_MS = 5000


class MlLabelCaptureError(ValueError):
    """Static private capture failure, never a partial successful observation."""


class MlLabelCaptureUnavailable(MlLabelCaptureError):
    """The entire bounded snapshot could not be observed."""


def require(condition, code="ml_label_capture_unavailable"):
    if not condition:
        raise MlLabelCaptureError(code)


def _phase(budget, started, *, rows=0):
    """One cumulative ledger; completed phases never yield partial output.

    Old helpers retain their own preflight bounds. Their complete row counts
    are charged at the phase boundary, not reset for the label observation.
    Repeated captured rows in distinct phases are conservatively counted again.
    """
    require(type(rows) is int and rows >= 0)
    require(type(budget.get("rows")) is int and budget["rows"] + rows <= MAX_ROWS,
            "ml_label_capture_row_limit")
    budget["rows"] += rows
    require(type(budget.get("bytes")) is int and 0 <= budget["bytes"] <= MAX_BYTES,
            "ml_label_capture_byte_limit")
    require(time.monotonic() - started < MAX_SECONDS, "ml_label_capture_deadline")


async def _read_only(db):
    await require_read_session(db)
    row = (await db.execute(sa.text("""SELECT current_setting('transaction_read_only') AS read_only,
        (SELECT setting::bigint FROM pg_settings WHERE name='statement_timeout') AS timeout_ms"""))).mappings().one()
    require(row["read_only"] == "on", "ml_label_read_only_snapshot_required")
    require(type(row["timeout_ms"]) is int and 0 < row["timeout_ms"] <= STATEMENT_TIMEOUT_MS,
            "ml_label_statement_timeout_required")


def _normalized_binding(row):
    value = dict(row)
    stamp = datetime.fromisoformat(value["created_at"])
    require(stamp.tzinfo is not None, "ml_label_binding_timestamp_invalid")
    value["created_at"] = stamp.astimezone(timezone.utc).isoformat(timespec="microseconds")
    return value


async def _capture_feature_review(db, *, actor, grant, base_manifest, expected_base_manifest_sha256,
        source_companion, expected_source_companion_sha256, artifact_bytes, budget, started):
    """Unchanged review protocol, recaptured without an independent budget/tx."""
    from services.ml_feature_companion import _release
    from services.ml_feature_review_companion import (
        assemble_ml_review_companion,
        review_feature_inventory,
    )

    inventory = review_feature_inventory(base_manifest, artifact_bytes)
    release = await _release(db, base_hash=expected_base_manifest_sha256)
    require(canonical(release["manifest"]) == canonical(base_manifest)
            and str(release["id"]) == source_companion["base_release_id"], "ml_label_exact_base_required")
    bindings = await read_rows(db, "ml_feature_source_bindings", [str(release["id"])],
        column="base_release_id", byte_budget=budget, limit=500)
    _phase(budget, started, rows=len(bindings))
    actual_bindings = [_normalized_binding(parse(row["row_text"])) for row in bindings]
    expected_bindings = [_normalized_binding(row) for row in parse(canonical(source_companion["bindings"]).decode())]
    require(equal(actual_bindings, expected_bindings), "ml_label_binding_inventory_changed")
    admission = {"version": REVIEW_EXPORT_SCOPE, "actor_user_id": str(actor), "actor_grant_id": str(grant)}
    property_ids = sorted(inventory["property_pins"])
    audit_rows, heads = await _audit(db, property_ids, admission, budget)
    _phase(budget, started, rows=len(audit_rows))
    properties = []
    for property_id in property_ids:
        current = None
        if any(heads[property_id].values()):
            current = await capture_result_subject(db, property_id)
            account(budget, len(current.text.encode("utf-8")) + 256)
            _phase(budget, started, rows=len(current.data["rows"]))
        properties.append({"property_id": property_id,
            "frozen_row_sha256": inventory["property_pins"][property_id]["row_sha256"],
            "current_subject_text": current.text if current else None,
            "current_subject_sha256": current.sha256 if current else None, "heads": heads[property_id]})
    inputs = [{"input_id": input_id, "frozen_row_sha256": pin["row_sha256"],
        "binding_ids": sorted(row["id"] for row in source_companion["bindings"] if row["example_input_id"] == input_id)}
        for input_id, pin in sorted(inventory["input_pins"].items())]
    source = await capture_source_observation(db, base_manifest=base_manifest,
        source_companion=source_companion, property_ids=property_ids, byte_budget=budget)
    _phase(budget, started, rows=len(source["rows"]) + len(source["lifecycle"]))
    observation = {"version": "ml-review-observation/1.0.0", "capture_admission": admission,
        "properties": properties, "inputs": inputs, "audit_rows": audit_rows, "source_observation": source}
    value = assemble_ml_review_companion(base_manifest=base_manifest,
        expected_base_manifest_sha256=expected_base_manifest_sha256, source_companion=source_companion,
        expected_source_companion_sha256=expected_source_companion_sha256, observation=observation)
    _phase(budget, started)
    return value


async def capture_ml_label_companion(db, *, actor_user_id, expected_actor_grant_id, export_scope,
        base_manifest, expected_base_manifest_sha256, source_companion, expected_source_companion_sha256,
        review_companion, expected_review_companion_sha256, artifact_bytes):
    """Capture every frozen root label after exact feature-review recheck.

    The trusted caller supplies the authenticated actor and owns a clean READ
    ONLY UTC RR/SERIALIZABLE transaction. This function never commits, rolls
    back, changes session settings or opens a second connection. To observe a
    later committed change, the caller must start a new stable transaction.
    """
    from services.ml_feature_companion import decode_companion_artifacts, verify_feature_companion
    from services.ml_feature_review_companion import verify_ml_review_companion
    from services.ml_label_companion import assemble_ml_label_companion
    from services.ml_label_observation import capture_label_observation

    require(type(export_scope) is str and export_scope == EXPORT_SCOPE, "ml_label_export_scope_required")
    actor, grant = identifier(actor_user_id), identifier(expected_actor_grant_id)
    require(not (db.new or db.dirty or db.deleted), "ml_label_clean_session_required")
    started = time.monotonic()
    budget = {"bytes": 0, "rows": 0}
    try:
        async with asyncio.timeout(MAX_SECONDS):
            with db.no_autoflush:
                await _read_only(db)
                await require_research_admin(db, actor)
                await active_grant(db, actor, role="curator", grant_id=grant)
                verify_manifest(base_manifest, artifact_bytes=artifact_bytes,
                    expected_manifest_sha256=expected_base_manifest_sha256)
                verify_feature_companion(source_companion, base_manifest=base_manifest,
                    expected_base_manifest_sha256=expected_base_manifest_sha256,
                    expected_companion_sha256=expected_source_companion_sha256)
                retained = decode_companion_artifacts(source_companion)
                require(all(retained.get(key) == value for key, value in artifact_bytes.items()),
                        "ml_label_base_artifact_bytes_mismatch")
                verify_ml_review_companion(review_companion, base_manifest=base_manifest,
                    expected_base_manifest_sha256=expected_base_manifest_sha256, source_companion=source_companion,
                    expected_source_companion_sha256=expected_source_companion_sha256,
                    expected_review_companion_sha256=expected_review_companion_sha256)
                expected_admission = {"version": REVIEW_EXPORT_SCOPE, "actor_user_id": str(actor), "actor_grant_id": str(grant)}
                require(review_companion["observation"]["capture_admission"] == expected_admission,
                        "ml_label_review_actor_mismatch")
                _phase(budget, started)
                common = {"base_manifest": base_manifest, "expected_base_manifest_sha256": expected_base_manifest_sha256,
                    "source_companion": source_companion, "expected_source_companion_sha256": expected_source_companion_sha256}
                current = await _capture_feature_review(db, actor=actor, grant=grant, **common,
                    artifact_bytes=artifact_bytes, budget=budget, started=started)
                require(current["observation_sha256"] == review_companion["observation_sha256"],
                        "ml_label_feature_review_observation_changed")
                admission = {"version": EXPORT_SCOPE, "actor_user_id": str(actor), "actor_grant_id": str(grant)}
                observation = await capture_label_observation(db, base_manifest=base_manifest,
                    capture_admission=admission, byte_budget=budget)
                _phase(budget, started)
                result = assemble_ml_label_companion(**common, review_companion=review_companion,
                    expected_review_companion_sha256=expected_review_companion_sha256, observation=observation)
                require(len(canonical(result)) <= MAX_BYTES, "ml_label_capture_byte_limit")
                _phase(budget, started)
                return result
    except (TimeoutError, SQLAlchemyError) as exc:
        raise MlLabelCaptureUnavailable("ml_label_capture_unavailable") from exc
    except (ReviewSourceError, MlReviewCaptureError, ScientificSubjectError) as exc:
        raise MlLabelCaptureError(str(exc)) from None


async def recheck_ml_label_companion(db, *, label_companion, expected_label_companion_sha256, **capture_args):
    """Recheck in the supplied snapshot, never pretend an old transaction is fresh.

    Historical offline verification remains unchanged. The caller must end its
    previous snapshot and begin a fresh READ ONLY transaction for live updates.
    Nothing here confers training rights or overwrites the historical artifact.
    """
    from services.ml_label_companion import verify_ml_label_companion
    verify_ml_label_companion(label_companion, **{key: capture_args[key] for key in (
        "base_manifest", "expected_base_manifest_sha256", "source_companion", "expected_source_companion_sha256",
        "review_companion", "expected_review_companion_sha256")}, expected_label_companion_sha256=expected_label_companion_sha256)
    current = await capture_ml_label_companion(db, **capture_args)
    require(current["observation_sha256"] == label_companion["observation_sha256"], "ml_label_observation_changed")
    return {"version": "ml-label-recheck/1.0.0", "observation_sha256": current["observation_sha256"],
            "authority": dict(current["authority"])}
