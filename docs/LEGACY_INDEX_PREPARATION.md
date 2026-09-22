# Retained legacy input preparation

The September 22 cutover decision is to preserve Search, Ask and Similar and
complete index compatibility before public cutover. Ingestion and outbound
alerts remain paused. A keyword-only release is not the selected path.

`scripts/prepare_legacy_index_pack.py` prepares the existing retained text for
that migration. It does not collect sources, call a model, write an application
database, publish vectors or activate a retrieval generation.

## Source and lineage boundary

The input is the explicitly named restored database, read in one repeatable-read,
read-only transaction. Exact chunk rows and deduplicated paper snapshots are
retained privately in SQLite. The bibliography is selected by the existing
`sclib_index_paper_snapshot_v1` contract. Source IDs must be strictly ordered;
the final source count must equal the database inventory in that transaction.

The representation is `retained_legacy_snapshot`. Historical parser version
and embedding completion are null, original-source verification is false,
permission remains unresolved and scientific acceptance is false. This is a
preparation format, **not a newly admitted API evidence kind**. A retained
database passage, including a legacy Facts rendering, is not reclassified as
verified original text or an independent scientific claim.

The supplied backup digest is recorded as an operator-declared identity;
this tool does not independently authenticate the backup file. Producer source
hashes and the tokenizer distribution version are also recorded.

## Exact text coverage and bounded partitions

Inputs fitting the existing local 1,536-token document limit stay byte-for-byte
intact. Longer inputs use the existing source-preserving chunker, with at most
128 local overlap tokens and a separately retained bounded metadata prefix.
Coordinates always refer to the unchanged legacy text, not a PDF or source
capture. Every retained character must be covered, including whitespace,
Unicode, long sentences, tables and OCR. No text is silently discarded.

The pack stores source text once; members store coordinates, prefix, actual
full-input token/character/byte counts and hashes. Members are grouped into
partitions of at most 1,000 inputs and 16 MiB of **embedding input bytes**.
This is not a promise that the existing SQL generation's separate snapshot
budget would fit. Paper and source snapshots have separate 16 MiB per-row
admission limits. The SQLite file is capped at 32 GiB.

Local cl100k counts are not provider token measurements. Whitespace-only or
otherwise inadmissible model inputs remain represented and are explicitly
counted; they cannot be treated as successful embeddings. A later embedding
worker still needs strict `auto_truncate=false`, actual per-input untruncated
provider statistics and vector/content bindings.

## Recovery and verification

Use an existing directory owned by the operator with mode 0700. Pack files
are created exclusively with mode 0600; symlinks and multiply linked files
are refused. Checkpoints commit complete source rows and their members.
An interrupted uncommitted batch rolls back. `--resume` requires the same
producer specification and compares every already-retained source identity
and hash while reading the same declared input snapshot again. A changed
source or bibliography is a hard failure, not an update to old history.

Sealing streams all stored paper, source and member content, independently
recounts full inputs, reconstructs coverage, checks partition limits and
creates separate paper/source/member/partition manifest digests. A subsequent
read-only verification must reproduce the exact report. Memory is bounded
by individual source rows and windows, rather than the whole corpus.

```bash
# DATABASE_URL is already supplied privately for the restored clone.
api/.venv/bin/python scripts/prepare_legacy_index_pack.py build \
  --pack /private/operator-directory/legacy-inputs.sqlite \
  --backup-sha256 BACKUP_SHA256 \
  --restored-database sclib_upgrade \
  --schema 0078_scientific_result_passage

# Resume the same interrupted input/producer, or verify a sealed pack.
api/.venv/bin/python scripts/prepare_legacy_index_pack.py build \
  --pack /private/operator-directory/legacy-inputs.sqlite \
  --backup-sha256 BACKUP_SHA256 \
  --restored-database sclib_upgrade \
  --schema 0078_scientific_result_passage --resume
api/.venv/bin/python scripts/prepare_legacy_index_pack.py verify \
  --pack /private/operator-directory/legacy-inputs.sqlite \
  --expected-sources EXPECTED_SOURCE_COUNT
```

The accepted restored database names are `sclib_upgrade` and explicitly named
`sclib_upgrade_*` clones. The tool never runs schema migrations. Logs contain
counts, hashes and static error codes; private text and driver diagnostics are
not emitted.

## Remaining production implementation

A sealed pack always reports `activation_eligible=false`. Remaining work is
durable embedding attempts/receipts, a typed legacy-snapshot admission contract,
scalable generation publication and activation, an isolated destination index,
complete expected-ID readback, full retrieval acceptance and rollback. The
existing 1,000-member SQL staging guard is unchanged. A single partition must
never become a substitute for the complete site.
