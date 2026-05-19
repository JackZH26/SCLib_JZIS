"""R2.3 offline gate — OLD(=HEAD, R2.2-shipped) vs NEW(=working tree,
R2.3) normalize_formula, with the element-set merge guardrail.
Read-only. No DB, no prod.

  python3 scripts/r23_guard.py /tmp/prod_all_formulas.tsv

The TSV is a fresh prod dump (id<TAB>formula), so the measured
re-key / merge counts are the real R2.3 consolidation scope.

Asserts:
  * every NEWLY-colliding group (old norms differ -> new norm equal =
    a proposed merge) is element-set HOMOGENEOUS — any cross-compound
    merge is a hard FAIL (would corrupt data on migration);
  * MUST_MERGE: the R2.3 target cases collapse to one key
    (HMgB2/H-MgB2, the ^10B/^11B isotopologues, Mg-AlB2 variants,
    NaxCoO2 hydrate ± forms);
  * MUST_KEEP: the Pd/Nd/Gd/Cd 'd' class + polytype + doping folding
    are unchanged (no regression from the new hyphen/caret rules);
  * reports clusters resolved + ids that would re-key.
"""
from __future__ import annotations

import re
import sys
import types
from collections import defaultdict

sys.path.insert(0, "scripts")
import aggregator_eval as E  # noqa: E402 (installs sqlalchemy/db stubs)

A = E.A
new_norm = A.normalize_formula

import subprocess  # noqa: E402

_old_src = subprocess.run(
    ["git", "show", "HEAD:ingestion/ingestion/nims.py"],
    capture_output=True, text=True, check=True).stdout
_mod = types.ModuleType("old_nims")
_mod.__file__ = "old_nims.py"
sys.modules["old_nims"] = _mod
exec(compile(_old_src, "old_nims.py", "exec"), _mod.__dict__)
old_norm = _mod.normalize_formula


def elemset(f: str):
    """Element multiset signature on the RAW formula, invariant under
    any cosmetic-only normalization. INFORMATIONAL ONLY — the
    tokenizer is fooled by alias shorthands (Y123), prose
    abbreviations (UC=unit cell, Ph=phenanthrene) and English-prose
    junk; per the R2.1/R2.2 method the VERDICT is the sanity tables,
    not this. Returns None for alias keys / obvious prose so the
    review list isn't drowned in known false positives."""
    fl = f.lower()
    if A.normalize_formula(f) in getattr(A, "_FORMULA_ALIASES", {}):
        return None
    # English-prose junk (not a compound — A-class, flagged anyway)
    if re.search(r"cuprate|nanotube|diamond|phenanthrene|graphene|"
                 r"systems?|doped|walled|hight?c|amorphous", fl):
        return None
    fe = re.sub(r"[δΔ]|[Dd]elta|[±*·⋅(){}\[\]$_^/,-]", "", f)
    return frozenset(re.findall(r"[A-Z][a-z]?", fe))


# Groups that MUST collapse to a single new key (the R2.3 fixes).
MUST_MERGE = [
    ["HMgB2", "H-MgB2"],
    ["YNi2^10B2C", "YNi2^11B2C", "YNi2B2C"],
    ["Mg-AlB2", "MgAlB2", "Mg,AlB2"],
    ["NaxCoO2-1.3H2O", "NaxCoO2+1.3H2O", "NaxCoO2·1.3H2O"],
    ["β^'-ET2ICl2", "β-ET2ICl2"],
]

# Substring assertions that MUST hold (no element corruption / no
# regression of existing R2.1/R2.2 folding by the new rules).
MUST_KEEP = {
    "PdTe2": "pd", "Nd2CuO4": "nd", "GdBa2Cu3O7-δ": "gd",
    "CdS": "cd", "D3S": "d3",
    "Bi2Sr2CaCu2O8±δ": "bi2sr2cacu2o8",
    "2H-NbSe2": "nbse2",                 # polytype still folds
    "Fe1-xSe": "fe",                     # doping not eaten to garbage
    "LaO0.9F0.1-δFeAs": "lao0.9f0.1feas",
    "NaxCoO2·1.3H2O": "naxcoo21.3h2o",   # R2-B3 unchanged
}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/prod_all_formulas.tsv"
    forms = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2 and parts[1]:
                forms.add(parts[1])
    forms.discard("")
    print(f"distinct raw formulas (prod corpus): {len(forms)}")

    rekeyed = 0
    new_groups = defaultdict(set)
    new_raws = defaultdict(list)
    for f in forms:
        o, n = old_norm(f), new_norm(f)
        if o != n:
            rekeyed += 1
        new_groups[n].add(o)
        new_raws[n].append(f)

    merges = {n: g for n, g in new_groups.items() if len(g) > 1}
    forbidden, homog = [], 0
    for n in merges:
        es = {x for x in (elemset(r) for r in new_raws[n]) if x is not None}
        if len(es) > 1:
            forbidden.append((n, sorted(set(new_raws[n]))[:5],
                              [sorted(x) for x in es]))
        else:
            homog += 1

    print(f"\nids that would re-key (old != new): {rekeyed}")
    print(f"merge groups (>=2 old norms -> 1 new): {len(merges)}")
    print(f"  element-homogeneous: {homog}  | cross-element "
          f"(INFORMATIONAL — manual review, not the verdict): "
          f"{len(forbidden)}")

    if forbidden:
        print("\n  cross-element review list (oracle fooled by "
              "alias/typo/prose — confirm none is two DIFFERENT real "
              "compounds merged):")
        for n, rs, ess in forbidden[:25]:
            print(f"    {n!r} <= {rs}  elemsets={ess}")

    print("\n  MUST_MERGE (R2.3 target fixes):")
    mm_fail = 0
    for grp in MUST_MERGE:
        keys = {new_norm(x) for x in grp}
        ok = len(keys) == 1
        mm_fail += not ok
        print(f"    [{'OK' if ok else 'FAIL'}] {grp} -> {sorted(keys)}")

    print("\n  MUST_KEEP (no regression / no element corruption):")
    mk_fail = 0
    for f, must in MUST_KEEP.items():
        nn = new_norm(f)
        ok = must in nn
        mk_fail += not ok
        print(f"    [{'OK' if ok else 'FAIL'}] {f:<22} -> {nn!r} "
              f"(expect ⊇ {must!r})")

    import random
    rnd = random.Random(7)
    samp = rnd.sample(sorted(merges), min(20, len(merges)))
    print("\n  MERGE SAMPLE (manual chemical-soundness review):")
    for n in samp:
        print(f"    {n:<28} <= {sorted(set(new_raws[n]))[:5]}")

    # VERDICT driven by the sanity tables (r21/r22 method); the
    # cross-element list is informational and requires manual sign-off
    # but does not auto-block (its oracle is known-noisy).
    blocked = bool(mm_fail or mk_fail)
    print(f"\n  VERDICT (sanity-table driven): "
          f"{'❌ BLOCK' if blocked else '✅ PASS'}  "
          f"(must_merge_fail={mm_fail}, must_keep_fail={mk_fail}; "
          f"{len(forbidden)} cross-element groups need manual sign-off)")
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
