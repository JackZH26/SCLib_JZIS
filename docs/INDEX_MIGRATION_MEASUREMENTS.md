# Synthetic chunking and index-migration measurements

This opt-in RG03 tool measures a fixed local engineering fixture. It does not
connect to an existing database, cloud index or embedding provider. It does not
approve scientific claims, training examples, source redistribution, production
deployment or an operational SLA.

It complements the [generation contract](INDEX_GENERATIONS.md) and
[embedding-completeness contract](EMBEDDING_COMPLETENESS.md). The report version
is `index-migration-rehearsal/1.0.0`; existing schema/restore measurement versions
and artifacts remain unchanged. This batch adds no database migration.

## Two comparisons, with different meanings

| Measurement | Before | After | Interpretation |
| --- | --- | --- | --- |
| Chunk construction | Exact historical chunker source at `44fd6ce377c89d4b4e1b78dbe082f420c33b8814` | Current installed chunker | Same fixed synthetic inputs and current recorded tokenizer/runtime; not the historical installed environment |
| Index lifecycle | Complete two-paper G1: 5 + 2 passages | Complete two-paper G2: 3 + 2 passages, then explicit G1 rollback | Real local ingestion, SQL, retained vector bytes, validation and generation-filtered hydration; synthetic embeddings and synthetic vector-ID ordering |

The historical file is an immutable `.py.txt` fixture, not an importable module.
Only the fixed bounded regular file with SHA-256
`43ee1e764a32fd39ac3c7f13c99bf94e525a54ab11a46ad4be0ea36336435139`
may execute. No CLI accepts replacement baseline code. Execution uses the current
runtime, so raw timings do not reconstruct historical production performance.

The 12 fixed cases cover long sentences, long title/section-heading metadata, OCR,
CJK, formulas, tables, Unicode whitespace, duplicate section headings, metadata
and override abstracts, state-aware positive/negative Facts, and the Facts cap.
Ten original/abstract cases compare both algorithms. Facts are current-only:
their changed scientific semantics make an old/new quality comparison invalid.

## Denominators and unknown values

- Full-input local token counts include metadata prefixes. Oversized chunks,
  stored-count mismatches and explicit metadata truncations are separate counts.
- Current original-passage coverage is the union of exact source intervals by
  section path, in both characters and UTF-8 bytes. Overlap does not multiply
  coverage. Identical section headings are distinct source locations. This is
  coverage of parsed synthetic text, not PDF extraction recall.
- The old chunker has no comparable source locators: its locator coverage is
  `null`, not zero and not guessed from string matching.
- Facts report input, renderable/eligible, unrenderable, retained and cap-skipped
  records. Parent records stay atomic. The 42-record fixture intentionally emits
  40 records and reports two cap exclusions; this is not complete Facts coverage.
  A non-detection keeps its lower tested temperature and is not a Tc=0 label.
- Failure canaries record the number and unit of input items as well as rejected
  cases. One rejected ten-input embedding response counts as ten rejected input
  items, not one. Simulated provider statistics are explicitly marked simulated.
- Query measurements retain three raw samples per phase. They exercise the real
  disposable adapter and SQL verification/hydration, but the adapter orders by
  synthetic vector IDs: there is no scientific relevance or real ANN claim.
- Measured local document tokens and retained float32 bytes are not provider
  billing. Provider tokens/cost, real ANN latency, production coverage, recall,
  precision, throughput, RPO/RTO and production cleanup remain `null`.

G1/G2 use unchanged paper metadata, raw scientific records and source-lifecycle
status. Only the parsed representation/parser label and resulting chunks differ.
This is an index-representation migration, not a corrected scientific source.
It permits rollback without bypassing current source or permission holds.

