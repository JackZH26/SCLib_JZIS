# Thirty-sixth implementation batch: source-task operator workflow

Date: 2026-09-09. Base commit: `b36080a`.
Issue advanced: [SC08 / #66](https://github.com/JackZH26/SCLib_JZIS/issues/66).
Related curator interaction: [UX02 / #73](https://github.com/JackZH26/SCLib_JZIS/issues/73).
Application schema remains `0067_scientific_adjudication`; no migration or backfill.

## Delivered software outcome

The existing exact-source Timeline invalidation service now has a private,
curator-only preview/commit/recovery API and an English dashboard workflow.
This completes a bounded operator interaction, **not** all source-change
propagation, scientific acceptance or the issue's operational SLA.

The operation contract is `source-task-operation/1.0.0`. Its only executable
action remains `timeline-cache-invalidation/1.0.0`: set an existing Timeline
readiness singleton's schema version to zero, or acknowledge an accurate no-op.
It neither creates a missing singleton nor rebuilds points. External cache,
vector index, saved-answer, ML release and RPS propagation are not acknowledged.

The new private `/dashboard/research/source-tasks` page offers:

1. Paper/Work lifecycle inspection and selection of the current exact event.
2. Bounded source-impact inventory inspection, including covered and excluded
   relationships; explicit enqueue preview and confirmation.
3. Immutable task history and exact predecessor-bound execution preview.
4. Original requester-key and exact executor-key recovery, without substituting
   the latest attempt for the operation the user actually submitted.

The fixed `false` fields for propagation completion, Timeline rebuild,
external-cache invalidation, scientific/ML approval and source reinstatement
remain visible in contracts and explanatory UI. A committed blocked/obsolete
record is not portrayed as successful invalidation.

## Integrity and failure handling

- Closed, strict, bounded JSON: no body-supplied actor/grant; canonical UUIDs,
  lower-case hashes, paired predecessor ID/hash, duplicate-key and coercion
  rejection. Requests are 8 KiB maximum, commit envelopes 8 KiB + 256 bytes,
  responses 32 KiB. No arbitrary browser-authored failure-report endpoint.
- Curator authorization is checked before reading upload bytes. That read-only
  snapshot is closed, then the complete body is parsed and a **fresh** UTC
  SERIALIZABLE session revalidates JWT/session and curator authority. This also
  protects historical replay when a session is revoked during upload.
- The stable preview binds the normalized operation, actor/exact grant,
  predicted record status/outcome and negative semantics. Rehearsal-generated
  IDs/timestamps/hashes are excluded. A checksum is not a signed authorization.
- Preview validation and actual insertion remain inside the ordered
  `540 → 550 → 560 → 580` fence. An intervening head, source, inventory or grant
  change cannot silently reuse the prior preview. Replacement grants do not
  revive the original requester's revoked authority.
- Preview and replay roll back the **entire** dedicated outer transaction,
  including guard epochs. The original receipt is retained and no rebuilt
  Timeline is invalidated again. New success is returned only after outer commit.
- Two nonblocking process-local slots, a 20-second route deadline, 10-second
  service deadline and 5-second statement timeouts bound resource use. Static
  private/no-store errors do not leak diagnostics.
- Unknown outcomes retain the original key, disable new writes and permit only
  explicit receipt checks. A 404 is an observation, not proof of rollback.
  Auth changes clear private evidence; recovery is bound to the original actor.

Browser recovery is memory-only. The page warns on browser unload and explicitly
explains that reloading, closing the tab or client-side navigation can discard
the key; this is not a durable browser outbox or universal SPA navigation guard.
Operators should securely retain the displayed original key before leaving.
Historical receipt grant IDs are not advertised as current permissions.

## Verification

All API runs used the guarded disposable native PostgreSQL/Redis runner. Each
counted run returned exit zero and confirmed cleanup of only its owned services
and temporary test data. No inherited or production database was accessed.

| Evidence | Result |
| --- | --- |
| Final integrated 17-module API regression | **411 passed**, 133.65 seconds; one existing FastAPI `regex` deprecation warning |
| Final focused operator HTTP suite | **55 passed**, 32.10 seconds; included in the integrated result |
| Focused service/legacy task/Timeline checkpoint | **87 passed**, 11.52 seconds; overlapping, not additive to integrated coverage |
| Entire scripts suite | **989 passed + 36 subtests**, 17.31 seconds |
| Entire frontend component suite, one worker | **711 passed**, 30 files, 35.83 seconds; includes 72 new source-task cases |
| Entire frontend source/English-default suite | **35 passed**, 0.793 seconds |
| Final TypeScript check | `pnpm exec tsc --noEmit --incremental false`, exit zero |
| Final isolated browser suite | **4 passed**, 14.7 seconds; desktop 1440px and mobile 390px, no horizontal overflow or unexpected network requests |
| Scoped Python lint and whitespace | Ruff import/undefined-name checks and `git diff --check`, passed |

The final browser run used a separate temporary source copy and port 32036;
it neither reused the normal `.next` directory nor the user's existing server.
Its temporary screenshot/trace root is
`/var/folders/m0/ztnj2ywn613cqhtb3_ym0xyc0000gn/T/sclib-source-task-browser-artifacts-gWl8tU`.
Desktop/mobile previews and unknown-outcome layouts were visually inspected;
the final mobile recovery view includes the explicit same-tab/reload limitation.
These temporary screenshots are local QA artifacts, not permanent release evidence.

The API integration covers all-table and epoch equality for preview/replay,
allowed-table-only enqueue, singleton-only invalidation, missing-state no-op,
old-receipt replay after rebuild, exact historical attempt retrieval, stale
source/inventory/head/grant rejection, independent-transaction competition,
cancellation and slot cleanup, real deferred-commit rollback, and recovery after
a committed transaction loses its HTTP acknowledgment. New and replayed writes
are tested against session revocation during upload.

The frontend fixture `frontend/tests/fixtures/source-task-operations-http.json`
was captured from actual HTTP responses over synthetic records in the disposable
database. Its source/history/impact and receipt shapes and Python operation
hashes are consumed by the strict frontend parsers. Browser transport is
explicitly synthetic: only browser-generated keys and their derived hashes are
remapped. It is not a claim of production or live-browser-to-API acceptance.

### Corrections observed during verification

- An initial legacy regression command named nonexistent test modules and exited
  before running tests; it is not counted as acceptance.
- The first complete legacy-source selection had **195 passes and one failure**:
  a 0056 contention test expected the source-specific busy error, but unchanged
  schema 0067 now acquires the shared integrity fence first. The test now asserts
  that exact earlier rejection plus SQLSTATE `55P03`, preserving retry/no-fork
  checks. No database guard or migration was relaxed.
- Early new HTTP test assertions omitted the existing global middleware's
  sanitized `error_code`/`request_id` fields; test expectations were corrected,
  not production error handling. A test-local stream variable capture was fixed.
- The first all-parallel frontend run passed 35 source tests and 702 component
  tests but timed out one unchanged Discovery layout test under concurrent host
  load. Final frontend acceptance uses a complete one-worker rerun without
  relaxing test assertions or timeout values.

## Compatibility and remaining work

The old internal task interfaces remain compatible; only optional exact-grant and
predecessor checks were added. The original request/attempt schema and immutable
record hashes remain unchanged. The earlier read-only task-history route still
admits current research operators; **recovery** endpoints are actor-scoped and
curator-only. The UI distinguishes those access rules. All prior ML compiler
formats, frozen source pins and accepted scientific fields remain untouched.

SC08 stays open for separately versioned delivery to other consumers, broader
lineage coverage, monitored rebuild completion, measured lag/SLA, reviewed real
source cases, rights/scientific review and authorized deployment. No automatic
worker, new dataset publication, positive source reinstatement or scientific
review decision is introduced by this batch.

The next planned independent engineering slice is EN06 / #71: a guarded restore
rehearsal that checks a complete synthetic scientific release, retained artifact
bytes, provenance and permission state, and index rebuild requirements rather
than reporting success from core-table row counts alone. Real recovery objectives
and production operations remain separate acceptance gates.

Local implementation and verification do not authorize push, PR creation, live
issue closure, production deployment, source redistribution or paid computation.
The broader goal remains active; this batch is substantive progress, not a claim
that all outstanding issues are complete.
