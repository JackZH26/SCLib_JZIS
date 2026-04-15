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
- Either a service account JSON **or** host ADC at
  `/root/.config/gcloud/application_default_credentials.json` (ADC
  option A is preferred — see `docker-compose.prod.yml`)

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
