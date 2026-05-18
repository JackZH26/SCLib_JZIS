"""Offline aggregator evaluation harness (Phase 0 baseline + regression gate).

Runs the REAL `materials_aggregator._derive_summary` (and the verbatim
per-record skip + grouping loop from `aggregate_from_papers`) over an
offline dump of `papers.materials_extracted`, with NO database. The
DB-only imports (`sqlalchemy`, `ingestion.index.indexer`) are stubbed
in `sys.modules`; every accuracy-relevant function is the genuine
implementation, so results are faithful to a production re-run
(minus P2 parent-variant linking, which only sets parent_material_id
/variant_count and never touches tc/family/phase).

Inputs (read-only prod dumps, JSONL, one row per line):
  /tmp/sclib_phase0/papers.jsonl     id,date_submitted,credibility_tier,paper_type,materials_extracted
  /tmp/sclib_phase0/materials.jsonl  current prod materials rows (the baseline output)
  /tmp/sclib_phase0/overrides.jsonl  manual_overrides
  /tmp/sclib_phase0/refuted.jsonl    refuted_claims

Usage:
  python3 scripts/aggregator_eval.py            # scorecard + fidelity + orphans
  python3 scripts/aggregator_eval.py --corpus   # also write the fixed eval corpus
"""
from __future__ import annotations

import json
import os
import sys
import types
from collections import Counter, defaultdict
from pathlib import Path

# Override with SCLIB_EVAL_DATA to point at a different snapshot
# (e.g. the Phase 4 post-NER dump) while keeping the Phase 0 baseline
# dir untouched for comparison.
DATA = Path(os.environ.get("SCLIB_EVAL_DATA", "/tmp/sclib_phase0"))


# --------------------------------------------------------------------------
# Stub the DB-only imports so the pure accuracy code imports cleanly.
# These objects are NEVER called by _derive_summary / the grouping loop.
# --------------------------------------------------------------------------
def _install_stubs() -> None:
    sa = types.ModuleType("sqlalchemy")
    sa.case = lambda *a, **k: None
    sa.select = lambda *a, **k: None
    sys.modules["sqlalchemy"] = sa
    dialects = types.ModuleType("sqlalchemy.dialects")
    pg = types.ModuleType("sqlalchemy.dialects.postgresql")
    pg.insert = lambda *a, **k: None
    dialects.postgresql = pg
    sys.modules["sqlalchemy.dialects"] = dialects
    sys.modules["sqlalchemy.dialects.postgresql"] = pg
    idx = types.ModuleType("ingestion.index.indexer")
    for name in ("_session_factory", "manual_overrides_table",
                 "materials_table", "papers_table", "refuted_claims_table"):
        setattr(idx, name, object())
    sys.modules["ingestion.index.indexer"] = idx


_install_stubs()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))

from ingestion.extract import materials_aggregator as A  # noqa: E402

_validate = A._formula_validator.validate_formula
_norm_ws = A._formula_validator.normalize_whitespace
_normalize_formula = A.normalize_formula
_clean_display = A._clean_display
_derive_summary = A._derive_summary
_material_id = A._material_id
_OverrideEntry = A._OverrideEntry
_RefutedEntry = A._RefutedEntry
_MIN_CONFIDENCE = A._MIN_CONFIDENCE          # 0.3
_DEFAULT_CONFIDENCE = A._DEFAULT_CONFIDENCE  # 0.5
# _TIER_MULTIPLIER is local to aggregate_from_papers(); copied verbatim.
_TIER_MULTIPLIER = {"T1": 1.0, "T2": 1.0, "T3": 0.8, "T4": 0.0, "T5": 0.0}


def _load_jsonl(name: str) -> list[dict]:
    p = DATA / name
    out = []
    with p.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _build_override_map(rows: list[dict]) -> dict[str, list]:
    m: dict[str, list] = defaultdict(list)
    for r in rows:
        m[r["canonical"]].append(
            _OverrideEntry(r["field"], r["override_value"], r["is_cap"],
                           r["source"], r.get("reason"))
        )
    return dict(m)


def _build_refuted_map(rows: list[dict]) -> dict[str, object]:
    m: dict[str, object] = {}
    for r in rows:
        c = r["canonical"]
        if c not in m:
            m[c] = _RefutedEntry(c, r["claim_type"], r.get("claimed_tc"),
                                 r.get("notes"))
    return m


def _year_of(date_submitted) -> int | None:
    if not date_submitted:
        return None
    try:
        return int(str(date_submitted)[:4])
    except (ValueError, TypeError):
        return None


