#!/usr/bin/env bash
# Hourly SCLib incremental ingest + stats refresh.
#
# Triggered by the systemd timer at /etc/systemd/system/sclib-ingest.timer.
# Cadence: every hour at :10. Runs are serialized via flock — if the
# previous hour's run is still going, this hour is skipped (the next
# tick picks up the harvest cursor from GCS harvest_state.json, so
# nothing is lost).
#
# Sibling of scripts/cron_daily_ingest.sh, which handles the slower
# nightly maintenance (retry drain / materials aggregation / postgres
# backup). Keep this script fast (<15 min) and idempotent.
#
# Steps:
#   1. sclib-ingest --mode incremental --limit 200  (arXiv → Postgres + VS)
#   2. POST /stats/refresh                           (update dashboard counters)
#   3. update /var/lib/sclib/consecutive_failures    (alert on 3-in-a-row)
#   4. append a line to /var/log/sclib/hourly.log
#
# Exit codes:
#   0  everything OK
#   1  ingest returned a soft failure (partial success below threshold)
#   2  ingest hard-crashed (stack trace in logs, counter bumped)
#   99 another run is in progress (flock), skipped
#
# On 3 consecutive non-zero exits (code 1 or 2) we send an email to
# info@jzis.org via Resend and reset the counter. Single/two-off
# failures are tolerated — arXiv OAI-PMH is intermittent.

set -Eeuo pipefail

# ---- Config --------------------------------------------------------------

SCLIB_ROOT="${SCLIB_ROOT:-/opt/SCLib_JZIS}"
LOG_DIR="${SCLIB_LOG_DIR:-/var/log/sclib}"
LOG_FILE="${LOG_DIR}/hourly.log"
STATE_DIR="${SCLIB_STATE_DIR:-/var/lib/sclib}"
FAILURE_COUNTER="${STATE_DIR}/consecutive_failures"
LOCKFILE="${SCLIB_LOCKFILE:-/var/lock/sclib-hourly-ingest.lock}"

COMPOSE_FILES=(-f docker-compose.yml)
# NOTE: We intentionally *do not* pick up docker-compose.prod.yml here.
# That override mounts /root/.config/gcloud/application_default_credentials.json
# over /credentials/gcp-sa.json — an authorized_user ADC whose refresh
# token expires every ~7 days and cannot be renewed non-interactively.
# The production deployment uses a real service-account key at
# ./credentials/gcp-sa.json (see docker-compose.yml), so skipping the
# prod override keeps ingest auth stable.
# Opt in via SCLIB_USE_PROD_OVERRIDE=1 only if you know the ADC is fresh.
if [[ "${SCLIB_USE_PROD_OVERRIDE:-}" == "1" && -f "${SCLIB_ROOT}/docker-compose.prod.yml" ]]; then
    COMPOSE_FILES+=(-f docker-compose.prod.yml)
fi

ALERT_EMAIL="${SCLIB_ALERT_EMAIL:-info@jzis.org}"
ALERT_FROM="${SCLIB_ALERT_FROM:-alerts@jzis.org}"
ALERT_THRESHOLD="${SCLIB_ALERT_THRESHOLD:-3}"
INGEST_LIMIT="${SCLIB_INGEST_LIMIT:-200}"

mkdir -p "${LOG_DIR}" "${STATE_DIR}"

# ---- Single-instance lock -----------------------------------------------
#
# Non-blocking: if a run is already going, exit 99 immediately. systemd
# logs this distinct exit code so "skipped" runs are visible in
# `systemctl status`.
if [[ "${SCLIB_LOCKED:-}" != "1" ]]; then
    export SCLIB_LOCKED=1
    exec flock --nonblock --conflict-exit-code 99 "${LOCKFILE}" "$0" "$@"
fi

# ---- Logging helpers ----------------------------------------------------

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "${LOG_FILE}"
}

on_error() {
    local exit_code=$?
    log "FAIL hourly_ingest unexpected exit=${exit_code} at line ${BASH_LINENO[0]}"
    bump_failure "unexpected exit ${exit_code} at line ${BASH_LINENO[0]}"
    exit "${exit_code}"
}
trap on_error ERR

# ---- Failure counter + email alert --------------------------------------

bump_failure() {
    local reason="$1"
    local count
    count=$(( $(cat "${FAILURE_COUNTER}" 2>/dev/null || echo 0) + 1 ))
    echo "${count}" > "${FAILURE_COUNTER}"
    log "consecutive_failures=${count} (threshold=${ALERT_THRESHOLD}) reason='${reason}'"

    if (( count >= ALERT_THRESHOLD )); then
        send_alert "${count}" "${reason}"
        # Reset so we don't spam every hour after the threshold
        echo 0 > "${FAILURE_COUNTER}"
    fi
}

reset_failure() {
    echo 0 > "${FAILURE_COUNTER}"
}

