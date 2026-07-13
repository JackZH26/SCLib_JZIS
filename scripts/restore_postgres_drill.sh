#!/usr/bin/env bash
# Restore a backup into an isolated, disposable PostgreSQL container.
set -Eeuo pipefail

usage() {
  echo "usage: $0 --dump FILE --manifest FILE --report FILE" >&2
}

dumpfile=""
manifest=""
report=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dump) dumpfile="${2:-}"; shift 2 ;;
    --manifest) manifest="${2:-}"; shift 2 ;;
    --report) report="${2:-}"; shift 2 ;;
    *) usage; exit 2 ;;
  esac
done
[[ -f "$dumpfile" && -f "$manifest" && -n "$report" ]] || {
  usage
  exit 2
}
for command in docker python3; do
  command -v "$command" >/dev/null || {
    echo "restore drill requires $command" >&2
    exit 1
  }
done

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$root/scripts/backup_manifest.py" verify \
  --dump "$dumpfile" --manifest "$manifest" >/dev/null

started_epoch="$(date -u +%s)"
container="sclib-restore-drill-${GITHUB_RUN_ID:-$$}-${RANDOM}"
image="${SCLIB_RESTORE_IMAGE:-postgres:16-alpine}"
cleanup() {
  docker rm --force --volumes "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run --detach --name "$container" \
  --label org.jzis.sclib.purpose=restore-drill \
  --env POSTGRES_PASSWORD=restore_drill_only \
  --env POSTGRES_DB=sclib_restore_drill \
  "$image" >/dev/null
for attempt in $(seq 1 60); do
  if docker exec "$container" pg_isready -U postgres -d sclib_restore_drill \
    >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" -eq 60 ]]; then
    docker logs "$container" >&2
    exit 1
  fi
  sleep 1
done

docker exec -i "$container" pg_restore \
  --exit-on-error --single-transaction --no-owner --no-acl \
  -U postgres -d sclib_restore_drill < "$dumpfile"

readarray -t result < <(
  docker exec -i "$container" psql -X -A -t -U postgres -d sclib_restore_drill <<'SQL'
SELECT version_num FROM alembic_version;
SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public';
SELECT count(*) FROM papers;
SELECT count(*) FROM materials;
SELECT count(*) FROM users;
SELECT count(*) FROM pipeline_state;
SELECT count(*) FROM pg_index WHERE NOT indisvalid;
SELECT count(*) FROM pg_constraint WHERE NOT convalidated;
SQL
)
[[ "${#result[@]}" -eq 8 ]]
[[ -n "${result[0]}" ]]
[[ "${result[1]}" -ge 4 ]]
[[ "${result[6]}" -eq 0 ]]
[[ "${result[7]}" -eq 0 ]]

finished_epoch="$(date -u +%s)"
mkdir -p "$(dirname "$report")"
python3 - "$manifest" "$report" "$started_epoch" "$finished_epoch" "${result[@]}" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text())
report = {
    "schema_version": 1,
    "status": "passed",
    "completed_at": datetime.now(timezone.utc).isoformat(),
    "duration_seconds": int(sys.argv[4]) - int(sys.argv[3]),
    "backup": manifest,
    "restored": {
        "alembic_revision": sys.argv[5],
        "public_table_count": int(sys.argv[6]),
        "papers": int(sys.argv[7]),
        "materials": int(sys.argv[8]),
        "users": int(sys.argv[9]),
        "pipeline_state_rows": int(sys.argv[10]),
        "invalid_indexes": int(sys.argv[11]),
        "unvalidated_constraints": int(sys.argv[12]),
    },
}
Path(sys.argv[2]).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
print(json.dumps(report, indent=2, sort_keys=True))
PY
