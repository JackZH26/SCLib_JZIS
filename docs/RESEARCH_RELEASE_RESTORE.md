# Scientific release recovery rehearsal

This runbook supports [EN06 / #71](https://github.com/JackZH26/SCLib_JZIS/issues/71).
It describes **fixed synthetic data in two independently owned disposable
instances**. It is not a production recovery command, a real audited-data release,
an external vector-service acceptance test, or approval to publish research data.

The earlier `scripts/restore_postgres_drill.sh` remains available for its existing
backup-manifest/core-table drill. Its backup inputs, retention and behavior are
unchanged. The new runner tests scientific dependencies in addition to SQL data.

## What is restored

The source is created from the current Alembic head, then populated with one
explicitly synthetic pending example and its dependency closure:

- Work, paper, sample, material state, claim and measurement/calculation events;
  unknown pressure stays unknown, and synthetic calculations remain unexecuted.
- Structure coordinate bytes, planned-run input/output bytes, source locator,
  policy and processing-review artifacts; every artifact is hashed and retained.
- A frozen research release, row pins, snapshot membership and ML-example input
  dependencies. Freezing is not scientific acceptance or training approval.
- Separate synthetic curator, reviewer and publisher accounts, immutable
  permission/publication records and a revoked role. The published payload is
  metadata only, never the restricted artifact bytes or scientific values.
- Two synthetic derived-fact chunks, immutable embedding completion receipts and
  retained float32 vector bytes, generation members, validation and activation
  records. No embedding provider is called; derived Facts stay support-ineligible.

The parent performs an actual custom-format `pg_dump`, copies the exact private
artifact capsule and independently pinned descriptor, and runs `pg_restore` into
a different empty owned database. The source instance's test-guard schema is
excluded; the target retains its own independently generated ownership marker.
No migration or test `drop_all/create_all` runs over the restored target.

## Running it

Use the repository's locked API development runtime. Run from the repository
root. The report's parent directory must already exist, with no symlink ancestor;
the report itself must **not** exist. Choose a fresh filename for every run.

Native example, with preinstalled local PostgreSQL and Redis:

```bash
api/.venv/bin/python scripts/run_research_restore_rehearsal.py \
  --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server \
  --report docs/reviews/2026-09-05/measurements/research-restore-new-run.json
```

Docker alternative, after explicitly preparing `postgres:16-alpine` and
`redis:7-alpine` in the local default Docker context:

```bash
api/.venv/bin/python scripts/run_research_restore_rehearsal.py \
  --backend docker \
  --report docs/reviews/2026-09-05/measurements/research-restore-new-run.json
```

The runner does not accept a database URL, an existing dump, a bucket, a command,
or an existing service to attach to. It strips inherited database/cloud/mail
settings, generates two fresh capability-bound PostgreSQL/Redis pairs, and
checks process/container ownership and database identity before operations.
Worker network connections are restricted to those owned loopback services.
The synthetic UTF-8 receipt path does not need a downloaded tokenizer cache.

The separate `research-release` job in `.github/workflows/restore-drill.yml`
configures the Docker version using the locked Python 3.11 runtime. The existing
core-table job is retained. Configuration and local native results do **not**
establish that the remote Linux job has run or passed.

## Success criteria and evidence

All stages must pass before a success receipt can be published:

1. Source migration and fixture creation succeed under their owned capabilities.
2. The exact manifest, complete artifact inventory and descriptor hashes survive
   transfer; missing, extra, symlinked, corrupt or replaced inputs are rejected.
3. Actual restore succeeds atomically with `--exit-on-error --single-transaction`.
4. The schema head matches, public constraints are validated and indexes are
   valid/ready. Every public table's row count and canonical content hash match the source
   snapshot, including audit, permission, source, release and generation rows.
   This is bounded synthetic-table equality, not an exhaustive DDL equivalence
   or cluster-role/secret recovery proof.
5. Frozen release pins and actual artifact bytes verify against the original
   manifest. Real ASGI API requests still deny anonymous, ungranted/admin-only
   and revoked users, while current research operators can use private reads.
   The independent-account metadata publication still excludes restricted data.
6. A fresh empty disposable vector resource is populated from the restored
   retained bytes, then fully observed and hydrated against the exact original
   generation and source/result identities. Repeating recovery performs zero
   upserts. The historical SQL validation/activation ledger is not refreshed.
7. Full target SQL and bundle contents remain unchanged after checks; the source
   SQL and files are rechecked independently and remain unchanged too.
8. Both owned service pairs and temporary data are cleaned up successfully, and
   executed source inputs remain byte-identical throughout the rehearsal.

The `research-restore-rehearsal/1.0.0` JSON receipt records per-stage durations,
actual PostgreSQL/Python/platform versions, dump/capsule/descriptor hashes,
identical SQL snapshot fingerprints, measured index results, input-file hashes,
base Git revision and dirty-worktree state. The final `report_sha256` is a
canonical-content checksum, **not** a digital signature or an authorization.

Validate an archived receipt without connecting to a service:

```bash
api/.venv/bin/python -c 'import sys; from pathlib import Path; sys.path.insert(0, "scripts"); from research_restore_contract import loads_report; loads_report(Path(sys.argv[1]).read_bytes()); print("Receipt structure and checksum verified")' \
  docs/reviews/2026-09-05/measurements/research-restore-new-run.json
```

This offline command validates the receipt's contract and checksum, not a new
restore or current worktree equality. Re-run the rehearsal for changed code.
The local report is created with mode `0600`; version control or CI upload can
change its distribution and does not preserve filesystem access permissions.
Only sanitized synthetic metadata belongs in retained reports, not dumps,
private logs, source text, artifact contents, passwords or live service URLs.

## Failures, limits and cleanup

Any failed stage, changed input, timeout, invalid identity or incomplete cleanup
prevents publication of a success report. Stage processes have a 180-second
deadline; dump/restore subprocesses have a 90-second deadline. SQL and capsule
inventories are deliberately bounded for this fixture, not full-corpus recovery.
Errors are sanitized rather than echoing SQL, credentials or private file text.

Normal exceptions and keyboard interruption attempt cleanup of both owned
instances. Cleanup validates directory identity and closes only resources owned
by this runner. If service shutdown cannot be confirmed, private temporary
directories are retained and the run fails. Never use broad cleanup commands or
stop a process merely because it uses PostgreSQL/Redis. Inspect the exact
capability, PID/container ownership and path identity before operator cleanup.
Uncatchable process termination or host failure may require that manual check.

Restricted-file mode and application access checks are not GCS/S3 ACL tests.
`--no-owner --no-acl` deliberately maps the dump into a fresh disposable database
role; production database roles, secrets and cloud IAM are outside this proof.
No backup is removed and no retention policy is changed.

## Remaining production and scientific acceptance gates

Keep production RPO, RTO, backup completeness, external vector restore and
scientific validity **unknown**, not zero, in this receipt. Its measured duration
is a synthetic local software rehearsal, not a production recovery objective.

Before closing EN06 or relying on production recovery, obtain an approved
operational plan covering:

1. One genuinely audited release and its authorized complete backup/retention
   inventory, including off-database artifacts and index reconstruction inputs.
2. Independently approved source rights, scientific review, ML admissibility and
   explicit permission to handle restricted material during the rehearsal.
3. Recovery of actual storage ACLs, roles/secrets, runtime/extensions and external
   vector resources in an isolated staging target; reconciliation at real scale.
4. Measured loss window and recovery duration from real backup timestamps and
   completed application validation, compared with owner-approved RPO/RTO.
5. Linked revision/PR, CI evidence, migration/compatibility review and a rollback
   runbook; the original production system and existing backups remain intact.

The fixed synthetic runner intentionally offers no shortcut to those operations.
