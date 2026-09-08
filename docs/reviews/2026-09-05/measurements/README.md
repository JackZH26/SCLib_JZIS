# Isolated engineering rehearsal measurements

This directory retains actual, opt-in EN02 migration/read-model rehearsal
receipts. They concern newly created disposable synthetic databases, not
production, scientific review, source redistribution or an approved deployment.

Use a fresh filename for every run. The runner refuses existing files and does
not publish a success receipt until the full rehearsal and owned-resource
cleanup succeed. Its embedded `report_sha256` covers the canonical report body
excluding that field; the completed receipt's **full file SHA-256** is recorded
below independently, including its final newline. Source hashes bind a
conservative API/scripts worktree inventory, including uncommitted code and
synthetic test fixtures—not only the recorded HEAD commit. This is not a claim
that every inventoried file executed or that installed dependencies matched a
release image.

See [SCHEMA_ROLLOUT.md](../../../SCHEMA_ROLLOUT.md) for report scope, operational
rollback instructions and the separate production-readiness gate.

No secrets, DSNs, capability files, raw source bodies or research-release bytes
belong in these archives. Hash equality is an integrity check, not human
authentication or scientific approval.

## 2026-09-08: retained native rehearsal

The initial development attempt failed a **new report-only fixture assertion**:
missing force constants correctly produced both `force_constants_unavailable`
and `validated_coordinates_unavailable`, while the first assertion expected only
the former. No receipt was published; the disposable services were cleaned up.
The reporting assertion/accounting was corrected without changing import
production code or suppressing either real reason.

The first successful actual receipt is
[EN02_Schema_Rehearsal_2026-09-08.json](EN02_Schema_Rehearsal_2026-09-08.json).
It remains unchanged after the subsequent EN04-only exception-handling fix.

| Measurement | Actual first-success value |
| --- | --- |
| Full file SHA-256 | `a50437d5f6e7140be8e9fda5c93d091e520c8bcb2038ce19a569487f74aed5d0` |
| Body SHA-256 | `b178e7c7c395d65ac3d2426fb6ed3df31cec4f33eaddd355651838cc0a5760b0` |
| Exact file size / initial permissions | 81,293 bytes / `0600` |
| UTC start / completion | `2026-09-08T08:58:04.282547Z` / `2026-09-08T08:58:38.364510Z` |
| Measured rehearsal time | 34,081 ms; excludes startup, cleanup and publication |
| Captured source inventory | 511 files; digest `bc3467b55ef13a222fe83494ae5b34e46d620deda03781c52b1169a4616e7601` |
| HEAD / worktree | `a04573060dd4c9de217a8364161e42a2f4c3be5f`; dirty worktree explicitly retained |
| Runtime | Native PostgreSQL 16.13 (`160013`), CPython 3.12.14, Darwin arm64 |
| Schema | Real `0050_timeline_identity` to `0066_result_impact_indexes` |
| Cleanup | Successful before final receipt publication |

Immediately after capture, the report's closed schema/body hash and full-file
hash were checked; source inventory was rechecked against then-current files.
A real repeated `--report` invocation for this existing path was refused with
exit 2 **before starting any services**, preserving the existing receipt.

Final synthetic SQL accounting was 2 packages / 2 attempts / 2 terminals:
1 `success_pending`, 1 `quarantined`, 0 `failed`, and 0 remaining unknown
terminals. Each missing-force-constants reason counted once for the **same**
quarantined package. Five scientific result tables were unchanged by that
quarantine. These ledger counts are not counts of failed rehearsal executions.
Shadow receipt rows were measured as zero; shadow-data exclusions and all
production exclusions remain unknown, not assumed zero.

The original two legacy material rows, one exact seeded source revision, and a
frozen release plus its 19 pins (20 rows total) passed before/after hash equality.
The final synthetic database held 12 materials, 9 papers, 11 raw material
records, 6 claims, 4 event properties, 4 source snapshots, 4 ML dataset snapshots,
4 ML examples and 4 releases / 76 release pins. Those totals include intentional
fixture additions; they are not a 2-to-12 production data conversion claim.
Two retained generations, two validations and three activation events prove
promotion and a distinct CAS rollback. The original text and all 3,072 float32
vector bytes remained exact despite a mutable-chunk replacement.

The final-source-aligned follow-up is retained separately below; never edit or
relabel this first successful artifact as having run the later EN04 code.

## Historical source-aligned receipt after the EN04 fix

[EN02_Schema_Rehearsal_2026-09-08-02.json](EN02_Schema_Rehearsal_2026-09-08-02.json)
records the EN04-fix checkpoint. It reran the **entire** guarded native
rehearsal after the EN04 exception-handling fix; it is not a rehash or relabelling
of the first run.

