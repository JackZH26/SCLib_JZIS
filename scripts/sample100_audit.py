"""Random-100 false-negative spot-check of the PUBLIC materials set.

Audits a reproducible random sample of needs_review=FALSE rows (the
data actually served at /sclib/materials) against the four residual
problem classes, using INDEPENDENT oracles — never the same guardrail
that already flagged the rest (that would only re-confirm true
positives; the point here is to estimate the false-NEGATIVE rate).

  A  NER prose / junk        formula_validator + element oracle
                             (validator-reject alone is NOT class A on
                             NIMS: delta/polytype notation is legit —
                             only no-real-element / prose words count)
  B  Tc sanity              global >250 K, family ceiling
                             (mirrors materials_aggregator P1), and
                             theoretical-headline (dominant_evidence)
  C  family misclassification independent_family() (mirrors
                             scripts/family_audit.py — deliberately
                             NOT nims.classify_family) vs stored family
  D  near-duplicate          element-stoichiometry signature collision
                             across the whole public set; same-prefix
                             collisions are the real concern,
                             mat:/nims: cross-prefix is by-design

  python3 scripts/sample100_audit.py /tmp/sample100.tsv /tmp/public_all.tsv
"""
from __future__ import annotations

import csv
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "ingestion")
from ingestion.extract import formula_validator as V  # noqa: E402

# --- inlined independent oracles (mirror sources noted) -------------
# scripts/family_audit.py ::_KNOWN_EL
_KNOWN_EL = {
    "h","he","li","be","b","c","n","o","f","ne","na","mg","al","si","p","s",
    "cl","ar","k","ca","sc","ti","v","cr","mn","fe","co","ni","cu","zn","ga",
    "ge","as","se","br","kr","rb","sr","y","zr","nb","mo","tc","ru","rh","pd",
    "ag","cd","in","sn","sb","te","i","xe","cs","ba","la","ce","pr","nd","pm",
    "sm","eu","gd","tb","dy","ho","er","tm","yb","lu","hf","ta","w","re","os",
    "ir","pt","au","hg","tl","pb","bi","po","at","rn","th","pa","u","np","pu",
}
# ingestion/.../materials_aggregator.py:147 ::_FAMILY_TC_CEILING_K
_CEIL = {
    "cuprate":180.0,"iron_based":110.0,"nickelate":110.0,"mgb2":50.0,
    "fulleride":50.0,"bismuthate":45.0,"conventional":45.0,
    "chalcogenide":40.0,"elemental":40.0,"borocarbide":30.0,
    "bis2_layered":30.0,"heavy_fermion":30.0,"organic":25.0,
    "kagome":15.0,"ruthenate":10.0,
}
_HYDRIDE_PARTNERS = {"S","Se","La","Y","Ca","Mg","Sr","Ba","Th","Sc","Yb",
    "Ce","Pr","Nd","Lu","Ac","Be","Hf","Na","Li","K","Zr","Mo","W","Nb",
    "Sn","Si","P","B","Cs"}
_CUP_CAT = {"La","Y","Ba","Sr","Ca","Bi","Hg","Tl","Nd","Sm","Gd","Pr",
            "Eu","Tb","Dy","Ho","Er","Tm","Pb"}
_HF = {"U","Ce","Pu","Yb","Np"}
_TM_CHALC = {"Nb","Ta","Mo","W","Ti","Zr","Hf","Pd","Pt","Ir","Re","V"}


def _tokens(f: str):
    f = re.sub(r"[\^_{}$]", "", f)
    return re.findall(r"([A-Z][a-z]?)(\d*\.?\d*)", f)


def els(f: str) -> set[str]:
    out = {t for t, _ in _tokens(f) if t.lower() in _KNOWN_EL}
    fl = f.lower()
    for sym in ("cu", "fe", "ni", "ru", "bi"):
        if re.search(rf"(?<![a-z]){sym}\d", fl):
            out.add(sym[:1].upper() + sym[1:])
    return out


def _has_high_h(f: str) -> bool:
    for sym, cnt in _tokens(f):
        if sym == "H" and cnt:
            try:
                if float(cnt) >= 2:
                    return True
            except ValueError:
                pass
    return False


def independent_family(f: str):
    fl = f.lower(); e = els(f)
    if not e:
        return None
    if re.search(r"bedt-?ttf|tmtsf|\bbets\b|\(et\)|\(bdt\)|\(best\)", fl):
        return "organic"
    if re.search(r"c(?:60|70|76|78|84)\b", fl) and "C" in e:
        return "fulleride"
    if "Cu" in e and "O" in e and (e & _CUP_CAT) and "P" not in e:
        return "cuprate"
    if "Fe" in e and (e & {"As","P"} or (e & {"Se","Te"}) or
                      ("S" in e and "Cu" not in e)) and "Cu" not in e:
        return "iron_based"
    if "Ni" in e and "O" in e and "Cu" not in e and "Fe" not in e \
            and "B" not in e:
        return "nickelate"
    if _has_high_h(f) and "O" not in e and "C" not in e \
            and (e & _HYDRIDE_PARTNERS):
        return "hydride"
    if "Mg" in e and "B" in e and re.search(r"b[0-9]", fl) \
            and not (e & {"Cu","Fe","Ni","O"}):
        return "mgb2"
    if "Ru" in e and "O" in e and (e & {"Sr","Ca"}) and "Cu" not in e:
        return "ruthenate"
    if "Bi" in e and "O" in e and "Cu" not in e:
        if "S" in e and (e & {"La","Ce","Pr","Nd","Sm","Eu","Gd","Y"}):
            return "bis2_layered"
        if (e & {"Ba","K","Sr"}) and "S" not in e and "Se" not in e:
            return "bismuthate"
    if "Ni" in e and "B" in e and "C" in e and re.search(r"ni2b2c", fl):
        return "borocarbide"
    if "V" in e and "Sb" in e and re.search(r"v3sb5", fl):
        return "kagome"
    if (e & _HF) and len(e) >= 2 and (e & {"In","Co","Rh","Ir","Pt",
            "Pd","Ni","Si","Ge","Al","Cu","Be","Ru"}):
        return "heavy_fermion"
    if (e & {"S","Se","Te"}) and (e & _TM_CHALC) and "Fe" not in e \
            and "Cu" not in e and "O" not in e:
        return "chalcogenide"
    return None


