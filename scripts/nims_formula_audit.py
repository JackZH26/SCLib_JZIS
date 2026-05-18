"""NIMS-provenance formula hygiene audit (read-only).

The arXiv path runs every formula through
``formula_validator.validate_formula`` twice (NER + aggregator). The
NIMS CSV loader (ingestion/nims.py) never does — so NIMS sample
designators ("A1", "#B", "B/2", "6-delta") reach the public
``materials`` table unflagged. The periodic audit in api/main.py is
provenance-global but its SQL predicates are a strict *subset* of the
Python validator, so it misses most of them too.

This tool quantifies the gap with ZERO production risk and, crucially,
proves the proposed flag rule does not touch legitimate elemental
NIMS entries (Ag, Al, As, Au, Ba, Be ... are real superconductors).

Buckets (priority order, first match wins):
  1 validator_reject   real formula_validator says invalid -> reason.
                        Zero-risk: the project's own validator rejects
                        it; only unflagged due to the NIMS path gap.
  2 no_real_element     passes the validator but tokenises to zero
                        known chemical elements ("A1","A2","A-2").
                        A real compound ALWAYS has >=1 element, so
                        false-positive risk is ~nil.
  3 dataless_bare       has an element but NO tc_max AND NO family
                        (low-confidence; reported, NOT proposed).
  4 legit               has an element and carries data. MUST NOT flag.

Safety gate: any row in bucket 1/2 that carries tc_max or family is a
would-be FALSE POSITIVE and is listed explicitly; the rule is only
safe if that list is empty.

  python3 scripts/nims_formula_audit.py [/tmp/nims_visible.tsv]
"""
from __future__ import annotations

import re
import sys
from collections import Counter

sys.path.insert(0, "ingestion")
from ingestion.extract import formula_validator as V  # noqa: E402

# Independent lowercase element set (same membership family_audit uses;
# inlined to keep this tool free of the aggregator harness/stubs).
_KNOWN_EL = {
    "h","he","li","be","b","c","n","o","f","ne","na","mg","al","si","p","s",
    "cl","ar","k","ca","sc","ti","v","cr","mn","fe","co","ni","cu","zn","ga",
    "ge","as","se","br","kr","rb","sr","y","zr","nb","mo","tc","ru","rh","pd",
    "ag","cd","in","sn","sb","te","i","xe","cs","ba","la","ce","pr","nd","pm",
    "sm","eu","gd","tb","dy","ho","er","tm","yb","lu","hf","ta","w","re","os",
    "ir","pt","au","hg","tl","pb","bi","po","at","rn","th","pa","u","np","pu",
}


def has_real_element(f: str) -> bool:
    f = re.sub(r"[\^_{}$]", "", f)
    return any(t.lower() in _KNOWN_EL
               for t, _ in re.findall(r"([A-Z][a-z]?)(\d*\.?\d*)", f))


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/nims_visible.tsv"
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            mid, formula, tc, fam = parts[0], parts[1], parts[2], parts[3]
            formula = formula.strip('"')
            rows.append((mid, formula, tc.strip('"'), fam.strip('"')))

    buckets: dict[str, list] = {
        "validator_reject": [], "no_real_element": [],
        "dataless_bare": [], "legit": []}
    reasons: Counter[str] = Counter()
    false_pos: list = []

    for mid, formula, tc, fam in rows:
        has_data = bool(tc) or bool(fam)
        ok, reason = V.validate_formula(V.normalize_whitespace(formula))
        if not ok:
            buckets["validator_reject"].append((mid, formula, tc, fam))
            reasons[reason] += 1
            if has_data:
                false_pos.append((mid, formula, tc, fam, reason))
        elif not has_real_element(formula):
            buckets["no_real_element"].append((mid, formula, tc, fam))
            if has_data:
                false_pos.append((mid, formula, tc, fam, "no_real_element"))
        elif not has_data:
            buckets["dataless_bare"].append((mid, formula, tc, fam))
        else:
            buckets["legit"].append((mid, formula, tc, fam))

    n = len(rows)
    print(f"\n===== NIMS visible formula audit ({n} rows) =====")
    for b in ("validator_reject", "no_real_element",
              "dataless_bare", "legit"):
        print(f"  {b:18s}: {len(buckets[b]):5d}")

    # The full validator is NER-prose-tuned and UNSAFE on NIMS:
    # forbidden_char/invalid_start reject legit delta/polytype NIMS
    # notation (Fe1-xSe, 2H-NbSe). Proven by would-be FALSE POS below.
    # The only zero-risk signal is: tokenises to NO known element AND
    # carries no tc_max and no family -> a pure dataless designator.
    safe_rows = [(mid, f, tc, fam)
                 for (mid, f, tc, fam) in buckets["no_real_element"]
                 if not (tc or fam)]
    print(f"  {'-'*38}")
    print(f"  full-validator-on-NIMS would FALSE-POS : {len(false_pos):5d}"
          f"  (UNSAFE — kills real SC)")
    print(f"  TIGHTENED SAFE RULE (no element & no   : {len(safe_rows):5d}"
          f"  ({100*len(safe_rows)/n:.1f}% of NIMS)")
    print(f"   tc & no family; 0 data-bearing rows)")

    print("\n  validator_reject by reason:")
    for r, c in reasons.most_common():
        print(f"    {r:34s} {c}")

    print("\n  sample no_real_element (proposed new catch):")
    seen = set()
    for mid, f, tc, fam in buckets["no_real_element"]:
        if f not in seen:
            seen.add(f)
            print(f"    {f!r}")
        if len(seen) >= 30:
            break

    if false_pos:
        print(f"\n  !! {len(false_pos)} FALSE POSITIVES (carry data — "
              f"do NOT flag); rule must be tightened:")
        for mid, f, tc, fam, why in false_pos[:40]:
            print(f"    [{why}] {f!r} tc={tc!r} fam={fam!r}  {mid}")
    else:
        print("\n  no false positives: every flagged row is "
              "data-free. RULE IS SAFE.")

    print("\n  sample dataless_bare (has element, no data — "
          "reported only, NOT proposed):")
    seen = set()
    for mid, f, tc, fam in buckets["dataless_bare"]:
        if f not in seen:
            seen.add(f)
            print(f"    {f!r}")
        if len(seen) >= 20:
            break

    print(f"\n  FULL tightened-safe set ({len(safe_rows)} rows, "
          f"every formula listed for review):")
    for f in sorted({r[1] for r in safe_rows}, key=lambda x: (len(x), x)):
        print(f"    {f!r}")
    out = "/tmp/nims_designator_ids.txt"
    with open(out, "w", encoding="utf-8") as fh:
        for mid, f, tc, fam in safe_rows:
            fh.write(mid + "\n")
    print(f"\n  -> {len(safe_rows)} ids written to {out} "
          f"(for the gated flag step; review the list above first)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
