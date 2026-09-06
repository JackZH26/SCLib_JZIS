# Legacy Discovery feed contract (DR03)

This is a legacy research-lead feed, not RPS or a source of experimental
negative labels. `negative_control` is a research role, not a measured outcome.

## Validation and local publication

`api/services/discovery_contract.py` is the DB-independent, strict Pydantic
contract shared by ingestion and API reads. Required fields, explicit known
extensions, candidate ID uniqueness and finite typed numbers are validated.
The parser also rejects duplicate JSON keys and overflowing exponents. We do
not invent a common numerical range for different legacy heuristic scores.

Existing upstream schema version omission is supported as version 1; unknown
versions/fields fail closed. Six existing upstream extension fields are
explicitly retained instead of silently discarded. A producer extension must
be reviewed and added to the contract before it is published locally.

The pull script requires `DISCOVERY_VALIDATOR_PYTHON` to name a Python
environment containing the API's Pydantic v2 dependency. Its default is
`api/.venv/bin/python` in the checkout. Missing dependencies fail before a pull.

```bash
api/.venv/bin/python scripts/validate_discovery_feed.py \
  --feed /explicit/path/download.json --metadata /explicit/path/meta.json
```

Without `--publish`, this validates only; it does not write or contact a
service. `--publish /explicit/path/discovery_feed.json` atomically replaces a
single **local cache envelope** containing the original feed, matching metadata,
content digest and validation timestamp. Producer metadata must match the
feed's digest, count, status, timestamp and declared source. Digest calculation
retains the existing producer's sorted-key, UTF-8 JSON convention.

The cache file is no longer necessarily the raw feed: consumers of the local
filesystem must understand `cache_schema: discovery-cache/1`. The public full
feed endpoint still returns the legacy wire payload. Old raw local feed files
remain readable, but incomplete objects are no longer merged with defaults.

Before publication, the previous validated envelope is saved as
`<feed-path>.last-good.json`. API workers also checkpoint a successfully
validated raw/enveloped feed for restart recovery. The cache directory must be
writable by the pull process and API user; preflight permissions before rollout.
The API never reports an unreadable/uncheckpointable initial cache as validated.

A failed pull records a sanitized failure marker at
`<feed-path>.update-status.json` without replacing the feed. Readers then show
the last-good data as `stale`, even if the active file itself was not changed.
A later successful validated publication supersedes the earlier failure time.
Download, schema and atomic-promotion failures leave the previous matched pair
intact. No invalid or missing feed is replaced by synthetic candidate rows.

## Version-bound HTTP reads

1. Read `/discovery/metadata` and retain `data_version`.
2. Send that value as `data_version` on each candidate page/role filter and
   detail request. Responses repeat it in their body and `X-Data-Version`.
3. A changed version returns `409` and an explicit restart instruction; an
   unpinned continuation or detail returns `428`. The current implementation
   does not retain arbitrary old versions for pagination. Restart from metadata.

The first candidate page can bootstrap without a version, but the frontend
always pins it to metadata. Metadata includes `source_status`,
`last_successful_at` and a sanitized `source_error`. With no validated version,
metadata exposes missing/invalid status and data routes return `503`. With a
recoverable version, data remain available with `stale` status.

ETags validate the actual metadata/page/detail representation. Last-Modified
is informational, not a sufficient conditional-read validator, because stale
status can change without changing the source timestamp. Reads use revalidation;
version conflicts are `no-store`. The client validates version, identity, role,
total/offset and duplicate IDs before appending, and clears mixed-version data
with an English reload prompt. It does not fall back to unversioned full-feed
data during deployment errors.

## Verification and rollout boundary

Pure filesystem and direct-route tests can run with `--noconftest` and require
no DB, Redis, network, app startup or cloud credentials. The full API suite must
use the separately guarded disposable-test runner, never a live database.

Roll out backend and frontend contracts together. Confirm cache directory
permissions, validator interpreter and scheduled-pull environment before use;
back up the current local feed. No deployment or production migration is
performed by these source changes.
