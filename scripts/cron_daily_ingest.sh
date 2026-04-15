#!/usr/bin/env bash
# Nightly SCLib ingest + stats refresh.
#
# Install on VPS2 as root (or under a dedicated user with docker group):
#
#   sudo ln -s /opt/sclib/scripts/cron_daily_ingest.sh \
#              /etc/cron.daily/sclib-ingest
#
# or, with an explicit schedule, add to root's crontab:
#
#   # m h  dom mon dow   command
#   17 3   *   *   *     /opt/sclib/scripts/cron_daily_ingest.sh
#
# The script is intentionally small and dependency-free — all the heavy
# lifting lives in the `ingestion` container and the `stats_refresh`
# service. Its only jobs are:
#
#   1. run `sclib-ingest --mode incremental` inside a one-shot ingestion
#      container (profiles=["tools"] so it never auto-starts)
#   2. if that partial-succeeds (exit 0, threshold met) OR fails with a
#      recoverable error, fire a `--mode retry` pass to drain the GCS
#      failure pool
#   3. refresh the dashboard stats cache via the api container so the
#      landing page / GET /stats reflects today's numbers on next hit
#   4. append a timestamped log line to /var/log/sclib/cron.log
#
# Failures DO NOT wake the retry pass off a 2+ exit (hard crash) —
# we'd rather a human see the stack trace in logs than paper over it.
set -Eeuo pipefail

# ---- Config --------------------------------------------------------------

SCLIB_ROOT="${SCLIB_ROOT:-/opt/sclib}"
LOG_DIR="${SCLIB_LOG_DIR:-/var/log/sclib}"
LOG_FILE="${LOG_DIR}/cron.log"

COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml)

# Allow overriding in an env file next to the compose file so secrets
# and tunables live in one place.
if [[ -f "${SCLIB_ROOT}/.env.cron" ]]; then
    # shellcheck disable=SC1091
    source "${SCLIB_ROOT}/.env.cron"
fi

mkdir -p "${LOG_DIR}"

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "${LOG_FILE}"
}

on_error() {
    local exit_code=$?
    log "FAIL cron_daily_ingest exit=${exit_code} at line ${BASH_LINENO[0]}"
    exit "${exit_code}"
}
trap on_error ERR

cd "${SCLIB_ROOT}"

# ---- 1. Incremental ingest ----------------------------------------------

log "START cron_daily_ingest"
log "step 1/3: incremental ingest"

# --rm so each run is a clean container. `|| true` is deliberate: a
# partial failure (below failure_success_threshold) returns non-zero
# but we still want the retry pass + stats refresh to run. We capture
# the exit code so the final log line reflects it.
set +e
docker compose "${COMPOSE_FILES[@]}" run --rm ingestion \
    sclib-ingest --mode incremental 2>&1 | tee -a "${LOG_FILE}"
ingest_rc=${PIPESTATUS[0]}
set -e
log "incremental ingest exit=${ingest_rc}"

# ---- 2. Retry pass (drain failure pool) ---------------------------------

log "step 2/3: retry pass (drain failure pool)"
set +e
docker compose "${COMPOSE_FILES[@]}" run --rm ingestion \
    sclib-ingest --mode retry --limit 20 2>&1 | tee -a "${LOG_FILE}"
retry_rc=${PIPESTATUS[0]}
set -e
log "retry pass exit=${retry_rc}"

# ---- 3. Refresh stats cache ---------------------------------------------
#
# Call POST /stats/refresh on the internal loopback (127.0.0.1:8000)
# with the X-Internal-Key header. Never touches Nginx or the public
# internet — the api container publishes only to 127.0.0.1:8000 and
# the endpoint is gated by INTERNAL_API_KEY loaded from .env.

log "step 3/3: refresh dashboard stats cache"
if [[ -z "${INTERNAL_API_KEY:-}" ]]; then
    # Fall back to sourcing the compose .env so operators don't have to
    # duplicate the secret in .env.cron.
    if [[ -f "${SCLIB_ROOT}/.env" ]]; then
        # shellcheck disable=SC1091
        set -a && source "${SCLIB_ROOT}/.env" && set +a
    fi
fi

if [[ -z "${INTERNAL_API_KEY:-}" ]]; then
    log "WARN INTERNAL_API_KEY unset — skipping stats refresh"
else
    curl --fail --silent --show-error \
        -X POST "http://127.0.0.1:8000/v1/stats/refresh" \
        -H "X-Internal-Key: ${INTERNAL_API_KEY}" \
        2>&1 | tee -a "${LOG_FILE}" || log "WARN stats refresh curl failed"
fi

log "DONE cron_daily_ingest ingest_rc=${ingest_rc} retry_rc=${retry_rc}"
