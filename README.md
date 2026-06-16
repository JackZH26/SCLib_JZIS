# SCLib_JZIS — JZIS Superconductivity Library

A self-hosted research platform for superconductivity: **full-text
semantic search**, a **provenance-traced materials database**, and
**RAG Q&A with per-paper citations**. Built on arXiv cond-mat, a
small APS TDM pilot, and NIMS SuperCon seed data, with production
ingest, aggregation, stats refresh, and scoped data-audit jobs.

**Live:** [jzis.org/sclib](https://jzis.org/sclib) ·
**API:** [api.jzis.org/sclib/v1](https://api.jzis.org/sclib/v1) ·
**License:** Apache 2.0 (code) / CC BY 4.0 (data)

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
can cross-check. Example: [HgBa₂Ca₂Cu₃O₈](https://jzis.org/sclib/materials/mat:hgba2ca2cu3o8)
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
email+password, using a shared JZIS account that also works at
[jzis.org](https://jzis.org) and [asrp.jzis.org](https://asrp.jzis.org).

---

## Quickstart (local dev)

```bash
cp .env.example .env        # fill DB_PASSWORD, JWT_SECRET,
                            # INTERNAL_API_KEY, GCP creds, RESEND_API_KEY
docker compose up -d        # postgres + redis + api + frontend
docker compose exec api alembic upgrade head
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

# Authenticated — register at jzis.org/sclib/register first
curl -s https://api.jzis.org/sclib/v1/materials?family=cuprate&sort=tc_max \
     -H 'X-API-Key: scl_your_key_here'
```

Full endpoint reference: [`docs/API.md`](./docs/API.md).

---

## Architecture

```
                     ┌──────── Nginx (TLS, reverse proxy) ────────┐
                     │                                              │
  Next.js 14  ◄──────┤ jzis.org/sclib                               │
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
frontend/         Next.js 14 (app router, SSR)
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
