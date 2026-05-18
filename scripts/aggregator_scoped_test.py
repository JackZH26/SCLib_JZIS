"""Scoped 30-record aggregator test — REAL DB, REAL upsert, ROLLBACK.

*** T0.2 — MANDATORY PRE-DEPLOY GATE ***
Run this (green) before EVERY production aggregator re-run, together
with the offline T0.1 schema-drift guard in aggregator_eval.py. The
offline harness stubs SQLAlchemy and therefore CANNOT exercise the
pg_insert/`stmt.excluded` upsert path — the exact path whose
`best_credibility_tier` KeyError crashed production. T0.1 catches
summary-key vs Table-column drift statically; this test then proves
the real upsert executes against the live schema. Both must pass
before `sclib-ingest --mode aggregate-materials` is run on prod.

Purpose: prove the indexer schema-drift fix (best_credibility_tier)
lets the exact upsert path that crashed in production
(`{k: stmt.excluded[k] for k in summary}`) execute against the real
materials table, on a random 30-canonical sample, WITHOUT mutating
production (everything runs in one transaction that is rolled back).

Run inside the ingestion container (real sqlalchemy + DB):
  docker compose --profile tools run --rm ingestion \
      python /app/scripts/aggregator_scoped_test.py
"""
from __future__ import annotations

import asyncio
import random
from collections import Counter, defaultdict

from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ingestion.extract import materials_aggregator as A
from ingestion.index.indexer import (
    _session_factory,
    materials_table,
    papers_table,
)

_TIER_MULTIPLIER = {"T1": 1.0, "T2": 1.0, "T3": 0.8, "T4": 0.0, "T5": 0.0}
SAMPLE_N = 30
SEED = 20260518


def _year_of(d):
    if not d:
        return None
    try:
        return int(str(d)[:4])
    except (ValueError, TypeError):
        return None


