"""Cross-model comparison: 5-run intra-model variance + inter-model agreement.

After Sonnet removal, the dataset has:
  - Opus 4.7         × 5 runs
  - GPT-5.5          × 5 runs
  - GPT-5.4-mini     × 5 runs
  - Gemini 2.5 Flash × 1 run (production single-shot)

Run from repo root:  python3 scripts/audit_compare_all.py
"""
from __future__ import annotations
import json
import math
import sqlite3
import statistics
from itertools import combinations
from collections import Counter
import pathlib

DB = pathlib.Path(__file__).resolve().parents[1] / "audit" / "audit_review.db"

MODELS = [
    ("Opus 4.7",         "claude-opus-4-7",    5),
    ("GPT-5.5",          "gpt-5.5",            5),
    ("GPT-5.4-mini",     "gpt-5.4-mini",       5),
    ("Gemini 2.5 Flash", "gemini-2.5-flash",   1),
]


def normalize_formula(f: str | None) -> str:
    if not f:
        return ""
    s = str(f).lower().replace("-", "").replace(" ", "")
    for sub_d, plain in zip("₀₁₂₃₄₅₆₇₈₉", "0123456789"):
        s = s.replace(sub_d, plain)
    return s


def load_material(conn, m, ri):
    out = {}
    for pid, mj in conn.execute(
        "SELECT paper_id, materials_json FROM audit_extraction_model "
        "WHERE model_name = ? AND run_idx = ? AND prompt_version='material_ner_v2_core'",
        (m, ri),
    ):
        try:
            arr = json.loads(mj) if mj else []
            out[pid] = arr if isinstance(arr, list) else []
        except Exception:
            out[pid] = []
    return out


def load_geo(conn, m, ri):
    out = {}
    for pid, pg in conn.execute(
        "SELECT paper_id, paper_geo_json FROM audit_extraction_model "
        "WHERE model_name = ? AND run_idx = ? AND prompt_version LIKE 'geo_%'",
        (m, ri),
    ):
        if pg:
            try:
                out[pid] = json.loads(pg)
            except Exception:
                out[pid] = {}
    return out


def hr(c="=", w=82):
    print(c * w)


