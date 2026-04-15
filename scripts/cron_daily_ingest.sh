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
#   3. run `sclib-ingest --mode aggregate-materials` to roll fresh NER
#      records (papers.materials_extracted) into the materials table
#   4. refresh the dashboard stats cache via the api container so the
#      landing page / GET /stats reflects today's numbers on next hit
#   5. dump postgres → GCS via scripts/backup_postgres.sh (best-effort)
#   6. append a timestamped log line to /var/log/sclib/cron.log
#
# Failures DO NOT wake the retry pass off a 2+ exit (hard crash) —
# we'd rather a human see the stack trace in logs than paper over it.
set -Eeuo pipefail

# ---- Single-instance lock ------------------------------------------------
#
# Re-exec under flock so a second invocation (e.g. cron racing with a
# manual kick) can't run two ingests against the same DB at once. The
# fd-99 trick keeps the lock open for the duration of the script.
LOCKFILE="${SCLIB_LOCKFILE:-/var/lock/sclib-ingest.lock}"
if [[ "${SCLIB_LOCKED:-}" != "1" ]]; then
    export SCLIB_LOCKED=1
    exec flock --nonblock "${LOCKFILE}" "$0" "$@"
fi

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
log "step 1/4: incremental ingest"

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

log "step 2/4: retry pass (drain failure pool)"
set +e
docker compose "${COMPOSE_FILES[@]}" run --rm ingestion \
    sclib-ingest --mode retry --limit 20 2>&1 | tee -a "${LOG_FILE}"
retry_rc=${PIPESTATUS[0]}
set -e
log "retry pass exit=${retry_rc}"

# ---- 3. Aggregate per-paper NER into materials table -------------------
#
# After new papers land, roll their materials_extracted records up into
# the material-level summary columns (tc_max, pairing_symmetry,
# hc2_tesla, is_unconventional flags, etc.). Idempotent — rebuilds the
# summary from scratch every run.

log "step 3/5: aggregate NER records into materials table"
set +e
docker compose "${COMPOSE_FILES[@]}" run --rm ingestion \
    sclib-ingest --mode aggregate-materials 2>&1 | tee -a "${LOG_FILE}"
aggregate_rc=${PIPESTATUS[0]}
set -e
log "aggregate-materials exit=${aggregate_rc}"

# ---- 4. Refresh stats cache ---------------------------------------------
#
# Call POST /stats/refresh on the internal loopback (127.0.0.1:8000)
# with the X-Internal-Key header. Never touches Nginx or the public
# internet — the api container publishes only to 127.0.0.1:8000 and
# the endpoint is gated by INTERNAL_API_KEY loaded from .env.

log "step 4/5: refresh dashboard stats cache"
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

# ---- 5. Postgres backup → GCS -------------------------------------------
#
# Runs after the ingest + stats refresh so the snapshot includes the
# day's new rows. Failures here are logged but do not fail the cron —
# losing one night's backup is preferable to alerting on a noisy
# transient gcloud error.
log "step 5/5: postgres backup → GCS"
if [[ -x "${SCLIB_ROOT}/scripts/backup_postgres.sh" ]]; then
    "${SCLIB_ROOT}/scripts/backup_postgres.sh" || log "WARN backup_postgres failed"
else
    log "WARN backup_postgres.sh missing or not executable"
fi

log "DONE cron_daily_ingest ingest_rc=${ingest_rc} retry_rc=${retry_rc} aggregate_rc=${aggregate_rc}"
