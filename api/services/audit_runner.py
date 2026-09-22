"""Run the audit_rules registry, persist counts in audit_reports.

Invoked by the lifespan ``_nightly_data_audit`` task at 20:00 UTC
(== 04:00 Beijing). Scheduled runs share one coordinator transaction; a failed
rule rolls back all effects. Manual callers retain the per-rule commit mode.

For each rule:

1. Recompute raw-preserving numeric findings using the shared versioned
   policy. Legacy administrative notes never override scientific findings.
   Legacy notes never exempt a row from a fresh governance-rule evaluation.
2. Snapshot the first 10 ids that the rule now points at (for the
   admin UI's "what got flagged" sample).
3. Look up yesterday's count for the same rule to compute
   ``delta_vs_previous`` — useful for spotting regressions.
4. Insert one row into ``audit_reports``.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.background_jobs_v1 import JOB_LOCK_KEYS
from models.db import Material
from services.audit_rules import ANOMALY_RULE_NAME, RULES, AuditRule
from services.material_anomalies import material_review, review_context
from services.material_source_scope import SourceScopeError
from services.material_visibility_adapter import prepare_material_views

log = logging.getLogger(__name__)
AUDIT_METRIC_VERSION = "audit-rule-matches/2.0.0"


def _metric_marker(rule: AuditRule) -> list[dict]:
    return [{"kind": "audit_count_basis", "version": AUDIT_METRIC_VERSION,
             "basis": "current_materials" if rule.severity == "critical" else "current_unheld_materials"}]


def _source_scoped(view) -> bool:
    """Only a verified complete partition can avoid a *new* material hold."""
    if view.source_scope is None:
        return False
    try:
        return bool(view.current_records())
    except SourceScopeError:
        return False


async def _run_source_eligibility_policy(session: AsyncSession, rule: AuditRule) -> dict:
    """Count every source-rule match; retain separable records without flagging all.

    The current source rule has no CTE setup. Its predicate remains the audit's
    denominator, including already held rows. This never clears a persisted
    hold or modifies retained scientific records.
    """
    if rule.setup:
        raise ValueError("source_audit_rule_setup_unsupported")
    last_id, affected, sample_ids, findings = None, 0, [], []
    while True:
        stmt = select(Material).where(text(rule.predicate)).order_by(Material.id).limit(200).with_for_update()
        if last_id is not None:
            stmt = stmt.where(Material.id > last_id)
        rows = (await session.execute(stmt)).scalars().all()
        if not rows:
            break
        views = await prepare_material_views(session, rows)
        for material, view in zip(rows, views, strict=True):
            scoped = _source_scoped(view)
            affected += 1
            if len(sample_ids) < 10:
                sample_ids.append(material.id)
                findings.append({"material_id": material.id,
                                 "action": "retain_raw_source_scoped" if scoped else "retain_raw_and_review"})
            if not scoped and material.needs_review is False:
                material.needs_review = True
                material.review_reason = material.review_reason or rule.name
        last_id = rows[-1].id
        await session.flush()
    return {"flagged": affected, "sample_ids": sample_ids, "suggested_fixes": findings}


async def _run_anomaly_policy(session: AsyncSession) -> dict:
    """Recompute derived findings without changing records or scientific values.

    Count all currently affected materials (not only newly hidden rows), making
    trends repeatable. Existing governance flags, quarantines and holds are never
    cleared. A free-text legacy admin override is not a scientific acceptance.
    """
    last_id = None
    affected = 0
    sample_ids = []
    findings = []
    while True:
        stmt = select(Material).order_by(Material.id).limit(200).with_for_update()
        if last_id is not None:
            stmt = stmt.where(Material.id > last_id)
        rows = (await session.execute(stmt)).scalars().all()
        if not rows:
            break
        views = await prepare_material_views(session, rows)
        for material, view in zip(rows, views, strict=True):
            scoped = _source_scoped(view)
            review = material_review(material.records, scope_id=material.id, context=review_context(material))
            if material.anomaly_review != review:
                material.anomaly_review = review
            if review["needs_review"]:
                affected += 1
                if len(sample_ids) < 10:
                    sample_ids.append(material.id)
                    findings.append({"material_id": material.id, "policy_version": review["version"],
                                     "rule_counts": review["rule_counts"],
                                     "action": "retain_raw_source_scoped" if scoped else "retain_raw_and_review"})
                if not scoped and not material.needs_review:
                    material.needs_review = True
                    material.review_reason = material.review_reason or ANOMALY_RULE_NAME
        last_id = rows[-1].id
        await session.flush()
    return {"flagged": affected, "sample_ids": sample_ids, "suggested_fixes": findings}


async def _run_rule(session: AsyncSession, rule: AuditRule) -> dict:
    """Execute a single rule. Returns a dict with the flag count and
    sample ids; the runner aggregates these into the report rows."""
    if rule.name == ANOMALY_RULE_NAME:
        return await _run_anomaly_policy(session)
    if rule.name == "source_eligibility_review_required":
        return await _run_source_eligibility_policy(session, rule)
    # Critical rules flip needs_review; warn/info rules just count
    # (we still want them in audit_reports for trends, but they
    # don't hide the row from default views).
    if rule.severity == "critical":
        update_sql = f"""
            {rule.setup}
            UPDATE materials
            SET needs_review = TRUE,
                review_reason = COALESCE(review_reason, '{rule.name}')
            WHERE needs_review = FALSE
              AND ({rule.predicate});
        """
        await session.execute(text(update_sql))
        # Report current matches, not only this run's mutations. This makes a
        # repeated evaluation comparable and does not call an old note a review
        # of later evidence. Existing unrelated holds and private notes survive.
        count_sql = f"""
            {rule.setup}
            SELECT COUNT(*) FROM materials WHERE ({rule.predicate});
        """
        result = await session.execute(text(count_sql))
        flagged = int(result.scalar_one() or 0)
    else:
        # Count without flagging.
        count_sql = f"""
            {rule.setup}
            SELECT COUNT(*) FROM materials
            WHERE needs_review = FALSE
              AND ({rule.predicate});
        """
        result = await session.execute(text(count_sql))
        flagged = int(result.scalar_one() or 0)

    # Pull up to 10 sample ids — for warn/info rules they're rows
    # that *would* match (still needs_review=FALSE); for critical
    # rules they match the current predicate, even with an older unrelated hold.
    if rule.severity == "critical":
        sample_sql = f"""
            {rule.setup}
            SELECT id FROM materials WHERE ({rule.predicate})
            ORDER BY id
            LIMIT 10;
        """
        sample_rows = await session.execute(text(sample_sql))
    else:
        sample_sql = f"""
            {rule.setup}
            SELECT id FROM materials
            WHERE needs_review = FALSE
              AND ({rule.predicate})
            ORDER BY id
            LIMIT 10;
        """
        sample_rows = await session.execute(text(sample_sql))
    sample_ids = [r[0] for r in sample_rows.fetchall()]

    # Run fix_query if present to get per-row suggested fixes.
    # Each row is (material_id, field, current_val, suggested_val).
    suggested_fixes: list[dict] = []
    if rule.fix_query and flagged > 0:
        try:
            fix_rows = await session.execute(text(rule.fix_query))
            for mid, field, cur, sug in fix_rows.fetchall():
                suggested_fixes.append({
                    "material_id": mid,
                    "field": field,
                    "current_value": cur,
                    "suggested_value": sug,
                })
        except Exception:  # noqa: BLE001
            log.warning("fix_query for rule %s failed", rule.name, exc_info=True)

    return {
        "flagged": flagged,
        "sample_ids": sample_ids,
        "suggested_fixes": suggested_fixes,
    }


async def run_audit(session: AsyncSession, *, commit: bool = True,
                    scheduled_for: datetime | None = None, cycle_id=None) -> dict[str, int]:
    """Run every rule in the registry, return ``{rule_name: count}``.

    Each rule runs in its own transaction so a malformed predicate
    on one rule doesn't take the whole audit down. The session
    passed in is the outer caller's; we ``commit()`` per rule and
    re-use it for the next. With ``commit=False``, use per-rule savepoints and
    let the background coordinator own the single outer commit or rollback.
    """
    if type(commit) is not bool:
        raise ValueError("commit must be Boolean")
    if scheduled_for is not None and (scheduled_for.tzinfo is None or scheduled_for.utcoffset() is None):
        raise ValueError("scheduled_for must identify an aware instant")
    if not commit and (scheduled_for is None or cycle_id is None):
        raise ValueError("Atomic scheduled audit requires a cycle and scheduled instant")
    if commit and (scheduled_for is not None or cycle_id is not None):
        raise ValueError("Manual audits cannot claim a scheduled cycle identity")
    started_at = scheduled_for.astimezone(UTC) if scheduled_for is not None else datetime.now(UTC)
    summary: dict[str, int] = {}

    for rule in RULES:
        if commit:
            # A manual rule's effect/report transaction cannot race a scheduled
            # owner. Unlike session locks this is safe across per-rule commits.
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": JOB_LOCK_KEYS["nightly_audit"]})
        try:
            async with session.begin_nested():
                outcome = await _run_rule(session, rule)
                if not commit and outcome["flagged"] < 0:
                    raise RuntimeError("Scheduled audit rule unavailable")
        except Exception:  # noqa: BLE001
            log.exception("audit rule %s failed; rolling back its tx",
                          rule.name)
            if not commit:
                # The coordinator rolls back every preceding rule's flags and
                # report together, then records the failed cycle separately.
                raise RuntimeError("Scheduled audit did not complete every rule") from None
            await session.rollback()
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": JOB_LOCK_KEYS["nightly_audit"]})
            outcome = {"flagged": -1, "sample_ids": []}

        # Compare only a successful report with the same count semantics.
        # Pre-SC08 critical reports counted *newly* flagged rows: subtracting
        # those from current matches would manufacture a data-quality spike.
        metric = _metric_marker(rule)
        prev = await session.execute(
            text("""
                SELECT rows_flagged FROM audit_reports AS report
                WHERE rule_name = :name
                  AND rows_flagged >= 0
                  AND suggested_fixes @> CAST(:metric AS jsonb)
                  AND started_at < :started
                  AND (:scheduled IS FALSE OR EXISTS (
                    SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(report.suggested_fixes)='array'
                        THEN report.suggested_fixes ELSE '[]'::jsonb END) AS marker
                    JOIN background_job_cycles AS cycle ON cycle.id::text=marker->>'cycle_id'
                    WHERE marker->>'kind'='background_cycle' AND marker->>'version'='background-cycle/1.0.0'
                      AND cycle.job_name='nightly_audit' AND cycle.status='succeeded'
                      AND cycle.scheduled_for=report.started_at))
                ORDER BY started_at DESC, id DESC
                LIMIT 1;
            """),
            {"name": rule.name, "metric": json.dumps(metric), "started": started_at, "scheduled": not commit},
        )
        prev_count = prev.scalar_one_or_none()
        delta = (outcome["flagged"] - prev_count) if prev_count is not None and outcome["flagged"] >= 0 else None

        await session.execute(
            text("""
                INSERT INTO audit_reports
                  (started_at, completed_at, rule_name, severity,
                   rows_flagged, delta_vs_previous, sample_ids,
                   suggested_fix, suggested_fixes)
                VALUES
                  (:started, :completed, :name, :sev,
                   :rows, :delta, CAST(:samples AS jsonb),
                   :fix_text, CAST(:fixes AS jsonb))
            """),
            {
                "started":   started_at,
                "completed": datetime.now(UTC),
                "name":      rule.name,
                "sev":       rule.severity,
                "rows":      outcome["flagged"],
                "delta":     delta,
                "samples":   json.dumps(outcome["sample_ids"]),
                "fix_text":  rule.suggested_fix or None,
                "fixes":     json.dumps(metric + ([{"kind": "background_cycle", "version": "background-cycle/1.0.0",
                    "cycle_id": str(cycle_id), "scheduled_for": started_at.isoformat()}] if cycle_id is not None else [])
                    + outcome.get("suggested_fixes", [])),
            },
        )
        if commit:
            await session.commit()
        summary[rule.name] = outcome["flagged"]

        if outcome["flagged"] > 0:
            log.info(
                "audit rule %-40s flagged=%d delta=%s severity=%s",
                rule.name, outcome["flagged"], delta, rule.severity,
            )

    log.info(
        "nightly audit %s: %d rules, %d summed rule matches (not distinct materials)",
        "committed" if commit else "computed; outer commit pending",
        len(RULES),
        sum(v for v in summary.values() if v > 0),
    )
    return summary
