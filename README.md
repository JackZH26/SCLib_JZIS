# SCLib by JZIS

**A superconductivity research library connecting literature, materials, reported properties and research workflows.**

SCLib combines hybrid literature search and citation-backed AI question answering
with a source-linked materials database, an interactive reported-Tc timeline,
and Discovery tools for inspecting evidence and preparing research proposals.
It is developed and maintained by **JZ Institute of Science** and is available
at **[jzis.org](https://jzis.org/)**.

[Search & ask](https://jzis.org/search) · [Browse materials](https://jzis.org/materials)

[Reported Tc Timeline](https://jzis.org/timeline) · [Discovery](https://jzis.org/discovery)

[User documentation](https://jzis.org/docs) · [API reference](https://jzis.org/docs/api)

## Current coverage and versions

Checked **9 October 2026 (UTC)** against the public API and website. Counts describe
the retained library and its current public projections, not independently
validated experiments or complete coverage of superconductivity research.

| Measure | Verified snapshot |
|---|---|
| Indexed papers | **75,202**: 46,895 arXiv + 28,307 APS |
| Catalogued materials | **11,463** stored library entries |
| Public Materials catalogue | **10,507** entries under the default browsing scope |
| Retained literature chunks | **1,117,982**; not a count of verified active vector-index members |
| Data version | **`v2026.09.03`** |
| Latest paper ingest | 3 September 2026, 10:30 UTC |
| Statistics refreshed | 9 October 2026, 09:00 UTC |
| Deployed software checked | [`7efe186`](https://github.com/JackZH26/SCLib_JZIS/commit/7efe1866d610ad227fef9be9f59000173c09d248), rechecked at 09:52–09:53 UTC |
| Public API version | **`v1`**, at `https://api.jzis.org/sclib/v1` |

Statistics refresh, literature ingest, source-reference updates and software
deployment have separate timelines. Automatic literature ingest/NER and scheduled
material aggregation were [paused on 3 September](docs/operations/SCLIB_AUTOMATION_PAUSE_2026-09-03.md);
the daily arXiv workflow remained disabled when checked. A fresh statistics
timestamp does not mean new papers were ingested that day.

Use [Library statistics](https://jzis.org/stats), [`GET /stats`](https://api.jzis.org/sclib/v1/stats)
and [`GET /version`](https://api.jzis.org/sclib/v1/version) for current values.
The [verification record](docs/README_SNAPSHOT_2026_10_09.md) explains the snapshot
and its scope. Research-v2 contracts and the package metadata version are separate
from the deployed commit, API version and dataset date.

## Explore the library

### Search literature and ask research questions

- Search by topic, formula or research question, with date and scientific filters.
- Hybrid retrieval combines Vertex AI semantic candidates with PostgreSQL
  full-text search, rank fusion and query-coverage reranking. Formula-safe routing
  keeps qualified numerical extractions separate from ordinary paper hits.
- Ask produces answers with linked paper citations; registered users can retain
  question history and bookmarks. Evidence receipts preserve supported provenance
  for new authenticated answers where the receipt workflow is enabled.
- Retrieval reports its index-generation mode. Without an active generation,
  ordinary Search/Ask use an explicit lexical fallback; structured scientific
  lookup reports unavailable rather than inventing numerical evidence.

Source coverage and processing rights differ by provider. APS coverage includes
28,307 indexed paper records; its raw licensed full text is processed transiently
and is not redistributed as an open full-text archive.

### Compare materials with their reported conditions

[Materials](https://jzis.org/materials) supports formula text, family, reported
Tc, pressure, result origin and source filters, plus sorting and pagination.
Additional controls cover reported pairing/classification, source tier,
source-link counts, library-only entries and parent materials.

The table presents **one reported Tc result together with that result's
conditions and source year**. Family/Tc/pressure/result-evidence predicates must
match the same extracted result. A catalogue maximum and a separately matched
result stay distinct; pairing/classification summaries can have a different
source or state scope. Reviewed phase filtering remains unavailable until the
required material/state associations exist.

Open a material's **Evidence** and detail views to inspect retained records,
alternative reports, source identity, provenance gaps and review status.
Source recovery adds bounded, pending candidates for literal values, methods,
sample descriptions, classifications and table fields. Its checked source
window and exclusions are exposed; an unsuccessful search is not proof that
the complete paper omitted a property.

The current primary-source recovery batch exposes **55 source observations and
34 pending literal candidates across 16 materials**. These sets can overlap;
they are not 89 independently accepted facts. Sample/state associations remain
pending, with no canonical property correction or human scientific approval.
The [batch record](docs/MATERIALS_SOURCE_RECOVERY_BATCH_20261008.md) and
[review preparation](docs/NEXTSTAGE_EXECUTION_2026_10_09.md) retain the unresolved conditions.

See [material semantics](docs/MATERIAL_SEMANTICS_CONTRACT.md),
[pressure semantics](docs/PRESSURE_SEMANTICS.md) and
[source recovery](docs/materials_enrichment.md).

### Inspect independent source references

Eligible material pages offer separate, on-demand **Materials Project**, **COD**,
**NOMAD** and versioned **NIMS MDR SuperCon** reference panels. Composition matches
provide references to investigate; they do not establish the same experimental
sample, phase, state or accepted catalogue property.

| Source surface | What it provides |
|---|---|
| NIMS MDR SuperCon Ver.240322, Oxide & Metallic | A pinned 33,458-row, 191-column source table; material-bound lookups retain source rows, bibliography, raw cells and condition roles |
| [NIMS Organic reader](https://jzis.org/materials/source-references/organic) | **568 nonempty source rows and 49 original columns**, with search, pagination, row details and full or filtered exports |
| COD | Crystallographic references with revision links, cell metrics, uncertainties and available diffraction conditions |
| Materials Project / NOMAD | Computed composition references and available calculation metadata, kept separate from experimental superconducting results |
| [Source-reference pilot](https://jzis.org/materials/source-references) | Seven scoped CrB₂ paper items and three independent COD references, with downloadable metadata |
| [Source observations](https://jzis.org/materials/source-observations) | Finite source-specific property windows, including field estimates, penetration depth, gap fits and crystallographic metadata |

The [computational reference reader](https://jzis.org/materials/source-observations/computational-references)
also exposes a finite NOMAD CrB₂ capture and native-input context. Source studies
cover [Nb-doped CsV₃Sb₅ pressure results](docs/materials_nb_cvs_pressure.md),
[NbScTiZr annealing](https://jzis.org/materials/source-observations/nbsctizr-annealing)
and [LaH₁₀/LaD₁₀ computed pressure series](docs/discovery_pressure_series.md).
These readers preserve source-specific definitions and unresolved associations;
they do not automatically promote observations into formal material properties.

### Explore reported Tc over time

The [Reported Tc Timeline](https://jzis.org/timeline) plots reported results with
family, result origin, pressure, source and date basis. It includes family/origin
filters, linear, logarithmic and low-temperature views, overlap inspection and
an accessible result table.

Full eligible-selection summaries are separate from the displayed sample, which
can be limited to 2,000 or 10,000 results. The timeline is a view of reported
records, not a certified world-record ranking or a discovery-history chronology.

### Inspect candidates and prepare a research workflow

[Discovery](https://jzis.org/discovery) now has **Candidates** and **Research & tools** tabs.

The candidate view now provides **103 composition-distinct source-computed
research hypotheses**, derived from Materials Cloud 2023.163 v1 under CC BY 4.0.
Each retains its source state, controls, method limitations and evidence dossier.
Displayed Tc is a source Eliashberg model result at **μ* = 0.1**, with no binding
to an individual Gaussian-smearing row. All 103 remain **C (exploratory), E1
(published source theory)**. No experimental confirmation, room-temperature
support, formal RPS score or recorded human scientific review is established.

Published RPS assessments and the **unrelaxed COD coordinate catalogue** remain
separate. The latter contains **eight composition groups and 19 coordinate
states**, including the earlier Mg₇AlB₁₆, Mg₇CaB₁₆ and Mg₇B₁₆ proposals and host
strain references. Coordinate states are not separate new compounds; these
counts are not added to the 103 source-computed materials.

Research tools support an explicit **host → modification → state → conditions**
workflow: source/physical-reference inspection, local research-design drafts,
structure coordinates and CIF exports, site/combined modifications, and
Quantum ESPRESSO input preparation with original pseudopotentials.
The [calculation reader](https://jzis.org/discovery/calculations) checks supported
native QE outputs against their preparation inputs and supports sampled
numerical-refinement comparisons. Browser preparation and reading do not submit
or execute a calculation; file consistency does not attest an actual execution.

The repository also retains **12 retrospective benchmark cases** and **36
prepared SCF inputs across 12 MgB₂/Al/C/joint-substitution states**. Those inputs
are not executed results or a prospective held-out benchmark. The earlier
nine-run VPS SCF pilot completed, but its sampled energy windows failed the
declared tolerance and require method refinement. An isolated dummy compute
coordinator has separate transport acceptance; it does not enable browser
submission, native QE execution or scientific acceptance.

RPS-v1.2 scores span **1,000-10,000** and prioritize a **material-state-action**
within a defined campaign, evidence policy and resource budget. They are not
superconductivity probabilities, predicted Tc values or universal cross-campaign
rankings. Scientific companions and historical candidate feeds have their own
publication and availability states.

See the [source-computed catalogue](docs/DISCOVERY_EVIDENCE_CARDS_20261008.md),
[coordinate catalogue](docs/discovery_research_catalogue_v2.md),
[batch preparation](docs/SCLIB_BATCHES_1_2_20261008.md),
[research-design protocol](docs/discovery_research_design_protocol.md),
[QE preparation](docs/discovery_qe_input_preparation.md) and
[scientific evaluation protocol](docs/SCIENTIFIC_EVALUATION_PROTOCOL.md).

## Database and evidence model

SCLib retains the public paper/material catalogue while extending PostgreSQL
with versioned research records. The research model separates **material
identity, sample, state, structure, event, property, run, artifact, review and
publication** rather than treating a formula as a complete scientific result.

- **Property context:** values retain units, quantity roles, origin, method,
  pressure/temperature context and source locators where supplied.
- **Provenance and revisions:** source captures, hashes, append-only revisions,
  lifecycle decisions and current serving checks support reproducible inspection.
- **Missingness and conflicts:** unknown, unavailable, pending and disputed
  evidence remain distinct. Missing pressure is not ambient pressure; a missing
  classification is not an explicit negative result.
- **Separate decisions:** catalogue visibility, source rights, scientific
  acceptance, public release and ML use have distinct checks. Source-link counts
  do not measure independent experiments or replications.

AI-assisted extraction and generated answers require checking against the
original literature. Legacy records and incomplete locators remain visible as
limitations; no claim is made that every retained field is fully source-verified.
Read [Data & methodology](https://jzis.org/docs/data) for interpretation guidance.

### Research and ML implementation status

The repository also contains restricted scientific import/review workbenches,
frozen evidence releases, RPS publication governance, task-specific ML dataset
compilers, baseline preparation/replay, membership and source-rights registries,
and conditional run-plan review. Availability depends on explicit feature flags,
roles, source permissions and reviewed records.

These implementations are not a blanket production rollout, an approved training
dataset or an automatic model-execution service. An input preparation, integrity
hash or conditional plan approval does not establish scientific acceptance or
permission to train. The [documentation index](docs/README.md) groups these
contracts and their operational boundaries without conflating them with the
public browsing features above.

The [current execution record](docs/NEXTSTAGE_EXECUTION_2026_10_09.md) separates
online acceptance, measured latency, pending material review, a 60-question
retrieval acquisition draft and compute/ML prerequisites. The draft is not an
adjudicated gold set or permission to train. Recheck public versions and scoped
counts with the credential-free acceptance tool:

```bash
python3 scripts/verify_public_snapshot.py --samples 3 --output /tmp/sclib-public-snapshot.json
# Optional: also verify all 206 static source-detail and evidence-card files.
# Add --all-details; use a new output path for each capture.
```

## Accounts and API

Sign in with [Google or email/password](https://jzis.org/login), or
[register](https://jzis.org/register). The account dashboard provides API keys,
saved items and question history. Browser sessions use HttpOnly cookies;
programmatic clients can use `X-API-Key: scl_…` or a bearer JWT.

| Access | Default daily query quota |
|---|---|
| Guest | 3 quota-checked data queries per IP |
| Verified registered account | 999 quota-checked data queries per user, shared across API-key/session access |

Quotas are configurable and do not apply uniformly to every public page or
metadata endpoint. Restricted research roles are granted separately.

```bash
# Public coverage and version metadata
curl -fsS https://api.jzis.org/sclib/v1/stats
curl -fsS https://api.jzis.org/sclib/v1/version

# Literature search
curl -fsS -X POST https://api.jzis.org/sclib/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"MgB2 multiband superconductivity","top_k":5}'

# Reported, observed cuprate results with a supplied pressure limit
# Set SCLIB_API_KEY to an API key from your account dashboard.
curl -fsS \
  'https://api.jzis.org/sclib/v1/materials?family=cuprate&tc_min=30&pressure_max=1&knowledge_origin=Observed&limit=10&offset=0' \
  -H "X-API-Key: ${SCLIB_API_KEY}"
```

Pagination uses **`limit`/`offset`**. Inspect response status and provenance
envelopes as well as result rows. Full contracts and compatibility notes:
[API reference](docs/API.md), [API versioning](docs/API_VERSIONING.md) and
[scientific query routing](docs/SCIENTIFIC_QUERY_ROUTING.md).

## Run locally

Use Docker Compose for the application stack, **uv** for Python development and
**pnpm** for the frontend. Configure `.env` from the example, including matching
database passwords, authentication secrets and the required GCP/Vertex settings.
Provision the credential files referenced by Compose as described in
[workload identity](docs/WORKLOAD_IDENTITY.md).

```bash
git clone https://github.com/JackZH26/SCLib_JZIS.git
cd SCLib_JZIS
cp .env.example .env
# Configure .env and credential files before starting services.
docker compose up -d postgres redis

# Supply SCLIB_MIGRATION_DATABASE_URL only to this shell's migration job,
# using your local database credential. Keep it out of the API .env.
docker compose run --rm migration
docker compose up -d api frontend
```

Open [localhost:3100](http://localhost:3100) and
[localhost:8000/v1/stats](http://localhost:8000/v1/stats).
Migrations are explicit one-shot jobs; API startup checks schema compatibility
and does not migrate it. Data ingest is a separate, opt-in job requiring source
and cloud configuration. See [schema rollout](docs/SCHEMA_ROLLOUT.md),
[deployment](docs/DEPLOYMENT.md) and [safe testing](docs/TESTING_SAFELY.md).

## Architecture and repository

| Layer | Implementation |
|---|---|
| Public gateway | Nginx with TLS, serving `jzis.org` and `api.jzis.org/sclib/v1` |
| Website | Next.js 15 App Router, React 19, TypeScript and Tailwind CSS |
| API | FastAPI, SQLAlchemy and versioned response contracts |
| Storage | PostgreSQL 16 with explicit Alembic migrations; Redis for quotas/caching |
| Retrieval and AI | Vertex AI Vector Search, 768-dimensional embedding configuration, configurable Gemini generation/extraction |
| Ingestion | arXiv and licensed APS processing, parsing, chunking, extraction and audit tooling |
| Research operations | Versioned source/evidence workflows, offline validation, controlled publication and private ML preparation |
| Delivery and monitoring | Docker Compose, signed image releases, deployment checks, Prometheus/Grafana and backup/restore tooling |

```text
api/                 API, models, services, migrations and tests
frontend/            Website, researcher tools and bounded source readers
ingestion/           Literature and legacy seed-data ingestion
scripts/             Source adapters, offline research/ML tools and operations
deploy/              Host service and timer definitions
ops/                 Monitoring configuration
docs/                Contracts, workflows, release records and operational guides
```

Application ports bind to loopback in the base stack; PostgreSQL and Redis remain
internal. The development override exposes their ports on loopback.
The [documentation index](docs/README.md) is the starting point for contributors.
Report security issues through [SECURITY.md](SECURITY.md).

## Citation and licensing

Maintainer: **Jian Zhou**, Principal Investigator, **JZ Institute of Science**,
Hong Kong, China. [jack@jzis.org](mailto:jack@jzis.org),
[ORCID 0009-0000-3536-9500](https://orcid.org/0009-0000-3536-9500).

```bibtex
@misc{sclib2026,
  author       = {Jian Zhou},
  title        = {{SCLib}: {JZIS} Superconductivity Research Library},
  year         = {2026},
  organization = {JZ Institute of Science},
  url          = {https://github.com/JackZH26/SCLib_JZIS},
  note         = {Live service: https://jzis.org}
}
```

When citing a data result, also identify its dataset version, source publication
and relevant source/record identifiers.

- **Code:** [Apache 2.0](LICENSE).
- **SCLib-produced and curated data:** [CC BY 4.0](LICENSE-DATA), within the stated scope.
- **Upstream publications and datasets:** retain their own rights and attribution
  requirements. The versioned MDR Ver.240322 projection has its own CC BY 4.0
  metadata; legacy NIMS sources must be assessed under their applicable terms.
- **APS licensed raw content:** transient processing only; no raw-content redistribution.

SCLib's data licence does not override upstream licences or confer model-training
rights. Consult [data provenance](DATA_SOURCES.md), the
[versioned MDR documentation](docs/materials_enrichment.md#versioned-mdr-supercon-references),
[Organic source documentation](docs/materials_mdr_organic.md) and individual source notices.

© 2026 Jian Zhou / JZ Institute of Science.
