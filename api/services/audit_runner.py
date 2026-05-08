"""Run the audit_rules registry, persist counts in audit_reports.

Invoked by the lifespan ``_nightly_data_audit`` task at 20:00 UTC
(== 04:00 Beijing). One run = one transaction per rule so a regex
error in one rule does not block the others.

For each rule:

1. Run the UPDATE that flips needs_review=TRUE on matching rows.
   We skip rows that already have a matching ``admin_decision`` so
   admin overrides survive subsequent runs.
2. Snapshot the first 10 ids that the rule now points at (for the
   admin UI's "what got flagged" sample).
3. Look up yesterday's count for the same rule to compute
   ``delta_vs_previous`` — useful for spotting regressions.
4. Insert one row into ``audit_reports``.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.audit_rules import RULES, AuditRule

log = logging.getLogger(__name__)


async def _run_rule(session: AsyncSession, rule: AuditRule) -> dict:
    """Execute a single rule. Returns a dict with the flag count and
    sample ids; the runner aggregates these into the report rows."""
    # Critical rules flip needs_review; warn/info rules just count
    # (we still want them in audit_reports for trends, but they
    # don't hide the row from default views).
    if rule.severity == "critical":
        update_sql = f"""
            {rule.setup}
            UPDATE materials
            SET needs_review = TRUE,
                review_reason = '{rule.name}'
            WHERE needs_review = FALSE
              AND (admin_decision IS NULL
                   OR admin_decision->>'rule' != '{rule.name}')
              AND ({rule.predicate});
        """
        result = await session.execute(text(update_sql))
        flagged = result.rowcount or 0
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
    # rules they're rows that *just got* flagged.
    if rule.severity == "critical":
        sample_sql = """
            SELECT id FROM materials
            WHERE review_reason = :name
            ORDER BY id
            LIMIT 10;
        """
        sample_rows = await session.execute(text(sample_sql), {"name": rule.name})
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

    return {"flagged": flagged, "sample_ids": sample_ids}


async def run_audit(session: AsyncSession) -> dict[str, int]:
    """Run every rule in the registry, return ``{rule_name: count}``.

    Each rule runs in its own transaction so a malformed predicate
    on one rule doesn't take the whole audit down. The session
    passed in is the outer caller's; we ``commit()`` per rule and
    re-use it for the next.
    """
    started_at = datetime.now(timezone.utc)
    summary: dict[str, int] = {}

    for rule in RULES:
        try:
            outcome = await _run_rule(session, rule)
            await session.commit()
        except Exception:  # noqa: BLE001
            log.exception("audit rule %s failed; rolling back its tx",
                          rule.name)
            await session.rollback()
            outcome = {"flagged": -1, "sample_ids": []}

        # Look up yesterday's count for delta. NULL is fine on the
        # first night the rule exists.
        prev = await session.execute(
            text("""
                SELECT rows_flagged FROM audit_reports
                WHERE rule_name = :name
                ORDER BY started_at DESC
                LIMIT 1;
            """),
            {"name": rule.name},
        )
        prev_count = prev.scalar_one_or_none()
        delta = (outcome["flagged"] - prev_count) if prev_count is not None else None

        await session.execute(
            text("""
                INSERT INTO audit_reports
                  (started_at, completed_at, rule_name, severity,
                   rows_flagged, delta_vs_previous, sample_ids)
                VALUES
                  (:started, :completed, :name, :sev,
                   :rows, :delta, CAST(:samples AS jsonb))
            """),
            {
                "started":   started_at,
                "completed": datetime.now(timezone.utc),
                "name":      rule.name,
                "sev":       rule.severity,
                "rows":      outcome["flagged"],
                "delta":     delta,
                "samples":   json.dumps(outcome["sample_ids"]),
            },
        )
        await session.commit()
        summary[rule.name] = outcome["flagged"]

        if outcome["flagged"] > 0:
            log.info(
                "audit rule %-40s flagged=%d delta=%s severity=%s",
                rule.name, outcome["flagged"], delta, rule.severity,
            )

    log.info(
        "nightly audit done: %d rules, %d total new flags",
        len(RULES),
        sum(v for v in summary.values() if v > 0),
    )
    return summary
