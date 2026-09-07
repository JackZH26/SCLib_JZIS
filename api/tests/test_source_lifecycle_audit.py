"""SC08 synthetic source changes: no legacy note may bypass reevaluation.

Use the guarded disposable runner. Lifecycle flags affect eligibility, not the
scientific truth of every result or an immutable historical release.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from models.db import AuditReport, Material, Paper, get_session_factory
from services import audit_runner
from services.audit_rules import AuditRule, rule_by_name
from services.audit_runner import _run_rule


@pytest_asyncio.fixture(loop_scope="function")
async def db_session():
    async with get_session_factory()() as session:
        yield session


def scoped_rule(name, material_id):
    # Isolate current-match/sample assertions from other tests' retained audit
    # history. IDs below are generated locally, never request input.
    rule = rule_by_name(name)
    return replace(rule, predicate=f"({rule.predicate}) AND id = '{material_id}'")


async def seeded(session, *, status="published", records=None, **overrides):
    suffix = uuid4().hex
    paper = Paper(id=f"paper:sc08-audit-{suffix}", source="arxiv", title="Synthetic source",
                  abstract="Synthetic fixture", authors=[], status=status)
    raw = records if records is not None else [{"paper_id": paper.id, "tc_kelvin": 10}]
    material = Material(**{
        "id": f"mat:sc08-audit-{suffix}", "formula": "Nb", "formula_normalized": f"sc08-{suffix}",
        "family": "conventional", "records": raw, "tc_max": 10, "total_papers": 1,
        "needs_review": False, "admin_decision": {"action": "override", "note": "Prior synthetic review"},
        **overrides,
    })
    session.add_all([paper, material])
    await session.flush()
    return paper, material


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["retracted", "withdrawn", "corrected", "disputed", " RETRACTED "])
async def test_lifecycle_change_cannot_reuse_legacy_approval_and_replay_is_idempotent(db_session, status):
    paper, material = await seeded(db_session)
    before_records, before_note = deepcopy(material.records), deepcopy(material.admin_decision)
    rule = scoped_rule("source_eligibility_review_required", material.id)
    first = await _run_rule(db_session, rule)
    assert material.id not in first["sample_ids"]
    paper.status = status
    await db_session.flush()
    first = await _run_rule(db_session, rule)
    second = await _run_rule(db_session, rule)
    assert first == second
    assert material.id in first["sample_ids"]
    await db_session.refresh(material)
    assert material.needs_review and material.review_reason == rule.name
    assert material.records == before_records and material.admin_decision == before_note
    assert material.tc_max == 10 and material.retracted is False and material.disputed is False
    # A later source status alone is not a revision-aware approval. Retain the
    # hold for reviewed resolution rather than silently resurrect old claims.
    paper.status = "published"
    await db_session.flush()
    cleared = await _run_rule(db_session, rule)
    assert material.id not in cleared["sample_ids"]
    await db_session.refresh(material)
    assert material.needs_review and material.admin_decision == before_note
    await db_session.rollback()


@pytest.mark.asyncio
async def test_mixed_sources_and_existing_holds_are_not_relabelled_as_refuted_material(db_session):
    held_paper, material = await seeded(db_session, status="retracted", needs_review=True,
                                      review_reason="provenance_quarantine_existing")
    active_paper, _ = await seeded(db_session)
    material.records = [{"paper_id": held_paper.id, "tc_kelvin": 10},
                        {"paper_id": active_paper.id, "tc_kelvin": 9}]
    await db_session.flush()
    assert material.id not in (await _run_rule(db_session, scoped_rule("sole_source_retracted", material.id)))["sample_ids"]
    source_rule = await _run_rule(db_session, scoped_rule("source_eligibility_review_required", material.id))
    assert material.id in source_rule["sample_ids"]
    await db_session.refresh(material)
    assert material.review_reason == "provenance_quarantine_existing" and material.needs_review
    assert len(material.records) == 2 and not material.disputed and not material.retracted
    await db_session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [{}, {"paper_id": "paper:missing"}, {"paper_id": 123}, None])
async def test_missing_or_malformed_record_does_not_mean_every_source_is_retracted(db_session, extra):
    paper, material = await seeded(db_session, status="retracted")
    material.records = [{"paper_id": paper.id}, extra]
    await db_session.flush()
    result = await _run_rule(db_session, scoped_rule("sole_source_retracted", material.id))
    assert material.id not in result["sample_ids"]
    # Known held support still adds a conservative review hold.
    assert material.id in (await _run_rule(db_session, scoped_rule("source_eligibility_review_required", material.id)))["sample_ids"]
    await db_session.rollback()


@pytest.mark.asyncio
async def test_governance_rules_no_longer_skip_an_old_manual_decision(db_session):
    _, material = await seeded(db_session, is_unconventional=True)
    rule = scoped_rule("family_unconv_contradiction", material.id)
    assert await _run_rule(db_session, rule) == await _run_rule(db_session, rule)
    await db_session.refresh(material)
    assert material.needs_review and material.review_reason == rule.name
    assert material.admin_decision["action"] == "override"
    await db_session.rollback()


def test_retraction_rule_never_suggests_fabricating_scientific_dispute_flags():
    rule = rule_by_name("sole_source_retracted")
    assert not rule.fix_query
    assert "do not set" in rule.suggested_fix


@pytest.mark.asyncio
async def test_report_delta_uses_only_successful_comparable_metric_versions(db_session, monkeypatch):
    name = "synthetic-sc08-metric-" + uuid4().hex
    instant = datetime.now(UTC)
    db_session.add(AuditReport(rule_name=name, severity="critical", started_at=instant,
                               completed_at=instant, rows_flagged=1, sample_ids=[], suggested_fixes=[]))
    await db_session.commit()
    rule = AuditRule(name=name, severity="critical", description="Synthetic metric only", predicate="FALSE")
    monkeypatch.setattr(audit_runner, "RULES", [rule])
    count = 7

    async def outcome(*_args):
        return {"flagged": count, "sample_ids": []}

    monkeypatch.setattr(audit_runner, "_run_rule", outcome)
    for current, expected_delta in [(7, None), (8, 1), (-1, None), (8, 0)]:
        count = current
        await audit_runner.run_audit(db_session)
        latest = (await db_session.execute(select(AuditReport).where(AuditReport.rule_name == name)
                                          .order_by(AuditReport.started_at.desc()).limit(1))).scalar_one()
        assert latest.rows_flagged == current and latest.delta_vs_previous == expected_delta
        assert latest.suggested_fixes[0] == {
            "kind": "audit_count_basis", "version": audit_runner.AUDIT_METRIC_VERSION, "basis": "current_materials",
        }
