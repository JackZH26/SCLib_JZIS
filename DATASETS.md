# SCLib Published Datasets

This repository's frozen corpus snapshots are deposited on Zenodo.

## v1.0 — Freeze 2026-05-28

| | |
|---|---|
| **Version DOI** | [10.5281/zenodo.20428169](https://doi.org/10.5281/zenodo.20428169) |
| **Concept DOI** (always latest) | [10.5281/zenodo.20428168](https://doi.org/10.5281/zenodo.20428168) |
| **Record URL** | https://zenodo.org/record/20428169 |
| **License** | CC-BY-4.0 (data) + MIT (code) |
| **Deposit size** | 73 MB (tarball), 87 MB (uncompressed) |
| **DB schema version** | 0037_paper_geo |

### Headline numbers

- 43,183 active papers (1991–2026, 17 retracted excluded)
- 19,028 strict-filter Tc records (`tc_kelvin ∈ (0, 300] AND status != 'retracted'`)
- 5,880 distinct superconducting materials
- 7,768 distinct papers with at least one Tc record
- 99.99% per-paper author-country geographic coverage

### How to cite

> Zhou, Jian (2026). *SCLib: Reproducible LLM-Extracted arXiv cond-mat.supr-con
> Bibliometric Dataset (Freeze 2026-05-28)* [Data set]. Zenodo.
> https://doi.org/10.5281/zenodo.20428169

For analyses that should auto-update to the latest freeze, cite the concept
DOI instead: https://doi.org/10.5281/zenodo.20428168

### How this freeze was produced

The full workflow is reproducible from this repository:

```bash
# 1. Capture freeze timestamp, pause aggregate timer, run all corpus stats
bash scripts/refresh_corpus_stats.sh 2026-05-28

# 2. Re-run statistical analyses against the new snapshot
python3 scripts/powerlaw_fit.py
python3 scripts/valley_statistics.py
python3 scripts/timeline_plot.py

# 3. Generate diff vs the prior freeze
python3 scripts/compare_snapshots.py \
    --old audit/refresh_2026_05_26 \
    --new audit/refresh_2026_05_28 \
    --out audit/refresh_2026_05_28/SNAPSHOT_DIFF.md

# 4. Upload to Zenodo (token from env var)
ZENODO_TOKEN=... python3 scripts/zenodo_upload.py
```

The full deposit tree (built at `zenodo_v1/` before upload) is intentionally
gitignored — it weighs ~87 MB and the public version on Zenodo is the canonical
copy.
