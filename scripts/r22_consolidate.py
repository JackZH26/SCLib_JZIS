"""R2.2 — near-duplicate consolidation (companion to R2.1).

Reconciles the materials table to the R2.1 normalize_formula id
scheme: re-key rows, merge fragmented rows (pool+dedup records,
recompute summary via the real _derive_summary, preserve
admin_decision), fold R2.4 stale orphans, then bump
pipeline_state.materials_normalize_version (releases the aggregator
interlock).

Modes (safety-gated):
  (default)            offline DRY-RUN on a JSONL snapshot. Zero DB.
      SCLIB_EVAL_DATA=/tmp/sclib_r2 python3 scripts/r22_consolidate.py
  --db                 STAGING dry-run: real DB, compute plan,
                        READ-ONLY (rolls back). Run in the ingestion
                        container.
  --db --apply --yes   PROD apply: real DB, ONE transaction, writes,
                        bumps the version. SEPARATELY AUTHORISED.
                        --ack-hetero N must equal the reviewed
                        element-heterogeneous group count or it aborts
                        (forces a human to re-confirm that fuzzy
                        safety dimension).
"""
from __future__ import annotations

import hashlib
import re
import sys
from collections import Counter, defaultdict

OFFLINE = not ({"--db"} & set(sys.argv))

if OFFLINE:
    sys.path.insert(0, "scripts")
    import aggregator_eval as E            # installs sqlalchemy stubs
    A = E.A
    _load_jsonl = E._load_jsonl
    _build_override_map = E._build_override_map
    _build_refuted_map = E._build_refuted_map
    DATA = E.DATA
else:
    # real modules — NO stubs (run inside the ingestion container)
    from ingestion.extract import materials_aggregator as A  # noqa

normalize_formula = A.normalize_formula
_derive_summary = A._derive_summary
_clean_display = A._clean_display
NORMALIZE_SCHEMA_VERSION = A.NORMALIZE_SCHEMA_VERSION
_KNOWN_EL = __import__("family_audit")._KNOWN_EL if OFFLINE else None
_ALIASES = getattr(A, "_FORMULA_ALIASES", {})


def build_id(prefix: str, norm: str) -> str:
    if len(norm) <= 90:
        return f"{prefix}:{norm}"
    h = hashlib.sha1(norm.encode()).hexdigest()[:8]
    return f"{prefix}:{norm[:80]}:{h}"


def elemset(formula: str):
    if _KNOWN_EL is None:                  # --db: skip the fuzzy oracle
        return frozenset()
    f = formula.strip().replace("−", "-")
    f = re.sub(r"^[0-9]+[A-Za-z]+'?-", "", f)
    if normalize_formula(f) in _ALIASES or f.lower() in _ALIASES:
        return None
    fe = re.sub(r"[δΔ]|[Dd]elta|[±*·⋅(){}\[\]$_]", "", f)
    return frozenset(t for t in re.findall(r"[A-Z][a-z]?", fe)
                     if t.lower() in _KNOWN_EL)


def _rec_key(r: dict):
    tc = r.get("tc_kelvin")
    try:
        tc = round(float(tc), 2)
    except (TypeError, ValueError):
        tc = None
    return (r.get("paper_id"), tc, (r.get("measurement") or "").lower(),
            r.get("year"), r.get("pressure_gpa"))


