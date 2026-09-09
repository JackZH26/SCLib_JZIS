# Immutable retrieval generations and controlled activation

Status: bounded local RG03 implementation, not a production index migration.
Related: [RG03 / #69](https://github.com/JackZH26/SCLib_JZIS/issues/69),
[complete-input receipts](EMBEDDING_COMPLETENESS.md),
[typed evidence](RAG_EVIDENCE_LINEAGE.md). Additive schema:
`0062_index_generations` after `0061_embedding_receipts`.

## What is authoritative

The active SQL pointer selects one immutable, fully declared generation.
Mutable `chunks` rows and positional legacy vector IDs are never an ANN
hydration authority. Each member retains its full SQL chunk snapshot, bounded
Paper attribution, actual canonical float32 vector bytes, exact 0060 evidence
and 0061 completion-receipt identities/hashes, source snapshot, parser and
chunker versions. Retained bytes allow rollback after current chunks are
replaced or removed. A hash-only history would not provide that capability.

This is a private operational index, **not** a source-use license, scientific
acceptance, independent-evidence count or ML dataset release. A new parser
label records the producer of the indexed representation; the Facts renderer
label does not certify the upstream NER extractor. Unknown historical parser
labels are not silently invented. Actual arXiv/APS parsing and chunk creation
now propagate producer labels prospectively.

| Boundary | Contract |
| --- | --- |
| Generation | Explicit UUID; immutable logical-index/profile/resource/manifest header |
| Member/vector ID | `ig62_` + generation UUID without hyphens + `_` + exact chunk-revision SHA-256 |
| Manifest | SHA-256 of ASCII TSV, sorted by vector ID: ID, full-text hash, vector hash, newline |
| Full text | Exact UTF-8 bytes; no truncation or whitespace normalization |
| Vector | 768 canonical big-endian IEEE754 binary32 values; exact bytes retained |
| Profile | Google Vertex AI `text-embedding-005`; document/query retrieval tasks kept distinct |
| Resource | Explicit project/location/index/endpoint/deployment, `COSINE_DISTANCE`, feature normalization `NONE` |
| Local pilot | 1–1,000 members, at most 16 MiB aggregate retained chunk/Paper JSON; retrieval adds smaller byte limits |
| Activation | Append-only event, exact predecessor event UUID, monotonic event number and caller idempotency key |

Tables: `index_generations`, `index_generation_members`,
`index_generation_validations`, `index_activation_events`,
`index_active_pointer` and its integrity epoch. Header/member/validation/event
history is immutable; pointer mutation is trigger-controlled. Direct SQL also
checks closed shapes, exact bindings, actual float32 hashes, complete manifests,
freshness and current Paper/accepted-Work lifecycle holds. Populated downgrade
refuses to erase history. Frozen 0052–0061 schemas are not modified.

## Staging and live ingestion

`stage_generation()` preflights count and aggregate JSON bytes in SQL before
loading private payloads, independently recounts document inputs and verifies
current evidence/receipt binding. Tokenizer initialization precedes the shared
SQL fence. The fence order is 540 → 560 → 620; operational index staging does
not use the unrelated research-publication fence or acquire publication rights.
Services default to dry-run, use savepoints and never commit the caller's outer
transaction. Exact replay preserves the entire database state, including epochs.

Both real arXiv and APS writers accept an optional **SQL-only**
`generation_stager(session, chunks)` callback after evidence/receipt persistence
inside their existing transaction. `prepare_generation_items()` derives exact
receipt-bound inputs from those actual completed chunks; the core rechecks
them independently. Callback failure rolls back the paper, replacement chunks,
evidence, receipts and staged generation together. Cloud publication must never
run in this callback. Normal ingestion does not automatically create, publish
or activate a generation; orchestration must explicitly choose the bounded
generation membership. Legacy uploads remain legacy and are not consumed by
the new ANN readers.

## Publish, read back, validate, then activate

1. Stage the complete declared member set and commit SQL.
2. Publish retained vectors with immutable generation IDs. Before upserting,
   read existing IDs and refuse a conflicting vector/identity/year binding.
   Only missing members are upsert candidates. Interrupted publication is
   resumed with the same generation; an acknowledgement is not validation.
3. Read back every declared ID and compare generation/profile/resource and
   actual vector/content/revision bindings. Each completed observation gets a
   new canonical UUID and `observed_at` UTC timestamp. Retry the *same report*
   with its original UUID/time; do not restamp a stale report.
4. Retain the closed validation observation. Its scope is
   `declared_generation_members`. Successful validation requires the complete
   declared manifest, not equal SQL/vector totals.
5. Explicitly promote with the exact current activation event as predecessor.
   First activation requires explicit `none`. SQL checks both DB receipt age
   and observation age within 15 minutes; at most 30 seconds future clock skew
   is allowed. These are trusted-operator clock reports, not cryptographically
   signed provider attestations.
6. Roll back by rereading/revalidating a retained generation and appending a
   new `rollback` event with the exact current predecessor. G1 → G2 → G1 has
   three different activation events: a request pinned to the first G1 cannot
   pass a currentness check against the third event.

Current science/permission holds are never undone by rollback. A historical
generation may be ineligible for reactivation after a source correction.
An already active snapshot is still checked against fresh read-side holds.

### Remote inventory limits

The public Vertex Matching Engine API supports known-ID readback and full
datapoint returns. The implementation uses the low-level public MatchService
surface so numeric restrictions and actual vector bytes are not silently
omitted by a higher-level wrapper. It verifies the actual streaming index,
dimension, distance, normalization, public endpoint and deployed-index binding.
Unsupported private endpoint capabilities fail closed. A project number in a
resource name is accepted only under the exact configured endpoint/deployment
contract; no number-to-project mapping is guessed.

Known-ID readback **cannot enumerate unknown remote IDs**. Public observations
therefore always report `full_inventory_observed=false`. A matching declared
manifest may be activated because every live hit must also pass closed SQL
membership and hash checks. Unknown IDs cannot become evidence, but could
still affect ANN recall. They are not proof of successful full-index cleanup.
The disposable adapter can enumerate its synthetic generation inventory and
exercise orphan detection. It does not emulate model quality or real ANN recall.

`repair_plan()` is read-only: missing IDs, observed orphans, hash mismatches,
pending known IDs and bounded upsert candidates; delete candidates are always
empty. Profile/resource incompatibility refuses the operation. Inactive
generation members remain rollback history, not automatically deletable
tombstones. Corpus-wide inventory, tombstone/retention review and actual cleanup
are still separate acceptance gates. No million-chunk parity claim is made.

SDK RPCs use a remaining deadline, capped per call, with one SDK attempt.
Provider/client credential construction and an in-flight blocking SDK call are
not proven forcibly cancellable. Similar stops subsequent work after timeout;
request-level fallback/retry policy is separate from the SDK attempt count.

## Private operator commands

Use an approved API runtime with dependencies/tokenizer assets installed, an
explicitly selected `DATABASE_URL` and normal runtime credentials/configuration.
The CLI requires an explicit PostgreSQL target and checks the exact supported
schema head **before** opening the operator session; it does not run migrations.
Never place credentials or private staging JSON in git, shell arguments or
public logs. The commands below use placeholders, not production targets.

```bash
api/.venv/bin/python scripts/index_generations.py stage --input /private/path/staging.json
api/.venv/bin/python scripts/index_generations.py inspect --generation-id GENERATION_UUID
api/.venv/bin/python scripts/index_generations.py publish --generation-id GENERATION_UUID
api/.venv/bin/python scripts/index_generations.py observe --generation-id GENERATION_UUID
```

All four commands default to preview/read-only SQL with **no provider calls**.
The private stage file has exactly `generation_id`, `logical_index`, `resource`
and `items`; each item has `chunk_id`, `receipt_id`, `vector`, `parser_version`.
It is bounded to 16 MiB and rejects duplicate JSON fields/nonfinite constants.
Only actual completion-bound vectors are admissible; the CLI does not create
embeddings from an arbitrary historical chunk or invent completion receipts.

After separately approving the target and any costs:

```bash
api/.venv/bin/python scripts/index_generations.py stage --input /private/path/staging.json --apply
api/.venv/bin/python scripts/index_generations.py publish --generation-id GENERATION_UUID --apply
api/.venv/bin/python scripts/index_generations.py observe --generation-id GENERATION_UUID --read-remote --apply
api/.venv/bin/python scripts/index_generations.py activate --generation-id GENERATION_UUID --validation-id VALIDATION_UUID --expected-event-id none --idempotency-key REVIEWED_KEY --action promote --apply
```

`publish --apply` explicitly writes vectors but never changes the active pointer.
`observe --read-remote` performs a possibly billed read; only `--apply` persists
its validation. `activate` without `--apply` checks its proposal in a rolled-back
savepoint. Later promotion/rollback must replace `none` with the exact current
event from `inspect`. Only the CLI, not its services, commits the outer session.

Inspection returns the current active generation/event and whether the requested
generation is current; it does not require matching current cloud configuration.
Activation output separates the historical/requested `activation_receipt` from
`current_active_generation`, `receipt_is_current` and actual pointer change. An
exact retry can return an older receipt after a later event; it is not a new
activation. An interrupted/failed command may have an unknown commit/upsert
outcome. Inspect state and reuse the **same** activation idempotency key.
Errors never print raw exceptions, SQL parameters, text, vectors or credentials.
Summary timing is local wall time; estimated cost stays unknown, not zero.

## HTTP behavior and release sequencing

Search, Ask and Similar pin the generation before ANN and accept only matching
retained members. Lexical candidates are restricted to that same generation;
frozen attribution is distinct from current Paper/Work/Material governance.
Search rechecks numeric year against the retained SQL chunk, not only remote
filter tags. Restricted/stale evidence withholds excerpts and material payloads.
Post-LLM checks rehydrate immutable members, compare the exact activation event
and reread holds. Search and Similar also check the final active pin.

All three response models add a closed `retrieval_generation` envelope:
`version=index-read/1.0.0`, `mode`, `generation_id`, `activation_event_id`,
`manifest_sha256`. Generation mode requires all three identity fields; explicit
`legacy_lexical_only` requires all three null. No cloud resource or text is in
this public envelope. It is not a completeness, rights or scientific-quality score.
New authenticated Ask responses now retain these exact generation/event pins
and final output in [private answer-history receipts](ANSWER_HISTORY_RECEIPTS.md).
Old history stays explicitly unpinned. Historical integrity checking is not
currentness revalidation, scientific acceptance or deterministic regeneration.

With no active generation, Search/Ask use legacy lexical-only retrieval and
never positional ANN. Similar returns a sanitized 503. Consequently, deploying
the API without a reviewed active generation changes availability and recall;
do not treat this batch as an unattended production rollout. A 1,000-member
canary is an intentionally limited corpus, not a replacement for the full site.

Before production: separately authorize a source-use-reviewed, costed canary;
apply migrations through the migration job; verify Linux/release-image CI;
stage and verify the complete intended corpus; rehearse activation and rollback;
measure coverage, rejected inputs, provider tokens, actual cost, build/query
latency and family/task retrieval evaluation against a frozen baseline. Agree
release thresholds before reading held-out results. No cloud call, migration,
source redistribution or live activation is authorized by this document itself.
