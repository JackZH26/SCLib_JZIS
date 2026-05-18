"""R2.2 — near-duplicate consolidation (companion to R2.1).

Reconciles the materials table to the R2.1 normalize_formula id
scheme: re-keys rows, merges fragmented rows (pool+dedup records,
recompute summary via the real _derive_summary, preserve
admin_decision), and folds R2.4 stale orphans.

DEFAULT = offline DRY-RUN on a JSONL snapshot (zero DB, zero prod):
  SCLIB_EVAL_DATA=/tmp/sclib_r2 python3 scripts/r22_consolidate.py

The real-DB --apply path (staging then prod, transactional) is a
SEPARATELY-AUTHORISED step — not enabled here.
"""
from __future__ import annotations

import hashlib
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "scripts")
import aggregator_eval as E  # noqa: E402 (installs sqlalchemy stubs)

A = E.A
normalize_formula = A.normalize_formula
_derive_summary = A._derive_summary
_clean_display = A._clean_display

_KNOWN_EL = __import__("family_audit")._KNOWN_EL


def build_id(prefix: str, norm: str) -> str:
    """Replicates _material_id, preserving the origin prefix."""
    if len(norm) <= 90:
        return f"{prefix}:{norm}"
    h = hashlib.sha1(norm.encode()).hexdigest()[:8]
    return f"{prefix}:{norm[:80]}:{h}"


_ALIASES = getattr(A, "_FORMULA_ALIASES", {})


def elemset(formula: str) -> frozenset | None:
    """Robust true-chemistry element set (defence-in-depth flag).
    Strips the crystallographic polytype prefix (2H-/4H-/1T-/3R-/1T'-)
    so its letter is not misread as H/T, drops x/X/y/z/n doping
    variables and δ. Returns None for alias shorthands (Y123/YBCO/…)
    whose literal token set is meaningless — excluded from the check.
    """
    f = formula.strip().replace("−", "-")                    # U+2212
    f = re.sub(r"^[0-9]+[A-Za-z]+'?-", "", f)                # polytype
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


def main():
    mats = E._load_jsonl(str(E.DATA / "materials.jsonl"))
    omap = E._build_override_map(
        E._load_jsonl(str(E.DATA / "overrides.jsonl")))
    rmap = E._build_refuted_map(
        E._load_jsonl(str(E.DATA / "refuted.jsonl")))
    print(f"prod materials rows: {len(mats)}")

    groups: dict[str, list[dict]] = defaultdict(list)
    for row in mats:
        oid = row["id"]
        prefix = "nims" if str(oid).startswith("nims:") else "mat"
        norm = normalize_formula(row.get("formula") or "")
        if not norm:
            groups[oid].append(row)            # leave unkeyable as-is
            continue
        groups[build_id(prefix, norm)].append(row)

    n_unchanged = n_rekey = 0
    merge_groups = []
    hetero = []                                 # element-heterogeneous
    rows_removed = 0
    stale_only_flagged = 0
    rekey_samples, merge_samples = [], []

    for new_id, rows in groups.items():
        if len(rows) == 1:
            r = rows[0]
            if r["id"] == new_id:
                n_unchanged += 1
            else:
                n_rekey += 1
                if len(rekey_samples) < 8:
                    rekey_samples.append((r["id"], new_id))
            continue

        # MERGE group
        es = {elemset(r.get("formula") or "") for r in rows}
        es = {e for e in es if e}               # ignore empties (alias)
        if len(es) > 1:
            hetero.append((new_id, [r.get("formula") for r in rows[:4]],
                           [sorted(x) for x in es]))

        pooled, seen = [], set()
        for r in rows:
            for rec in (r.get("records") or []):
                k = _rec_key(rec)
                if k not in seen:
                    seen.add(k)
                    pooled.append(rec)
        # display formula: most-common cleaned, shortest tiebreak
        dc = Counter(_clean_display(r.get("formula") or "")
                     or (r.get("formula") or "") for r in rows)
        top = dc.most_common(1)[0][1]
        disp = min([f for f, c in dc.items() if c == top], key=len)
        norm_key = normalize_formula(disp)
        summary = _derive_summary(disp, pooled,
                                  overrides=omap.get(norm_key),
                                  refuted=rmap.get(norm_key))

        # admin_decision preservation
        admin = next((r for r in rows
                      if r.get("admin_decision") is not None), None)
        if admin is not None:
            summary["needs_review"] = admin.get("needs_review")
            summary["review_reason"] = admin.get("review_reason")

        # R2.4: group made ENTIRELY of stale orphans (no fresh member)
        all_stale = all(r.get("best_credibility_tier") is None
                        and not str(r["id"]).startswith("nims:")
                        for r in rows)
        if all_stale and admin is None:
            summary["needs_review"] = True
            summary["review_reason"] = "stale_orphan_no_current_source"
            stale_only_flagged += 1

        rows_removed += len(rows) - 1
        merge_groups.append(new_id)
        if len(merge_samples) < 12:
            merge_samples.append((
                new_id, [r["id"] for r in rows],
                f"{len(pooled)} pooled recs",
                f"fam {summary.get('family')} tc {summary.get('tc_max')}"))

    print("\n===== R2.2 CONSOLIDATION PLAN (offline dry-run) =====")
    print(f"  unchanged rows          : {n_unchanged}")
    print(f"  pure re-key (id rename) : {n_rekey}")
    print(f"  merge groups            : {len(merge_groups)}")
    print(f"  rows removed by merge   : {rows_removed}")
    print(f"  stale-orphan-only flagged (R2.4): {stale_only_flagged}")
    print(f"  final row count         : "
          f"{len(mats) - rows_removed}")
    print(f"\n  GUARDRAIL element-heterogeneous merge groups: "
          f"{len(hetero)} (review — may be alias/x-variable noise)")
    for nid, fs, es in hetero[:8]:
        print(f"    {nid} <= {fs}  elemsets={es}")
    print("\n  re-key sample:")
    for o, n in rekey_samples:
        print(f"    {o}  ->  {n}")
    print("\n  merge sample (old ids -> new id):")
    for nid, oids, npool, fam in merge_samples:
        print(f"    {nid}\n      <= {oids[:6]}  | {npool} | {fam}")
    print("\n  (DRY-RUN — zero DB writes. --apply path is a separately"
          "-authorised staging/prod step.)")


if __name__ == "__main__":
    main()
