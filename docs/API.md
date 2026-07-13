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
{ "email": "you@example.com", "password": "…", "name": "…" }
```
Creates an account and emails a verification link. Returns 201. `age`,
`institution`, `country`, `research_area`, and `purpose` are optional for
backward compatibility; the public form does not request age.

### `GET /auth/verify?token=<one-time-token-from-email>`
Marks the account verified and returns the first API key (`scl_…`).

### `POST /auth/login`
```json
{ "email": "…", "password": "…" }
```
Returns a bearer JWT for non-browser clients. Browser clients use
`POST /auth/session/login`, which establishes an HttpOnly cookie without
exposing the JWT to JavaScript.

Login, registration, and password-reset attempts are rate-limited by both
client IP and a keyed digest of the normalized account identifier. Repeated
login failures trigger an exponential `Retry-After` backoff.

### `POST /auth/password-reset/request`
```json
{ "email": "you@example.com" }
```
Always returns the same response. Eligible password accounts receive a
single-use reset link that expires after 30 minutes.

### `POST /auth/password-reset/confirm`
```json
{ "token": "<one-time-token-from-email>", "new_password": "…" }
```
Consumes the hashed reset grant, changes the password, and invalidates every
previously issued JWT session.

### `POST /auth/sessions/revoke-all`
Requires a browser session or bearer JWT. Invalidates all browser and bearer
sessions for the user. API keys are unaffected and retain their own explicit
revocation lifecycle.

### `GET /auth/me`
Returns the authenticated user.

### `GET /auth/me/export`
Returns a downloadable, `no-store` JSON copy of the authenticated user's
profile, API-key metadata, Ask history, bookmarks, token lifecycle metadata,
and security events. Password hashes, API-key hashes, reset/verification token
material, raw IP hashes, and user-agent hashes are never exported.

### `DELETE /auth/me`
```json
{
  "confirmation": "DELETE",
  "email": "you@example.com",
  "current_password": "required for password-capable accounts"
}
```
Permanently deletes the current non-admin account and its API keys, Ask
history, bookmarks, and authentication grants. The exact account email and
current password (when one exists) are required. Direct user references are
removed from the retained pseudonymous security audit event. Administrator
accounts must be demoted before using this endpoint.

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
Combines Google `text-embedding-005` / Vertex ANN candidates with PostgreSQL
full-text candidates, applies Reciprocal Rank Fusion and a deterministic
query-coverage reranker, then joins authoritative paper/chunk rows. A Vertex
timeout, exhausted retry, or open circuit degrades to PostgreSQL lexical
retrieval. Each hit carries a `relevance_score` float in `[0, 1]`.

### `POST /ask`
```json
{ "query": "What is the role of pressure in high-Tc hydrides?" }
```
Runs the same hybrid candidate strategy, keeps at most one source per paper,
and feeds bounded untrusted-source JSON into Gemini with a separate system
instruction that requires inline `[n]` citations. The response includes
`citation_valid` and machine-readable `citation_warnings`. Invalid source
numbers are removed. A Gemini timeout, exhausted retry, or open circuit returns
cited extractive snippets instead of failing the entire request.

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
