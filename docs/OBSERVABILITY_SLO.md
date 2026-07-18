# SCLib observability, SLOs, and release gate

This runbook covers the private Prometheus, Alertmanager, and Grafana stack,
the service-level objectives used by SCLib, and the response procedure for
every repository-provisioned alert. The monitoring services are optional
Compose profile members and bind to loopback only.

## Start and access the stack

Set a unique `GRAFANA_ADMIN_PASSWORD` in `.env`, then start the profile:

```bash
docker compose --profile observability up -d
docker compose --profile observability ps
curl -fsS http://127.0.0.1:9090/-/ready
curl -fsS http://127.0.0.1:9093/-/ready
```

Use an SSH tunnel rather than opening firewall ports:

```bash
ssh -L 3200:127.0.0.1:3200 -L 9090:127.0.0.1:9090 root@72.62.251.29
```

Grafana is then available at `http://127.0.0.1:3200`. The provisioned
`SCLib Service Overview` dashboard includes traffic, 5xx ratio, p95 latency,
provider outcomes, dependency latency, RAG quality, data age, and consenting
browser Web Vitals. Prometheus retains aggregate time series for 90 days.

The API `/metrics` target is reachable inside the Docker network. Nginx
explicitly returns 404 for the public `/sclib/metrics` path.

## SLO definitions

| SLO | Indicator | 30-day target | Monthly error budget |
|---|---|---:|---:|
| Public read API | Non-5xx responses on stats, version, materials, paper detail, timeline, and discovery | 99.9% | 43m 12s |
| Search and Ask API | Non-5xx responses on search, Ask, and similar-paper routes | 99.5% | 3h 36m |
| Public API latency | p95 request duration for non-generation public routes | < 750 ms | monitored, not a release blocker |
| Search latency | p95 search duration | < 2 s | monitored, not a release blocker |
| Ask latency | p95 Ask duration | < 15 s | monitored, not a release blocker |
| Data freshness | Latest reported ingestion pipeline run age | <= 24 h | 99% of calendar days |
| RAG citations | Answers passing citation validation | >= 95% over 30 minutes | quality alert |

HTTP 4xx responses do not count against availability because they represent a
completed client contract. A provider fallback that returns a grounded 2xx
response remains available but is tracked separately by provider and RAG
metrics. Planned maintenance is not automatically excluded.

## Release gate

Before a production release, run on VPS2:

```bash
python3 scripts/check_error_budget.py \
  --prometheus-url http://127.0.0.1:9090 \
  --window 30d
```

The gate fails closed when Prometheus is unavailable, traffic is insufficient,
the public/AI availability budget is exhausted, or the ingestion pipeline is stale. Use
`--allow-no-data` only for local validation or the initial monitoring bootstrap;
never pass it in the production deployment workflow. A failed gate freezes
feature releases. Emergency security and reliability fixes may proceed only
with an incident record and an explicit rollback owner.

Before enabling the signed-image deployment workflow for the first time, start
the observability profile manually and validate its targets. The automated gate
has no bootstrap bypass: it begins deploying only after the required request
sample and freshness metric exist.

## Notification routing requirement

The repository default routes alerts to the private Alertmanager console and
does not contain third-party credentials. Before enabling the production gate,
the operator must replace or extend `operator-console` in
`ops/alertmanager/alertmanager.yml` with an approved email, Slack, PagerDuty,
or other receiver, reload Alertmanager, and send a test alert. Store receiver
secrets outside Git and mount them read-only. Record the destination and test
date in the operations log.

## Alert runbooks

### API error-budget alert

1. Open the request-rate, error-ratio, and latency panels and isolate the route.
2. Correlate the alert start with the deployed `site_version` from `/v1/version`.
3. Inspect API logs using the response `X-Request-ID`; do not log request bodies.
4. If a release caused the regression, roll back the application image while
   keeping forward-compatible database migrations in place.
5. Keep feature releases frozen until both the 1-hour trend and dependency
   health have recovered.

### Latency alert

Compare route p95 with PostgreSQL/Redis and provider p95 panels. Check in-flight
requests and database pool use. If only a provider is slow, preserve the bounded
timeout/circuit-breaker fallback; do not raise timeouts during the incident.

### Provider alert

Identify `provider` and `outcome`. `timeout` and `circuit_open` indicate the
resilience boundary is protecting the API. Confirm the upstream status, then
validate search/Ask fallbacks and citation warnings. Rotate credentials only if
authentication failures are confirmed.

### Dependency alert

For PostgreSQL, check container health, disk space, locks, connections, and slow
queries. For Redis, check memory, persistence, and latency. Quota and telemetry
failures must not be bypassed by disabling their controls.

### Data-freshness alert

Inspect `scripts/cron_daily_ingest.sh` stage logs, the ingestion container exit
code, `pipeline_state`, and the failed-paper pool. The separate
`sclib_dataset_age_seconds` content metric may legitimately grow when arXiv has
no new records, including weekends. Retry only the failed stage; do not
manually advance either freshness metric.

### Pipeline alert

Use the `stage` label to select the corresponding ingest/audit log. Preserve
the last good published snapshot while rerunning the stage. A failed publication
or stats refresh blocks a release.

### RAG-quality alert

Run the fixed RAG evaluation set, compare lexical/vector retrieval contribution,
and inspect citation warnings. Disable a regressed retrieval path through a
reviewed rollback rather than weakening citation validation.

## Routine operations

- Daily: confirm all scrape targets are up and no critical alert is firing.
- Weekly: review 30-day budget trends, p95 latency, provider fallbacks, and
  browser-error counts.
- Monthly: test one notification and record acknowledgement time.
- Quarterly: restore the dashboard/alert configuration from Git in a clean
  environment alongside the disaster-recovery drill.
