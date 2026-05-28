#!/usr/bin/env python3
"""Upload SCLib data freeze to Zenodo as a draft deposition.

Reads the Zenodo API token from the ZENODO_TOKEN environment variable
(NEVER hard-codes a token). Creates a draft (NOT published) — user must
click "Publish" from the Zenodo web UI after reviewing.

Usage:
    export ZENODO_TOKEN='...'
    python3 scripts/zenodo_upload.py

Files uploaded:
    - SCLib_data_freeze_2026_05_28.tar.gz  (main deposit, 73 MB)
    - zenodo_v1/README.md
    - zenodo_v1/DATA_DICTIONARY.md
    - zenodo_v1/REPRODUCE.md
    - zenodo_v1/CHANGELOG.md
    - zenodo_v1/CITATION.cff
    - zenodo_v1/CHECKSUMS.sha256
    - zenodo_v1/LICENSE-data.txt
    - zenodo_v1/LICENSE-code.txt
"""
from __future__ import annotations

import os
import sys
import json
import time
from pathlib import Path

import requests


ZENODO_BASE = "https://zenodo.org/api"
REPO = Path(__file__).resolve().parent.parent
TARBALL = REPO / "SCLib_data_freeze_2026_05_28.tar.gz"
DEPOSIT_ROOT = REPO / "zenodo_v1"

FILES_TO_UPLOAD = [
    TARBALL,                                  # main asset
    DEPOSIT_ROOT / "README.md",
    DEPOSIT_ROOT / "DATA_DICTIONARY.md",
    DEPOSIT_ROOT / "REPRODUCE.md",
    DEPOSIT_ROOT / "CHANGELOG.md",
    DEPOSIT_ROOT / "CITATION.cff",
    DEPOSIT_ROOT / "CHECKSUMS.sha256",
    DEPOSIT_ROOT / "LICENSE-data.txt",
    DEPOSIT_ROOT / "LICENSE-code.txt",
]


DESCRIPTION_HTML = """
<p><strong>SCLib</strong> is a corpus-level bibliometric dataset extracted from the full
arXiv <code>cond-mat.supr-con</code> primary-submission record (1991–2026), with
LLM-based named-entity recognition for <strong>superconducting materials</strong>,
<strong>critical temperatures (T<sub>c</sub>)</strong>, <strong>pressure regimes</strong>,
<strong>evidence types</strong>, and <strong>author geography</strong>.</p>

<p>This deposit is a <strong>standalone data resource</strong>: it contains the frozen
relational database, all derived analysis outputs, the multi-model NER audit
corpus, the production NER prompts (SHA-256 pinned), and all reproducibility
code. Publications that use this dataset will appear under "Related identifiers"
as they are released.</p>

<h3>Headline numbers (freeze 2026-05-28)</h3>
<ul>
  <li><strong>43,183</strong> active papers (1991–2026); 17 retracted (excluded)</li>
  <li><strong>19,028</strong> distinct T<sub>c</sub> records (strict filter)</li>
  <li><strong>5,880</strong> distinct superconducting materials</li>
  <li><strong>7,768</strong> distinct papers with at least one T<sub>c</sub> record</li>
  <li><strong>99.99%</strong> per-paper author-country geographic NER coverage</li>
  <li><strong>3,200</strong> LLM extraction calls in the multi-model audit
      (Claude Opus 4.7, GPT-5.5, GPT-5.4-mini, Gemini 2.5 Flash)
      with Krippendorff α / Cohen κ / Fleiss κ inter-rater reliability</li>
</ul>

<h3>What's included</h3>
<ul>
  <li><code>data/</code> — Frozen PostgreSQL dump (data-only, column-inserts)
      plus 10 per-table / per-view CSV exports (papers, materials,
      v_tc_geo_strict, paper_geo, audit_reports, manual_overrides, …)</li>
  <li><code>audit/</code> — Multi-model NER audit SQLite DB, 100-paper cached
      inputs, full LLM stdout/stderr logs (compressed), and 49 analytical
      output CSVs (q*.csv + IRR + power-law + valley statistics)</li>
  <li><code>schema/</code> — 37 Alembic database migrations (0001 → 0037_paper_geo)</li>
  <li><code>scripts/</code> — ~40 reproducibility scripts (refresh_corpus_stats,
      compute_reliability, powerlaw_fit, valley_statistics, timeline_plot, ...)</li>
  <li><code>prompts/</code> — SHA-256 pinned production NER prompts
      (material_ner_v2_core, author_geo_ner_text, author_geo_ner_pdf,
      and a PROMPT_MANIFEST.json with provenance)</li>
</ul>

<h3>What's intentionally NOT included</h3>
<ul>
  <li>arXiv full text (<code>chunks</code> table, 1.8 GB) — recoverable via
      arXiv OAI-PMH using the recipe in <code>REPRODUCE.md</code></li>
  <li>User accounts (<code>users</code>, <code>api_keys</code>) and user
      activity (<code>ask_history</code>, <code>bookmarks</code>) — privacy</li>
  <li>Manuscripts / paper PDFs — this is a pure data deposit; publications
      using this dataset will be listed under "Related identifiers"</li>
</ul>

<h3>Licensing</h3>
<ul>
  <li><strong>Data</strong> (everything under <code>data/</code>, <code>audit/</code>,
      <code>schema/</code>) — <strong>CC-BY-4.0</strong></li>
  <li><strong>Code</strong> (everything under <code>scripts/</code>,
      <code>prompts/</code>) — <strong>MIT</strong></li>
</ul>

<h3>Reproducibility</h3>
<p>See <code>REPRODUCE.md</code> for three reproduction levels:</p>
<ol>
  <li>Load frozen DB and reproduce analyses (5–30 min)</li>
  <li>Re-run NER on the same 100-paper audit set (~1 hr, ~$5–20 LLM cost)</li>
  <li>Rebuild the entire corpus from arXiv (~3 days, ~$200–500 LLM cost)</li>
</ol>

<h3>Strict filter convention</h3>
<p>All bibliometric analyses use the canonical strict filter:
<code>tc_kelvin ∈ (0, 300] AND papers.status != 'retracted'</code>.
This filter is the source-of-record for the 19,028 record count.</p>
"""


