# SCLib_JZIS — Data Provenance & Upstream Licenses

SCLib_JZIS aggregates and re-publishes data from several upstream
providers. **Each upstream keeps its original license** — the
project-level `LICENSE-DATA` (CC BY 4.0) covers only the *new* data
SCLib produces (the curated `materials` table, our Tc-record
aggregations, family classifications, and statistics derived from
all sources combined).

If you redistribute SCLib data, you must respect both:
1. The CC BY 4.0 attribution to SCLib_JZIS, and
2. The upstream license of any record that originated externally.

The `data_provenance` field in API responses (`/materials/{formula}`,
records inside `materials.records`) marks every Tc record with one of
the source codes below so downstream consumers can route attribution
correctly.

---

## Source: arXiv

| Field | Value |
|---|---|
| Source code | `arxiv` |
| What we ingest | Paper metadata + abstracts via OAI-PMH (set `cond-mat.supr-con`); LaTeX source for parsing chunks |
| Coverage | 1986 → present, daily incremental |
| License | arXiv abstracts are licensed under [arXiv non-exclusive distribution](https://arxiv.org/help/license/), individual papers are under the license each author selected (often arXiv perpetual or CC variants). |
| Our redistribution | We **do not redistribute the original PDFs**. We redistribute extracted snippets ("chunks") of paper text under fair-use research scope, citing the arXiv ID. |
| Required attribution | Cite the arXiv ID of the originating paper. SCLib API responses include `paper_id` for every match. |

## Source: NIMS SuperCon (v22.12.03)

| Field | Value |
|---|---|
| Source code | `nims` |
| What we ingest | 40,325 superconductor records (formula, Tc, pressure, family) from the NIMS SuperCon CSV release |
| Coverage | Historical — frozen at v22.12.03 |
| License | NIMS SuperCon is provided under **academic / non-commercial** terms. **Redistribution requires NIMS attribution and is restricted to research use.** See https://supercon.nims.go.jp/en/ for the original terms. |
| Our redistribution | We surface NIMS-derived rows in our materials database with an explicit `source: "nims"` tag. **Commercial use of NIMS-tagged records requires a separate agreement with NIMS** — SCLib's CC BY 4.0 license does *not* override NIMS's restrictions on those rows. |
| Required attribution | "Data partially derived from NIMS SuperCon, National Institute for Materials Science, Japan." |

## Source: Materials Project (Phase B+ integration)

| Field | Value |
|---|---|
| Source code | `mp` |
| What we ingest | Material-id mappings, band gap, formation energy, phonon descriptors via the public MP API |
| Coverage | ~200,000 inorganic materials (DFT-computed) |
| License | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — same as SCLib's own data, so the combined output remains uniformly licensed. |
| Our redistribution | When we cache MP-derived properties in our DB, we keep the `mp_id` so attribution is unambiguous. The `/version` endpoint reports the MP `database_version` we last synced against. |
| Required attribution | Cite Materials Project alongside SCLib when redistributing combined records. Suggested: "Combined with Materials Project (https://next-gen.materialsproject.org, CC BY 4.0)." |

---

## Source codes summary

Use these strings to filter or attribute records. The `source` field
appears on every record inside `materials.records` and on every
material's `data_provenance` summary.

| Code | Meaning | Default attribution required |
|---|---|---|
| `arxiv_ner` | Tc value extracted by Gemini NER from an arXiv paper | Cite paper's arXiv ID |
| `nims` | Tc value imported from NIMS SuperCon CSV | NIMS, plus academic-use restriction |
| `mp` | Property derived from Materials Project DFT | Materials Project + CC BY 4.0 |
| `manual` | Curator-edited or user-corrected value | SCLib_JZIS (CC BY 4.0) |

## Combined dataset

When SCLib publishes a record that mixes sources (e.g. a material
whose `tc_max` was reported in an arXiv paper but whose formula was
canonicalised against NIMS SuperCon), the most-restrictive upstream
license governs that record. In practice this means: **any material
whose `data_provenance` includes `nims` is covered by NIMS's
non-commercial term**, regardless of SCLib's CC BY 4.0.

The `data_provenance` field is therefore not just metadata — it is
the legal mechanism by which downstream users determine which terms
apply to each row.
