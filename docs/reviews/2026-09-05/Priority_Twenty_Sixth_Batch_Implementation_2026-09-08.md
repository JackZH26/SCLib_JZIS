# Twenty-sixth implementation batch — public RPS recomputation and delivery

Date: 2026-09-08. Branch: `codex/sclib-research-v2`.
Baseline: `a1d1842` (twenty-fifth batch).
Priority: [DR02 / #74](https://github.com/JackZH26/SCLib_JZIS/issues/74).
Specification: [RPS public delivery](../../RPS_PUBLIC_DELIVERY.md).

## Outcome and retained scope

Discovery now has an actual end-to-end public package path: strict package
preparation and offline recomputation, independently pinned download admission,
a failure-isolated revisioned catalogue, and its English frontend consumer.
This is not a new unused scoring schema. RPS-v1.2 scoring, action eligibility
and existing release/page/detail 1.2 identities are preserved. Catalogue 1.3
is a deliberate coordinated consumer upgrade, not a silent legacy fallback.

No real campaign, source disclosure, reviewer consent, scientific acceptance,
production configuration, database backfill, cloud computation or deployment
was created. No push, PR or remote issue closure was performed. All new positive
release and consent declarations in tests are synthetic. #74 and the overall
upgrade goal remain open for their unsatisfied dependency/acceptance gates.

## Implemented end-to-end

1. **Complete independently recomputable package.** The unchanged release,
   full campaign/budget/cutoff/profile mixes/rubrics, reviewed action templates,
   prerequisites/dependencies/resources, all assessment inputs and artifacts,
   complete scoring policy and every computed row travel together. The verifier
   resolves original manifests and transitive references, recomputes eligibility,
   effective weights, P/G/A bounds, affordability, raw/display/upper scores,
   ranks and the full contribution decomposition. It compares complete canonical
   outputs, not merely a displayed score or a bundle's self-asserted hash.
2. **Separate public disclosure admission.** Material/review/profile-assignment
   dictionaries are closed in addition to existing typed artifacts. Nested
   unknown text/private containers, source URLs containing user credentials,
   private reviewer identifiers and incomplete disclosure inventories are
   refused. Each review/template review has an exact artifact-bound public
   pseudonym/attestation declaration covering the full release digest. Unsafe
   original bundles are not stripped and served under an old approval hash.
3. **Honest verification report.** Integrity, recomputation and structural
   disclosure checks are separate from unauthenticated review/consent, unverified
   source rights, unchecked offline serving authorization and false scientific/
   empirical acceptance. Allowed prose still requires actual human disclosure
   review; a field allowlist is not a secret detector or permission grant.
4. **Packaged offline verifier.** The thin repository launcher and installed
   `python -m services.priority_public_bundle_cli` use the same implementation.
   Actual source bytes of five packaged modules are bound: public bundle,
   packaged CLI, shared file cache, release contracts and scoring policy. This
   works with the existing API image's `services` package without requiring
   an unpublished root `scripts` directory or a private database. Public files
   require bounded, exact canonical UTF-8, no duplicate keys or nonfinite values.
   Read-only subprocess tests forbid network, database and file-write attempts.
5. **Independent serving pins.** `discovery_rps_approved_public_bundles` defaults
   to empty. A download needs opt-in, original release approval, separate public
   bundle approval, matching requested catalogue pins, successful validation of
   both files and a final approval/file-witness check. A stale link yields an
   error, never an unpinned replacement. Existing release manifests remain
   `X-Data-Version`; public envelope identity has its own response header.
6. **Failure-isolated catalogue.** Healthy releases remain visible when another
   approved release is absent, corrupt or mismatched. Failures expose only
   sanitized ID/status/reason entries. A broken public package degrades download
   availability without discarding a separately verified release. All-failed
   is `unavailable`, not `not_published`. The complete approval snapshot and
   observed catalogue content determine revision/ETag, replacing POLICY_HASH
   as the catalogue identity. File/config changes cause one whole-snapshot
   retry; repeated changes fail closed rather than publishing partial refreshes.
7. **Bounded, shared single-flight verification.** Replace the two-entry LRU
   with 32 entries and 128 MiB of accounted reachable objects, including dataclass
   slots and cached rows. Keys bind expected digests and device/inode/size/mtime/
   ctime; regular-file and before/after read checks are repeated on current reads.
   Two distinct keys may validate at once; waiting is capped at 32 callers and
   30 seconds. Parsed failures have a one-second negative cache. Catalogue reads
   use lightweight detached projections; other consumers receive copies so
   mutable nested model data cannot poison cached verification.
8. **Bounded request work and cancellation.** At most four catalogue tasks and
   eight submitted worker jobs. Cancellation retains a worker permit until its
   real job finishes. If a catalogue worker fails or its client cancels, sibling
   tasks are cancelled and awaited: already submitted threads finish safely,
   but no remaining catalogue entries continue to be enqueued after the response.
9. **Currentness-aware HTTP and chronology.** Success requires immediate
   revalidation; 304 is considered only after the current file and approval
   checks. Publication dates are not used as Last-Modified validators. All RPS
   errors, including 404/409/503 and malformed request parameters, are no-store.
   Capacity failures have a bounded retry hint. Catalogue newest-first ordering
   compares aware timestamps rather than lexicographic ISO strings, preserving
   original timestamps and manifest bytes.
10. **Actual English frontend.** The board validates the exact catalogue schema,
    bounded inventory, IDs, dates, declared status and complete public-bundle
    metadata. Partial failures, all-failed and not-published have distinct states.
    Refresh clears prior scores/download pins immediately and cancels/fences
    old catalogue/page/detail requests. Links use only the configured public API
    and both selected hashes. Snapshot hashes are labelled server declarations,
    not browser recomputation or scientific certification. Captured synthetic
    HTTP catalogue and page payloads are checked across the backend/frontend
    boundary without silently changing their group or inventing research data.
11. **CI collection completeness.** All script suites now run under pytest in
    the API's locked runtime before disposable database service setup. This
    includes the scientific-evaluation CLI, new public RPS CLI and benchmark
    subprocess tests. The plain operations job retains its pure unittest error-
    budget check instead of importing the whole pytest-dependent directory in
    an environment that does not install the API test runtime. Existing guarded
    API/migration execution remains unchanged.

## Independent review and resolved findings

- A single invalid release previously aborted the catalogue; actual HTTP
  regressions now exercise two good/one bad and all-failed inventories.
- A manifest approval and `public: true` did not recursively authorize arbitrary
  internal artifact dictionaries. Full unsafe payloads are refused and public
  disclosure approval is independent from the original release pin.
- Slot-backed receipts initially escaped generic object-size accounting;
  dataclass fields are now included in the retained cache bound.
- Error responses initially lacked no-store, permitting stale negative caching;
  an RPS-only route wrapper covers explicit HTTP and parameter-validation errors.
- Merely moving validation into threads did not bound executor submissions.
  Submitted jobs now have independent capacity and cancellation-safe permits.
- `asyncio.gather` propagated failures but left sibling catalogue workers alive.
  The final audit caught this; two real HTTP/event-controlled tests prove that
  no new entries are traversed after failure/cancellation while current threads
  still finish safely and permits remain usable.
- ISO timestamp string sorting misordered releases with different offsets.
  A real catalogue regression now checks newest-first UTC-equivalent instants
  without rewriting the published timestamp or hash.
- That new test initially hashed a UTC `+00:00` fixture string instead of the
  immutable contract's canonical `Z` representation. The fixture now passes
  the actual release validator before it is served; the production hash check
  was not relaxed. A full-suite source-impact test also confused `9999` inside
  a legitimate opaque ID/hash with a leaked numeric Tc. Its deterministic
  collision fixture now checks actual sensitive fields and scalar values while
  preserving the prose canaries; source-impact production code is unchanged.
- The existing CI source assertion named the old single-file pytest step. It
  now checks full script collection in the locked runtime before services,
  retaining the database safety invariant rather than weakening it.

## Measured local workload

Full observation: [synthetic benchmark JSON](../../measurements/RPS_Delivery_Synthetic_Benchmark_2026-09-08.json).
Python 3.12.14 on macOS; tracemalloc enabled; 8 synthetic releases containing
8 assessments, 4 worker threads, 258,800 input bytes, 20 warm rounds. Each round
reads all eight objects. The fixture/source hashes and complete round timings
are retained, not only summary percentiles.

| Reader workload | Cold whole-round ms | Warm p50 / p95 whole-round ms | Cold / warm full verifications |
| --- | ---: | ---: | ---: |
| Catalogue with public bundles | 295.16 | 9.90 / 11.36 | 16 / 0 |
| Bundle delivery gate | 313.07 | 9.81 / 11.50 | 16 / 0 |

The warm runs each recorded 320 cache hits, 16 retained entries and 953,640
accounted cache bytes. Process-lifetime peak RSS was 51,838,976 bytes; this is
not memory attributable only to the cache or one request. These observations
are for local service readers, not HTTP transport, a production tail latency,
an isolated hardware benchmark or an agreed service budget. Operator-reviewed
representative workloads and budgets remain open. No production incident rate
or scientific-utility improvement is inferred from the measurements.

## Final verification

The final full API collection ran after all production and test corrections
were frozen and passed **3,889 tests** (20 existing deprecation warnings,
357.71 s). The guarded runner removed only its owned disposable services and
temporary data. Earlier in-progress runs are not added to the final count.

| Final check | Result |
| --- | --- |
| Full API, owned native PostgreSQL/Redis | 3,889 passed; 357.71 s |
| Full ingestion, inert database/Redis endpoints | 1,275 passed; 34 existing warnings; 8.31 s |
| Full script suite | 429 passed plus 36 subtests; 8.84 s |
| Full frontend components | 507 passed across 27 files |
| Frontend source checks | 35 passed |
| TypeScript | `tsc --noEmit` passed |
| Migrations | Disposable rehearsal through 0062, including populated-history rollback and index-generation guards, passed |
| Dependency locks | API and ingestion `uv lock --check` passed |
| Changed Python checks | Ruff `I,F` passed |
| Patch whitespace | `git diff --check` passed |

Total: **6,135 ordinary tests plus 36 subtests**, with no skipped tests in
these full suites. This batch adds 130 API, 66 script and 54 frontend component
tests, or 250 ordinary tests relative to the preceding completed batch.

Focused evidence includes 83 new public-package tests, 44 HTTP delivery tests
(155 with existing RPS tests), 2 real cancellation tests, 52 actual offline CLI
tests and 14 benchmark tests. After the final corrections, all 241 RPS tests
and all 25 source-impact tests also passed in focused guarded runs. Focused
reruns are not counted again. The final timezone-order regression is included
in the full API collection. All fixtures
are synthetic; no production database or provider credentials were consumed.
Frontend evidence is component/source and captured-wire validation, not a live
production browser/canary. Full Linux image/PR CI was configured, not run here.

## Remaining acceptance and next dependency

Live #74 was reread before implementation and is still OPEN. Its actual local
download/catalogue consumers and mechanical acceptance evidence are materially
stronger; remaining work is not all the same type of blocker:

- **Scientific/rights judgment:** real public consent, disclosure review and
  DR01 scientific template/assessment acceptance cannot be supplied by tests.
- **Technical cross-contract dependency:** ML07 source/release integration
  remains unfinished. File-backed RPS source metadata is not an authenticated
  database source-root/claim or current lifecycle binding. This must be
  implemented, not waved away as merely an external review.
- **Performance/operations:** representative workloads, an agreed service
  budget, exact implementation PR/release CI and separately approved deployment
  remain necessary. No production routes or real release approvals were enabled.

Next priority is ML06 / #70 before real ML09 / #76 training: compile an actual
0054 frozen input capsule into a task-specific Tc dataset and independently
recompute it offline. The existing examples are a fixed candidate inventory,
not trusted labels or splits. Re-derive labels from exact claims/events/states,
recompute formula features, enforce condition/criterion/temporal admission,
preserve exclusions, group dependent examples before splitting, and fit any
preprocessing on training rows only. A successful freeze or public package
does not create `ml_training_approved=true`. Missing reviewed data, applicable
rights or sufficient independent groups must remain an explicit no-go rather
than fabricated baseline results.
