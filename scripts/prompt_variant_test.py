#!/usr/bin/env python3
"""A.1 — Prompt-variant exploratory test.

Goal: run a single alternative prompt (variant_B, "primary-only stricter")
on the configured Gemini Flash model for 30 cached_inputs papers and report formula-set
Jaccard between prompt_A (original production prompt) and prompt_B.

Reuses cached_inputs/ which were created during the original audit.
Outputs go to audit/refresh_2026_05_26/prompt_variant_test/.

The variant differs from prompt_A in two specific ways:
1. Re-orders fields so that evidence_type is asked FIRST (priming)
2. Explicit instruction: "ONLY emit records for materials whose Tc is
   MEASURED OR COMPUTED in THIS paper. SKIP all cited / introduction-survey
   / reference-table mentions entirely."
This is a stricter primary-only variant; we hypothesize the Jaccard
with prompt_A's Gemini output will be moderate (~0.5-0.7).
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "ingestion"))
CACHED = REPO / "audit" / "cached_inputs"
DB = REPO / "audit" / "audit_review.db"
OUT_DIR = REPO / "audit" / "refresh_2026_05_26" / "prompt_variant_test"
OUT_DIR.mkdir(parents=True, exist_ok=True)


VARIANT_B_PROMPT = """\
You are extracting superconductor data from an arXiv paper. Return a JSON
array of objects.

CRITICAL EVIDENCE-TYPE RULE (top priority):
- Emit a record ONLY IF the Tc value is MEASURED or CALCULATED in THIS paper
  for the specific material listed.
- SKIP entirely: cited literature values (e.g. "LaH10 has Tc=260 K [Drozdov 2019]"),
  introduction surveys, comparison tables of prior-work Tc values, references
  to "previously reported" findings.
- If unsure whether the Tc was measured in this paper or merely cited, SKIP.

After applying the evidence-type filter, for each retained record emit:
- formula: chemical formula in PLAIN TEXT only (strip LaTeX). Unicode subscripts allowed.
- tc_kelvin: critical temperature in Kelvin (null if unknown)
- pressure_gpa: numeric value in GPa (null unless paper explicitly states pressure)
- measurement: one of resistivity / susceptibility / specific_heat / muSR / ARPES / STM / neutron / unknown
- family: one of cuprate / iron_based / nickelate / hydride / mgb2 / heavy_fermion / fulleride / kagome / organic / bismuthate / borocarbide / ruthenate / chalcogenide / elemental / conventional
- evidence_type: MUST be primary_experimental or primary_theoretical (anything cited has been skipped)
- confidence: 0.0-1.0

Return [] if no in-paper-measured material is found.

Output ONLY the JSON array. No prose, no markdown fences.