def run_aggregator(papers, override_map, refuted_map):
    """Verbatim reproduction of aggregate_from_papers() lines 1108-1205,
    minus the DB upsert and P2 parent-variant linking."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    display_counts: dict[str, Counter] = defaultdict(Counter)
    n_skipped_t4t5 = 0
    skip_reasons: Counter = Counter()

    for row in papers:
        mats = row.get("materials_extracted")
        if not isinstance(mats, list) or not mats:
            continue
        cred_tier = row.get("credibility_tier")
        tier_mult = _TIER_MULTIPLIER.get(cred_tier, 1.0)
        if tier_mult <= 0.0:
            n_skipped_t4t5 += 1
            continue
        year = _year_of(row.get("date_submitted"))
        paper_id = row["id"]
        for m in mats:
            if not isinstance(m, dict):
                continue
            raw = m.get("formula")
            if not raw or not isinstance(raw, str):
                continue
            raw = _norm_ws(raw)
            ok, reject_reason = _validate(raw)
            if not ok:
                skip_reasons[f"validator:{reject_reason}"] += 1
                continue
            if m.get("evidence_type") == "cited":
                skip_reasons["cited"] += 1
                continue
            conf = m.get("confidence")
            if isinstance(conf, (int, float)) and conf < _MIN_CONFIDENCE:
                skip_reasons["low_confidence"] += 1
                continue
            tc = m.get("tc_kelvin")
            if isinstance(tc, (int, float)) and (tc < 0.01 or tc > 300):
                skip_reasons["tc_out_of_range"] += 1
                continue
            norm = _normalize_formula(raw)
            if not norm:
                skip_reasons["empty_norm"] += 1
                continue
            record = dict(m)
            record["paper_id"] = paper_id
            record["credibility_tier"] = cred_tier
            if tier_mult < 1.0:
                raw_conf = record.get("confidence", _DEFAULT_CONFIDENCE)
                record["confidence"] = round(raw_conf * tier_mult, 3)
            if year is not None and "year" not in record:
                record["year"] = year
            grouped[norm].append(record)
            display_counts[norm][_clean_display(raw) or raw.strip()] += 1

    fresh: dict[str, dict] = {}
    for norm, records in grouped.items():
        candidates = display_counts[norm].most_common()
        top_count = candidates[0][1]
        top_raws = [r for r, c in candidates if c == top_count]
        display_raw = min(top_raws, key=len)
        summary = _derive_summary(
            display_raw, records,
            overrides=override_map.get(norm),
            refuted=refuted_map.get(norm),
        )
        fresh[_material_id(norm)] = {"summary": summary, "norm": norm,
                                     "display_raw": display_raw,
                                     "n_records": len(records),
                                     "records": records}
    return fresh, n_skipped_t4t5, skip_reasons


# --------------------------------------------------------------------------
# Scorecard metrics
# --------------------------------------------------------------------------
def _tc_max_is_theory_only(summary, records_unused=None) -> bool:
    """Heuristic for audit category E: headline tc_max tied only by
    theoretical records while dominant_evidence reads experimental."""
    ev = summary.get("dominant_evidence")
    tcm = summary.get("tc_max")
    if tcm is None or ev not in ("experimental", "mixed"):
        return False
    recs = summary.get("records") or []
    tying = [r for r in recs
             if isinstance(r.get("tc_kelvin"), (int, float))
             and abs(float(r["tc_kelvin"]) - float(tcm)) <= 0.15]
    if not tying:
        return False
    # Tightened detector: use the production single-source-of-truth
    # classifier so this metric measures exactly what the fix targets.
    return all(A._record_is_theoretical(r) for r in tying)


def _phase_inconsistent(summary) -> bool:
    """Audit category D — mirrors the production
    _sanity_check_structure_phase EXACTLY (normalized, exact token
    match; "1232" is a valid phase, not "123")."""
    ph = summary.get("structure_phase") or ""
    if not ph:
        return False
    import re
    f = summary.get("formula") or ""
    toks = re.findall(r"[A-Z][a-z]?", f)
    has_cu = "Cu" in toks
    p = ph.lower().removeprefix("cuprate_").strip()
    if ph.lower().startswith("cuprate") and not has_cu:
        return True
    if p == "123" and has_cu and "Ce" in toks and "Ba" not in toks:
        return True
    if p == "214" and has_cu and ("Hg" in toks or "Tl" in toks):
        return True
    return False


def scorecard(fresh: dict) -> dict:
    sums = [v["summary"] for v in fresh.values()]
    rejectable = 0
    for s in sums:
        ok, _ = _validate(_norm_ws(s.get("formula") or ""))
        if not ok:
            rejectable += 1
    theory_headline = sum(1 for s in sums if _tc_max_is_theory_only(s))
    phase_bad = sum(1 for s in sums if _phase_inconsistent(s))
    fam_null_with_papers = sum(
        1 for s in sums
        if not s.get("family") and (s.get("total_papers") or 0) > 0)
    # near-duplicate clusters: collapse to alnum-lowercase signature
    import re
    sig = defaultdict(set)
    for v in fresh.values():
        s = v["summary"]
        key = re.sub(r"[^a-z0-9]", "", (s.get("formula") or "").lower())
        if key:
            sig[key].add(v["norm"])
    dup_clusters = sum(1 for k, st in sig.items() if len(st) > 1)
    needs_review = sum(1 for s in sums if s.get("needs_review"))
    return {
        "fresh_materials": len(fresh),
        "fresh_needs_review_true": needs_review,
        "fresh_visible(needs_review=false)": len(fresh) - needs_review,
        "validator_rejectable_in_output": rejectable,
        "tc_max_theory_but_evidence_experimental": theory_headline,
        "structure_phase_inconsistent_with_formula": phase_bad,
        "family_null_with_papers": fam_null_with_papers,
        "near_duplicate_clusters": dup_clusters,
    }


def fidelity_and_orphans(fresh: dict, prod_rows: list[dict]) -> dict:
    prod = {r["id"]: r for r in prod_rows}
    fresh_ids = set(fresh)
    prod_ids = set(prod)
    both = fresh_ids & prod_ids
    fields = ["tc_max", "family", "structure_phase", "dominant_evidence"]
    match = {f: 0 for f in fields}
    mismatch = {f: 0 for f in fields}
    nr_match = nr_mismatch = nr_skipped_admin = 0
    for mid in both:
        fs = fresh[mid]["summary"]
        pr = prod[mid]
        for f in fields:
            a, b = fs.get(f), pr.get(f)
            if isinstance(a, float) and isinstance(b, float):
                same = abs(a - b) <= 0.05
            else:
                same = a == b
            (match if same else mismatch)[f] += 1
        if pr.get("admin_decision") is not None:
            nr_skipped_admin += 1
        elif bool(fs.get("needs_review")) == bool(pr.get("needs_review")):
            nr_match += 1
        else:
            nr_mismatch += 1

    orphans = prod_ids - fresh_ids
    orphan_visible = 0
    orphan_rejectable = 0
    orphan_reasons: Counter = Counter()
    orphan_family: Counter = Counter()
    for mid in orphans:
        pr = prod[mid]
        if not pr.get("needs_review"):
            orphan_visible += 1
        ok, _ = _validate(_norm_ws(pr.get("formula") or ""))
        if not ok:
            orphan_rejectable += 1
        orphan_reasons[pr.get("review_reason") or "(none)"] += 1
        orphan_family[pr.get("family") or "(null)"] += 1
    return {
        "prod_rows": len(prod),
        "fresh_rows": len(fresh),
        "in_both": len(both),
        "field_match": match,
        "field_mismatch": mismatch,
        "needs_review_match": nr_match,
        "needs_review_mismatch": nr_mismatch,
        "needs_review_skipped(admin_decision)": nr_skipped_admin,
        "ORPHANS_prod_not_reproduced": len(orphans),
        "orphans_visible(needs_review=false)": orphan_visible,
        "orphans_validator_rejectable": orphan_rejectable,
        "orphans_top_review_reason": orphan_reasons.most_common(8),
        "orphans_top_family": orphan_family.most_common(8),
        "fresh_only(not_in_prod)": len(fresh_ids - prod_ids),
    }


def tc_change_analysis(fresh: dict) -> None:
    """A/B the NEW experimental-first headline vs the OLD all-records
    _corroborated_max, classifying every change as intended or
    regression. Self-contained: 'old' is recomputed from the same
    records, so this isolates the Round-2 change from prod staleness."""
    cmax = A._corroborated_max
    is_theo = A._record_is_theoretical
    TCS = getattr(A, "_TC_SANITY_MAX_K", 250.0)
    cats = Counter()
    samples = defaultdict(list)
    for mid, v in fresh.items():
        # Mirror _derive_summary's Step-0.5 clean filter so "old" is the
        # value the OLD code actually produced (cmax over post-sanity
        # records), not a pre-sanity proxy. (Per-compound override caps
        # omitted — rare; prod-fidelity is the authoritative gate.)
        recs = [r for r in v["records"]
                if not (isinstance(r.get("tc_kelvin"), (int, float))
                        and r["tc_kelvin"] > TCS)]
        if not recs:
            recs = v["records"]   # all-bad fallback (matches code)
        s = v["summary"]
        new = s.get("tc_max")
        old, _ = cmax(recs, "tc_kelvin")          # OLD headline = all-records
        exp = [r for r in recs if not is_theo(r)
               and r.get("evidence_type") != "cited"]
        theo = [r for r in recs if is_theo(r)]
        exp_max, _ = cmax(exp, "tc_kelvin")
        if (new is None and old is None) or (
                new is not None and old is not None
                and abs(new - old) <= 0.05):
            cats["unchanged"] += 1
            continue
        # changed
        if new is None and old is not None:
            if exp_max is None and theo:
                cats["intended: theory_only->headline_kept_theo?"] += 1
            else:
                cats["REGRESSION: dropped_to_None"] += 1
                samples["REGRESSION: dropped_to_None"].append(
                    (s.get("formula"), old))
        elif exp_max is not None and abs((new or -1) - exp_max) <= 0.05:
            # new headline == experimental corroborated max
            if old is not None and old > exp_max + 0.05:
                cats["intended: theory_inflated_headline_removed"] += 1
                samples["intended: theory_inflated_headline_removed"].append(
                    (s.get("formula"), f"{old}->{new}"))
            else:
                cats["benign: headline==exp (==old)"] += 1
        elif theo and not exp:
            cats["theory_only_material (headline=theo, ok)"] += 1
        else:
            cats["other_change (inspect)"] += 1
            samples["other_change (inspect)"].append(
                (s.get("formula"), f"{old}->{new}"))

    print("\n===== TC_MAX CHANGE A/B (new exp-first vs old all-records) =====")
    for k, n in cats.most_common():
        print(f"  {k:46} {n}")
    for k in ("REGRESSION: dropped_to_None", "other_change (inspect)"):
        if samples[k]:
            print(f"  e.g. {k}: {samples[k][:6]}")
    for k in ("intended: theory_inflated_headline_removed",):
        if samples[k]:
            print(f"  e.g. {k}: {samples[k][:6]}")


def reconcile_preview(fresh: dict, prod_rows: list[dict]) -> None:
    """Simulate P3 discriminating reconcile over the prod dump using the
    REAL _is_purgeable_orphan, with guardrails."""
    live_ids = set(fresh)  # == {_material_id(n) for n in grouped} in prod
    pred = A._is_purgeable_orphan
    flagged, preserved_nims, preserved_valid = [], [], []
    for r in prod_rows:
        if r.get("needs_review"):
            continue
        if r.get("admin_decision") is not None:
            continue
        if r["id"] in live_ids:
            continue
        if pred(r.get("formula"), r.get("review_reason"), r["id"]):
            flagged.append(r)
        elif str(r["id"]).startswith("nims:"):
            preserved_nims.append(r)
        else:
            preserved_valid.append(r)

    by_fam = Counter((r.get("family") or "(null)") for r in flagged)
    by_rsn = Counter((r.get("review_reason") or "(none)") for r in flagged)
    # GUARDRAILS
    g_nims = sum(1 for r in flagged if str(r["id"]).startswith("nims:"))
    g_live = sum(1 for r in flagged if r["id"] in live_ids)
    g_validpass = 0
    for r in flagged:
        ok, _ = _validate(_norm_ws(r.get("formula") or ""))
        rr = r.get("review_reason") or ""
        if ok and not any(g and g in rr for g in A._GARBAGE_REVIEW_REASONS):
            g_validpass += 1

    print("\n===== P3 RECONCILE PREVIEW (real _is_purgeable_orphan) =====")
    print(f"  orphans soft-retired (needs_review->True) : {len(flagged)}")
    print(f"  preserved: NIMS-only                       : {len(preserved_nims)}")
    print(f"  preserved: valid/source-less (non-NIMS)    : {len(preserved_valid)}")
    print(f"  flagged by family : {by_fam.most_common(8)}")
    print(f"  flagged by reason : {by_rsn.most_common(8)}")
    print("  -- GUARDRAILS (all must be 0) --")
    print(f"  flagged that are NIMS                : {g_nims}")
    print(f"  flagged that were live this sweep    : {g_live}")
    print(f"  flagged w/ valid formula & no gbg rsn: {g_validpass}")
    print("  sample flagged   :",
          [r["formula"] for r in flagged[:8]])
    print("  sample presv NIMS:",
          [r["formula"] for r in preserved_nims[:6]])
    print("  sample presv valid:",
          [r["formula"] for r in preserved_valid[:6]])


def schema_drift_check(fresh: dict) -> set[str]:
    """T0.1 — offline guard for the bug class that crashed prod.

    Every key _derive_summary emits MUST be a real column in the
    hand-maintained indexer.materials_table Table object, or the
    production upsert `{k: stmt.excluded[k] for k in summary}` raises
    KeyError and aggregate_from_papers dies on the first material.
    This parses the Table column names statically (no sqlalchemy /
    DB) and asserts summary_keys ⊆ columns. Would have caught
    `best_credibility_tier` instantly, offline.
    """
    import re as _re
    idx = (Path(__file__).resolve().parents[1]
           / "ingestion/ingestion/index/indexer.py")
    src = idx.read_text().splitlines()
    i = next(n for n, l in enumerate(src)
             if l.strip().startswith("materials_table = Table("))
    depth = 0
    cols: set[str] = set()
    for n in range(i, len(src)):
        depth += src[n].count("(") - src[n].count(")")
        m = _re.search(r'Column\("([a-z0-9_]+)"', src[n])
        if m:
            cols.add(m.group(1))
        if depth <= 0 and n > i:
            break
    keys: set[str] = set()
    for v in fresh.values():
        keys |= set(v["summary"].keys())
    drift = keys - cols
    print("\n===== SCHEMA-DRIFT GUARD (summary keys vs "
          "indexer.materials_table) =====")
    print(f"  indexer columns: {len(cols)}  summary keys: {len(keys)}")
    if drift:
        print(f"  ❌ FAIL — {len(drift)} key(s) not declared as columns: "
              f"{sorted(drift)}")
        print("  → production upsert WILL KeyError on these. Add the "
              "column(s) to indexer.materials_table before any re-run.")
    else:
        print("  ✅ PASS — every summary key has a materials_table column")
    return drift


def main():
    papers = _load_jsonl("papers.jsonl")
    prod_rows = _load_jsonl("materials.jsonl")
    override_map = _build_override_map(_load_jsonl("overrides.jsonl"))
    refuted_map = _build_refuted_map(_load_jsonl("refuted.jsonl"))
    print(f"loaded: papers={len(papers)} prod_materials={len(prod_rows)} "
          f"overrides={sum(len(v) for v in override_map.values())} "
          f"refuted={len(refuted_map)}")

    fresh, n_t4t5, skips = run_aggregator(papers, override_map, refuted_map)
    print(f"\nrun: papers_skipped_T4T5={n_t4t5}  "
          f"records_skipped={sum(skips.values())}")
    for k, v in skips.most_common():
        print(f"  skip {k:32} {v}")

    schema_drift_check(fresh)

    print("\n===== SCORECARD (fresh recompute) =====")
    for k, v in scorecard(fresh).items():
        print(f"  {k:48} {v}")

    print("\n===== FIDELITY vs PROD + ORPHANS =====")
    fo = fidelity_and_orphans(fresh, prod_rows)
    for k, v in fo.items():
        print(f"  {k:42} {v}")

    tc_change_analysis(fresh)
    reconcile_preview(fresh, prod_rows)

    if "--corpus" in sys.argv:
        # Fixed stratified eval corpus: all papers whose surviving
        # records land in a sampled set of canonicals, stratified by
        # family + new/old NER schema, seed=42. Saves paper subset so
        # later rounds re-run _derive_summary on an identical input.
        import random
        random.seed(42)
        by_fam = defaultdict(list)
        for mid, v in fresh.items():
            by_fam[v["summary"].get("family") or "(null)"].append(v["norm"])
        picked = set()
        for fam, norms in by_fam.items():
            random.shuffle(norms)
            picked.update(norms[:max(15, len(norms) // 10)])
        keep_papers = []
        for row in papers:
            mats = row.get("materials_extracted") or []
            for m in mats:
                if not isinstance(m, dict):
                    continue
                rw = m.get("formula")
                if isinstance(rw, str) and _normalize_formula(_norm_ws(rw)) in picked:
                    keep_papers.append(row)
                    break
        outp = DATA / "corpus_v1.jsonl"
        with outp.open("w") as fh:
            for row in keep_papers:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"\ncorpus_v1: {len(keep_papers)} papers covering "
              f"{len(picked)} canonicals -> {outp}")


if __name__ == "__main__":
    main()
