# Full-retrieval cutover: index compatibility

The operator selected complete index compatibility before website cutover,
preserving Search, Ask and Similar. Ingestion and outbound alert delivery
remain deferred. Production still serves the previous version.

## Actual cloud readback

The existing deployed index was queried read-only, without embedding calls
or vector writes. A bounded selection of 20 SQL IDs (from the ordered and
longest-text samples) returned 18 finite, nonzero 768-dimensional vectors and
two explicitly missing IDs. None of those 18 vectors had the new content or
revision hash namespaces. This is a deliberately bounded diagnostic sample,
not a random corpus-quality estimate or an exhaustive missing-ID inventory.

The first mixed-batch call failed with `NotFound`. Individual reads established
the missing members, and an actual mixed response showed that the provider
names several missing IDs in a comma-separated diagnostic. The adapter now
recognizes that exact diagnostic only for distinct IDs in the current request,
then verifies the remaining members under the same bounded deadline. Other
errors are not converted to absence, and a conflicting existing member still
prevents publication.

The changed `read` method was extracted unchanged from the current source AST
and executed with the actual configured provider client. Its real mixed-batch
read returned the same 18 vectors and two missing IDs. The receipt records the
module hash; this is method-level operational verification, not a signed-image
deployment. The initial single-ID-only implementation failed the mixed
multi-ID response; that failed attempt remains in the private delivery logs.

These observations do not establish that historical positional vector IDs
correspond to the currently retained text. No historical completion metadata,
source binding or parser identity was invented to activate them.

## Implemented corpus preparation

[The private input pack](../../LEGACY_INDEX_PREPARATION.md) streams the full
restored database in a read-only transaction, keeps exact old rows and paper
snapshots, and prepares bounded embedding inputs with complete character
coverage. It supports source-atomic checkpoints, strict replay comparison,
on-disk partitions and full manifest verification. Unknown origin and
historical completion remain explicitly unknown.

The real-data worker uses the existing upgraded clone in its internal Docker
network, with no cloud credentials and no application writes. It is limited
to two CPUs and 4 GiB. The initial attempt was stopped after identifying
repeated paper-snapshot computation; its partial pack/log remains intact.
The revised worker shares a bounded paper cache inside the same transaction.
Its complete result is retained separately from the input-preparation
test report. A successful input pack is not an active or publishable index.

The full run completed its preparation and verification in **1,698.834 seconds**:

| Measurement | Actual value |
| --- | ---: |
| Retained source chunks | 1,117,982 |
| Papers with retained chunks | 74,848 |
| Source characters | 1,635,763,861 |
| Source UTF-8 bytes | 1,679,685,021 |
| Split source chunks | 15,222 |
| Prepared embedding inputs | 1,179,386 |
| Bounded partitions | 1,180 |
| Full input characters, including prefixes/overlap | 1,658,125,174 |
| Full input UTF-8 bytes | 1,703,379,822 |
| Local cl100k tokens | 519,140,487 |
| Maximum local input tokens | 1,536 |
| Locally inadmissible embedding inputs | 0 |
| Private pack file bytes | 4,392,534,016 |

The source counts, character counts and byte counts match the independent
earlier inventory. Every stored source, paper and member was verified, with
complete retained-character coverage and bounded partitions. Four separate
manifest roots and the complete file digest are retained in the receipt.
Original-source coverage, historical vector correspondence, provider embedding
completion and activation eligibility remain explicitly false. The number of
papers above is the inventory with retained chunks, not the total catalogue.

A second container, with networking disabled and both source and pack mounts
read-only, independently recomputed the complete report in **349.525 seconds**.
Every result matched, and the full file SHA-256 remained
`e159c8ccf9719fe3afc7a269c723c3cceff246af34e7e7f8be8e2f8a4daab591`.
All three owned preparation/verification containers were then removed. The
private pack, producer source, logs and receipts remain available on the host;
the upgraded database clone remains separate from production.

The final production read returned HTTP 200 for both `/v1/version` and
`/readyz`, with version `d26fc09` and healthy PostgreSQL/Redis dependencies.
The pause marker and inactive ingestion/Discovery timers remain, while the
maintenance backup timer stays active. Deployment variables remain `paused`
and `console`. An initial probe used the nonexistent `/healthz` route and
returned 404; the corrected readiness request is retained in the final receipt.

## Verification and retained failures

- Input pack: 21 offline cases, including Unicode, whitespace, OCR, tables,
  source coverage, 2,002-member partitioning, interrupted transactions,
  replay drift, source/member tampering and unsafe file destinations. The
  additional real child-process `os._exit` case recovers only the committed
  checkpoint; no normal connection close or application rollback runs in
  that child.
- Index adapter, generation/operation regression and seven actual native HTTP
  captures: 140 passed, with one existing FastAPI deprecation warning. All
  retained capture bytes and 297/600 source pins were independently checked.
- The first preparation CLI test found an unterminated SQL literal. It was
  corrected and the complete 20-case suite passed.
- New captures added two root script inputs. The frontend's exact inventory
  assertions were updated from 598 to 600, retaining per-file hash checks.
  The first frontend attempt with the old counts is retained.
- A concurrent broad rerun encountered two 5-second frontend test timeouts
  and one document-worker timeout. The 44-case document module subsequently
  passed in isolation without changed timeouts or assertions. The complete
  frontend then passed all 1,895 cases using two workers, with unchanged
  5-second test limits; all 46 source checks and TypeScript also passed.
- The stable complete offline rerun passed 2,329 cases and 97 subtests. The
  subsequently added abrupt-process-exit case and security tests passed in
  the final 35-case focused suite. A preceding offline run had loaded the old
  scanner fingerprint set while its ignore file was being updated; that
  mismatched run is retained and was replaced by the stable full rerun.
- Incremental scanning found 13 matches across three immutable capture
  fingerprints. Each matched value was privately decoded and compared with
  an actual synthetic request key. Exact commit/file/rule/line exceptions
  and a sanitized triage receipt were retained; the final scan found no
  unhandled leaks. No rule-wide or directory-wide exclusion was added.

## Work still required before cutover

1. Admit the explicit retained-legacy representation in the new retrieval
   contracts without calling it original scientific evidence.
2. Implement durable, bounded embedding attempts and actual completion receipts,
   using the complete prepared input inventory and an explicit cost ceiling.
3. Implement scalable generation storage/publication and atomic activation;
   the existing 1,000-member SQL pilot remains bounded and unchanged.
4. Publish to an isolated destination and verify all declared IDs, hashes and
   metadata; preserve the old index while it serves the current website.
5. Exercise full Search/Ask/Similar, current-source holds, recovery, cold
   performance, final-head CI, signed images and production acceptance.

The legacy keyword fallback is not the selected public release. Human
scientific review remains outside this deployment work; technical migration
does not confer scientific acceptance or source-use approval.
