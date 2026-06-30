# APS Manifest Audit Summary

Date: 2026-06-29

## Confirmed Local Inputs

Authorized-window manifest:

- Directory: `audit/aps_manifest_20260616T065908Z_authorized_19860101_20261231/`
- DOI list rows: 28,577
- JSONL rows: 28,577
- CSV rows: 28,578 including header
- Publication window: 1986-01-01 to 2026-12-31
- Removed outside window: 3,204, all before 1986-01-01
- Removed after 2026-12-31 or unknown date: 0

Original discovery manifest:

- Generated UTC: 2026-06-16T07:07:44+00:00
- Source: Crossref public metadata, APS DOI prefix `10.1103`,
  `type:journal-article`
- Query set: core superconductivity/device/material terms
- Candidate DOI records before 1986-window filtering: 31,781
- Database coverage in that run: not available

## Authorized-Window Distribution

By period:

| Period | DOI records |
|---|---:|
| 1986--1990 | 2,044 |
| 1991--1995 | 2,697 |
| 1996--2000 | 2,824 |
| 2001--2005 | 3,461 |
| 2006--2010 | 4,001 |
| 2011--2015 | 3,873 |
| 2016--2020 | 4,200 |
| 2021--2025 | 4,879 |
| 2026 partial/future-window rows | 598 |

Top journals:

| Journal | DOI records |
|---|---:|
| PRB | 19,784 |
| PRL | 5,251 |
| PRA | 619 |
| Physical Review Applied | 592 |
| Physical Review Research | 566 |
| PRD | 473 |
| Physical Review Materials | 320 |
| PRAB | 239 |
| PRX | 235 |
| PRE | 137 |
| Physics | 129 |
| PRX Quantum | 88 |
| RMP | 72 |
| PRC | 46 |
| unknown | 21 |

Priority classes:

| Priority | DOI records |
|---|---:|
| P0 | 20,920 |
| P1 | 6,607 |
| P2 | 1,050 |

Candidate classes:

| Candidate class | DOI records |
|---|---:|
| general_superconductivity | 17,461 |
| devices_or_theory | 5,840 |
| materials_tc_likely | 4,863 |
| keyword_candidate | 413 |

Matched-term highlights:

| Term | DOI records |
|---|---:|
| superconduct | 24,280 |
| josephson | 3,497 |
| tc | 1,942 |
| vortex | 1,811 |
| topological | 1,769 |
| cuprate | 1,440 |
| andreev | 853 |
| pairing | 844 |
| pnictide | 597 |
| cooper_pair | 518 |
| heavy_fermion | 293 |
| organic | 285 |
| charge_density_wave | 255 |
| mgb2 | 207 |
| nickelate | 197 |
| hydride | 85 |

## Ingestion-State Evidence From Documentation

`docs/APS_OPENCLAW_FULLTEXT_INGEST_RUNBOOK.md` states that, as of
2026-06-16:

- APS Harvest whitelist and VPS2 main path were working.
- Production metadata and full-text ZIP retrieval were validated.
- DOI manifest plus checkpoint/resume batch runner were available.
- A modern-window 500-paper calibration had completed:
  - 499 ok
  - 1 error
  - invalid DOI: `10.1103/466c-8sl4` returned Harvest 404
- One APS aggregation had completed in production, confirming the
  NER -> papers -> aggregate-materials loop.

Local audit directory `audit/aps_manifest_20260616T065908Z/` contains:

- `production_existing_aps_dois.txt`: 101 DOI rows
- several 500-row calibration/pending DOI lists

## Important Caveats

The authorized-window manifest is a discovery/candidate universe, not a
final freeze of successfully ingested APS papers.

The APS study must distinguish:

1. Candidate DOI universe: Crossref-derived, authorized date window.
2. Harvest-ready DOI universe: candidate universe after excluding known
   non-Harvest or unstable classes such as `Physics`, `PhysRevFocus`, and
   rows missing required bibliographic locators.
3. Successfully ingested APS papers: `papers.source='aps'` with `T1`,
   allowed `chunks.section` values only, and a successful TDM audit row.
4. APS-only strict material record view: joined from `v_tc_geo` and
   `papers`, filtered to `source='aps'`, active status, and valid
   `tc_kelvin`.

This local machine cannot query the production database because `docker`
is not available here. The final freeze must be confirmed on VPS2.