The worker interrupts a real disposable publication after the first point is
written. It observes one of five G2 members, retains a rejected validation and
checks that partial activation is refused. Read-only repair diagnostics are
fingerprinted against unchanged pointer/event/epoch and transport state; explicit
publication then resumes with one already-present and four newly written points.
This is not automatic repair or a production orphan inventory. A valid G2
activation also succeeds inside its service savepoint and is then rolled back
by the outer transaction. Fresh SQL checks require unchanged state; subsequent
commit and exact-key replay must create only one new activation event.

One real private answer receipt selects passages from both measured papers.
One real frozen research dependency closure binds those same papers through
material claims and source memberships. Full answer/release/pin row hashes,
manifest hashes and verified artifact inventories are compared before, after
and after rollback. Synthetic release fixtures are not approved research data.

## Run on newly owned services

Use the repository's installed API runtime with ingestion dependencies and the
`cl100k_base` tokenizer asset already available locally. Before tokenizer/app
imports the worker installs a Python socket/DNS guard allowing only its owned
loopback service ports; provider factories are separately forbidden and counted.
This is not an operating-system network sandbox. Missing tokenizer assets cause
failure rather than a download.

For a native macOS installation, select the actual installed binaries and a
new report filename beneath an existing private directory:

```bash
api/.venv/bin/python scripts/run_index_migration_rehearsal.py \
  --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server \
  --report /private/approved-directory/new-index-measurement.json
```

The default backend is Docker. Docker support is not evidence that a specific
release image or remote CI run passed; retain that execution separately when
performed. No DSN, existing index, model, corpus, arbitrary command, reuse flag
or production target can be supplied. The parent owns fresh PostgreSQL/Redis,
verifies their capability and empty starting schema, then runs migration and
measurement in separate fresh worker processes. It never imports API test
fixtures to perform migrations.

Stage files are private, bounded, single-link regular files. FIFO/device/symlink
inputs fail admission without blocking the parent. Source capture covers bounded
API, scripts and ingestion Python inputs, lock/config files and the exact frozen
baseline. File hashes, inventory hash, HEAD and dirty-state metadata are recorded;
inputs must remain unchanged throughout execution. This conservative inventory
does not imply that every listed file executed or that dependencies match a
production image.

Success publication requires all checks, exact run/schema binding, unchanged
sources and cleanup of only the originally owned services/directory. Publication
uses a held-directory, no-clobber, mode-0600 file. An existing destination,
replaced directory, worker failure/timeout, failed cleanup or changed source
cannot produce a success report. Failed cleanup retains private diagnostics.
Never publish capability files, service logs, private paths, DSNs, source text
or release artifact bytes with a measurement.

## Read a retained report

```bash
PYTHONPATH=scripts api/.venv/bin/python -c \
  'from pathlib import Path; from index_migration_contract import loads_report; r=loads_report(Path("/private/approved-directory/new-index-measurement.json").read_bytes()); print(r["status"], r["report_sha256"])'
```

The offline report validator initializes no application, database, provider or
tokenizer. It rejects unknown fields, duplicate JSON keys, malformed identities,
nonfinite values, excessive resources, altered authority/null metrics and broken
closure hashes. The embedded hash binds the canonical body without its own
field; retain the full-file SHA-256 separately, including the final newline.
Neither checksum authenticates the person who ran the experiment.

Retain each actual report under a fresh filename. Do not update an old report
to claim it ran a later commit, different source bytes or a corrected test.
Rerun after any relevant source change. Documentation-only changes can link the
original measurement without altering its captured source identity.

## Release boundary

This fixture supplies repeatable local coverage, rejection, truncation,
build/query timing and recovery evidence. Different G1/G2 workloads (7 versus
5 members), tiny samples, shared host conditions and synthetic vectors do not
establish a speedup, production capacity or model quality. Full production
rewriting is not required to pass this disposable engineering exercise.

Before production, separately approve the target, source-use review, costed
canary, complete intended membership and rollback/retention policy. Measure real
provider truncation/tokens/billing and actual ANN quality on a reviewed corpus;
unknown remote IDs cannot be inferred absent from matching declared-member
counts. See the [generation operational boundary](INDEX_GENERATIONS.md).
