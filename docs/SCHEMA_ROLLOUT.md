# Schema admission and controlled research rollout

Status: EN02 local implementation. This document and the code do not authorize a
production migration, backfill, credential/role change, traffic switch or issue
closure. Real staging rehearsal, role provisioning and an approved cutover report
remain release gates.

## Execution boundary

The API never invokes a migration on restart. The container entrypoint runs
`python -m services.schema_lifecycle check`, which is read-only. The FastAPI
lifespan repeats admission before creating any background task, including when
ASGI is started directly without that entrypoint. A missing version table, an
older/newer revision, multiple heads, unavailable database or active migration
prevents application startup. No admission failure stamps or repairs the schema.

Admission reads the image's Alembic revision graph and accepts **exact head
equality only**. It does not certify the contents of every table, historical
migration bytes or source evidence. It is an initial-startup gate, not continuous
schema monitoring and not a substitute for readiness probes or release parity.

All online Alembic commands use the same nonblocking PostgreSQL advisory **session
lock**, acquired before Alembic begins its migration transaction. A second
upgrader fails immediately with an explicit retry-later error. It must restart
the complete job after the first job finishes; there is no hidden waiting queue
or automatic migration retry. Session scope is necessary because migration 0043
uses an autocommit block for its concurrent index. The connection uses `NullPool`;
closing it releases the lock on success, exceptions and process/session failure.
Read-only admission uses the matching shared transaction lock and fails while an
upgrader holds the exclusive lock.

This lock is cooperative: it covers the repository's online Alembic environment,
not arbitrary SQL executed by a privileged administrator, another migration
framework or an old image without the lock. Do not run those entrypoints in
parallel. Offline SQL rendering does not acquire a database lock; applying such
SQL manually is outside this deployment procedure.

## One-shot migration service and credentials

The `migration` Compose service is in the `tools` profile and never starts during
ordinary `compose up`, API restart or scaling. It executes only:

```text
python -m services.schema_lifecycle migrate
```

The command upgrades to the image's head and performs a read-only post-upgrade
check. It does not backfill research records, invoke ingestion or publish data.
Direct online Alembic commands share the lock, but the reviewed operational entry
point is the dedicated service, not `compose exec api alembic ...`.

Production uses the same verified immutable API image digest for the migration
job. It receives no API `.env`, GCP credential, application data mount, public
port or background process. Its database URL is read from:

```text
Host:      /etc/sclib/credentials/migration-database-url
Container: /run/secrets/sclib-migration-database-url (read-only)
```

An operator must provision a regular UTF-8 file containing one PostgreSQL URL,
readable only by the deployment administrator and the container's UID/GID as
required. The production service blanks `DATABASE_URL`; a missing/invalid secret
file has no fallback to the API credential. Do not put the migration credential
in the API `.env`, shell history, repository, CI output or cutover report. The
file parser is an operational input check, not a secret store or credential
rotation system.

Use a dedicated migration role, and remove schema ownership/DDL privileges from
the API runtime role after reviewing required runtime DML grants and default
privileges on newly created objects. No code in this batch automatically creates
roles, changes ownership or applies grants; the checker does not attest that
those privileges have already been separated. Existing production role grants
must be audited and provisioned before claiming least-privilege acceptance.

For local development, supply `SCLIB_MIGRATION_DATABASE_URL` only in the invoking
shell to the base Compose migration service. It is not automatically forwarded
to the API. Do not add it to the API's `.env`. Start `postgres redis`, explicitly
run `docker compose run --rm migration`, then start `api frontend`.

## Deployment failure gates

The deployment workflow preserves the existing SLO/error-budget, connection,
keyless-identity, backup, immutable digest and image-signature gates. The new
migration credential file must exist before changing the deployed checkout.
After dependency health and image verification:

1. Run the one-shot migration job with its separate credential.
2. Check the target schema using the new API image's **runtime** credential.
3. Only if both succeed, replace/start the API and frontend and wait for health.
4. Preserve existing local/public smoke and deployed-image identity checks.
5. Persist the signed image manifest only after every smoke check succeeds.

