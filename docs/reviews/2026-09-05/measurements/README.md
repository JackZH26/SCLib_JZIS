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

## 0067 adjudication checkpoint

[EN02_Schema_Rehearsal_2026-09-08-04.json](EN02_Schema_Rehearsal_2026-09-08-04.json)
is a new complete native rehearsal after batch34 API, schema, gate and boundary
edits, before the subsequent publication preflight-order correction. It was not
derived by editing an earlier report or relabelled after that correction.

| Measurement | Actual 0067 value |
| --- | --- |
| Full file SHA-256 | `a3ff06ee98d626ac52b015cab17599e30b93857dc5f7d9ff8c3238a799d1bd1f` |
| Body SHA-256 | `024e4fab33e3f9121f806fb61414fb1482391e33b739400dc0732b15e5e2ec88` |
| Exact file size / initial permissions | 83,418 bytes / `0600` |
| UTC start / completion | `2026-09-08T09:48:20.116238Z` / `2026-09-08T09:48:46.893948Z` |
| Measured rehearsal time | 26,777 ms; not a production latency benchmark |
| Captured source inventory | 525 files; digest `58b0842610e2b05ee3325b509b7e1e8f792a6808932950e9b0164f8638dd766b` |
| HEAD / worktree | `11e674a6a20093416e6ffc00631dca85c9765686`; actual dirty-worktree input bytes pinned |
| Schema | Actual `0050_timeline_identity` to `0067_scientific_adjudication` |
| Result | Exit 0; full historical guards, 0067 empty roundtrip, actual preview/commit/replay, retained-history downgrade refusal and cleanup passed |

The closed schema/body hash and current full source inventory were independently
validated after report publication. Legacy/source/frozen retention signatures
still match; actual import accounting remains one pending success and one
quarantine with two overlapping reason codes. The report's unchanged v1 named
outcome/count vocabulary remains the earlier sixteen outcomes and listed
tables: it does not add named 0067 audit-table counts. The source-pinned extended
harness executed the additional 0067 assertions before `finish`; its exit and
native test evidence are documented in
[batch34](../Priority_Thirty_Fourth_Batch_Implementation_2026-09-08.md).
Neither the unchanged report vocabulary nor an accepted synthetic test decision
is reinterpreted as real scientific review or production approval.

## Final 0067 source checkpoint after publication preflight correction

[EN02_Schema_Rehearsal_2026-09-08-05.json](EN02_Schema_Rehearsal_2026-09-08-05.json)
reruns the entire migration rehearsal after restoring the original publication
material/source preflight order. The prior `-04` report remains unchanged.

| Measurement | Actual final checkpoint |
| --- | --- |
| Full file SHA-256 | `d65d8b6e66ce5df9aa94d49986e8441d05161ff82bd877e7ccb4a7eae71caf18` |
| Body SHA-256 | `e90e7c36e95462ad3c1c8c5959d8065e3a0a0611ea09c3b8c5d2f8de18392837` |
| UTC start / completion | `2026-09-08T09:54:14.950437Z` / `2026-09-08T09:54:41.161294Z` |
| Measured rehearsal time | 26,210 ms; excludes startup, cleanup and report publication |
| Captured source inventory | 525 files; digest `b53a701dda3836d59ab1ff394ab6c3efd10614f1312e4dfc8896f31810366113` |
| HEAD / worktree | Same `11e674a` base, explicitly pinned dirty-worktree bytes |
| Result | Exit 0, `0050` to `0067`, all original and new history guards passed, owned cleanup verified |

Independent closed report/body and exact current source verification passed.
The sole source-input difference from `-04` is `api/services/research_publication.py`;
the corrected ordering keeps the review gate inside the same stable transaction,
after existing resource/source preflights and before admission. Its targeted
69-test publication/public-gate rerun passed without changing old limit assertions.
The v1 report vocabulary and non-production authority limitations remain as
described above.
