# Disaster recovery

## Objectives and ownership

- PostgreSQL recovery point objective (RPO): 24 hours.
- PostgreSQL recovery time objective (RTO): 4 hours from incident declaration.
- Backup retention: at least 35 daily recovery points in a dedicated GCS bucket.
- Automated restore: monthly against a generated migrated database.
- Production-backup restore drill: quarterly in an isolated disposable container.

The on-call operator owns incident command and records timestamps, chosen backup,
checksum, restored row counts, final RPO/RTO, and follow-up actions. Restores must
never target the live `sclib` database during a drill.

## Backup contract

`scripts/backup_postgres.sh` creates a PostgreSQL custom-format dump and a JSON
manifest containing byte size, SHA-256, PostgreSQL version, source Git revision,
and creation time. It validates the archive with `pg_restore --list`, uploads
both objects, confirms remote size, and only then applies retention. Missing
configuration, upload, integrity, listing, or deletion failures fail the job.

Configure `/opt/SCLib_JZIS/.env.backup` with a bucket different from the
application data bucket:

```bash
SCLIB_BACKUP_BUCKET=sclib-jzis-backups
SCLIB_BACKUP_PREFIX=postgres
SCLIB_BACKUP_RETAIN_DAYS=35
SCLIB_BACKUP_CREDENTIALS_FILE=/etc/sclib/credentials/backup-external-account.json
SCLIB_BACKUP_SERVICE_ACCOUNT=sclib-backup@jzis-sclib.iam.gserviceaccount.com
```

Enable GCS bucket retention/versioning and use a dedicated backup identity with
write/list/delete only on this bucket. Alert when `backup.log` has no `DONE`
record within 26 hours or a `FAIL` record appears.

The backup script exports this external-account configuration only for its own
`gcloud` process. It validates the dedicated backup service-account target and
rotating subject token before accessing GCS; API or ingestion identities cannot
be reused as a backup credential.

## Quarterly production-backup drill

Download one recent matching pair without changing production data:

```bash
mkdir -p /var/tmp/sclib-restore-drill
gcloud storage cp \
  gs://sclib-jzis-backups/postgres/sclib-<timestamp>.dump \
  gs://sclib-jzis-backups/postgres/sclib-<timestamp>.manifest.json \
  /var/tmp/sclib-restore-drill/
bash scripts/restore_postgres_drill.sh \
  --dump /var/tmp/sclib-restore-drill/sclib-<timestamp>.dump \
  --manifest /var/tmp/sclib-restore-drill/sclib-<timestamp>.manifest.json \
  --report /var/tmp/sclib-restore-drill/report.json
```

The drill verifies the checksum before starting a temporary PostgreSQL 16
container, restores with `--single-transaction --exit-on-error`, and checks the
Alembic revision, core table counts, invalid indexes, and unvalidated
constraints. The container and anonymous volume are removed on exit. Store the
JSON report in the private operations evidence location for at least one year.

## Incident restore sequence

1. Freeze writes and record incident time; do not delete the failed database.
2. Select the newest backup strictly before the corruption/event time.
3. Run the isolated drill above and confirm its SHA-256 and report.
4. Provision a new PostgreSQL volume/instance and restore there; never overwrite
   the only copy of the old volume.
5. Apply forward-only migrations only if the selected application revision
   requires them, then run read-only API and row-count checks.
6. Switch the application database endpoint during an approved maintenance
   window, monitor errors, and retain the old volume for forensic review.
7. Record actual RPO/RTO and rotate any credential implicated in the incident.

Redis is a cache/quota dependency and is rebuilt empty after PostgreSQL is
healthy. Git provides application/configuration history; `.env` secrets are
recovered from the approved secret store, never from repository or backup logs.