METADATA = {
    "upload_type": "dataset",
    "publication_date": "2026-05-28",
    "title": (
        "SCLib: Reproducible LLM-Extracted arXiv cond-mat.supr-con "
        "Bibliometric Dataset (Freeze 2026-05-28)"
    ),
    "creators": [
        {
            "name": "Zhou, Jian",
            "affiliation": "JZ Institute of Science, Hong Kong",
        }
    ],
    "description": DESCRIPTION_HTML.strip(),
    "access_right": "open",
    "license": "cc-by-4.0",
    "keywords": [
        "scientometrics",
        "superconductivity",
        "arXiv",
        "LLM extraction",
        "named entity recognition",
        "NER",
        "critical temperature",
        "Tc",
        "bibliometrics",
        "cond-mat.supr-con",
        "materials science",
        "inter-rater reliability",
        "Krippendorff alpha",
    ],
    "version": "1.0",
    "language": "eng",
    "related_identifiers": [
        {
            "identifier": "https://arxiv.org/list/cond-mat.supr-con/",
            "relation": "isDerivedFrom",
            "resource_type": "publication-preprint",
        }
    ],
    "notes": (
        "Code portion of this deposit (everything under scripts/ and prompts/) "
        "is released under the MIT License, separately from the CC-BY-4.0 data "
        "license. See LICENSE-data.txt and LICENSE-code.txt in the deposit "
        "for full license texts.\n\n"
        "This is the first public freeze (v1.0). Future versions will be "
        "released as new Zenodo versions under the same concept DOI."
    ),
}


def main() -> int:
    token = os.environ.get("ZENODO_TOKEN")
    if not token:
        print("ERROR: ZENODO_TOKEN env var not set", file=sys.stderr)
        return 1

    headers = {"Authorization": f"Bearer {token}"}

    # ---------- 1. Create empty draft deposition ----------
    print("[1/4] Creating draft deposition...")
    r = requests.post(
        f"{ZENODO_BASE}/deposit/depositions",
        headers={**headers, "Content-Type": "application/json"},
        json={},
    )
    if r.status_code != 201:
        print(f"  FAIL: HTTP {r.status_code}: {r.text[:500]}", file=sys.stderr)
        return 1
    deposit = r.json()
    deposit_id = deposit["id"]
    bucket_url = deposit["links"]["bucket"]
    print(f"  ✓ Created deposit #{deposit_id}")
    print(f"    Edit URL: {deposit['links']['html']}")

    # ---------- 2. Upload files via bucket API ----------
    print(f"\n[2/4] Uploading {len(FILES_TO_UPLOAD)} files...")
    for f in FILES_TO_UPLOAD:
        if not f.exists():
            print(f"  [skip] missing: {f}", file=sys.stderr)
            continue
        size_mb = f.stat().st_size / 1024 / 1024
        print(f"  -> {f.name}  ({size_mb:.2f} MB)...", end="", flush=True)
        t0 = time.time()
        with f.open("rb") as fp:
            r = requests.put(f"{bucket_url}/{f.name}", data=fp, headers=headers)
        dt = time.time() - t0
        if r.status_code in (200, 201):
            print(f" ok ({dt:.1f}s, {size_mb / max(dt, 0.1):.1f} MB/s)")
        else:
            print(f" FAIL HTTP {r.status_code}: {r.text[:200]}")
            return 1

    # ---------- 3. Set metadata ----------
    print("\n[3/4] Setting metadata...")
    r = requests.put(
        f"{ZENODO_BASE}/deposit/depositions/{deposit_id}",
        headers={**headers, "Content-Type": "application/json"},
        json={"metadata": METADATA},
    )
    if r.status_code != 200:
        print(f"  FAIL: HTTP {r.status_code}: {r.text[:800]}", file=sys.stderr)
        return 1
    print("  ✓ Metadata applied")

    # ---------- 4. Report ----------
    print("\n[4/4] Final state — DRAFT (NOT YET PUBLISHED):")
    print(f"  Deposit ID:    {deposit_id}")
    print(f"  Edit/Review:   {deposit['links']['html']}")
    print(f"  Files API:     {deposit['links']['files']}")
    print(f"  Reserved DOI:  10.5281/zenodo.{deposit_id} (activates on publish)")
    print()
    print("Next steps:")
    print(f"  1. Open {deposit['links']['html']} in browser")
    print("  2. Review the metadata and file list")
    print("  3. Click 'Publish' if everything looks good")
    print("     (Publishing is IRREVERSIBLE — DOI activates and record becomes public)")
    print()
    print("After publishing — REVOKE THE API TOKEN at:")
    print("  https://zenodo.org/account/settings/applications/tokens/")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
