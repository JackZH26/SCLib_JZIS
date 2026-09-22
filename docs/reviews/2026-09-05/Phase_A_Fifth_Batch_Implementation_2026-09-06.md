# SCLib Phase A — Fifth implementation batch

Date: 2026-09-06. Primary issue: [SC07 #49](https://github.com/JackZH26/SCLib_JZIS/issues/49). Tracker: [#41](https://github.com/JackZH26/SCLib_JZIS/issues/41).

Status: local implementation and regression verification, not production rollout or issue closure. This batch starts from the user-authorized commit `c6f05f1ca757f692d3f5169768b2fd75c6f685eb` on `codex/sclib-research-v2`, which contains the preceding upgrades. This batch is not committed or pushed. No production database connection, migration, backfill, deployment, paid extraction or scientific acceptance was performed.

Verified progress is recorded in [SC07](https://github.com/JackZH26/SCLib_JZIS/issues/49#issuecomment-5557554417) and the [master tracker](https://github.com/JackZH26/SCLib_JZIS/issues/41#issuecomment-5557554501). Both issues remain open for their review and release gates.

## Outcome

Material governance is now a shared current-read policy, rather than a different `needs_review` or NIMS check at each endpoint. A retained record can remain available for source inspection without becoming an approved superconductivity result or ML label. Public eligibility, Archive access, scientific evidence and acceptance are separate concepts.

`material-visibility/1.0.0` reports state, catalogue eligibility, Archive availability, current source status, fixed English reasons/warnings and a governance fingerprint. Every response explicitly says `scientific_acceptance: false`. The legacy material table has no revision-bound scientific approval contract; this implementation does not invent one.

## Implemented behavior

### Policy and live source/parent resolution

- The policy uses material governance, freshly evaluated anomaly findings, explicitly linked current source statuses and the resolved parent chain. Cached visibility, extraction-provided approval claims and private admin decisions cannot confer eligibility.
- Material states distinguish `catalogue`, `pending`, `disputed`, `corrected`, `retracted`, `quarantined` and `unknown`. Default catalogue excludes holds; explicit Archive inclusion cannot override provenance restrictions or result-level scientific anomaly rules.
- Explicit negative governance inside retained records imposes a conservative whole-material hold. A record marked retracted does not assert that the entire material is retracted: it produces a pending state with a record-specific reason. More precise dependency-level adjudication remains SC08.
- Current source corrections/retractions add read-time holds without rewriting raw records. Unknown source status remains explicitly unknown and does not itself revoke legacy catalogue compatibility or establish publication approval.
- The adapter resolves up to 32 parent edges. Missing, cyclic or deeper ancestry closes public Archive access because ancestor provenance restrictions cannot be established. This is an unresolved-permission state, not a fabricated retraction. Cycle revisions are independent of input/batch order.
- Source and parent lookups are batched. Formula equality never establishes material identity or parentage.

### Read surfaces and intentional differences

| Surface | Default behavior | Intentional Archive behavior |
| --- | --- | --- |
| Materials list | Current catalogue eligibility; final count and pagination follow that policy | `include_pending=true` includes accessible held rows with reasons |
| Direct material detail | Current policy is always attached | Held rows are directly inspectable; restricted/unresolved-provenance rows return 404 |
| Detail variants | Query actual children, not a stale `variant_count` existence flag | Accessible Archive children are labelled individually; count precedes the 100-row display bound |
| Phase diagram | Parent and child eligibility plus existing per-quantity anomaly gates | Explicit inclusion retains those numeric gates |
| Hydride parameters | Parent eligibility, row-specific source status, typed original quantities and independent validation flags | Flagged rows require Archive inclusion; this does not validate paired calculation inputs |
| Material bookmarks | Current Archive-accessible saved rows, with policy-consistent counts | Held saved materials remain labelled; restricted targets cannot be newly bookmarked or resurface in saved lists |
| Timeline fallback and projection | Current material/parent/source visibility before emitting points | Explicit inclusion preserves anomaly restrictions; projected rows cannot outrun newer raw material records |
| Search/Paper/Ask source occurrences | Explicit material links inherit material restrictions; source lifecycle is separate | Bibliography and legitimate source excerpts remain inspectable; structured restricted occurrences are omitted |
| ML Foundation claims | Stored claim `accepted` plus current material, occurrence, paper and work gates | `include_pending=true`; retracted claims additionally require `include_retracted=true`; direct details carry independent claim/material visibility |
| Sitemap and scientific SEO | Held/restricted materials are excluded; frontend rejects missing or inconsistent visibility for scientific metadata | Archive material pages use `noindex` and omit quantitative scientific JSON-LD/Tc SEO descriptions |
| Retained-scientific-record download | Authorized scientific projection only | Governance version, current warnings and non-acceptance travel with the download; no bare claim-only export |

Source occurrences are not material catalogue rows. A genuinely unlinked source occurrence may still match a reported-claim search filter, with `public_catalogue_eligible=false`, `scientific_acceptance=false` and an unlinked/unreviewed warning. An explicit material link that cannot be resolved is different: its structured occurrence is withheld because the governing provenance cannot be established. Malformed explicit review fields impose a hold. Bibliographic access is not evidence acceptance or a new full-text redistribution permission.

Claims use UUID keyset scanning until enough **finally visible** rows and one lookahead row exist. Filtering only a single limited batch would silently lose eligible later claims; the regression fixture crosses more than 100 held rows. Stored `validity_status=accepted` remains a database enum, not a new scientific decision or a complete ML admission check. `ML_FOUNDATION_PUBLIC_ENABLED` remains disabled by default. Other research-release access controls remain ML07 work.

### Privacy, identity and caching

- Fixed public reasons replace arbitrary legacy reviewer notes. Structured private reviewer/curator metadata is removed from retained records, property evidence, nested source locators, hydride provenance and claim responses. Raw database records are not modified.
- The sanitizer is bounded and removes known structured private fields; it is **not** a general detector of personal information embedded in arbitrary prose or a source-license evaluator. The retained archive is an authorized bounded scientific projection, not an exact dump of every original ingestion field.
- Scientific decisions and result IDs are computed from originals before sanitization. Derived `visibility` is excluded from source-result and claim identity inputs in both API and ingestion; existing frozen export-v1 bytes/schema remain unchanged.
- Mutable material/source/claim/Timeline responses use `private, no-store`, including route errors. Material detail, Timeline and dynamic sitemap reads also avoid Next.js cross-request caching. Historical Ask entries explicitly warn that source status may have changed; they are not silently rewritten as current reviews.
- Timeline does not read or write the previous Redis response cache. It evaluates current governance before any ETag/304 decision. Its data version includes the complete current point set and governance revisions before paging, so a source-only status change can change the representation without changing `Material.updated_at`.
- The visibility fingerprint is not a signed approval, full scientific-content hash or immutable release revision. A transactional governance/release epoch is still needed before safely restoring shared response caching.

All new website-owned labels, warnings and accessibility text are English. This batch does not alter Discovery candidate scores or imply that RPS is an experimental probability.

## Verification

Final verification: **1,699 tests passed** (832 API + 644 ingestion + 61 operational-script + 32 frontend source + 130 frontend component/unit). Targeted tests are not added again to this total.

| Check | Result |
| --- | --- |
| API full suite | 832 passed; one existing FastAPI `regex` deprecation warning |
| Ingestion full suite | 644 passed; placeholder loopback connection settings |
| Operational-script suite | 61 passed |
| Frontend source tests | 32 passed |
| Frontend component/unit tests | 130 passed |
| Frontend TypeScript and Next production build | Passed; 28 static-generation items; API pointed to an unreachable loopback port during build |
| Existing migration head 0049 | Empty database upgrade, empty-ledger downgrade/upgrade, nonempty-ledger rollback refusal all passed in disposable services |
| New schema migration for this batch | None |
| Scoped Ruff I/F and whitespace checks | Passed |
| API/ingestion scientific contract parity | Six modules remain byte-identical |

New regressions cover the six-state actual-route matrix, transitive parent holds, missing/cyclic/deep ancestry, stale variant counts, bookmarks after quarantine, independently flagged hydride rows, typed-original precedence, private metadata preservation in storage/removal from responses, source-only Timeline status changes versus old ETags, claims pagination, malformed/unresolved source links and frozen source-export compatibility. Pure policy, route and frontend checks are complementary; passing synthetic fixtures does not measure production data quality.

API/migration commands, from the repository root:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite api -- -q

api/.venv/bin/python scripts/run_disposable_tests.py --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server --suite migrations
```

Only the capability-checked disposable runner may create/drop test schema or flush Redis. Its temporary services and data were cleaned up; no production target was used. Local macOS success does not establish Linux CI or production performance.

## Offline audit and release gates

See [policy contract](../../VISIBILITY_POLICY.md) and [source/claim/export implementation](SC07_Source_Read_And_Export_Implementation_2026-09-06.md). `scripts/audit_source_visibility_snapshot.py` audits an explicitly supplied authorized governance snapshot separately from frozen source-export/v1. Missing inputs produce an undetermined result, not invented present-day eligibility. No current production prevalence audit was run.

Before rollout:

1. Review the complete diff, create a traceable PR/revision, and verify API/frontend are released together. Keep #49 and #41 open until dependency, review and release gates are satisfied.
2. Obtain an authorized representative snapshot and compare catalogue/Archive exclusions, unknown links and reviewer workload. Conservative whole-material holds may remove unaffected sibling observations until dependency-aware adjudication exists.
3. Benchmark list counts, sitemaps, parent resolution and Timeline on that snapshot. Correct final counts currently require scanning candidate rows and evaluating current raw governance; removing stale shared caches increases database/CPU work. This batch makes no production latency claim. Design an indexed, transactionally invalidated governance projection or approved-release epoch before restoring caching, and re-run the same change-after-cache tests.
4. Keep research public-access feature flags closed until ML07 release/export permissions are implemented. This policy is not a complete temporal split, leakage, license or accepted-label gate.
5. Implement SC08 historical correction/retraction propagation and source revision dependencies separately. Current-read holds do not rewrite frozen datasets, adjudicate old claims, or replace missing source lifecycle synchronization.

Recommended next batch: **SC06 #50**, rebuilding Timeline around result identity, explicit date basis and honest sampling/coverage. Existing coarse deduplication, date fallback and legacy aggregate sort semantics remain documented limitations; the 60-event reviewed evidence pilot remains a separate research gate.
