#!/usr/bin/env bash
# Create and upload a verifiable PostgreSQL custom-format backup.
set -Eeuo pipefail

SCLIB_ROOT="${SCLIB_ROOT:-/opt/SCLib_JZIS}"
LOG_DIR="${SCLIB_LOG_DIR:-/var/log/sclib}"
LOG_FILE="${LOG_DIR}/backup.log"
RETAIN_DAYS="${SCLIB_BACKUP_RETAIN_DAYS:-35}"
BACKUP_PREFIX="${SCLIB_BACKUP_PREFIX:-postgres}"

mkdir -p "$LOG_DIR"

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG_FILE"
}

on_error() {
  local rc=$?
  log "FAIL backup_postgres exit=$rc at line ${BASH_LINENO[0]}"
  exit "$rc"
}
trap on_error ERR

if [[ -f "$SCLIB_ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  set -a && source "$SCLIB_ROOT/.env" && set +a
fi
if [[ -f "$SCLIB_ROOT/.env.backup" ]]; then
  # shellcheck disable=SC1091
  set -a && source "$SCLIB_ROOT/.env.backup" && set +a
fi

: "${SCLIB_BACKUP_BUCKET:?set a dedicated backup bucket in .env.backup}"
: "${SCLIB_BACKUP_CREDENTIALS_FILE:=/etc/sclib/credentials/backup-external-account.json}"
: "${SCLIB_BACKUP_SERVICE_ACCOUNT:=sclib-backup@jzis-sclib.iam.gserviceaccount.com}"
if [[ -n "${GCS_BUCKET:-}" && "$SCLIB_BACKUP_BUCKET" == "$GCS_BUCKET" ]]; then
  log "FAIL backup bucket must differ from the application data bucket"
  exit 1
fi
[[ "$RETAIN_DAYS" =~ ^[1-9][0-9]*$ ]] || {
  log "FAIL SCLIB_BACKUP_RETAIN_DAYS must be a positive integer"
  exit 1
}
for command in docker gcloud python3 git; do
  command -v "$command" >/dev/null || {
    log "FAIL required command not found: $command"
    exit 1
  }
done

cd "$SCLIB_ROOT"
python3 scripts/validate_gcp_credentials.py validate \
  --credential "$SCLIB_BACKUP_CREDENTIALS_FILE" \
  --expected-service-account "$SCLIB_BACKUP_SERVICE_ACCOUNT"
export CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE="$SCLIB_BACKUP_CREDENTIALS_FILE"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
basename="sclib-$timestamp"
dumpfile="$tmpdir/$basename.dump"
manifest="$tmpdir/$basename.manifest.json"
listing="$tmpdir/listing.txt"
destination="gs://$SCLIB_BACKUP_BUCKET/$BACKUP_PREFIX"

log "START backup_postgres destination=$destination"
docker compose exec -T postgres \
  pg_dump --format=custom --compress=9 --no-owner --no-acl \
  -U sclib -d sclib > "$dumpfile"
[[ -s "$dumpfile" ]]
docker compose exec -T postgres pg_restore --list < "$dumpfile" >/dev/null

postgres_version="$(docker compose exec -T postgres \
  psql -X -A -t -U sclib -d sclib -c 'SHOW server_version')"
git_sha="$(git rev-parse HEAD)"
python3 scripts/backup_manifest.py create \
  --dump "$dumpfile" \
  --output "$manifest" \
  --postgres-version "$postgres_version" \
  --git-sha "$git_sha"
python3 scripts/backup_manifest.py verify --dump "$dumpfile" --manifest "$manifest"

gcloud storage cp "$dumpfile" "$destination/$basename.dump"
gcloud storage cp "$manifest" "$destination/$basename.manifest.json"
local_bytes="$(wc -c < "$dumpfile" | tr -d '[:space:]')"
remote_bytes="$(gcloud storage ls -l "$destination/$basename.dump" | awk 'NR == 1 {print $1}')"
[[ "$remote_bytes" == "$local_bytes" ]]
log "uploaded artifact=$basename.dump bytes=$local_bytes"

# Retention deletion is strict: an access or delete failure makes the backup
# job fail so monitoring cannot mistake an unhealthy backup set for success.
gcloud storage ls -l "$destination/" > "$listing"
cutoff_epoch=$(( $(date -u +%s) - RETAIN_DAYS * 86400 ))
while read -r updated uri; do
  [[ -n "$uri" ]] || continue
  updated_epoch="$(date -u -d "$updated" +%s)"
  if (( updated_epoch < cutoff_epoch )); then
    log "prune $uri"
    gcloud storage rm "$uri"
  fi
done < <(
  awk '/sclib-.*\.(dump|manifest\.json)$/ {print $2, $3}' "$listing"
)

log "DONE backup_postgres artifact=$basename.dump retain_days=$RETAIN_DAYS"
