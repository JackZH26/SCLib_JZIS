# SCLib_JZIS Deployment Guide

Production target: **VPS2** (`72.62.251.29`), alongside existing
`jzis.org` and `asrp.jzis.org` sites. Never break them.

## Topology

```
  Internet ─┐
            │  443
            ▼
        Nginx (host)
            │
            ├── jzis.org          → /etc/nginx/sites-available/jzis.org
            │       └── /sclib    → 127.0.0.1:3100  (Next.js frontend)
            │
            ├── asrp.jzis.org     → 127.0.0.1:3000  (existing site — untouched)
            │
            └── api.jzis.org      → /etc/nginx/conf.d/sclib.conf
                    └── /sclib/   → 127.0.0.1:8000/ (FastAPI, path-stripped)

  docker-compose (bound to 127.0.0.1 only):
     sclib-frontend   :3100 → 3000 (Next.js standalone)
     sclib-api        :8000
     sclib-postgres   (internal only)
     sclib-redis      (internal only)
     sclib-ingestion  (profile: tools, one-shot)
```

## Prereqs

- Ubuntu 22.04+ on VPS2, Nginx already live
- Docker + compose plugin
- DNS `A api.jzis.org → 72.62.251.29`
- GCP project `jzis-sclib` with Vertex AI + Matching Engine endpoint
- **Service account `sclib-api@jzis-sclib.iam.gserviceaccount.com`**
  with `roles/aiplatform.user` and `roles/storage.objectUser`.
  The API container authenticates as this SA via **impersonation**
  — we never create or ship a JSON key (org policy forbids it and
  SA keys are the current anti-pattern per Google's own docs).
- Host ADC at `/root/.config/gcloud/application_default_credentials.json`
  wrapped as an `impersonated_service_account` credential. See the
  "SA impersonation setup" section below.

## Bootstrap

```bash
ssh root@72.62.251.29
git clone https://github.com/JackZH26/SCLib_JZIS.git /opt/SCLib_JZIS
cd /opt/SCLib_JZIS
bash scripts/setup_vps2.sh
```

The script is idempotent: it installs Docker if missing, clones/pulls
the repo, templates `.env`, runs `certbot --nginx -d api.jzis.org`,
and installs `nginx/sclib.conf` into `/etc/nginx/conf.d/`.

## Manual steps after bootstrap

1. **Edit `/opt/SCLib_JZIS/.env`** — set
   `DB_PASSWORD`, `JWT_SECRET`, `RESEND_API_KEY`,
   `VERTEX_AI_INDEX_ENDPOINT`, `INTERNAL_API_KEY`.
2. **Install the frontend proxy block** into
   `/etc/nginx/sites-available/jzis.org` — copy the `location /sclib`
   stanza from the comment at the top of `nginx/sclib.conf`. Note it
   points at **port 3100**, not 3000.
3. `nginx -t && systemctl reload nginx`
4. Start the stack:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
   ```
5. Run Alembic migrations:
   ```bash
   docker compose exec api alembic upgrade head
   ```
6. Smoke-test:
   ```bash
   curl -s http://127.0.0.1:8000/v1/stats | jq .
   curl -s https://api.jzis.org/sclib/v1/stats | jq .
   curl -sI https://jzis.org/sclib/ | head -1
   ```

## SA impersonation setup (GCP auth)

Org policy `iam.disableServiceAccountKeyCreation` prevents us from
shipping a JSON key, which is also the current Google-recommended
stance. The API container instead runs as `sclib-api@jzis-sclib...`
via **impersonation**: the host ADC is a wrapped credential that
exchanges a human operator's OAuth refresh token for a short-lived
(1h) SA access token on every API call.

### One-time GCP side
Run from any machine that can `gcloud` as a project owner:

```bash
PROJECT=jzis-sclib
SA_EMAIL=sclib-api@${PROJECT}.iam.gserviceaccount.com
ME=jack@jzis.org   # or whichever human owns the source ADC

# 1. Create the SA (idempotent; 409 if it already exists)
gcloud iam service-accounts create sclib-api \
    --display-name="SCLib API runtime" --project=$PROJECT

# 2. Runtime roles
gcloud projects add-iam-policy-binding $PROJECT \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/aiplatform.user"
gcloud projects add-iam-policy-binding $PROJECT \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/storage.objectUser"

# 3. Human impersonator (resource-level binding — org policies
#    typically don't block tokenCreator at this scope)
gcloud iam service-accounts add-iam-policy-binding $SA_EMAIL \
    --member="user:$ME" \
    --role="roles/iam.serviceAccountTokenCreator" \
    --project=$PROJECT

# 4. Enable IAM Credentials API (required for generateAccessToken)
gcloud services enable iamcredentials.googleapis.com --project=$PROJECT
```

### One-time VPS2 side
The host already has a plain `authorized_user` ADC from a previous
`gcloud auth application-default login`. Rewrite it in place as an
impersonated credential via the helper script:

```bash
ssh root@72.62.251.29
python3 /opt/SCLib_JZIS/scripts/wrap_adc_impersonated.py
docker restart sclib-api
```

The script keeps a timestamped backup of the original user ADC next
to the file (so you can roll back by copying back), writes the new
`impersonated_service_account` form, and relaxes the mode to `0644`
so uid 1001 inside the api container can read it. Re-running
`gcloud auth application-default login` by hand will **reset** the
file back to user form and reset mode to `0600`; always re-run the
wrap script after any manual ADC refresh.

### Verify

```bash
# gcloud fetches an impersonated token automatically
TOK=$(gcloud auth application-default print-access-token)
# tokeninfo will show NO email (SA tokens don't carry one)
curl -s "https://oauth2.googleapis.com/tokeninfo?access_token=$TOK"

# Real upstream call
docker exec sclib-redis redis-cli --scan --pattern "guest_quota:*" \
    | xargs -r -I{} docker exec sclib-redis redis-cli DEL {}
curl -fsS -X POST http://127.0.0.1:8000/v1/search \
    -H "content-type: application/json" \
    -d '{"query":"iron-based superconductor","top_k":1}' | jq .total
```

## Data bootstrap

### Papers (Phase 2 smoke)
```bash
docker compose run --rm ingestion \
    sclib-ingest --mode smoke --limit 30
```
Reads from arXiv OAI-PMH, writes LaTeX sources to GCS, parses/chunks/
embeds, upserts into Postgres + Vertex VS. Phase 2 acceptance: 30/30
papers ingested, 0 dead.

### Materials (NIMS SuperCon)
```bash
docker compose run --rm -v /root/data:/data ingestion \
    sclib-import-nims --csv /data/supercon.csv
```
Tolerant to column naming drift across NIMS releases. Supports
`--dry-run` and `--limit N` for debugging.

### First stats refresh
```bash
curl -sX POST http://127.0.0.1:8000/v1/stats/refresh \
     -H "X-Internal-Key: $(grep ^INTERNAL_API_KEY .env | cut -d= -f2)"
```

## Nightly automation

Install the cron wrapper:
```bash
ln -s /opt/SCLib_JZIS/scripts/cron_daily_ingest.sh \
      /etc/cron.daily/sclib-ingest
```
or add to root's crontab:
```
17 3 * * * /opt/SCLib_JZIS/scripts/cron_daily_ingest.sh
```

The wrapper runs, in order:
1. `sclib-ingest --mode incremental` (one-shot container)
2. `sclib-ingest --mode retry --limit 20` (drain the GCS failure pool)
3. `POST /stats/refresh` over loopback (using `INTERNAL_API_KEY`)

Each step writes a timestamped line to `/var/log/sclib/cron.log` so
operators can `tail -f` during the first few nights.

## Observability

- `docker compose logs -f api frontend`
- `docker compose ps` — all 4 services should show `healthy`
- `GET /stats.updated_at` tells you whether the cron ran
- GCS `metadata/failed_papers.json` — the failure pool; non-empty is
  fine, the retry pass drains it; only intervene if the same paper IDs
  persist across runs with `status: dead`

## Rollback

Everything is Docker Compose, so rollback is:
```bash
git -C /opt/SCLib_JZIS checkout <previous-commit>
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
Postgres data lives in the `postgres_data` named volume and survives
image rebuilds. Alembic migrations are forward-only — if a migration
needs reverting, write a new migration.