def has_real_element(f: str) -> bool:
    return bool(els(f))


def dup_sig(formula: str) -> str | None:
    """Element-stoichiometry signature: doping placeholders dropped so
    near-dups (delta/x variants) collapse. None if no real element."""
    toks = [(t, c) for t, c in _tokens(formula) if t.lower() in _KNOWN_EL]
    if not toks:
        return None
    parts = []
    for t, c in toks:
        c = c.strip(".")
        parts.append(f"{t}{c}" if c else t)
    return "|".join(sorted(parts))


def _rows(path):
    # Postgres COPY ... FORMAT csv quotes empty fields as "" and any
    # field containing a quote — a naive split("\t") would treat ""
    # as a non-empty string (corrupts NULL family / empty tc checks).
    with open(path, encoding="utf-8", newline="") as fh:
        return [r for r in csv.reader(fh, delimiter="\t") if r and any(r)]


def main() -> int:
    sample = _rows(sys.argv[1] if len(sys.argv) > 1
                   else "/tmp/sample100.tsv")
    public = _rows(sys.argv[2] if len(sys.argv) > 2
                   else "/tmp/public_all.tsv")

    # D: signature -> set of distinct ids across the whole public set
    sig_ids: dict[str, set[str]] = defaultdict(set)
    for r in public:
        if len(r) < 3:
            continue
        sig = dup_sig(r[1])
        if sig:
            sig_ids[sig].add(r[0])

    A: list = []; B: list = []; C: list = []; D: list = []
    cat = Counter()
    for r in sample:
        mid, formula, fnorm, fam, tc, tce, tct, dom = (r + [""]*8)[:8]
        tcf = None
        try:
            tcf = float(tc) if tc else None
        except ValueError:
            pass

        # ---- A ----
        ok, reason = V.validate_formula(V.normalize_whitespace(formula))
        if not has_real_element(formula):
            A.append((mid, formula, "no_real_element")); cat["A"] += 1
        elif (not ok) and reason in (
                V.DESCRIPTIVE_WORD, V.CONCATENATED_PROSE,
                V.LITERAL_PLACEHOLDER, V.GENERIC_FAMILY_NAME,
                V.ENGLISH_ELEMENT_NAME, V.TRADE_NAME):
            A.append((mid, formula, reason)); cat["A"] += 1

        # ---- B ----
        if tcf is not None and tcf > 250:
            B.append((mid, formula, f"tc={tcf:g}>250 abs")); cat["B"] += 1
        elif tcf is not None and fam in _CEIL and tcf > _CEIL[fam]:
            B.append((mid, formula,
                      f"tc={tcf:g}>{_CEIL[fam]:g} {fam} ceil"))
            cat["B"] += 1
        elif dom == "theoretical" and not tce and tcf is not None:
            B.append((mid, formula,
                      f"headline tc={tcf:g} theoretical-only"))
            cat["B-soft"] += 1

        # ---- C ----
        indep = independent_family(formula)
        if indep and fam and indep != fam:
            C.append((mid, formula, f"stored={fam} indep={indep}"))
            cat["C"] += 1
        elif indep and not fam:
            C.append((mid, formula, f"stored=NULL indep={indep}"))
            cat["C-miss"] += 1

        # ---- D ----
        sig = dup_sig(formula)
        if sig and len(sig_ids.get(sig, ())) > 1:
            others = sorted(sig_ids[sig] - {mid})
            same_pfx = any(o.split(":")[0] == mid.split(":")[0]
                           for o in others)
            D.append((mid, formula, others[:3],
                      "SAME-prefix" if same_pfx else "cross(by-design)"))
            cat["D" if same_pfx else "D-xprov"] += 1

    n = len(sample)
    print(f"\n===== RANDOM-{n} PUBLIC SPOT-CHECK (A/B/C/D) =====")
    print(f"  A  NER junk (hard)        : {cat['A']}")
    print(f"  B  Tc sanity (hard)       : {cat['B']}")
    print(f"  B  Tc theoretical (soft)  : {cat['B-soft']}")
    print(f"  C  family wrong (hard)    : {cat['C']}")
    print(f"  C  family NULL-miss (soft): {cat['C-miss']}")
    print(f"  D  same-prefix dup (hard) : {cat['D']}")
    print(f"  D  cross-prov (by-design) : {cat['D-xprov']}")
    hard = cat['A'] + cat['B'] + cat['C'] + cat['D']
    print(f"  {'-'*38}")
    print(f"  HARD problems            : {hard}/{n}")
    print(f"  clean (no hard issue)    : {n-hard}/{n} "
          f"(hard-problem est. {100*hard/n:.0f}%)")

    for tag, rows in (("A", A), ("B", B), ("C", C), ("D", D)):
        if rows:
            print(f"\n  --- class {tag} cases ({len(rows)}) ---")
            for item in rows[:30]:
                print(f"    {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
