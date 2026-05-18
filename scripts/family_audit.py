"""Independent review of family=null materials.

Pulls EVERY family=null material from the latest aggregator output
(post-NER snapshot) and cross-checks each against an INDEPENDENT
element-chemistry classifier (deliberately NOT a copy of
nims.classify_family) plus the NER-provided per-record family vote.
A null whose independent signature OR NER vote strongly indicates a
known SC family is a suspected misclassification (错判).

Read-only. Run:
  SCLIB_EVAL_DATA=/tmp/sclib_phase4 python3 scripts/family_audit.py
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "scripts")
import aggregator_eval as E  # noqa: E402

A = E.A

# Case-insensitive element tokenizer (also catches NER lowercase
# spellings like "yba2cu3o7" that classify_family's [A-Z][a-z]? misses
# — makes this audit genuinely independent of that bug).
_KNOWN_EL = {
    "h","he","li","be","b","c","n","o","f","ne","na","mg","al","si","p","s",
    "cl","ar","k","ca","sc","ti","v","cr","mn","fe","co","ni","cu","zn","ga",
    "ge","as","se","br","kr","rb","sr","y","zr","nb","mo","tc","ru","rh","pd",
    "ag","cd","in","sn","sb","te","i","xe","cs","ba","la","ce","pr","nd","pm",
    "sm","eu","gd","tb","dy","ho","er","tm","yb","lu","hf","ta","w","re","os",
    "ir","pt","au","hg","tl","pb","bi","po","at","rn","th","pa","u","np","pu",
}


def _tokens(f: str) -> list[tuple[str, str]]:
    """Correct chemistry tokenization: greedy [A-Z][a-z]? on ORIGINAL
    case (so 'Rh' is rhodium, not R+h), with the trailing count."""
    f = re.sub(r"[\^_{}$]", "", f)
    return re.findall(r"([A-Z][a-z]?)(\d*\.?\d*)", f)


def els(f: str) -> set[str]:
    out = {t for t, _ in _tokens(f) if t.lower() in _KNOWN_EL}
    # also recover lowercase-NER element spellings (yba2cu3o7) for the
    # cuprate/iron checks only — never invents elements.
    fl = f.lower()
    for sym in ("cu", "fe", "ni", "ru", "bi"):
        if re.search(rf"(?<![a-z]){sym}\d", fl):
            out.add(sym[:1].upper() + sym[1:])
    return out


def _has_high_h(f: str) -> bool:
    """True iff a real H element token has a subscript >= 2 (so the
    'h' in Rh/Th/Hf and a bare H1 never count)."""
    for sym, cnt in _tokens(f):
        if sym == "H" and cnt:
            try:
                if float(cnt) >= 2:
                    return True
            except ValueError:
                pass
    return False


_HYDRIDE_PARTNERS = {
    "S","Se","La","Y","Ca","Mg","Sr","Ba","Th","Sc","Yb","Ce","Pr","Nd",
    "Lu","Ac","Be","Hf","Na","Li","K","Zr","Mo","W","Nb","Sn","Si","P","B","Cs",
}
_CUP_CAT = {"La","Y","Ba","Sr","Ca","Bi","Hg","Tl","Nd","Sm","Gd","Pr","Eu",
            "Tb","Dy","Ho","Er","Tm","Pb"}
_HF = {"U","Ce","Pu","Yb","Np"}
_TM_CHALC = {"Nb","Ta","Mo","W","Ti","Zr","Hf","Pd","Pt","Ir","Re","V"}


def independent_family(f: str) -> str | None:
    """Robust element-chemistry signature — independent of
    classify_family's exact regexes. Conservative: only returns a
    family on a strong, well-established signature."""
    fl = f.lower()
    e = els(f)
    if not e:
        return None
    if re.search(r"bedt-?ttf|tmtsf|\bbets\b|\(et\)|\(bdt\)|\(best\)", fl):
        return "organic"
    if re.search(r"c(?:60|70|76|78|84)\b", fl) and "C" in e:
        return "fulleride"
    # cuprate: Cu + O + a cuprate cation, but NOT a phosphate/arsenate
    # (excludes the LK-99 lead-apatite Pb9Cu(PO4)6O false positive —
    # real cuprates contain no P).
    if "Cu" in e and "O" in e and (e & _CUP_CAT) and "P" not in e:
        return "cuprate"
    # iron-based: Fe + pnictide/chalcogen, not a cuprate
    if "Fe" in e and (e & {"As","P"} or (e & {"Se","Te"}) or
                      ("S" in e and "Cu" not in e)) and "Cu" not in e:
        return "iron_based"
    # nickelate
    if "Ni" in e and "O" in e and "Cu" not in e and "Fe" not in e \
            and "B" not in e:
        return "nickelate"
    # superhydride
    if _has_high_h(f) and "O" not in e and "C" not in e \
            and (e & _HYDRIDE_PARTNERS):
        return "hydride"
    # MgB2 family
    if "Mg" in e and "B" in e and re.search(r"b[0-9]", fl) \
            and not (e & {"Cu","Fe","Ni","O"}):
        return "mgb2"
    # ruthenate
    if "Ru" in e and "O" in e and (e & {"Sr","Ca"}) and "Cu" not in e:
        return "ruthenate"
    # bismuthate vs BiS2-layered
    if "Bi" in e and "O" in e and "Cu" not in e:
        if "S" in e and (e & {"La","Ce","Pr","Nd","Sm","Eu","Gd","Y"}):
            return "bis2_layered"
        if (e & {"Ba","K","Sr"}) and "S" not in e and "Se" not in e:
            return "bismuthate"
    # borocarbide RNi2B2C
    if "Ni" in e and "B" in e and "C" in e and re.search(r"ni2b2c", fl):
        return "borocarbide"
    # kagome AV3Sb5
    if "V" in e and "Sb" in e and re.search(r"v3sb5", fl):
        return "kagome"
    # heavy fermion — classic f-electron lattice + a transition-metal
    # partner (no bare Sb/Te dipnictides like YbSb2: not HF SCs).
    if (e & _HF) and len(e) >= 2 and (e & {"In","Co","Rh","Ir","Pt",
            "Pd","Ni","Si","Ge","Al","Cu","Be","Ru"}):
        return "heavy_fermion"
    # TMD / chalcogenide
    if (e & {"S","Se","Te"}) and (e & _TM_CHALC) and "Fe" not in e \
            and "Cu" not in e and "O" not in e:
        return "chalcogenide"
    return None


def ner_family_vote(records) -> str | None:
    c = Counter()
    for r in records:
        v = r.get("family")
        if isinstance(v, str) and v.strip() and v.strip().lower() != "unknown":
            c[v.strip().lower()] += 1
    return c.most_common(1)[0][0] if c else None


def main():
    papers = E._load_jsonl(str(E.DATA / "papers.jsonl"))
    fresh, _, _ = E.run_aggregator(
        papers,
        E._build_override_map(E._load_jsonl(str(E.DATA / "overrides.jsonl"))),
        E._build_refuted_map(E._load_jsonl(str(E.DATA / "refuted.jsonl"))),
    )
    nulls = [(m, v) for m, v in fresh.items()
             if not v["summary"].get("family")]
    with_papers = [(m, v) for m, v in nulls
                   if (v["summary"].get("total_papers") or 0) > 0]
    print(f"fresh materials: {len(fresh)}")
    print(f"family=null total: {len(nulls)}  | with papers: "
          f"{len(with_papers)}")

    suspect_sig = defaultdict(list)   # independent signature says X
    suspect_ner = defaultdict(list)   # NER vote says X (sig silent)
    genuine_other = []
    for m, v in with_papers:
        s = v["summary"]
        f = s.get("formula") or ""
        sig = independent_family(f)
        nv = ner_family_vote(v["records"])
        if sig:
            suspect_sig[sig].append((f, nv, s.get("tc_max")))
        elif nv and nv not in ("conventional", "other", "elemental"):
            suspect_ner[nv].append((f, s.get("tc_max")))
        else:
            genuine_other.append(f)

    tot_sig = sum(len(x) for x in suspect_sig.values())
    tot_ner = sum(len(x) for x in suspect_ner.values())
    print(f"\n=== SUSPECTED MISCLASSIFICATION (independent signature) "
          f"= {tot_sig} ===")
    for fam, items in sorted(suspect_sig.items(),
                             key=lambda kv: -len(kv[1])):
        print(f"\n  -> should likely be '{fam}': {len(items)}")
        for f, nv, tc in items[:12]:
            print(f"     {f:<34} (NERvote={nv}, tc_max={tc})")
        if len(items) > 12:
            print(f"     ... +{len(items)-12} more")

    print(f"\n=== NER-vote suggests a family, signature silent "
          f"= {tot_ner} ===")
    for fam, items in sorted(suspect_ner.items(),
                             key=lambda kv: -len(kv[1])):
        print(f"  -> NER says '{fam}': {len(items)}  e.g. "
              f"{[f for f,_ in items[:8]]}")

    print(f"\n=== GENUINELY 'Other' (no signature, no NER family) = "
          f"{len(genuine_other)} ===")
    print("  sample:", genuine_other[:25])


if __name__ == "__main__":
    main()
