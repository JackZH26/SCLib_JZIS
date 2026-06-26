#!/usr/bin/env bash
# Pull the public SC SuperLoop Discovery feed into the SCLib local cache.
#
# Failure policy: never delete or overwrite the last known-good cache unless the
# newly downloaded feed is valid JSON and, when provided, matches the published
# metadata sha256.
set -euo pipefail

BASE_URL="${DISCOVERY_FEED_BASE_URL:-https://discovery-feed.jzis.org}"
CACHE_DIR="${DISCOVERY_CACHE_DIR:-/data/sclib/discovery}"
FEED_PATH="$CACHE_DIR/discovery_feed.json"
META_PATH="$CACHE_DIR/discovery_meta.json"
LOCK_PATH="$CACHE_DIR/.pull_discovery_feed.lock"

mkdir -p "$CACHE_DIR"

exec 9>"$LOCK_PATH"
flock -n 9 || {
  echo "another discovery feed pull is already running"
  exit 0
}

TMP_DIR="$(mktemp -d "$CACHE_DIR/.pull.XXXXXX")"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

META_TMP="$TMP_DIR/discovery_meta.json"
FEED_TMP="$TMP_DIR/discovery_feed.json"

curl -fsS --connect-timeout 10 --max-time 30 --retry 2 --retry-delay 3 \
  "$BASE_URL/discovery-meta.json" -o "$META_TMP"
jq . "$META_TMP" >/dev/null

NEW_SHA="$(jq -r '.sha256 // empty' "$META_TMP")"
OLD_SHA="$([ -f "$FEED_PATH" ] && sha256sum "$FEED_PATH" | awk '{print $1}' || true)"

if [ -n "$NEW_SHA" ] && [ "$NEW_SHA" = "$OLD_SHA" ]; then
  cp "$META_TMP" "$META_PATH"
  echo "discovery feed unchanged: $NEW_SHA"
  exit 0
fi

curl -fsS --connect-timeout 10 --max-time 60 --retry 2 --retry-delay 3 \
  "$BASE_URL/discovery-feed.json" -o "$FEED_TMP"
jq . "$FEED_TMP" >/dev/null

if [ -n "$NEW_SHA" ]; then
  DOWNLOADED_SHA="$(sha256sum "$FEED_TMP" | awk '{print $1}')"
  if [ "$DOWNLOADED_SHA" != "$NEW_SHA" ]; then
    echo "sha256 mismatch: meta=$NEW_SHA downloaded=$DOWNLOADED_SHA" >&2
    exit 1
  fi
fi

STATUS="$(jq -r '.status // empty' "$FEED_TMP")"
CANDIDATES="$(jq -r '(.candidates // .materials // .items // []) | length' "$FEED_TMP")"
if [ -z "$STATUS" ] || [ "$CANDIDATES" = "0" ]; then
  echo "refusing to publish empty or status-less discovery feed: status=$STATUS candidates=$CANDIDATES" >&2
  exit 1
fi

chmod 0644 "$FEED_TMP" "$META_TMP"
mv "$FEED_TMP" "$FEED_PATH"
mv "$META_TMP" "$META_PATH"

echo "updated discovery feed: status=$STATUS candidates=$CANDIDATES sha=${NEW_SHA:-unknown}"
