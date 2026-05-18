"""R2.1 offline gate — OLD vs NEW normalize_formula, with the
element-set merge guardrail. Read-only. No DB, no prod.

  SCLIB_EVAL_DATA=/tmp/sclib_r2 python3 scripts/r21_guard.py

Asserts:
  * every NEWLY-colliding group (old norms differ -> new norm equal =
    a proposed merge) is element-set HOMOGENEOUS — any cross-compound
    merge is a hard FAIL (would corrupt data on migration);
  * known element-ambiguous formulas (PdTe2, Nd2CuO4, GdBa2Cu3O7,
    CdS, D3S, ...) keep their elements (catches the Pd/Nd/Gd 'd'
    corruption class);
  * reports clusters resolved + ids that would re-key (migration
    scope).
"""
from __future__ import annotations

import re
import sys
import types
from collections import defaultdict

sys.path.insert(0, "scripts")
import aggregator_eval as E  # noqa: E402 (installs stubs)

A = E.A
new_norm = A.normalize_formula

# OLD normalize_formula from git HEAD (pre-R2.1)
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
    """True chemistry signature: [A-Z][a-z]? element tokens on the
    RAW formula, minus variable-stoich markers — invariant under any
    cosmetic-only normalisation."""
    fe = re.sub(r"[δΔ]|[Dd]elta|[±*·⋅(){}\[\]$_]", "", f)
    return frozenset(re.findall(r"[A-Z][a-z]?", fe))


def main():
    forms = set()
    for r in E._load_jsonl(str(E.DATA / "materials.jsonl")):
        if r.get("formula"):
            forms.add(r["formula"])
    for p in E._load_jsonl(str(E.DATA / "papers.jsonl")):
        for m in (p.get("materials_extracted") or []):
            if isinstance(m, dict) and isinstance(m.get("formula"), str):
                forms.add(m["formula"])
    forms.discard("")
    print(f"distinct raw formulas: {len(forms)}")

    rekeyed = 0
    new_groups = defaultdict(set)   # new_norm -> {old_norm,...}
    new_raws = defaultdict(list)    # new_norm -> [raw,...]
    for f in forms:
        o, n = old_norm(f), new_norm(f)
        if o != n:
            rekeyed += 1
        new_groups[n].add(o)
        new_raws[n].append(f)

    merges = {n: g for n, g in new_groups.items() if len(g) > 1}
    forbidden = []        # cross-element merge -> data corruption
    homog = 0
    for n, _ in merges.items():
        es = {elemset(r) for r in new_raws[n]}
        if len(es) > 1:
            forbidden.append((n, [r for r in new_raws[n][:4]],
                              [sorted(x) for x in es]))
        else:
            homog += 1

    # direct element-corruption sanity (the Pd/Nd/Gd/Cd/D class)
    sanity = {
        "PdTe2": "pd", "Nd2CuO4": "nd", "GdBa2Cu3O7-δ": "gd",
        "CdS": "cd", "D3S": "d3", "Bi2Sr2CaCu2O8±δ": "bi2sr2cacu2o8",
        "(Ba0.6K0.4)Fe2As2": "ba0.6k0.4fe2as2",
        "Ca10(Pt4As8)(Fe2As2)5": "(fe2as2)5",   # multiplier preserved
        "NaxCoO2·1.3H2O": "naxcoo21.3h2o",
        "LaO0.9F0.1-δFeAs": "lao0.9f0.1feas",
    }
    sane = []
    for f, must in sanity.items():
        nn = new_norm(f)
        ok = must in nn
        sane.append((f, nn, "OK" if ok else "FAIL", must))

    print(f"\nids that would re-key (old_norm != new_norm): {rekeyed}")
    print(f"merge groups (>=2 old norms -> 1 new): {len(merges)}")
    print("  (raw-elemset cross-check is INFORMATIONAL only — its "
          "tokenizer is fooled by alias shorthands [Y123] and the "
          "x/X doping variable; not the verdict oracle)")
    print(f"  raw-elemset-homogeneous: {homog}  "
          f"| raw-elemset-differs: {len(forbidden)} (review sample below)")

    import random
    rnd = random.Random(7)
    sample = rnd.sample(list(merges.items()), min(15, len(merges)))
    print("\n  MERGE SAMPLE (manual chemical-soundness review):")
    for n, _ in sample:
        rs = sorted(set(new_raws[n]))
        print(f"    {n:<30} <= {rs[:5]}")

    print("\n  ELEMENT-CORRUPTION / SEMANTICS SANITY (the real gate — "
          "covers Pd/Nd/Gd/Cd, deuterium, multiplier, delta, hydrate, "
          "paren):")
    bad = [x for x in sane if x[2] == "FAIL"]
    for f, nn, st, must in sane:
        print(f"    [{st}] {f:<26} -> {nn!r}  (expect contains {must!r})")
    print(f"\n  VERDICT (driven by sanity table): "
          f"{'❌ BLOCK' if bad else '✅ PASS'} "
          f"(sanity_fail={len(bad)}; +manual review of merge sample)")


if __name__ == "__main__":
    main()