| Measurement | Actual final value |
| --- | --- |
| Full file SHA-256 | `c13d15a7b9604bd2859b11f09bec235efa0ba6f0bcc2f71dc8f99786c6bcece3` |
| Body SHA-256 | `26812538800673b10c3eb5176e047abdee68ece27b240e81859d5c2cb2a489f7` |
| Exact file size / initial permissions | 81,293 bytes / `0600` |
| UTC start / completion | `2026-09-08T08:59:55.349275Z` / `2026-09-08T09:00:34.751053Z` |
| Measured rehearsal time | 39,401 ms; not a production performance benchmark |
| Captured source inventory | 511 files; digest `544794709f3392f33c21502a0f6c39669e054b7864d7deafab6ad9cc1d7c7c8b` |
| HEAD / worktree | Same `a04573060dd4c9de217a8364161e42a2f4c3be5f`; exact changed bytes retained separately |
| Result | Exit 0; all original migration/history assertions and the measured quarantine/rollback checks passed; cleanup completed before publication |

The before/after table counts and bounded import accounting match the first
successful run. Generation and validation IDs were newly observed in this
second disposable database; the receipt contains the actual IDs used for its
rollback. The code-input inventory differs only in
`scripts/verify_release_runtime.py` and
`scripts/tests/test_release_runtime_parity.py`. Other source hashes, including
the EN02 recorder/runner, were unchanged. Immediately after publication, the
final receipt's closed schema and full/body hashes were verified and all 511
source inputs were rechecked against the then-current worktree. The first
receipt's complete file hash was checked again and remained unchanged.

The final invocation was:

```sh
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite migrations \
  --report /Users/jackzhou/Documents/SCLib_JZIS/docs/reviews/2026-09-05/measurements/EN02_Schema_Rehearsal_2026-09-08-02.json
```

Related source-only regressions: **111 passed, 20 subtests passed** (75 new report
tests plus 36 existing schema/test-safety tests), latest focused run 1.90 seconds.
Ruff import/undefined-name checks passed. These do not substitute for the actual
database run above, and neither establishes Linux release-image package parity.

## Latest batch-33 receipt after the test-isolation fix

[EN02_Schema_Rehearsal_2026-09-08-03.json](EN02_Schema_Rehearsal_2026-09-08-03.json)
is the **latest** full native rehearsal receipt. Both preceding successful
artifacts remain unchanged.

The older full API run finished with 5,033 passed, 1 failed and 3 skipped. Its
failure was a test-isolation assumption: a queue test treated the globally first
material as its own AlAs fixture, although an earlier test had retained MgB2.
Only `api/tests/test_scientific_result_dossier.py` was corrected to use two
distinct material records and an exact UUID/keyset range. No product schema or
service code changed. The parent task then reported **147 passed**, 20 existing
warnings, in 45.49 seconds across six focused modules, with owned-service
cleanup complete. This is not a claim that the old full run passed, or that a
new full API run was executed after the fix.

After the explicit source freeze, the complete migration rehearsal was rerun
with a new `-03.json` output path:

| Measurement | Actual latest value |
| --- | --- |
| Full file SHA-256 | `7b22fa6c61d3399e40002ae48675d8ada2c537dc26a9348acbc8b1a33f673104` |
| Body SHA-256 | `a1d6ee96a6124b2b2f69e25bf0a4080ddd013b090a1244f4866859abc5cebe47` |
| Exact file size / initial permissions | 81,293 bytes / `0600` |
| UTC start / completion | `2026-09-08T09:06:28.142496Z` / `2026-09-08T09:06:51.222877Z` |
| Measured rehearsal time | 23,080 ms; excludes startup, cleanup and publication |
| Captured source inventory | 511 files; digest `7470b58c6de92527264245a4ced71a2928131a5418136a818f867d95561bde8b` |
| HEAD / worktree | `a04573060dd4c9de217a8364161e42a2f4c3be5f`; dirty worktree bytes explicitly captured |
| Result | Exit 0; full upgrade/independent history guards, retention, quarantine and CAS rollback passed; successful cleanup before publication |

Independent post-publication verification validated the report schema, body and
full-file hashes, and all captured source hashes against the then-current
worktree. Exactly one source entry differs from `-02`:
`api/tests/test_scientific_result_dossier.py`. The four measured count phases
and final import accounting are identical to `-02`. Both earlier receipts'
complete file hashes were rechecked and remained unchanged. No additional
full-script run was claimed for this documentation/measurement follow-up.