PAPER BODY:
{{BODY}}
"""

_MAX_CHARS = 16_000


def load_existing_promptA(paper_id: str) -> list[dict]:
    """Load the Gemini run_idx=0 material extraction for prompt_A."""
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT materials_json FROM audit_extraction_model "
        "WHERE paper_id=? AND vendor='google' AND model_name='gemini-2.5-flash' "
        "AND run_idx=0 AND prompt_version='material_ner_v2_core'",
        (paper_id,),
    ).fetchone()
    if not row or not row[0]:
        return []
    try:
        parsed = json.loads(row[0])
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def normalize_formula(s: str) -> str:
    if not s:
        return ""
    return "".join(s.strip().split()).lower()


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def run_variant_b_on_paper(paper_id: str, body: str, sys_module) -> list[dict]:
    """Invoke the configured Gemini Flash model with variant_B prompt."""
    prompt = VARIANT_B_PROMPT.replace("{{BODY}}", body[:_MAX_CHARS])
    client = sys_module["client"]
    types = sys_module["types"]
    try:
        resp = client.models.generate_content(
            model=sys_module["model"],
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=32768,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        text = resp.text or "[]"
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            return []
        return parsed
    except Exception as e:
        print(f"  Gemini API error: {e}", file=sys.stderr)
        return []


def main() -> int:
    # Read all cached_inputs paper IDs
    cache_files = sorted(CACHED.glob("*.json"))
    if not cache_files:
        print(f"No cached inputs found in {CACHED}", file=sys.stderr)
        return 1
    print(f"Found {len(cache_files)} cached input papers")

    # Sample 30 papers (deterministically: first 30 alphabetically)
    sample = cache_files[:30]
    print(f"Using first 30 alphabetically for prompt-variant test")

    # Initialize Gemini client from the same config used by ingestion.
    try:
        from google.genai import types
        from ingestion.config import get_settings
        from ingestion.genai_client import make_genai_client

        settings = get_settings()
        client = make_genai_client(settings)
        sys_module = {"client": client, "types": types, "model": settings.gemini_model}
    except ImportError:
        print("Cannot import google.genai. Install: pip install google-genai", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Failed to init Gemini client: {e}", file=sys.stderr)
        return 1

    results = []
    for i, cf in enumerate(sample, 1):
        paper_id = f"arxiv:{cf.stem}"
        # cond-mat style IDs need "arxiv:cond-mat/" prefix
        if "/" not in paper_id and not paper_id.split(":", 1)[1][0].isdigit():
            paper_id = f"arxiv:cond-mat/{cf.stem}"
        try:
            cached = json.loads(cf.read_text())
        except Exception:
            continue
        # Match by arxiv_id field rather than guessing
        actual_pid = cached.get("paper_id", paper_id)
        body = cached.get("body_for_material_ner", "")
        if not body:
            print(f"  [{i:2d}/30] {actual_pid}: no body, skip")
            continue

        existing_A = load_existing_promptA(actual_pid)
        formulas_A = {normalize_formula(r.get("formula", "")) for r in existing_A}
        formulas_A.discard("")

        new_B = run_variant_b_on_paper(actual_pid, body, sys_module)
        formulas_B = {normalize_formula(r.get("formula", "")) for r in new_B}
        formulas_B.discard("")

        j = jaccard(formulas_A, formulas_B)
        results.append({
            "paper_id": actual_pid,
            "n_A": len(formulas_A),
            "n_B": len(formulas_B),
            "overlap": len(formulas_A & formulas_B),
            "jaccard": j,
            "formulas_A": sorted(formulas_A),
            "formulas_B": sorted(formulas_B),
        })
        print(f"  [{i:2d}/30] {actual_pid}: |A|={len(formulas_A):2d} |B|={len(formulas_B):2d} ∩={len(formulas_A & formulas_B):2d} J={j:.2f}")

        # Persist after each call so partial failures don't lose data
        (OUT_DIR / "raw_results.jsonl").write_text(
            "\n".join(json.dumps(r) for r in results)
        )

        time.sleep(0.5)

    # Summary
    n = len(results)
    if n == 0:
        print("No results.")
        return 1

    js = [r["jaccard"] for r in results]
    mean_j = sum(js) / n
    median_j = sorted(js)[n // 2]
    perfect = sum(1 for j in js if j == 1.0)
    zero = sum(1 for j in js if j == 0.0)

    print(f"\n=== Summary (n={n} papers) ===")
    print(f"Mean Jaccard:      {mean_j:.3f}")
    print(f"Median Jaccard:    {median_j:.3f}")
    print(f"Perfect agreement: {perfect}/{n}")
    print(f"Zero agreement:    {zero}/{n}")
    print(f"Mean |A|:          {sum(r['n_A'] for r in results) / n:.1f}")
    print(f"Mean |B|:          {sum(r['n_B'] for r in results) / n:.1f}")

    # CSV summary
    with (OUT_DIR / "prompt_variant_summary.csv").open("w") as f:
        f.write("paper_id,n_A,n_B,overlap,jaccard\n")
        for r in results:
            f.write(f"{r['paper_id']},{r['n_A']},{r['n_B']},{r['overlap']},{r['jaccard']:.4f}\n")

    print(f"\nWrote {OUT_DIR/'prompt_variant_summary.csv'} and raw_results.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
