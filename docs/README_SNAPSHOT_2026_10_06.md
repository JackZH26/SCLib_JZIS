# Homepage verification snapshot: 6 October 2026

This record supports the repository README refresh. It records public observations
and source-code scope; it does not certify scientific data quality, approve a
research release or record a new website deployment.

## Software and coverage

The GitHub default branch was `main`, whose application baseline was
`d080cd5be5b7ddd8f10b3bd008935684868331d5` (PR #145, Discovery candidate tabs).
No GitHub release objects were published when checked. The public version API
reported the matching short deployed commit. Consequently the README identifies
the commit, public API version and dataset date separately rather than calling
the entire service a new semantic-version release.

| Public observation | Value |
|---|---|
| `GET https://api.jzis.org/sclib/v1/version` | `site_version=d080cd5`, `api_version=1`, `dataset_version=v2026.09.03` |
| `GET https://api.jzis.org/sclib/v1/stats`: `total_papers` | 75,202 |
| Sum of `papers_by_year_arxiv` | 46,895 |
| Sum of `papers_by_year_aps` | 28,307 |
| `total_materials` | 11,463 |
| `total_chunks` | 1,117,982 |
| `last_ingest_at` | `2026-09-03T10:30:54.970754+00:00` |
| `stats_refreshed_at` | `2026-10-06T03:00:29.256970+00:00` |
| `data_pipeline.last_run_at` | `2026-09-03T10:32:13Z`; recorded status `complete` |
| `GET https://api.jzis.org/sclib/v1/materials?limit=1&offset=0`: `total` | 10,507 |
| Materials `sort_basis` / `scientific_display_policy` | `current_projected_catalogue` / `atomic_property_evidence` |
| GitHub `ingest-daily.yml` workflow state | `disabled_manually` |

The two paper-source sums equal the reported total. Material counts use different
scopes: the statistics cache reports stored entries, while the current Materials
reader applies default visibility/source rules. Neither count measures unique
experimental samples or scientific acceptance. Chunk totals do not establish
the membership/completeness of a particular active vector generation.

The last pipeline result is historical, not proof that scheduling is active.
The [pause record](operations/SCLIB_AUTOMATION_PAUSE_2026-09-03.md) documents the
September ingest/NER/aggregate pause. This README task checked the GitHub workflow
state, not current host timer or process state, and did not resume any scheduler.

## Feature checks and documentary basis

Public page reads included `/`, `/stats`, `/docs`, `/docs/data`, `/docs/api`,
`/materials`, `/timeline` and `/discovery`. Current API responses and fresh page
reads take precedence over older search-engine page snapshots.

| README description | Basis and scope |
|---|---|
| Search/Ask, generation mode and numerical envelopes | [API](API.md), [routing](SCIENTIFIC_QUERY_ROUTING.md), [generations](INDEX_GENERATIONS.md); branch implementation and documented fallback, not a new model-quality evaluation |
| Atomic material result conditions and evidence | [semantics](MATERIAL_SEMANTICS_CONTRACT.md), [pressure](PRESSURE_SEMANTICS.md), [recovery](materials_enrichment.md) and current public catalogue response |
| External MP/COD/NOMAD/MDR readers | [recovery/reference contracts](materials_enrichment.md); independent references, not automatic sample/phase association |
| MDR Organic 568 populated rows / 49 columns | [Organic reader](materials_mdr_organic.md); excludes one entirely empty trailing data record |
| Source windows and finite computational capture | [source observations](materials_source_observations.md), [reference pilot](materials_source_reference_pilot.md), [computational context](materials_computational_reference.md) |
| Reported-Tc timeline and sampling | Fresh `/timeline` page plus [timeline contract](TIMELINE_RESULT_CONTRACT.md) |
| Discovery tabs and three unranked MgB₂-site proposals | Fresh `/discovery` page plus [catalogue contract](discovery_candidate_catalogue_2026_10_06.md) |
| Local structure/QE preparation and output tools | [coordinate workflow](discovery_structure_coordinates.md), [QE input](discovery_qe_input_preparation.md), [QE output](discovery_qe_output_reading.md), [sampled convergence](discovery_qe_convergence.md) |
| Restricted research/ML capabilities | The individual contracts in the [documentation index](README.md); feature/role/source/review gates remain separate |
| Development setup and architecture | `docker-compose.yml`, `docker-compose.dev.yml`, `.env.example`, `frontend/package.json`, `api/config.py` and [schema rollout](SCHEMA_ROLLOUT.md) |

This verification used public read-only coverage requests and source/document
inspection. It did not run production ingestion, migrate a database, call a
generation provider, execute a scientific calculation or train a model.
The README update changes repository documentation and GitHub metadata; the
deployed application baseline above remains a historical observation.

## Documentation validation

Before publication, all **169 relative links/anchors** in the three new or
updated documents resolved, and all **19 distinct live website/API links** in
the README returned HTTP 200. GitHub's GFM renderer produced the expected
14 headings, four tables and four code blocks. `git diff --check` passed.

The filtered Materials example was exercised as a public read-only request and
returned four rows with `limit=10` and `offset=0`. The Search JSON was parsed and
checked against the current request-model fields; no provider-backed Search/Ask
request was executed. No application code changed, so application tests and
the automatic image/deployment chain are not needed for this documentation
publication. The documentation commit uses `[skip ci]` for that scope.
