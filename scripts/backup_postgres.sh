#!/usr/bin/env bash
# Nightly Postgres backup → GCS.
#
# Dumps the sclib database from the running postgres container, gzips
# it, uploads to gs://${SCLIB_BACKUP_BUCKET}/postgres/ with a UTC
# timestamp, and prunes anything older than ${SCLIB_BACKUP_RETAIN_DAYS}
# (default 14) from the bucket.
#
# Designed to be invoked by cron_daily_ingest.sh after the ingest pass
# finishes, so the backup captures the day's new rows. Runs are also
# safe to invoke standalone.
#
# Required env (sourced from /opt/sclib/.env via the wrapper):
#   DB_PASSWORD             postgres user password
#   SCLIB_BACKUP_BUCKET     GCS bucket name (no gs:// prefix)
#
# Optional env:
#   SCLIB_ROOT              repo root, default /opt/sclib
#   SCLIB_LOG_DIR           log dir, default /var/log/sclib
#   SCLIB_BACKUP_RETAIN_DAYS  prune horizon, default 14
#
# Requires `gcloud` on PATH and active ADC (the same credential the
# api container uses). On VPS2 that's already provisioned by Phase 0.

set -Eeuo pipefail

SCLIB_ROOT="${SCLIB_ROOT:-/opt/sclib}"
LOG_DIR="${SCLIB_LOG_DIR:-/var/log/sclib}"
LOG_FILE="${LOG_DIR}/backup.log"
RETAIN_DAYS="${SCLIB_BACKUP_RETAIN_DAYS:-14}"

mkdir -p "${LOG_DIR}"

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "${LOG_FILE}"
}

on_error() {
    local rc=$?
    log "FAIL backup_postgres exit=${rc} at line ${BASH_LINENO[0]}"
    exit "${rc}"
}
trap on_error ERR

if [[ -z "${SCLIB_BACKUP_BUCKET:-}" ]]; then
    if [[ -f "${SCLIB_ROOT}/.env" ]]; then
        # shellcheck disable=SC1091
        set -a && source "${SCLIB_ROOT}/.env" && set +a
    fi
fi

if [[ -z "${SCLIB_BACKUP_BUCKET:-}" ]]; then
    log "WARN SCLIB_BACKUP_BUCKET unset — skipping backup"
    exit 0
fi

cd "${SCLIB_ROOT}"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
dumpfile="/tmp/sclib-${ts}.sql.gz"

log "START backup_postgres bucket=${SCLIB_BACKUP_BUCKET}"

# pg_dump from inside the postgres container. -Fc would be smaller and
# allow selective restore but plain SQL is friendlier for ad-hoc grep
# on a recovery host that may not have the same pg_restore version.
docker compose exec -T postgres \
    pg_dump --no-owner --no-acl -U sclib -d sclib \
    | gzip -9 > "${dumpfile}"

bytes="$(stat -c%s "${dumpfile}" 2>/dev/null || stat -f%z "${dumpfile}")"
log "dump complete bytes=${bytes} path=${dumpfile}"

# Upload. gsutil cp is idempotent (overwrite-on-collision) but ts in
# the name guarantees no collisions in practice.
gcloud storage cp "${dumpfile}" "gs://${SCLIB_BACKUP_BUCKET}/postgres/sclib-${ts}.sql.gz" \
    2>&1 | tee -a "${LOG_FILE}"
rm -f "${dumpfile}"

# Prune anything older than RETAIN_DAYS. We list, filter by
# Updated timestamp, and delete in one batch.
log "prune horizon=${RETAIN_DAYS}d"
cutoff_epoch=$(( $(date -u +%s) - RETAIN_DAYS * 86400 ))

# `gcloud storage ls -l` prints `<size> <UTC-iso8601> <gs-uri>`.
gcloud storage ls -l "gs://${SCLIB_BACKUP_BUCKET}/postgres/" 2>/dev/null \
    | awk '/sclib-.*\.sql\.gz$/ {print $2, $3}' \
    | while read -r updated uri; do
        # Convert the gcloud iso8601 to epoch. GNU date understands it directly.
        upd_epoch=$(date -u -d "${updated}" +%s 2>/dev/null || echo 0)
        if (( upd_epoch > 0 && upd_epoch < cutoff_epoch )); then
            log "prune ${uri}"
            gcloud storage rm "${uri}" 2>&1 | tee -a "${LOG_FILE}" || true
        fi
    done

log "DONE backup_postgres"
