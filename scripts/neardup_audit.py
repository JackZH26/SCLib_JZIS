"""R2.0 — near-duplicate + stale-orphan audit on settled (post-re-run)
data. Read-only. Design input for Round 2 (R2.1+).

  python3 scripts/neardup_audit.py            (uses SCLIB_EVAL_DATA)
  SCLIB_EVAL_DATA=/tmp/sclib_r2 python3 scripts/neardup_audit.py

Two reports:
  1. near-duplicate clusters (alnum-signature collapses to >1 distinct
     canonical) bucketed by root cause + the cross-element guard.
  2. stale-orphan subset: prod rows NOT regenerated this sweep
     (best_credibility_tier IS NULL), non-NIMS, valid formula,
     needs_review=False — the HMgB2-class that Round 2 / R2.4 targets.
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "scripts")
import aggregator_eval as E  # noqa: E402

A = E.A


def _eset(f: str) -> frozenset:
    fe = re.sub(r"(?<=[A-Z0-9])[xyzδ](?=[A-Z0-9()\[\]+\-·.,/]|$)", "", f)
    return frozenset(re.findall(r"[A-Z][a-z]?", fe))


def near_dup_report(fresh: dict) -> None:
    sig = defaultdict(list)
    for v in fresh.values():
        f = v["summary"].get("formula") or ""
        k = re.sub(r"[^a-z0-9]", "", f.lower())
        if k:
            sig[k].append((f, v["norm"]))
    clusters = [(k, vv) for k, vv in sig.items()
                if len({n for _, n in vv}) > 1]
    mats = sum(len(vv) for _, vv in clusters)
    B = Counter()
    cross = []
    for k, vv in clusters:
        forms = [f for f, _ in vv]
        esets = {_eset(f) for f in forms}
        if len(esets) > 1:
            B["CROSS-ELEMENT (must NOT merge)"] += 1
            cross.append((forms[:3], [sorted(x) for x in esets]))
            continue
        fl = " ".join(forms).lower()
        if any(re.search(r"[·*]|[.\-]?y?h2o", x.lower()) for x in forms) \
                and any("h2o" in x.lower() or "coo2" in x.lower()
                        for x in forms):
            B["hydrate-separator"] += 1
        elif any(any(g in x for g in ("α-", "β-", "γ-", "κ-", "κ(",
                                      "λ-")) for x in forms):
            B["greek polymorph (EXCLUDE)"] += 1
        elif any(("(" in x or "[" in x) for x in forms):
            B["cosmetic paren/bracket"] += 1
        elif "±" in fl or "δ" in fl:
            B["delta/pm-delta residue"] += 1
        else:
            B["other"] += 1
    print("===== NEAR-DUPLICATE CLUSTERS (settled data) =====")
    print(f"  clusters={len(clusters)}  materials_in_clusters={mats}"
          f"  (~{100*mats/max(len(fresh),1):.1f}% of {len(fresh)})")
    for kk, c in B.most_common():
        print(f"  {kk:34} {c}")
    if cross:
        print("  CROSS-ELEMENT samples (detector false-merge risk):")
        for forms, es in cross[:8]:
            print(f"    {forms}  elements={es}")


def stale_orphan_report() -> None:
    rows = E._load_jsonl(str(E.DATA / "materials.jsonl"))
    val = A._formula_validator.validate_formula
    nw = A._formula_validator.normalize_whitespace
    n_total = len(rows)
    stale_valid = []
    for r in rows:
        if r.get("best_credibility_tier") is not None:
            continue                       # regenerated this/recent sweep
        if str(r.get("id", "")).startswith("nims:"):
            continue                       # legit NIMS-only (preserve)
        if r.get("needs_review"):
            continue                       # already hidden
        ok, _ = val(nw(r.get("formula") or ""))
        if not ok:
            continue                       # garbage (reconcile handles)
        stale_valid.append(r)
    print("\n===== STALE-ORPHAN SUBSET (HMgB2-class) =====")
    print(f"  prod rows: {n_total}")
    print(f"  stale valid non-NIMS visible orphans "
          f"(best_credibility_tier NULL): {len(stale_valid)}")
    fam = Counter((r.get("family") or "(null)") for r in stale_valid)
    print(f"  by family: {fam.most_common(10)}")
    has_tc = sum(1 for r in stale_valid if r.get("tc_max") is not None)
    print(f"  with a tc_max value: {has_tc}")
    print("  samples:",
          [r.get("formula") for r in stale_valid[:18]])


def main():
    papers = E._load_jsonl(str(E.DATA / "papers.jsonl"))
    fresh, _, _ = E.run_aggregator(
        papers,
        E._build_override_map(E._load_jsonl(str(E.DATA / "overrides.jsonl"))),
        E._build_refuted_map(E._load_jsonl(str(E.DATA / "refuted.jsonl"))),
    )
    print(f"fresh canonicals this sweep: {len(fresh)}\n")
    near_dup_report(fresh)
    stale_orphan_report()


if __name__ == "__main__":
    main()
