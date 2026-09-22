# Tenth implementation batch — source revisions and temporal ML safeguards

Date: 2026-09-07. Branch: `codex/sclib-research-v2`.

Priority: [ML01 #57](https://github.com/JackZH26/SCLib_JZIS/issues/57), following
the ninth-batch checkpoint `5585292`. This is local implementation and synthetic
verification, not production rollout, historical scientific review or issue closure.
No production database, source archive, vector index or published dataset was
backfilled. The existing ML Foundation public-access flag remains disabled by default.

## Why this is the next dependency

ML03's research loader and subsequent temporal datasets need to distinguish a
paper's initial submission from the first version that actually contains a
particular result. The former mapper assigned a record's extracted date or the
minimum paper date to `available_at`. The old arXiv pipeline also reused
work-level source caches while obtaining mutable current metadata. Together these
could make a newly introduced Tc or structure result appear available too early.

This batch removes that unsupported inference. **Unknown is the correct output
when exact version, content, locator and result association have not been verified.**

## Delivered boundaries

| Layer | Local delivery | What it does not prove |
| --- | --- | --- |
| Source registry | Migration `0052_source_provenance`; three append-only tables; internal insert-or-verify importer and exact reviewed witness resolver | No source-history campaign, authenticated human review UI or production registration |
| arXiv capture | Explicit version selectors; immutable content-addressed bytes and version anchors; separate metadata and actual bounded NER-input hashes | An explicit URL is not independently authenticated content, a public date or a qualified result witness |
| Result projection | Shared `temporal-provenance/1.0.0`; mapper v1.4 removes paper-date fallback | Known-by is not first discovery, scientific approval or ML training eligibility |
| Public claim reads | Registry-derived temporal fields, separate legacy date hint, inclusive aware cutoff, current visibility and fail-closed error handling | Live pagination is not a frozen historical dataset or historical review replay |
| Dependency gate | Deterministic bounded offline DAG evaluation; own result time plus all declared input times; separate public-knowledge/capture modes | No automatic discovery of omitted dependencies, database DAG locking or release freezing |
| Dry-run reconciliation | Complete per-claim old-projection comparison in the existing planner summary; changed/unchanged and unverifiable counted separately | No live-database comparison, date repair, historical bundle rewrite or database mutation |

## Scientific scheme

The distinctions are:

```text
Work (bibliographic group, used for split grouping)
  -> Source revision (explicit version and qualified public time)
     -> Capture (representation + exact bytes hash + observed capture time)
        -> Source occurrence (existing claim + exact locator + pinned review)
           -> Result known-by assessment
              -> Declared dependency temporal gate
```

Multiple explicitly reviewed version occurrences can reference one existing
claim. Equal formulas, equal Tc values or semantic fingerprints never perform
that merge automatically. The new registry does not create new material IDs or
rewrite existing claim, work or source-export snapshot identities.

The earliest qualified version witness is a conservative **known-by** bound.
A later local capture does not itself postpone historical public availability;
operational replay separately requires local capture by the cutoff. Date-only
values do not silently become midnight UTC. A valid time witness cannot override
current source/material holds, missing source rights or scientific QC.

A dependent node requires its own qualified time and every declared dependency:
the effective time is their maximum. Unknown inputs, missing dependencies,
incomplete declarations and cycles hold the affected result and descendants.
An unrelated acyclic component remains assessable. A recent recomputation from
old data is not automatically an old public result. Reconstructible feature
policies require separately pinned algorithms, constants and source inputs.

## Persistence and failure behavior

The source registry uses composite foreign keys to enforce claim/work,
revision/work, capture/revision and review-artifact-kind bindings. NULL work
identities cannot bypass the occurrence association. UPDATE, DELETE and TRUNCATE
are rejected by database triggers. Import collisions with different content fail
the whole bundle; identical reimports verify existing rows. Dry-run rolls back
its savepoint and the service never commits the caller's outer transaction.

Reviewed status is not accepted as a naked flag. The resolver checks the actual
review artifact, policy schema, pinned hashes, locator and linkage, current
claim content digest, accepted bibliographic work mapping and source/capture
integrity. A changed upstream claim or review invalidates stale witnesses.
This digest is deliberately conservative: even some non-scientific metadata
changes can require new review.

The initial registry has **no supersession/amendment workflow**. Pending
occurrences keep a claim uncertain; a later separate reviewed occurrence does
not automatically cancel earlier unresolved evidence. Unresolved records are not
updated in place. Until an additive correction/review contract exists, do not
mass-import pending bindings expecting an automatic later promotion. Keep capture
diagnostics separate and register only explicitly reviewed associations through
the internal reviewed-bundle boundary. This limitation remains a rollout gate.

Migration creates empty tables without altering old raw records or dates. It
adds an existing-claim composite unique key, which still needs an operational
lock/backup rehearsal. Empty-registry downgrade is tested. A nonempty registry
refuses destructive downgrade, preserving evidence rather than silently dropping
it. This is not a rollback procedure for a deployed, populated registry.

## Capture, disclosure and compatibility

Current OAI title/abstract plus a pinned historical body is mixed, unverified
input. The pipeline records separate artifact, metadata, assembled-document and
actually truncated NER-document hashes; none can substitute for another. PDF
fallback currently uses metadata for NER, not PDF body text. Capture preparation
and downstream attempts must remain distinguishable, including on failed runs.

Fresh downloads replace reuse of the ambiguous work-level cache. Legacy cache
objects are not deleted. Explicit version anchors use create-only generation
preconditions and exact-byte verification. Differing bytes for the same version
and representation fail closed, including legitimate provider repackaging until
an explicit reconciliation policy exists. This has request, storage and retry
costs requiring deployment review. The downloader's inherited complete-body and
tar-decompression resource limits are not solved by metadata-size bounds.

Capture diagnostics and stored temporal assertions are excluded from legacy
scientific identity hashing and stripped recursively from public raw DTOs.
The separately resolved typed claim envelope exposes only bounded coordinates,
identifiers, hashes and dates, not storage objects, source quotes or private
review references. Existing scientific source fields remain identity-bearing.
APS retains its independent transient full-text processing and deletion policy.

The compatibility claim `available_at` is now the qualified known-by UTC date
or null; the old stored value is labelled `legacy_available_at`. Existing stored
rows are not edited by reads. Consumers needing exact cutoffs use the full
timezone-aware timestamp, not the date alias. Website-owned copy remains English.

## Acceptance record and remaining work

Verification uses guarded, capability-checked disposable PostgreSQL/Redis and
mocked external providers. Final integrated checks:

| Check | Result |
| --- | --- |
| API full suite | 1,409 passed; one pre-existing FastAPI `regex` deprecation warning |
| Ingestion full suite | 789 passed |
| Scripts | 102 passed, plus 36 separately reported subtests |
| Frontend source / unit suites | 35 / 245 passed |
| Total ordinary tests | 2,580 passed; excludes the 36 script subtests |
| TypeScript | `tsc --noEmit` passed |
| Migration rehearsal | Full head upgrade, empty downgrade/re-upgrade, raw preservation and nonempty source/correction ledger refusal passed |
| Static checks | Scoped changed-module Ruff I/F and `git diff --check` passed; API/ingestion shared-policy byte parity passed |

Disposable test services and their temporary data were removed by the guarded
runner. No production data was removed. No new frontend build/browser acceptance
or remote Linux/Docker CI run is claimed for this backend batch. Synthetic
fixtures are not a gold scientific dataset or a source-permission audit.

Remaining ML01/research gates include:

1. Authorized review/adjudication and additive correction/supersession semantics;
   real source version-history verification and explicit result associations.
2. Bounded, revision-aware shadow loading and immutable claim revisions (ML03),
   then complete dependency closure and release freezing (ML04).
3. Source-generation-aware chunks and hydrated temporal retrieval (RG02/RG03).
   Search bibliographic year filters, Ask prompts and bundle-asserted RPS cutoffs
   do not gain historical correctness from this batch.
4. Release-only public access and recursive source permissions (ML07), reviewed
   pilot evidence (ML08), and task-specific dataset/split construction (ML06).
5. Rehearsed production migrations, real arXiv/GCS behavior, resource/retention
   limits and a staged rollout approved against actual data.

Retrieval cutoffs do not establish absence of LLM pretraining contamination.
Model provenance and prospective evaluation remain separate research requirements.
ML01 remains open; GitHub issue status has not been mutated in this batch.

## Detailed contracts

- [Source registry](../../SOURCE_PROVENANCE_REGISTRY.md)
- [Capture provenance](../../ARXIV_CAPTURE_PROVENANCE.md)
- [Temporal consumers and regression matrix](../../TEMPORAL_CONSUMERS.md)
- [Safe testing](../../TESTING_SAFELY.md)
