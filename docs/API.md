# SCLib_JZIS HTTP API

Base URL: `https://api.jzis.org/sclib/v1`

All endpoints return JSON. Authenticated endpoints accept a header:

```
X-API-Key: scl_xxxxxxxxxxxxxxxx
```

Unauthenticated clients get **3 requests per day per IP** (Redis
counter, key `guest_quota:YYYY-MM-DD:{ip}`). Exceeding the quota returns
`429 Too Many Requests`.

## Auth

### `POST /auth/register`
```json
{ "email": "you@example.com", "password": "…" }
```
Creates an account and emails a verification link. Returns 202.

### `POST /auth/verify`
```json
{ "token": "<one-time-token-from-email>" }
```
Marks the account verified and returns the first API key (`scl_…`).

### `POST /auth/login`
```json
{ "email": "…", "password": "…" }
```
Returns a JWT session cookie + the masked API key record.

### `GET /auth/me`
Returns the authenticated user and their API keys.

## Search & Q&A

### `POST /search`
```json
{
  "query": "room temperature superconductors 2023",
  "top_k": 10,
  "year_min": 2020,
  "year_max": 2024,
  "material_family": "cuprate"
}
```
Embeds the query with `text-embedding-005`, runs an
approximate-nearest-neighbor lookup against the Vertex AI Matching
Engine index, then joins the hits against Postgres to return full
paper records + chunk snippets. Each hit carries a `relevance` float
in `[0, 1]`.

### `POST /ask`
```json
{ "query": "What is the role of pressure in high-Tc hydrides?" }
```
Runs `POST /search` internally, feeds the top chunks into Gemini 2.5
Flash with a system prompt that forces inline `[n]` citations, and
returns:

```json
{
  "answer": "High-pressure hydrides [1] … [2] …",
  "sources": [ { "n": 1, "paper_id": "arxiv:…", "title": "…" }, … ]
}
```

Gemini is called from a thread offload so the FastAPI event loop stays
responsive. Limits: temperature 0.2, max 1024 output tokens.

## Papers & Materials

### `GET /paper/{id:path}`
Path matches include colons: `/paper/arxiv:2512.20530`. Returns full
paper metadata, abstract, authors, linked materials, and `chunk_count`.

### `GET /similar/{id:path}?top_k=10`
Fetches up to 20 chunks for the given paper, runs a batched ANN lookup,
aggregates neighbor paper IDs by mean distance, excludes self-hits,
and returns the top-k similar papers.

### `GET /materials?family=cuprate&tc_min=77&limit=100`
Returns aggregated rows from the `materials` table. Sort order is
`tc_max DESC NULLS LAST`. Family filter values: `cuprate`, `iron_based`,
`hydride`, `mgb2`, `heavy_fermion`, `conventional`, or `null`.

### `GET /materials/{id}`
Returns a single material including its full JSONB `records` array
(every NIMS measurement aggregated under the normalized formula).

### `GET /timeline?family=cuprate`
Flattens `Material.records` into a list of `(year, tc, formula)`
points for the Plotly chart on the frontend.

### `GET /stats`
Returns dashboard counters sourced from `stats_cache['dashboard']`:
`total_papers`, `total_materials`, `total_chunks`, `papers_by_year`,
`top_material_families`, `last_ingest_at`, `updated_at`. Falls back
to a live aggregation if the cache row is missing (fresh install).

## Admin

### `POST /stats/refresh`
Recomputes and upserts the `dashboard` stats cache row. Requires:

```
X-Internal-Key: <INTERNAL_API_KEY from .env>
```

Never exposed via Nginx. Called by `scripts/cron_daily_ingest.sh`
over the loopback after each nightly ingest. Returns 503 if
`INTERNAL_API_KEY` is unset, 401 on mismatch.

## Error shape

```json
{ "detail": "human-readable message" }
```

Standard FastAPI. Quota exhaustion is `429`, auth failures are `401`,
unknown paper/material is `404`.
