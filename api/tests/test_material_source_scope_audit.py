"""Actual SQL audit/scoped-read integration; disposable guarded runner only."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from models.db import AuditReport, Material, Paper, get_session_factory
from services import audit_runner
from services.audit_rules import ANOMALY_RULE, ANOMALY_RULE_NAME, rule_by_name
from services.material_source_scope import current_visibility_allows_view
from services.material_visibility_adapter import prepare_material_views


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    # Transaction teardown must run on the same loop as the test's SQL. Remove
    # only this test's explicitly tracked disposable materials after rollback.
    async with get_session_factory()() as session:
        try:
            yield session
        finally:
            await session.rollback()
            identifiers = session.info.get("scope_audit_materials", [])
            if identifiers:
                await session.execute(delete(Material).where(Material.id.in_(identifiers)))
                await session.commit()


async def seed(db, *, held_status="retracted", held_tc=40, good_tc=10, **changes):
    token = uuid4().hex
    papers = [Paper(id=f"paper:scope-audit:{tag}:{token}", title="Synthetic source audit",
                    authors=[], source="arxiv", abstract="Synthetic test fixture, not scientific evidence.", status=status)
              for tag, status in (("good", "published"), ("held", held_status))]
    records = [{"paper_id": paper.id, "formula": "Nb", "tc_kelvin": tc,
                "pressure_gpa": 0, "pressure_state": "explicit_ambient",
                "knowledge_origin": "Observed", "source_role": "primary"}
               for paper, tc in zip(papers, (good_tc, held_tc), strict=True)]
    material = Material(**{
        "id": f"000:scope-audit:{token}", "formula": "Nb", "formula_normalized": f"scope-audit-{token}",
        "family": "conventional", "status": "active_research", "needs_review": False,
        "records": records, "tc_max": held_tc, "total_papers": 2,
        "admin_decision": {"action": "legacy override", "private_note": "PRIVATE-SCOPE-AUDIT"}, **changes,
    })
    db.add_all([*papers, material])
    db.info.setdefault("scope_audit_materials", []).append(material.id)
    await db.flush()
    return material, papers


def source_rule(material):
    original = rule_by_name("source_eligibility_review_required")
    return replace(original, predicate=f"({original.predicate}) AND materials.id = '{material.id}'")


async def current_view(db, material):
    return (await prepare_material_views(db, [material]))[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["retracted", "withdrawn", "corrected", "disputed"])
async def test_source_audit_counts_mixed_matches_without_new_global_hold(db_session, status):
    material, _ = await seed(db_session, held_status=status)
    raw, notes = deepcopy(material.records), deepcopy(material.admin_decision)
    updated = material.updated_at
    rule = source_rule(material)
    before = (await current_view(db_session, material)).visibility
    first = await audit_runner._run_rule(db_session, rule)
    second = await audit_runner._run_rule(db_session, rule)
    assert first == second == {"flagged": 1, "sample_ids": [material.id],
        "suggested_fixes": [{"material_id": material.id, "action": "retain_raw_source_scoped"}]}
    await db_session.refresh(material)
    assert material.needs_review is False and material.review_reason is None
    assert material.updated_at == updated
    assert material.records == raw and material.admin_decision == notes
    assert material.tc_max == 40 and not material.retracted and not material.disputed
    after = (await current_view(db_session, material)).visibility
    assert after == before and current_visibility_allows_view(after)


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"needs_review": True, "review_reason": "existing explicit hold"},
    {"status": "pending"}, {"disputed": True}, {"retracted": True},
    {"review_reason": "provenance_quarantine_original"},
])
async def test_source_audit_does_not_clear_or_override_global_governance(db_session, changes):
    material, _ = await seed(db_session, **changes)
    original_reason = material.review_reason
    result = await audit_runner._run_rule(db_session, source_rule(material))
    assert result["flagged"] == 1
    assert result["suggested_fixes"][0]["action"] == "retain_raw_and_review"
    await db_session.refresh(material)
    assert material.needs_review is True
    assert material.review_reason == (original_reason or "source_eligibility_review_required")
    assert (await current_view(db_session, material)).source_scope is None


@pytest.mark.asyncio
async def test_parent_hold_prevents_audit_exception(db_session):
    parent, _ = await seed(db_session, needs_review=True)
    child, _ = await seed(db_session, parent_material_id=parent.id)
    result = await audit_runner._run_rule(db_session, source_rule(child))
    assert result["suggested_fixes"][0]["action"] == "retain_raw_and_review"
    await db_session.refresh(child)
    assert child.needs_review is True
    assert parent.needs_review is True


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["unknown", "missing", "record_hold", "all_anomalous", "record_quarantine"])
async def test_no_eligible_record_does_not_suppress_source_audit_hold(db_session, case):
    material, papers = await seed(db_session)
    if case == "unknown":
        papers[0].status = "indexed"
    elif case == "missing":
        material.records = [{**material.records[0], "paper_id": "source-not-present"}, material.records[1]]
    elif case == "record_hold":
        material.records = [{**material.records[0], "needs_review": True}, material.records[1]]
    elif case == "all_anomalous":
        material.records = [{**material.records[0], "tc_kelvin": 900}, material.records[1]]
    else:
        material.records = [material.records[0], {**material.records[1], "provenance_status": "quarantined"}]
    await db_session.flush()
    result = await audit_runner._run_rule(db_session, source_rule(material))
    assert result["flagged"] == 1
    assert result["suggested_fixes"][0]["action"] == "retain_raw_and_review"
    await db_session.refresh(material)
    assert material.needs_review is True


@pytest.mark.asyncio
async def test_anomaly_audit_retains_full_findings_and_raw_but_not_new_global_hold(db_session):
    material, _ = await seed(db_session, held_tc=900)
    raw = deepcopy(material.records)
    first = await audit_runner._run_rule(db_session, ANOMALY_RULE)
    second = await audit_runner._run_rule(db_session, ANOMALY_RULE)
    assert first == second
    assert first["flagged"] >= 1 and material.id in first["sample_ids"]
    finding = next(row for row in first["suggested_fixes"] if row["material_id"] == material.id)
    assert finding["action"] == "retain_raw_source_scoped"
    assert finding["rule_counts"]
    await db_session.refresh(material)
    assert material.anomaly_review["needs_review"] is True
    assert material.anomaly_review["counts"]["total_records"] == 2
    assert material.anomaly_review["counts"]["review_required"] == 1
    assert material.records == raw and material.tc_max == 900
    assert material.needs_review is False and material.review_reason is None
    view = await current_view(db_session, material)
    assert view.source_scope.eligible_indices == (0,)
    assert current_visibility_allows_view(view.visibility)


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"held_status": "published"}, {"good_tc": 900}, {"needs_review": True}])
async def test_anomaly_audit_keeps_original_gate_without_a_valid_source_partition(db_session, changes):
    material, _ = await seed(db_session, held_tc=900, **changes)
    result = await audit_runner._run_rule(db_session, ANOMALY_RULE)
    assert material.id in result["sample_ids"]
    finding = next(row for row in result["suggested_fixes"] if row["material_id"] == material.id)
    assert finding["action"] == "retain_raw_and_review"
    await db_session.refresh(material)
    assert material.needs_review is True
    if not changes.get("needs_review"):
        assert material.review_reason == ANOMALY_RULE_NAME


@pytest.mark.asyncio
async def test_later_source_loss_creates_hold_that_plain_reactivation_does_not_clear(db_session):
    material, papers = await seed(db_session)
    rule = source_rule(material)
    await audit_runner._run_rule(db_session, rule)
    assert material.needs_review is False
    papers[0].status = "retracted"
    await db_session.flush()
    await audit_runner._run_rule(db_session, rule)
    assert material.needs_review is True
    papers[0].status = "published"
    await db_session.flush()
    result = await audit_runner._run_rule(db_session, rule)
    assert result["suggested_fixes"][0]["action"] == "retain_raw_and_review"
    assert material.needs_review is True


@pytest.mark.asyncio
async def test_current_match_reports_keep_source_scoped_action_not_approval(db_session, monkeypatch):
    material, _ = await seed(db_session)
    mid = material.id
    await db_session.commit()
    monkeypatch.setattr(audit_runner, "RULES", [source_rule(material)])
    await audit_runner.run_audit(db_session)
    await audit_runner.run_audit(db_session)
    reports = (await db_session.execute(select(AuditReport).where(
        AuditReport.rule_name == "source_eligibility_review_required")
        .order_by(AuditReport.started_at.desc()).limit(2))).scalars().all()
    assert [report.rows_flagged for report in reports] == [1, 1]
    assert reports[0].delta_vs_previous == 0
    assert reports[0].sample_ids == [mid]
    assert reports[0].suggested_fixes[0]["basis"] == "current_materials"
    assert reports[0].suggested_fixes[1] == {"material_id": mid, "action": "retain_raw_source_scoped"}
    await db_session.refresh(material)
    assert material.needs_review is False


@pytest.mark.asyncio
async def test_audit_outer_rollback_discards_all_new_review_and_flag_changes(db_session):
    scoped_material, _ = await seed(db_session, held_tc=900)
    unscoped_material, _ = await seed(db_session, held_tc=900, held_status="published")
    scoped_id, unscoped_id = scoped_material.id, unscoped_material.id
    await db_session.commit()
    original = {row.id: (row.needs_review, deepcopy(row.anomaly_review), deepcopy(row.records), row.review_reason)
                for row in (scoped_material, unscoped_material)}
    await audit_runner._run_rule(db_session, ANOMALY_RULE)
    assert scoped_material.needs_review is False and unscoped_material.needs_review is True
    assert scoped_material.anomaly_review["needs_review"] is True
    await db_session.rollback()
    rows = (await db_session.execute(select(Material).where(Material.id.in_([scoped_id, unscoped_id])))).scalars().all()
    assert {row.id: (row.needs_review, row.anomaly_review, row.records, row.review_reason)
            for row in rows} == original


@pytest.mark.asyncio
async def test_other_critical_rules_still_apply_to_scoped_material(db_session):
    material, _ = await seed(db_session, is_unconventional=True)
    rule = rule_by_name("family_unconv_contradiction")
    rule = replace(rule, predicate=f"({rule.predicate}) AND id='{material.id}'")
    await audit_runner._run_rule(db_session, rule)
    await db_session.refresh(material)
    assert material.needs_review is True
    assert material.review_reason == "family_unconv_contradiction"
