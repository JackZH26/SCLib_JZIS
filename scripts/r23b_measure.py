"""R2.3b element-ORDER canonicalization — OFFLINE MEASUREMENT ONLY.

Does NOT modify production normalize_formula. Applies a candidate
element-token sort ON TOP of the current (R2.3a) normalize and
measures, over the full prod corpus:

  * how many ids would re-key  (migration blast radius)
  * how many NEW merge groups  (genuine order-variant de-frag, e.g.
    LaMnPO ≡ LaOMnP, FeTe0.8Se0.2 ≡ FeSe0.2Te0.8)
  * element-set homogeneity of every merge (cross-element = the
    tokenizer mangled a doping/paren placeholder = corruption risk)

Element order in a chemical formula is not identity-bearing
(BaFe2As2 ≡ Fe2As2Ba), so a correct sort should yield ONLY
element-homogeneous merges; cross-element groups quantify the
implementation risk for the decision.

  python3 scripts/r23b_measure.py /tmp/prod_all_formulas.tsv
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict

sys.path.insert(0, "scripts")
import aggregator_eval as E  # noqa: E402 (stubs)

A = E.A
norm = A.normalize_formula  # current (R2.3a) production normalize


def order_canon(raw: str) -> str:
    """Candidate: sort element tokens (symbol+trailing count) into a
    canonical order before normalize. Grouping chars stripped first
    so tokenization isn't broken by them (normalize drops them too)."""
    f = re.sub(r"[(){}\[\]·*]", "", raw)
    toks = re.findall(r"([A-Z][a-z]?)(\d*\.?\d*)", f)
    if len(toks) < 2:
        return raw
    return "".join(e + c for e, c in sorted(toks, key=lambda t: t[0]))


def elemset(f: str):
    fl = f.lower()
    if A.normalize_formula(f) in getattr(A, "_FORMULA_ALIASES", {}):
        return None
    if re.search(r"cuprate|nanotube|diamond|phenanthrene|graphene|"
                 r"systems?|doped|walled|hight?c|amorphous", fl):
        return None
    fe = re.sub(r"[δΔ]|[Dd]elta|[±*·⋅(){}\[\]$_^/,-]", "", f)
    return frozenset(re.findall(r"[A-Z][a-z]?", fe))


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/prod_all_formulas.tsv"
    forms = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 2 and p[1]:
                forms.add(p[1])
    print(f"distinct raw formulas (prod corpus): {len(forms)}")

    rekeyed = 0
    groups = defaultdict(set)   # new(order) key -> {old(R2.3a) key,...}
    raws = defaultdict(list)
    for f in forms:
        o = norm(f)
        n = norm(order_canon(f))
        if o != n:
            rekeyed += 1
        groups[n].add(o)
        raws[n].append(f)

    merges = {k: v for k, v in groups.items() if len(v) > 1}
    homog, cross = 0, []
    for k in merges:
        es = {x for x in (elemset(r) for r in raws[k]) if x is not None}
        if len(es) > 1:
            cross.append((k, sorted(set(raws[k]))[:5],
                          [sorted(x) for x in es]))
        else:
            homog += 1

    print(f"\nids that would re-key (R2.3a -> +order): {rekeyed} "
          f"({100*rekeyed/max(len(forms),1):.0f}% of distinct formulas)")
    print(f"NEW merge groups (order-variant de-frag): {len(merges)}")
    print(f"  element-homogeneous (safe): {homog}")
    print(f"  CROSS-ELEMENT (tokenizer risk): {len(cross)}")
    for k, rs, ess in cross[:20]:
        print(f"    {k!r} <= {rs}  elemsets={ess}")

    import random
    rnd = random.Random(7)
    samp = rnd.sample(sorted(merges), min(20, len(merges)))
    print("\n  MERGE SAMPLE (order-variant unification):")
    for k in samp:
        print(f"    {k:<26} <= {sorted(set(raws[k]))[:4]}")

    print(f"\n  SUMMARY: rekey={rekeyed}  merges={len(merges)}  "
          f"cross_elem={len(cross)}  (measurement only — no prod)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
