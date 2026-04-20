#!/usr/bin/env bash
# Daily SCLib materials aggregate.
#
# Triggered by the systemd timer at /etc/systemd/system/sclib-aggregate.timer.
# Cadence: every day at 03:10 UTC (11:10 UTC+8).
#
# This script *does not touch arXiv ingest*. The user's 瓦力 cron
# handles that; our sole job is to roll the per-paper NER output
# (papers.materials_extracted JSONB) into the flat `materials` table
# columns, and refresh the dashboard stats cache afterwards.
#
# Steps:
#   1. sclib-ingest --mode aggregate-materials
#      (reads papers → weighted-vote → upserts materials rows)
#   2. POST /stats/refresh
#      (so the homepage count reflects the fresh aggregate)
#
# Exit codes mirror the hourly script:
#   0  everything OK
#   1  aggregate or stats-refresh soft-failure
#   2  aggregate hard-crashed
#   99 another run is in progress (flock), skipped
#
# 3 consecutive non-zero runs fire an email to info@jzis.org via Resend.

set -Eeuo pipefail

# ---- Config --------------------------------------------------------------

SCLIB_ROOT="${SCLIB_ROOT:-/opt/SCLib_JZIS}"
LOG_DIR="${SCLIB_LOG_DIR:-/var/log/sclib}"
LOG_FILE="${LOG_DIR}/aggregate.log"
STATE_DIR="${SCLIB_STATE_DIR:-/var/lib/sclib}"
FAILURE_COUNTER="${STATE_DIR}/aggregate_consecutive_failures"
LOCKFILE="${SCLIB_LOCKFILE:-/var/lock/sclib-aggregate.lock}"

COMPOSE_FILES=(-f docker-compose.yml)

ALERT_EMAIL="${SCLIB_ALERT_EMAIL:-info@jzis.org}"
ALERT_FROM="${SCLIB_ALERT_FROM:-alerts@jzis.org}"
ALERT_THRESHOLD="${SCLIB_ALERT_THRESHOLD:-3}"

mkdir -p "${LOG_DIR}" "${STATE_DIR}"

# ---- Single-instance lock -----------------------------------------------

if [[ "${SCLIB_AGG_LOCKED:-}" != "1" ]]; then
    export SCLIB_AGG_LOCKED=1
    exec flock --nonblock --conflict-exit-code 99 "${LOCKFILE}" "$0" "$@"
fi

# ---- Logging helpers ----------------------------------------------------

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "${LOG_FILE}"
}

# Pluck a single KEY=... line out of .env without sourcing it.
# Safely handles values containing spaces, '<', quotes.
_env_get() {
    local key="$1" file="$2"
    local line value
    line=$(grep -E "^${key}=" "${file}" | head -1) || true
    [[ -z "${line}" ]] && return 0
    value="${line#${key}=}"
    if [[ "${value}" =~ ^\".*\"$ ]]; then value="${value:1:-1}"; fi
    if [[ "${value}" =~ ^\'.*\'$ ]]; then value="${value:1:-1}"; fi
    printf '%s' "${value}"
}

on_error() {
    local exit_code=$?
    log "FAIL aggregate unexpected exit=${exit_code} at line ${BASH_LINENO[0]}"
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
    log "aggregate_consecutive_failures=${count} (threshold=${ALERT_THRESHOLD}) reason='${reason}'"

    if (( count >= ALERT_THRESHOLD )); then
        send_alert "${count}" "${reason}"
        echo 0 > "${FAILURE_COUNTER}"
    fi
}

reset_failure() {
    echo 0 > "${FAILURE_COUNTER}"
}

send_alert() {
    local count="$1" reason="$2"

    if [[ -z "${RESEND_API_KEY:-}" && -f "${SCLIB_ROOT}/.env" ]]; then
        RESEND_API_KEY=$(_env_get RESEND_API_KEY "${SCLIB_ROOT}/.env")
        export RESEND_API_KEY
    fi

    if [[ -z "${RESEND_API_KEY:-}" ]]; then
        log "WARN RESEND_API_KEY unset — skipping email alert"
        return
    fi

    local tail_lines host subject body payload
    tail_lines=$(tail -n 60 "${LOG_FILE}" | sed 's/"/\\"/g' | tr '\n' '|' || true)
    host=$(hostname)
    subject="[SCLib] Daily aggregate failed ${count}x on ${host}"
    body=$(cat <<EOF
The SCLib daily materials-aggregate on ${host} has failed ${count} times in a row.

Reason: ${reason}

Last ~60 log lines (pipe-separated):
${tail_lines}

Triage:
  ssh root@${host}
  systemctl status sclib-aggregate.service
  journalctl -u sclib-aggregate.service -n 200
  tail -n 200 ${LOG_FILE}
  psql -U sclib sclib -c "SELECT COUNT(*), COUNT(tc_max), COUNT(pairing_symmetry) FROM materials;"
EOF
)
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

# ---- Main -----------------------------------------------------------------

cd "${SCLIB_ROOT}"

log "START daily_aggregate"

# Step 1: aggregate
log "step 1/2: sclib-ingest --mode aggregate-materials"
set +e
docker compose "${COMPOSE_FILES[@]}" run --rm ingestion \
    sclib-ingest --mode aggregate-materials 2>&1 | tee -a "${LOG_FILE}"
agg_rc=${PIPESTATUS[0]}
set -e
log "aggregate exit=${agg_rc}"

if (( agg_rc != 0 )); then
    bump_failure "aggregate exit ${agg_rc}"
    exit "${agg_rc}"
fi

# Step 2: refresh dashboard stats cache so the homepage count reflects
# any newly-added materials immediately, rather than waiting for the
# API's next hourly refresh tick.
log "step 2/2: refresh dashboard stats cache"
if [[ -z "${INTERNAL_API_KEY:-}" && -f "${SCLIB_ROOT}/.env" ]]; then
    INTERNAL_API_KEY=$(_env_get INTERNAL_API_KEY "${SCLIB_ROOT}/.env")
    export INTERNAL_API_KEY
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

if (( stats_rc != 0 )); then
    bump_failure "stats refresh exit ${stats_rc}"
    log "DONE daily_aggregate stats_refresh_failed"
    exit 1
fi

reset_failure
log "DONE daily_aggregate ok"
exit 0