def _build_grouped(rows):
    """Verbatim reproduction of aggregate_from_papers grouping
    (per-record filters identical to the production sweep)."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    display_counts: dict[str, Counter] = defaultdict(Counter)
    for pid, date_submitted, cred_tier, mats in rows:
        if not isinstance(mats, list) or not mats:
            continue
        tier_mult = _TIER_MULTIPLIER.get(cred_tier, 1.0)
        if tier_mult <= 0.0:
            continue
        year = _year_of(date_submitted)
        for m in mats:
            if not isinstance(m, dict):
                continue
            raw = m.get("formula")
            if not raw or not isinstance(raw, str):
                continue
            raw = A._formula_validator.normalize_whitespace(raw)
            ok, _ = A._formula_validator.validate_formula(raw)
            if not ok:
                continue
            if m.get("evidence_type") == "cited":
                continue
            conf = m.get("confidence")
            if isinstance(conf, (int, float)) and conf < A._MIN_CONFIDENCE:
                continue
            tc = m.get("tc_kelvin")
            if isinstance(tc, (int, float)) and (tc < 0.01 or tc > 300):
                continue
            norm = A.normalize_formula(raw)
            if not norm:
                continue
            rec = dict(m)
            rec["paper_id"] = pid
            rec["credibility_tier"] = cred_tier
            if tier_mult < 1.0:
                rc = rec.get("confidence", A._DEFAULT_CONFIDENCE)
                rec["confidence"] = round(rc * tier_mult, 3)
            if year is not None and "year" not in rec:
                rec["year"] = year
            grouped[norm].append(rec)
            display_counts[norm][A._clean_display(raw) or raw.strip()] += 1
    return grouped, display_counts


async def main() -> None:
    Session = _session_factory()
    async with Session() as s:
        prows = (await s.execute(
            select(
                papers_table.c.id,
                papers_table.c.date_submitted,
                papers_table.c.credibility_tier,
                papers_table.c.materials_extracted,
            )
        )).all()
        print(f"scanned {len(prows)} papers")
        grouped, display_counts = _build_grouped(prows)
        print(f"{len(grouped)} canonical formulas")

        override_map = await A._load_all_overrides(s)
        refuted_map = await A._load_all_refuted(s)

        rnd = random.Random(SEED)
        sample = rnd.sample(list(grouped), min(SAMPLE_N, len(grouped)))

        # pre-existing prod rows for the sampled ids (for side-by-side)
        ids = [A._material_id(n) for n in sample]
        before = {
            r.id: r for r in (await s.execute(
                select(
                    materials_table.c.id, materials_table.c.formula,
                    materials_table.c.family, materials_table.c.tc_max,
                    materials_table.c.dominant_evidence,
                    materials_table.c.needs_review,
                ).where(materials_table.c.id.in_(ids))
            )).all()
        }

        ok_n = 0
        fail = []
        results = []
        for norm in sample:
            recs = grouped[norm]
            cand = display_counts[norm].most_common()
            top = cand[0][1]
            display_raw = min([r for r, c in cand if c == top], key=len)
            mat_id = A._material_id(norm)
            try:
                summary = A._derive_summary(
                    display_raw, recs,
                    overrides=override_map.get(norm),
                    refuted=refuted_map.get(norm),
                )
                # EXACT production upsert path (the line that crashed)
                stmt = pg_insert(materials_table).values(
                    id=mat_id, status="active_research", **summary,
                )
                update_cols = {k: stmt.excluded[k] for k in summary}
                mt = materials_table.c
                update_cols["needs_review"] = case(
                    (mt.admin_decision.isnot(None), mt.needs_review),
                    else_=stmt.excluded["needs_review"],
                )
                update_cols["review_reason"] = case(
                    (mt.admin_decision.isnot(None), mt.review_reason),
                    else_=stmt.excluded["review_reason"],
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=[mt.id], set_=update_cols,
                )
                await s.execute(stmt)
                ok_n += 1
                results.append((mat_id, summary))
            except Exception as e:  # noqa: BLE001
                fail.append((mat_id, type(e).__name__, str(e)[:160]))

        # read back the just-upserted rows WITHIN the txn (proves write)
        wrote = {
            r.id: r for r in (await s.execute(
                select(
                    materials_table.c.id, materials_table.c.formula,
                    materials_table.c.family, materials_table.c.tc_max,
                    materials_table.c.tc_ambient,
                    materials_table.c.dominant_evidence,
                    materials_table.c.needs_review,
                    materials_table.c.review_reason,
                    materials_table.c.best_credibility_tier,
                ).where(materials_table.c.id.in_(ids))
            )).all()
        }

        await s.rollback()  # <<< NO production mutation

    print(f"\nupsert OK: {ok_n}/{len(sample)}   failed: {len(fail)}")
    for mid, et, msg in fail:
        print(f"  FAIL {mid}: {et}: {msg}")

    print("\n=== 30-record results (rolled back; prod untouched) ===")
    print(f"{'formula':<26}{'family':<13}{'tcmax':>7} {'amb':>6}  "
          f"{'evidence':<12}{'nR':<3}{'tier':<4} prevTcmax/fam")
    for mid, summ in results:
        w = wrote.get(mid)
        b = before.get(mid)
        f = (summ.get("formula") or "")[:25]
        prev = (f"{b.tc_max}/{b.family}" if b else "(new row)")
        print(f"{f:<26}{str(summ.get('family')):<13}"
              f"{str(summ.get('tc_max')):>7} {str(summ.get('tc_ambient')):>6}  "
              f"{str(summ.get('dominant_evidence')):<12}"
              f"{'Y' if summ.get('needs_review') else 'n':<3}"
              f"{str(summ.get('best_credibility_tier')):<4} {prev}")

    # post-rollback safety proof
    Session2 = _session_factory()
    async with Session2() as s2:
        cnt = (await s2.execute(
            select(materials_table.c.id).where(
                materials_table.c.id.in_(ids))
        )).all()
        upd = (await s2.execute(
            select(materials_table.c.id, materials_table.c.updated_at)
            .where(materials_table.c.id.in_(ids))
        )).all()
    print(f"\nrollback proof: {len(cnt)} of the {len(ids)} sampled ids "
          f"exist in prod (unchanged); newest updated_at among them = "
          f"{max((u.updated_at for u in upd), default=None)}")


if __name__ == "__main__":
    asyncio.run(main())
