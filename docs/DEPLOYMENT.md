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
- Three workload-scoped service accounts and an approved OIDC workload identity
  provider/agent, as defined in [`WORKLOAD_IDENTITY.md`](WORKLOAD_IDENTITY.md).
  Production rejects service-account keys and human OAuth/ADC refresh tokens.

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
   stanza from the comment at the top of `nginx/sclib.conf`. It points at
   **port 3100**, not 3000.
3. Preserve the main site's existing root `robots.txt` and append this line
   to its content: `Sitemap: https://jzis.org/sclib/sitemap.xml`. Do not
   replace or proxy the root file: it may contain rules for other JZIS sites.
4. `nginx -t && systemctl reload nginx`
5. Start the stack:
   ```bash
   # Use the three signed digests from one successful Release images run.
   export SCLIB_FRONTEND_IMAGE='ghcr.io/jackzh26/sclib-frontend@sha256:<digest>'
   export SCLIB_API_IMAGE='ghcr.io/jackzh26/sclib-api@sha256:<digest>'
   export SCLIB_INGESTION_IMAGE='ghcr.io/jackzh26/sclib-ingestion@sha256:<digest>'
   docker compose --profile observability \
     -f docker-compose.yml -f docker-compose.prod.yml up -d --no-build
   ```
6. Run Alembic migrations:
   ```bash
   docker compose exec api alembic upgrade head
   ```
7. Smoke-test:
   ```bash
   curl -s http://127.0.0.1:8000/v1/stats | jq .
   curl -s https://api.jzis.org/sclib/v1/stats | jq .
   curl -sI https://jzis.org/sclib/ | head -1
   curl -fsS https://jzis.org/robots.txt | grep 'Sitemap: https://jzis.org/sclib/sitemap.xml'
   curl -fsS https://jzis.org/sclib/sitemap.xml | grep '<sitemapindex'
   ```

## Production Google identity

Follow [`WORKLOAD_IDENTITY.md`](WORKLOAD_IDENTITY.md) to provision the external
OIDC provider, three service accounts, external-account configurations, and
rotating subject-token files. Validate all identities before enabling the first
signed-image deployment. Do not copy or transform a human ADC onto VPS2.

Production Compose mounts API and ingestion identity directories separately;
the backup process uses a third identity through
`CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE`. A credential for one workload cannot
start another workload because the validator requires the exact target service
account.

## GitHub Actions production delivery

The production path is deliberately split into three workflows:

1. `Test` validates the exact `main` revision.
2. `Release images` builds once, scans, signs, and records immutable image
   digests only after that test run succeeds.
3. `Deploy to VPS2` verifies that successful release run, checks the 30-day
   error budget and workload identities, creates a database backup, verifies
   the image signatures, migrates, and starts the recorded digests with
   `--no-build`.

Configure these GitHub Actions repository secrets. Keeping the connection
values out of workflow source also lets the VPS move without a code change.

| Secret | Production value |
|---|---|
| `VPS2_HOST` | VPS2 address or trusted DNS name |
| `VPS2_USER` | Dedicated deployment login (currently `root`) |
| `VPS2_DEPLOY_PATH` | `/opt/SCLib_JZIS` |
| `VPS2_SSH_KEY` | Private half of the dedicated Actions key |
| `VPS2_HOST_FINGERPRINT` | Trusted host key fingerprint, for example `SHA256:...` |

Generate a key only for Actions on an administrator workstation. Do not reuse a
personal key, commit the private key, or leave a copy of it on VPS2.

```bash
ssh-keygen -t ed25519 -a 100 \
  -f ~/.ssh/sclib_github_actions -C sclib-github-actions
```

Append the public key to the deployment login's `~/.ssh/authorized_keys` with
forwarding, PTY, and user startup disabled:

```text
no-agent-forwarding,no-port-forwarding,no-pty,no-user-rc ssh-ed25519 AAAA... sclib-github-actions
```

Obtain the server fingerprint over an already trusted administrative SSH
connection; do not trust a first-seen fingerprint copied from an unverified
network scan:

```bash
ssh root@72.62.251.29 \
  "ssh-keygen -l -E sha256 -f /etc/ssh/ssh_host_ed25519_key.pub"
```

Create a GitHub environment named `production` and restrict its deployment
branch rule to the exact `main` branch. This preserves automatic delivery after
a successful `main` test run; organizations that require a manual change window
may additionally enable required reviewers. The workflows pin every third-party
Action to a full commit SHA and ask the SSH Action to compare the server key
with `VPS2_HOST_FINGERPRINT`; they do not use `StrictHostKeyChecking=no`,
destructive Git resets, or server-side image builds.

A push to `main` automatically enters the chain above. To redeploy an existing
release, run `Deploy to VPS2` manually and provide the numeric run ID of a
successful `Release images` workflow. The deploy workflow retrieves that run
through the GitHub API and rejects a run from another workflow, branch, event,
or failed conclusion. Manual deployment therefore cannot bypass tests, scans,
signatures, or immutable digests.

Before the first automated deployment, complete all three workload-identity
credentials, backup configuration and restore drill, and the monitoring sample
required by [`OBSERVABILITY_SLO.md`](OBSERVABILITY_SLO.md). The deployment gate
fails closed if any prerequisite is missing; SSH connectivity alone is not a
production-readiness signal.

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

The loopback-only Prometheus, Alertmanager, and Grafana services are enabled
with the `observability` Compose profile. Set `GRAFANA_ADMIN_PASSWORD`, configure
an approved Alertmanager notification receiver, and follow
[`OBSERVABILITY_SLO.md`](OBSERVABILITY_SLO.md) for dashboard access, SLOs,
release gates, and alert runbooks.

- `docker compose --profile observability logs -f api frontend prometheus`
- `docker compose --profile observability ps` — application and monitoring
  services should be running; API/frontend/PostgreSQL/Redis should be healthy
- `sclib_pipeline_last_run_age_seconds` reports operational ingest freshness;
  `GET /stats.last_ingest_at` and `sclib_dataset_age_seconds` report content age
- GCS `metadata/failed_papers.json` — the failure pool; non-empty is fine, the
  retry pass drains it; intervene if the same IDs persist with `status: dead`

## Rollback

Application releases use signed, immutable image digests. Select the three
digests from a previously successful `Release images` run, verify them with the
command in `SUPPLY_CHAIN_SECURITY.md`, then export them before restarting:

```bash
export SCLIB_FRONTEND_IMAGE='ghcr.io/jackzh26/sclib-frontend@sha256:<digest>'
export SCLIB_API_IMAGE='ghcr.io/jackzh26/sclib-api@sha256:<digest>'
export SCLIB_INGESTION_IMAGE='ghcr.io/jackzh26/sclib-ingestion@sha256:<digest>'
docker compose --profile observability \
  -f docker-compose.yml -f docker-compose.prod.yml \
  up -d --no-build --wait
```
Postgres data lives in the `postgres_data` named volume and survives
image replacement. Alembic migrations are forward-only — if a migration
needs reverting, write a new migration.
