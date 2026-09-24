# SCLib_JZIS — JZIS Superconductivity Library

A self-hosted research platform for superconductivity: **full-text
semantic search**, a **provenance-traced materials database**, and
**RAG Q&A with per-paper citations**. Built on arXiv cond-mat, a
small APS TDM pilot, and NIMS SuperCon seed data, with production
ingest, aggregation, stats refresh, and scoped data-audit jobs.

**Live:** [jzis.org](https://jzis.org) ·
**API:** [api.jzis.org/sclib/v1](https://api.jzis.org/sclib/v1) ·
**License:** Apache 2.0 (code) / CC BY 4.0 (data)

---

## Research-v2 development status

The local research branch has separate [implementation records](docs/reviews/2026-09-05/README.md).
Its latest infrastructure adds [bounded internal research integrity capsules](docs/RESEARCH_RELEASE_FREEZE.md)
and [explicit schema migration with read-only API admission](docs/SCHEMA_ROLLOUT.md).
The next boundary adds [explicit research-role access and reviewed metadata-only publications](docs/RESEARCH_PUBLICATION_ACCESS.md).
Retrieval now also has [immutable index generations and controlled rollback](docs/INDEX_GENERATIONS.md)
and [formula-safe scientific query routing](docs/SCIENTIFIC_QUERY_ROUTING.md).
New authenticated answers also retain [private final-output evidence receipts](docs/ANSWER_HISTORY_RECEIPTS.md),
with exact historical references, honest save outcomes and separate current
metadata warnings. Legacy history is not retroactively rebound.
Scientific-program ingestion now also has a [private, pending-only native-file importer](docs/SCIENTIFIC_PENDING_IMPORTS.md)
with retained source bytes, actual coordinate parsing, durable attempts and
rollback-only preview. Parsed observations are not approved scientific results.
A [private scientific evidence workbench](docs/SCIENTIFIC_EVIDENCE_WORKBENCH.md)
now pairs exact properties with state/run/source metadata and bounded downstream
references. Its read-only dossier now accompanies a separate
[exact-result adjudication workflow](docs/SCIENTIFIC_RESULT_ADJUDICATION.md) with
immutable scoped decisions, explicit previews and same-request recovery.
Scientific acceptance still does not confer training or publication authority.
RPS distribution now also has [exact source-binding and descriptor preparation](docs/RPS_DISTRIBUTION_PREPARATION.md)
for curator preview/atomic registration before the existing
[dependency rights workbench](docs/RPS_RIGHTS_PREPARATION.md).
The API prepares private descriptors from existing pinned sources; it does not
create scientific evidence, approve rights or publish the package.
An [exact scientific Discovery companion](docs/DISCOVERY_SCIENTIFIC_PROJECTIONS.md)
now binds explicit material representatives and alternatives to native scientific
observations, with separate three-account disclosure and opt-in current public
admission. Its [public browser matrix](docs/DISCOVERY_SCIENTIFIC_MATRIX.md),
[curator preparation](docs/DISCOVERY_SELECTION_PREPARATION.md), and independent
[Discovery governance workbench](docs/DISCOVERY_OPERATOR_GOVERNANCE.md) now expose
separate scientific inspection, append-only history and exact protected actions.
The [v2 main-barrier contract](docs/DISCOVERY_MAIN_BARRIERS.md) adds explicit,
context-bound curator interpretations without changing frozen RPS or v1 records.
A real reviewed pilot remains separate; recorded quantities and research-priority
scores are not ground truth.
The [private ML08 review report](docs/ML_PILOT_REPORT.md) provides an offline
English view of a replayed canary, with complete event/history accounting,
missingness and recorded effort; it does not authorize scientific acceptance.
The [private run-review evidence workflow](docs/ML_RUN_EVIDENCE.md) binds short
review text to exact conditional approvals with controlled read/purge, without
granting scientific acceptance or execution authority.
The [private ML08 canary command](docs/ML_PILOT_CANARY.md) binds the frozen
selection, complete review ledger, explicit context bytes and final documentary
conclusion through exact replay; it does not authenticate human review or grant
scientific acceptance or training permission.
The [private baseline preparation CLI](docs/ML_BASELINE_PREPARATION.md) connects
audited datasets to reproducible configuration drafts, feature/split coverage
inspection and exact preparation replay. It does not authorize or run real-data
model training.
The [independent ML membership registry](docs/ML_USE_GOVERNANCE.md) adds opt-in
administrator preview/grant/revoke and current authenticated role inspection.
It grants neither source access nor model execution; existing roles are not
automatically converted to ML memberships.
An [exact ML-use intake and online preflight](docs/ML_USE_PREFLIGHT.md) now links
locally rebuilt baseline inputs to server-derived registered source requirements.
The inspection is read-only and grants neither source permission nor execution.
The [private input reconstruction endpoint](docs/ML_USE_RECONSTRUCTION.md) can
also receive all eight exact files and rebuild the dataset/preparation in a
bounded offline worker. It does not authenticate client runtime claims, persist
an approval request or grant source-use/training permission.
A separate [current ML audit inspection](docs/ML_USE_CURRENTNESS.md) recaptures
the full review/label observations and reports their versioned dependency
inventory in one fresh SQL snapshot. It is not a lasting permission or run grant.
The [private submission workflow](docs/ML_USE_SUBMISSIONS.md) retains exact
requests and separately purgeable inputs for recovery and fresh reinspection;
retained historical evidence is not source-use or training authorization.
The [independent ML rights registry](docs/ML_USE_RIGHTS.md) records purpose-bound,
expiring per-resource decisions and checks full current permission coverage;
neither a historical rights receipt nor coverage alone authorizes training.
Its private **ML source rights** dashboard provides exact-resource inspection,
explicit preview/commit and original-key recovery without automatic approvals.
The [private run-plan registry](docs/ML_USE_RUNS.md) binds independent conditional
review to exact inputs and budgets; live readiness remains separate from execution.
Its private **ML run plans** dashboard supports explicit owner budgets,
independent preview/commit, historical recovery and separate current-condition
checks; neither the page nor an approval can start a model.
Numerical/evidence queries and Search UI scientific filters return qualified,
exact-parent extraction rows separately from ordinary paper hits; without an
active generation they explicitly report unavailable. These are not reviewed
scientific Results. See the routing document for client compatibility changes.
These are not a production rollout, scientifically approved training datasets,
or permission to redistribute source text and artifacts. The production snapshot
below is historical and must not be read as validation of these local upgrades.

---

## What's inside today

Production snapshot checked 2026-06-14 UTC.

| | |
|---|---|
| 📄 **Papers indexed** | 45,763 total: 45,762 arXiv + 1 APS pilot row |
| 🧪 **Materials** | 15,623 compounds with records; 8,252 public after review filters |
| 📚 **Vector chunks** | 1,014,882 (Vertex AI Matching Engine, 768-dim) |
| 🏷 **Families** | 16 populated families, led by iron-based, cuprate, conventional, chalcogenide, hydride, heavy fermion, and MgB₂ |
| 🔄 **Freshness** | Latest paper indexed 2026-06-14 08:02 UTC; latest scoped data audit 2026-06-14 07:00 UTC |

Paper ingest and material aggregation run out-of-band and are
**idempotent**: every record carries enough state to survive restarts
and be re-run. The deployed materials aggregate runs hourly via
systemd; broad data audits are explicit review passes recorded in
`audit_reports`.

---

## Design decisions that make this different from a plain paper index

### 1. Every cell in the materials table is traceable

The flat columns on a material page (Tc max, pairing symmetry,
crystal structure, …) are **aggregates** of per-paper NER records.
We show both the aggregate *and* the underlying evidence so readers
can cross-check. Example: [HgBa₂Ca₂Cu₃O₈](https://jzis.org/materials/mat:hgba2ca2cu3o8)
currently shows `Tc max = 138 K` across 29 source papers after the
per-compound cap is applied, with the record table below listing each
paper's claim (Tc, pressure, sample form, measurement method, pairing,
year, source paper).

### 2. Conservative aggregation — NULL beats "confidently wrong"

Discrete fields (pairing symmetry, structure phase, gap structure …)
use **confidence-weighted voting** with thresholds:

- ≥ 60% of summed paper confidence must point to one value
- ≥ 2 distinct papers must agree when the material has ≥ 2 records
- Boolean flags (`is_topological`, `is_unconventional`, …) need
  70% agreement AND < 20% dissent; otherwise NULL

A single low-confidence paper does not promote a value to the flat
column. Silence is preferred over false precision.

### 3. Automatic sanity gates

Numeric outliers that the NER plausibly mis-extracted are held back
from the public list with `needs_review=true`:

- Family-specific and per-compound Tc ceilings catch values above
  known superconducting records.
- Ambient-pressure claims above the accepted ambient record are
  quarantined for review.
- Hydride claims with high Tc at low pressure are quarantined, since
  plausible high-Tc hydrides require extreme pressure.
- Contradictory pressure, family, unconventionality, citation
  conflation, and retracted-source patterns are audited.
- Formula-shape rules catch descriptor text, charged/incomplete
  formulas, and space-group prefixes that slipped through NER.
- Manual overrides and caps preserve reviewed corrections for
  well-studied materials such as MgB₂ and Hg cuprates.

### 4. Formula canonicalization + family taxonomy

`Bi_2Sr_2CaCu_2O_{8+δ}`, `Bi2212`, `BSCCO`, `Bi_2Sr_2CaCu_2O_8-δ`,
`Bi_2Sr_2CaCu_2O_8+x`, `Bi_2Sr_2CaCu_2O_{8+delta}` — all collapse to
the same material (572 source papers in the current production
snapshot). Implementation: LaTeX subscript
strip + Greek-ASCII fold + variable-stoichiometry suffix collapse +
acronym alias table + crystallographic polytype prefix strip (2H-,
3R-, …). Distinct numeric stoichiometries (O₆.₅ vs O₆.₉₅ vs O₇)
deliberately stay separate as different doping regimes.

### 5. Production refresh and scoped audit workflow

- FastAPI lifespan spawns an async task that rebuilds the
  `stats_cache['dashboard']` row every 3600 s, so the landing
  page reflects the real DB state within the hour.
- A `systemd` timer at `*:30` reruns
  `sclib-ingest --mode aggregate-materials` on all papers,
  refreshing the per-material summary with new NER evidence.
- Admin/reviewer audit pages expose `audit_reports`, the review queue,
  one-click pass/hold actions, and scoped data-audit reports for
  newly ingested paper windows.
- Three consecutive aggregate failures send an email via
  Resend to `info@jzis.org`.

---

## Access model

| Tier | Auth | Limit |
|---|---|---|
| **Guest** | none (IP-based Redis counter) | 3 quota-checked search/ask requests per day |
| **Registered** | email verified, `X-API-Key: scl_…` or JWT | 999 quota-checked requests per day by default |

Registered users get a Google OAuth option in addition to
email+password. Existing JZIS accounts, API keys and saved research continue
to work throughout SCLib at [jzis.org](https://jzis.org).

---

## Quickstart (local dev)

```bash
cp .env.example .env        # fill DB_PASSWORD, JWT_SECRET,
                            # INTERNAL_API_KEY, GCP creds, RESEND_API_KEY
docker compose up -d postgres redis
# Set SCLIB_MIGRATION_DATABASE_URL in this shell to the local-only migration
# credential; do not store it in the API's .env. See docs/SCHEMA_ROLLOUT.md.
docker compose run --rm migration
docker compose up -d api frontend  # startup checks schema; never migrates it
docker compose run --rm ingestion sclib-ingest --mode smoke --limit 30
```

Then:
- Frontend: <http://localhost:3100>
- API: <http://localhost:8000/v1/stats>

## Quickstart (API consumers)

```bash
# Unauthenticated guest search (3 free per day per IP)
curl -s -X POST https://api.jzis.org/sclib/v1/search \
     -H 'Content-Type: application/json' \
     -d '{"query":"hydride room temperature superconductor","top_k":5}'

# Authenticated — register at jzis.org/register first
curl -s https://api.jzis.org/sclib/v1/materials?family=cuprate&sort=tc_max \
     -H 'X-API-Key: scl_your_key_here'
```

Full endpoint reference: [`docs/API.md`](./docs/API.md).

---

## Architecture

```
                     ┌──────── Nginx (TLS, reverse proxy) ────────┐
                     │                                              │
  Next.js 15  ◄──────┤ jzis.org                                     │
  (SSR, RSC)         │ api.jzis.org/sclib/v1                        │
                     │                                              │
                     └──┬────────────────┬──────────────────────────┘
                        ▼                ▼
                   FastAPI           PostgreSQL 16
                   (api)             papers · chunks · materials ·
                     │               users · api_keys · stats_cache
                     │
       ┌─────────────┼─────────────┐
       ▼             ▼             ▼
     Redis      Vertex VS     Gemini 3.5 Flash
   (rate lim)  (768-dim)      (RAG answer + NER)

                         ─── ingest pipeline ───
                         (scheduled one-shot jobs)
  arXiv OAI-PMH  →  LaTeX parser  →  chunker  →  Gen AI text-embedding-005
  APS TDM pilot  →  transient XML  →  fact chunks  →  deletion audit
       │                                                  │
       ▼                                                  ▼
  GCS archive / metadata                       Vertex VS + Postgres
                                                          │
                                         ┌────────────────┘
                                         ▼
                               Gemini NER → per-paper
                               materials_extracted JSONB
                                         │
                                         ▼       (hourly systemd timer)
                               aggregate-materials
                                  → materials row upsert
```

All containers bind to `127.0.0.1` only; Nginx is the only public
listener. Deploy details: [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md).

---

## Repo layout

```
api/              FastAPI + SQLAlchemy + Alembic migrations
frontend/         Next.js 15 (app router, SSR)
ingestion/        Pipelines: arXiv/APS → Postgres + Vertex VS
scripts/          Host-side cron, audit, backup, and systemd orchestration
deploy/systemd/   Timer + service units for hourly material aggregation
docs/             API reference, deployment, APS/TDM validation notes
```

---

## Roadmap

- Expand APS ingestion beyond the current pilot while preserving TDM
  deletion-proof audit logs.
- Improve reviewer workflows around the 7k+ `needs_review` queue,
  including batch review and richer suggested fixes.
- Per-material Hc2(T), Tc(P), and source-quality widgets synthesised
  from the records array.
- Citation and cross-source consistency graph for paper ↔ material
  provenance checks.
- Broader Materials Project / parent-variant UI for composition
  families and doped variants.

---

## Citation

```bibtex
@misc{sclib2026,
  author    = {Zhou, Jian},
  title     = {{SCLib\_JZIS}: {JZIS} {S}uperconductivity {L}ibrary},
  year      = {2026},
  publisher = {GitHub},
  url       = {https://github.com/JackZH26/SCLib_JZIS}
}
```

## License

| | |
|---|---|
| Code | Apache 2.0 |
| Aggregated material / paper data | CC BY 4.0 |
| arXiv full-text | original arXiv license (per paper) |
| APS licensed content | transient processing only; raw content is not redistributed |

© 2026 Jian Zhou / JZIS
