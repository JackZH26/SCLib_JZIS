"""Rigorous 100-sample scientific audit of family=null materials.

For each sampled material checks 5 independent dimensions:
  A. family correctness   (independent chemistry signature + NER vote)
  B. non-SC contaminant   (manganite/ferroelectric/substrate scraped
                           by NER as a fake "material")
  C. Tc plausibility      (the family-Tc-cap blind spot: absurd Tc on
                           a family=null row is never guarded)
  D. near-duplicate       (fragmented across cosmetic-notation rows)
  E. formula/notation     (garbage / isotope / odd notation)

Read-only. Run:
  SCLIB_EVAL_DATA=/tmp/sclib_phase4 python3 scripts/family_null_audit100.py
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "scripts")
import aggregator_eval as E      # noqa: E402
import family_audit as FA        # noqa: E402  (independent classifier)

A = E.A
N = 100
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 20260518


def _toks(f):
    return FA._tokens(f)


def is_non_sc_contaminant(f, els):
    """High-confidence NON-superconductor compounds NER scraped as
    materials (CMR manganites, ferroelectrics, plain substrates)."""
    fl = f.lower()
    # CMR / ferromagnetic manganites: A(1-x)A'(x)MnO3 (La/Pr/Nd/Sm/Y +
    # Ca/Sr/Ba + Mn + O). Not superconductors (ferromagnetic metals).
    if "Mn" in els and "O" in els and (els & {"La","Pr","Nd","Sm","Y",
            "Ca","Sr","Ba","Bi"}) and "Cu" not in els and "Fe" not in els:
        if re.search(r"mno3|mno_?3|mn2o|manganit", fl) or "Mn" in els:
            return "manganite_CMR_not_SC"
    # Plain perovskite substrates / ferroelectrics with no dopant
    if re.fullmatch(r"(srtio3|ktao3|batio3|laalo3|mgo|al2o3|sio2|"
                    r"pbtio3|catio3|latio3|sno2|tio2|zno|ga2o3)", fl):
        return "substrate_or_ferroelectric"
    # Pure elemental gases / non-SC simple compounds NER over-extracts
    if fl in ("o2","n2","h2o","co2","sio2","nacl","kcl"):
        return "non_material"
    return None


def main():
    papers = E._load_jsonl(str(E.DATA / "papers.jsonl"))
    fresh, _, _ = E.run_aggregator(
        papers,
        E._build_override_map(E._load_jsonl(str(E.DATA / "overrides.jsonl"))),
        E._build_refuted_map(E._load_jsonl(str(E.DATA / "refuted.jsonl"))),
    )
    # near-dup signature over ALL fresh (alnum-collapsed -> >1 norm)
    sig = defaultdict(set)
    sig_forms = defaultdict(list)
    for v in fresh.values():
        f = v["summary"].get("formula") or ""
        k = re.sub(r"[^a-z0-9]", "", f.lower())
        if k:
            sig[k].add(v["norm"])
            sig_forms[k].append(f)
    dup_sigs = {k for k, s in sig.items() if len(s) > 1}

    nulls = [(m, v) for m, v in fresh.items()
             if not v["summary"].get("family")
             and (v["summary"].get("total_papers") or 0) > 0]
    import random
    rnd = random.Random(SEED)
    sample = rnd.sample(nulls, min(N, len(nulls)))
    print(f"family=null with papers: {len(nulls)}; auditing {len(sample)}"
          f" (seed={SEED})\n")

    cat = Counter()
    detail = defaultdict(list)
    for m, v in sample:
        s = v["summary"]
        f = s.get("formula") or ""
        tc = s.get("tc_max")
        e = FA.els(f)
        issues = []

        # B. non-SC contaminant
        nsc = is_non_sc_contaminant(f, e)
        if nsc:
            issues.append(nsc)

        # A. family 错判
        sigfam = FA.independent_family(f)
        nv = FA.ner_family_vote(v["records"])
        if sigfam:
            issues.append(f"misclassified_should_be_{sigfam}")
        elif nv and nv not in ("conventional", "other", "elemental",
                               "unknown") and not nsc:
            issues.append(f"NER_says_{nv}_verify")

        # C. implausible Tc on family=null (blind spot of family-Tc-cap)
        if (tc is not None and not sigfam and not nsc
                and not FA._has_high_h(f) and tc > 40):
            issues.append(f"implausible_tc_{tc}K_on_null")

        # D. near-duplicate fragment
        k = re.sub(r"[^a-z0-9]", "", f.lower())
        if k in dup_sigs:
            sibs = sorted(set(sig_forms[k]) - {f})
            issues.append(f"near_dup(siblings={sibs[:3]})")

        # E. formula notation oddity
        ok, why = A._formula_validator.validate_formula(
            A._formula_validator.normalize_whitespace(f))
        if not ok:
            issues.append(f"formula_reject_{why}")

        if not issues:
            cat["A. correctly_null_Other"] += 1
        else:
            for it in issues:
                head = it.split("(")[0].split("_should")[0]
                cat[head if head in (
                    "manganite", "substrate", "non") else it.split(
                    "(")[0]] += 0  # placeholder; real tally below
            primary = issues[0]
            tag = ("CONTAMINANT" if (nsc) else
                   "FAMILY_MISCLASS" if primary.startswith("misclassified")
                   else "TC_IMPLAUSIBLE" if "implausible_tc" in primary
                   else "NEAR_DUP" if primary.startswith("near_dup")
                   else "NER_VERIFY" if primary.startswith("NER_says")
                   else "FORMULA_ODD")
            cat[tag] += 1
            detail[tag].append((f, tc, s.get("dominant_evidence"),
                                 v["n_records"], "; ".join(issues)))

    print("=== CATEGORY TALLY (of %d) ===" % len(sample))
    order = ["A. correctly_null_Other", "FAMILY_MISCLASS", "CONTAMINANT",
             "TC_IMPLAUSIBLE", "NEAR_DUP", "NER_VERIFY", "FORMULA_ODD"]
    for kx in order:
        if cat.get(kx):
            print(f"  {kx:<26} {cat[kx]}")
    print()
    for kx in order[1:]:
        if detail.get(kx):
            print(f"=== {kx} ({len(detail[kx])}) ===")
            for f, tc, ev, nr, why in detail[kx]:
                print(f"  {f:<32} tc={str(tc):<7} ev={str(ev):<11}"
                      f" n={nr}  :: {why}")
            print()


if __name__ == "__main__":
    main()
