# arXiv 2026 Gap Audit and Backfill Plan

Date: 2026-07-24  
Production baseline: site `3a3783f`, dataset `v2026.07.24`
Completion: deployed and verified on production at site `8c229b8`

## Scope and method

The audit queried arXiv OAI-PMH for every `physics:cond-mat` record updated
between 2026-01-01 and 2026-07-24, then compared stable arXiv identifiers
against the production `papers` table.

Two scopes were kept separate:

1. **Canonical SCLib scope:** `cond-mat.supr-con` is the primary category.
2. **Extended candidates:** `cond-mat.supr-con` is only a secondary category.

This distinction follows the existing collector and avoids silently changing
the corpus definition during a data repair.

## Audit result

| Scope | arXiv records seen | Missing from production | `26xx` IDs |
|---|---:|---:|---:|
| Primary `cond-mat.supr-con` | 1,408 updated records | 18 | 1 |
| Any-category `cond-mat.supr-con` | 2,087 updated records | 211 | 171 |
| Secondary-category candidates only | 679 additional records | 193 | 170 |

The production failure pool contained zero pending or dead papers. The 18
canonical gaps are therefore harvest-window gaps, not failed NER retries.

## Canonical backfill batches

Every batch runs the complete pipeline: metadata, source/PDF archive, parsing,
chunking, embedding, material NER, PostgreSQL upsert, and Vertex Vector Search
upsert. Batches are deliberately small so failures remain attributable and
retries do not repeat successful papers.

### Batch A — material-bearing and new 2026 priority

| arXiv ID | Title |
|---|---|
| `2602.22793` | Hourglass Dirac chains enable intrinsic topological superconductivity in nonsymmorphic silicides |
| `2505.00514` | Signatures of three-dimensional photo-induced superconductivity in YBa₂Cu₃O₆.₄₈ |
| `2502.14324` | Impact of Pressure and Apical Oxygen Vacancies on Superconductivity in La₃Ni₂O₇ |
| `2311.13674` | Electron-phonon mediated superconductivity in La₆Ni₅O₁₂ nickel oxides |
| `2502.01501` | Damage of bilayer structure in La₃Ni₂O₇₋δ induced by high pO₂ annealing |
| `2504.16412` | Superconductivity and Electron Correlations in Kagome Metal LuOs₃B₂ |

### Batch B — superconducting states and mechanisms

| arXiv ID | Title |
|---|---|
| `2504.16166` | Two-dimensional flat band on the (011) surface of UTe₂ |
| `2501.14254` | Fermi-surface geometry and optical response of Sr₂RuO₄ |
| `2505.01759` | Ferroelectrically Switchable Chirality in Topological Superconductivity |
| `2507.20549` | Finite-momentum mixed singlet-triplet pairing in chiral antiferromagnets |
| `2508.00460` | Hybrid magnon–Nambu-Goldstone excitations in topological-superconductor heterostructures |
| `2506.06140` | Cavity control of the Ginzburg–Landau stiffness in superconductors |

### Batch C — Josephson devices, electrodynamics, and review

| arXiv ID | Title |
|---|---|
| `2305.14643` | On-chip superconducting Josephson plasma emitters |
| `2504.17779` | Josephson anomalous vortices |
| `2510.17805` | The Meissner effect in superconductors |
| `2504.04468` | Planar Josephson junctions with narrow superconducting strips |
| `2504.02948` | Perfect supercurrent diode efficiency in chiral nanotube weak links |
| `2505.03913` | Large-critical-current Josephson π junctions with PdNi barriers |

## Post-ingest sequence

1. Drain the retry pool if any batch has recoverable failures.
2. Run `aggregate-materials` once after all three batches.
3. Refresh dashboard stats and rebuild the timeline projection.
4. Verify paper/chunk/NER counts for all 18 identifiers.
5. Verify API health, dataset version, statistics, Materials, Search, and
   Timeline pages.
6. Take and verify the normal PostgreSQL backup.

## Production completion

The canonical backfill completed on 2026-07-24:

| Batch | Result |
|---|---|
| A | 6/6 full-pipeline successes |
| B | 5/6 full-pipeline successes; `2508.00460` retained as withdrawn metadata |
| C | 6/6 full-pipeline successes |

arXiv withdrew `2508.00460` in v5 and removed its downloadable source/PDF.
Its database row is marked `retracted`, records the withdrawal date and reason,
and points to replacement `2508.00499`; it was deliberately excluded from
embedding, NER, and material aggregation.

Final production verification:

- 18/18 canonical identifiers are present.
- 17 papers completed full-text parsing, embedding, NER, PostgreSQL, and Vector
  Search ingestion.
- The batch added 440 chunks and 29 paper-level material NER records.
- The canonical primary-category difference is zero and the failure pool is
  empty.
- Material aggregation upserted 9,343 canonical formulas and linked 289
  variants to 6 parents.
- Timeline projection is ready with 29,645 active points across 9,698
  materials.
- Public statistics are 75,037 papers, 11,432 materials, and 1,113,929 chunks;
  the arXiv 2026 histogram contains 1,246 papers.
- The production paper, material, statistics, and timeline pages were verified.
- PostgreSQL backup `sclib-20260724T105325Z.dump` and its manifest were uploaded
  and size-verified.

## Extended-candidate disposition

The 193 secondary-category gaps are retained as a separate relevance-review
backlog. They include superconducting qubits, detectors, accelerators, cold
atoms, nuclear matter, and papers where superconductivity is contextual rather
than the primary subject. They should be title/abstract screened before any
corpus-policy expansion; they are not part of this canonical repair batch.
