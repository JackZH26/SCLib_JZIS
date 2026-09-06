#!/usr/bin/env bash
# Pull the public SC SuperLoop Discovery feed into the SCLib local cache.
#
# Failure policy: never delete or overwrite the last known-good cache unless the
# newly downloaded feed passes the same strict contract as the API and matches
# metadata. A single local envelope atomically publishes feed + metadata.
set -euo pipefail

BASE_URL="${DISCOVERY_FEED_BASE_URL:-https://discovery-feed.jzis.org}"
CACHE_DIR="${DISCOVERY_CACHE_DIR:-/data/sclib/discovery}"
FEED_PATH="$CACHE_DIR/discovery_feed.json"
LOCK_PATH="$CACHE_DIR/.pull_discovery_feed.lock"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VALIDATOR_PYTHON="${DISCOVERY_VALIDATOR_PYTHON:-$SCRIPT_DIR/../api/.venv/bin/python}"
if [ ! -x "$VALIDATOR_PYTHON" ]; then
  echo "Set DISCOVERY_VALIDATOR_PYTHON to an API Python environment with Pydantic v2." >&2
  exit 1
fi
"$VALIDATOR_PYTHON" "$SCRIPT_DIR/validate_discovery_feed.py" --help >/dev/null

mkdir -p "$CACHE_DIR"

exec 9>"$LOCK_PATH"
flock -n 9 || {
  echo "another discovery feed pull is already running"
  exit 0
}

TMP_DIR="$(mktemp -d "$CACHE_DIR/.pull.XXXXXX")"
cleanup() {
  local pull_status=$?
  if [ "$pull_status" -ne 0 ]; then
    "$VALIDATOR_PYTHON" "$SCRIPT_DIR/validate_discovery_feed.py" --mark-failed "$FEED_PATH" || true
  fi
  # Only files created by this pull are removed; never recursively erase cache.
  rm -f -- "$META_TMP" "$FEED_TMP"
  rmdir -- "$TMP_DIR"
  return "$pull_status"
}
trap cleanup EXIT

META_TMP="$TMP_DIR/discovery_meta.json"
FEED_TMP="$TMP_DIR/discovery_feed.json"

curl -fsS --connect-timeout 10 --max-time 30 --retry 2 --retry-delay 3 \
  "$BASE_URL/discovery-meta.json" -o "$META_TMP"

curl -fsS --connect-timeout 10 --max-time 60 --retry 2 --retry-delay 3 \
  "$BASE_URL/discovery-feed.json" -o "$FEED_TMP"
"$VALIDATOR_PYTHON" "$SCRIPT_DIR/validate_discovery_feed.py" \
  --feed "$FEED_TMP" --metadata "$META_TMP" --publish "$FEED_PATH"