def build_plan(rows, omap, rmap):
    """Pure: rows -> consolidation plan. rows = [{id,formula,records,
    needs_review,review_reason,admin_decision,best_credibility_tier}]."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        oid = row["id"]
        prefix = "nims" if str(oid).startswith("nims:") else "mat"
        norm = normalize_formula(row.get("formula") or "")
        groups[build_id(prefix, norm) if norm else oid].append(row)

    plan = {"unchanged": 0, "rekey": [], "merges": [], "hetero": [],
            "stale_flag": 0, "rows_removed": 0}
    for new_id, grp in groups.items():
        if len(grp) == 1:
            r = grp[0]
            if r["id"] == new_id:
                plan["unchanged"] += 1
            else:
                plan["rekey"].append((r["id"], new_id))
            continue
        es = {e for e in {elemset(r.get("formula") or "")
                          for r in grp} if e}
        if len(es) > 1:
            plan["hetero"].append(
                (new_id, [r.get("formula") for r in grp[:4]]))
        pooled, seen = [], set()
        for r in grp:
            for rec in (r.get("records") or []):
                k = _rec_key(rec)
                if k not in seen:
                    seen.add(k)
                    pooled.append(rec)
        dc = Counter(_clean_display(r.get("formula") or "")
                     or (r.get("formula") or "") for r in grp)
        topc = dc.most_common(1)[0][1]
        disp = min([f for f, c in dc.items() if c == topc], key=len)
        nk = normalize_formula(disp)
        summary = _derive_summary(disp, pooled, overrides=omap.get(nk),
                                  refuted=rmap.get(nk))
        admin = next((r for r in grp
                      if r.get("admin_decision") is not None), None)
        if admin is not None:
            summary["needs_review"] = admin.get("needs_review")
            summary["review_reason"] = admin.get("review_reason")
        elif all(r.get("best_credibility_tier") is None
                 and not str(r["id"]).startswith("nims:") for r in grp):
            summary["needs_review"] = True
            summary["review_reason"] = "stale_orphan_no_current_source"
            plan["stale_flag"] += 1
        plan["rows_removed"] += len(grp) - 1
        plan["merges"].append({
            "new_id": new_id, "old_ids": [r["id"] for r in grp],
            "summary": summary, "n_pooled": len(pooled),
            "admin_row": admin})
    return plan


def print_plan(plan, total):
    print("\n===== R2.2 CONSOLIDATION PLAN =====")
    print(f"  unchanged          : {plan['unchanged']}")
    print(f"  pure re-key        : {len(plan['rekey'])}")
    print(f"  merge groups       : {len(plan['merges'])}")
    print(f"  rows removed       : {plan['rows_removed']}")
    print(f"  R2.4 stale flagged : {plan['stale_flag']}")
    print(f"  final row count    : {total - plan['rows_removed']}")
    print(f"  element-heterogeneous groups (review): "
          f"{len(plan['hetero'])}")
    for nid, fs in plan["hetero"][:8]:
        print(f"    {nid} <= {fs}")


# --------------------------------------------------------------------
# OFFLINE (default)
# --------------------------------------------------------------------
def run_offline():
    rows = _load_jsonl(str(DATA / "materials.jsonl"))
    omap = _build_override_map(_load_jsonl(str(DATA / "overrides.jsonl")))
    rmap = _build_refuted_map(_load_jsonl(str(DATA / "refuted.jsonl")))
    print(f"prod materials rows (snapshot): {len(rows)}")
    plan = build_plan(rows, omap, rmap)
    print_plan(plan, len(rows))
    print("\n  (OFFLINE DRY-RUN — zero DB. Use --db for staging.)")


# --------------------------------------------------------------------
# REAL DB  (--db [--apply --yes --ack-hetero N])
# --------------------------------------------------------------------
async def _run_db(apply: bool, ack_hetero):
    import asyncio  # noqa
    from sqlalchemy import select, delete
    from ingestion.index.indexer import (
        _session_factory, materials_table, pipeline_state_table)
    from ingestion.extract.materials_aggregator import (
        _load_all_overrides, _load_all_refuted)

    Session = _session_factory()
    async with Session() as db:
        rows = [dict(r._mapping) for r in (await db.execute(
            select(materials_table))).all()]
        omap = await _load_all_overrides(db)
        rmap = await _load_all_refuted(db)
        print(f"DB materials rows: {len(rows)}")
        plan = build_plan(rows, omap, rmap)
        print_plan(plan, len(rows))

        if not apply:
            print("\n  STAGING DRY-RUN (--db, no --apply): no writes.")
            return
        if ack_hetero != len(plan["hetero"]):
            raise SystemExit(
                f"ABORT: --ack-hetero must equal the "
                f"{len(plan['hetero'])} element-heterogeneous groups "
                f"(human must review them first). Got {ack_hetero}.")

        print("\n  APPLYING (one transaction)…")
        async with db.begin():
            for m in plan["merges"]:
                await db.execute(delete(materials_table).where(
                    materials_table.c.id.in_(m["old_ids"])))
                ins = {"id": m["new_id"], "status": "active_research",
                       **m["summary"]}
                await db.execute(materials_table.insert().values(**ins))
            for old_id, new_id in plan["rekey"]:
                exists = (await db.execute(select(materials_table.c.id)
                          .where(materials_table.c.id == new_id))).first()
                if exists:
                    await db.execute(delete(materials_table).where(
                        materials_table.c.id == old_id))
                else:
                    await db.execute(materials_table.update().where(
                        materials_table.c.id == old_id).values(
                        id=new_id))
            await db.execute(
                pipeline_state_table.update().where(
                    pipeline_state_table.c.key
                    == "materials_normalize_version"
                ).values(value=str(NORMALIZE_SCHEMA_VERSION)))
        print(f"  DONE. materials_normalize_version -> "
              f"{NORMALIZE_SCHEMA_VERSION}. Aggregator interlock "
              f"released; run the aggregator next to refresh summaries.")


def main():
    args = set(sys.argv[1:])
    if OFFLINE:
        run_offline()
        return
    import asyncio
    apply = "--apply" in args
    if apply and "--yes" not in args:
        raise SystemExit("ABORT: --apply requires explicit --yes.")
    ack = None
    for a in sys.argv[1:]:
        if a.startswith("--ack-hetero="):
            ack = int(a.split("=", 1)[1])
    asyncio.run(_run_db(apply, ack))


if __name__ == "__main__":
    main()