def main():
    conn = sqlite3.connect(DB)

    # Preload r0 for all models (used in multiple sections)
    r0_mat = {m: load_material(conn, m, 0) for _, m, _ in MODELS}

    # =====================================================================
    print()
    hr()
    print("§1. RECALL — single-run (r0) Material NER")
    hr()
    print(f"{'Model':<22} {'empty':<8} {'non-empty':<11} {'total records':<15} {'mean':<8} {'median':<8} {'max':<5}")
    print("-" * 82)
    for label, m, _ in MODELS:
        counts = [len(v) for v in r0_mat[m].values()]
        nonempty = [c for c in counts if c > 0]
        empty = sum(1 for c in counts if c == 0)
        total = sum(counts)
        mean_n = statistics.mean(nonempty) if nonempty else 0
        med_n = statistics.median(nonempty) if nonempty else 0
        max_n = max(nonempty) if nonempty else 0
        print(f"{label:<22} {empty:<8} {len(nonempty):<11} {total:<15} {mean_n:<8.2f} {med_n:<8.1f} {max_n:<5}")

    # =====================================================================
    print()
    hr()
    print("§2. INTER-MODEL formula overlap rate at r0")
    print("   (papers with ≥1 normalized-formula overlap / papers with both non-empty)")
    hr()
    print(f"{'':<22}", end="")
    for lbl, _, _ in MODELS:
        print(f"{lbl:<18}", end="")
    print()
    for i, (li, mi, _) in enumerate(MODELS):
        print(f"{li:<22}", end="")
        for j, (lj, mj, _) in enumerate(MODELS):
            if i == j:
                print(f"{'—':<18}", end="")
                continue
            overlap = 0; denom = 0
            for pid in r0_mat[mi]:
                if pid not in r0_mat[mj]:
                    continue
                fi = {normalize_formula(r.get("formula", "")) for r in r0_mat[mi][pid] if isinstance(r, dict) and r.get("formula")}
                fj = {normalize_formula(r.get("formula", "")) for r in r0_mat[mj][pid] if isinstance(r, dict) and r.get("formula")}
                if fi and fj:
                    denom += 1
                    if fi & fj:
                        overlap += 1
            rate = (100.0 * overlap / denom) if denom else 0
            print(f"{rate:>5.1f}% ({overlap:>2}/{denom:>2})    ", end="")
        print()

    # =====================================================================
    print()
    hr()
    print("§3. INTRA-MODEL variance: pairwise r-vs-r byte diff (Material NER)")
    hr()
    print(f"{'Model':<22} {'N runs':<8} {'pairs':<8} {'identical%':<13} {'count-diff%':<13} {'median |Δn|':<12}")
    print("-" * 82)
    for label, m, nruns in MODELS:
        if nruns < 2:
            continue
        runs = {ri: load_material(conn, m, ri) for ri in range(nruns)}
        identical = 0; differ = 0
        count_diff_papers = 0
        n_changes = []
        pair_obs = 0
        for ri, rj in combinations(range(nruns), 2):
            for pid in runs[ri]:
                if pid not in runs[rj]:
                    continue
                pair_obs += 1
                a = runs[ri][pid]; b = runs[rj][pid]
                if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True):
                    identical += 1
                else:
                    differ += 1
                if len(a) != len(b):
                    count_diff_papers += 1
                    n_changes.append(abs(len(a) - len(b)))
        id_pct = 100.0 * identical / pair_obs if pair_obs else 0
        cd_pct = 100.0 * count_diff_papers / pair_obs if pair_obs else 0
        med_dn = statistics.median(n_changes) if n_changes else 0
        print(f"{label:<22} {nruns:<8} {pair_obs:<8} {id_pct:<13.1f} {cd_pct:<13.1f} {med_dn:<12.1f}")

    # =====================================================================
    print()
    hr()
    print("§4. SELF-CONSISTENCY (distinct outputs per paper across N runs)")
    hr()
    print(f"{'Model':<22} {'all 5 same':<14} {'all 5 distinct':<16} {'mean uniq / paper':<18}")
    print("-" * 82)
    for label, m, nruns in MODELS:
        if nruns < 2:
            continue
        runs = {ri: load_material(conn, m, ri) for ri in range(nruns)}
        uniq_counts = []
        all_same = 0
        all_distinct = 0
        for pid in runs[0]:
            outputs = []
            for ri in range(nruns):
                if pid in runs[ri]:
                    outputs.append(json.dumps(runs[ri][pid], sort_keys=True))
            if len(outputs) != nruns:
                continue
            n_u = len(set(outputs))
            uniq_counts.append(n_u)
            if n_u == 1:
                all_same += 1
            elif n_u == nruns:
                all_distinct += 1
        n_papers = len(uniq_counts)
        same_pct = 100.0 * all_same / n_papers if n_papers else 0
        dist_pct = 100.0 * all_distinct / n_papers if n_papers else 0
        mean_u = statistics.mean(uniq_counts) if uniq_counts else 0
        print(f"{label:<22} {all_same:>3} ({same_pct:>5.1f}%)  {all_distinct:>3} ({dist_pct:>5.1f}%)   {mean_u:.2f} / {nruns}")

    # =====================================================================
    print()
    hr()
    print("§5. FORMULA SET stability — across N runs, do papers stabilize on the same set?")
    print("   For papers with ≥1 record in any run: how many distinct formula-sets does ")
    print("   each paper produce?")
    hr()
    print(f"{'Model':<22} {'5 same set':<15} {'mean uniq sets':<18}")
    print("-" * 82)
    for label, m, nruns in MODELS:
        if nruns < 2:
            continue
        runs = {ri: load_material(conn, m, ri) for ri in range(nruns)}
        stable_sets = 0
        uniq_set_counts = []
        for pid in runs[0]:
            sets = []
            for ri in range(nruns):
                f = frozenset(
                    normalize_formula(r.get("formula", ""))
                    for r in runs[ri].get(pid, [])
                    if isinstance(r, dict) and r.get("formula")
                )
                sets.append(f)
            if not any(sets):
                continue
            unique = set(sets)
            uniq_set_counts.append(len(unique))
            if len(unique) == 1:
                stable_sets += 1
        n = len(uniq_set_counts)
        pct = 100.0 * stable_sets / n if n else 0
        mu = statistics.mean(uniq_set_counts) if uniq_set_counts else 0
        print(f"{label:<22} {stable_sets:>3}/{n} ({pct:>5.1f}%)  {mu:.2f} / {nruns}")

    # =====================================================================
    print()
    hr()
    print("§6. GEO NER stability across N runs")
    hr()
    print(f"{'Model':<22} {'N runs':<8} {'country same %':<18} {'city same %':<14}")
    print("-" * 82)
    for label, m, nruns in MODELS:
        if nruns < 2:
            continue
        runs = {ri: load_geo(conn, m, ri) for ri in range(nruns)}
        c_same = 0; ci_same = 0; total = 0
        for pid in runs[0]:
            country_sets = []; city_sets = []
            ok = True
            for ri in range(nruns):
                g = runs[ri].get(pid)
                if not g:
                    ok = False; break
                country_sets.append(tuple(sorted(g.get("countries", []))))
                city_sets.append(tuple(sorted(g.get("cities", []))))
            if not ok:
                continue
            total += 1
            if len(set(country_sets)) == 1: c_same += 1
            if len(set(city_sets))    == 1: ci_same += 1
        if total:
            print(f"{label:<22} {nruns:<8} {c_same:>3}/{total} ({100*c_same/total:>5.1f}%)   "
                  f"{ci_same:>3}/{total} ({100*ci_same/total:>5.1f}%)")

    # =====================================================================
    print()
    hr()
    print("§7. INTER-MODEL Tc agreement at r0")
    print("   For (paper × shared formula) pairs where both models report tc_kelvin,")
    print("   how often is |Δtc| < 2K?")
    hr()
    def get_tcs(mats):
        out = {}
        for pid, records in mats.items():
            tcmap = {}
            for r in records:
                if not isinstance(r, dict): continue
                f = normalize_formula(r.get("formula", ""))
                tc = r.get("tc_kelvin")
                if f and isinstance(tc, (int, float)):
                    tcmap.setdefault(f, []).append(float(tc))
            if tcmap:
                out[pid] = tcmap
        return out

    tc_data = {m: get_tcs(r0_mat[m]) for _, m, _ in MODELS}
    print(f"{'Pair':<40} {'shared keys':<14} {'close (<2K)':<14} {'agree %':<10}")
    print("-" * 82)
    for (li, mi, _), (lj, mj, _) in combinations(MODELS, 2):
        a = tc_data[mi]; b = tc_data[mj]
        n_shared = 0; n_close = 0
        for pid in a:
            if pid not in b: continue
            for f, tcs_a in a[pid].items():
                if f in b[pid]:
                    n_shared += 1
                    if min(abs(ta - tb) for ta in tcs_a for tb in b[pid][f]) < 2.0:
                        n_close += 1
        pair = f"{li} ↔ {lj}"
        rate = 100.0 * n_close / n_shared if n_shared else 0
        print(f"{pair:<40} {n_shared:<14} {n_close:<14} {rate:>5.1f}%")

    # =====================================================================
    print()
    hr()
    print("§8. EVIDENCE_TYPE distribution at r0")
    print("   How does each model classify its extractions as primary vs cited?")
    hr()
    print(f"{'Model':<22} {'primary_exp':<14} {'primary_theo':<14} {'cited':<10} {'other':<8}")
    print("-" * 82)
    for label, m, _ in MODELS:
        counter = Counter()
        for records in r0_mat[m].values():
            for r in records:
                if isinstance(r, dict):
                    ev = (r.get("evidence_type") or "").lower()
                    if ev in ("primary_experimental", "primary_theoretical", "cited"):
                        counter[ev] += 1
                    elif ev == "primary":  # legacy
                        counter["primary_experimental"] += 1
                    else:
                        counter["other"] += 1
        total = sum(counter.values())
        if total:
            print(f"{label:<22} "
                  f"{counter['primary_experimental']:>4} ({100*counter['primary_experimental']/total:>4.1f}%)  "
                  f"{counter['primary_theoretical']:>4} ({100*counter['primary_theoretical']/total:>4.1f}%)  "
                  f"{counter['cited']:>4} ({100*counter['cited']/total:>4.1f}%)  "
                  f"{counter['other']:>4}")

    # =====================================================================
    print()
    hr()
    print("§9. FAMILY distribution at r0")
    hr()
    fam_per_model = {}
    for label, m, _ in MODELS:
        counter = Counter()
        for records in r0_mat[m].values():
            for r in records:
                if isinstance(r, dict):
                    fam = (r.get("family") or "").lower().replace("-", "_").replace(" ", "_")
                    if fam:
                        counter[fam] += 1
        fam_per_model[label] = counter

    # Build union of top 10 families
    all_fams = Counter()
    for c in fam_per_model.values():
        all_fams.update(c)
    top_fams = [f for f, _ in all_fams.most_common(10)]

    print(f"{'Family':<18}", end="")
    for label, _, _ in MODELS:
        print(f"{label:<18}", end="")
    print()
    for fam in top_fams:
        print(f"{fam:<18}", end="")
        for label, _, _ in MODELS:
            n = fam_per_model[label].get(fam, 0)
            print(f"{n:<18}", end="")
        print()

    # =====================================================================
    print()
    hr()
    print("§10. KRIPPENDORFF-α style: jaccard agreement on formula sets at r0")
    print("    avg over papers of |A ∩ B| / |A ∪ B|, when at least one model non-empty")
    hr()
    print(f"{'Pair':<40} {'n papers':<12} {'mean jaccard':<14}")
    print("-" * 82)
    for (li, mi, _), (lj, mj, _) in combinations(MODELS, 2):
        jacc = []
        for pid in r0_mat[mi]:
            if pid not in r0_mat[mj]: continue
            fi = {normalize_formula(r.get("formula", "")) for r in r0_mat[mi][pid] if isinstance(r, dict) and r.get("formula")}
            fj = {normalize_formula(r.get("formula", "")) for r in r0_mat[mj][pid] if isinstance(r, dict) and r.get("formula")}
            union = fi | fj
            if not union:
                continue
            jacc.append(len(fi & fj) / len(union))
        n = len(jacc)
        mean = statistics.mean(jacc) if jacc else 0
        print(f"{li} ↔ {lj}".ljust(40) + f"{n:<12} {mean:<14.3f}")

    # =====================================================================
    # 11. Within-paper, across-model: how many models "agree" that a SC material exists?
    print()
    hr()
    print("§11. HARD vs EASY papers — by inter-model unanimity at r0")
    hr()
    easy = 0       # all 4 non-empty AND all share at least one formula
    consensus = 0  # all 4 non-empty
    mostly_empty = 0  # ≥ 3 of 4 empty
    contentious = 0  # mixed: some empty, some not
    all_empty = 0
    for pid in r0_mat[MODELS[0][1]]:
        states = []
        formula_sets = []
        for _, m, _ in MODELS:
            recs = r0_mat[m].get(pid, [])
            f = {normalize_formula(r.get("formula", "")) for r in recs if isinstance(r, dict) and r.get("formula")}
            formula_sets.append(f)
            states.append(1 if f else 0)
        n_nonempty = sum(states)
        if n_nonempty == 0:
            all_empty += 1
        elif n_nonempty == 4:
            consensus += 1
            inter = set.intersection(*formula_sets)
            if inter:
                easy += 1
        elif n_nonempty <= 1:
            mostly_empty += 1
        else:
            contentious += 1
    print(f"  EASY (all 4 models non-empty AND ≥1 shared formula): {easy}/100")
    print(f"  4 models non-empty (but no full overlap):            {consensus - easy}/100")
    print(f"  Contentious (2–3 of 4 non-empty, others empty):      {contentious}/100")
    print(f"  Mostly empty (3+ models empty):                      {mostly_empty}/100")
    print(f"  All 4 empty:                                         {all_empty}/100")
    print()
    print(f"  → \"Hard\" papers (contentious + mostly empty + all empty): "
          f"{contentious + mostly_empty + all_empty}/100")

    conn.close()


if __name__ == "__main__":
    main()