send_alert() {
    local count="$1"
    local reason="$2"

    # Load RESEND_API_KEY from .env if not already in env
    if [[ -z "${RESEND_API_KEY:-}" && -f "${SCLIB_ROOT}/.env" ]]; then
        # shellcheck disable=SC1091
        set -a && source "${SCLIB_ROOT}/.env" && set +a
    fi

    if [[ -z "${RESEND_API_KEY:-}" ]]; then
        log "WARN RESEND_API_KEY unset — skipping email alert"
        return
    fi

    local tail_lines
    tail_lines=$(tail -n 80 "${LOG_FILE}" | sed 's/"/\\"/g' | tr '\n' '|' || true)
    local host
    host=$(hostname)
    local subject="[SCLib] Hourly ingest failed ${count}x on ${host}"
    local body
    body=$(cat <<EOF
The SCLib hourly ingest on ${host} has failed ${count} times in a row.

Reason: ${reason}

Last ~80 log lines (pipe-separated):
${tail_lines}

Triage:
  ssh root@${host}
  systemctl status sclib-ingest.service
  journalctl -u sclib-ingest.service -n 200
  tail -n 200 ${LOG_FILE}
  psql -U sclib sclib -c "SELECT id, started_at, status, mode, papers_succeeded, papers_failed, error_message FROM ingest_runs ORDER BY started_at DESC LIMIT 10;"
EOF
)
    # Resend expects JSON; build the payload with jq so newlines/quotes
    # in the body are escaped correctly.
    local payload
    payload=$(jq -n --arg from "${ALERT_FROM}" --arg to "${ALERT_EMAIL}" \
                    --arg subject "${subject}" --arg text "${body}" \
                    '{from:$from, to:[$to], subject:$subject, text:$text}')

    if curl --fail --silent --show-error --max-time 15 \
            -X POST "https://api.resend.com/emails" \
            -H "Authorization: Bearer ${RESEND_API_KEY}" \
            -H "Content-Type: application/json" \
            -d "${payload}" >/dev/null 2>>"${LOG_FILE}"; then
        log "alert email sent to ${ALERT_EMAIL}"
    else
        log "WARN Resend email send failed"
    fi
}

# ---- Stale-row reconciliation -------------------------------------------
#
# If a prior crashed run left an ingest_runs row with status='running'
# but started_at is more than 30 minutes ago, mark it 'failed' before
# we insert our own row. This keeps the admin view readable.

reconcile_stale_runs() {
    local sql="UPDATE ingest_runs
               SET status='failed',
                   finished_at=now(),
                   error_message=COALESCE(error_message, 'reconciled: crashed, no finish_ingest_run called')
               WHERE status='running'
                 AND started_at < now() - INTERVAL '30 minutes';"
    if docker exec sclib-postgres psql -U sclib -d sclib -c "${sql}" >/dev/null 2>&1; then
        :
    else
        log "WARN could not reconcile stale ingest_runs rows"
    fi
}

# ---- Main -----------------------------------------------------------------

cd "${SCLIB_ROOT}"

log "START hourly_ingest"
reconcile_stale_runs

# Step 1: incremental ingest
log "step 1/2: incremental ingest (limit=${INGEST_LIMIT})"
set +e
docker compose "${COMPOSE_FILES[@]}" run --rm ingestion \
    sclib-ingest --mode incremental --limit "${INGEST_LIMIT}" \
    2>&1 | tee -a "${LOG_FILE}"
ingest_rc=${PIPESTATUS[0]}
set -e
log "incremental ingest exit=${ingest_rc}"

if (( ingest_rc != 0 && ingest_rc != 1 )); then
    # Hard crash (rc >= 2) — pipeline.py returns 2 for unhandled
    # exceptions. Pipeline already recorded the failed row in
    # ingest_runs; just bump the counter + possibly alert.
    bump_failure "ingest exit ${ingest_rc} (hard crash)"
    exit "${ingest_rc}"
fi

# Step 2: refresh dashboard stats cache so the landing page + /stats
# reflect new rows immediately. The INTERNAL_API_KEY gate means the
# endpoint stays safe even if Nginx ever exposes it externally.

log "step 2/2: refresh dashboard stats cache"
if [[ -z "${INTERNAL_API_KEY:-}" && -f "${SCLIB_ROOT}/.env" ]]; then
    # shellcheck disable=SC1091
    set -a && source "${SCLIB_ROOT}/.env" && set +a
fi

if [[ -z "${INTERNAL_API_KEY:-}" ]]; then
    log "WARN INTERNAL_API_KEY unset — skipping stats refresh"
    stats_rc=0
else
    set +e
    curl --fail --silent --show-error --max-time 30 \
         -X POST "http://127.0.0.1:8000/v1/stats/refresh" \
         -H "X-Internal-Key: ${INTERNAL_API_KEY}" \
         -o /dev/null 2>>"${LOG_FILE}"
    stats_rc=$?
    set -e
    log "stats refresh exit=${stats_rc}"
fi

# Resolve final exit code + counter bookkeeping.
if (( ingest_rc == 0 && stats_rc == 0 )); then
    reset_failure
    log "DONE hourly_ingest ok"
    exit 0
elif (( ingest_rc == 1 )); then
    bump_failure "ingest partial-failure (below threshold)"
    log "DONE hourly_ingest soft_failure ingest_rc=1"
    exit 1
else
    bump_failure "stats refresh exit ${stats_rc}"
    log "DONE hourly_ingest stats_refresh_failed stats_rc=${stats_rc}"
    exit 1
fi
