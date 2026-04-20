# SCLib_JZIS — JZIS Superconductivity Library

A self-hosted research platform for superconductivity: **full-text
semantic search**, a **provenance-traced materials database**, and
**RAG Q&A with per-paper citations**. Built on arXiv cond-mat plus
NIMS SuperCon seed data, refreshed hourly.

**Live:** [jzis.org/sclib](https://jzis.org/sclib) ·
**API:** [api.jzis.org/sclib/v1](https://api.jzis.org/sclib/v1) ·
**License:** Apache 2.0 (code) / CC BY 4.0 (data)

---

## What's inside today

| | |
|---|---|
| 📄 **Papers indexed** | 6,163 arXiv papers (1993–present), ~100/hour new |
| 🧪 **Materials** | 8,181 compounds; 1,227 with full NER evidence trail |
| 📚 **Vector chunks** | 152,933 (Vertex AI Matching Engine, 768-dim) |
| 🏷 **Families** | 7 (cuprate · iron-based · hydride · MgB₂ · heavy fermion · fulleride · conventional) |
| 🔄 **Freshness** | Dashboard updated hourly, aggregates rebuilt daily |

Paper ingest (arXiv OAI-PMH → LaTeX parse → chunk → embed → Vertex
VS + Postgres) runs out-of-band and is **idempotent** — every record
carries enough state to survive restarts and be re-run.

---

## Design decisions that make this different from a plain paper index

### 1. Every cell in the materials table is traceable

The flat columns on a material page (Tc max, pairing symmetry,
crystal structure, …) are **aggregates** of per-paper NER records.
We show both the aggregate *and* the underlying evidence so readers
can cross-check. Example: [HgBa₂Ca₂Cu₃O₈](https://jzis.org/sclib/materials/mat:hgba2ca2cu3o8)
shows `Tc max = 164 K, confirmed by 4 papers`, with a table below
listing each paper's claim (Tc, pressure, sample form, measurement
method, pairing, year, arXiv link).

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
from the public list:

- **Tc > 250 K at ambient pressure** → `needs_review=true`, hidden
  from `/materials` (confirmed SC Tc tops out near 140 K at ambient;
  200 GPa hydrides stay under 260 K). These are usually NER confusing
  a Curie temperature, melting point, or theoretical estimate with
  the SC Tc.
- **`cuprate_*` structure phase without Cu in formula** → rejected
  (NER over-applies cuprate taxonomy to unfamiliar compounds).
- **`tc_max` for well-studied materials requires multi-paper
  corroboration** — at least `min(10, n_papers/20)` independent
  papers must report ≥ the candidate value. MgB₂ would have shown
  79 K from one outlier paper under plain `max(tc_kelvin)`; the
  corroboration rule gives it the correct 40 K confirmed by 36
  papers.
- **`tc_ambient` only counts records where NER affirmatively
  emitted `ambient_sc=true`** — we do not trust the NER's
  `pressure_gpa=0.0` fallback as an ambient signal.
- Invariant `tc_max ≥ tc_ambient` is enforced post-hoc.

### 4. Formula canonicalization + family taxonomy

`Bi_2Sr_2CaCu_2O_{8+δ}`, `Bi2212`, `BSCCO`, `Bi_2Sr_2CaCu_2O_8-δ`,
`Bi_2Sr_2CaCu_2O_8+x`, `Bi_2Sr_2CaCu_2O_{8+delta}` — all collapse to
the same material (388 papers). Implementation: LaTeX subscript
strip + Greek-ASCII fold + variable-stoichiometry suffix collapse +
acronym alias table + crystallographic polytype prefix strip (2H-,
3R-, …). Distinct numeric stoichiometries (O₆.₅ vs O₆.₉₅ vs O₇)
deliberately stay separate as different doping regimes.

### 5. Hourly dashboard / daily aggregates

- FastAPI lifespan spawns an async task that rebuilds the
  `stats_cache['dashboard']` row every 3600 s, so the landing
  page reflects the real DB state within the hour.
- A `systemd` timer at 03:10 UTC reruns
  `sclib-ingest --mode aggregate-materials` on all papers,
  refreshing the per-material summary with any new NER evidence
  from the previous day's arXiv harvest.
- Three consecutive failures on either loop send an email via
  Resend to `info@jzis.org`.

---

## Access model

| Tier | Auth | Limit |
|---|---|---|
| **Guest** | none (IP-based Redis counter) | 3 search + 3 ask / day |
| **Registered** | email verified, `X-API-Key: scl_…` | unlimited |

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
     Redis      Vertex VS     Gemini 2.5 Flash
   (rate lim)  (768-dim)      (RAG answer + NER)

                         ─── ingest pipeline ───
                               (one-shot)
  arXiv OAI-PMH  →  LaTeX parser  →  chunker  →  text-embedding-005
       │                                                  │
       ▼                                                  ▼
  GCS archive                                   Vertex VS + Postgres
                                                          │
                                         ┌────────────────┘
                                         ▼
                               Gemini NER → per-paper
                               materials_extracted JSONB
                                         │
                                         ▼       (daily systemd timer)
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
ingestion/        One-shot pipeline: arXiv → Postgres + Vertex VS
scripts/          Host-side cron / systemd orchestration
deploy/systemd/   Timer + service units (hourly stats, daily aggregate)
docs/             API reference, deployment guide
```

---

## Roadmap

- Backfill remaining NIMS-origin materials (~6,900) with NER evidence
  as the arXiv archive catches up to their formula mentions
- Family-specific sanity thresholds (e.g. `fulleride > 60 K →
  needs_review` — historical record is Cs₃C₆₀ at 38 K)
- Admin view for `include_pending=true` materials with one-click
  unflag after manual review
- Per-material Hc2(T) and Tc(P) plot widgets synthesised from the
  records array
- Citation graph (papers ↔ references) for cross-paper consistency
  checks

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

© 2026 Jian Zhou / JZIS