Failure in steps 1–2 prevents new API replacement. It does not imply the database
is unchanged: historical migration 0043 intentionally commits an autocommit
boundary. Earlier migrations may already be committed, and a failed concurrent
index may require restricted operator diagnosis. Inspect the exact database
revision/index state before retrying. Never automatically downgrade, stamp head
or delete evidence in response to a failed deployment.

The old API may still be running during additive schema changes. Consequently,
every expand migration must be reviewed and rehearsed against that exact old
reader/writer image before rollout. No zero-downtime or automatic service-rollback
guarantee is claimed here. New API health/smoke failure also requires an approved
recovery action; it is not silently treated as successful cutover.

## Expand → shadow → parity → read cutover → contract

1. **Expand:** Record source image/schema/data versions and backup/restore
   evidence. Apply additive, reviewed migration modules only. Preserve original
   source rows and immutable evidence/release bytes. Verify the existing reader
   can still operate against the expanded schema.
2. **Shadow load:** Use a separately reviewed bounded export and ML03 processing
   approval. Run dry-run verification and import in isolation. Keep canonical
   data and public/ML eligibility unchanged. Record all original occurrences,
   including duplicates, failed parsing and quarantines.
3. **Parity audit:** Compare source versus shadow inventories and representative
   results, conditions, units, evidence links and legacy API responses. Account
   for every input with reason-coded exclusions; an overall pass percentage
   cannot waive a scientific invariant. Capture exact code/schema/parser/policy
   versions, manifests, hashes, reviewer approvals and resource measurements.
4. **Read cutover:** Enable only the approved read model or release digest with a
   named owner, observation window and rollback triggers. A frozen or imported
   record is not automatically a reviewed training label. Validate material,
   Timeline, Discovery and export consumers against the same approved version.
5. **Read-model rollback:** Restore the previous approved read selection/feature
   flags or feed/release pointer; retain the expanded schema, raw evidence,
   append-only history and rejected proposal records. Recheck original-result
   counts and legacy API behavior. Record the reason and affected version IDs.
6. **Contract later:** Remove an obsolete projection or compatibility path only
   in a new reviewed migration after retention/recovery requirements and every
   consumer have been checked. Never amend a released migration's semantics.

With strict schema-head equality, restarting an **older image** against a newer
schema fails admission. Read-model rollback within the compatible image is the
default safe mechanism. If an older application image is necessary, first build
and rehearse an explicitly versioned compatibility change against the expanded
schema; do not disable admission or perform destructive down-migrations to make
the old image start.

## Released migration immutability

Keep every released `api/alembic/versions/*.py` file and its versioned schema
dependencies unchanged, including `research_schema_v1.py`,
`source_provenance_v1.py` and `research_import_v1.py`. Revision 0054 also freezes
`models/research_release_v1.py` and its SQL-generation dependency
`services/research_release_spec.py`, despite the latter's service-directory name.
Do not edit that wire specification in place when introducing future fields or
foreign keys; add a new versioned specification/schema module and migration.
Extend released modules using a new revision, never by redefining old semantics.
The current branch's new release schema follows this rule once released. Reviewers must compare
these files against the exact deployed/released Git commit and signed image;
changed historical bytes block rollout. This is a documented replacement/review
procedure, not an automated historical digest enforcement tool.

## Required cutover report

Before enabling a new read model, retain an internal report containing:

- Operator/reviewer identities, approval reference, timestamps and target scope.
- Source/target code commits, signed image digests, Alembic revisions and exact
  input/export/plan/release hashes; no credentials or restricted source text.
- Material, paper, raw-occurrence, distinct-occurrence and revision counts;
  inserted/reused/revised/quarantined/failed totals and reason-coded exclusions.
- Legacy/source preservation, data/consumer parity and scientific review results;
  unresolved exceptions and explicit release restrictions.
- Migration duration, lock contention, resource limits, application health,
  before/after read selections and acceptance/rollback thresholds.
- Backup identity and tested restore reference; exact read-model rollback steps,
  accountable operator and post-rollback verification results.

The local disposable migration/API tests are synthetic safety evidence, not that
report. Real old-schema staging upgrade, legacy preservation, released-snapshot
preservation, runtime-role grants, migration contention and read-model rollback
must still be rehearsed together before EN02 is closed.
