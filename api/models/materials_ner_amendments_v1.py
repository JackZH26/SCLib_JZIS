"""Append-only private editorial revisions; zero canonical scientific columns."""
import hashlib
from sqlalchemy import text
from models.materials_ner_proposals_v2 import VERSION as PARENT_VERSION, FINGERPRINT as PARENT_FINGERPRINT

VERSION = 'materials-proposal-amendment/1'
DDL = [
    """CREATE TABLE materials_ner_v1.amendments(
       id text PRIMARY KEY CHECK(id ~ '^[0-9a-f]{64}$'),
       parent_run_id text NOT NULL REFERENCES materials_ner_v1.runs(id),
       parent_packet_hash text NOT NULL CHECK(parent_packet_hash ~ '^[0-9a-f]{64}$'),
       payload jsonb NOT NULL, mapping jsonb NOT NULL,
       storage_hash text NOT NULL CHECK(storage_hash ~ '^[0-9a-f]{64}$'),
       created_at timestamptz NOT NULL DEFAULT now(),
       CHECK((payload->>'schema'='materials-proposal-amendment/1'
          AND payload->>'amendment_id'=id
          AND payload->>'parent_run_id'=parent_run_id
          AND payload->>'parent_packet_hash'=parent_packet_hash
          AND payload#>>'{author,kind}'='assistant'
          AND payload->'independent_review'='false'::jsonb
          AND payload->'scientific_acceptance'='false'::jsonb
          AND payload->'ml_training_eligible'='false'::jsonb
          AND payload->'canonical_writes'='false'::jsonb
          AND mapping->>'amendment_id'=id) IS TRUE))""",
    "CREATE INDEX ner_amendments_parent ON materials_ner_v1.amendments(parent_run_id,id)",
    """CREATE FUNCTION materials_ner_v1.amendment_immutable_v1()
       RETURNS trigger LANGUAGE plpgsql AS $$
       BEGIN RAISE EXCEPTION 'retained_editorial_amendment_is_immutable'
         USING ERRCODE='23514'; END $$""",
    """CREATE TRIGGER ner_amendment_no_rewrite BEFORE UPDATE OR DELETE
       ON materials_ner_v1.amendments FOR EACH ROW
       EXECUTE FUNCTION materials_ner_v1.amendment_immutable_v1()""",
    "REVOKE ALL ON materials_ner_v1.amendments FROM PUBLIC",
]
FINGERPRINT = hashlib.sha256((PARENT_FINGERPRINT + '\n' + '\n'.join(DDL)).encode()).hexdigest()


def upgrade(connection):
    connection.execute(text('SELECT pg_advisory_xact_lock(924601)'))
    versions = dict(connection.execute(text('SELECT version,fingerprint FROM materials_ner_v1.schema_version')).all())
    if versions.get(PARENT_VERSION) != PARENT_FINGERPRINT:
        raise ValueError('amendment_parent_schema_mismatch')
    if VERSION in versions:
        if versions[VERSION] != FINGERPRINT:
            raise ValueError('amendment_schema_fingerprint_mismatch')
        return
    for sql in DDL: connection.execute(text(sql))
    connection.execute(text('INSERT INTO materials_ner_v1.schema_version VALUES(:v,:f)'),dict(v=VERSION,f=FINGERPRINT))


def downgrade(connection):
    connection.execute(text('SELECT pg_advisory_xact_lock(924601)'))
    if connection.execute(text('SELECT EXISTS(SELECT 1 FROM materials_ner_v1.amendments)')).scalar_one():
        raise ValueError('retained_amendments_refuse_downgrade')
    connection.execute(text('DROP TABLE materials_ner_v1.amendments'))
    connection.execute(text('DROP FUNCTION materials_ner_v1.amendment_immutable_v1()'))
    connection.execute(text('DELETE FROM materials_ner_v1.schema_version WHERE version=:v'),dict(v=VERSION))
